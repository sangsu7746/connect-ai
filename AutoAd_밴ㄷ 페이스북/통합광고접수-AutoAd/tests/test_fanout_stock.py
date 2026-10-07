# -*- coding: utf-8 -*-
"""한 그림이 몇 방에 뿌려지는가를 상한으로 막는다.

시간 분산(한 바퀴를 2~3일에 걸쳐 돌기)은 이 문제를 못 고친다 — 노출 속도만
늦출 뿐 '같은 그림이 66곳에 남아 있다' 는 사실은 그대로다. 플랫폼이 보는 것은
속도가 아니라 콘텐츠 지문이다.

⚠ enabled_channel_count·images_per_round·stock_target·stock_count 는 전부
  profile 뿐 아니라 platform 도 받는다. 그림 재고가 파일명에 플랫폼을 담아
  나뉘어 있기 때문이다(showcase_{profile}_{platform}_v{n}.png). 업종 전체로
  한 번만 세면 재고가 몰린 플랫폼이 재고 없는 플랫폼의 부족을 가린다 —
  실측(2026-09-08): printcraft 전체 53장(목표 42장)으로 '충족' 판정났지만
  그 53장은 전부 facebook 것이고 band(채널 10개)는 0장이었다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import db
import auto_loop as A


def _chan(monkeypatch, n):
    monkeypatch.setattr(A, "enabled_channel_count", lambda prof, platform: n)


def test_small_profile_needs_one_image_per_round(monkeypatch):
    import config
    _chan(monkeypatch, 8)
    monkeypatch.setattr(config, "IMAGE_FANOUT_MAX", 20)  # ceil(8/20)=1 산술 고정
    assert A.images_per_round("inkcraft", "band") == 1


def test_exactly_at_cap_is_still_one(monkeypatch):
    import config
    _chan(monkeypatch, 20)
    monkeypatch.setattr(config, "IMAGE_FANOUT_MAX", 20)  # ceil(20/20)=1 산술 고정
    assert A.images_per_round("x", "band") == 1


def test_one_over_cap_needs_two(monkeypatch):
    import config
    _chan(monkeypatch, 21)
    monkeypatch.setattr(config, "IMAGE_FANOUT_MAX", 20)  # ceil(21/20)=2 산술 고정
    assert A.images_per_round("x", "band") == 2


def test_large_profile_splits(monkeypatch):
    """adstudio 74채널 → ceil(74/20) = 4장"""
    import config
    _chan(monkeypatch, 74)
    monkeypatch.setattr(config, "IMAGE_FANOUT_MAX", 20)  # ceil(74/20)=4 산술 고정
    assert A.images_per_round("adstudio", "facebook") == 4


def test_zero_channels_is_zero(monkeypatch):
    import config
    _chan(monkeypatch, 0)
    monkeypatch.setattr(config, "IMAGE_FANOUT_MAX", 20)  # ceil(0/20)=0 산술 고정
    assert A.images_per_round("dead", "band") == 0


def test_stock_target_is_round_images_times_cooldown(monkeypatch):
    import config
    _chan(monkeypatch, 50)
    monkeypatch.setattr(config, "IMAGE_FANOUT_MAX", 20)  # ceil(50/20)=3 * 14일
    monkeypatch.setattr(config, "CREATIVE_COOLDOWN_DAYS", 14)  # 산술 고정: 둘 다 필요
    assert A.stock_target("printcraft", "facebook") == 3 * 14


def test_stock_target_is_scoped_per_platform(monkeypatch):
    """같은 업종이라도 플랫폼마다 채널 수가 다르면 목표도 달라야 한다.

    printcraft 실측: facebook 40채널 → ceil(40/20)=2장 x 14일=28장,
                     band     10채널 → ceil(10/20)=1장 x 14일=14장.
    업종 전체(50채널)로 한 번만 계산하면 band 몫이 facebook 몫에 섞여
    버린다 — 이 테스트가 그걸 막는다.
    """
    import config
    monkeypatch.setattr(config, "IMAGE_FANOUT_MAX", 20)
    monkeypatch.setattr(config, "CREATIVE_COOLDOWN_DAYS", 14)

    def fake_count(prof, platform):
        return {"facebook": 40, "band": 10}[platform]
    monkeypatch.setattr(A, "enabled_channel_count", fake_count)

    assert A.stock_target("printcraft", "facebook") == 2 * 14
    assert A.stock_target("printcraft", "band") == 1 * 14


def test_stock_count_is_platform_scoped(monkeypatch, tmp_path):
    """디스크의 그림 파일은 이름에 플랫폼이 박혀 있다 — stock_count 는 그
    플랫폼 몫만 세야 한다(다른 업종·다른 플랫폼 파일에 섞이면 안 된다)."""
    import config
    monkeypatch.setattr(config, "CREATIVES_DIR", tmp_path)
    names = [
        "showcase_printcraft_band_v0.png",
        "showcase_printcraft_band_v1.png",
        "doc_printcraft_facebook_v0.png",
        "showcase_printcraft_facebook_v1.png",
        "showcase_printcraft_facebook_v2.png",
        "showcase_otherprofile_band_v0.png",   # 다른 업종 - 섞이면 안 됨
        "showcase_printcraft_band_note.txt",   # png 아님 - 안 세어야 함
    ]
    for n in names:
        (tmp_path / n).write_bytes(b"x")

    assert A.stock_count("printcraft", "band") == 2
    assert A.stock_count("printcraft", "facebook") == 3


def test_stock_count_missing_dir_is_zero(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "CREATIVES_DIR", tmp_path / "no-such-dir")
    assert A.stock_count("printcraft", "band") == 0


def test_enabled_channel_count_is_platform_scoped(temp_db):
    """real 구현 — profile_key 는 같아도 platform 이 다르면 따로 세야 한다."""
    with db.get_conn() as con:
        con.execute(
            "INSERT INTO channels (platform, target_ref, profile_key, enabled, "
            "created_at) VALUES ('band','b1','printcraft',1,'2026-01-01')")
        con.execute(
            "INSERT INTO channels (platform, target_ref, profile_key, enabled, "
            "created_at) VALUES ('facebook','f1','printcraft',1,'2026-01-01')")
        con.execute(
            "INSERT INTO channels (platform, target_ref, profile_key, enabled, "
            "created_at) VALUES ('facebook','f2','printcraft',1,'2026-01-01')")
        # 꺼진 채널 · 다른 업종은 어느 쪽 집계에도 안 잡혀야 한다
        con.execute(
            "INSERT INTO channels (platform, target_ref, profile_key, enabled, "
            "created_at) VALUES ('band','b2','printcraft',0,'2026-01-01')")
        con.execute(
            "INSERT INTO channels (platform, target_ref, profile_key, enabled, "
            "created_at) VALUES ('band','b3','otherprofile',1,'2026-01-01')")

    assert A.enabled_channel_count("printcraft", "band") == 1
    assert A.enabled_channel_count("printcraft", "facebook") == 2
