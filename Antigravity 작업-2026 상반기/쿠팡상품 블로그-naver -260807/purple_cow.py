"""
purple_cow.py
세스 고딘 《보랏빛 소가 온다》 프레임워크 — 쿠팡 상품 콘텐츠에 리마커블함을 빌트인한다.

왜 필요한가:
  기존 coupang_blog_pipeline.py 의 theme_guide 는
  "제목: [쿠팡 핫딜] 어제보다 N원 내려간 ○○ 최저가 분석 / 서론: 인기 이유 / 본론: 가격 비교..."
  라는 구조였다. 수천 개 블로그가 똑같이 쓰는 형식이라 아무도 기억하지 못한다.
  고딘의 표현으로는 '갈색 소'다. 광고 문구를 다듬어서 해결되는 문제가 아니라,
  기획 단계에서 리마커블함을 심어야 한다.

이 모듈이 하는 일:
  1) diagnose()        실제 수집 데이터로 4가지 자가진단 질문에 답하고 점수를 매긴다
  2) build_blog_guide() 진단 결과에 맞는 블로그 원고 지침을 생성한다
  3) build_reels_guide() 릴스 대본용 지침을 생성한다

설계 원칙:
  진단은 반드시 '실제 수집된 값'에 근거한다. 데이터가 없으면 없다고 답한다.
  리마커블하지 않은 상품을 리마커블한 척 쓰는 건 고딘이 가장 경계한 것이다.
  평범한 상품이면 '평범하다'고 진단하고, 대신 8가지 실행 원칙에서 각도를 찾는다.
"""
import re
import json


# ════════════════════════════════════════════════════════════════
# 1. 퍼플카우 자가 진단 체크리스트 (4문항)
# ════════════════════════════════════════════════════════════════

CHECKLIST = [
    {
        "key": "one_second",
        "q": "단 1초 만에 제품의 차별성을 설명할 수 있는가?",
        "why": "1초를 넘기면 스크롤로 사라진다. 숫자 하나 또는 단어 하나로 끝나야 한다.",
    },
    {
        "key": "what_is_that",
        "q": "누구에게 보여줘도 '이건 뭐야?'라는 즉각적인 반응을 이끌어낼 수 있는가?",
        "why": "설명이 필요한 순간 리마커블함은 죽는다. 반응이 먼저 오고 설명이 뒤따라야 한다.",
    },
    {
        "key": "sneezer",
        "q": "스니저와 오타쿠들이 자발적으로 자랑하고 떠들 만한 매력 포인트가 있는가?",
        "why": "광고는 사서 하는 것이고 입소문은 벌어지는 것이다. 떠들 거리를 만들어 줘야 한다.",
    },
    {
        "key": "no_discount",
        "q": "가격을 깎아주지 않아도 독특함 때문에 사고 싶은 가치를 지녔는가?",
        "why": "할인으로만 팔리는 상품은 할인이 끝나면 잊힌다. 할인은 이유가 아니라 계기여야 한다.",
    },
]


# ════════════════════════════════════════════════════════════════
# 2. 퍼플카우를 작동시키는 8가지 실행 원칙
#    각 원칙을 '쿠팡 상품 콘텐츠 작성'이라는 현장에 대입해 두었다
# ════════════════════════════════════════════════════════════════

PRINCIPLES = [
    {
        "n": 1,
        "name": "제품 변화",
        "origin": "고객의 호감을 살 수 있도록 제품을 근본적으로 변화시키는 방법 10가지를 생각해 본다.",
        "apply": "상품 자체는 못 바꾸니 '쓰는 법'을 바꿔 제안한다. "
                 "판매자가 의도하지 않은 용도 10가지를 떠올리고 그중 가장 뜻밖의 1가지로 글을 연다.",
    },
    {
        "n": 2,
        "name": "초소형 시장 타깃",
        "origin": "가장 작은 시장을 먼저 정의하고, 그 틈새를 완전히 뒤흔들 제품을 그린다.",
        "apply": "'모두에게 좋은 상품'이라고 쓰지 않는다. 이 상품이 미치도록 필요한 단 한 사람을 "
                 "직업·상황·시간대까지 좁혀 지목하고, 그 한 사람만을 위해 쓴다.",
    },
    {
        "n": 3,
        "name": "아웃소싱",
        "origin": "핵심 역량에 집중하고 나머지는 아웃소싱한다.",
        "apply": "글은 '단 하나의 주장'만 책임진다. 스펙 나열·배송 정책·색상 옵션은 "
                 "링크와 이미지에 위임하고 본문에서 지운다.",
    },
    {
        "n": 4,
        "name": "허락자산 구축",
        "origin": "가장 충실한 고객들과 막힘없이 직접 얘기할 소통 구조를 만든다.",
        "apply": "글 끝에서 '다음에 또 오세요'가 아니라 '무엇을 언제 보내줄지' 약속한다. "
                 "예: 이 상품 가격이 다시 내려가면 알려드립니다.",
    },
    {
        "n": 5,
        "name": "타 산업 모방",
        "origin": "전혀 다른 산업에서 성공한 리마커블한 아이디어를 그대로 베낀다.",
        "apply": "커머스 리뷰 형식을 버리고 다른 장르의 형식을 빌린다. "
                 "실험 보고서 / 법정 판결문 / 부검 소견서 / 연애편지 / 사용설명서 오탈자 정정 공지 등.",
    },
    {
        "n": 6,
        "name": "정반대로 실행",
        "origin": "다른 회사들이 표준이라 믿는 방식을 완전히 뒤집어 시도한다.",
        "apply": "모두가 '사세요'로 시작할 때 '이런 사람은 사지 마세요'로 연다. "
                 "장점 앞에 단점을 먼저, 그것도 구체적으로 놓는다. 신뢰가 역으로 올라간다.",
    },
    {
        "n": 7,
        "name": "업계 최초 시도",
        "origin": "속한 산업에서 '아직 행해지지 않은 것'을 찾아 누구보다 먼저 실천한다.",
        "apply": "이 카테고리 리뷰에서 아무도 하지 않은 것을 하나 한다. "
                 "예: 경쟁 상품과 같은 조건에서 직접 비교, 실패 사례 공개, 원가 추정.",
    },
    {
        "n": 8,
        "name": "근본적인 의문",
        "origin": "관행적으로 이어져 온 방식에 항상 '왜 안 되는데?'라고 묻는다.",
        # 원래 "왜 이 가격이 가능한가를 추적하라"였다. 데이터에 답이 없는 질문이라
        # 모델이 원가·재고·유통 사정을 지어냈고, 그 문장이 그대로 발행됐다.
        # 답할 수 있는 질문으로 바꾼다 — 계산은 지어낼 수가 없다.
        "apply": "가격을 소개하지 말고 계산한다. '이걸 하나로 나누면 얼마인가?' "
                 "'100ml당으로 보면 어떤가?' 총액은 판단이 안 서지만 단가는 판단이 선다. "
                 "원가·재고 사정은 확인할 방법이 없으니 추측하지 않는다.",
    },
]


# ════════════════════════════════════════════════════════════════
# 3. 자가 진단 — 실제 수집 데이터로만 채점한다
# ════════════════════════════════════════════════════════════════

def _int(v, default=0):
    if v is None:
        return default
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"[\d,]+", str(v))
    return int(m.group(0).replace(",", "")) if m else default


def diagnose(product: dict, price_history: list = None) -> dict:
    """
    상품 데이터를 4가지 질문으로 진단한다.
    각 항목은 YES/NO 와 그 근거(실제 값)를 함께 남긴다.

    반환: {
      "score": 0~4, "verdict": str, "answers": [...],
      "hooks": [훅으로 쓸 수 있는 사실 문장들],
      "weak": [보강이 필요한 지점]
    }
    """
    p = product or {}
    hist = price_history or []

    disc = _int(p.get("discount_rate"))
    orig = _int(p.get("original_price"))
    curr = _int(p.get("current_price"))
    reviews = _int(p.get("review_count"))
    rating = float(p.get("rating") or 0)
    buyers = (p.get("monthly_buyers") or "").strip()
    delivery = (p.get("delivery_info") or "").strip()
    title = (p.get("title") or "").strip()

    specs = p.get("specs")
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except Exception:
            specs = {}
    specs = specs or {}

    answers, hooks, weak = [], [], []

    # ── Q1. 1초 만에 차별성을 말할 수 있는가
    #    숫자 하나로 끝나야 한다. 할인률 50% 이상이면 그 자체가 1초 메시지다.
    saved = orig - curr if orig > curr else 0
    if disc >= 50:
        answers.append({"key": "one_second", "yes": True,
                        "evidence": f"할인률 {disc}% — 반값 이하는 그 숫자 하나로 설명이 끝난다"})
        hooks.append(f"{disc}%")
    elif saved >= 50000:
        answers.append({"key": "one_second", "yes": True,
                        "evidence": f"절감액 {saved:,}원 — 금액 자체가 한 번에 와닿는 크기"})
        hooks.append(f"{saved:,}원 절감")
    else:
        answers.append({"key": "one_second", "yes": False,
                        "evidence": f"할인률 {disc}%, 절감 {saved:,}원 — 숫자만으로는 시선을 못 잡는다"})
        weak.append("숫자가 약하다. 가격 대신 '용도'나 '한 사람'으로 1초 메시지를 만들어야 한다(원칙 1·2)")

    # ── Q2. '이건 뭐야?' 반응을 끌어내는가
    #    가격의 이상함, 스펙의 특이함, 이름의 낯섦 중 하나라도 걸리면 YES
    odd = []
    if orig and curr and disc >= 70:
        odd.append(f"정가 {orig:,}원짜리가 {curr:,}원 — 가격 구조 자체가 의심스러울 만큼 벌어져 있다")
    # 행정용 메타 필드는 훅이 될 수 없다 — 되묻게 만드는 '제품 속성'만 남긴다.
    # 상세페이지를 수집하면 사업자등록번호·구매날짜 같은 행정 정보가 스펙에 섞여 들어와
    # "사업자 등록번호: 120-88-00767" 이 훅 후보로 올라온 적이 있다.
    BORING_KEY = ("번호", "등록", "날짜", "일자", "기한", "제조", "출시", "원산지",
                  "수입", "모델", "인증", "브랜드", "사업자", "통신판매", "연락처",
                  "주소", "대표", "상호", "소재지", "문의", "고객센터", "반품", "교환",
                  "A/S", "코드", "ID", "품번", "수입사", "판매자")
    for k, v in list(specs.items())[:12]:
        kv = str(k)
        vv = str(v)
        if any(b in kv for b in BORING_KEY):
            continue
        if re.match(r"^\s*\d{2,4}[.\-/]\d{1,2}[.\-/]\d{1,2}", vv):   # 날짜값
            continue
        if re.match(r"^\s*[\d\-]{8,}\s*$", vv):                      # 사업자번호·일련번호류
            continue
        if re.search(r"\d", vv) and len(vv) <= 30:
            odd.append(f"{kv}: {vv}")
    if odd:
        answers.append({"key": "what_is_that", "yes": True, "evidence": odd[0]})
        hooks.extend(odd[:2])
    else:
        answers.append({"key": "what_is_that", "yes": False,
                        "evidence": "가격·스펙 어디에도 되묻게 만드는 지점이 없다"})
        weak.append("낯섦이 없다. 다른 장르 형식을 빌리거나(원칙 5) 통념을 뒤집어(원칙 6) 만들어야 한다")

    # ── Q3. 스니저·오타쿠가 떠들 거리가 있는가
    #    이미 떠들고 있다는 증거 = 리뷰수, 월간 구매자수
    social = []
    if buyers:
        social.append(buyers)
    if reviews >= 1000:
        social.append(f"상품평 {reviews:,}개")
    # 평점은 판정 근거로만 쓰고 훅(=콘텐츠에 실릴 문구)에는 넣지 않는다.
    # 목록 수집분은 0.5 단위로 뭉뚱그려져 대부분 5.0 이라 그대로 실으면 과장이 되고,
    # 모델이 "리뷰가 전부 만점"으로 부풀려 쓴 사고도 있었다. 상품평 '개수'로 충분하다.
    # rating 은 판정 근거에서도 뺀다. 실측 79건 중 59건이 정확히 5.0 인 오염 컬럼이라
    # "평점이 높으니 사회적 증거가 있다"는 판정 자체가 성립하지 않는다.
    # evidence 는 프롬프트로 들어가므로, 여기에 남기면 오염값이 원고까지 흘러간다.
    if social:
        evidence = " · ".join(social)
        answers.append({"key": "sneezer", "yes": True, "evidence": evidence})
        hooks.extend(social[:2])
    else:
        answers.append({"key": "sneezer", "yes": False,
                        "evidence": f"리뷰 {reviews:,}개 / 월간 구매 데이터 없음 — 아직 떠드는 무리가 안 보인다"})
        weak.append("사회적 증거가 얇다. 남이 안 한 검증을 직접 해서 떠들 거리를 만들어야 한다(원칙 7)")

    # ── Q4. 할인 없이도 사고 싶은가
    #    가격 이력이 있으면 '할인이 상시인지'를 본다. 상시 할인이면 할인은 이유가 못 된다.
    prices = [_int(h.get("price")) for h in hist if _int(h.get("price"))]
    # 관측일이 3일 미만이면 '상시 할인'인지 판단할 근거가 없다.
    # 수집 첫날에는 값이 1개뿐이라 max==min 이 되어 무조건 상시가로 오판했었다.
    enough_history = len(prices) >= 3
    always_on_sale = (enough_history
                      and (max(prices) - min(prices)) / max(max(prices), 1) < 0.05)
    # rating 은 근거로 쓰지 않는다. 목록 화면에서 긁은 값이라 실측 79건 중 59건이 정확히 5.0 —
    # 이 게이트가 rating 만으로 79건 중 51건을 yes 로 통과시키고 있었다.
    # 월간 구매자 수(buyers)만 남긴다. yes 가 크게 줄지만, 그게 사실이다.
    unique_value = bool(buyers)
    if unique_value and not always_on_sale:
        answers.append({"key": "no_discount", "yes": True,
                        "evidence": "할인과 무관하게 사람들이 계속 사고 있다는 신호가 있다"})
    elif always_on_sale:
        answers.append({"key": "no_discount", "yes": False,
                        "evidence": f"{len(prices)}일간 가격 변동 5% 미만 — '오늘만 특가'가 사실은 상시가다"})
        weak.append("할인이 상시라 구매 이유가 못 된다. 가격 말고 다른 축으로 글을 세워야 한다(원칙 8)")
    elif not enough_history:
        answers.append({"key": "no_discount", "yes": False,
                        "evidence": f"가격 관측 {len(prices)}일치뿐 — 상시가인지 진짜 특가인지 아직 판단 불가"})
        weak.append("가격 이력이 3일 이상 쌓이기 전까지는 '최저가' 주장을 쓰지 마라. "
                    "지금은 가격 대신 용도나 타깃으로 글을 세워라(원칙 1·2)")
    else:
        answers.append({"key": "no_discount", "yes": False,
                        "evidence": "할인을 빼면 남는 구매 이유가 데이터에 드러나지 않는다"})
        weak.append("할인 의존형이다. '이 한 사람에게는 정가여도 싸다'는 각도가 필요하다(원칙 2)")

    score = sum(1 for a in answers if a["yes"])
    verdict = {
        4: "보랏빛 소 — 있는 사실만 정확히 배치해도 리마커블하다. 각색하지 마라.",
        3: "보랏빛에 가깝다 — 가장 강한 사실 하나를 맨 앞에 세우면 완성된다.",
        2: "회색 소 — 사실만으로는 부족하다. 형식이나 관점을 비틀어야 한다.",
        1: "갈색 소 — 상품 소개로 접근하면 반드시 묻힌다. 다른 장르를 빌려라.",
        0: "완전한 갈색 소 — 가격·스펙 이야기를 전부 버리고 사람 이야기로 다시 시작하라.",
    }[score]

    return {
        "score": score,
        "verdict": verdict,
        "answers": [
            {**a, "q": next(c["q"] for c in CHECKLIST if c["key"] == a["key"])}
            for a in answers
        ],
        "hooks": hooks,
        "weak": weak,
        "title": title,
    }


def _pick_principles(diag: dict) -> list:
    """진단 결과에 따라 지금 이 상품에 가장 필요한 실행 원칙을 고른다."""
    score = diag["score"]
    yes = {a["key"] for a in diag["answers"] if a["yes"]}

    picked = []
    if "one_second" not in yes:
        picked += [1, 2]          # 1초 메시지가 없으면 용도 변경·타깃 압축
    if "what_is_that" not in yes:
        picked += [5, 6]          # 낯섦이 없으면 장르 차용·정반대 실행
    if "sneezer" not in yes:
        picked += [7]             # 떠들 거리가 없으면 업계 최초 시도
    if "no_discount" not in yes:
        picked += [8, 2]          # 할인 의존이면 근본 의문·타깃 압축
    picked += [3, 4]              # 아웃소싱·허락자산은 항상 적용

    if score >= 3:                # 이미 리마커블하면 덜어내는 쪽에 무게
        picked = [3, 4, 6]

    seen, out = set(), []
    for n in picked:
        if n not in seen:
            seen.add(n)
            out.append(next(p for p in PRINCIPLES if p["n"] == n))
    return out[:5]


# ════════════════════════════════════════════════════════════════
# 4. 프롬프트 생성기
# ════════════════════════════════════════════════════════════════

def build_blog_guide(product: dict, price_history: list = None, diag: dict = None) -> str:
    """
    블로그 원고용 지침을 만든다. coupang_blog_pipeline 의 theme_guide 자리에 넣는다.
    기존의 '서론-본론1-본론2-결론' 정형을 대체한다.
    """
    d = diag or diagnose(product, price_history)
    principles = _pick_principles(d)
    title = (product.get("title") or "").strip()
    affiliate = product.get("affiliate_url") or product.get("detail_url") or ""

    diag_lines = "\n".join(
        f"    {'✔' if a['yes'] else '✘'} {a['q']}\n       → {a['evidence']}"
        for a in d["answers"]
    )
    principle_lines = "\n".join(
        f"    원칙 {p['n']}. {p['name']}\n"
        f"       고딘: {p['origin']}\n"
        f"       적용: {p['apply']}"
        for p in principles
    )
    hook_line = " / ".join(d["hooks"][:3]) if d["hooks"] else "(데이터에서 뽑을 훅 없음)"
    weak_line = "\n".join(f"    - {w}" for w in d["weak"]) if d["weak"] else "    - 없음"

    return f"""
[보랏빛 소 진단 결과] — 세스 고딘 《보랏빛 소가 온다》 기준
    진단 점수: {d['score']}/4
    판정: {d['verdict']}

{diag_lines}

    데이터에서 뽑은 훅 후보: {hook_line}
    보강이 필요한 지점:
{weak_line}

[이 글에 반드시 적용할 실행 원칙]
{principle_lines}

[작성 지침 — 아래를 그대로 따를 것]

1. 제목
   "[쿠팡 핫딜] ○○ 최저가 분석" 같은 형식을 절대 쓰지 마라. 그건 갈색 소다.

   **제목에는 브랜드와 상품명이 반드시 들어가야 한다.** 검색으로 찾아오는 사람은
   상품명으로 검색한다. 훅만 남기고 상품명을 빼면 아무도 그 글에 도달하지 못한다.

   구성: [브랜드 + 상품명 + 핵심 사양] + [훅 후보 중 가장 강한 것 하나]
   예) 빙그레 아카페라 아메리카노 1L 12개, 167,700원이 18,080원

   훅은 하나만 쓴다. 두 개 이상 넣으면 둘 다 약해진다.

   **34자 안쪽으로 맞춰라.** 검색결과는 40자 안팎에서 잘리는데, 발행할 때
   쿠팡 파트너스 표시 "[광고]" 4자가 제목 앞에 자동으로 붙는다. 그 자리를 남겨 둬야 한다.
   ("[광고]" 를 직접 쓰지는 마라 — 발행 단계에서 붙인다. 두 번 붙으면 자리만 낭비다)

   길이를 줄이려면 규격을 덜어내라. '45g, 5개입, 1개' 는 '5개입' 만 남기면 된다.

2. 첫 문단
   상품 이름으로 시작하지 마라. 인사말도 쓰지 마라.
   원칙 2에 따라 지목한 '단 한 사람'의 구체적 상황으로 시작하라.
   (예: 시간대, 직업, 그 사람이 오늘 겪은 불편)

3. 본문
   '단 하나의 주장'만 책임진다(원칙 3). 스펙 나열·배송 정책·옵션 설명은 넣지 마라.
   주장을 뒷받침하는 사실만 남기되, 그 사실은 반드시 아래 [상품 데이터]에 있는 값이어야 한다.
   데이터에 없는 수치·효능·후기를 지어내면 파트너스 정책 위반이자 거짓이다.

   **분량: 공백 포함 500~700자.** 이 범위를 넘기지 마라.
   한 문단은 2~3문장, 전체 4~5문단이면 충분하다.
   사진이 함께 들어가므로 글이 길면 읽는 사람이 스크롤로 흘려보낸다.
   같은 말을 다르게 반복하지 말고, 수식어를 덜어내라. 덜어낼수록 강해진다(원칙 3).

4. 단점 먼저
   원칙 6에 따라 장점보다 단점을 먼저, 그것도 구체적으로 써라.
   "이런 사람에게는 권하지 않는다"를 실제로 써라. 신뢰가 여기서 만들어진다.

5. 가격
   가격을 소개하지 말고 **계산하라**.
   정가·판매가·할인율·절감액을 쓰되, 아래 [상품 데이터]에 파생 단가(개당·100ml당)가
   있으면 반드시 함께 써라. 총액은 싼지 비싼지 알 수 없는 숫자지만,
   "12개니까 개당 1,507원"은 판단이 서는 숫자다.

   **"왜 이 가격이 가능한가"는 쓰지 마라.** 원가·재고·유통 사정은 데이터에 없다.
   예전 지침이 이걸 시켰고, 그래서 "재고 소진이 아닌 파격적인 마케팅 전략 덕분에"라는
   완전한 창작이 실제로 발행됐다. 모르는 것은 모른다고 쓰거나, 쓰지 마라.
   할인률을 자랑하는 문장도 금지. 할인은 이유가 아니라 계기다.

5-1. 문단을 통째로 떼어내도 말이 되게 써라
   생성형 검색(AI 브리핑, ChatGPT 등)과 검색엔진은 문단을 앞뒤 문맥 없이 뽑아 간다.
   앞 문단을 읽어야 이해되는 문단은 인용되지 못하고 버려진다.
   - 문단마다 **브랜드+상품명을 다시** 써라. "이 제품", "위의", "그것" 금지.
   - 숫자를 쓸 때마다 **언제 확인한 값인지** 붙여라.
   - 나쁨: "그래서 이 가격이면 사도 됩니다."
   - 좋음: "빙그레 아카페라 아메리카노 1L 12개는 2026년 8월 10일 확인 기준 18,080원이었다.
            12개로 나누면 개당 1,507원, 100ml당 150.7원이다."
   분량을 늘리라는 뜻이 아니다. 같은 500~700자 안에서 지시대명사를 이름으로 바꾸면 된다.

6. 마무리
   원칙 4에 따라 무엇을 언제 보내줄지 구체적으로 약속하라.
   "다음에 또 오세요"는 약속이 아니다.

7. 필수 고지 (생략 불가)
   "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

8. 구매 링크
   {affiliate}

[금지 표현]
   "역대급", "지금이 기회", "품절 임박", "강력 추천", "가성비 갑", "안 사면 후회"
   — 전부 갈색 소의 언어다. 하나라도 쓰면 글 전체가 평범해진다.

   "NO.1", "1위", "최고", "최상", "유일", "최저가", "국내 최초" 등 순위·최상급 주장도 금지.
   상품 상세페이지나 패키지에 그렇게 적혀 있어도 옮겨 쓰지 마라.
   근거를 댈 수 없는 순위 주장은 표시광고법 위반 소지가 있다.

[숫자를 다루는 법]
   평점은 '평균'이다. "리뷰가 모두 만점", "전원 5점" 처럼 개별 리뷰를 단정하지 마라.
   상품평 개수는 '평가를 남긴 사람 수'이지 '구매자 수'가 아니다.
   참조 문서에 없는 수치는 만들지 말고, 있는 수치도 부풀려 해석하지 마라.
""".strip()


def build_reels_guide(product: dict, price_history: list = None, diag: dict = None,
                      scene_level: bool = False) -> str:
    """
    릴스 대본용 지침. 영상은 글보다 더 짧으므로 1초 규칙이 절대적이다.

    scene_level=True 로 부르면 '씬 구성' 지침을 뺀다.
    씬 하나짜리 프롬프트에 전체 구성 규칙을 넣으면 모델이 스토리보드를
    통째로 만들어 버려서 자막 파싱이 깨진다(실제로 겪은 문제).
    """
    d = diag or diagnose(product, price_history)
    principles = _pick_principles(d)
    hook_line = " / ".join(d["hooks"][:3]) if d["hooks"] else "(없음 — 사실 대신 상황으로 열어라)"

    principle_lines = "\n".join(f"    원칙 {p['n']}. {p['name']} — {p['apply']}" for p in principles[:3])

    common = f"""[보랏빛 소 지침]
    진단 {d['score']}/4 — {d['verdict']}
    훅 후보: {hook_line}

{principle_lines}

[표현 규칙]
- 화면 자막 = 사실(숫자·조건). 음성 나레이션 = 그 사실이 나에게 주는 이점.
  같은 문장을 자막과 음성에 중복해서 넣지 마라.
- 금지어: "역대급", "지금이 기회", "품절 임박", "강력 추천", "가성비 갑", "핫딜", "폭풍"
- 순위·최상급 주장 금지: "NO.1", "1위", "최고", "최상", "유일", "최저가", "국내 최초".
  상품 사진의 패키지에 그렇게 적혀 있어도 옮겨 쓰지 마라 — 근거를 댈 수 없는 순위 주장은
  표시광고법 문제가 된다.
- 데이터에 없는 수치·효능·후기를 지어내지 마라. 위 훅 후보에 있는 값만 쓴다."""

    if scene_level:
        return (common + """

[이번 출력 범위 — 반드시 지킬 것]
- 지금은 씬 '하나'의 자막과 나레이션만 만든다. 여러 씬을 만들지 마라.
- 마크다운(**, ##), 씬 번호, 해설, 추가 설명을 쓰지 마라.
- 정확히 두 줄만 출력한다. 그 외 텍스트가 한 글자라도 있으면 실패다.""").strip()

    return (common + """

[씬 구성]
    훅 → 뜻밖의 용도 또는 단점 고백 → 근거 사실 → 한 사람 지목 → 행동 유도
    각 씬은 한 가지만 말한다. 첫 1초는 상품명이 아니라 훅 후보의 숫자로 연다.""").strip()


def summary_text(diag: dict) -> str:
    """대시보드·로그에 한 줄로 찍을 요약."""
    marks = "".join("✔" if a["yes"] else "✘" for a in diag["answers"])
    return f"보랏빛소 {diag['score']}/4 [{marks}] {diag['verdict'].split('—')[0].strip()}"


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 66)
    print("보랏빛 소 자가 진단 체크리스트")
    print("=" * 66)
    for c in CHECKLIST:
        print(f"\n  Q. {c['q']}\n     {c['why']}")

    print("\n" + "=" * 66)
    print("퍼플카우를 작동시키는 8가지 실행 원칙")
    print("=" * 66)
    for p in PRINCIPLES:
        print(f"\n  {p['n']}. {p['name']}")
        print(f"     고딘: {p['origin']}")
        print(f"     적용: {p['apply']}")

    # DB에 실측 상품이 있으면 실제로 진단해 본다
    try:
        import sqlite3, os
        db = os.path.join(os.path.dirname(os.path.abspath(__file__)), "price_history.db")
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cols = {r[1] for r in cur.execute("PRAGMA table_info(products)")}
        where = "WHERE is_real=1" if "is_real" in cols else ""
        rows = cur.execute(
            f"SELECT * FROM products {where} ORDER BY discount_rate DESC LIMIT 3").fetchall()
        if rows:
            print("\n" + "=" * 66)
            print("DB 상품 실제 진단")
            print("=" * 66)
            for r in rows:
                prod = dict(r)
                hist = [dict(h) for h in cur.execute(
                    "SELECT price, discount_rate FROM price_history WHERE product_id=? "
                    "ORDER BY price_date DESC LIMIT 14", (prod["product_id"],))]
                d = diagnose(prod, hist)
                print(f"\n  {prod['title'][:44]}")
                print(f"  {summary_text(d)}")
                for a in d["answers"]:
                    print(f"     {'✔' if a['yes'] else '✘'} {a['evidence'][:76]}")
        conn.close()
    except Exception as e:
        print(f"\n(DB 진단 건너뜀: {e})")
