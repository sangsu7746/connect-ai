import json
from core import script_gen, storyboard

POSTS = [
    {"title": "전세 보증보험 총정리", "url": "https://a/1", "source": "naver",
     "summary": "",
     "content": "보증료는 연 0.128%다.\n3억이면 연 38만원이다.\n"
                "하지만 사실 집주인 동의는 필요 없다.\n1. 서류\n2. 신청\n3. 납부"},
]

def _fake_scene(caption="보증료 연 0.128%", narration="보증료는 연 0.128%입니다"):
    return {"caption": caption, "sub": "", "narration": narration,
            "image_prompt": "insurance document illustration"}

def _gen_ok(prompt, **kw):
    # 프레임/챕터 호출 모두 요청된 씬 수만큼 유효 씬 반환
    want = prompt.count('"idx"')
    return json.dumps([_fake_scene() for _ in range(max(want, 1))],
                      ensure_ascii=False)

def test_generate_script_fills_all_scenes(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(script_gen.gemini, "generate", _gen_ok)
    out = script_gen.generate_script(POSTS, "reels", 30)
    scenes = out["scenes"]
    assert len(scenes) == storyboard.PLAN[("reels", 30)]
    body = [s for s in scenes if s["role"] != "chapter"]
    assert all(s["caption"] and s["narration"] for s in body)
    assert all(len(s["caption"]) <= 18 and len(s["sub"]) <= 22 for s in scenes)

def test_gate_rejects_fabricated_then_safe_fallback(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    def bad_gen(prompt, **kw):
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene(narration="가입자의 92%가 만족했습니다")
                           for _ in range(max(want, 1))], ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", bad_gen)
    out = script_gen.generate_script(POSTS, "reels", 30)
    narrs = [s["narration"] for s in out["scenes"] if s["role"] != "chapter"]
    assert all("92" not in n for n in narrs)          # 날조 숫자는 절대 통과 못 함
    assert any(n == script_gen.SAFE_NARRATION for n in narrs)

def test_gate_rejects_copied_sentence(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    copied = "하지만 사실 집주인 동의는 필요 없다"     # 원문 15자+ 그대로
    def copy_gen(prompt, **kw):
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene(narration=copied)
                           for _ in range(max(want, 1))], ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", copy_gen)
    out = script_gen.generate_script(POSTS, "reels", 30)
    assert all(copied not in s["narration"] for s in out["scenes"])

def test_caption_over_18_truncated(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    long_cap = "가나다라마바사아자차카타파하가나다라마바"   # 20자
    monkeypatch.setattr(script_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(
                            [_fake_scene(caption=long_cap)
                             for _ in range(max(p.count('"idx"'), 1))],
                            ensure_ascii=False))
    out = script_gen.generate_script(POSTS, "reels", 30)
    assert all(len(s["caption"]) <= 18 for s in out["scenes"])

def test_regen_scene_single(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(script_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(_fake_scene(), ensure_ascii=False))
    diag = script_gen.purple_cow_blog.diagnose(POSTS[0], [])
    scene = {"idx": 2, "role": "point", "sec": 4.0, "chapter": "",
             "caption": "옛 자막", "sub": "", "narration": "옛 나레이션",
             "image_prompt": ""}
    new = script_gen.regen_scene(scene, POSTS, diag)
    assert new["caption"] == "보증료 연 0.128%" and new["idx"] == 2

def test_safe_fallback_sanitizes_caption(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    def bad_gen(prompt, **kw):
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene(caption="가입자 92% 만족",
                                       narration="가입자 92%가 만족했습니다")
                           for _ in range(max(want, 1))], ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", bad_gen)
    out = script_gen.generate_script(POSTS, "reels", 30)
    for s in out["scenes"]:
        assert "92" not in s["caption"] and "92" not in s["narration"]

def test_non_list_batch_response_degrades(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(script_gen.gemini, "generate",
                        lambda p, **kw: '{"scenes": "잘못된 형태"}')
    out = script_gen.generate_script(POSTS, "reels", 30)   # 크래시 없이
    body = [s for s in out["scenes"] if s["role"] != "chapter"]
    assert all(s["narration"] == script_gen.SAFE_NARRATION for s in body)

def test_scripts_table_exists(db):
    names = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "scripts" in names
