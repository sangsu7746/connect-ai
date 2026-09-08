# ============================================================
#  tests/test_channels_threads.py — channels/threads.py(ThreadsAdapter) 단위 테스트
#  · 브리프가 명시적으로 요구한 파일 목록엔 없지만, 이 어댑터가
#    BaseAdapter._rate_ok() 를 그대로 물려받으면(오버라이드를 빼먹으면)
#    쓰레드 답글은 전부 채널 1행에 귀속되므로 CHANNEL_DAILY_LIMIT(=1)에
#    걸려 오늘 첫 건 이후 전부 막힌다 — dry-run 으로는 절대 드러나지
#    않고 실발행 첫날에야 터지는 종류의 버그라 별도로 고정해 둔다.
#  · 실제 브라우저는 쓰지 않는다 — ThreadsPublisher.reply()/login() 을
#    직접 부르지 않고, ThreadsAdapter 가 이들에게 그대로 위임하는지만
#    확인한다(threads/publisher.py 자신의 동작은 test_publisher.py 가
#    이미 커버한다).
# ============================================================
import config
from channels.base import PostResult
from channels.threads import ThreadsAdapter


def test_platform_is_threads():
    assert ThreadsAdapter().platform == "threads"


def test_post_ignores_image_path(monkeypatch):
    """디스패치 명시: image_path 는 무시한다(답글은 텍스트 전용)."""
    seen = {}

    def fake_reply(post_url, text, dry_run=True, auto=False):
        seen["args"] = (post_url, text, dry_run, auto)
        return PostResult(ok=True, dry_run=dry_run)

    ad = ThreadsAdapter(account_id="tester")
    monkeypatch.setattr(ad._pub, "reply", fake_reply)
    ad.post("https://www.threads.net/@a/post/1", "hi",
            image_path="/tmp/should_be_ignored.png", dry_run=True)
    # fake_reply 시그니처 자체에 image_path 자리가 없다 — 넘겼다면 TypeError 로
    # 이미 여기서 실패했을 것이다. 명시적으로도 한 번 더 확인한다.
    assert seen["args"][0] == "https://www.threads.net/@a/post/1"
    assert seen["args"][1] == "hi"


def test_post_delegates_to_publisher_reply(monkeypatch):
    ad = ThreadsAdapter(account_id="tester")
    calls = []

    def fake_reply(post_url, text, dry_run=True, auto=False):
        calls.append((post_url, text, dry_run, auto))
        return PostResult(ok=True, perm_url="https://x/ok", dry_run=dry_run)

    monkeypatch.setattr(ad._pub, "reply", fake_reply)
    res = ad.post("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert res.ok is True
    assert calls == [("https://www.threads.net/@a/post/1", "hi", False, False)]


# ── 상한 위임 — BaseAdapter 의 채널당 1건 한도가 아니라 threads 전용
#    계정 상한(THREADS_DAILY_LIMIT)을 써야 한다 ──────────────────
def test_rate_ok_uses_threads_daily_limit_not_channel_limit(monkeypatch, temp_db):
    """CHANNEL_DAILY_LIMIT=1 이어도(기본값) 오늘 두 번째 답글이 막히면
    안 된다 — 쓰레드 답글은 채널 1행(계정)에 전부 귀속되므로 그 한도를
    그대로 쓰면 안 된다는 게 threads/publisher.py 의 명시적 설계다.
    이 테스트는 ThreadsAdapter 가 그 설계를 실제로 물려받았는지 본다."""
    monkeypatch.setattr(config, "CHANNEL_DAILY_LIMIT", 1)
    monkeypatch.setattr(config, "THREADS_DAILY_LIMIT", 20)
    ad = ThreadsAdapter(account_id="tester")
    # db.threads_replies_today() 는 실제 DB(temp_db, 비어 있음)를 본다 → 0건.
    assert ad._rate_ok(channel_id=999) is True


def test_rate_ok_blocks_at_threads_daily_limit(monkeypatch):
    monkeypatch.setattr("db.threads_replies_today", lambda auto_only=False: 20)
    monkeypatch.setattr(config, "THREADS_DAILY_LIMIT", 20)
    ad = ThreadsAdapter(account_id="tester")
    assert ad._rate_ok(channel_id=1) is False
    assert "총 상한" in ad._rate_reason(channel_id=1)


# ── orchestrator._close()/_session_still_valid() 가 기대하는 계약 ──
def test_auto_property_mirrors_publisher_automator():
    ad = ThreadsAdapter(account_id="tester")
    assert ad._auto is None   # 아직 자동화 객체를 만들지 않았다
    sentinel = object()
    ad._pub._auto = sentinel
    assert ad._auto is sentinel   # 프로퍼티가 실시간으로 비춘다(캐시 아님)


def test_login_delegates_and_syncs_logged_in_flag(monkeypatch):
    ad = ThreadsAdapter(account_id="tester")
    monkeypatch.setattr(ad._pub, "login", lambda cred=None: True)
    assert ad._logged_in is False
    ok = ad.login()
    assert ok is True
    assert ad._logged_in is True
