import datetime

import pytest

import config
from threads.models import RawPost, Reply, Verdict

# 브리프 원문은 posted_at 을 "2026-08-03T10:00:00" 으로 고정 문자열
# 박아뒀다 — runner._fresh_enough() 는 실제 벽시계(datetime.now())와
# 비교하므로, 이 스위트를 그 날짜 이후에 돌리면(예: 2026-08-04) 신선도
# 필터가 테스트 픽스처 전부를 조용히 걸러내 zip(posts, verdicts) 가
# 빈 이터레이션이 되고, 라우팅 로직과 무관하게 모든 통계가 0으로
# 나온다(실측: 이 스위트를 실행한 시점 자체가 이미 2026-08-04 였다).
# 테스트가 검증하려는 건 "점수 분기"이지 "신선도 필터"가 아니므로,
# 실행 시각 기준 상대 시각으로 바꿔 항상 신선하게 만든다.
_FRESH_TS = datetime.datetime.now().isoformat()


@pytest.fixture
def wired(temp_db, monkeypatch):
    """5개 모듈을 전부 목으로 갈아끼운다 — runner 의 분기만 본다."""
    from threads import runner

    posts = [RawPost(url=f"https://www.threads.net/@u{i}/post/{i}",
                     author=f"@u{i}", text="셀카 보정", posted_at=_FRESH_TS)
             for i in range(4)]
    # 점수: 95(자동) / 75(승인) / 50(폐기) / 92(자동)
    verdicts = [Verdict(True, 95, "r", "a"), Verdict(True, 75, "r", "a"),
                Verdict(False, 50, "낮음", ""), Verdict(True, 92, "r", "a")]

    monkeypatch.setattr(runner.harvester, "harvest", lambda *a, **k: posts)
    monkeypatch.setattr(runner.gate, "screen", lambda *a, **k: verdicts)
    monkeypatch.setattr(runner.reply_writer, "write",
                        lambda p, v, t, _llm=None: Reply(text="답글 https://x.test"))
    monkeypatch.setattr(config, "THREADS_AUTO_THRESHOLD", 90)
    monkeypatch.setattr(config, "THREADS_GATE_THRESHOLD", 70)
    monkeypatch.setattr(config, "THREADS_AUTO_DAILY_LIMIT", 5)
    monkeypatch.setattr(config, "THREADS_DAILY_LIMIT", 20)
    return runner


def test_routes_by_score(wired):
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["harvested"] == 4
    assert res["auto_published"] == 2      # 95, 92
    assert res["queued"] == 1              # 75
    assert res["dropped"] == 1             # 50


def test_auto_limit_spills_into_queue(wired, monkeypatch):
    """자동분 상한이 차면 고득점 건이 폐기되지 않고 승인 큐로 간다."""
    monkeypatch.setattr(config, "THREADS_AUTO_DAILY_LIMIT", 1)
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["auto_published"] == 1
    assert res["queued"] == 2              # 밀린 고득점 1건 + 원래 75점 1건


def test_author_cooldown_skips(wired, monkeypatch):
    monkeypatch.setattr("db.threads_author_replied_since",
                        lambda author, days: author == "@u0")
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["dropped"] == 2             # 원래 1건 + 쿨다운 1건


def test_empty_harvest_is_not_an_error(wired, monkeypatch):
    monkeypatch.setattr(wired.harvester, "harvest", lambda *a, **k: [])
    res = wired.run_once(account="tester", profile={"threads": {}}, dry_run=True)
    assert res["harvested"] == 0
    assert res["errors"] == []


def test_retryable_verdicts_stay_pending(wired, monkeypatch, temp_db):
    """LLM 판정 실패 건은 dropped 가 아니라 deferred 이고,
    DB 에는 pending 으로 남아 다음 회차가 다시 본다."""
    import db
    monkeypatch.setattr(wired.gate, "screen", lambda *a, **k: [
        Verdict(False, 0, "LLM 판정 실패(TimeoutError)", "", True) for _ in range(4)])
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["deferred"] == 4
    assert res["dropped"] == 0
    assert len(db.threads_targets_pending(10)) == 4


# ── 브리프 Step 1 원문 5개 이후 — 디스패치가 "On testing" 절에서 명시적으로
# 요구한 나머지 경계(자동임계 정확한 경계값·게이트임계·답글생성 실패·
# 쿨다운→LLM 순서·개별 글 예외 격리·브라우저 프로세스 정리)를 채운다.


def test_score_exactly_at_auto_threshold_is_auto_published(wired, monkeypatch):
    """점수가 자동 임계값과 정확히 같으면 자동발행이어야 한다(>= 이지 > 가
    아니다). 브리프 원문 테스트는 95/92 처럼 임계값(90)에서 멀리 떨어진
    값만 쓰므로 이 경계 자체는 실제로 검증하지 못한다."""
    posts = [RawPost(url="https://www.threads.net/@u9/post/9", author="@u9",
                     text="셀카 보정", posted_at=_FRESH_TS)]
    verdicts = [Verdict(True, 90, "r", "a")]   # wired 픽스처의 THREADS_AUTO_THRESHOLD == 90
    monkeypatch.setattr(wired.harvester, "harvest", lambda *a, **k: posts)
    monkeypatch.setattr(wired.gate, "screen", lambda *a, **k: verdicts)
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["auto_published"] == 1
    assert res["queued"] == 0


def test_score_just_below_auto_threshold_is_queued_not_dropped(wired, monkeypatch):
    """점수가 자동 임계값보다 1 낮으면(그러나 게이트는 통과) 승인 큐로
    가야 한다 — 폐기가 아니다. 자동임계·게이트임계 두 경계를 혼동하면
    이 건이 dropped 로 새어나간다."""
    posts = [RawPost(url="https://www.threads.net/@u8/post/8", author="@u8",
                     text="셀카 보정", posted_at=_FRESH_TS)]
    verdicts = [Verdict(True, 89, "r", "a")]
    monkeypatch.setattr(wired.harvester, "harvest", lambda *a, **k: posts)
    monkeypatch.setattr(wired.gate, "screen", lambda *a, **k: verdicts)
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["auto_published"] == 0
    assert res["queued"] == 1
    assert res["dropped"] == 0


def test_verdict_passed_at_gate_threshold_is_not_dropped(wired, monkeypatch):
    """게이트 임계값의 실제 수치 비교는 gate.py 의 책임이다(Task 2 에서
    검증됨). runner 의 책임은 gate.screen() 이 이미 내린 verdict.passed
    판정을 그대로 신뢰하는 것뿐이다 — 게이트 임계값과 정확히 같은
    점수라도 passed=True 로 왔으면 폐기하지 않는지 확인한다."""
    posts = [RawPost(url="https://www.threads.net/@u7/post/7", author="@u7",
                     text="셀카 보정", posted_at=_FRESH_TS)]
    verdicts = [Verdict(True, 70, "r", "a")]   # wired 픽스처의 THREADS_GATE_THRESHOLD == 70
    monkeypatch.setattr(wired.harvester, "harvest", lambda *a, **k: posts)
    monkeypatch.setattr(wired.gate, "screen", lambda *a, **k: verdicts)
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["dropped"] == 0
    assert res["queued"] == 1   # 70 < AUTO_THRESHOLD(90) 이므로 자동이 아니라 큐로


def test_reply_generation_failure_is_dropped_and_pass_continues(wired, monkeypatch):
    """가드 통과 실패 등으로 reply_writer.write() 가 두 번 다 실패하면
    ValueError 가 올라온다(Task 3 계약). 이 건만 dropped 로 기록되고
    (재판정 대기가 아니다 — LLM 판정 자체는 이미 통과했으므로), 나머지
    글은 계속 처리된다."""
    def _boom(p, v, t, _llm=None):
        raise ValueError("답글 가드 통과 실패: 우리 것이 아닌 주소")
    monkeypatch.setattr(wired.reply_writer, "write", _boom)
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    # score 50(verdict.passed=False)은 애초에 reply_writer 까지 못 감 → dropped 1
    # score 95/75/92(verdict.passed=True) 는 전부 답글 생성에서 터짐 → dropped 3
    assert res["dropped"] == 4
    assert res["auto_published"] == 0
    assert res["queued"] == 0
    assert res["passed"] == 0
    assert len(res["errors"]) == 3


def test_cooldown_checked_before_reply_generation(wired, monkeypatch):
    """작성자 쿨다운에 걸리면 reply_writer.write() 를 아예 호출하지 않는다
    — 이미 버릴 답글에 LLM 할당량을 쓰지 않기 위함(디스패치 항목 4)."""
    calls = []

    def _spy(p, v, t, _llm=None):
        calls.append(p.author)
        return Reply(text="답글 https://x.test")

    monkeypatch.setattr(wired.reply_writer, "write", _spy)
    monkeypatch.setattr("db.threads_author_replied_since",
                        lambda author, days: author == "@u0")
    wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert "@u0" not in calls
    assert calls.count("@u1") == 1   # 쿨다운 아닌 다른 글은 정상적으로 계속 감


def test_single_post_exception_does_not_abort_the_pass(wired, monkeypatch):
    """예상 못 한 예외(DB 락 등)가 한 건 처리 도중 터져도 run_once() 는
    올라오지 않고, 그 건만 errors 에 기록한 채 나머지 글을 계속 처리한다
    (디스패치 모호성 해소 지침 1: run_once() 는 절대 raise 하지 않는다)."""
    def _boom(*a, **k):
        raise RuntimeError("DB 락")
    monkeypatch.setattr("db.add_creative", _boom)

    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    # score 50 은 add_creative 까지 안 감(dropped). 나머지 3건(95/75/92)은
    # 전부 add_creative 에서 터져 auto_published/queued 어디에도 안 잡히고
    # errors 로만 기록된다.
    assert res["dropped"] == 1
    assert res["auto_published"] == 0
    assert res["queued"] == 0
    assert len(res["errors"]) == 3


def test_publisher_quit_called_even_on_mid_pass_exception(wired, monkeypatch):
    """루프 도중 예기치 못한 예외가 나도 pub.quit() 은 finally 로 반드시
    불린다 — 안 그러면 브라우저 프로세스가 leak 된다."""
    quit_calls = []
    monkeypatch.setattr(wired.ThreadsPublisher, "quit",
                        lambda self: quit_calls.append(1))

    def _boom(*a, **k):
        raise RuntimeError("DB 락")
    monkeypatch.setattr("db.add_creative", _boom)

    wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert quit_calls == [1]


def test_dry_run_auto_publish_does_not_poison_author_cooldown(wired, temp_db):
    """드라이런에서 자동발행이 '성공'으로 집계돼도 실제로는 아무 것도
    게시되지 않았다. threads_target_link_creative() 를 조건 없이 여기서
    부르면 replied_at 이 찍혀 다음 회차(진짜 실행이든 또 다른 드라이런
    이든)가 이 작성자를 쿨다운으로 오인해 건너뛴다(디스패치 항목 3).
    db.threads_author_replied_since() 는 몽키패치하지 않은 실제 함수로
    확인한다."""
    import db
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["auto_published"] == 2   # sanity: 정상적으로 라우팅은 됐다
    assert db.threads_author_replied_since("@u0", 30) is False
    assert db.threads_author_replied_since("@u3", 30) is False
