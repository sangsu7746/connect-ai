import config
import preflight


def test_reports_missing_account(monkeypatch):
    monkeypatch.setattr(config, "THREADS_ACCOUNT", "")
    res = preflight.check_threads()
    assert res["ok"] is False
    names = [n for n, ok, _ in res["items"] if not ok]
    assert any("계정" in n for n in names)


def test_reports_disabled_master_switch(monkeypatch):
    monkeypatch.setattr(config, "THREADS_ACCOUNT", "tester")
    monkeypatch.setattr(config, "THREADS_ENABLED", False)
    res = preflight.check_threads()
    assert any("THREADS_ENABLED" in desc for _, _, desc in res["items"])


def test_never_raises_without_browser(monkeypatch):
    """preflight 는 읽기 전용이다. 브라우저를 띄우면 안 된다."""
    monkeypatch.setattr(config, "THREADS_ACCOUNT", "tester")
    res = preflight.check_threads()          # 예외 없이 돌아야 한다
    assert "items" in res


# ── 추가 — 디스패치 "On testing" 절이 명시한 4개 probe 중 브리프 Step 1
#    코드에는 없던 3개(쿠키 파일 없음 / 프로필에 threads: 없음 / 랜딩
#    주소 없음)를 각각 독립적으로 고정한다. 계정 하나만 갖춘 상태에서
#    나머지 세 관문이 각각 단독으로도 ok=False 를 만드는지 확인한다 —
#    account 테스트만으로는 이 세 관문이 실제로 작동하는지 알 수 없다
#    (account 가 비어 있으면 cookie_path() 가 애초에 None 을 돌려주므로
#    쿠키 관문 자체를 안 거친다).

def test_reports_missing_cookie_file(monkeypatch, tmp_path):
    """계정은 있지만 쿠키 파일이 디스크에 없는 경우."""
    monkeypatch.setattr(config, "THREADS_ACCOUNT", "tester")
    missing = tmp_path / "threads_tester.json"
    assert not missing.exists()
    monkeypatch.setattr(config, "cookie_path", lambda platform, account=None: missing)
    res = preflight.check_threads()
    assert res["ok"] is False
    names = [n for n, ok, _ in res["items"] if not ok]
    assert any("쿠키" in n for n in names)


def test_reports_missing_threads_profile_section(monkeypatch):
    """활성 프로필(YAML)에 threads: 섹션 자체가 없는 경우 — 지금 저장소의
    기본 프로필(loan)이 실제로 이 상태다(threads: 섹션 없음)."""
    monkeypatch.setattr(config, "THREADS_ACCOUNT", "tester")
    # preflight 는 활성 프로필이 아니라 쓰레드 전용 프로필을 본다.
    # threads: 섹션이 없는 프로필을 돌려주도록 막는다.
    monkeypatch.setattr(config, "PROFILE", {"key": "loan", "brand": {}})
    monkeypatch.setattr(config, "threads_profile",
                        lambda: {"key": "loan", "brand": {}})
    res = preflight.check_threads()
    assert res["ok"] is False
    names = [n for n, ok, _ in res["items"] if not ok]
    assert any("프로필" in n for n in names)


def test_reports_missing_landing_url(monkeypatch):
    """threads: 섹션은 있지만 landing 도 없고 config.BRAND_SITE 폴백도 없는 경우."""
    monkeypatch.setattr(config, "THREADS_ACCOUNT", "tester")
    _prof = {"key": "loan", "brand": {},
             "threads": {"interest_keywords": ["사진"]}}
    monkeypatch.setattr(config, "PROFILE", _prof)
    # preflight 는 쓰레드 전용 프로필을 본다.
    monkeypatch.setattr(config, "threads_profile", lambda: _prof)
    monkeypatch.setattr(config, "BRAND_SITE", "")
    res = preflight.check_threads()
    assert res["ok"] is False
    names = [n for n, ok, _ in res["items"] if not ok]
    assert any("랜딩" in n for n in names)
