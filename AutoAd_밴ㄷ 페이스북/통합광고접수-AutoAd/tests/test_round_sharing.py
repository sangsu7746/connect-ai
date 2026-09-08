# -*- coding: utf-8 -*-
"""한 바퀴 안에서는 여러 채널이 같은 그림을 나눠 쓴다.

지금은 _used_paths 가 한 실행 안의 재사용을 전부 막아, 채널 50곳이면 그림도
50장이 필요했다. 그래서 '발행 1건 = 그림 1장' 이 됐고 과금이 발행량에 정비례했다.
바꾼 뒤에는 '상품 1바퀴 = 그림 N장'(N = ceil(채널수 / IMAGE_FANOUT_MAX)) 이다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import orchestrator as O


def test_new_round_id_is_unique():
    a, b = O.new_round_id(), O.new_round_id()
    assert a and b and a != b


def test_pick_cycles_through_pool():
    pool = [(0, "/a.png"), (1, "/b.png"), (2, "/c.png")]
    got = [O.pick_for_channel(pool, i)[1] for i in range(7)]
    assert got == ["/a.png", "/b.png", "/c.png",
                   "/a.png", "/b.png", "/c.png", "/a.png"]


def test_pick_spreads_evenly_over_many_channels():
    """adstudio 74채널 · 그림 4장 → 각 그림이 18~19곳을 덮는다(상한 20 이내)."""
    pool = [(i, f"/{i}.png") for i in range(4)]
    counts = {}
    for i in range(74):
        p = O.pick_for_channel(pool, i)[1]
        counts[p] = counts.get(p, 0) + 1
    assert max(counts.values()) <= 20
    assert len(counts) == 4


def test_pick_raises_on_empty_pool():
    import pytest
    with pytest.raises(ValueError):
        O.pick_for_channel([], 0)


def test_round_pool_returns_requested_count(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "CREATIVES_DIR", tmp_path)
    for i in range(5):
        (tmp_path / f"doc_x_band_v{i}.png").write_bytes(b"x")
    monkeypatch.setattr(O, "_claimed_images", lambda round_id=None: set())
    monkeypatch.setattr(O.db, "image_cooldown_left",
                        lambda p, d, channel_id=None: 0)
    pool = O._round_pool("doc_x_band_v{n}.png", 3, "r1")
    assert len(pool) == 3
    assert len({p for _, p in pool}) == 3          # 서로 다른 그림


def test_round_pool_shrinks_when_stock_is_short(monkeypatch, tmp_path):
    """재고가 모자라면 있는 만큼만. 없다고 터지지 않는다."""
    import config
    monkeypatch.setattr(config, "CREATIVES_DIR", tmp_path)
    (tmp_path / "doc_x_band_v0.png").write_bytes(b"x")
    monkeypatch.setattr(O, "_claimed_images", lambda round_id=None: set())
    monkeypatch.setattr(O.db, "image_cooldown_left",
                        lambda p, d, channel_id=None: 0)
    pool = O._round_pool("doc_x_band_v{n}.png", 3, "r1")
    assert len(pool) == 1
