"""대본 엔진 (spec §7). 흐름:
  진단 → 팩트 시트 → 챕터 → 씬 테이블 → Gemini 배치 생성(프레임 1회 + 챕터별 1회)
  → 씬 단위 게이트(guardrails+금지어+복사+길이) → 위반 씬 scene_level 재생성 ≤3회
  → 최종 실패 시 숫자 없는 안전 문구."""
import json

from . import analysis, gemini, guardrails, purple_cow_blog, storyboard

SAFE_NARRATION = "자세한 조건은 설명란의 원문에서 확인하세요."
MAX_REGEN = 3


def narration_budget(sec: float) -> int:
    """씬 길이에 맞는 나레이션 자수 예산. edge-tts ≈6자/초 — 5자/초로 여유."""
    return max(int(float(sec) * 5), 10)

_SCENE_JSON = ('{"idx": %d, "caption": "≤18자 자막", "sub": "≤22자 보조(없으면 빈칸)", '
               '"narration": "나레이션(자막을 그대로 읽지 말 것)", '
               '"image_prompt": "english image prompt, no text"}')


def _merged_post(posts: list[dict]) -> dict:
    """진단은 대표 1건 형태를 받으므로 선택 글을 합쳐 하나로 만든다."""
    return {"title": posts[0].get("title", ""), "source": posts[0].get("source", ""),
            "summary": " ".join(p.get("summary", "") for p in posts),
            "content": analysis.corpus_text(posts)}


def _batch_prompt(guide: str, facts: list[dict], scenes: list[dict],
                  label: str) -> str:
    fact_lines = "\n".join(f"- {f['fact']}" for f in facts)
    scene_specs = "\n".join(
        _SCENE_JSON % s["idx"] +
        f"  ← 역할 {s['role']}, {s['sec']}초, 나레이션 {narration_budget(s['sec'])}자 이내" +
        (f", 챕터 '{s['chapter']}'" if s["chapter"] else "")
        for s in scenes)
    return f"""{guide}

[팩트 시트] — 아래 문장의 숫자만 사용할 수 있다. 여기 없는 숫자는 절대 쓰지 마라.
{fact_lines}

[GEO 규칙] 씬마다 주제어를 명시적으로 다시 쓴다. "이 방법"·"그것"·"위에서 말한" 금지.
각 씬은 앞뒤 씬 없이 단독으로 인용돼도 말이 되어야 한다.

[{label}] 아래 씬들을 채워라. 각 씬은 다음 JSON 형태이고, JSON 배열만 출력한다:
{scene_specs}"""


def _gate(scene: dict, corpus: str, sources: list[str]) -> list[str]:
    # 필드마다 독립된 "문장"으로 취급 — \n으로 결합해야 guardrails._sentences가
    # 필드 경계에서 쪼갠다. " "로 합치면 narration의 hedge("확인할 수 없다")가
    # 같은 문장으로 묶인 caption의 금지어까지 면제시켜 버린다 (C1).
    text = "\n".join(x for x in (scene.get("caption"), scene.get("sub"),
                                 scene.get("narration")) if x)
    problems = list(guardrails.check(text, corpus)["blocking"])
    problems += [f"원문 복사: {s}" for s in guardrails.check_copy(text, sources)]

    narr = scene.get("narration") or ""
    if narr and narr != SAFE_NARRATION and "sec" in scene:
        budget = narration_budget(scene["sec"])
        if len(narr) > budget:
            problems.append(f"나레이션 길이 초과: {len(narr)}자 > {budget}자")
    return problems


def _apply(scene: dict, gen: dict) -> None:
    scene["caption"] = (gen.get("caption") or "")[:18]
    scene["sub"] = (gen.get("sub") or "")[:22]
    scene["narration"] = gen.get("narration") or ""
    scene["image_prompt"] = gen.get("image_prompt") or ""


def _safe_fallback(scene: dict, corpus: str, sources: list[str]) -> None:
    cap = scene["caption"][:18]
    if not cap or _gate({"caption": cap, "sub": "", "narration": ""}, corpus, sources):
        cap = scene["chapter"][:18] or "핵심 정리"
    scene["caption"] = cap
    scene["sub"] = ""
    scene["narration"] = SAFE_NARRATION
    if not scene["image_prompt"]:
        scene["image_prompt"] = "clean minimal infographic background, no text"


def regen_scene(scene: dict, posts: list[dict], diag: dict,
                facts: list[dict] | None = None, corpus: str | None = None,
                sources: list[str] | None = None) -> dict:
    """씬 하나를 scene_level 프롬프트로 다시 생성한다. 실패하면 원본 그대로.

    facts/corpus/sources를 호출자가 넘기면 재계산을 생략한다 (I3) — generate_script의
    게이트 루프는 이미 계산해 둔 값을 재사용하고, 내부 regen API 엔드포인트는
    기존처럼 None을 넘겨 posts에서 다시 계산한다."""
    guide = purple_cow_blog.build_script_guide(diag, scene_level=True)
    if facts is None:
        facts = analysis.build_fact_sheet(posts)
    if corpus is None:
        corpus = analysis.corpus_text(posts)
    if sources is None:
        sources = [p.get("content") or "" for p in posts]
    prompt = _batch_prompt(guide, facts, [scene], "씬 재생성")
    out = dict(scene)
    try:
        gen = gemini.parse_json(gemini.generate(prompt, max_tokens=1024))
        if isinstance(gen, list):
            gen = gen[0]
        cand = dict(scene)
        _apply(cand, gen)
        if not _gate(cand, corpus, sources):
            return cand
    except Exception:
        pass
    return out


def generate_script(posts: list[dict], fmt: str, duration: int) -> dict:
    diag = purple_cow_blog.diagnose(_merged_post(posts),
                                    [{"title": p.get("title", ""),
                                      "source": p.get("source", "")} for p in posts])
    facts = analysis.build_fact_sheet(posts)
    corpus = analysis.corpus_text(posts)
    sources = [p.get("content") or "" for p in posts]
    n_ch = storyboard.CHAPTERS.get((fmt, duration), 0)
    chapters = analysis.extract_chapters(posts, n_ch) if n_ch else []
    scenes = storyboard.build_scenes(fmt, duration, chapters)
    guide = purple_cow_blog.build_script_guide(diag, scene_level=False)

    # 배치 구성: 릴스=전체 1회 / 롱폼=프레임(hook·summary·twist·cta) 1회 + 챕터별 1회
    fill = [s for s in scenes if s["role"] != "chapter"]
    if fmt == "reels":
        batches = [("릴스 대본", fill)]
    else:
        frame = [s for s in fill if s["role"] in ("hook", "summary", "twist", "cta")]
        batches = [("프레임 씬", frame)]
        for ch in chapters:
            batches.append((f"챕터 '{ch}'",
                            [s for s in fill if s["role"] == "point"
                             and s["chapter"] == ch]))

    by_idx = {s["idx"]: s for s in scenes}
    for label, batch in batches:
        if not batch:
            continue
        try:
            gens = gemini.parse_json(
                gemini.generate(_batch_prompt(guide, facts, batch, label),
                                max_tokens=4096))
        except Exception:
            gens = []
        if not isinstance(gens, list):
            gens = []
        gen_by_idx = {g.get("idx"): g for g in gens if isinstance(g, dict)}
        for pos, s in enumerate(batch):
            g = gen_by_idx.get(s["idx"]) or (gens[pos] if pos < len(gens)
                                             and isinstance(gens[pos], dict) else {})
            _apply(s, g)

    # I2: 모든 배치 호출이 실패해 생성 대상 씬 전부가 나레이션 없는 채로 남았다면
    # (=결과가 전량 안전 폴백이 될 상황) 퇴화 대본을 조용히 저장하지 않고 명확히 실패한다.
    # spec §7 복사 차단 원칙상 원문 기반 규칙 대본은 만들지 않는다 — API에서 502로 변환.
    if fill and all(not s.get("narration") for s in fill):
        raise gemini.GeminiError("대본 생성 실패 — 모든 배치 호출이 실패했습니다")

    # 씬 단위 게이트 + 재생성 루프 (I3: 요청당 재생성 예산 상한)
    budget = 20
    for s in fill:
        tries = 0
        while _gate(s, corpus, sources) and tries < MAX_REGEN and budget > 0:
            tries += 1
            budget -= 1
            cand = regen_scene(s, posts, diag, facts=facts, corpus=corpus, sources=sources)
            if not _gate(cand, corpus, sources):
                by_idx[s["idx"]].update(cand)
                break
        if _gate(by_idx[s["idx"]], corpus, sources) or not s["narration"]:
            _safe_fallback(by_idx[s["idx"]], corpus, sources)

    return {"scenes": scenes, "fact_sheet": facts, "diag": diag,
            "chapters": chapters}
