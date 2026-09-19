# ============================================================
#  content/registry.py — 더스틴홀딩스 전단지 템플릿 라이브러리
#  · content/templates/flyers/*.jpg  (post-ready 렌더)
#  · content/templates/psd/*.psd     (편집소스 — PSD 텍스트 교체는 P2, win32com)
#  파일명은 타임스탬프 포함이라 'match' 부분일치로 해석(견고).
# ============================================================
from pathlib import Path

import config

TEMPLATES_DIR = Path(__file__).parent / "templates"
# 전단 위치는 업종 프로필(content.flyers_dir)에서 온다. 없으면 기본 경로.
FLYERS_DIR = config.FLYERS_DIR or (TEMPLATES_DIR / "flyers")
PSD_DIR = TEMPLATES_DIR / "psd"

# key: 시스템 상품키 / title: 표시명 / category / audience: consumer|business|mixed
# match: 파일명 부분일치 키 (flyers·psd 공통)
PRODUCTS = [
    {"key": "apart",         "title": "아파트 담보대출",           "category": "부동산담보", "audience": "consumer", "match": "아파트담보대출-260602"},
    {"key": "apart_alt",     "title": "아파트 담보대출 (대안)",     "category": "부동산담보", "audience": "consumer", "match": "아파트담보대출-02"},
    {"key": "toji",          "title": "토지 담보대출",             "category": "부동산담보", "audience": "consumer", "match": "토지담보대출"},
    {"key": "imya",          "title": "임야 담보대출",             "category": "부동산담보", "audience": "consumer", "match": "임야담보대출"},
    {"key": "factory",       "title": "공장 담보대출",             "category": "사업자담보", "audience": "business", "match": "공장담보대출"},
    {"key": "villa_junior",  "title": "빌라 후순위 담보대출",       "category": "후순위",    "audience": "consumer", "match": "빌라 후순위"},
    {"key": "villa_multi_junior", "title": "빌라·다가구 후순위 담보대출", "category": "후순위", "audience": "consumer", "match": "빌라-다가구 후순위"},
    {"key": "biz_operating", "title": "사업자 운영 담보대출",       "category": "사업자",    "audience": "business", "match": "사업자운영담보대출"},
    {"key": "biz_solution",  "title": "사업자 운영 솔루션 담보대출", "category": "사업자",    "audience": "business", "match": "사업자운영 솔루션"},
    {"key": "store_factory_solution", "title": "상가·공장 솔루션 담보대출", "category": "사업자", "audience": "business", "match": "상가공장 솔루션"},
    {"key": "lodging",       "title": "숙박시설 금융솔루션",        "category": "사업자",    "audience": "business", "match": "숙박시설 금융솔류션"},
    {"key": "call_fund",     "title": "콜자금 솔루션 대출",         "category": "사업자",    "audience": "business", "match": "콜자금 솔루션"},
    {"key": "general",       "title": "종합 대출광고",             "category": "종합",      "audience": "mixed",    "match": "대출광고-260602"},
    {"key": "general_03",    "title": "종합 대출광고 03",          "category": "종합",      "audience": "mixed",    "match": "대출광고-03"},
    {"key": "general_04",    "title": "종합 대출광고 04",          "category": "종합",      "audience": "mixed",    "match": "대출광고-04"},
    {"key": "banner_sheet_01", "title": "배너 광고 시트 1",        "category": "배너",      "audience": "mixed",    "match": "배너 대출광고-01"},
    {"key": "banner_sheet_02", "title": "배너 광고 시트 2",        "category": "배너",      "audience": "mixed",    "match": "배너 대출광고-02"},
]


def _find(directory: Path, match: str, exts) -> str:
    if not directory.exists():
        return None
    for ext in exts:
        for p in sorted(directory.glob(f"*{ext}")):
            if match in p.name:
                return str(p)
    return None


def resolve(product: dict) -> dict:
    return {
        **product,
        "flyer": _find(FLYERS_DIR, product["match"], [".jpg", ".jpeg", ".png"]),
        "psd":   _find(PSD_DIR,    product["match"], [".psd"]),
    }


def products() -> list:
    """전체 상품 목록(경로 해석 포함)."""
    return [resolve(p) for p in PRODUCTS]


def get(key: str) -> dict:
    for p in PRODUCTS:
        if p["key"] == key:
            return resolve(p)
    raise KeyError(f"미등록 상품키: {key}")


def by_audience(audience: str) -> list:
    """채널 성향(consumer|business|mixed)에 맞는 상품만."""
    return [resolve(p) for p in PRODUCTS
            if p["audience"] == audience or p["audience"] == "mixed"]


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    ok = miss = 0
    for p in products():
        flag = "OK" if p["flyer"] else "JPG없음(PSD만)"
        if p["flyer"]:
            ok += 1
        else:
            miss += 1
        print(f"  {p['key']:22s} [{p['audience']:8s}] flyer={flag}  psd={'있음' if p['psd'] else '—'}")
    print(f"\n총 {len(PRODUCTS)}종 · flyer 즉시사용 {ok} · PSD전용 {miss}")
