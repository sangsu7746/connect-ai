# -*- coding: utf-8 -*-
"""칸 수는 채널 규격이 정하고, 생성 엔진은 스위치가 정한다.

격자 코드가 cols = min(n, 2) 라서 칸 수가 곧 결과물의 비율이다.
 2장 → 2x1 가로  (facebook 1200x630)
 4장 → 2x2 정사각 (band/kakao 1080x1080)

⚠ 컨트롤러 판정(2026-09-08): styles_for 의 무인자 폴백은 tiles_for("band")
  로 바꾸지 않는다. 기존 재고 75장 중 26장이 '채널 규격이 말하는 칸 수'와
  '그림이 실제로 가진 칸 수'가 다르다(band 2칸 22장 · facebook 4칸 4장).
  그래서 재사용 시에는 이미지 자체에서 칸 수를 되짚는 tiles_in_image() 를
  쓴다 — 아래 TestTilesInImage 참고.
"""
import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from content import showcase as S


def test_tiles_for_landscape_channel_is_two():
    assert S.tiles_for("facebook") == 2


def test_tiles_for_square_channel_is_four():
    assert S.tiles_for("band") == 4


def test_tiles_for_portrait_channel_is_four():
    assert S.tiles_for("kakao") == 4


def test_tiles_for_unknown_channel_defaults_to_four():
    assert S.tiles_for("nosuchplatform") == 4


# ⚠ temp_db 가 필요하다 — _gen_one 은 그림이 나온 자리에서 하루 예산 카운터를
#   올린다(db.note_image_generated). 격리하지 않으면 이 테스트가 운영 DB 의
#   오늘치 예산을 실제로 갉아먹는다(실측: data/autoad.db 에 1이 찍혔다).
def test_gen_one_uses_sd_when_engine_is_sd(monkeypatch, temp_db):
    import config
    import db
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", False, raising=False)
    from content import sd_backend
    monkeypatch.setattr(sd_backend, "gen_tile",
                        lambda brief, size=768, retries=2:
                            Image.new("RGB", (8, 8), (255, 255, 255)))
    out = S._gen_one("a sticker of a cat")
    assert isinstance(out, (bytes, bytearray))
    assert out[:8] == b"\x89PNG\r\n\x1a\n"      # PNG 시그니처
    # SD 갈래도 GPU 시간을 쓴다 — 예산을 쓴 것으로 세야 한다.
    assert db.images_generated_today() == 1


def test_gen_one_locked_spends_nothing(monkeypatch, temp_db):
    """잠겨서 못 만든 그림은 예산을 쓰지 않는다."""
    import config, db, pytest
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", True, raising=False)
    with pytest.raises(RuntimeError):
        S._gen_one("x")
    assert db.images_generated_today() == 0


def test_gen_one_still_locked_when_image_gen_locked(monkeypatch):
    """회귀 방지 — 잠금은 엔진과 무관하게 먼저 걸려야 한다."""
    import config, pytest
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", True, raising=False)
    with pytest.raises(RuntimeError, match="IMAGE_GEN_LOCKED"):
        S._gen_one("x")


# ── tiles_in_image: 재사용 시 '그림이 실제로 가진' 칸 수 ──────────────
#
# styles_for 의 n 은 make() 가 실제로 그린 n 과 같아야 한다(파일 상단 주석의
# 경고). 채널 규격에서 역산한 칸 수(tiles_for)는 과거 SHOWCASE_TILES 값이
# 바뀌기 전에 만들어진 재고와 어긋날 수 있다 — 그림 자체의 가로세로 비율만이
# 그 그림이 실제로 몇 칸인지 거짓 없이 말해준다(격자가 cols=min(n,2)라서
# 4칸은 세로가 길고 2칸은 가로가 길다).
def test_tiles_in_image_landscape_grid_is_two(tmp_path):
    # make() 가 실제로 만드는 2칸 격자 치수: 620*2+14*3=1282, 620+14*2+92=740
    p = tmp_path / "showcase_x_facebook_v0.png"
    Image.new("RGB", (1282, 740), "white").save(p)
    assert S.tiles_in_image(p) == 2


def test_tiles_in_image_square_grid_is_four(tmp_path):
    # make() 가 실제로 만드는 4칸 격자 치수: 1282, 620*2+14*3+92=1374
    p = tmp_path / "showcase_x_band_v0.png"
    Image.new("RGB", (1282, 1374), "white").save(p)
    assert S.tiles_in_image(p) == 4


def test_tiles_in_image_accepts_str_path(tmp_path):
    p = tmp_path / "showcase_x_band_v1.png"
    Image.new("RGB", (1282, 1374), "white").save(p)
    assert S.tiles_in_image(str(p)) == 4
