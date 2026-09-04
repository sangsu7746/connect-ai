import pytest
from core import storyboard as sb

@pytest.mark.parametrize("fmt,dur", [("reels", 30), ("reels", 60),
                                     ("long", 60), ("long", 180),
                                     ("long", 300), ("long", 600)])
def test_scene_count_and_total(fmt, dur):
    scenes = sb.build_scenes(fmt, dur, ["챕터A", "챕터B", "챕터C",
                                        "챕터D", "챕터E", "챕터F"])
    assert len(scenes) == sb.PLAN[(fmt, dur)]
    assert abs(sum(s["sec"] for s in scenes) - dur) < 0.5
    assert all(s["sec"] >= 2.2 for s in scenes)

def test_structure_order_reels():
    scenes = sb.build_scenes("reels", 30, [])
    roles = [s["role"] for s in scenes]
    assert roles[0] == "hook" and roles[1] == "summary"
    assert roles[-1] == "cta" and roles[-2] == "twist"
    assert set(roles[2:-2]) == {"point"}

def test_structure_long_has_chapters():
    scenes = sb.build_scenes("long", 180, ["기초", "실전", "주의점"])
    roles = [s["role"] for s in scenes]
    assert roles.count("chapter") == 3
    ch = [s for s in scenes if s["role"] == "chapter"]
    assert [c["caption"] for c in ch] == ["기초", "실전", "주의점"]
    first = roles.index("chapter")
    assert scenes[first + 1]["role"] == "point"
    pts = [s for s in scenes if s["role"] == "point"]
    assert all(p["chapter"] in ("기초", "실전", "주의점") for p in pts)

def test_chapter_titles_padded_when_missing():
    scenes = sb.build_scenes("long", 60, ["하나뿐"])
    ch = [s["caption"] for s in scenes if s["role"] == "chapter"]
    assert len(ch) == 2 and ch[0] == "하나뿐" and ch[1]

def test_unknown_plan_raises():
    with pytest.raises(KeyError):
        sb.build_scenes("long", 999, [])
