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

import config
import db
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


# ── Finding 2 (Important) e2e: run_campaign 자체를 잇는 배선 ─────────────
# 위 6개는 _round_pool/pick_for_channel 헬퍼만 본다. run_campaign 이 이 둘을
# 실제로 잇는 배선(채널 열거, 두 호출부, db.add_creative 의 round_id)은
# 여태 테스트가 없었다 - 인덱스를 뒤집거나 round_id=round_id 를 빠뜨려도
# 스위트가 전부 초록일 수 있었다.

def _lock_docs_mode(monkeypatch, tmp_path):
    """run_campaign 이 재고 재사용 경로(_round_pool/pick_for_channel)를
    타도록 만든다 - docs_mode(광고형 카드) + 생성 잠금 + 격리된 재고 폴더.

    ⚠ 활성 프로필이 무엇이든(현재는 loan) 이 테스트는 재사용 '배선'만 본다.
      실제 업종의 의무표기·허용 플랫폼 상태에 결과가 흔들리면 안 되므로
      두 게이트를 통과 상태로 고정한다.
    """
    monkeypatch.setattr(config, "CONTENT_SOURCE", "docs", raising=False)
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", True, raising=False)
    monkeypatch.setattr(config, "CREATIVES_DIR", tmp_path, raising=False)
    monkeypatch.setattr(config, "compliance_gaps", lambda *a, **k: [], raising=False)
    monkeypatch.setattr(config, "platform_allowed", lambda *a, **k: True, raising=False)


def _band_channel(n):
    """실발행 경로가 아니라 run_campaign 소재 생성만 타는 밴드 채널.
    ad_policy='allow' → creative_form() 이 'ad' 를 줘서 doc_ 카드(재사용) 경로를 탄다."""
    ch = db.add_channel("band", f"https://band.us/band/9000{n:04d}",
                        name=f"Alpha Band {n}", enabled=True, audience="mixed")
    db.set_ad_policy(ch, "allow")
    return ch


def _fb_channel(n):
    ch = db.add_channel("facebook", f"https://facebook.com/groups/8000{n:04d}",
                        name=f"Bravo FB {n}", enabled=True, audience="mixed")
    db.set_ad_policy(ch, "allow")
    return ch


def test_run_campaign_shares_one_image_across_same_platform_channels(
        temp_db, monkeypatch, tmp_path):
    """같은 플랫폼 채널 2곳 + 재고 1장 → 두 채널이 그 1장을 나눠 쓴다.

    _round_pool/pick_for_channel 이 아니라 run_campaign 을 실제로 불러 확인한다.
    round_id 도 같아야 한다 - _claimed_images(round_id) 가 '다른 바퀴' 인지를
    바로 이 문자열로 구분하기 때문이다."""
    _lock_docs_mode(monkeypatch, tmp_path)
    (tmp_path / f"doc_{config.PROFILE_KEY}_band_v0.png").write_bytes(b"x")

    ch1, ch2 = _band_channel(1), _band_channel(2)
    chans = [c for c in db.list_channels(enabled_only=True)
             if c["id"] in (ch1, ch2)]
    assert len(chans) == 2

    res = O.run_campaign(
        {"title": "t", "goal": "g", "product": ""},
        copy_fn=lambda p: '{"headline":"h","body":"b","cta":"c"}',
        channels=chans)

    creatives = res["creatives"]
    assert len(creatives) == 2, creatives
    images = {c["image"] for c in creatives}
    assert len(images) == 1, f"재고 1장인데 서로 다른 그림을 썼다: {images}"

    with db.get_conn() as conn:
        rids = [conn.execute("SELECT round_id FROM creatives WHERE id=?",
                             (c["creative_id"],)).fetchone()[0]
               for c in creatives]
    assert rids[0], "round_id 가 비어 있다"
    assert rids[0] == rids[1], f"같은 바퀴인데 round_id 가 다르다: {rids}"


def test_run_campaign_pool_is_scoped_per_platform(temp_db, monkeypatch, tmp_path):
    """Finding 1: 플랫폼마다 재고 namespace 가 다르므로 장수도 플랫폼별로 정해야 한다.

    band 2곳 · facebook 6곳 · IMAGE_FANOUT_MAX=2 로 두면:
      · band 는 ceil(2/2)=1 장이면 충분한데, 고치기 전 코드는 **전체 채널 수(8)**로
        ceil(8/2)=4 를 band 에도 그대로 넘긴다 - band 재고가 넉넉하면 소수
        플랫폼이 실제 필요량의 몇 배를 써 버린다(브리핑의 '2~4배 과소비').
      · facebook 은 ceil(6/2)=3 장이 맞다(고치기 전 코드는 여기도 4).
    band·facebook 재고를 똑같이 4장씩 채워 두고, 고친 뒤에는 band 가 정확히
    1장, facebook 이 정확히 3장으로 수렴하는지 본다 - **고치기 전에는 band 가
    2장을 써서(전역 n_imgs=4 를 전역 채널 순번으로 순환) 이 assert 에서 실패한다**
    (해당 assert 는 컨트롤러가 지시한 대로, 고침 전 실행에서 FAIL 했음을 확인했다).
    """
    monkeypatch.setattr(config, "IMAGE_FANOUT_MAX", 2, raising=False)
    _lock_docs_mode(monkeypatch, tmp_path)

    for n in range(4):
        (tmp_path / f"doc_{config.PROFILE_KEY}_band_v{n}.png").write_bytes(b"x")
        (tmp_path / f"doc_{config.PROFILE_KEY}_facebook_v{n}.png").write_bytes(b"x")

    band_ids = [_band_channel(i) for i in range(2)]
    fb_ids = [_fb_channel(i) for i in range(6)]
    by_id = {c["id"]: c for c in db.list_channels(enabled_only=True)}
    # 순서를 우리가 정한다(band 먼저) - '전역 채널 순번' 버그를 재현하려면
    # 순서가 고정돼야 한다.
    chans = [by_id[i] for i in band_ids] + [by_id[i] for i in fb_ids]

    res = O.run_campaign(
        {"title": "t", "goal": "g", "product": ""},
        copy_fn=lambda p: '{"headline":"h","body":"b","cta":"c"}',
        channels=chans)

    creatives = res["creatives"]
    assert len(creatives) == 8, creatives
    by_platform = {"band": [], "facebook": []}
    for c in creatives:
        by_platform[c["platform"]].append(c["image"])

    # 자기 플랫폼의 namespace 에서만 그림을 받았는가 - band 소재에 facebook
    # 파일이 섞이면 안 된다(물리적으로 다른 파일이다).
    for platform, imgs in by_platform.items():
        for img in imgs:
            assert f"_{platform}_" in img, \
                f"{platform} 소재가 다른 namespace 그림을 썼다: {img}"

    band_distinct = set(by_platform["band"])
    fb_distinct = set(by_platform["facebook"])
    # 소수 플랫폼(band)이 자기 채널 수가 필요로 하는 것보다 더 많은 그림을
    # 쓰면 안 된다 - ceil(2/2)=1.
    assert len(band_distinct) == 1, (
        f"band 채널은 2곳뿐이라 그림 1장이면 충분한데 {len(band_distinct)}장을 "
        f"썼다(전체 채널 수로 장수를 정하면 이렇게 된다): {band_distinct}")
    assert len(fb_distinct) == 3, (
        f"facebook 채널 6곳 · IMAGE_FANOUT_MAX=2 → ceil(6/2)=3 장이어야 하는데 "
        f"{len(fb_distinct)}장을 썼다: {fb_distinct}")
