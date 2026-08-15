"""
coupang_blog_pipeline.py
쿠팡 TOP 100 상품 선택 후 AI 릴스 + 가격 변동 동적 위젯 + 네이버 블로그 원클릭 자동 포스팅 파이프라인
"""
import os
import re
import sys
import json
import logging
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import coupang_collector as collector
import price_widget_server as widget_server
import reels_generator as reels
import config as cfg
import purple_cow
import unit_price
import guardrails

def _category_word(title: str, product: dict) -> str:
    """
    상품명에서 '검색될 만한 카테고리어'를 뽑는다.

    쿠팡 상품명은 '브랜드 + 제품명 + 규격, 수량' 구조라, 앞에서 자르면 브랜드 조각만 남는다.
    실제 검색량은 카테고리어에 있다(예: '카놀라유' 60~100 vs '해표 카놀라유' 0.7~2.9).
    첫 구(콤마 앞)에서 브랜드와 규격을 걷어낸 뒤 마지막 명사구를 쓴다.
    """
    head = re.split(r"[,(]", title or "")[0].strip()
    brand = (product.get("brand") or "").strip()
    if brand and head.startswith(brand):
        head = head[len(brand):].strip()
    # 용량·치수·수량 토큰은 카테고리어가 아니다
    words = [w for w in head.split()
             if not re.match(r"^\d", w) and not re.search(r"\d\s*(ml|l|g|kg|mm|cm|개|매|입|종)$", w, re.I)]
    # '세트', '리필' 같은 포장 형태는 검색어가 못 된다.
    # '드라이버 8종 세트'에서 뽑아야 할 건 '세트'가 아니라 '드라이버'다.
    STOP = {"세트", "패키지", "기획", "기획전", "묶음", "대용량", "리필", "리필용",
            "본품", "증정", "선물", "선물용", "구성", "종합", "모음", "특가", "행사"}
    words = [w for w in words if w not in STOP] or words
    # '48mm x 40m' 의 'x' 처럼 규격 표기 조각이 남는 경우를 걷어낸다
    words = [w for w in words if not re.fullmatch(r"[a-zA-Z]{1,2}", w)] or words
    return words[-1] if words else ""


def _build_post_inputs(product: dict, logger_func=print) -> dict:
    """
    상품 데이터로 원고 생성 입력 일체를 만든다.
    run_coupang_pipeline 과 generate_post_draft 가 같은 입력을 쓰도록 한 곳에 모았다.

    참조 문서(context)에는 '실제로 관측한 값'만 넣는다. 데이터가 없는 항목은
    기본값으로 메우지 말고 아예 빼야 한다 — 예전에는 평점이 없으면 4.8,
    리뷰수가 없으면 1200 을 채워 넣어 원고에 없는 사실이 실렸다.
    """
    pid = str(product["product_id"])
    comp = product.get("comparison", {}) or {}
    title = product.get("title", "")
    curr = product.get("current_price", 0)
    orig = product.get("original_price", 0)
    disc = product.get("discount_rate", 0)

    # 관측 시각을 맨 앞에 둔다.
    # 지침(5-1)이 "숫자마다 언제 확인한 값인지 붙여라"라고 요구하는데 컨텍스트에 날짜가
    # 없어서 모델이 "쿠팡 확인 기준"까지만 쓰고 날짜를 못 넣었다. 문단을 통째로 떼어냈을 때
    # 시점을 알 수 없으면 생성형 검색이 인용하지 못한다.
    observed = _observed_date(product.get("updated_at", ""))
    lines = []
    if observed:
        lines.append(f"- 이 데이터를 확인한 시점: {observed} "
                     "(본문에서 가격을 말할 때 반드시 이 날짜를 함께 쓸 것)")
    lines.append(f"- 상품명: {title}")
    if product.get("brand"):
        lines.append(f"- 브랜드: {product['brand']}")
    if product.get("category"):
        lines.append(f"- 카테고리: {product['category']}")
    if orig:
        lines.append(f"- 정가: {orig:,}원")
    if curr:
        lines.append(f"- 현재 판매가: {curr:,}원" + (f" (할인율 {disc}%)" if disc else ""))
    if orig and curr and orig > curr:
        lines.append(f"- 정가 대비 절감액: {orig - curr:,}원")
    # 파생 단가. 산술 결과라 지어낼 수가 없고, 쿠팡 페이지에는 없는 값이라
    # 이 글에만 있는 정보가 된다. 계산 과정을 같이 넘겨 모델이 검산할 수 있게 한다.
    lines.extend(unit_price.context_lines(title, curr))
    if comp.get("yesterday_price") and comp.get("diff"):
        st = "내림" if comp.get("status") == "down" else "오름"
        lines.append(f"- 어제 {comp['yesterday_price']:,}원 → 오늘 {curr:,}원 "
                     f"({abs(comp['diff']):,}원 {st})")
    if product.get("review_count"):
        lines.append(f"- 상품평 수: {product['review_count']:,}개")
    if product.get("monthly_buyers"):
        lines.append(f"- 최근 구매 규모: {product['monthly_buyers']}")
    if product.get("delivery_info"):
        lines.append(f"- 배송: {product['delivery_info']}")
    specs = product.get("specs")
    if isinstance(specs, str):
        try:
            specs = json.loads(specs)
        except Exception:
            specs = {}
    if specs:
        # 평점·만족도는 specs 로도 새어 들어온다.
        # ('퀵디 뚫어뻥' specs 에 "만족도: 4.8/5" 가 있었다)
        # 위에서 rating 을 뺀 이유가 그대로 적용된다. 게다가 이 값을 원고에 쓰면
        # guardrails 가 '만족도' 를 차단해서, 우리가 준 데이터 때문에 발행이 막힌다.
        _BAN = re.compile(r"만족도|평점|별점|후기|리뷰\s*점수|추천\s*지수")
        shown = 0
        for k, v in specs.items():
            if shown >= 6:
                break
            if _BAN.search(str(k)) or _BAN.search(str(v)):
                continue
            lines.append(f"- {k}: {v}")
            shown += 1
    lines.append(f"- 구매 링크: {product.get('affiliate_url') or product.get('detail_url', '')}")

    # 평점은 원고에 넣지 않는다.
    # 목록 페이지 값은 0.5 단위로 뭉뚱그려져 대부분 5.0 으로 내려오는데,
    # 그걸 넣었더니 모델이 "상품평 7만 5천 개가 모두 5.0 만점"이라고 썼다.
    # 5.0 은 평균이지 전원 만점이 아니다. 상세 수집의 정밀 평점이 안정화되기 전까지는
    # 상품평 '개수'만으로도 사회적 증거는 충분하다.

    context = ("[쿠팡에서 실제로 수집한 상품 정보 — 아래 값 외에는 사실로 쓰지 말 것]\n"
               + "\n".join(lines))

    # ── 보랏빛 소 진단 → 원고 지침 ──────────────────────────────────
    # 예전에는 "제목: [쿠팡 핫딜] ○○ 최저가 분석 / 서론 / 본론1·2·3 / 결론" 이라는
    # 고정 구성을 넘겼다. 수천 개 블로그가 쓰는 형식이라 리마커블함이 0이었다.
    price_hist = collector.get_price_history(pid, days=14)
    diag = purple_cow.diagnose(product, price_hist)
    logger_func(f"  └ {purple_cow.summary_text(diag)}")
    for a in diag["answers"]:
        logger_func(f"     {'✔' if a['yes'] else '✘'} {a['evidence'][:72]}")

    # 키워드를 title[:12] 로 자르면 '빙그레 아카페라 아메리' 같은 조각이 나온다.
    # 그런 문자열은 아무도 검색하지 않는다(네이버 데이터랩상 상품명 전체도 측정 임계 미만).
    # 검색량이 실제로 있는 건 카테고리어다. 브랜드 + 카테고리 + 상품명 순으로 넘긴다.
    # 제목을 통째로 넣으면 그 안의 쉼표 때문에 '1L', '12개' 가 별도 키워드로 쪼개진다.
    # 규격 앞의 첫 구까지만 쓴다.
    head = re.split(r"[,(]", title)[0].strip()
    kw = [w for w in (product.get("brand"), _category_word(title, product), head) if w]
    return {
        "topic": f"{title} 실제 가격과 살 만한 이유",
        "keywords": ", ".join(dict.fromkeys(kw + ["쿠팡", "가격비교"])),
        "context": context,
        "theme_guide": purple_cow.build_blog_guide(product, price_hist, diag),
        "diag": diag,
        "price_history": price_hist,
    }


def generate_post_draft(product_id: str, logger_func=print) -> dict:
    """
    원고만 생성한다. 차트·릴스·네이버 포스팅은 건드리지 않는다.
    발행은 사람이 원고를 읽고 판단할 일이라 이 함수는 절대 포스팅하지 않는다.
    """
    all_prods = collector.get_all_products_from_db()
    product = next((p for p in all_prods if str(p["product_id"]) == str(product_id)), None)
    if not product:
        raise ValueError(f"DB에 상품 '{product_id}' 이(가) 없습니다. (보유 {len(all_prods)}건)")

    logger_func(f"📦 {product['title'][:40]}")
    inputs = _build_post_inputs(product, logger_func)

    api_key = cfg.load_config().get("gemini_api_key", "")
    if not api_key:
        raise RuntimeError("config.json 에 gemini_api_key 가 없습니다.")

    from ai_writer import generate_blog_post
    post = generate_blog_post(
        api_key=api_key,
        topic=inputs["topic"],
        keywords=inputs["keywords"],
        context=inputs["context"],
        theme_prompt=inputs["theme_guide"],
    )
    post["product"] = product
    post["diag"] = inputs["diag"]

    # 원고 검사. 지침으로 부탁한 것과 달리 여기는 통과 못 하면 기록이 남는다.
    # (발행 함수에서 raise_on_fail=True 로 다시 부른다 — 여기서는 보여주기만 한다)
    post["guard"] = guardrails.enforce(post.get("content", ""), inputs["context"],
                                       logger_func, title=post.get("title", ""))
    post["context"] = inputs["context"]
    return post


BLOG_IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_blog_imgs")

#: 쿠팡 파트너스 운영 정책상 제휴 링크가 들어간 글에 반드시 표기해야 하는 문구.
#: 한 글자도 바꾸지 말 것 — 특히 "제공받습니다"를 "제공받을 수 있습니다"로 바꾸면
#: 조건부·불확정 표현이 되어 파트너스 심사에서 부적합 판정을 받는다(공식 가이드 명시).
PARTNERS_DISCLOSURE = (
    "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
)

#: 제목 앞에 붙여야 하는 광고 표시. 쿠팡 파트너스 최종 승인 기준이다.
#: 공식 가이드의 O 예시가 "[광고]아이들이 좋아하는 인기 장난감 추천" 형태다.
AD_MARK = "[광고]"

#: 대가성 고지 글자색. 공정위 지침이 '흐린 색으로 묻히는 것'을 부적절 사례로 든다.
DISCLOSURE_COLOR = "#FF0000"


def split_sentences(text: str) -> list:
    """
    문장 끝(마침표·물음표·느낌표)에서 자른다. 문장마다 줄을 바꿔 읽기 쉽게 하려는 것이다.

    소수점과 약어를 문장 끝으로 오해하면 안 된다 —
    '1,507원' 이나 '150.7원', '4.8점' 에서 잘리면 글이 부서진다.
    그래서 마침표 뒤에 공백이나 줄끝이 오는 경우만 자른다.
    """
    t = (text or "").strip()
    if not t:
        return []
    parts = re.split(r"(?<=[.!?？！])\s+", t)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # 숫자 사이의 마침표에서 잘린 조각은 앞 문장에 되붙인다
        if out and re.search(r"\d$", out[-1]) and re.match(r"^\d", p):
            out[-1] = out[-1] + " " + p
        else:
            out.append(p)
    return out


def ad_title(title: str) -> str:
    """
    제목을 그대로 둔다. 이미 붙어 있던 [광고] 는 떼어낸다.

    쿠팡 파트너스 공식 가이드는 표시 위치를 **제목 또는 게시물 첫 부분** 중
    하나로 정한다(둘 다 요구하지 않는다). 공정위 심사지침도 문자 매체에 대해
    '제목 또는 첫 부분' 이라고 쓴다.
    이 시스템은 대가성 고지를 본문 맨 위에 본문과 같은 크기로 넣으므로
    제목 표시는 필요 없다. 제목 40자 제한을 4자 아껴 상품명·가격에 쓰는 편이 낫다.

    **대신 본문 고지 위치 검사가 더 엄격해진다** — 그게 유일한 표시가 되기 때문이다.
    check_disclosure() 를 보라.
    """
    t = re.sub(r"^\s*\[\s*(광고|AD|Ad|ad)\s*\]\s*", "", (title or "").strip())
    return t

# ════════════════════════════════════════════════════════════════
# 블로그 카테고리 매핑
# ════════════════════════════════════════════════════════════════

#: 네이버 블로그에 실제로 만들어 둔 하위 카테고리(2026-08 기준).
#: 이름이 정확히 일치해야 에디터에서 선택된다.
BLOG_CATEGORIES = [
    "식품", "의류", "패션", "생활용품", "뷰티", "가전디지털", "주방용품",
    "홈인테리어", "스포츠/레저", "자동차용품", "도서/음반/DVD", "헬스/건강식품",
]
DEFAULT_BLOG_CATEGORY = "쿠팡 할인물품"       # 매칭 실패 시 부모 카테고리

#: 쿠팡 분류에 없는 이름을 블로그 카테고리로 옮기는 규칙. 위에서부터 먼저 맞는 것을 쓴다.
_CATEGORY_RULES = [
    (("반려동물", "펫티켓", "강아지", "고양이"), "생활용품"),
    (("헬스", "건강식품", "영양제", "요가", "보충제"), "헬스/건강식품"),
    # '수세미'는 '세제' 규칙보다 먼저 봐야 한다.
    # 뒤에 두면 '철 수세미'가 세제로 분류돼 생활용품으로 간다(실제로 그랬다).
    (("주방", "조리", "식기", "커피머신", "텀블러", "밀폐용기",
      "수세미", "행주", "도마", "젓가락", "숟가락", "냄비", "프라이팬"), "주방용품"),
    (("공구", "철물", "DIY", "조명", "가구", "수납", "인테리어"), "홈인테리어"),
    (("자동차", "차량", "카센터", "타이어"), "자동차용품"),
    (("도서", "음반", "DVD", "eBook"), "도서/음반/DVD"),
    # 쿠팡 분류는 '패션의류/잡화' 처럼 패션과 의류를 함께 쓴다.
    # 경로에 '패션'이 있으면 패션으로, 옷 자체를 가리키면 의류로 보낸다.
    (("패션잡화", "패션소품", "주얼리", "시계", "선글라스", "지갑", "벨트"), "패션"),
    (("의류", "티셔츠", "바지", "원피스", "아우터", "속옷", "잠옷"), "의류"),
    (("신발", "가방", "모자", "잡화", "패션"), "패션"),
    (("가전", "디지털", "컴퓨터", "노트북", "휴대폰", "TV", "모니터"), "가전디지털"),
    (("뷰티", "화장", "스킨", "헤어", "네일"), "뷰티"),
    (("생수", "음료", "커피", "과자", "냉동", "정육", "농산",
      # 상세 수집이 안 된 상품은 category 가 비어 있어 상품명으로만 판단해야 한다.
      # 실제로 '백설 카놀라유' 가 분류에 실패해 카테고리 없이 발행됐다.
      "식용유", "카놀라유", "올리브유", "참기름", "식초", "설탕", "소금", "간장",
      "밀가루", "라면", "이유식", "우유", "아메리카노", "차음료", "생리대"), "식품"),
    (("욕실", "청소", "세제", "위생", "생활",
      "변기", "배수구", "하수구", "뚫어뻥", "탈취", "제습", "방향제", "살충",
      "물티슈", "휴지", "면봉", "장갑", "쓰레기봉투", "지퍼백", "테이프",
      "건전지", "배변봉투", "해충", "끈끈이", "드릴펑", "막힘", "미용티슈",
      "아이스팩", "개미", "벌레", "곰팡이", "락스", "표백"), "생활용품"),
    (("스포츠", "레저", "캠핑", "등산", "자전거", "낚시",
      "무릎보호대", "토시", "헤어밴드", "매트", "캡가드"), "스포츠/레저"),
]

#: 위 규칙보다 나중에 보는 보조 규칙.
#: 앞 규칙은 위에서부터 먼저 맞는 것을 쓰므로, 여러 곳에 걸릴 수 있는 낱말은 여기 둔다.
#: ('수세미'는 청소용품이자 주방용품인데, 실제 쓰임은 주방이다)
_CATEGORY_RULES_LATE = [
    (("수세미", "행주", "도마", "젓가락", "숟가락", "냄비", "프라이팬",
      "보관용기", "종이컵", "포일", "랩", "위생백", "크린백", "용기"), "주방용품"),
    (("칫솔", "치약", "샴푸", "린스", "바디워시", "핸드워시", "비누",
      "마스크팩", "클렌징", "로션", "선크림", "면도"), "뷰티"),
    # 먹는 것은 대체로 식품이다. 위 규칙에서 안 걸린 식재료·간식을 여기서 받는다.
    (("고추장", "된장", "쌈장", "곰탕", "국물", "즉석", "레토르트", "과일칩",
      "견과", "김치", "햄", "참치", "통조림", "시리얼", "누룽지", "떡",
      "생수", "차", "주스", "탄산"), "식품"),
    # 붙이고 자르고 닦는 잡화류
    (("필름", "밴드", "반창고", "마스크", "샤워호스", "매직블럭", "수세미솔",
      "빨래", "세탁", "건조대", "옷걸이", "먼지", "청소포"), "생활용품"),
    (("보호필름", "액정", "케이블", "충전기", "USB", "이어폰", "마우스",
      "키보드", "어댑터", "멀티탭"), "가전디지털"),
    (("도서", "책", "문해", "학습지", "교재", "스케치북", "도화지", "노트", "필기"),
     "도서/음반/DVD"),
    (("얼음", "올리고당", "포도씨유", "요리유", "조미", "향신료", "소스", "시럽"), "식품"),
    (("접착제", "본드", "물막이", "실리콘", "방충", "커튼", "매트리스", "선반"), "홈인테리어"),
    (("풋크림", "핸드크림", "바디", "각질", "네일", "향수"), "뷰티"),
    (("테스트기", "체온계", "혈압", "찜질", "파스", "영양", "비타민"), "헬스/건강식품"),
    (("핸드 워시", "핸드워시", "미백제", "치아", "구강"), "뷰티"),
    (("참깨", "돌김", "조미김", "김자반", "미역", "다시마"), "식품"),
]


def map_blog_category(product: dict) -> str:
    """
    쿠팡 카테고리 경로를 블로그 카테고리 이름으로 옮긴다.

    최상위만 보면 안 된다. 쿠팡은 수입 상품을 '쿠팡수입' 아래에 묶어서
    '쿠팡수입 > 헬스/건강식품 > ...' 처럼 실제 분류가 2단계에 오는 경우가 있다.
    그래서 경로 전체를 훑어 블로그 카테고리와 정확히 일치하는 조각을 먼저 찾는다.
    """
    path = (product.get("category") or "").strip()
    segs = [s.strip() for s in path.split(">") if s.strip()]

    for s in segs:                                  # 1) 정확 일치 (깊이 무관)
        if s in BLOG_CATEGORIES:
            return s

    hay = f"{path} {product.get('title', '')}"
    for keys, cat in _CATEGORY_RULES:               # 2) 키워드 규칙
        if any(k in hay for k in keys):
            return cat
    for keys, cat in _CATEGORY_RULES_LATE:          # 3) 보조 규칙(겹치는 낱말)
        if any(k in hay for k in keys):
            return cat

    return DEFAULT_BLOG_CATEGORY                    # 4) 부모 카테고리로 보낸다


def prepare_images(product: dict, max_n: int = 3, logger_func=print) -> list:
    """
    상품 이미지를 로컬 파일로 내려받아 경로 목록을 돌려준다.

    DB 의 detail_images 는 갤러리 스코프로 수집한 '해당 상품' 사진이다
    (예전엔 '함께 본 상품' 캐러셀이 섞여 남의 제품이 들어갔다 — 그건 수집기에서 고쳤다).
    너무 작은 이미지는 본문에서 뭉개지므로 거른다.
    """
    import requests
    from PIL import Image

    os.makedirs(BLOG_IMG_DIR, exist_ok=True)
    urls = product.get("detail_images") or []
    if isinstance(urls, str):
        try:
            urls = json.loads(urls)
        except Exception:
            urls = []
    main = product.get("image_url")
    if main:
        urls = [main] + [u for u in urls if u != main]
    urls = [u for u in dict.fromkeys(urls) if u and "/image/displayitem" not in u]

    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.coupang.com/"}
    out = []
    pid = product.get("product_id", "x")
    for i, u in enumerate(urls):
        if len(out) >= max_n:
            break
        path = os.path.join(BLOG_IMG_DIR, f"{pid}_{i}.jpg")
        try:
            if not os.path.exists(path):
                r = requests.get(u, headers=headers, timeout=15)
                if r.status_code != 200 or len(r.content) < 4000:
                    continue
                with open(path, "wb") as f:
                    f.write(r.content)
            with Image.open(path) as im:
                if min(im.size) < 400:          # 본문에서 뭉개진다
                    continue
                if im.mode != "RGB":
                    im.convert("RGB").save(path, "JPEG", quality=92)
            out.append(path)
        except Exception as e:
            logger_func(f"  이미지 준비 실패({i}): {str(e)[:44]}")
    logger_func(f"  └ 본문 이미지 {len(out)}장 준비")
    return out


def _publish_log_conn():
    """발행 이력 테이블을 보장하고 연결을 돌려준다."""
    import sqlite3
    conn = sqlite3.connect(collector.DB_PATH if hasattr(collector, "DB_PATH")
                           else os.path.join(BASE_DIR, "price_history.db"))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS published_posts (
            product_id TEXT NOT NULL,
            channel    TEXT NOT NULL,
            published_at TEXT NOT NULL,
            url        TEXT,
            PRIMARY KEY (product_id, channel)
        )
    """)
    conn.commit()
    return conn


def clear_published(product_id: str, channel: str = "") -> int:
    """
    발행 원장에서 기록을 지운다 — 같은 상품을 의도적으로 다시 올리고 싶을 때 쓴다.
    (원장이 없으면 중복을 못 막고, 지울 방법이 없으면 재발행이 영영 막힌다)
    channel 을 비우면 모든 채널에서 지운다. 돌려주는 값은 지워진 행 수.
    """
    conn = _publish_log_conn()
    try:
        if channel:
            cur = conn.execute("DELETE FROM published_posts WHERE product_id=? AND channel=?",
                               (str(product_id), channel))
        else:
            cur = conn.execute("DELETE FROM published_posts WHERE product_id=?",
                               (str(product_id),))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def check_publishable(product_id: str, channel: str, force: bool = False) -> dict:
    """
    발행해도 되는 상품인지 판정한다. 발행 함수 진입부에서 반드시 부른다.

    막는 것 두 가지:
    1. 실측이 아닌 상품(is_real != 1) — 난수로 만든 리뷰수·별점·가격 이력이 붙어 있다.
    2. 이미 같은 채널에 올린 상품 — 실제로 티스토리 /2 와 /3 에 같은 글이 두 번 나갔다.
       중복 글은 검색엔진에 유사문서로 잡히고, 둘 다 손해를 본다.
    """
    prod = next((x for x in collector.get_all_products_from_db()
                 if str(x["product_id"]) == str(product_id)), None)
    if not prod:
        return {"ok": False, "why": f"DB 에 상품 {product_id} 이(가) 없습니다"}
    if int(prod.get("is_real") or 0) != 1:
        return {"ok": False, "why": f"실측 데이터가 아닙니다(is_real={prod.get('is_real')}). "
                                    "난수로 만들어진 값이 섞여 있어 발행하면 안 됩니다"}

    conn = _publish_log_conn()
    try:
        row = conn.execute(
            "SELECT published_at, url FROM published_posts WHERE product_id=? AND channel=?",
            (str(product_id), channel)).fetchone()
    finally:
        conn.close()
    if row and not force:
        return {"ok": False,
                "why": f"{channel} 에 이미 발행했습니다({row[0]}) {row[1] or ''}. "
                       f"다시 올리려면 clear_published('{product_id}', '{channel}') 로 기록을 지우거나 "
                       "force=True 로 부르세요".strip()}
    return {"ok": True, "why": "", "product": prod}


def record_published(product_id: str, channel: str, url: str = "") -> None:
    """발행에 성공했을 때만 기록한다. 실패한 시도를 기록하면 재시도가 막힌다."""
    conn = _publish_log_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO published_posts (product_id, channel, published_at, url) "
            "VALUES (?, ?, ?, ?)",
            (str(product_id), channel, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), url))
        conn.commit()
    finally:
        conn.close()


def _product_tags(product: dict, logger_func=print, n: int = 10) -> str:
    """
    상품별 검색 키워드를 태그 문자열로 만든다.

    예전에는 두 경로가 각각 `"쿠팡,할인정보,가격비교"` 하드코딩과 빈 `default_keywords` 를
    썼다. 모든 글에 같은 태그 3개가 붙거나 아예 안 붙었고, 상품별로 계산해 둔 키워드는
    버려졌다. 그런 태그로는 검색으로 그 글에 도달할 수 없다.
    """
    try:
        import keyword_finder
        tags = keyword_finder.keyword_string(product, n=n, log=lambda *a: None)
        logger_func(f"  └ 검색 키워드 {len(tags.split(','))}개: {tags[:70]}")
        return tags
    except Exception as e:
        logger_func(f"  └ 키워드 조회 실패, 상품명 사용: {str(e)[:50]}")
        return re.split(r"[,(]", product.get("title", ""))[0].strip()


def _observed_date(observed_at: str) -> str:
    """products.updated_at 을 '2026년 08월 11일' 로 바꾼다. 못 읽으면 빈 문자열."""
    s = (observed_at or "").strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(
                s[:len(datetime.now().strftime(fmt))], fmt).strftime("%Y년 %m월 %d일")
        except ValueError:
            continue
    return ""


def _fmt_observed(observed_at: str) -> str:
    """고지 문구용 표현. 모르면 얼버무리지 않고 그렇게 밝힌다."""
    d = _observed_date(observed_at)
    # 파싱 실패한 문자열을 그대로 흘리면 "※ 위 가격은 not a date 에 확인한 값입니다"가
    # 본문에 박힌다. 모르면 모른다고 쓴다.
    return f"{d}에" if d else "확인 시점이 기록되지 않은 시점에"


def build_segments(post: dict, image_paths: list, affiliate_url: str = "",
                   chart_path: str = "", observed_at: str = "") -> list:
    """
    원고와 이미지를 섞어 네이버 에디터용 세그먼트를 만든다.

    image_paths 를 write_post 에 그냥 넘기면 본문을 다 쓴 뒤 맨 끝에 몰아서 붙는다.
    글 맥락에 맞는 자리에 놓으려면 segments 에 image 타입을 끼워 넣어야 한다.
    (segments 에 image 가 있으면 naver_poster 가 끝단 일괄첨부를 건너뛴다.)

    observed_at: 가격을 실제로 확인한 시각(products.updated_at).
      비워 두면 '확인 시점 미상'으로 적는다. 발행일을 수집일로 적으면 안 된다 —
      08-11 에 수집한 값을 08-13 에 발행하면서 "08월 13일 기준"이라고 쓰면 거짓이다.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", post["content"].strip()) if p.strip()]
    disclosure_kw = "쿠팡 파트너스 활동의 일환"

    body = []
    for p in paras:
        # 문단 통째로 버리지 않고 '줄 단위'로 거른다.
        # AI 원고는 파트너스 고지와 구매 링크를 한 문단에 붙여 내놓는 경우가 있어
        # 문단째로 버리면 멀쩡한 문장까지 사라지고, 안 버리면 링크가 중복된다.
        keep = []
        for line in p.split("\n"):
            s = line.strip()
            if not s:
                continue
            if disclosure_kw in s:
                continue
            if re.match(r"^\[?구매\s*링크", s) or re.match(r"^https?://", s):
                continue
            if "coupang.com" in s and len(s) < 120:      # 링크만 있는 줄
                continue
            keep.append(s)
        if keep:
            body.append("\n".join(keep))

    imgs = list(image_paths or [])
    # 첫 이미지는 도입부 바로 뒤, 나머지는 남은 문단에 고르게 흩는다.
    slots = set()
    if imgs and body:
        slots.add(1 if len(body) > 1 else 0)
        remaining = len(imgs) - 1
        if remaining > 0 and len(body) > 2:
            step = max(1, (len(body) - 1) // (remaining + 1))
            pos = 1 + step
            while remaining > 0 and pos < len(body):
                slots.add(pos)
                pos += step
                remaining -= 1

    # 가격 이야기가 나오는 문단을 찾는다 — 차트는 그 뒤에 놓아야 맥락이 맞는다.
    chart_after = -1
    if chart_path and os.path.exists(chart_path):
        for i, p in enumerate(body):
            if re.search(r"\d{1,3},\d{3}원", p) or "가격" in p:
                chart_after = i
                break
        if chart_after < 0:
            chart_after = min(1, len(body) - 1)

    # 작성 시점과 가격 변동 고지.
    # 쿠팡 가격은 수시로 바뀌므로, 글을 나중에 읽는 사람에게 '언제 기준인지'를
    # 알려주지 않으면 사실과 다른 정보를 보게 된다.
    when = _fmt_observed(observed_at)
    price_notice = (
        f"※ 위 가격은 {when} 쿠팡 판매 페이지에서 확인한 값입니다. "
        "쿠팡 판매가는 수시로 변동되므로, 구매 시점에 실제 가격을 반드시 확인해 주세요."
    )
    notice_placed = False

    # 대가성 고지는 '맨 위'다. 예전엔 본문 끝에 회색 13px 로 붙였는데,
    # 공정위 추천·보증 심사지침은 문자 매체의 표시문구를 제목 또는 첫 부분에 두도록 하고,
    # 본문과 뚜렷이 구분되게(작은 글씨·흐린 색으로 묻히지 않게) 요구한다.
    # 그래서 위치를 올리고 본문과 같은 크기·색으로 쓴다.
    segs, img_i = [], 0
    # 고지는 빨간색으로. 공정위 지침이 '본문과 뚜렷이 구분되게' 요구하고,
    # 작은 글씨·흐린 색으로 묻히는 것을 부적절 사례로 든다. 눈에 띄는 편이 안전하다.
    # bold 는 확실히 동작하는 서식이라 함께 건다.
    # 색상 적용이 실패해도 고지가 본문에 묻히지 않게 하는 보험이다 —
    # 공정위 지침이 요구하는 건 '뚜렷이 구분되게' 이고, 색 자체를 지정하진 않는다.
    segs.append({"type": "normal", "text": PARTNERS_DISCLOSURE,
                 "size": "15", "bold": True, "color": DISCLOSURE_COLOR,
                 "newline_after": 2})

    for i, p in enumerate(body):
        # 문장이 끝나면 줄을 바꾼다. 한 문단이 통짜로 붙어 있으면 모바일에서 읽기 나쁘다.
        # 문단 사이는 빈 줄(newline_after=2), 문장 사이는 한 줄(newline_after=1).
        sents = split_sentences(p)
        for j, s in enumerate(sents):
            last = (j == len(sents) - 1)
            segs.append({"type": "normal", "text": s, "size": "15",
                         "newline_after": 2 if last else 1})
        if i == chart_after:
            segs.append({"type": "image", "path": chart_path,
                         "visual_label": "가격 변동 그래프", "newline_after": 1})
            segs.append({"type": "normal",
                         # '매일 수집'은 사실이 아니었다. 수집이 며칠 비어도 이 문구가 나갔다.
                         "text": "▲ 확인한 시점들의 판매가 기록입니다.",
                         "size": "13", "newline_after": 1})
            segs.append({"type": "normal", "text": price_notice,
                         "size": "13", "newline_after": 2})
            notice_placed = True
        if i in slots and img_i < len(imgs):
            segs.append({"type": "image", "path": imgs[img_i],
                         "visual_label": f"상품 이미지 {img_i + 1}", "newline_after": 2})
            img_i += 1
    # 배치되지 못한 이미지는 마지막 문단 뒤에 붙인다
    while img_i < len(imgs):
        segs.append({"type": "image", "path": imgs[img_i],
                     "visual_label": f"상품 이미지 {img_i + 1}", "newline_after": 2})
        img_i += 1

    # 그래프가 없어 고지가 배치되지 못했으면 링크 앞에 반드시 넣는다.
    if not notice_placed:
        segs.append({"type": "normal", "text": price_notice,
                     "size": "13", "newline_before": 1, "newline_after": 2})

    if affiliate_url:
        # URL 은 반드시 '단독 줄'로 넣는다.
        # "구매 링크: https://..." 처럼 문장 중간에 두면 네이버 에디터가
        # 자동 링크화를 하지 않아 클릭이 안 되는 맨 텍스트로 남는다.
        # '최저가'라고 쓰지 않는다. 그 상품이 지금 최저가인지 확인할 방법이 없고,
        # purple_cow.py 가 스스로 금지어로 지정해 둔 표현이기도 하다.
        segs.append({"type": "normal", "text": "▼ 쿠팡에서 현재 가격 확인하기",
                     "size": "15", "bold": True, "newline_before": 1, "newline_after": 1})
        segs.append({"type": "normal", "text": affiliate_url,
                     "size": "15", "newline_after": 2})
    # 고지는 맨 위에 이미 넣었다. 여기서 한 번 더 반복해 글 끝에서도 보이게 한다.
    segs.append({"type": "normal", "text": PARTNERS_DISCLOSURE,
                 "size": "13", "color": "#888888", "newline_before": 1})
    return segs


def publish_to_naver(product_id: str, tags: str = "",
                     image_paths: list = None, logger_func=print) -> dict:
    """
    원고를 만들어 네이버 블로그에 발행한다. 차트·릴스 생성은 하지 않는다.

    주의: naver_poster.write_post 는 '최종 발행'까지 진행한다. 비공개나 임시저장
    옵션이 없어서 호출 즉시 공개 글이 된다. 티스토리 쪽(draft 기본값)과 다르다.
    """
    guard = check_publishable(product_id, "naver")
    if not guard["ok"]:
        logger_func(f"  ⛔ 발행 중단: {guard['why']}")
        return {"status": "blocked", "why": guard["why"]}

    post = generate_post_draft(product_id, logger_func)
    if not post.get("guard", {}).get("ok", True):
        why = " / ".join(post["guard"]["blocking"][:3])
        logger_func(f"  ⛔ 원고 검사 실패로 발행 중단: {why}")
        return {"status": "blocked", "why": f"원고 검사 실패: {why}"}

    cfgd = cfg.load_config()
    nid, npw = cfgd.get("naver_id", ""), cfgd.get("naver_pw", "")
    if not nid or not npw:
        raise RuntimeError("config.json 에 naver_id / naver_pw 가 없습니다.")

    aff = post["product"].get("affiliate_url") or ""
    if "link.coupang.com" not in aff:
        logger_func("  [주의] 파트너스 딥링크가 아닙니다 — 이 글은 수수료가 붙지 않습니다.")

    from naver_poster import NaverBlogPoster
    poster = NaverBlogPoster(headless=cfgd.get("headless_mode", False),
                             log_callback=logger_func)
    try:
        if not poster.login(nid, npw):
            return {"status": "failed", "why": "네이버 로그인 실패"}
        imgs = ([p for p in image_paths if p and os.path.exists(p)]
                if image_paths else prepare_images(post["product"], 3, logger_func))

        # 가격 변동 그래프 — 네이버 블로그는 iframe·스크립트를 못 넣으므로
        # 라이브 위젯 대신 이미지로 만들어 본문에 삽입한다.
        chart = ""
        try:
            hist = collector.get_price_history(str(product_id), days=14)
            if len(hist) >= widget_server.MIN_POINTS_FOR_CHART:
                chart = widget_server.save_widget_chart_image(str(product_id))
                logger_func(f"  └ 가격 그래프 생성 (관측 {len(hist)}점)")
            else:
                # 2점을 이은 선은 추세가 아니다. 그리지 않는다.
                logger_func(f"  └ 관측 {len(hist)}점 — 그래프 생략"
                            f"({widget_server.MIN_POINTS_FOR_CHART}점 이상 필요)")
        except Exception as e:
            logger_func(f"  └ 그래프 생성 실패: {str(e)[:50]}")

        segments = build_segments(post, imgs, aff, chart,
                                  observed_at=post["product"].get("updated_at", ""))
        n_img = sum(1 for s in segments if s.get("type") == "image")

        # 파트너스 승인 기준(제목 [광고] / 고지 위치 / 확정 표현)을 발행 직전에 확인한다.
        # 세그먼트를 평문으로 되살려 검사한다 — 실제로 나가는 순서 그대로 봐야 의미가 있다.
        flat = "\n".join(s.get("text", "") for s in segments if s.get("type") == "normal")
        probs = guardrails.check_disclosure(flat, ad_title(post["title"]))
        if probs:
            for x in probs:
                logger_func(f"  ⛔ {x}")
            return {"status": "blocked", "why": "파트너스 표시 기준 위반: " + probs[0]}

        # 파트너스 고지가 빠지면 안 된다 — 규정이자 신뢰 문제다.
        # build_segments 가 항상 붙이지만, 여기서 한 번 더 확인하고 없으면 채운다.
        if not any(PARTNERS_DISCLOSURE in (s.get("text") or "") for s in segments):
            logger_func("  ⚠️ 파트너스 고지 누락 감지 — 보강합니다")
            segments.append({"type": "normal", "text": PARTNERS_DISCLOSURE, "size": "13"})

        # 태그를 안 주면 상품별 검색 키워드를 뽑아 쓴다.
        # 예전엔 기본값이 "쿠팡,할인정보,가격비교" 로 하드코딩돼 모든 글에 같은 태그 3개가
        # 붙었고, 상품별로 계산해 둔 키워드는 버려졌다. 그런 태그로는 아무도 도달하지 못한다.
        if not tags:
            tags = _product_tags(post["product"], logger_func)

        blog_cat = map_blog_category(post["product"])
        logger_func(f"  └ 본문 {len(post['content'])}자 · 세그먼트 {len(segments)}개 · "
                    f"이미지 {n_img}장 · 카테고리 '{blog_cat}'")
        ok = poster.write_post(ad_title(post["title"]), post["content"], blog_cat,
                               naver_id=nid, tags=tags, segments=segments)

        # 발행 후 알림 — 딥링크로 바꿔야 할 상품 링크를 사람에게 보낸다.
        # 알림 실패가 발행 결과를 뒤집지 않게 한다.
        if ok:
            # 성공했을 때만 기록한다 — 실패를 기록하면 재시도가 영영 막힌다.
            record_published(product_id, "naver")
            try:
                import notify
                if notify.notify_published(post["product"], post["title"],
                                           category=blog_cat):
                    logger_func("  └ 텔레그램 알림 전송")
            except Exception as e:
                logger_func(f"  └ 알림 건너뜀: {str(e)[:50]}")

        return {"status": "success" if ok else "failed",
                "title": post["title"], "chars": len(post["content"]),
                "images": n_img, "category": blog_cat}
    finally:
        try:
            poster.close()
        except Exception:
            pass


def run_coupang_pipeline(product_id: str, logger_func=print) -> dict:
    """
    특정 쿠팡 상품 ID에 대해:
    1. 일별 가격 DB 조회 및 비교 계산
    2. 동적 가격 변동 그래프 차트 이미지 생성
    3. 부동산 스타일 AI 릴스/숏폼 영상 제작 (.mp4)
    4. AI 구매 유도 리뷰 본문 작성 (Gemini)
    5. 네이버 블로그 스마트에디터 포스팅 진행
    """
    logger_func(f"🚀 [Coupang Pipeline] 상품({product_id}) 자동 포스팅 프로세스 시작...")

    # 발행 가드는 반드시 여기 있어야 한다.
    # 대시보드의 '원클릭 포스팅' 버튼이 부르는 건 publish_to_naver 가 아니라 이 함수다.
    # (publish_to_naver 는 현재 아무도 부르지 않는다)
    guard = check_publishable(product_id, "naver")
    if not guard["ok"]:
        logger_func(f"⛔ 발행 중단: {guard['why']}")
        return {"status": "blocked", "message": guard["why"]}

    # 1. DB 상품 조회
    all_prods = collector.get_all_products_from_db()
    product = next((p for p in all_prods if p["product_id"] == product_id), None)

    if not product:
        logger_func("❌ DB에서 해당 상품 정보를 찾을 수 없습니다. 수집을 먼저 실행하세요.")
        return {"status": "error", "message": "Product not found"}


    comp = product.get("comparison", {})
    logger_func(f"📦 선택된 상품: {product['title'][:25]}... (현재가: {product['current_price']:,}원)")

    # 2. 가격 변동 차트 — 관측이 부족하면 그리지 않는다.
    #    예전엔 여기서 무조건 만들었고, 이력이 없으면 가짜 4점으로 그렸다.
    #    이제 3점 미만이면 ValueError 가 나므로 반드시 감싸야 한다(안 그러면 발행 전체가 죽는다).
    logger_func("📊 [1/4] 가격 변동 차트 이미지 생성 중...")
    chart_image_path = ""
    try:
        hist = collector.get_price_history(str(product_id), days=14)
        if len(hist) >= widget_server.MIN_POINTS_FOR_CHART:
            chart_image_path = widget_server.save_widget_chart_image(product_id)
            logger_func(f"  └ 차트 생성 완료 (관측 {len(hist)}점): {chart_image_path}")
        else:
            logger_func(f"  └ 관측 {len(hist)}점 — 차트 생략"
                        f"({widget_server.MIN_POINTS_FOR_CHART}점 이상 필요)")
    except Exception as e:
        logger_func(f"  └ 차트 생략: {str(e)[:60]}")

    # 3. 부동산 스타일 릴스 영상 생성
    logger_func("🎬 [2/4] 부동산 릴스 스타일 AI 숏폼 영상 제작 중 (15초 9:16)...")
    reels_video_path = reels.generate_product_reels_video(product_id)
    logger_func(f"  └ 릴스 영상 제작 완료: {reels_video_path}")

    # 4. AI 원고 생성
    logger_func("✍️ [3/4] AI 리뷰 원고 작성 중 (Gemini AI)...")
    config_data = cfg.load_config()
    api_key = config_data.get("gemini_api_key", "")

    title = product['title']
    curr_price = product['current_price']
    orig_price = product['original_price']
    disc_rate = product['discount_rate']
    yest_price = comp.get('yesterday_price', curr_price)
    diff_val = abs(comp.get('diff', 0))
    # '최저가 유지'는 확인할 수 없는 주장이다. 관측된 사실만 쓴다.
    # 관측이 1점뿐이면 비교 자체가 불가능하므로 그렇게 밝힌다.
    _st = comp.get('status')
    status_str = ("전일 대비 하락" if _st == 'down'
                  else "전일 대비 상승" if _st == 'up'
                  else "전일과 같은 가격" if _st == 'same'
                  else "이전 관측이 없어 비교 불가")
    affiliate_url = product['affiliate_url']

    inputs = _build_post_inputs(product, logger_func)
    diag = inputs["diag"]

    post_data = {"title": "", "content": ""}
    if api_key:
        try:
            from ai_writer import generate_blog_post
            post_data = generate_blog_post(
                api_key=api_key,
                topic=inputs["topic"],
                keywords=inputs["keywords"],
                context=inputs["context"],
                theme_prompt=inputs["theme_guide"],
            )
        except Exception as e:
            logger_func(f"⚠️ AI 원고 생성 오류 (기본 템플릿 대체): {e}")

    if not post_data.get("title"):
        # AI 생성 실패 시의 폴백. 리마커블함을 흉내내지 않는다 —
        # 없는 매력을 과장하는 건 보랏빛 소가 아니라 색칠한 갈색 소다.
        # 대신 관측한 사실만 정확히 적는다.
        strongest = diag["hooks"][0] if diag["hooks"] else f"{disc_rate}% 할인"
        post_data["title"] = f"{title[:26]} — {strongest}"
        change_line = (
            f"- 어제 {yest_price:,}원 → 오늘 {curr_price:,}원 ({diff_val:,}원 {status_str})"
            if diff_val else f"- 어제와 같은 {curr_price:,}원"
        )
        post_data["content"] = f"""
        **{title}**

        관측된 사실만 적습니다.

        - 정가 {orig_price:,}원 / 현재 {curr_price:,}원 ({disc_rate}%)
        {change_line}
        - 상품평 {product.get('review_count', 0):,}개
          (개수일 뿐, 만족한 사람 수가 아닙니다. 별점은 신뢰할 만큼 정확히
           수집하지 못해 이 글에서는 쓰지 않습니다.)

        오늘 값이 바닥이 아닐 수도 있습니다. 직접 확인하고 판단하세요.

        가격이 다시 내려가면 이 블로그에 같은 형식으로 다시 올립니다.

        구매 링크: {affiliate_url}

        이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.
        """

    # 5. 네이버 블로그 포스팅 실행
    logger_func("🌐 [4/4] 네이버 블로그 포스팅 등록 중 (Playwright/Selenium)...")
    try:
        from naver_poster import NaverBlogPoster
        naver_id = config_data.get("naver_id", "")
        naver_pw = config_data.get("naver_pw", "")
        headless = config_data.get("headless_mode", False)
        
        if not naver_id or not naver_pw:
            logger_func("⚠️ 네이버 아이디/비밀번호가 설정되어 있지 않습니다. 원고 및 첨부파일 준비 완료 상태로 임시 보관됩니다.")
            return {
                "status": "prepared",
                "title": post_data["title"],
                "content": post_data["content"],
                "chart_image": chart_image_path,
                "reels_video": reels_video_path
            }
            
        poster = NaverBlogPoster(headless=headless)
        if poster.login(naver_id, naver_pw):
            # naver_poster 에는 post_article 이 없다 — write_post 다.
            # 이 호출부가 존재하지 않는 메서드를 부르고 있어서 쿠팡 파이프라인의
            # 네이버 발행은 지금껏 한 번도 성공한 적이 없다(AttributeError 로 except 행).
            imgs = [p for p in [chart_image_path] if p and os.path.exists(p)]
            if reels_video_path and os.path.exists(reels_video_path):
                # write_post 는 이미지 첨부만 지원한다. 영상은 별도 업로드 흐름이라
                # 여기서 조용히 버리지 않고 경로를 남겨 사람이 직접 올리게 한다.
                logger_func(f"  └ 릴스 영상은 수동 업로드 필요: {reels_video_path}")
            # 대가성 고지 보장. 이 경로는 segments 를 쓰지 않고 원고 본문을 그대로 넘기므로,
            # AI 생성이 성공하면 고지가 없는 글이 나갈 수 있었다(폴백 템플릿에만 박혀 있었다).
            # 이 경로는 generate_post_draft 를 거치지 않으므로 여기서 직접 검사한다.
            g = guardrails.enforce(post_data["content"], inputs["context"], logger_func,
                                   title=post_data.get("title", ""))
            if not g["ok"]:
                logger_func("  ⛔ 원고 검사 실패로 발행 중단")
                poster.close()
                return {"status": "blocked", "why": " / ".join(g["blocking"][:3])}

            body = post_data["content"]
            if PARTNERS_DISCLOSURE not in body:
                logger_func("  └ 파트너스 고지 누락 — 본문 맨 앞에 삽입합니다")
                body = f"{PARTNERS_DISCLOSURE}\n\n{body}"

            probs = guardrails.check_disclosure(body, ad_title(post_data["title"]))
            if probs:
                for x in probs:
                    logger_func(f"  ⛔ {x}")
                poster.close()
                return {"status": "blocked", "why": "파트너스 표시 기준 위반: " + probs[0]}

            success = poster.write_post(
                ad_title(post_data["title"]),
                body,
                "",
                naver_id=naver_id,
                # config 의 default_keywords 는 비어 있어서 태그가 하나도 안 붙었다.
                # 상품별 검색 키워드를 뽑아 쓴다.
                tags=_product_tags(product, logger_func),
                image_paths=imgs,
            )
            poster.close()

            if success:
                record_published(product_id, "naver")
                logger_func("🎉 [성공] 쿠팡 TOP 100 상품 포스팅이 성공적으로 등록되었습니다!")
                return {"status": "success", "title": post_data["title"]}
            else:
                logger_func("❌ 포스팅 등록 중 실패가 발생했습니다.")
                return {"status": "failed"}
        else:
            logger_func("❌ 네이버 로그인 실패. 아이디/비밀번호를 확인하세요.")
            return {"status": "failed", "message": "Login error"}
            
    except Exception as e:
        logger_func(f"❌ 포스터 실행 중 예외 발생: {e}")
        return {"status": "prepared_fallback", "title": post_data["title"], "chart_image": chart_image_path}

if __name__ == "__main__":
    print("[Coupang Pipeline] Testing pipeline with product CP100_001...")
    res = run_coupang_pipeline("CP100_001", print)
    print(f"[Coupang Pipeline] Test result: {res}")
