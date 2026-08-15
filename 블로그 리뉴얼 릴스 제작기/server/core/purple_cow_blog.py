"""보랏빛소 4문항 진단 — 블로그 콘텐츠판.

원본(쿠팡 purple_cow.py)의 원칙 유지:
- 판정은 수집 데이터에서만. 모델 추론으로 YES를 만들지 않는다.
- evidence는 원문에서 잘라낸 문자열 (예외: no_discount는 코퍼스 통계 요약 — 원문이 아니라 수집 목록에서 계산된 값).
원본 4문항을 콘텐츠 기준으로 각색 (spec §6 표):
  one_second   구체 숫자 훅 후보 존재
  what_is_that 통념 반박 마커 존재
  sneezer      실행 가능한 팁 구조(목록/단계) 존재
  no_discount  검색 상위 다수 노출(유사 제목) — 양 소스 노출 시 가점
"""
import re

CHECKLIST = [
    ("one_second", "단 1초 만에 시선을 잡을 구체 숫자·사실이 있는가?"),
    ("what_is_that", "'이건 뭐야?' 반응을 부를 통념 반박·의외성이 있는가?"),
    ("sneezer", "보는 사람이 저장·공유할 실행 팁(단계·체크리스트)이 있는가?"),
    ("no_discount", "검색 상위 다수가 다루는 검증된 수요 주제인가?"),
]

VERDICTS = {4: "보랏빛 소", 3: "보랏빛에 가깝다", 2: "회색 소",
            1: "갈색 소", 0: "완전한 갈색 소"}

_NUM = re.compile(r"(\d[\d,\.]*)\s*(만원|억원|억|원|%|퍼센트|배|년|개월|주|일|시간|평|건|명|kg|km)")
_COUNTER = ("하지만 사실", "의외로", "오해", "반대로", "잘못 알", "잘못 알려진",
            "착각", "진짜 이유", "숨겨진", "하지 마세요", "필요 없습니다", "없습니다만")
_TIP_LINE = re.compile(r"^\s*(\d+[\.\)]|[①-⑩]|[-•·])\s*\S", re.M)
_TIP_WORDS = ("체크리스트", "방법", "단계", "순서", "꿀팁", "준비물")
_HOOK_UNITS = {"만원", "억", "억원", "%", "퍼센트", "배"}


def extract_numbers(text: str) -> list[tuple[str, float, str]]:
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0)
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append((raw, val, m.group(2)))
    return out


def _sentence_around(text: str, needle: str) -> str:
    """needle이 포함된 줄 전체를 반환. 마침표 기준으로 자르면 '0.128%' 같은
    소수점 숫자를 중간에서 끊으므로 줄 단위로만 자른다."""
    idx = text.find(needle)
    if idx < 0:
        return needle
    start = text.rfind("\n", 0, idx) + 1
    end = text.find("\n", idx + len(needle))
    if end == -1:
        end = len(text)
    return text[start:end].strip() or needle


def _title_tokens(title: str) -> set[str]:
    return {t for t in re.split(r"[^\w가-힣]+", title or "") if len(t) >= 2}


def diagnose(post: dict, corpus: list[dict]) -> dict:
    text = "\n".join(x for x in (post.get("title"), post.get("summary"),
                                 post.get("content")) if x)
    answers, hooks = [], []

    # Q1 one_second — 훅이 될 구체 숫자
    hook_nums = [(raw, val, unit) for raw, val, unit in extract_numbers(text)
                 if unit in _HOOK_UNITS or (unit == "원" and val >= 10000)]
    q1 = bool(hook_nums)
    ev1 = _sentence_around(text, hook_nums[0][0]) if q1 else ""
    if q1:
        seen = []
        for raw, _, _ in hook_nums:
            line = _sentence_around(text, raw)
            if line not in seen:
                seen.append(line)
        hooks = seen[:3]
    answers.append({"key": "one_second", "q": CHECKLIST[0][1], "yes": q1,
                    "evidence": ev1})

    # Q2 what_is_that — 통념 반박 마커
    marker = next((mk for mk in _COUNTER if mk in text), None)
    answers.append({"key": "what_is_that", "q": CHECKLIST[1][1],
                    "yes": marker is not None,
                    "evidence": _sentence_around(text, marker) if marker else ""})

    # Q3 sneezer — 실행 팁 구조
    tip_lines = _TIP_LINE.findall(post.get("content") or "")
    tip_word = next((w for w in _TIP_WORDS if w in text), None)
    q3 = len(tip_lines) >= 3 or (len(tip_lines) >= 2 and tip_word is not None)
    ev3 = ""
    if q3:
        m = _TIP_LINE.search(post.get("content") or "")
        ev3 = _sentence_around(post.get("content") or "", m.group(0).strip()) if m \
            else _sentence_around(text, tip_word)
    answers.append({"key": "sneezer", "q": CHECKLIST[2][1], "yes": q3,
                    "evidence": ev3})

    # Q4 no_discount — 유사 제목 다수 노출 (+양 소스 가점, spec §5)
    mine = _title_tokens(post.get("title", ""))
    similar = []
    for other in corpus:
        toks = _title_tokens(other.get("title", ""))
        union = mine | toks
        if union and len(mine & toks) / len(union) >= 0.25:
            similar.append(other)
    sources = {post.get("source")} | {o.get("source") for o in similar}
    q4 = len(similar) >= 2 or (len(similar) >= 1 and {"naver", "google"} <= sources)
    answers.append({"key": "no_discount", "q": CHECKLIST[3][1], "yes": q4,
                    "evidence": f"유사 상위 글 {len(similar)}건, 소스 {sorted(s for s in sources if s)}"})

    score = sum(1 for a in answers if a["yes"])
    return {"score": score, "verdict": VERDICTS[score],
            "answers": answers, "hooks": hooks}
