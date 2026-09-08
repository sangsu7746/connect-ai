# -*- coding: utf-8 -*-
"""한 그림이 몇 방에 뿌려지는가를 상한으로 막는다.

시간 분산(한 바퀴를 2~3일에 걸쳐 돌기)은 이 문제를 못 고친다 — 노출 속도만
늦출 뿐 '같은 그림이 66곳에 남아 있다' 는 사실은 그대로다. 플랫폼이 보는 것은
속도가 아니라 콘텐츠 지문이다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import auto_loop as A


def _chan(monkeypatch, n):
    monkeypatch.setattr(A, "enabled_channel_count", lambda prof: n)


def test_small_profile_needs_one_image_per_round(monkeypatch):
    _chan(monkeypatch, 8)
    assert A.images_per_round("inkcraft") == 1


def test_exactly_at_cap_is_still_one(monkeypatch):
    _chan(monkeypatch, 20)
    assert A.images_per_round("x") == 1


def test_one_over_cap_needs_two(monkeypatch):
    _chan(monkeypatch, 21)
    assert A.images_per_round("x") == 2


def test_large_profile_splits(monkeypatch):
    """adstudio 74채널 → ceil(74/20) = 4장"""
    _chan(monkeypatch, 74)
    assert A.images_per_round("adstudio") == 4


def test_zero_channels_is_zero(monkeypatch):
    _chan(monkeypatch, 0)
    assert A.images_per_round("dead") == 0


def test_stock_target_is_round_images_times_cooldown(monkeypatch):
    import config
    _chan(monkeypatch, 50)
    monkeypatch.setattr(config, "CREATIVE_COOLDOWN_DAYS", 14)
    assert A.stock_target("printcraft") == 3 * 14
