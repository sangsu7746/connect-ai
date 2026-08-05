# ============================================================
#  tests/test_orchestrator_threads.py — Task 7 승인→발행 배선 검증
#  · 브라우저를 전혀 띄우지 않는다. orchestrator.get_adapter() 를
#    호출 기록만 남기는 대역(_RecordingAdapter)으로 바꿔치기해
#    publish_creative()/approve_and_publish() 의 "무엇을 어디로
#    보내는가" 분기만 검증한다(threads/publisher.py 나 selenium은
#    이미 Task 5 테스트가 커버한다 — 여기서 다시 보지 않는다).
#  · 디스패치 "On testing" 절이 요구하는 3가지를 핵심으로 삼는다:
#      1) threads 분기가 band/facebook/kakao 를 안 건드리는가
#      2) 승인된 답글이 원글 URL 로 답글 텍스트를(빈 문자열이 아니라)
#         내보내는가
#      3) 중복 승인 방지 관문이 threads 경로에서도 그대로 작동하는가
#    + 요구사항 4(승인 경로에서도 실발행 성공 시에만 작성자 쿨다운
#      시계가 시작되는가)
# ============================================================
import time

import pytest

import config
import orchestrator
from channels.base import PostResult


class _RecordingAdapter:
    """실제 브라우저 대신 orchestrator 가 어댑터에 무엇을 넘기는지만
    기록한다. ensure_login()/BaseAdapter._rate_ok() 가 기대하는 속성을
    전부 미리 채워 실발행 경로의 안전장치들이 '준비됨'으로 통과하게
    한다 — 이 테스트가 보려는 건 그 장치들 자체(이미 다른 곳에서
    검증됨)가 아니라 orchestrator 가 만든 target/text 다."""

    def __init__(self, platform="threads", **kw):
        self.platform = platform
        self.kw = kw
        self.calls = []
        self.account_id = kw.get("account_id", "")
        self._logged_in = True
        self._login_at = time.time()   # ensure_login() 의 재확인 주기를 피한다
        self._current_post_id = None

    def login(self, cred=None):
        self._logged_in = True
        return True

    def _rate_ok(self, channel_id=None):
        return True

    def _rate_reason(self, channel_id=None):
        return ""

    def post(self, target, text, image_path=None, dry_run=True):
        self.calls.append({"target": target, "text": text,
                           "image_path": image_path, "dry_run": dry_run})
        return PostResult(ok=True, perm_url="https://example.test/ok", dry_run=dry_run)


def _make_threads_reply(reply="저도 그 고민 했어요", target_url="https://www.threads.net/@a/post/1",
                        target_author="@a"):
    import db
    ch = db.add_channel("threads", "@tester", name="쓰레드 @tester", audience="consumer")
    camp = db.add_campaign("쓰레드 답글")
    cid = db.add_creative(camp, ch, {
        "reply": reply,
        "target_url": target_url,
        "target_author": target_author,
        "target_excerpt": "셀카 보정 앱 뭐 쓰세요?",
        "score": 91,
        "profile_key": "photomagic",
        "brand": "PhotoMagic",
    }, kind="threads_reply")
    aid = db.enqueue_approval(cid)
    return ch, camp, cid, aid


def _make_band_creative(caption):
    import db
    ch = db.add_channel("band", "https://band.us/band/1", name="테스트밴드")
    camp = db.add_campaign("일반 캠페인")
    cid = db.add_creative(camp, ch, caption)
    aid = db.enqueue_approval(cid)
    return ch, camp, cid, aid


def _no_wait(monkeypatch):
    """실발행 경로의 hours_ok/_space_out 이 테스트 실행 시각·환경에
    따라 흔들리거나 대기하지 않도록 고정한다."""
    monkeypatch.setattr(config, "GLOBAL_DRY_RUN", False)
    monkeypatch.setattr(config, "POST_HOURS_START", 0)
    monkeypatch.setattr(config, "POST_HOURS_END", 0)   # start==end → 종일 허용
    monkeypatch.setattr(config, "POST_INTERVAL_MIN", 0)
    monkeypatch.setattr(config, "POST_INTERVAL_MAX", 0)


# ── 1) threads 분기가 나머지 세 채널을 건드리지 않는가 ─────────────
def test_dry_run_band_still_uses_caption_text_and_target_ref(temp_db, monkeypatch):
    """band(및 facebook/kakao 와 같은 코드 경로)는 threads 분기 추가 이전과
    바이트 단위로 같은 인자로 adapter.post() 를 불러야 한다."""
    fake = _RecordingAdapter(platform="band")
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    caption = {"headline": "제목", "body": "본문", "cta": "문의하기"}
    _, _, cid, _ = _make_band_creative(caption)

    res = orchestrator.publish_creative(cid, dry_run=True)

    assert res.ok is True
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["target"] == "https://band.us/band/1"          # target_ref 그대로
    assert call["text"] == orchestrator._caption_text(caption)  # 기존 캡션 조립 그대로


# ── 2) 승인된 답글이 원글 URL 로 답글 텍스트를 내보내는가 ──────────
def test_dry_run_threads_reply_routes_reply_text_and_post_url(temp_db, monkeypatch):
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    _, _, cid, _ = _make_threads_reply(reply="저도 그 고민 했어요",
                                       target_url="https://www.threads.net/@a/post/1")

    res = orchestrator.publish_creative(cid, dry_run=True)

    assert res.ok is True
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["text"] == "저도 그 고민 했어요"                       # reply 그대로(빈 문자열 아님)
    assert call["target"] == "https://www.threads.net/@a/post/1"     # 원글 URL
    assert call["target"] != "@tester"                                # 채널 핸들이 아니다


def test_real_publish_threads_reply_sends_to_post_url_and_starts_cooldown(temp_db, monkeypatch):
    """승인 → 실발행 전체 경로. 요구사항 4: 실발행이 진짜 성공했을 때만
    threads_targets.replied_at 이 찍혀 작성자 쿨다운이 시작돼야 한다."""
    import db
    from threads.models import RawPost
    _no_wait(monkeypatch)

    db.threads_target_upsert(
        RawPost(url="https://www.threads.net/@a/post/1", author="@a",
               text="셀카 보정 뭐 쓰세요?", posted_at="2026-08-03T10:00:00"),
        "photomagic")
    assert db.threads_author_replied_since("@a", 30) is False   # 전제조건

    _, _, cid, aid = _make_threads_reply(reply="저도 그 고민 했어요",
                                         target_url="https://www.threads.net/@a/post/1",
                                         target_author="@a")
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)

    res = orchestrator.approve_and_publish(aid, dry_run=False)

    assert res.ok is True
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["text"] == "저도 그 고민 했어요"
    assert call["target"] == "https://www.threads.net/@a/post/1"
    assert call["dry_run"] is False
    assert db.threads_author_replied_since("@a", 30) is True     # 쿨다운 시작됨


def test_dry_run_threads_approval_does_not_start_cooldown(temp_db, monkeypatch):
    """dry-run 은 '성공'으로 보여도 실제로 아무 것도 나가지 않았다 —
    threads/runner.py 가 자동발행에서 이미 지키는 규칙(디스패치 항목 4의
    전제)이 승인 경로에서도 지켜져야 한다."""
    import db
    from threads.models import RawPost

    db.threads_target_upsert(
        RawPost(url="https://www.threads.net/@a/post/1", author="@a",
               text="셀카 보정 뭐 쓰세요?", posted_at="2026-08-03T10:00:00"),
        "photomagic")

    _, _, cid, aid = _make_threads_reply(target_url="https://www.threads.net/@a/post/1",
                                         target_author="@a")
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)

    res = orchestrator.approve_and_publish(aid, dry_run=True)

    assert res.ok is True
    assert res.dry_run is True
    assert db.threads_author_replied_since("@a", 30) is False


# ── 3) 중복 승인 방지 관문이 threads 경로에서도 유지되는가 ─────────
def test_duplicate_approval_guard_still_fires_on_threads_path(temp_db, monkeypatch):
    _no_wait(monkeypatch)
    _, _, cid, aid = _make_threads_reply()
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)

    first = orchestrator.approve_and_publish(aid, dry_run=False)
    second = orchestrator.approve_and_publish(aid, dry_run=False)

    assert first.ok is True
    assert second.ok is False
    assert second.blocked is True
    assert "이미 처리된" in (second.error or "")
    assert len(fake.calls) == 1   # 두 번째 호출은 adapter.post() 까지 가지 않았다


# ── 4) next_free_slot() 이 이미 예약된 건을 실제로 보는가 ──────────
def test_next_free_slot_sees_already_scheduled_jobs(temp_db, monkeypatch):
    """실측(2026-08-05): scheduler.schedule_publish() 는 job id 를
    f"pub-{creative_id}" 로 만드는데, next_free_slot() 은 "publish:"
    접두사(콜론)를 찾고 있었다 — 하이픈/콜론이 달라 기존 예약을 단 하나도
    못 찾았다. 그 결과 승인 6건을 30초 간격으로 연달아 누르면 예약도
    30초 간격으로 겹쳐 잡혔다(의도는 THREADS_REPLY_INTERVAL 180~600초).
    발행이 _PUBLISH_LOCK 을 쥔 채 진행되므로, 겹친 예약들이 락 하나를
    놓고 줄줄이 대기하며 각 건의 스페이싱(최대 600초)+실제 게시 시간만큼씩
    밀렸다 - '멈춘 것'이 아니라 '한 시간 넘게 순서를 기다리는 중'이었다.

    이 테스트는 실제 scheduler.get_scheduler() 에 진짜 job 을 하나 등록해
    두고, next_free_slot() 이 그 job 의 next_run_time 을 실제로 보고
    간격을 벌리는지 확인한다 — job id 형식이 다시 어긋나면 이 테스트가
    실패해야 한다."""
    import datetime as dt
    monkeypatch.setattr(orchestrator, "_LAST_RESERVED_AT", {})  # 테스트 간 오염 방지
    import scheduler as sched_mod

    monkeypatch.setattr(config, "THREADS_REPLY_INTERVAL_MIN", 300)
    monkeypatch.setattr(config, "THREADS_REPLY_INTERVAL_MAX", 300)  # 고정값 - 흔들림 없이 검증

    _, _, cid, _ = _make_threads_reply()

    sched_mod.start()          # next_run_time 은 스케줄러가 돈 뒤에만 채워진다
    s = sched_mod.get_scheduler()
    try:
        # scheduler.schedule_publish() 와 동일한 id 형식으로 실제 job 등록.
        already_at = dt.datetime.now() + dt.timedelta(seconds=50)
        s.add_job(sched_mod._publish_job, "date", run_date=already_at,
                  args=[cid, True], id=f"pub-{cid}", replace_existing=True)

        slot = orchestrator.next_free_slot("threads")

        # 이미 예약된 job 이후로 최소 300초는 더 벌어져야 한다.
        assert slot >= already_at.replace(tzinfo=None) + dt.timedelta(seconds=300)
    finally:
        try:
            s.remove_job(f"pub-{cid}")
        except Exception:
            pass


def test_next_free_slot_survives_a_job_that_already_fired_and_vanished(temp_db, monkeypatch):
    """실측(2026-08-05)에서 실제로 터진 경쟁 상태를 재현한다.

    최근 실제 발행이 오래전이면 첫 슬롯은 '거의 지금'으로 계산되는 게
    맞다. 그런데 '거의 지금'으로 잡힌 job 은 APScheduler 가 즉시 실행
    하고, date 트리거는 1회성이라 실행되는 순간 스토어에서 사라진다 -
    직접 확인: 예약 0.57초 뒤 get_jobs() 가 이미 빈 목록이었다. db.
    last_post_time() 은 그 job 이 '실제로 posted' 에 도달해야만 갱신
    되는데, 그건 브라우저 발행이 끝나는 60~90초 뒤다. 그 사이 두 번째
    호출은 스토어에서도 last_post_time 에서도 첫 job 을 못 보고, 똑같이
    '거의 지금'을 받는다 - 승인 6건이 전부 같은 시각에 예약돼 락 하나를
    놓고 줄줄이 대기한 실제 사고가 이렇게 났다.

    이 테스트는 스케줄러/DB 를 건드리지 않고 재현한다: 스토어가 비어
    있고(첫 job 이 이미 사라진 상태) db.last_post_time 도 옛날 값을
    주는 상황에서, 직전 next_free_slot() 호출 자체가 두 번째 호출을
    밀어내야 한다."""
    monkeypatch.setattr(config, "THREADS_REPLY_INTERVAL_MIN", 300)
    monkeypatch.setattr(orchestrator, "_LAST_RESERVED_AT", {})  # 테스트 간 오염 방지
    monkeypatch.setattr(config, "THREADS_REPLY_INTERVAL_MAX", 300)
    monkeypatch.setattr("db.last_post_time", lambda platform=None: None)  # 최근 발행 기록 없음
    monkeypatch.setattr("scheduler.get_scheduler",
                        lambda: type("S", (), {"get_jobs": lambda self: []})())

    slot1 = orchestrator.next_free_slot("threads")
    slot2 = orchestrator.next_free_slot("threads")

    assert slot2 >= slot1 + __import__("datetime").timedelta(seconds=300)


def test_next_free_slot_ignores_jobs_for_other_platforms(temp_db, monkeypatch):
    """다른 플랫폼(band) 앞으로 예약된 job 은 threads 의 슬롯 계산에
    영향을 주면 안 된다 - 서로 다른 계정·채널이 서로를 기다리게 만드는
    건 간격 장치의 취지(그 계정이 기계처럼 안 보이게)와 무관하다."""
    import datetime as dt
    import scheduler as sched_mod

    monkeypatch.setattr(orchestrator, "_LAST_RESERVED_AT", {})  # 테스트 간 오염 방지
    monkeypatch.setattr(config, "POST_INTERVAL_MIN", 300)
    monkeypatch.setattr(config, "POST_INTERVAL_MAX", 300)

    _, _, band_cid, _ = _make_band_creative(
        {"headline": "제목", "body": "본문", "cta": "문의"})

    sched_mod.start()
    s = sched_mod.get_scheduler()
    try:
        soon = dt.datetime.now() + dt.timedelta(seconds=20)
        s.add_job(sched_mod._publish_job, "date", run_date=soon,
                  args=[band_cid, True], id=f"pub-{band_cid}", replace_existing=True)

        slot = orchestrator.next_free_slot("threads")

        # band 앞 job 때문에 밀리면 안 된다 - 거의 '지금'이어야 한다.
        assert slot < dt.datetime.now() + dt.timedelta(seconds=5)
    finally:
        try:
            s.remove_job(f"pub-{band_cid}")
        except Exception:
            pass
