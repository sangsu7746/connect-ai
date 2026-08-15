"""선택 글들의 분석 계층 — 팩트 시트(숫자 문장)와 챕터 후보.
팩트 시트는 대본 프롬프트의 '사용 가능한 숫자' 전부이고,
corpus_text는 guardrails 숫자 대조의 context다."""
import re
from collections import Counter

from . import gemini, guardrails
from .banned_words import CLICHE, FIRST_PERSON, SUPERLATIVE
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


def _title_blocked(title: str, corpus: str) -> bool:
    """챕터 타이틀이 게이트에 걸리는가 (C2). guardrails.check는 문장 하나짜리
    타이틀 안에 hedge가 같이 있으면 금지어를 면제할 수 있으므로(C1과 같은 함정),
    banned_words 패턴은 hedge 여부와 무관하게 한 번 더 직접 검사한다."""
    if guardrails.check(title, corpus)["blocking"]:
        return True
    for pats in (SUPERLATIVE, CLICHE):
        for pat, _why in pats:
            if re.search(pat, title):
                return True
    return any(re.search(pat, title) for pat in FIRST_PERSON)


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
        parsed = gemini.parse_json(raw)
        if not isinstance(parsed, list):
            return _fallback_chapters(posts, n)
        ch = [str(c).strip() for c in parsed if str(c).strip()]
    except Exception:
        return _fallback_chapters(posts, n)
    ch = ch[:n]
    while len(ch) < n:
        ch.append(f"포인트 {len(ch) + 1}")

    # C2: 챕터 타이틀은 무게이트로 scenes_json·설명란에 유입됐다. 차단이 아니라
    # 그 타이틀만 안전한 폴백으로 교체 — "3가지 방법"의 3 같은 숫자 오탐도
    # 영상 자체를 막지 않고 안전하게 처리된다.
    corpus = corpus_text(posts)
    fallback = _fallback_chapters(posts, n)
    for i, title in enumerate(ch):
        if _title_blocked(title, corpus):
            ch[i] = fallback[i] if i < len(fallback) else f"포인트 {i + 1}"
    return ch
