from core import guardrails as g

CTX = ("전세 보증보험은 보증료가 연 0.128%입니다. 3억 전세면 연 38만원."
       "\n가입은 계약 기간의 절반이 지나기 전까지 가능합니다."
       "\n보증 한도는 수도권 7억원입니다.")

def test_fabricated_number_blocked():
    r = g.check("가입자의 92%가 만족했습니다", CTX)
    assert not r["ok"]
    assert any("92" in b for b in r["blocking"])

def test_known_and_derived_numbers_pass():
    # 38만원(원문 존재), 0.128%(존재), 3억-7억 차이 4억(뺄셈 파생)
    r = g.check("보증료는 연 0.128%로 3억 기준 연 38만원이다.", CTX)
    assert r["ok"], r["blocking"]

def test_superlative_blocked_but_hedge_passes():
    assert not g.check("이 방법이 최저가로 가입하는 유일한 방법입니다", CTX)["ok"]
    assert g.check("최저가인지 아닌지 이 글은 확인할 수 없다.", CTX)["ok"]

def test_space_evasion_blocked():
    assert not g.check("최 저 가 방법입니다", CTX)["ok"]

def test_first_person_blocked():
    assert not g.check("제가 직접 써 봤는데 간단했어요", CTX)["ok"]

def test_date_numbers_ignored():
    r = g.check("2026년 8월 기준으로 확인된 내용이다", CTX)
    assert r["ok"], r["blocking"]

def test_no_context_warns():
    r = g.check("좋은 방법이다", "")
    assert r["ok"] and r["warnings"]

def test_copy_detection():
    src = ["전세 보증보험은 보증료가 연 0.128%입니다. 3억 전세면 연 38만원."]
    hits = g.check_copy("놀랍게도 전세 보증보험은 보증료가 연 0.128%입니다.", src)
    assert hits                                   # 연속 15자+ 복사
    assert not g.check_copy("보증료는 연 0.128%다. 즉 3억이면 38만원 수준.", src)

def test_derived_subtraction_passes():
    # 4억은 CTX에 없지만 7억-3억 뺄셈 파생 → 통과해야 한다
    r = g.check("보증 한도 7억원과 전세가 3억의 차이는 4억원이다.", CTX)
    assert r["ok"], r["blocking"]

def test_first_person_hedged_passes():
    r = g.check("제가 써본 적은 없지만 후기를 종합하면 이렇다.", CTX)
    assert r["ok"], r["blocking"]

def test_same_value_date_then_fabricated_blocked():
    r = g.check("3층 매장인데 이용자가 3배 늘었다는 주장이 있다.", "매장 정보 없음")
    assert not r["ok"]                     # 3배는 컨텍스트에 없는 숫자
