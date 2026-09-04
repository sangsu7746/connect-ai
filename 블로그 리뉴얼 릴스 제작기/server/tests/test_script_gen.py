import json
import pytest
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
    # I2: 모든 배치가 쓸모없는 응답만 내놓으면(생성 대상 전부 나레이션 빈 상태)
    # 더 이상 퇴화 대본을 조용히 저장하지 않는다 — 명확한 실패로 바뀐다.
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(script_gen.gemini, "generate",
                        lambda p, **kw: '{"scenes": "잘못된 형태"}')
    with pytest.raises(script_gen.gemini.GeminiError):
        script_gen.generate_script(POSTS, "reels", 30)

def test_gate_field_isolation():
    # C1: caption/sub/narration을 " "로 합치면 narration의 hedge가 caption의
    # 금지어를 면제시켜 버렸다. "\n" 결합이면 필드별로 격리돼 caption이 걸린다.
    scene = {"caption": "최저가 예약 비법", "sub": "",
             "narration": "가격이 최저인지 확인할 수 없다."}
    assert script_gen._gate(scene, "본문", ["본문"])   # caption 금지어가 차단돼야 함

def test_regen_budget_caps_total_calls(monkeypatch):
    # I3: 위반 씬마다 무상한 재생성을 허용하면 대형 롱폼(72씬)에서 폭주한다.
    # 요청당 재생성 예산(20)을 넘으면 남은 위반 씬은 즉시 안전 폴백으로 간다.
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    calls = {"n": 0}
    def always_bad(prompt, **kw):
        calls["n"] += 1
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene(narration="가입자의 92%가 만족했습니다")
                           for _ in range(max(want, 1))], ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", always_bad)
    out = script_gen.generate_script(POSTS, "long", 600)   # 72씬, 프레임 1+챕터 6=배치 7회
    body = [s for s in out["scenes"] if s["role"] != "chapter"]
    assert all(s["narration"] == script_gen.SAFE_NARRATION for s in body)
    # 챕터 추출 1회 + 배치 7회 + 예산 상한 20회 (script_gen.gemini와 analysis.gemini는
    # 같은 core.gemini 모듈이라 always_bad가 챕터 추출 호출도 가로챈다)
    assert calls["n"] <= 1 + 7 + 20

def test_scripts_table_exists(db):
    names = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "scripts" in names

def test_narration_budget_formula():
    assert script_gen.narration_budget(4.0) == 20
    assert script_gen.narration_budget(8.3) == 41
    assert script_gen.narration_budget(1.0) == 10          # 하한

def test_gate_flags_over_budget_narration():
    scene = {"idx": 0, "role": "point", "sec": 4.0, "chapter": "",
             "caption": "자막", "sub": "",
             "narration": "가" * 40, "image_prompt": ""}
    problems = script_gen._gate(scene, "본문", ["본문"])
    assert any("길이 초과" in p for p in problems)

def test_gate_allows_within_budget_and_safe():
    scene = {"idx": 0, "role": "point", "sec": 4.0, "chapter": "",
             "caption": "자막", "sub": "",
             "narration": "가" * 15, "image_prompt": ""}
    assert not any("길이 초과" in p
                   for p in script_gen._gate(scene, "본문", ["본문"]))
    safe = dict(scene, narration=script_gen.SAFE_NARRATION, sec=2.2)
    assert not any("길이 초과" in p
                   for p in script_gen._gate(safe, "본문", ["본문"]))

def test_over_budget_triggers_regen_then_fallback(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    def long_gen(prompt, **kw):
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene(narration="보증료는 " + "가" * 60)
                           for _ in range(max(want, 1))], ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", long_gen)
    out = script_gen.generate_script(POSTS, "reels", 30)
    for s in out["scenes"]:
        if s["role"] == "chapter":
            continue
        budget = script_gen.narration_budget(s["sec"])
        assert len(s["narration"]) <= max(budget,
                                          len(script_gen.SAFE_NARRATION))

def test_prompt_includes_budget(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    seen = {}
    def spy(prompt, **kw):
        seen["p"] = prompt
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene() for _ in range(max(want, 1))],
                          ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", spy)
    script_gen.generate_script(POSTS, "reels", 30)
    assert "자 이내" in seen["p"]                    # 씬별 예산 문구
