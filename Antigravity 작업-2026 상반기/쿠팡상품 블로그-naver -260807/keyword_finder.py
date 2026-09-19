"""
상품에 맞는 '실제로 검색되는' 키워드 10개를 뽑는다.

왜 필요한가:
발행 코드가 태그로 `"쿠팡,할인정보,가격비교"` 를 하드코딩해 넣고 있었다.
모든 글에 같은 태그 3개가 붙었고, 상품별로 계산해 둔 키워드는 버려졌다.
그런 태그로는 아무도 그 글에 도달하지 못한다.

무엇을 근거로 뽑는가:
1. **네이버 자동완성** — 사람들이 실제로 입력하는 질의를 인기순으로 돌려준다.
   검색광고 API(정확한 검색량)는 별도 계정이 필요해서 쓰지 못한다. 자동완성은
   '정확한 검색량'은 아니지만 '실제로 검색되는 말'이라는 점에서 추측보다 훨씬 낫다.
2. **카테고리 경로로 모호성 제거** — 이게 핵심이다.
   '미니 드라이버' 자동완성은 캘러웨이·핑 같은 **골프채**와 배우 이름을 돌려준다.
   상품 카테고리가 `홈인테리어 > 공구/철물/DIY > 수공구/절단도구 > 드라이버` 이므로
   공구 도메인 낱말을 함께 넣어 씨앗을 만들고, 결과도 그 도메인으로 거른다.
3. **네이버 블로그 검색으로 교차 검증** — 애매한 후보는 실제로 검색해 보고,
   상위 글들이 같은 주제인지 확인한다. (쇼핑 API 는 이 앱에 권한이 없어 blog.json 을 쓴다)
"""
import io
import json
import os
import re
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_AC = "https://ac.search.naver.com/nx/ac"
_BLOG = "https://openapi.naver.com/v1/search/blog.json"

#: 상품명·카테고리에서 키워드로 쓸 수 없는 말
_STOP = {
    "세트", "패키지", "기획", "묶음", "대용량", "리필", "리필용", "본품", "증정",
    "선물", "선물용", "구성", "종합", "모음", "특가", "행사", "기타", "일반",
    "브랜드", "상품", "제품", "무료배송", "당일발송",
}

#: 구매와 무관한 정보성 꼬리말. '아메리카노 카페인/칼로리' 같은 것이 여기 걸린다.
_INFO_TAIL = re.compile(
    r"(효능|부작용|칼로리|카페인|뜻|의미|영어로|가사|배우|드라마|영화|나무위키|"
    r"만드는\s*법|레시피|증상|병원|약|디시|갤러리)")


def _cfg():
    try:
        return json.load(io.open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8"))
    except Exception:
        return {}


def autocomplete(query: str, timeout: int = 12) -> list:
    """네이버 자동완성. 인기순으로 내려온다. 실패하면 빈 리스트."""
    if not query.strip():
        return []
    url = _AC + "?" + urllib.parse.urlencode({
        "q": query, "con": "0", "frm": "nv", "ans": "2", "r_format": "json",
        "r_enc": "UTF-8", "r_unicode": "0", "t_koreng": "1", "run": "2",
        "rev": "4", "q_enc": "UTF-8", "st": "100",
    })
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0", "Referer": "https://search.naver.com/"})
        data = json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception:
        return []
    out = []
    for group in data.get("items", []):
        for item in group:
            if item and item[0] and item[0] not in out:
                out.append(item[0])
    return out


def blog_total(query: str, timeout: int = 12):
    """블로그 검색 결과 수와 상위 제목들. 자격증명이 없거나 실패하면 (None, [])."""
    c = _cfg()
    cid, sec = c.get("naver_client_id", ""), c.get("naver_client_secret", "")
    if not cid or not sec:
        return None, []
    url = _BLOG + "?" + urllib.parse.urlencode({"query": query, "display": 5})
    try:
        req = urllib.request.Request(url, headers={
            "X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec})
        d = json.load(urllib.request.urlopen(req, timeout=timeout))
    except Exception:
        return None, []
    # 제목만 보면 근거가 너무 적다. 요약(description)까지 합쳐야 도메인이 드러난다.
    texts = [re.sub(r"<[^>]+>", "", i.get("title", "") + " " + i.get("description", ""))
             for i in d.get("items", [])]
    return d.get("total", 0), texts


def _category_parts(product: dict) -> list:
    """
    카테고리 경로를 도메인 낱말로 쪼갠다. 'A > B/C > D' → [A, B, C, D]

    주의: 이 목록의 마지막을 '잎 카테고리'로 쓰면 안 된다.
    '식품 > 생수/음료 > 커피음료/차음료 > 커피음료' 에서 '/' 까지 쪼개고 중복을 지우면
    마지막이 '차음료' 가 되어, 아메리카노 상품에 차 키워드를 뽑았다.
    """
    raw = (product.get("category") or "")
    parts = []
    for seg in re.split(r"[>/]", raw):
        s = seg.strip()
        if s and s not in _STOP and s not in parts:
            parts.append(s)
    return parts


def _core_word(product: dict) -> str:
    """
    이 상품을 부르는 '핵심 낱말'. 사람들이 실제로 검색창에 치는 말이다.

    카테고리 잎보다 상품명에서 뽑는 게 정확하다.
    (카테고리 잎은 '커피음료' 지만 사람들은 '아메리카노' 로 검색한다)
    """
    try:
        import coupang_blog_pipeline as _p
        w = _p._category_word(product.get("title", ""), product)
        if w and w not in _STOP:
            return w
    except Exception:
        pass
    # 파이프라인을 못 불러오면 카테고리 경로의 '>' 기준 마지막 조각을 쓴다
    raw = (product.get("category") or "")
    leaf = raw.split(">")[-1].strip()
    return leaf.split("/")[0].strip()


def _domain_word(product: dict, core: str) -> str:
    """
    검색어로 자연스러운 도메인 낱말 하나. '절단도구' 보다 '공구' 가 낫다.
    사람들이 실제로 쓰는 말이어야 씨앗 질의가 성립한다.
    """
    parts = [w for w in _category_parts(product) if w != core]
    if not parts:
        return ""
    # 짧은 낱말부터 후보로 본다(상위 개념일수록 사람들이 실제로 쓰는 말이다).
    cands = sorted(parts, key=lambda w: (len(w), parts.index(w)))[:4]
    # '철물 드라이버' 처럼 자동완성이 반응하지 않는 조합을 고르면 모호성 판정이 흐려진다.
    # 실제로 결과가 가장 많이 나오는 조합을 쓴다.
    best, best_n = cands[0], -1
    for w in cands:
        n = len(autocomplete(f"{w} {core}"))
        if n > best_n:
            best, best_n = w, n
    return best


def is_ambiguous(core: str, domain: str) -> bool:
    """
    핵심 낱말이 다른 분야와 겹치는가.

    판정법: `핵심어` 자동완성과 `도메인 핵심어` 자동완성이 얼마나 겹치는가.
      '면봉' vs '뷰티 면봉'      → 많이 겹친다 → 명확함
      '드라이버' vs '공구 드라이버' → 거의 안 겹친다(골프 vs 공구) → 모호함
    카테고리 낱말이 블로그 본문에 나오는지로 판정했더니 '면봉'·'아메리카노' 까지
    모호하다고 오판해서, 자기 연관어를 '다른 분야' 로 학습하는 사고가 났다.
    """
    if not core or not domain:
        return False
    a = set(autocomplete(core))
    b = set(autocomplete(f"{domain} {core}"))
    if not a or not b:
        return False
    overlap = len(a & b) / max(1, min(len(a), len(b)))
    return overlap < 0.25


def build_seeds(product: dict) -> list:
    """
    자동완성에 넣을 씨앗 질의. 도메인을 함께 넣어 엉뚱한 분야로 새는 것을 막는다.
    '미니 드라이버'만 넣으면 골프채가 나오지만 '공구 드라이버'는 안 그렇다.
    """
    parts = _category_parts(product)
    core = _core_word(product)
    domain = _domain_word(product, core)
    brand = (product.get("brand") or "").strip()
    head = re.split(r"[,(]", product.get("title", ""))[0].strip()

    seeds = []
    for s in (core, f"{domain} {core}".strip(), f"{core} 추천", f"{core} 세트",
              f"{brand} {core}".strip() if brand else "", head):
        s = re.sub(r"\s+", " ", s).strip()
        if s and s not in seeds:
            seeds.append(s)
    return seeds


def find_keywords(product: dict, n: int = 10, verify: bool = True, log=print) -> list:
    """
    상품에 맞는 검색 키워드를 인기순으로 최대 n개 돌려준다.

    verify=True 면 애매한 후보를 블로그 검색으로 교차 확인한다(API 호출이 늘어난다).
    """
    parts = _category_parts(product)
    core = _core_word(product)
    domain_words = set(parts) | set(re.findall(r"[가-힣A-Za-z]{2,}", product.get("title", "")))
    domain_words = {w for w in domain_words if w not in _STOP}
    # 검증 근거는 **카테고리 경로 낱말만** 쓴다.
    # 상품명 토큰을 섞었더니 '미니' 같은 흔한 말 때문에 골프 글도 도메인 일치로 통과했다
    # (그 결과 '드라이버' 를 '명확함' 으로 오판했다).
    # 핵심 낱말도 뺀다 — '드라이버' 를 근거로 인정하면 골프 드라이버가 다시 들어온다.
    proof_words = {w for w in parts if w != core and len(w) >= 2}

    seeds = build_seeds(product)
    log(f"  씨앗: {', '.join(seeds)}")

    # 후보 수집 — 자동완성 순서를 점수로 쓴다(앞일수록 많이 검색되는 말)
    scored = {}
    for si, seed in enumerate(seeds):
        for rank, kw in enumerate(autocomplete(seed)):
            kw = kw.strip()
            if not kw or len(kw) < 2 or len(kw) > 25:
                continue
            if _INFO_TAIL.search(kw):
                continue                       # 정보성 질의는 구매 의도가 없다
            # 씨앗이 앞일수록, 자동완성 순위가 높을수록 좋은 점수(작을수록 좋음)
            s = si * 12 + rank
            scored[kw] = min(scored.get(kw, 999), s)

    # 도메인 적합성 — 상품/카테고리 낱말을 하나도 안 담은 후보는 버린다
    def relevant(kw: str) -> bool:
        return any(w in kw for w in domain_words) or (core and core in kw)

    cands = sorted((k for k in scored if relevant(k)), key=lambda k: scored[k])
    dropped = [k for k in scored if not relevant(k)]
    if dropped:
        log(f"  도메인 불일치로 제외 {len(dropped)}개: {', '.join(dropped[:5])}")

    if verify and cands:
        # 핵심 낱말이 모호한지 먼저 본다.
        # '면봉' 처럼 뜻이 하나뿐인 말까지 엄격히 걸렀더니 정상 키워드가 잘려 나갔다
        # ('면봉 추천', '십자드라이버' 가 제외됐다). 모호할 때만 조인다.
        domain = _domain_word(product, core)
        ambiguous, rival = is_ambiguous(core, domain), set()
        if ambiguous:
            _, base_texts = blog_total(core)
            base_blob = " ".join(base_texts)
            if base_blob:
                # 경쟁 도메인 낱말을 '학습' 한다.
                # '드라이버' 를 그냥 검색하면 골프 글이 나온다 — 그 글에서 자주 나오는 말
                # (골프·스윙·비거리…)이 곧 다른 분야의 표식이다. 목록을 손으로 적지 않는다.
                freq = {}
                for w in re.findall(r"[가-힣]{2,6}", base_blob):
                    if w == core or w in proof_words or w in _STOP:
                        continue
                    freq[w] = freq.get(w, 0) + 1
                rival = {w for w, c in freq.items() if c >= 3}
                if rival:
                    log(f"  다른 분야 표식 학습: {', '.join(list(rival)[:8])}")
        log(f"  핵심 낱말 '{core}' — {'모호함(엄격 검증)' if ambiguous else '명확함(완화 검증)'}")

        kept = []
        for kw in cands[: n + 8]:
            total, texts = blog_total(kw)
            if total is None:                  # 검증 못 하면 통과시킨다
                kept.append(kw)
                continue
            if total < 30:                     # 아무도 안 쓰는 말
                log(f"  '{kw}' 블로그 {total}건 — 너무 적어 제외")
                continue
            if ambiguous:
                blob = " ".join(texts)
                mine = sum(1 for w in proof_words if w in blob) + \
                       sum(2 for w in proof_words if w in kw)
                theirs = sum(1 for w in rival if w in blob) + \
                         sum(2 for w in rival if w in kw)
                # 우리 도메인 표식보다 다른 분야 표식이 더 많으면 그 분야 키워드다.
                # ('남성 드라이버 추천' 은 골프 표식이 압도적이다)
                if theirs > mine:
                    log(f"  '{kw}' 다른 분야로 보임(우리 {mine} vs 다른 분야 {theirs}) — 제외")
                    continue
                if mine == 0 and theirs == 0:
                    log(f"  '{kw}' 도메인 판단 불가 — 제외")
                    continue
            kept.append(kw)
        cands = kept

    return cands[:n]


def keyword_string(product: dict, n: int = 10, log=print) -> str:
    """발행 함수에 넘길 쉼표 구분 문자열."""
    kws = find_keywords(product, n=n, log=log)
    if not kws:
        # 아무것도 못 찾으면 상품명 기반 최소 키워드라도 남긴다
        head = re.split(r"[,(]", product.get("title", ""))[0].strip()
        kws = [x for x in (head, (product.get("brand") or "").strip()) if x]
    return ", ".join(kws)


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.path.insert(0, BASE_DIR)
    import coupang_collector as C

    ids = [a for a in sys.argv[1:] if a.isdigit()] or ["8336040965", "7522620409", "8982016972"]
    for pid in ids:
        p = next((x for x in C.get_all_products_from_db() if str(x["product_id"]) == pid), None)
        if not p:
            print(f"{pid}: DB 에 없음")
            continue
        print("\n" + "=" * 66)
        print(f"{p['title'][:46]}")
        print(f"카테고리: {p.get('category')}")
        print("=" * 66)
        kws = find_keywords(p, n=10)
        print(f"\n  키워드 {len(kws)}개:")
        for i, k in enumerate(kws, 1):
            print(f"    {i:2d}. {k}")
