"""
발행 직전에 원고를 검사한다. 프롬프트로 부탁하는 것과 달리 여기는 통과 못 하면 못 나간다.

첫 판은 금지어 목록이었고, 정확히 거꾸로 동작했다:
  "구매자의 80%가 만족했습니다"        → 통과 (날조인데)
  "써 본 결과 흡수가 빨랐습니다"       → 통과 (안 써봤는데)
  "역대 가장 싼 가격입니다"            → 통과 ('역대급'만 막았으니까)
  "최저가인지 아닌지 확인할 수 없습니다"  → 차단 (정직한 문장인데)
날조 44개 중 42개가 통과했고, 정직한 부정문은 막혔다.

원인은 구조다. **날조는 열거할 수 없다.** 표현은 무한하다.
그래서 열거할 수 있는 쪽으로 뒤집는다:

  1. 숫자 대조 — 본문의 모든 숫자는 [실측 데이터]에 있어야 한다.
     "80%", "10명 중 9명", "반품률 2%" 는 전부 여기서 걸린다. 표현을 바꿔도 못 피한다.
     이게 이 모듈의 중심이다.
  2. 어휘 검사 — 그래도 숫자 없는 거짓("이보다 싼 곳은 없습니다")이 있으니 보조로 둔다.
     단, 부정·유보 문맥에서는 통과시킨다. 안 그러면 정직한 글이 막힌다.
  3. 공백 우회 차단 — '최 저 가' 같은 회피를 막기 위해 검사 전에 공백을 지운 사본도 본다.
"""
import re

# ── 1. 부정·유보 문맥 ────────────────────────────────────────────
# 이 표현들이 같은 문장 안에 있으면, 금지어가 나와도 '주장'이 아니라 '부인'이다.
#   "최저가인지 확인할 수 없습니다"  → 최저가를 주장하는 게 아니다
#   "상품평 개수는 만족도가 아니다"  → 만족도를 주장하는 게 아니다
_HEDGE = re.compile(
    r"(확인할\s*수\s*없|알\s*수\s*없|판단할\s*수\s*없|answer|답할\s*수\s*없|"
    r"아니(다|라|며|고|에요|입니다|랍니다)|아님|"
    r"모른다|모릅니다|쓰지\s*않|쓸\s*수\s*없|말할\s*수\s*없|"
    r"근거가\s*없|데이터가\s*없|기록이\s*없|검증할\s*수\s*없|"
    r"보장하지\s*않|의미하지\s*않|뜻하지\s*않)")

# ── 2. 어휘 검사 ─────────────────────────────────────────────────
# 여기 없는 표현이 얼마든지 있다는 걸 전제하고 쓴다. 주력은 숫자 대조다.
CAUSAL = [
    (r"덕분에|덕에", "근거 없는 인과"),
    (r"때문에\s*가능|결과\s*이\s*가격|그래서\s*이\s*가격", "근거 없는 인과"),
    (r"재고\s*(소진|정리|떨이)|재고가\s*(얼마|거의|별로)", "재고 상황은 확인할 수 없다"),
    (r"(마케팅|유통|물량|가격)\s*전략|유통\s*단계를\s*(줄|축소|없)", "내부 사정은 확인할 수 없다"),
    (r"(원가|마진)\w*\s*(를|을|이|가)?\s*(낮|줄|없앤|없애|포기|최소)", "원가 데이터가 없다"),
    (r"신선(한|하다|합니다|해서|도가)", "신선도를 확인할 방법이 없다"),
    (r"(증명|입증)(하는|한다|합니다|된|되는)", "숫자는 무엇도 증명하지 않는다"),
    (r"만족(도|했|하고\s*있|스러웠|한다는)", "리뷰 개수는 만족을 뜻하지 않는다"),
    (r"(검증|보장)(된|됐|합니다|됩니다|해)", "검증·보장 주체가 없다"),
    (r"재구매(율|했|하는\s*사람)", "재구매 데이터가 없다"),
    (r"반품률|불량률|고장률", "그런 통계는 수집하지 않는다"),
]

SUPERLATIVE = [
    (r"역대\s*급?|역대\s*가장|사상\s*최", ""),
    (r"지금이\s*기회|지금\s*사지\s*않으면|놓치면|서두르|서둘러", ""),
    (r"품절\s*임박|얼마\s*남지\s*않|마감\s*임박|한정\s*수량", ""),
    (r"최저가|가장\s*싼|(이보다|더)\s*싼\s*(곳|데|가격)?[은는이가]?\s*없", ""),
    (r"국내\s*최초|세계\s*최초|업계\s*최", ""),
    (r"NO\.?\s*1|넘버\s*원|1위|일등", ""),
    (r"최고(의|급|다|입니다)|최상(의|급)|최적(의)?\s*선택", ""),
    (r"유일(한|무이)", ""),
    (r"강력\s*추천|무조건\s*사|안\s*사면\s*후회|후회하지\s*않", ""),
    (r"가성비\s*(갑|최고|끝판)", ""),
]

# ── 3. 1인칭 사용 경험 ───────────────────────────────────────────
# 쓰지 않은 물건을 써본 것처럼 말하는 것. 표시광고법 추천·보증 심사지침 위반이다.
FIRST_PERSON = [
    r"직접\s*(써|사용|테스트|해)\s*(보|봤|본|봐)",
    r"제가\s*(써|사용|구매|구입|주문|받아)",
    r"저도\s*(써|사용|구매|구입|주문)",
    r"써\s*(봤|보니|보았|\s*본\s*결과)",
    r"사용(해|하고)\s*(보니|본\s*결과|봤|봤더니)",
    r"먹어\s*(봤|보니)|발라\s*(봤|보니)|입어\s*(봤|보니)|신어\s*(봤|보니)",
    r"내돈내산|체험기|사용기|솔직\s*후기",
    r"(받아|배송\s*받)(보니|봤)",
]

_NUM = re.compile(r"\d[\d,]*\.?\d*")
#: 숫자 대조에서 뺄 것 — 날짜·시각처럼 본문에서 자연스럽게 생기는 값
_DATE_CTX = re.compile(r"(년|월|일|시|분|초|번째|층|호|세기)")


def _squash(s: str) -> str:
    """'최 저 가' 같은 공백 우회를 막기 위해 공백을 지운 사본."""
    return re.sub(r"\s+", "", s or "")


def _sentences(text: str) -> list:
    return [s for s in re.split(r"(?<=[.!?。])\s+|\n+", text or "") if s.strip()]


def _numbers_with_ctx(text: str) -> list:
    """(값, 그 숫자 주변 텍스트) 목록. 날짜 판별에 주변 문맥이 필요하다."""
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
        # 원 단위 반올림 표기 차이를 흡수한다(1,506.7 → 1,507)
        vals.add(round(v))
    return vals


def _derivable(v: float, known: set) -> bool:
    """
    실측값끼리의 단순 계산으로 나오는 값인가?

    지침이 "개당 단가를 직접 계산해 써라"라고 시키므로, 모델이 3,390 ÷ 8 = 424 를
    본문에 쓰는 것은 정상이다. 그런데 424 는 컨텍스트에 없으니 그대로 두면 차단된다 —
    시키는 대로 하면 막히는 모순이 생긴다.

    그래서 **뺄셈과 나눗셈만** 허용한다. 이 둘이 실제로 요구하는 연산이다
    (절감액 = 정가 − 판매가, 개당 단가 = 판매가 ÷ 수량).
    곱셈·덧셈은 허용하지 않는다 — 허용 범위를 넓힐수록 지어낸 수가 우연히 통과한다.
    나누는 수는 수량으로 볼 수 있는 작은 정수로 제한한다.
    """
    if v <= 0:
        return False
    for a in known:
        if a <= 0:
            continue
        for b in known:
            if b <= 0 or b == a:
                continue
            if abs((a - b) - v) < 0.51:                 # 절감액·차액
                return True
            if 2 <= b <= 1000 and float(b).is_integer():   # 수량으로 나눈 단가
                q = a / b
                if abs(q - v) < 0.51 or abs(round(q) - v) < 0.51:
                    return True
    return False


#: 대가성 고지를 무력화하는 조건부·불확정 표현.
#: 쿠팡 파트너스 공식 가이드가 "수수료를 제공받을 수 있습니다" 를 부적합 예시로 못박았다.
#: "받습니다"(확정)여야 하고 "받을 수 있습니다"(조건부)면 승인이 거부된다.
_WEAK_DISCLOSURE = re.compile(
    r"수수료를?\s*제공\s*받을\s*수\s*(있|도)|수수료가?\s*(발생|지급)될\s*수\s*있|"
    r"일부\s*수수료를?\s*받을\s*수")


def check_disclosure(content: str, title: str = "") -> list:
    """
    쿠팡 파트너스 승인 기준을 검사한다. 원고 품질과 별개로, 이걸 어기면 계정이 위험하다.

    표시 위치는 **제목 또는 게시물 첫 부분** 중 하나면 된다(공식 가이드·공정위 지침 모두
    '또는' 이다). 그래서 둘 중 어느 쪽으로 표시했는지에 따라 검사 기준이 달라진다.

      제목에 [광고] 가 있으면      → 본문 고지 위치는 느슨하게 본다
      제목에 표시가 없으면(기본)   → **본문 고지가 맨 앞이어야 한다**. 그게 유일한 표시다

    나머지 두 가지는 어느 경우든 지켜야 한다:
      · 고지 문구가 본문에 있을 것
      · 확정 표현일 것 — "제공받습니다". 조건부("받을 수 있습니다")는 부적합
    """
    problems = []
    body = content or ""
    titled = bool(re.match(r"^\s*\[?\s*(광고|AD|Ad|ad)\s*\]?", title or ""))

    m = _WEAK_DISCLOSURE.search(body)
    if m:
        problems.append(f"고지가 조건부 표현이다 '{m.group(0)}' — '제공받습니다'로 확정해야 한다")

    if "쿠팡 파트너스 활동의 일환" not in body:
        problems.append("대가성 고지 문구가 본문에 없다")
        return problems

    head = body[:body.index("쿠팡 파트너스 활동의 일환")]
    if re.search(r"!\[|<img|https?://|^#\S+", head, re.M):
        problems.append("고지 앞에 이미지·링크·태그가 있다 — 고지가 첫 부분이어야 한다")
    else:
        # 제목 표시가 없으면 본문 고지가 유일한 표시이므로 자리를 더 엄격히 본다.
        limit = 120 if titled else 40
        n = len(head.strip())
        if n > limit:
            problems.append(
                f"고지가 본문 {n}자 뒤에 있다 — 맨 앞으로 올려야 한다"
                + ("" if titled else " (제목에 [광고] 표시가 없어 본문 고지가 유일한 표시다)"))
    return problems


def check(content: str, context: str = "", title: str = "") -> dict:
    """
    원고를 검사한다.

    context: 프롬프트에 넣은 [실측 데이터] 블록. 본문 숫자의 유일한 출처다.
    title:   제목도 함께 검사한다(제목은 검사에서 빠져 있었다).
    """
    text = ((title + "\n") if title else "") + (content or "")
    blocking, warnings = [], []

    for sent in _sentences(text):
        hedged = bool(_HEDGE.search(sent))
        squashed = _squash(sent)
        for pats, kind in ((CAUSAL, "근거 없는 서술"), (SUPERLATIVE, "검증 불가한 표현")):
            for pat, why in pats:
                m = re.search(pat, sent) or re.search(_squash(pat), squashed)
                if not m:
                    continue
                if hedged:
                    # "최저가인지 확인할 수 없다" — 주장이 아니라 부인이다. 통과시킨다.
                    continue
                blocking.append(f"{kind} '{m.group(0)}'" + (f" — {why}" if why else ""))
        for pat in FIRST_PERSON:
            m = re.search(pat, sent)
            if m:
                blocking.append(f"사용 경험 사칭 '{m.group(0)}' — 쓰지 않은 물건이다")

    # ── 숫자 대조: 이게 주력이다 ──
    # 본문에 있는데 실측 데이터에 없는 숫자는 지어낸 값이다. 표현을 바꿔도 못 피한다.
    if context:
        known = _known_numbers(context)
        seen = set()
        for v, tail in _numbers_with_ctx(text):
            if v in seen:
                continue
            seen.add(v)
            if _DATE_CTX.match(tail.strip()[:1] or " ") or _DATE_CTX.search(tail[:2]):
                continue                      # 날짜·시각 표기
            if v in known or round(v) in known:
                continue
            if any(abs(v - k) <= max(1.0, abs(k) * 0.005) for k in known):
                continue                      # 반올림 오차
            if _derivable(v, known):
                continue                      # 실측값에서 계산해 낼 수 있는 값
            blocking.append(
                f"실측 데이터에 없는 숫자 {v:,.10g} — 지어낸 값이거나 출처가 없다")
    else:
        warnings.append("실측 데이터가 없어 숫자 대조를 건너뛰었다 — 검사가 약해진다")

    # 같은 지적이 여러 번 나오면 한 번만 남긴다
    blocking = list(dict.fromkeys(blocking))
    return {"ok": not blocking, "blocking": blocking, "warnings": warnings}


def enforce(content: str, context: str = "", logger_func=print,
            title: str = "", raise_on_fail: bool = False) -> dict:
    """검사하고 결과를 로그로 남긴다."""
    r = check(content, context, title)
    for w in r["warnings"]:
        logger_func(f"  ⚠️ {w}")
    for b in r["blocking"][:12]:
        logger_func(f"  ⛔ {b}")
    if not r["ok"]:
        logger_func(f"  ⛔ 원고 검사 실패 — {len(r['blocking'])}건")
        if raise_on_fail:
            raise ValueError("원고 검사 실패: " + " / ".join(r["blocking"][:3]))
    return r


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    CTX = ("- 정가: 12,000원\n- 현재 판매가: 1,760원 (할인율 85%)\n"
           "- 정가 대비 절감액: 10,240원\n- 상품평 수: 1,963개")

    MUST_BLOCK = [
        "재고 소진이 아닌 마케팅 전략 덕분에 가능한 가격이죠",
        "2024년 10월 24일 제조된 신선한 제품입니다",
        "1,963개 상품평이 증명하는 꾸준한 만족도",
        "제가 직접 써보니 흡수가 잘 됐습니다",
        "써 본 결과 흡수가 빨랐습니다",
        "구매자의 80%가 만족했습니다",
        "10명 중 9명이 재구매했습니다",
        "반품률이 2%에 불과합니다",
        "유통 단계를 줄인 결과 이 가격이 됐습니다",
        "마진을 없앤 데 있습니다",
        "역대 가장 싼 가격입니다",
        "이보다 싼 곳은 없습니다",
        "재고가 얼마 남지 않았습니다",
        "최 저 가 입니다",
        "지금 사지 않으면 후회합니다",
        "별점 4.8점의 검증된 제품입니다",
    ]
    MUST_PASS = [
        "미샤 소프트 면봉은 2026년 8월 11일 확인 기준 1,760원이었다.",
        "정가 12,000원에서 10,240원 낮은 가격이다.",
        "상품평은 1,963개다. 개수일 뿐 만족한 사람 수가 아니다.",
        "최저가인지 아닌지 이 글은 확인할 수 없다.",
        "재고 소진 여부는 알 수 없다.",
        "이 글은 상품평을 읽지 않았다. 실사용 평가가 필요하면 직접 확인하라.",
        "별점은 신뢰할 만큼 정확히 수집하지 못해 쓰지 않는다.",
    ]

    print("■ 차단되어야 하는 문장")
    miss = 0
    for t in MUST_BLOCK:
        r = check(t, CTX)
        blocked = not r["ok"]
        if not blocked:
            miss += 1
        print(f"  [{'차단' if blocked else '누락'}] {t}")
        if not blocked:
            print("         ↑ 통과해 버렸다")

    print("\n■ 통과되어야 하는 문장")
    false_pos = 0
    for t in MUST_PASS:
        r = check(t, CTX)
        mark = "OK  " if r["ok"] else "오차단"
        if not r["ok"]:
            false_pos += 1
        print(f"  [{mark}] {t}")
        if not r["ok"]:
            for b in r["blocking"]:
                print(f"         ⛔ {b}")

    print(f"\n차단 누락 {miss}/{len(MUST_BLOCK)} · 오차단 {false_pos}/{len(MUST_PASS)}")
