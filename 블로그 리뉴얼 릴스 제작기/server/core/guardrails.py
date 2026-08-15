"""대본 발행 전 검사. 프롬프트로 부탁하는 것과 달리 여기서 걸리면 못 나간다.

원본(쿠팡 guardrails.py)의 핵심 교훈 유지: **날조는 열거할 수 없다** —
금지어 목록만으로는 날조 44건 중 42건이 통과했다. 그래서:
  1. 숫자 대조(주력) — 대본의 모든 숫자는 수집 글(context)에 있어야 한다.
     파생값은 뺄셈·나눗셈만 허용(절감액·단가). 곱셈·덧셈은 우연 통과 위험.
  2. 어휘 검사(보조) — banned_words 목록. 부정·유보 문맥은 통과.
  3. 공백 우회 차단 — '최 저 가' 대비, 공백 제거 사본도 검사.
  4. 복사 차단 — 공백 제거 후 연속 15자 이상 원문 일치 문장 차단 (저작권).
"""
import re

from .banned_words import CLICHE, FIRST_PERSON, SUPERLATIVE

_HEDGE = re.compile(
    r"(확인할\s*수\s*없|알\s*수\s*없|판단할\s*수\s*없|답할\s*수\s*없|"
    r"아니(다|라|며|고|에요|입니다|랍니다)|아님|"
    r"모른다|모릅니다|쓰지\s*않|쓸\s*수\s*없|말할\s*수\s*없|"
    r"근거가\s*없|데이터가\s*없|기록이\s*없|검증할\s*수\s*없|"
    r"보장하지\s*않|의미하지\s*않|뜻하지\s*않)")

_NUM = re.compile(r"\d[\d,]*\.?\d*")
#: 숫자 대조에서 뺄 것 — 날짜·서수처럼 본문에서 자연스럽게 생기는 값
_DATE_CTX = re.compile(r"(년|월|일|시|분|초|번째|층|호|세기)")


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _sentences(text: str) -> list:
    return [s for s in re.split(r"(?<=[.!?。])\s+|\n+", text or "") if s.strip()]


def _numbers_with_ctx(text: str) -> list:
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0).replace(",", "").rstrip(".")
        if not raw:
            continue
        try:
            v = float(raw)
        except ValueError:
            continue
        tail = (text or "")[m.end():m.end() + 4]
        out.append((v, tail))
    return out


def _known_numbers(context: str) -> set:
    vals = set()
    for v, _ in _numbers_with_ctx(context):
        vals.add(v)
        vals.add(round(v))          # 반올림 표기 차이 흡수
    return vals


def _derivable(v: float, known: set) -> bool:
    """실측값끼리의 뺄셈·나눗셈으로 나오는 값인가? (절감액·단가만 허용)"""
    if v <= 0:
        return False
    for a in known:
        if a <= 0:
            continue
        for b in known:
            if b <= 0 or b == a:
                continue
            if abs((a - b) - v) < 0.51:
                return True
            if 2 <= b <= 1000 and float(b).is_integer():
                q = a / b
                if abs(q - v) < 0.51 or abs(round(q) - v) < 0.51:
                    return True
    return False


def check(text: str, context: str = "") -> dict:
    """대본 텍스트를 검사한다. context = 수집 글 본문 전체(숫자의 유일한 출처)."""
    blocking, warnings = [], []

    for sent in _sentences(text or ""):
        hedged = bool(_HEDGE.search(sent))
        squashed = _squash(sent)
        for pats in (SUPERLATIVE, CLICHE):
            for pat, why in pats:
                m = re.search(pat, sent) or re.search(_squash(pat), squashed)
                if m and not hedged:
                    blocking.append(f"금지 표현 '{m.group(0)}'" + (f" — {why}" if why else ""))
        for pat in FIRST_PERSON:
            m = re.search(pat, sent)
            if m:
                blocking.append(f"사용 경험 사칭 '{m.group(0)}' — 화자는 직접 해보지 않았다")

    if context:
        known = _known_numbers(context)
        seen = set()
        for v, tail in _numbers_with_ctx(text or ""):
            if v in seen:
                continue
            seen.add(v)
            if _DATE_CTX.match(tail.strip()[:1] or " ") or _DATE_CTX.search(tail[:2]):
                continue
            if v in known or round(v) in known:
                continue
            if any(abs(v - k) <= max(1.0, abs(k) * 0.005) for k in known):
                continue
            if _derivable(v, known):
                continue
            blocking.append(f"수집 글에 없는 숫자 {v:,.10g} — 지어낸 값이거나 출처가 없다")
    else:
        warnings.append("수집 글 본문이 없어 숫자 대조를 건너뛰었다 — 검사가 약해진다")

    blocking = list(dict.fromkeys(blocking))
    return {"ok": not blocking, "blocking": blocking, "warnings": warnings}


def check_copy(text: str, sources: list[str], run: int = 15) -> list[str]:
    """대본 문장이 원문을 통째로 베꼈는지 본다. 공백 제거 후 연속 run자 이상
    원문에 그대로 있으면 그 문장을 반환한다 (재구성 원칙 — spec §7)."""
    squashed_sources = [_squash(s) for s in sources if s]
    hits = []
    for sent in _sentences(text or ""):
        sq = _squash(sent)
        if len(sq) < run:
            continue
        for i in range(0, len(sq) - run + 1):
            chunk = sq[i:i + run]
            if any(chunk in src for src in squashed_sources):
                hits.append(sent)
                break
    return hits
