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
from .banned_words import prompt_ban_list

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

#: 훅 후보에서 배제할 행정성 숫자 문맥 (원본 BORING_KEY의 블로그판)
_ADMIN_CTX = re.compile(r"(전화|문의|팩스|사업자|등록\s*번호|우편|주소|계좌|"
                        r"인가|허가|신고\s*번호)")


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
    hook_nums = []
    for raw, val, unit in extract_numbers(text):
        if unit not in _HOOK_UNITS and not (unit == "원" and val >= 10000):
            continue
        line = _sentence_around(text, raw)
        if _ADMIN_CTX.search(line):
            continue                      # 사업자번호·전화번호는 훅이 아니다
        hook_nums.append((raw, val, unit))
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
    weak = [a["q"] for a in answers if not a["yes"]]
    return {"score": score, "verdict": VERDICTS[score],
            "answers": answers, "hooks": hooks, "weak": weak}


# ════════════════════════════════════════════════════════════════
# 보랏빛소 실행 원칙 8종 — 블로그 대본판 (원본: 쿠팡 purple_cow.py PRINCIPLES)
# ════════════════════════════════════════════════════════════════

PRINCIPLES = [
    {"n": 1, "name": "각도 변화",
     "origin": "고객의 호감을 살 수 있도록 제품을 근본적으로 변화시키는 방법 10가지를 생각해 본다.",
     "apply": "주제 자체는 못 바꾸니 '보는 각도'를 바꾼다. 이 주제를 다루는 뜻밖의 상황·용도 "
              "10가지를 떠올리고 가장 의외인 1가지로 영상을 연다."},
    {"n": 2, "name": "초소형 타깃",
     "origin": "가장 작은 시장을 먼저 정의하고, 그 틈새를 완전히 뒤흔들 제품을 그린다.",
     "apply": "'누구에게나 유용한 정보'라고 말하지 않는다. 이 정보가 미치도록 필요한 단 한 사람을 "
              "직업·상황·시간대까지 좁혀 지목하고, 그 한 사람에게 말하듯 쓴다."},
    {"n": 3, "name": "아웃소싱",
     "origin": "핵심 역량에 집중하고 나머지는 아웃소싱한다.",
     "apply": "대본은 '단 하나의 주장'만 책임진다. 세부 조건·예외·출처 나열은 "
              "설명란과 원문 링크에 위임하고 대본에서 지운다."},
    {"n": 4, "name": "허락자산 구축",
     "origin": "가장 충실한 고객들과 막힘없이 직접 얘기할 소통 구조를 만든다.",
     "apply": "CTA에서 '구독해 주세요'가 아니라 '무엇을 언제 보여줄지' 약속한다. "
              "예: 다음 영상에서 실패 사례 3가지를 공개합니다."},
    {"n": 5, "name": "타 장르 모방",
     "origin": "전혀 다른 산업에서 성공한 리마커블한 아이디어를 그대로 베낀다.",
     "apply": "정보 요약 형식을 버리고 다른 장르의 형식을 빌린다. "
              "실험 보고서 / 법정 판결문 / 연애편지 / 오답 노트 / 사건 브리핑 등."},
    {"n": 6, "name": "정반대 실행",
     "origin": "다른 회사들이 표준이라 믿는 방식을 완전히 뒤집어 시도한다.",
     "apply": "모두가 '이렇게 하세요'로 시작할 때 '이런 사람은 하지 마세요'로 연다. "
              "장점 앞에 단점·부작용을 먼저, 그것도 구체적으로 놓는다."},
    {"n": 7, "name": "최초 시도",
     "origin": "속한 산업에서 '아직 행해지지 않은 것'을 찾아 누구보다 먼저 실천한다.",
     "apply": "이 주제 영상에서 아무도 하지 않은 것을 하나 한다. "
              "예: 상위 글들의 상충 지점 공개 비교, 실패 조건 공개, 직접 계산."},
    {"n": 8, "name": "근본적인 의문",
     "origin": "관행적으로 이어져 온 방식에 항상 '왜 안 되는데?'라고 묻는다.",
     "apply": "숫자를 소개하지 말고 계산한다. '월로 나누면 얼마인가?' '하루당으로 보면?' "
              "총액은 판단이 안 서지만 단위당 값은 판단이 선다. "
              "수집 글에 없는 사정은 확인할 방법이 없으니 추측하지 않는다."},
]


def _pick_principles(diag: dict) -> list:
    """진단 결과에 따라 이 콘텐츠에 필요한 원칙을 고른다 (원본 매핑 유지)."""
    yes = {a["key"] for a in diag["answers"] if a["yes"]}
    picked = []
    if "one_second" not in yes:
        picked += [1, 2]
    if "what_is_that" not in yes:
        picked += [5, 6]
    if "sneezer" not in yes:
        picked += [7]
    if "no_discount" not in yes:
        picked += [8, 2]
    picked += [3, 4]
    if diag["score"] >= 3:
        picked = [3, 4, 6]
    seen, out = set(), []
    for n in picked:
        if n not in seen:
            seen.add(n)
            out.append(next(p for p in PRINCIPLES if p["n"] == n))
    return out[:5]


def build_script_guide(diag: dict, scene_level: bool = False) -> str:
    """대본 생성 프롬프트에 주입할 보랏빛소 지침.

    scene_level=True는 씬 하나 재생성용 — 전체 구성 규칙을 넣으면 모델이
    스토리보드를 통째로 다시 만들어 파싱이 깨진다(원본에서 실증된 실패)."""
    hooks = " / ".join(diag["hooks"][:3]) or "(데이터에서 뽑을 훅 없음)"
    principles = "\n".join(
        f"  원칙 {p['n']}. {p['name']} — {p['apply']}" for p in _pick_principles(diag)[:3])
    weak = "\n".join(f"  - {w}" for w in diag["weak"]) or "  - 없음"
    common = f"""[보랏빛소 진단] 점수 {diag['score']}/4 — {diag['verdict']}
보완할 약점:
{weak}
훅 후보(수집 데이터 원문): {hooks}
적용 원칙:
{principles}
표현 규칙: 수집 글에 있는 숫자만 사용. 원문 문장을 그대로 베끼지 말고 재구성.
{prompt_ban_list()}"""
    if scene_level:
        return common + """
[이번 출력 범위] 지금은 씬 하나만 다시 쓴다. 마크다운·씬 번호·설명 금지.
요구된 JSON 오브젝트 하나만 출력한다."""
    return common + """
[씬 구성] 훅 → 결론 요약 → 본문 챕터(씬마다 주제어 재기입) → 반전/단점 고백 → 행동 유도"""
