# ============================================================
#  threads/runner.py — 수집→판정→생성→분기→발행 조립
#  · 점수 분기가 이 시스템의 안전 경계다.
#    자동분 상한이 차면 고득점 건은 '폐기'가 아니라 '승인 큐'로 간다
#    (좋은 기회를 버리지 않으면서 무검수 발행량만 묶는다).
#  · run_once() 는 절대 예외를 밖으로 흘리지 않는다 — 수집·준비 단계
#    (harvest/ensure_channel/gate.screen/pub.login 등)가 통째로 터지든,
#    글 1건 처리 중 무엇이 터지든, 전부 errors 에 기록하고 정상적으로
#    dict 를 반환한다(리뷰 라운드 1 Finding 2 — 예전엔 for 루프 안만
#    이 보장을 받았다).
#  · 콘솔로 나가는 문자열 중 원글 본문·LLM 답글·예외 메시지가 섞인 것은
#    전부 threads.reply_writer._cp949_safe() 를 거친다(2차 sanitizer를
#    새로 만들지 않고 재사용) — cp949 콘솔에서 죽는 사고를 막기 위함.
# ============================================================
from __future__ import annotations

import json
import random
import time

import config
import db
from threads import gate, harvester, reply_writer
from threads.publisher import ThreadsPublisher
from threads.reply_writer import _cp949_safe


def ensure_channel(account: str) -> int:
    """threads 채널 1행을 보장한다(멱등).

    채널 행을 두는 이유 — posts/creatives 가 channel_id 를 요구하고,
    대시보드 집계가 채널 단위로 돌기 때문. 코드 수정 없이 그대로 잡힌다.

    ⚠ 리뷰 라운드 1 Finding 1: db.add_channel() 은 `INSERT OR IGNORE`
    라서, 이미 같은 (platform, target_ref) 행이 있으면 아무것도 삽입하지
    않고 cur.lastrowid 로 0 을 돌려준다(sqlite 사양 — 실제로 삽입한 행이
    없으므로) — 이걸 그대로 channel_id 로 반환하면, 두 번째 회차부터
    creatives.channel_id=0 이 돼 FK 위반이 나고(per-post try/except 가
    삼켜서 "실패"로만 기록되고), 그 이후 회차는 전부 아무것도 발행하지
    못하면서 겉보기 stats 는 계속 그럴듯하게 나온다(실측: PASS 2 부터
    'FOREIGN KEY constraint failed'). db.py 는 수정 금지 대상이므로,
    여기서 _ensure_campaign() 과 같은 SELECT-then-insert 패턴으로
    직접 멱등성을 보장한다."""
    ref = f"@{account}" if account and not account.startswith("@") else (account or "@threads")
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM channels WHERE platform=? AND target_ref=?",
            ("threads", ref)).fetchone()
        if row:
            return row["id"]
    return db.add_channel("threads", ref, name=f"쓰레드 {ref}", audience="consumer")


def _ensure_campaign() -> int:
    """'쓰레드 답글' 상시 캠페인 1건(멱등)."""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM campaigns WHERE title=? LIMIT 1", ("쓰레드 답글",)).fetchone()
        if row:
            return row["id"]
    return db.add_campaign("쓰레드 답글", goal="유입", product=config.PROFILE_KEY)


def run_once(account: str = "", profile: dict = None, dry_run: bool = None) -> dict:
    """1회차 실행. 반환값은 대시보드·로그가 그대로 쓴다."""
    account = account or config.THREADS_ACCOUNT
    tcfg = gate.threads_config(profile if profile is not None else config.PROFILE)
    if dry_run is None:
        dry_run = not (config.THREADS_ENABLED and not config.GLOBAL_DRY_RUN)

    stats = {"harvested": 0, "passed": 0, "auto_published": 0,
             "queued": 0, "dropped": 0, "deferred": 0, "errors": [],
             # harvester.py 의 파싱 손실 신호를 그대로 노출한다(항목 2) —
             # 이 두 값의 소비자가 지금까지 없었다. harvest_ambiguous 는
             # "글은 있는데 카드 자신의 것으로 못 좁힌" 실손실이고,
             # harvest_unpaired 는 광고/UI 카드도 섞이므로 순손실로 보면
             # 안 된다(harvester.last_no_pairing_count() 독스트링 참고) —
             # 그래서 이름에도 '손실'이라는 단정적 표현을 피했다.
             "harvest_ambiguous": 0, "harvest_unpaired": 0}

    # ── 준비 1단계: 수집. 아직 브라우저(pub)를 안 띄웠으므로 여기서
    # 뭐가 터져도 leak 걱정은 없지만, run_once() 자체는 이 단계에서도
    # 절대 raise 하면 안 된다(리뷰 라운드 1 Finding 2) — 스케줄러가
    # 이 함수 자체를 못 믿게 되면 회차가 통째로 멈춘다.
    try:
        posts = harvester.harvest(account, config.THREADS_HARVEST_LIMIT)
    except Exception as e:
        stats["errors"].append(_cp949_safe(f"수집 실패({type(e).__name__}): {e}"))
        _log_summary(stats)
        return stats

    stats["harvested"] = len(posts)
    # parse_feed() 는 harvest() 내부에서 스크롤마다 여러 번 불리고, 이 두
    # 카운터는 '가장 최근 parse_feed() 호출' 분만 반영한다(harvester.py
    # 자신의 문서화된 동작 — 누적 아님). harvester.py 는 이전 태스크
    # 산출물이라 이 동작 자체를 바꾸지 않고 있는 그대로 노출만 한다.
    stats["harvest_ambiguous"] = harvester.last_ambiguous_count()
    stats["harvest_unpaired"] = harvester.last_no_pairing_count()
    if not posts:
        # 수집 0건은 오류가 아니다. 다만 '진짜 0건'과 '파싱이 통째로
        # 깨져서 0건'은 이 요약 로그가 없으면 겉보기에 똑같다(항목 2) —
        # harvest_ambiguous/harvest_unpaired 가 카드 수만큼 치솟았는데
        # harvested 만 0이면 그건 파싱 붕괴 신호로 읽어야 한다.
        _log_summary(stats)
        return stats

    # 신선도 — 오래된 글의 답글은 아무도 보지 않는다.
    posts = [p for p in posts if _fresh_enough(p)]

    # ── 준비 2단계: 채널/캠페인 확보 + 게이트 판정. 역시 pub(브라우저)
    # 이전이라 leak 걱정은 없다 — 리뷰 라운드 1 Finding 2 가 실측한
    # 대표 사례: gate.screen() 내부 _load_prompt() 가 prompts/screen.txt
    # 를 못 읽으면(경로 오류 등) 여기서 예외가 그대로 터진다.
    try:
        channel_id = ensure_channel(account)
        campaign_id = _ensure_campaign()
        verdicts = gate.screen(posts, tcfg)
    except Exception as e:
        stats["errors"].append(_cp949_safe(f"준비 단계 실패({type(e).__name__}): {e}"))
        _log_summary(stats)
        return stats

    # ── 여기부터 pub(브라우저)를 만든다. 이 지점 이후로는 함수를 어떤
    # 경로로 빠져나가든(생성 자체가 실패하는 경우까지 포함) pub.quit()
    # 이 존재하는 객체에 대해서만 반드시 불려야 한다 — 리뷰 라운드 1
    # Finding 2: 예전엔 try/finally 가 for 루프에만 걸려 있어서
    # pub.login() 실패(예: 크롬 업데이트 이후 chromedriver 버전 불일치)
    # 가 quit() 없이 그대로 raise 됐다(=실행 모드에서 크롬 프로세스 leak).
    # 리뷰 라운드 2 Finding 2: ThreadsPublisher(account) 생성 자체가
    # try 밖에 있어서, 생성자가 터지면(오늘은 I/O 가 없어 가능성은
    # 낮지만 앞으로도 그럴 거라는 보장은 없다) 여전히 raise 가 새어
    # 나갔다 — pub 를 None 으로 시작해 try 안에서 생성하고, finally
    # 에서는 pub 이 실제로 만들어졌을 때만 quit() 을 부른다.
    pub = None
    try:
        pub = ThreadsPublisher(account)
        if not dry_run:
            pub.login()

        # 오늘 이미 실제로 나간 자동분(과거 회차 포함, 이 회차 시작 시점
        # 스냅샷). dry-run 은 posts.status 를 'posted' 로 남기지 않으므로
        # (_do_reply() 를 타지 않음) db.threads_replies_today(auto_only=True)
        # 를 이 회차 중간에 다시 조회해도 이 회차 안에서 이미 자동발행
        # '하기로 한' 건수가 반영되지 않는다 — pub._rate_ok() 만 믿으면
        # 한 회차 안에서 자동분 상한이 전혀 작동하지 않는다(실측: 상한
        # 1을 줘도 dry-run 한 회차에서 2건이 샜다). 그래서 이 회차
        # 자체의 소진분은 auto_sent_this_pass 로 따로 센다. pub._rate_
        # ok() 는 실발행일 때 DB 진실을 한 번 더 교차 확인하는 이중
        # 방어선으로 그대로 남긴다.
        auto_today_base = db.threads_replies_today(auto_only=True)
        auto_sent_this_pass = 0
        # 리뷰 라운드 1 Finding 3: 같은 작성자의 두 번째 글이 이번
        # 회차 안에서 또 걸리는 경우를 막는다. threads_target_upsert()
        # 는 post_url 로 키를 잡으므로 같은 작성자의 다른 글은 완전히
        # 새 target 이 되고, threads_author_replied_since() 는
        # replied_at(=실제 발행 성공 시에만 찍힘, 항목 3 참고) 만 보므로
        # "이번 회차에서 이미 답글을 준(자동이든 승인 큐행이든)" 작성자를
        # 놓친다 — 자동 상한을 auto_today_base+auto_sent_this_pass 로
        # 합쳐 본 것과 같은 패턴으로, DB 확인과 별개로 메모리에 따로
        # 추적한다.
        authors_replied_this_pass = set()

        # 리뷰 라운드 2 Finding 3: authors_replied_this_pass 는 이번
        # 회차 지역 변수라 회차를 넘어서는 기억이 없다. 이전 회차에서
        # 승인 큐로 간 답글은 link_creative() 를 안 부르므로(항목 3)
        # replied_at 도 안 찍힌다 — 그 결과 "1회차 큐잉 → 2회차 자동
        # 발행"이 같은 작성자에게 실제로 일어날 수 있었다(리뷰어 실측:
        # 두 번의 평범한 스케줄 회차만으로 재현됨). db.py 는 수정 금지
        # 대상이므로, 이미 있는 db.list_pending_approvals() 를 재사용
        # 해 '아직 승인 안 된' 소재의 작성자를 모은다 — 쓰레드 답글
        # creative 는 copy_json 에 target_author 키를 담고(runner.py
        # 의 add_creative 호출부), 이 코드베이스의 다른 소재 종류는
        # 이 키를 쓰지 않으므로 키 존재 여부만으로 '쓰레드 답글인가'를
        # 구분할 수 있다. 행 하나가 깨져 있어도(JSON 파싱 실패·
        # copy_json 이 dict 가 아님 등) 그 행만 건너뛰고 회차는 계속
        # 간다.
        authors_pending_approval = set()
        for row in db.list_pending_approvals():
            try:
                cap = json.loads(row.get("copy_json") or "{}")
            except (TypeError, ValueError):
                continue
            author = cap.get("target_author") if isinstance(cap, dict) else None
            if author:
                authors_pending_approval.add(author)

        for post, verdict in zip(posts, verdicts):
            try:
                target_id = db.threads_target_upsert(post, config.PROFILE_KEY)

                if not verdict.passed:
                    if verdict.retryable:
                        # 판정을 못 한 것뿐이다. pending 으로 남겨 다음
                        # 회차에 다시 본다 — dropped 로 찍으면 할당량이
                        # 떨어진 회차의 수집분이 영영 사라진다.
                        stats["deferred"] += 1
                    else:
                        db.threads_target_verdict(target_id, verdict.score,
                                                  "dropped", verdict.reason)
                        stats["dropped"] += 1
                    continue

                # 작성자 쿨다운은 반드시 답글 생성(LLM 호출)보다 먼저 본다 —
                # 이미 버릴 답글에 LLM 할당량을 쓰지 않기 위함이다. 세 가지
                # 출처를 순서대로 본다(싼 것부터 — 메모리 조회 두 개를 먼저
                # 봐서 걸리면 DB 왕복 자체를 아낀다): ① 이번 회차 안에서
                # 이미 답글을 준 작성자, ② 이전 회차에서 승인 대기 중인
                # (아직 사람이 처리 안 한) 작성자(리뷰 라운드 2 Finding 3),
                # ③ DB 에 기록된 실제 발행 쿨다운. 운영자가 어느 경로로
                # 막혔는지 구분할 수 있게 사유를 다르게 남긴다.
                if post.author in authors_replied_this_pass:
                    cooldown_reason = "이번 회차 내 동일 작성자 중복"
                elif post.author in authors_pending_approval:
                    cooldown_reason = "승인 대기 중인 동일 작성자 글 있음"
                elif db.threads_author_replied_since(
                        post.author, config.THREADS_AUTHOR_COOLDOWN_DAYS):
                    cooldown_reason = f"작성자 쿨다운({config.THREADS_AUTHOR_COOLDOWN_DAYS}일)"
                else:
                    cooldown_reason = None

                if cooldown_reason:
                    db.threads_target_verdict(
                        target_id, verdict.score, "dropped", cooldown_reason)
                    stats["dropped"] += 1
                    continue

                try:
                    reply = reply_writer.write(post, verdict, tcfg)
                except Exception as e:
                    db.threads_target_verdict(target_id, verdict.score, "dropped",
                                              f"답글 생성 실패: {e}")
                    stats["dropped"] += 1
                    stats["errors"].append(_cp949_safe(f"{post.url}: {e}"))
                    continue

                # 이 작성자에게는 이번 회차 안에서 더 이상 답글을 만들지
                # 않는다 — 자동/큐 어느 쪽으로 갈지 정해지기 전에 미리
                # 막아야, "1건 자동 + 1건 큐"처럼 두 갈래로 새는 것도
                # 함께 막힌다(Finding 3 이 지적한 두 번째 증상).
                authors_replied_this_pass.add(post.author)

                # passed 는 '판정 통과 + 답글 생성 성공'까지 온 건수다.
                # 이후 auto/queue 분기나 DB 기록에서 실패해도(아래 outer
                # except 가 잡는다) 이 카운트는 되돌리지 않는다 — "여기까지는
                # 정상적으로 왔다"는 사실 자체를 기록하는 값이기 때문이다.
                stats["passed"] += 1
                db.threads_target_verdict(target_id, verdict.score, "passed", verdict.reason)

                creative_id = db.add_creative(campaign_id, channel_id, {
                    "reply": reply.text,
                    "target_url": post.url,
                    "target_author": post.author,
                    "target_excerpt": (post.text or "")[:120],
                    "score": verdict.score,
                    "angle": verdict.angle,
                    "profile_key": config.PROFILE_KEY,
                    "brand": tcfg.get("brand", ""),
                    "guard_notes": reply.guard_notes,
                }, kind="threads_reply")

                # ── 점수 분기(이 시스템의 안전 경계) ──
                auto_room_left = ((auto_today_base + auto_sent_this_pass)
                                  < config.THREADS_AUTO_DAILY_LIMIT)
                auto_ok = (verdict.score >= config.THREADS_AUTO_THRESHOLD
                           and auto_room_left
                           and pub._rate_ok(auto=True))
                if auto_ok:
                    res = pub.reply(post.url, reply.text, dry_run=dry_run, auto=True)
                    status = "dry" if res.dry_run else ("posted" if res.ok else "failed")
                    post_id = db.record_post(creative_id, channel_id, status=status)
                    db.update_post_status(post_id, status,
                                          perm_url=res.perm_url, error=res.error)
                    if res.ok:
                        auto_sent_this_pass += 1
                        stats["auto_published"] += 1
                        # ── 항목 3 + 리뷰 라운드 1 Finding 4: '실제로
                        # 게시된 경우'에만 쿨다운 시계(link_creative)와
                        # 자동분 마커(_mark_auto)를 남긴다. dry-run
                        # 성공도 res.ok=True 이므로, 조건 없이 이 둘을
                        # 부르면 (a) 미리보기/개발 중 반복 dry-run 만으로
                        # 실제로는 한 번도 답글을 달지 않은 작성자가
                        # 쿨다운에 걸리고(항목 3), (b) metrics_json 의
                        # auto 마커만 보고 자동분을 세는 미래 쿼리가
                        # dry-run 을 실제 발행으로 오인한다(Finding 4).
                        # 큐 분기(else 절)에서는 애초에 이 둘을 걸지
                        # 않으므로 그 사고는 이미 피했고, 여기서는
                        # dry_run 여부까지 한 번 더 좁혀 '실제로 게시된
                        # 경우'에만 두 표식이 남는다.
                        if not dry_run:
                            db.threads_target_link_creative(target_id, creative_id)
                            _mark_auto(post_id)
                    else:
                        stats["errors"].append(
                            _cp949_safe(f"{post.url}: {res.error}"))
                    if not dry_run:
                        time.sleep(random.randint(config.THREADS_REPLY_INTERVAL_MIN,
                                                  config.THREADS_REPLY_INTERVAL_MAX))
                else:
                    # 자동 상한이 찼거나 점수가 임계 미만 — 좋은 기회를
                    # 버리지 않고 승인 큐로.
                    db.enqueue_approval(creative_id)
                    stats["queued"] += 1
            except Exception as e:
                # 이 글 하나가 어디서 죽든(예상 못 한 DB 락·네트워크 등)
                # 회차 전체를 끌고 내려가지 않는다 — 기록하고 다음 글로.
                stats["errors"].append(
                    _cp949_safe(f"{getattr(post, 'url', '?')}: {e}"))
    except Exception as e:
        # ThreadsPublisher(account) 생성·pub.login()·db.threads_
        # replies_today() 등 루프 진입 전 준비 자체가 통째로 실패한
        # 경우 — 이번 회차는 글을 하나도 처리하지 못했지만 run_once()
        # 는 여전히 raise 하지 않는다(Finding 2).
        stats["errors"].append(
            _cp949_safe(f"발행 준비 실패({type(e).__name__}): {e}"))
    finally:
        # 이 지점 위 어디서 무엇이 터지든(로그인 실패 포함) 브라우저
        # 프로세스를 반드시 정리한다 — 단, pub 이 실제로 만들어졌을
        # 때만(리뷰 라운드 2 Finding 2: 생성자 자체가 실패하면 pub 은
        # 여전히 None 이고, None.quit() 을 부르면 AttributeError 로
        # 새로운 실패가 하나 더 생긴다).
        if pub is not None:
            pub.quit()

    _log_summary(stats)
    return stats


def _fresh_enough(post) -> bool:
    """THREADS_POST_MAX_AGE_MIN 이내 글만. 시각을 못 읽으면 통과시킨다
    (읽기 실패로 전부 버리는 쪽이 더 나쁘다)."""
    import datetime as dt
    if not post.posted_at:
        return True
    try:
        ts = dt.datetime.fromisoformat(post.posted_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    age_min = (dt.datetime.now(ts.tzinfo) - ts).total_seconds() / 60
    return age_min <= config.THREADS_POST_MAX_AGE_MIN


def _mark_auto(post_id: int):
    """자동 발행분 표시. db.threads_replies_today(auto_only=True) 가 이걸 센다."""
    with db.get_conn() as conn:
        conn.execute("UPDATE posts SET metrics_json=? WHERE id=?",
                     (json.dumps({"auto": True}), post_id))


def _log_summary(stats: dict):
    """회차 결과 요약을 콘솔에 남긴다. 이 함수에 들어오는 값은 전부 정수
    아니면 고정 한국어 템플릿이라 원칙적으로 cp949 로 못 찍을 문자가
    없지만, 이 모듈의 다른 print 들과 같은 관례를 지켜 나중에 이 함수에
    문자열 필드(예: 예외 메시지)가 섞여도 안전하게 유지한다."""
    print(_cp949_safe(
        f"[threads:runner] 수집 {stats['harvested']}건 "
        f"(파싱 모호 {stats['harvest_ambiguous']}건 "
        f"· 짝 없음(광고/UI 카드 포함, 정상 범위일 수 있음) "
        f"{stats['harvest_unpaired']}건) "
        f"→ 통과 {stats['passed']} · 자동발행 {stats['auto_published']} "
        f"· 승인대기 {stats['queued']} · 폐기 {stats['dropped']} "
        f"· 재판정대기 {stats['deferred']}"
    ))


if __name__ == "__main__":
    print(run_once(dry_run=True))
