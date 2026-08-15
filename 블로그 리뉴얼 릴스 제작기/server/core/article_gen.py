"""블로그 글 생성 엔진 (spec §12-A). 대본 엔진과 같은 분석·진단·게이트 위에서
글(제목+마크다운)을 만든다. 게이트는 문단 단위 — 위반 문단만 재생성(예산 10회),
최종 실패 문단은 삭제하고 경고로 남긴다(글은 씬과 달리 삭제가 자연스럽다)."""
import json

from . import analysis, gemini, guardrails, purple_cow_blog
from .banned_words import prompt_ban_list
from .gemini import GeminiError

ARTICLE_REGEN_BUDGET = 10
TITLE_MAX = 32
SAFE_TITLE = "핵심 정리"


def build_article_guide(diag: dict) -> str:
    principles = "\n".join(
        f"  원칙 {p['n']}. {p['name']} — {p['apply']}"
        for p in purple_cow_blog._pick_principles(diag)[:3])
    weak = "\n".join(f"  - {w}" for w in diag["weak"]) or "  - 없음"
    hooks = " / ".join(diag["hooks"][:3]) or "(훅 후보 없음)"
    return f"""[보랏빛소 진단] 점수 {diag['score']}/4 — {diag['verdict']}
보완할 약점:
{weak}
훅 후보(수집 데이터 원문): {hooks}
적용 원칙:
{principles}
[글 규칙]
- 제목 {TITLE_MAX}자 이내, 낚시 금지, 구체 숫자가 있으면 제목에 쓴다.
- 구조: "■ 핵심 요약" 단정문 3줄 → ## 소제목 3~4개 → ## 단점/주의 → ## 마무리.
- 본문 1,200~1,800자. 각 ## 문단은 앞뒤 없이 단독으로 읽혀야 한다(GEO):
  문단마다 주제어를 다시 쓰고("이 방법"·"그것" 금지), 숫자마다 확인 시점을 붙인다.
- 장점보다 단점·안 맞는 사람을 먼저 쓴다.
- 수집 글에 있는 숫자만 사용. 원문 문장을 그대로 베끼지 말고 재구성.
{prompt_ban_list()}"""


def _paragraphs(body_md: str) -> list[str]:
    """빈 줄 기준 문단 분리. ## 헤딩은 다음 문단에 붙인다."""
    blocks, cur = [], []
    for line in (body_md or "").splitlines():
        if not line.strip():
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def gate_article(title: str, body_md: str, corpus: str,
                 sources: list[str]) -> list[str]:
    """문단별 게이트 위반 목록. 제목도 하나의 문단으로 검사한다."""
    problems = []
    for label, text in [("제목", title)] + [
            (f"문단 {i+1}", p) for i, p in enumerate(_paragraphs(body_md))]:
        r = guardrails.check(text, corpus)
        problems += [f"{label}: {b}" for b in r["blocking"]]
        problems += [f"{label}: 원문 복사 — {s}"
                     for s in guardrails.check_copy(text, sources)]
    return problems


def _regen_paragraph(par: str, guide: str, facts_text: str) -> str:
    prompt = f"""{guide}
[팩트 시트] — 아래 문장의 숫자만 사용할 수 있다.
{facts_text}
[이번 출력 범위] 아래 문단 하나만 규칙에 맞게 다시 써라. 마크다운 헤딩은 유지.
JSON 오브젝트 하나만 출력: {{"paragraph": "..."}}
[문제 문단]
{par}"""
    gen = gemini.parse_json(gemini.generate(prompt, max_tokens=1024))
    if isinstance(gen, list):
        gen = gen[0] if gen else {}
    return (gen.get("paragraph") or "") if isinstance(gen, dict) else ""


def generate_article(posts: list[dict]) -> dict:
    if not gemini.available():
        raise GeminiError("GEMINI_API_KEY 미설정")
    diag = purple_cow_blog.diagnose(
        {"title": posts[0].get("title", ""), "source": posts[0].get("source", ""),
         "summary": " ".join(p.get("summary", "") for p in posts),
         "content": analysis.corpus_text(posts)},
        [{"title": p.get("title", ""), "source": p.get("source", "")}
         for p in posts])
    guide = build_article_guide(diag)
    facts = analysis.build_fact_sheet(posts)
    facts_text = "\n".join(f"- {f['fact']}" for f in facts)
    corpus = analysis.corpus_text(posts)
    sources = [p.get("content") or "" for p in posts]

    raw = gemini.generate(f"""{guide}
[팩트 시트] — 아래 문장의 숫자만 사용할 수 있다. 여기 없는 숫자는 절대 쓰지 마라.
{facts_text}
[출력] JSON 오브젝트 하나만: {{"title": "제목({TITLE_MAX}자 이내)", "body_md": "마크다운 본문"}}""",
                          max_tokens=8192)
    gen = gemini.parse_json(raw)
    if not isinstance(gen, dict):
        raise GeminiError("글 생성 응답이 JSON 오브젝트가 아니다")

    warnings: list[str] = []
    title = (gen.get("title") or "").strip()[:TITLE_MAX]
    if not title or guardrails.check(title, corpus)["blocking"] \
            or guardrails.check_copy(title, sources):
        if title:
            warnings.append(f"제목이 게이트에 걸려 교체됨: {title}")
        hook = (diag["hooks"][0][:TITLE_MAX] if diag["hooks"] else "")
        title = hook if hook and not guardrails.check(hook, corpus)["blocking"] \
            else SAFE_TITLE

    paragraphs = _paragraphs(gen.get("body_md") or "")
    budget = ARTICLE_REGEN_BUDGET
    kept: list[str] = []
    for par in paragraphs:
        problems = gate_article("", par, corpus, sources)
        while problems and budget > 0:
            budget -= 1
            try:
                cand = _regen_paragraph(par, guide, facts_text)
            except Exception:
                cand = ""
            if cand and not gate_article("", cand, corpus, sources):
                par, problems = cand, []
                break
            problems = gate_article("", par, corpus, sources)
        if problems:
            warnings.append(f"게이트 실패로 문단 삭제: {par[:40]}…"
                            if len(par) > 40 else f"게이트 실패로 문단 삭제: {par}")
            continue
        kept.append(par)

    return {"title": title, "body_md": "\n\n".join(kept), "warnings": warnings}
