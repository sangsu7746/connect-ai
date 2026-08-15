"""선택 글들의 분석 계층 — 팩트 시트(숫자 문장)와 챕터 후보.
팩트 시트는 대본 프롬프트의 '사용 가능한 숫자' 전부이고,
corpus_text는 guardrails 숫자 대조의 context다."""
import re
from collections import Counter

from . import gemini
from .purple_cow_blog import extract_numbers


def corpus_text(posts: list[dict]) -> str:
    return "\n".join((p.get("content") or p.get("summary") or "") for p in posts)


def build_fact_sheet(posts: list[dict], limit: int = 40) -> list[dict]:
    facts, seen = [], set()
    for p in posts:
        for line in (p.get("content") or "").splitlines():
            line = line.strip()
            if not line or line in seen or not extract_numbers(line):
                continue
            seen.add(line)
            facts.append({"fact": line, "source_title": p.get("title", ""),
                          "source_url": p.get("url", "")})
            if len(facts) >= limit:
                return facts
    return facts


def _fallback_chapters(posts: list[dict], n: int) -> list[str]:
    tokens = Counter()
    for p in posts:
        for t in re.split(r"[^\w가-힣]+", p.get("title", "")):
            if len(t) >= 2:
                tokens[t] += 1
    top = [t for t, _ in tokens.most_common(n)]
    while len(top) < n:
        top.append(f"포인트 {len(top) + 1}")
    return top[:n]


def extract_chapters(posts: list[dict], n: int) -> list[str]:
    if n <= 0:
        return []
    if not gemini.available():
        return _fallback_chapters(posts, n)
    titles = "\n".join(f"- {p.get('title', '')}" for p in posts)
    body = corpus_text(posts)[:4000]
    try:
        raw = gemini.generate(
            f"다음 블로그 글들을 종합해 영상 챕터 제목 {n}개를 만들어라.\n"
            f"[글 제목들]\n{titles}\n[본문 발췌]\n{body}\n"
            f'짧은 한국어 명사구 {n}개의 JSON 배열만 출력: ["...", ...]',
            temperature=0.4, max_tokens=512)
        ch = [str(c).strip() for c in gemini.parse_json(raw) if str(c).strip()]
    except Exception:
        return _fallback_chapters(posts, n)
    ch = ch[:n]
    while len(ch) < n:
        ch.append(f"포인트 {len(ch) + 1}")
    return ch
