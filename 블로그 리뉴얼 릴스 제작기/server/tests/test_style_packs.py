from core import style_packs as sp

def test_load_six_packs_with_required_fields():
    packs = sp.load()
    assert set(packs.keys()) == {"flat_vector", "pastel_anime", "isometric",
                                 "cinematic", "papercut", "neon_abstract"}
    for p in packs.values():
        assert p["prefix"] and p["negative"] is not None and p["color"].startswith("#")

def test_pick_role_mapping():
    assert sp.pick("hook", "재테크") == "cinematic"
    assert sp.pick("summary", "부동산") == "neon_abstract"
    assert sp.pick("cta", "여행") == "neon_abstract"
    assert sp.pick("twist", "IT") == "papercut"

def test_pick_category_defaults():
    assert sp.pick("point", "부동산") == "isometric"
    assert sp.pick("point", "재테크") == "flat_vector"
    assert sp.pick("chapter", "요리") == "pastel_anime"
    assert sp.pick("point", "육아") == "flat_vector"      # 미정의 카테고리 기본

def test_common_negative_has_text_ban():
    for word in ("text", "watermark", "letters"):
        assert word in sp.COMMON_NEGATIVE
