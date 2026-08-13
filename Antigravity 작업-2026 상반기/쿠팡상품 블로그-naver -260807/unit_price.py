"""
상품명에서 수량·용량을 읽어 단가를 계산한다.

이 모듈의 존재 이유는 단 하나다: **산술 결과라 지어낼 수 없다는 것.**
그래서 틀린 값을 내놓는 순간 존재 이유가 사라진다. 아니, 더 나빠진다 —
계산된 값은 `[쿠팡에서 실제로 수집한 상품 정보]` 블록에 들어가고,
purple_cow 지침이 "반드시 함께 써라"라고 시키며, guardrails 가 그 블록을
사실의 기준으로 삼는다. 즉 **틀린 숫자가 검증 도장을 받고 나간다.**

첫 판이 실제로 그랬다. 실측 79건 중 5건이 틀렸다:
  '스케치북 도화지 130g 8절, 125매' → 총 16,250g (130g 은 종이 평량이다)
  '물티슈 50g, 70매, 4개'          → 총 14,000g (50g 에 장수 70을 곱했다)
  '갤럭시 A15 5G 케이스'           → 총 5g   ('5G' 를 5그램으로 읽었다)
  '생수 500ml*20'                  → 총 500ml (곱셈 표기를 놓쳤다)
  '미용티슈 6팩, 230매'            → '개당'  (장수를 개수라고 불렀다)

그래서 원칙을 바꿨다. **애매하면 계산하지 않는다.**
40%를 정확히 맞히는 것이 82%를 계산하고 5건을 틀리는 것보다 낫다.
"""
import re

# ── 단위 정의 ────────────────────────────────────────────────────
#: 낱개로 세는 단위. '개당 단가'를 말할 수 있다.
#: '종'은 가짓수지만, '드라이버 8종 세트'처럼 세트 구성품 수를 뜻하는 경우가 대부분이라
#: 개당 단가가 의미를 갖는다(3,390원 ÷ 8종 = 424원). 낱개 단위로 함께 취급한다.
_ITEM_UNITS = ("개입", "개", "팩", "포", "정", "캡슐", "롤", "캔", "병", "봉", "구", "종")
#: 장으로 세는 단위. 낱개가 아니므로 '개당'이라고 부르면 안 된다.
_SHEET_UNITS = ("매", "장")

_ITEM_RE = re.compile(r"(?<![\d.])(\d{1,5})\s*(" + "|".join(_ITEM_UNITS) + r")(?![가-힣])")
_SHEET_RE = re.compile(r"(?<![\d.])(\d{1,5})\s*(" + "|".join(_SHEET_UNITS) + r")(?![가-힣])")

# 용량·중량. 단위 앞에 반드시 숫자가 오고, 그 숫자 앞이 영문자면 안 된다.
# (?<![A-Za-z]) 가 없으면 '갤럭시 A15 5G' 의 '5G' 를 5그램으로 읽는다.
_VOLUME_RE = re.compile(
    r"(?<![A-Za-z])(?<![\d.])(\d+(?:\.\d+)?)\s*(ml|mL|ML|리터|L|l)(?![A-Za-z가-힣])")
# 단독 대문자 'G' 는 뺀다. 한국 커머스에서 그램은 'g'/'kg' 로 쓰고,
# 대문자 G 는 거의 항상 통신 규격이다('갤럭시 A15 5G' → 5그램으로 읽혔다).
_WEIGHT_RE = re.compile(
    r"(?<![A-Za-z])(?<![\d.])(\d+(?:\.\d+)?)\s*(kg|KG|Kg|g)(?![A-Za-z가-힣])")

#: '500ml*20', '48mm x 40m' 같은 곱셈·치수 표기
_MULT_RE = re.compile(r"[*xX×]\s*(\d{1,4})\b")

#: 종이 평량(g/m²)이 상품명에 나오는 맥락. 이걸 중량으로 읽으면 도화지가 16kg 이 된다.
_PAPER = re.compile(r"(절지?|평량|도화지|복사지|인쇄지|A4|A3|B4|B5|모조지|아트지)")

#: 무게가 '내용물'이 아니라 '빈 용기 수용량'인 상품. 단가의 지시 대상이 없다.
_CONTAINER = re.compile(r"(용기|컵|그릇|보관함|밀폐|텀블러|물통|공병|스프레이\s*병)")

#: 서로 다른 물건을 묶은 표기. 수량을 곱하면 안 된다(AA 4개 + AAA 4개 = 8개지 16개가 아니다).
_MIXED = re.compile(r"[+＋]|혼합|모둠|랜덤|각\s*\d")

_TO_ML = {"ml": 1.0, "l": 1000.0, "리터": 1000.0}
_TO_G = {"g": 1.0, "kg": 1000.0}


def _norm(u: str) -> str:
    return u.lower().replace("ℓ", "l")


def parse_quantity(title: str) -> dict:
    """
    상품명에서 수량 정보를 뽑는다. 조금이라도 애매하면 그 항목을 통째로 뺀다.

    돌려주는 키:
      count / count_unit / count_parts  낱개 수량
      sheets                            장수(매·장) — 낱개와 구분해서 담는다
      unit_volume_ml / unit_weight_g    '낱개 하나'의 용량·중량
      ambiguous                         계산을 포기한 이유(있으면 단가를 만들지 않는다)
    """
    t = (title or "").strip()
    if not t:
        return {"ambiguous": "상품명 없음"}
    out = {}

    # ── 낱개 수량 ──
    # 쿠팡 상품명은 '…, 22개입, 2개' 처럼 포장 단위를 겹쳐 쓴다. 이때는 곱해야 한다.
    # 다만 'AA 4개 + AAA 4개' 처럼 다른 물건을 나열한 것은 곱하면 안 된다.
    items = [(int(m.group(1)), m.group(2)) for m in _ITEM_RE.finditer(t)]
    items = [(n, u) for n, u in items if 2 <= n <= 10000]
    if items:
        if _MIXED.search(t) and len(items) > 1:
            out["ambiguous"] = "서로 다른 구성품이 섞여 있어 수량을 확정할 수 없음"
        else:
            total = 1
            for n, _ in items:
                total *= n
            if total > 100000:
                out["ambiguous"] = "수량이 비상식적으로 큼"
            else:
                out["count"] = total
                out["count_unit"] = items[0][1] if len(items) == 1 else "개"
                out["count_parts"] = [n for n, _ in items] if len(items) > 1 else []

    # ── 장수 ── 낱개와 절대 섞지 않는다.
    sheets = [int(m.group(1)) for m in _SHEET_RE.finditer(t)]
    sheets = [n for n in sheets if 2 <= n <= 100000]
    if sheets:
        s = 1
        for n in sheets:
            s *= n
        out["sheets"] = s

    # ── 곱셈 표기 ── '500ml*20' 의 20 은 위 정규식에 안 잡힌다.
    mult = _MULT_RE.search(t)
    if mult and "count" not in out:
        n = int(mult.group(1))
        if 2 <= n <= 10000:
            out["count"] = n
            out["count_unit"] = "개"
            out["count_parts"] = []

    # ── 용량·중량 ──
    vols = _VOLUME_RE.findall(t)
    wgts = _WEIGHT_RE.findall(t)

    if len(vols) > 1 or len(wgts) > 1:
        out.setdefault("ambiguous", "용량 표기가 여러 개라 어느 것이 낱개 용량인지 알 수 없음")
    elif vols:
        if _CONTAINER.search(t):
            out.setdefault("ambiguous", "빈 용기의 수용량이라 내용물 단가를 낼 수 없음")
        else:
            v, u = vols[0]
            out["unit_volume_ml"] = float(v) * _TO_ML[_norm(u)]
    elif wgts:
        if _PAPER.search(t):
            out.setdefault("ambiguous", "종이 평량(g/m²)으로 보여 중량으로 쓸 수 없음")
        elif sheets:
            # '50g, 70매, 4개' 에서 50g 이 한 장인지 한 팩인지 상품명만으로는 모른다.
            out.setdefault("ambiguous", "장수와 중량이 함께 있어 기준을 확정할 수 없음")
        else:
            w, u = wgts[0]
            out["unit_weight_g"] = float(w) * _TO_G[_norm(u)]

    if not out:
        return {"ambiguous": "수량·용량 표기 없음"}
    return out


def compute(title: str, current_price: int) -> dict:
    """단가를 계산한다. 계산할 수 없거나 애매하면 빈 dict — 이게 정상 동작이다."""
    price = int(current_price or 0)
    if price <= 0:
        return {}
    q = parse_quantity(title)
    if q.get("ambiguous"):
        return {}

    out = {"quantity": q}
    n = q.get("count")
    sheets = q.get("sheets")

    if n:
        out["per_item"] = round(price / n)
        # '6팩'을 '6개'라고 바꿔 부르지 않는다. 세는 단위를 그대로 쓴다.
        # 다만 '개입'은 '몇 개가 들었다'는 뜻이라 '개입당'은 어색하다 — '개당'으로 읽는다.
        # '개입'은 '몇 개 들었다'는 뜻, '종'은 세트 구성 가짓수 — 둘 다 '개당'으로 읽는 게 자연스럽다.
        u = q.get("count_unit", "개")
        out["per_item_unit"] = "개" if u in ("개입", "종") else u
    elif sheets:
        # 장수만 있으면 '장당'이라고 부른다. '개당'이라고 하면 거짓이다.
        out["per_item"] = round(price / sheets)
        out["per_item_unit"] = "장"

    ml = q.get("unit_volume_ml")
    g = q.get("unit_weight_g")
    if ml:
        total = ml * (n or 1)
        out["total_ml"] = total
        out["per_100ml"] = round(price / total * 100, 1)
    elif g:
        total = g * (n or 1)
        out["total_g"] = total
        out["per_100g"] = round(price / total * 100, 1)

    return out if len(out) > 1 else {}


def context_lines(title: str, current_price: int) -> list:
    """프롬프트의 [실측 데이터] 블록에 넣을 줄. 계산 과정을 같이 적어 검산이 되게 한다."""
    c = compute(title, current_price)
    if not c:
        return []
    price = int(current_price)
    q = c["quantity"]
    lines = []

    if "per_item" in c:
        unit = c["per_item_unit"]
        n = q.get("count") or q.get("sheets")
        parts = q.get("count_parts") or []
        how = f"{'×'.join(str(x) for x in parts)}={n}{unit}" if parts else f"{n}{unit}"
        lines.append(f"- {unit}당 단가: {price:,}원 ÷ {how} = {c['per_item']:,}원")
    if "per_100ml" in c:
        lines.append(f"- 100ml당 단가: 총 {c['total_ml']:,.0f}ml 기준 {c['per_100ml']:,.1f}원")
    if "per_100g" in c:
        lines.append(f"- 100g당 단가: 총 {c['total_g']:,.0f}g 기준 {c['per_100g']:,.1f}원")
    return lines


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    #: 앞판이 틀렸던 사례를 전부 포함한다. 여기서 '계산 안 함'이 나와야 정상이다.
    CASES = [
        ("빙그레 아카페라 아메리카노 1L 12개", 18080, "12개 × 1L"),
        ("해표 카놀라유, 900ml, 2개", 9800, "2개 × 900ml"),
        ("순수한면 생리대 날개형, 중형, 22개입, 2개", 12900, "22×2=44개"),
        ("미샤 소프트 면봉 72mm", 1760, "계산 안 함(72mm 는 길이)"),
        ("탐사 스케치북 도화지 130g 8절, 125매", 3900, "계산 안 함(130g 은 평량)"),
        ("크리넥스 물티슈 캡형, 50g, 70매, 4개", 5580, "계산 안 함(장수+중량)"),
        ("삼성 갤럭시 A15 5G 케이스", 12000, "계산 안 함(5G 는 규격)"),
        ("탐사 종이용기 520ml, 100개입", 9900, "계산 안 함(빈 용기)"),
        ("생수 500ml*20", 8900, "20개 × 500ml"),
        ("맥주 500ml 캔 24캔", 40000, "24캔 × 500ml"),
        ("건전지 AA 4개 + AAA 4개", 8000, "계산 안 함(혼합 구성)"),
        ("코멧 미니 미용티슈, 6팩, 230매", 5520, "6팩 기준"),
    ]
    bad = 0
    for t, p, expect in CASES:
        got = context_lines(t, p)
        print(f"\n{t}  ({p:,}원)")
        print(f"   기대: {expect}")
        if got:
            for line in got:
                print(f"   {line}")
        else:
            print("   → 계산 안 함")
