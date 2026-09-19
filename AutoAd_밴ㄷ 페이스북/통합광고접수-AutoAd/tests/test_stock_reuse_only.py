# -*- coding: utf-8 -*-
"""재고 목표를 채웠으면 **생성만** 멈춘다. 발행은 재고로 계속 돈다.

스펙 §5.6 이 말하는 수렴 지점은 '생성이 0 으로 수렴' 이지 '소재가 0' 이 아니다.
재고를 돌려 쓰는 경로(_round_pool/pick_for_channel)는 run_campaign **안에**
있으므로, 재고가 찼다고 run_campaign 자체를 건너뛰면 그 바퀴는 소재를 한 건도
만들지 못하고 발행할 것도 사라진다(2026-09-08 전수 리뷰 C2 — 기본값 그대로
머지하면 활성 채널 134곳이 그날로 조용해진다).
"""
import io
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import config
import db
import orchestrator as O


# ── auto_loop: 재고가 차면 '건너뜀' 이 아니라 '재사용만' 이다 ────────────

def _stub_platform_math(monkeypatch, A, logs, stocked=True):
    monkeypatch.setattr(A, "log", lambda *a, **k: logs.append(a[0] if a else ""))
    monkeypatch.setattr(A, "platforms_in_use",
                        lambda profiles=None: {"band": {"mirizip"}})
    monkeypatch.setattr(A, "remaining_today", lambda platform, profiles=None: 10)
    monkeypatch.setattr(A, "pending_count", lambda platform=None: 0)
    monkeypatch.setattr(A, "free_channels", lambda platform, profiles=None: 10)
    monkeypatch.setattr(A, "per_cycle_cap", lambda min_n=0: 10)
    monkeypatch.setattr(A, "remaining_image_budget", lambda: 100)
    monkeypatch.setattr(A, "free_images", lambda prof, platform: None)
    monkeypatch.setattr(A, "stock_target", lambda prof, platform: 14)
    monkeypatch.setattr(A, "stock_count", lambda prof, platform: 24 if stocked else 0)


def test_stocked_profile_still_makes_creatives(monkeypatch, temp_db):
    """mirizip/band 실측: 채널 11 · 목표 14 · 재고 24. 그래도 소재는 나와야 한다."""
    import auto_loop as A
    logs, calls = [], []
    _stub_platform_math(monkeypatch, A, logs)
    monkeypatch.setattr(A, "run", lambda cmd, env=None, timeout=1800:
                        (calls.append(cmd), (True, ""))[1])

    made = A.do_generate({"mirizip"}, dry=False)

    assert calls, f"재고가 찼다고 run_by_profile 을 아예 안 부르면 안 된다: {logs}"
    assert made > 0, "재고로 도는 소재도 '만든 것' 으로 세어야 다음 단계가 발행한다"


def test_stocked_profile_asks_for_reuse_only(monkeypatch, temp_db):
    """재고가 찼으면 자식 프로세스에 '새로 만들지 말라' 고 못 박아 보낸다."""
    import auto_loop as A
    logs, calls = [], []
    _stub_platform_math(monkeypatch, A, logs)
    monkeypatch.setattr(A, "run", lambda cmd, env=None, timeout=1800:
                        (calls.append(cmd), (True, ""))[1])

    A.do_generate({"mirizip"}, dry=False)

    assert any("--reuse-only" in c for c in calls), \
        f"재고 충족인데 재사용 전용 신호가 안 갔다: {calls}"


def test_unstocked_profile_may_generate(monkeypatch, temp_db):
    """재고가 모자라면 새로 만들 수 있어야 한다 — 신호를 붙이면 안 된다."""
    import auto_loop as A
    logs, calls = [], []
    _stub_platform_math(monkeypatch, A, logs, stocked=False)
    monkeypatch.setattr(A, "run", lambda cmd, env=None, timeout=1800:
                        (calls.append(cmd), (True, ""))[1])

    A.do_generate({"mirizip"}, dry=False)

    assert calls, "재고 미달이면 당연히 돌아야 한다"
    assert not any("--reuse-only" in c for c in calls), \
        f"재고가 비었는데 재사용 전용으로 묶으면 재고가 영영 안 채워진다: {calls}"


def test_stock_log_still_tells_the_operator(monkeypatch, temp_db):
    """운영자는 '이 업종은 재고가 찼다' 를 계속 볼 수 있어야 한다."""
    import auto_loop as A
    logs = []
    _stub_platform_math(monkeypatch, A, logs)
    monkeypatch.setattr(A, "run", lambda cmd, env=None, timeout=1800: (True, ""))

    A.do_generate({"mirizip"}, dry=False)

    assert any("재고 목표 14장 충족" in str(m) for m in logs), logs


# ── run_by_profile: 신호가 자식 프로세스까지 실제로 간다 ────────────────

def _import_run_by_profile():
    """⚠ tools/run_by_profile.py 는 import 되는 순간 sys.stdout 을
    TextIOWrapper(sys.stdout.buffer) 로 갈아치운다. pytest 캡처 위에서 그러면
    그 래퍼가 나중에 GC 될 때 **캡처 버퍼까지 닫아** 이 파일 뒤의 테스트가 전부
    'I/O operation on closed file' 로 무너진다(auto_loop._utf8_stdout 주석의
    바로 그 사고 — 실측으로 여기서도 재현했다. 참조만 되돌려서는 안 되고,
    애초에 감쌀 버퍼를 버려도 되는 것으로 줘야 한다)."""
    saved = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    try:
        import run_by_profile as R
    finally:
        sys.stdout = saved
    return R


def test_run_profile_passes_reuse_only_to_child(monkeypatch, temp_db):
    R = _import_run_by_profile()

    db.add_channel("band", "https://band.us/band/77770001", name="Zed",
                   enabled=True, audience="mixed")
    with db.get_conn() as con:
        con.execute("UPDATE channels SET profile_key='mirizip'")

    seen = {}

    class _R:
        stdout = '@@{"campaign_id": 1, "n": 0}'
        stderr = ""

    def _fake_run(argv, **kw):
        seen["argv"] = argv
        return _R()

    monkeypatch.setattr(R.subprocess, "run", _fake_run)
    monkeypatch.setattr(R.P, "load", lambda k: {"name": k})

    R.run_profile("mirizip", 0, "t", False, reuse_only=True)
    assert seen["argv"][-1] == "1", \
        f"자식이 재사용 전용인지 알 방법이 없다: {seen['argv'][-1:]}"

    R.run_profile("mirizip", 0, "t", False, reuse_only=False)
    assert seen["argv"][-1] == "0"


# ── run_campaign: 신호를 받으면 재고를 돌린다(잠금과 무관하게) ──────────

def _docs_mode(monkeypatch, tmp_path):
    """test_round_sharing._lock_docs_mode 와 같되, **생성 잠금은 켜지 않는다**.
    reuse_only 인자 하나만으로 재사용 경로를 타는지 보기 위해서다."""
    monkeypatch.setattr(config, "CONTENT_SOURCE", "docs", raising=False)
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", False, raising=False)
    monkeypatch.setattr(config, "CREATIVES_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "compliance_gaps", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(config, "platform_allowed", lambda *a, **k: True, raising=False)


def test_run_campaign_reuse_only_uses_stock_instead_of_generating(
        temp_db, monkeypatch, tmp_path):
    """reuse_only=True 면 그림을 새로 만들지 않고 재고에서 꺼내 쓴다."""
    _docs_mode(monkeypatch, tmp_path)
    (tmp_path / f"doc_{config.PROFILE_KEY}_band_v0.png").write_bytes(b"x")

    def _boom(*a, **k):
        raise AssertionError("reuse_only 인데 새 그림을 만들려고 했다")
    monkeypatch.setattr(O.pamphlet, "render_from_doc", _boom)

    ch = db.add_channel("band", "https://band.us/band/66660001", name="Yankee",
                        enabled=True, audience="mixed")
    db.set_ad_policy(ch, "allow")
    chans = [c for c in db.list_channels(enabled_only=True) if c["id"] == ch]

    res = O.run_campaign({"title": "t", "goal": "g", "product": ""},
                         copy_fn=lambda p: '{"headline":"h","body":"b","cta":"c"}',
                         channels=chans, reuse_only=True)

    assert len(res["creatives"]) == 1, res["creatives"]
    assert res["creatives"][0]["image"].endswith("_band_v0.png")
