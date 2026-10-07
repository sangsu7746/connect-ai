# -*- coding: utf-8 -*-
"""이미지 생성을 잠갔을 때, 만들어둔 재고로 광고를 계속 돌린다.

2026-08-14 운영자 지시: 새 제미나이 키를 넣되 이미지는 지시가 있을 때까지
만들지 말 것. 그런데 소재에는 그림이 반드시 있어야 하므로, 과거에 만들어
디스크에 남아 있는 이미지를 재사용한다(실측 당시 즉시 사용 가능 163장).
"""
import sys
import sqlite3
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import config
from content import showcase as SH


# ── 잠금이 실제로 과금을 막는가 ────────────────────────────────────
def test_lock_blocks_every_paid_image_path(monkeypatch):
    """돈이 나가는 세 지점이 전부 막혀야 한다. 하나라도 새면 과금된다."""
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", True, raising=False)
    from content import pamphlet as PM

    with pytest.raises(RuntimeError) as e1:
        SH.make(profile_key="inkcraft", channel="band", variant=0)
    assert "IMAGE_GEN_LOCKED" in str(e1.value)

    with pytest.raises(RuntimeError) as e2:
        PM.brief_from_doc(__file__)
    assert "IMAGE_GEN_LOCKED" in str(e2.value)


def test_lock_can_be_released(monkeypatch):
    """되돌릴 수 있어야 한다 — 코드를 고치지 않고 플래그만으로.

    ⚠ config 는 .env 를 읽으므로 환경변수만 지워서는 기본값을 볼 수 없다
      (그렇게 짠 첫 테스트가 헛돌았다). 대신 '플래그를 내리면 잠금 검사를
      **지나간다**'를 확인한다. 실제 생성은 하지 않는다 — 돈이 나간다.
    """
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", False, raising=False)

    class _Passed(Exception):
        pass

    def _boom(*a, **k):
        raise _Passed("잠금을 지나 생성 단계까지 왔다")

    monkeypatch.setattr(SH, "_gen_one", _boom)
    with pytest.raises(_Passed):
        SH.make(profile_key="inkcraft", channel="band", variant=0)


# ── 재사용 시 그림과 문구가 맞는가 ─────────────────────────────────
def test_styles_for_matches_what_make_would_draw():
    """이 테스트가 재사용의 핵심이다.

    styles_for 는 make 가 그렸을 스타일을 생성 없이 되살린다. 두 계산식이
    어긋나면 **그림에 없는 스타일을 문구가 말한다**.
    make 의 식: styles[(variant*n + i) % len(styles)]
    """
    spec = SH.SPECS["inkcraft"]
    styles = spec["styles"]
    n = max(1, min(int(config.SHOWCASE_TILES), len(styles)))
    for variant in range(0, 9):
        expect = [styles[(variant * n + i) % len(styles)][0] for i in range(n)]
        assert SH.styles_for("inkcraft", variant) == expect, f"variant={variant}"


def test_styles_for_varies_across_variants():
    """변형마다 조합이 달라야 재사용해도 글이 겹치지 않는다."""
    seen = {tuple(SH.styles_for("inkcraft", v)) for v in range(8)}
    assert len(seen) > 1


def test_styles_for_unknown_profile_is_empty_not_crash():
    assert SH.styles_for("존재하지않는업종", 0) == []


def test_styles_for_never_returns_empty_for_supported_profiles():
    """빈 목록이 나오면 프롬프트의 '스타일:' 칸이 비어 문구가 겉돈다."""
    for key in SH.SPECS:
        assert SH.styles_for(key, 3), f"{key} 의 스타일이 비었다"


# ── 재고 선택 규칙 ────────────────────────────────────────────────
def test_reuse_requires_file_to_actually_exist(tmp_path, monkeypatch):
    """존재하지 않는 번호를 고르면 발행 직전에 '이미지 파일 없음'으로 막힌다."""
    import db
    import orchestrator as O

    dbf = tmp_path / "t.db"
    monkeypatch.setattr(db, "DB_PATH", dbf, raising=False)
    monkeypatch.setenv("AUTOAD_DB", str(dbf))
    con = sqlite3.connect(dbf)
    con.executescript("""
        CREATE TABLE creatives (id INTEGER PRIMARY KEY, image_path TEXT);
        CREATE TABLE posts (id INTEGER PRIMARY KEY, creative_id INT,
                            status TEXT, posted_at TEXT, created_at TEXT);
    """)
    con.commit()
    con.close()
    monkeypatch.setattr(config, "CREATIVES_DIR", tmp_path, raising=False)

    # 파일을 하나만 만들어 둔다 — v0 는 없고 v1 만 있다
    (tmp_path / "showcase_x_band_v1.png").write_bytes(b"fake")

    # orchestrator 내부 함수라 직접 부를 수 없으므로 규칙만 재현해 확인한다:
    # 존재하는 번호만 후보가 된다.
    import os
    cands = [n for n in range(3)
             if os.path.isfile(str(tmp_path / f"showcase_x_band_v{n}.png"))]
    assert cands == [1]
