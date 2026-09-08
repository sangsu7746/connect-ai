# ============================================================
#  tests/test_loan_disclosure.py — 대부업법 제9조 필수기재사항
#
#  무엇을 지키는 테스트인가:
#    1) 대출 소재의 최종 캡션에 법 제9조제3항 + 시행령 제6조제3항 **전 항목**이
#       실린다(13종). 예전 판본은 6종만 알고 있었고, 그 6종만 채우면 게이트가
#       열려 **나머지가 빠진 광고가 '법정 필수 표기' 머리표를 달고** 나갔다.
#    2) 항목이 하나라도 비면 **소재 생성과 발행이 모두 차단**된다
#       (빈 값을 지어내 채우지 않는다)
#    3) 경고문구는 [별표1] 2.가 의 **지정문구**여야 하고, 이자율은 연 환산
#       표기여야 한다 - 값이 있다는 이유만으로 통과시키지 않는다
#    4) ★ 다른 업종(mirizip·inkcraft 등 14개)에는 대출 문구가 절대 안 붙는다
#    5) 등록 유효기간이 지나면 차단, 갱신 창구면 renewal_due
#    6) LLM 이 카피를 다시 써도 의무표기가 남고, LLM 출력이 업종 표식
#       (profile_key)을 덮어쓸 수 없다
#    7) 새 문구가 cp949 콘솔에서 인코딩된다(이 프로젝트는 이 사고로 job 이 죽은 적 있다)
#    8) 이미지에 의무표기가 **몇 줄** 그려졌는지까지 본다([별표1] 1.가/1.다) -
#       흰 픽셀 총량만 세면 13종 중 1종만 인쇄돼도 통과한다
#    9) 소재를 구울 때의 값과 발행 시점의 값이 다르면 막는다(지문 대조)
#   10) 프로필 파일이 사라져도 fail-open 하지 않는다
#
#  ⚠ DB 를 쓰는 테스트는 반드시 temp_db fixture 를 받는다(data/autoad.db 보호).
#    AUTOAD_DB 환경변수는 건드리지 않는다.
# ============================================================
import time
from datetime import date

import pytest

import config
import orchestrator
import profiles
from channels.base import PostResult
from content import disclosure, pamphlet

# 운영자가 채워야 하는 값의 '테스트용' 예시. 실제 값이 아니다.
#
# ⚠ 2026-08-09 운영자가 실제 값을 확인해 주어 profiles/loan.yaml 이 완성됐다
#   (커밋 216c47929). 그 전까지 이 파일의 여러 테스트는 "실제 yaml 이 비어
#   있다"는 전제로 미완성 동작을 검증했고, yaml 이 채워지자 9건이 깨졌다.
#   전제가 사라졌으므로 **미완성 상태는 _empty_loan()/_incomplete_profile() 로
#   명시적으로 만들어** 검증한다. 실제 yaml 은 완성된 채로 둔다.
#   실제 yaml 이 완성·유효한지는 test_real_profile_is_complete_and_valid 가 지킨다.
FAKE_RATE = "연 5.9% ~ 연 20.0% (연 환산 기준)"
FAKE_OVERDUE = "연 20.0% (연 환산 기준)"
FAKE_COSTS = "근저당설정비, 인지대 등 실비가 발생할 수 있습니다"
FAKE_EARLY = "조기상환수수료 없음"

# 캡션·이미지에 반드시 들어가야 하는 핵심 문자열.
# ⚠ 법 제9조제3항 각 호 + 시행령 제6조제3항 **전 항목**이다. 예전 판본은
#   6종만 알고 있었고(명칭·연체이자율·조기상환조건·신용등급 경고문구·주소·
#   등록관청 누락), 그 6종만 채우면 게이트가 열렸다.
# ⚠ 경고문구는 [별표1] 2.가 가 **지정한 문장**이다. 예전 판본은 "가져올"
#   이라는 비지정 문장을 하드코딩해 두어, 구현과 테스트가 같은 오답을
#   공유하고 있었다(뮤테이션 13종을 통과해도 잡히지 않는 종류의 결함).
MUST_HAVE = (
    "(주)더스틴홀딩스대부중개",                            # 1. 명칭(상호)
    "2026-대구중구-0002",                              # 2. 등록번호
    FAKE_RATE,                                         # 3. 대부이자율(연 환산)
    FAKE_OVERDUE,                                      # 3. 연체이자율
    FAKE_COSTS,                                        # 4. 부대비용
    FAKE_EARLY,                                        # 5. 조기상환조건
    "과도한 빚은 당신에게 큰 불행을 안겨 줄 수 있습니다.",   # 6. 과도차입 경고(지정문구)
    "대출 시 귀하의 신용등급이 하락할 수 있습니다.",        # 6. 신용등급 경고(지정문구)
    "대구광역시 중구 공평로 105",                        # 7. 영업소 주소
    "010-2577-2679",                                   # 7. 등록된 광고용 전화번호
    "대구광역시 중구청",                                 # 8. 등록한 시·도
    "053-661-2655",                                    # 8. 등록정보 확인 전화
    "중개수수료를 요구하거나 받는 것은 불법입니다.",        # 9. 중개수수료 불법 고지
)


# ── 도구 ────────────────────────────────────────────────────
class _RecordingAdapter:
    """브라우저 대신 호출 인자만 기록한다(test_orchestrator_threads.py 와 같은 방식)."""

    def __init__(self, platform="band", **kw):
        self.platform = platform
        self.calls = []
        self.account_id = ""
        self._logged_in = True
        self._login_at = time.time()
        self._current_post_id = None

    def login(self, cred=None):
        return True

    def _rate_ok(self, channel_id=None):
        return True

    def _rate_reason(self, channel_id=None):
        return ""

    def post(self, target, text, image_path=None, dry_run=True):
        self.calls.append({"target": target, "text": text, "dry_run": dry_run})
        return PostResult(ok=True, perm_url="https://example.test/ok", dry_run=dry_run)


def _fill_loan(monkeypatch, rate=FAKE_RATE, costs=FAKE_COSTS,
               overdue=FAKE_OVERDUE, early=FAKE_EARLY, flyer_ok=True):
    """운영자가 빈 항목을 전부 채운 상태를 흉내낸다.

    monkeypatch.setitem 이라 테스트가 끝나면 원래대로 돌아간다 -
    profiles/loan.yaml 은 빈 채로 남는다."""
    m = config.PROFILE["compliance"]["mandatory"]
    monkeypatch.setitem(m, "interest_rate", rate)
    monkeypatch.setitem(m, "overdue_rate", overdue)
    monkeypatch.setitem(m, "extra_costs", costs)
    monkeypatch.setitem(m, "early_repayment", early)
    # 전단 인쇄 전화번호 확인 플래그(실제 yaml 은 false 여야 한다)
    monkeypatch.setitem(m, "flyer_phone_verified", bool(flyer_ok))
    # 소재 생성 시점에 캡션에 박히는 값도 같이 갱신(config 로드 시 1회 계산됨)
    monkeypatch.setattr(config, "MANDATORY_DISCLOSURE",
                        disclosure.build(config.PROFILE))


# 운영자가 채워야 하는 '사업상' 항목. 등록증에서 그대로 옮겨 적을 수 있는
# 항목(주소·등록관청 등)이나 법정 지정문구와 달리, 이 넷은 업체의 영업조건이라
# 지어낼 수 없다. 미완성 상태를 흉내낼 때 비우는 것도 이 넷이다.
BUSINESS_FIELDS = ("interest_rate", "overdue_rate", "extra_costs", "early_repayment")


def _empty_loan(monkeypatch, *fields):
    """운영자가 값을 채우기 **전** 상태를 흉내낸다(_fill_loan 의 반대).

    monkeypatch.setitem 이라 테스트가 끝나면 원래대로 돌아간다 -
    profiles/loan.yaml 은 채워진 채로 남는다."""
    m = config.PROFILE["compliance"]["mandatory"]
    for f in (fields or BUSINESS_FIELDS):
        monkeypatch.setitem(m, f, "")
    # 캡션에 박히는 값도 같이 갱신(config 로드 시 1회 계산됨)
    monkeypatch.setattr(config, "MANDATORY_DISCLOSURE",
                        disclosure.build(config.PROFILE))


def _incomplete_profile(*fields):
    """디스크에서 읽은 프로필의 **복사본**에서 사업상 항목을 비운다.

    config.PROFILE 이 아니라 profiles.load() 결과를 직접 쓰는 테스트용.
    deepcopy 라 원본 캐시를 오염시키지 않는다."""
    import copy
    prof = copy.deepcopy(profiles.load("loan"))
    for f in (fields or BUSINESS_FIELDS):
        prof["compliance"]["mandatory"][f] = ""
    return prof


def _no_wait(monkeypatch):
    monkeypatch.setattr(config, "GLOBAL_DRY_RUN", False)
    monkeypatch.setattr(config, "POST_HOURS_START", 0)
    monkeypatch.setattr(config, "POST_HOURS_END", 0)
    monkeypatch.setattr(config, "POST_INTERVAL_MIN", 0)
    monkeypatch.setattr(config, "POST_INTERVAL_MAX", 0)


def _make_band_creative(caption, image=None):
    """실발행 경로를 탈 수 있는 밴드 채널 + 크리에이티브.

    ⚠ 이름·주소에 '테스트'/band/1 같은 걸 쓰면 db.is_demo_channel 이
      게이트보다 먼저 막아서 이 테스트가 아무것도 검증하지 못한다."""
    import db
    ch = db.add_channel("band", "https://band.us/band/87654321", name="대구 자영업 모임")
    camp = db.add_campaign("대출 캠페인")
    cid = db.add_creative(camp, ch, caption, image)
    return ch, camp, cid


def _loan_caption():
    return {
        "headline": "아파트 담보대출 상담",
        "body": "보유 아파트의 가치를 활용한 자금 설계를 도와드립니다.",
        "cta": "상담 문의",
        "profile_key": "loan",
        "disclaimer": config.DISCLAIMER,
        "mandatory": config.MANDATORY_DISCLOSURE,
        "brand": config.BRAND_COMPANY,
        # 이미지에 실제로 구워진 의무표기의 지문(orchestrator.run_campaign 이 박는다).
        # 없으면 발행 게이트 C 가 '이미지가 현재 값과 다르다'로 막는다.
        "mandatory_img": config.mandatory_fingerprint("loan"),
    }


# ── 1) 필수기재 전 항목이 최종 캡션에 들어가는가 ─────────────
def test_mandatory_block_contains_all_statutory_items(monkeypatch):
    _fill_loan(monkeypatch)
    block = disclosure.build(config.PROFILE)
    for needle in MUST_HAVE:
        assert needle in block, f"의무표기 블록에 없음: {needle}"
    # 그 밖의 광고사항과 구별되도록 머리표가 붙는다([별표1])
    assert "법정 필수 표기" in block


def _band_blob(prof_key: str = None) -> str:
    """소재 **이미지**에 그려지는 의무표기 전체(머리글 + 하단 띠).

    ⚠ 규칙을 여기 베껴 적지 않는다. pamphlet.band_lines() 를 그대로 부른다 -
      중복 제거 규칙이 한쪽만 바뀌면 이 테스트가 조용히 거짓 통과한다."""
    from content import pamphlet
    key = prof_key or config.PROFILE_KEY
    hdr = config.mandatory_header_lines(key)
    lns = config.mandatory_lines(key)
    return "\n".join(list(hdr) + pamphlet.band_lines(lns, hdr))


def test_mandatory_reaches_the_ad_via_the_image_band(temp_db, monkeypatch):
    """의무표기가 **광고에 도달하는가**. dry-run 이라도 adapter 에 넘어가는
    본문 + 이미지 띠가 최종 광고다.

    ⚠ 2026-08-11 설계 변경: 예전에는 본문에도 같은 14줄을 붙였다. 그런데
      pamphlet 이 이미 같은 내용을 이미지 띠에 굽고 있어(실측: 이미지의
      45.8%) 광고가 전단보다 고지글로 보였다. 그래서 **이미지 띠가 현재
      값과 일치함이 증명된 소재에 한해** 본문에서는 뺀다.
      → 검사 대상이 '본문'에서 '광고 전체(본문+띠)'로 옮겨온 것이지,
        어느 항목도 광고에서 사라지면 안 된다는 요건은 그대로다.
      폴백(지문 없음·불일치 → 본문 유지)은 아래 별도 테스트가 지킨다."""
    _fill_loan(monkeypatch)
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    cap = _loan_caption()
    _, _, cid = _make_band_creative(cap)

    orchestrator.publish_creative(cid, dry_run=True)

    text = fake.calls[0]["text"]
    band = _band_blob()
    for needle in MUST_HAVE:
        assert needle in f"{text}\n{band}", f"광고 어디에도 없음: {needle}"
        assert needle in band, f"이미지 띠에 없음(본문에서 뺐는데): {needle}"

    # 중복 제거가 실제로 일어났는지 - 안 그러면 이 변경의 의미가 없다.
    assert "중개수수료를 요구하거나 받는 것은 불법입니다." not in text
    assert "[대부중개업 법정 필수 표기]" not in text
    # 면책문구는 띠에 없다. 본문에 그대로 남아야 한다.
    assert config.DISCLAIMER in text


def test_mandatory_stays_in_caption_when_image_is_not_proven(temp_db, monkeypatch):
    """★ 안전망. 이미지에 띠가 있다는 **증거가 없으면** 본문에서 빼지 않는다.

    미표기는 중복보다 훨씬 나쁘다. 지문이 없거나(쓰레드 답글·레거시 소재)
    현재 값과 다르면(옛 이미지) 본문에 그대로 실려야 한다."""
    _fill_loan(monkeypatch)

    for label, mutate in (
        ("지문 키 자체가 없음", lambda c: c.pop("mandatory_img", None)),
        ("지문이 빈 문자열", lambda c: c.update(mandatory_img="")),
        ("지문이 옛 이미지 것", lambda c: c.update(mandatory_img="deadbeef1234")),
    ):
        cap = _loan_caption()
        mutate(cap)
        text = orchestrator._caption_text(cap, "loan")
        for needle in MUST_HAVE:
            assert needle in text, f"{label}: 본문에서 사라졌다 - {needle}"


# ── 2) 이자율·부대비용이 비면 gaps 가 잡고 발행이 차단되는가 ──
def test_real_profile_is_complete_and_valid():
    """profiles/loan.yaml 이 **완성된 채로** 유지되는지 지킨다.

    2026-08-09 운영자가 사업상 4개 값을 확인해 주어 게이트가 열렸다.
    누가 값을 지우거나 법에 안 맞는 형태로 바꾸면 여기서 잡힌다.
    (예전 판본은 반대로 '비어 있어야 한다'를 단언했다. 지어낸 예시값이
     커밋되는 걸 막으려는 가드였는데, 진짜 값이 들어오자 그대로 깨졌다.)"""
    gaps = config.loan_compliance_gaps()
    assert gaps == [], f"실제 프로필에 빈 필수항목이 있다: {gaps}"

    # 이자율은 연 환산 표기여야 한다(법 제9조제3항제3호). 월 이자율만 적으면
    # disclosure 가 거부하므로 gaps 가 비었다는 것만으로도 보장되지만,
    # 값이 실제로 '연' 을 달고 있는지 눈으로 확인할 수 있게 남긴다.
    m = config.PROFILE["compliance"]["mandatory"]
    assert "연" in m["interest_rate"], m["interest_rate"]
    assert "연" in m["overdue_rate"], m["overdue_rate"]
    # 비어 있으면 안 되는 것이지 "없음"은 유효한 표기다(공란이 미표기다)
    assert m["extra_costs"].strip()
    assert m["early_repayment"].strip()

    # 전단 전화번호는 2026-08-07 에 교체를 마쳤다(구번호 010-4649-5078 27곳 ->
    # 등록 광고용 번호 010-2577-2679, content/templates/flyers_v2).
    # 위험한 조합을 막는다: 플래그만 true 로 올려 놓고 flyers_dir 은 구번호가
    # 인쇄된 원본을 그대로 가리키는 상태. 게이트는 열려 있는데 미등록 번호가
    # 박힌 전단이 그대로 발행된다.
    old = profiles.resolve_dir("content/templates/flyers")
    assert config.FLYERS_DIR.resolve() != old.resolve(), \
        "flyer_phone_verified 가 true 인데 flyers_dir 이 구번호 원본을 가리킨다: %s" % config.FLYERS_DIR


def test_gaps_report_business_fields_when_empty(monkeypatch):
    """사업상 값이 비면 gaps 가 **넷 다** 이름을 대며 잡는다."""
    _empty_loan(monkeypatch)
    gaps = config.loan_compliance_gaps()
    assert "대부이자율(연 환산)" in gaps
    assert "대부계약 관련 부대비용" in gaps
    assert "연체이자율(연 환산)" in gaps
    assert "조기상환수수료율 등 조기상환조건" in gaps
    # 등록번호·전화번호·지정문구는 등록증에서 옮긴 값이라 비지 않는다
    assert "대부중개업 등록번호" not in gaps
    assert "등록된 광고용 전화번호" not in gaps
    assert "명칭(상호)" not in gaps
    # 전단은 교체를 마쳤으므로 이 상태에서도 gap 이 아니다
    assert not any("전단" in g for g in gaps), gaps


def test_gate_blocks_and_names_missing_fields(monkeypatch):
    _empty_loan(monkeypatch)
    why = orchestrator._profile_gate("loan", "band")
    assert why, "필수 항목이 빈 상태인데 게이트가 통과시켰다"
    assert "대부이자율(연 환산)" in why
    assert "대부계약 관련 부대비용" in why
    assert "연체이자율(연 환산)" in why
    assert "조기상환수수료율 등 조기상환조건" in why


def test_gate_opens_on_the_real_profile():
    """완성된 실제 프로필에서는 게이트가 열려 있어야 한다(밴드 기준)."""
    assert orchestrator._profile_gate("loan", "band") is None


# ── 2-b) 항목을 하나만 비워도 각각 막히는가 ──────────────────
# ⚠ 예전 판본의 진짜 결함은 '6종을 채우면 열린다'였다. 나머지 법정 항목이
#   빠진 광고가 '[대부중개업 법정 필수 표기]' 머리표를 달고 나갔다.
@pytest.mark.parametrize("field,label", [
    ("interest_rate", "대부이자율(연 환산)"),
    ("overdue_rate", "연체이자율(연 환산)"),
    ("extra_costs", "대부계약 관련 부대비용"),
    ("early_repayment", "조기상환수수료율 등 조기상환조건"),
    ("overborrow_warning", "과도한 차입 위험성 경고문구"),
    ("credit_warning", "신용등급 하락 가능성 경고문구"),
    ("address", "영업소의 주소"),
    ("reg_authority", "등록한 시·도의 명칭"),
    ("reg_authority_tel", "등록정보 확인 전화번호"),
    ("broker_fee_notice", "중개수수료 불법 고지문구"),
])
def test_each_statutory_field_alone_blocks_publish(monkeypatch, field, label):
    _fill_loan(monkeypatch)
    assert orchestrator._profile_gate("loan", "band") is None   # 우선 열려 있고
    monkeypatch.setitem(config.PROFILE["compliance"]["mandatory"], field, "")
    why = orchestrator._profile_gate("loan", "band")
    assert why and label in why, f"{field} 가 비었는데 게이트가 통과시켰다"


@pytest.mark.parametrize("field", ["company", "reg_no"])
def test_brand_sourced_fields_also_block(monkeypatch, field):
    _fill_loan(monkeypatch)
    monkeypatch.setitem(config.PROFILE["brand"], field, "")
    why = orchestrator._profile_gate("loan", "band")
    assert why and "필수기재" in why


# ── 2-c) 법정 지정문구가 아니면 거부하는가 ───────────────────
def test_non_standard_warning_text_is_rejected(monkeypatch):
    """[별표1] 2.가 는 경고문구를 **지정**한다. 비슷한 문장은 통과하면 안 된다.

    실제로 이 리포는 "...큰 불행을 **가져올** 수 있습니다." 라는 비지정
    문장을 쓰고 있었다(지정문구는 "안겨 줄"). 값이 비어 있지 않다는
    이유만으로 게이트가 열리면 이런 오류가 영원히 안 잡힌다."""
    _fill_loan(monkeypatch)
    monkeypatch.setitem(config.PROFILE["compliance"]["mandatory"],
                        "overborrow_warning",
                        "과도한 빚은 당신에게 큰 불행을 가져올 수 있습니다.")
    why = orchestrator._profile_gate("loan", "band")
    assert why and "지정문구" in why


def test_all_standard_phrases_are_accepted(monkeypatch):
    """지정문구 목록에 든 문장은 전부 통과해야 한다(운영자 선택권)."""
    _fill_loan(monkeypatch)
    m = config.PROFILE["compliance"]["mandatory"]
    for s in disclosure.STANDARD_OVERBORROW:
        monkeypatch.setitem(m, "overborrow_warning", s)
        assert orchestrator._profile_gate("loan", "band") is None, s
    monkeypatch.setitem(m, "overborrow_warning", disclosure.STANDARD_OVERBORROW[1])
    for s in disclosure.STANDARD_CREDIT:
        monkeypatch.setitem(m, "credit_warning", s)
        assert orchestrator._profile_gate("loan", "band") is None, s


def test_monthly_rate_without_annual_conversion_is_rejected(monkeypatch):
    """법 제9조제3항제3호 - 연 이자율로 환산한 것을 포함해야 한다.
    월 이자율만 적으면 값이 있어도 통과시키지 않는다."""
    _fill_loan(monkeypatch)
    monkeypatch.setitem(config.PROFILE["compliance"]["mandatory"],
                        "interest_rate", "월 1.6%")
    why = orchestrator._profile_gate("loan", "band")
    assert why and "환산" in why


def test_real_publish_blocked_when_mandatory_missing(temp_db, monkeypatch):
    """실발행 경로에서 실제로 막히고, 어댑터가 **불리지 않아야** 한다."""
    _no_wait(monkeypatch)
    _empty_loan(monkeypatch)
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    _, _, cid = _make_band_creative(_loan_caption())

    res = orchestrator.publish_creative(cid, dry_run=False)

    assert res.ok is False and res.blocked is True
    assert "필수기재" in (res.error or "")
    assert fake.calls == [], "차단됐는데 어댑터가 호출됐다(광고가 나갔다)"


# ── 3) 두 값을 채우면 발행이 허용되는가 ──────────────────────
def test_real_publish_allowed_when_mandatory_filled(temp_db, monkeypatch):
    _no_wait(monkeypatch)
    _fill_loan(monkeypatch)
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    _, _, cid = _make_band_creative(_loan_caption())

    res = orchestrator.publish_creative(cid, dry_run=False)

    assert res.ok is True, f"채웠는데도 막혔다: {getattr(res, 'error', None)}"
    assert len(fake.calls) == 1
    # 의무표기는 이미지 띠가 나른다(위 test_mandatory_reaches_the_ad_via_the_image_band).
    blob = f"{fake.calls[0]['text']}\n{_band_blob()}"
    for needle in MUST_HAVE:
        assert needle in blob, f"광고 어디에도 없음: {needle}"


def test_dry_run_is_not_blocked_but_warns(temp_db, monkeypatch):
    """사전 점검용 dry-run 은 막지 않는다(막으면 점검 자체가 불가능해진다).
    대신 실발행 시 막힐 것이라는 사실이 사유로 남아야 한다."""
    import db
    _empty_loan(monkeypatch)
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    _, _, cid = _make_band_creative(_loan_caption())

    res = orchestrator.publish_creative(cid, dry_run=True)

    assert res.ok is True
    assert len(fake.calls) == 1
    with db.get_conn() as conn:
        err = conn.execute("SELECT error FROM posts WHERE creative_id=?",
                           (cid,)).fetchone()["error"]
    assert "실발행 시 차단됨" in (err or "")


# ── 4) ★ 무회귀 — 다른 업종에 대출 의무표기가 붙지 않는가 ────
@pytest.mark.parametrize("key", ["mirizip", "inkcraft", "adstudio", "homage",
                                 "photomagic", "printcraft"])
def test_other_profiles_have_no_loan_disclosure(key):
    """다른 업종 광고에 대출 문구가 붙는 것 자체가 사고다."""
    prof = profiles.load(key)
    assert disclosure.required_keys(prof) == []
    assert disclosure.build(prof) == ""
    assert disclosure.gaps(prof) == []
    assert disclosure.lines(prof) == []
    assert disclosure.registration_expired(prof) is False
    assert disclosure.renewal_due(prof) is False
    # config 경유(발행 게이트가 실제로 쓰는 경로)도 같아야 한다
    assert config.mandatory_disclosure(key) == ""
    assert config.mandatory_lines(key) == []
    assert config.compliance_gaps(key) == []


def test_other_profile_creative_publishes_without_loan_text(temp_db, monkeypatch):
    """mirizip 소재를 loan 프로세스가 발행해도 대출 문구가 붙으면 안 된다."""
    _no_wait(monkeypatch)
    _fill_loan(monkeypatch)          # loan 쪽은 완비 상태여도
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    _, _, cid = _make_band_creative({
        "headline": "인테리어 시안", "body": "사진 한 장으로 미리 봅니다.",
        "cta": "무료로 해보기", "profile_key": "mirizip",
        "disclaimer": "", "mandatory": "",
    })

    res = orchestrator.publish_creative(cid, dry_run=False)

    assert res.ok is True
    text = fake.calls[0]["text"]
    for needle in ("2026-대구중구-0002", "대부", "중개수수료", "과도한 빚",
                   "010-2577-2679"):
        assert needle not in text, f"타 업종 광고에 대출 문구가 붙었다: {needle}"


def test_platform_gate_judges_by_creative_profile_not_active_profile():
    """업종x플랫폼 판정은 **소재의 업종**으로 해야 한다(config.platform_allowed 주석).

    발행 프로세스의 업종(config.PROFILE_KEY, 보통 loan)으로 판정하면:
      · loan 이 threads 를 막고 있으므로 mirizip 소재까지 덩달아 막히고
      · 쓰레드용으로 AUTOAD_PROFILE 을 바꾸는 순간 loan 소재가 threads 로 샌다.
    이 테스트는 활성 프로필(loan)과 소재 업종이 다를 때만 차이가 드러난다."""
    assert config.PROFILE_KEY == "loan"
    # loan 은 band/facebook 만 허용 → threads 로는 절대 못 나간다
    assert orchestrator._profile_gate("loan", "threads")
    # mirizip 은 allow_platforms 가 없다(제한 없음) → loan 이 threads 를
    # 막고 있어도 mirizip 소재는 threads 로 나갈 수 있어야 한다
    assert orchestrator._profile_gate("mirizip", "threads") is None
    assert orchestrator._profile_gate("mirizip", "band") is None


def test_other_profiles_still_load_without_mandatory_keys():
    """프로필 로더가 새 키를 요구하지 않는다(14개가 그대로 뜬다)."""
    for key in profiles.available():
        if key.startswith("_"):
            continue
        p = profiles.load(key)
        assert isinstance(p["compliance"]["mandatory"], dict)
        assert isinstance(p["compliance"]["mandatory_required"], list)
        if key != "loan":
            assert p["compliance"]["mandatory_required"] == []


def test_empty_field_produces_no_line_at_all():
    """값이 비면 '대부이자율 ' 같은 빈 라벨을 찍지 않는다.
    빈 라벨은 표기한 척만 하는 것이라 미표기보다 나쁘다."""
    prof = _incomplete_profile()     # 사업상 값을 비운 프로필 사본
    ls = disclosure.lines(prof)
    for lab in ("대부이자율", "연체이자율", "부대비용", "조기상환조건"):
        assert not any(x.startswith(lab) for x in ls), (lab, ls)
    assert all(x.strip() for x in ls), ls
    # ⚠ 그래서 lines() 가 비지 않았다는 사실은 완전성의 증거가 아니다.
    #   완전성 판정은 gaps() 가 한다 - 그것이 실제로 막고 있어야 한다.
    assert disclosure.gaps(prof), "빈 항목이 있는데 gaps 가 비었다"


def test_mandatory_required_accepts_string_form():
    """YAML 에 한 줄 문자열로 적어도 게이트가 열리면 안 된다."""
    assert profiles._norm_keys("reg_no, ad_phone") == ["reg_no", "ad_phone"]
    assert profiles._norm_keys(["reg_no", " reg_no ", ""]) == ["reg_no"]
    assert profiles._norm_keys(None) == []


# ── 5) 등록 유효기간 ─────────────────────────────────────────
def test_registration_expiry_window():
    prof = profiles.load("loan")                    # 유효기간 2024-01-08 ~ 2027-01-08
    assert disclosure.registration_expired(prof, date(2026, 8, 6)) is False
    assert disclosure.registration_expired(prof, date(2027, 1, 8)) is False   # 당일은 유효
    assert disclosure.registration_expired(prof, date(2027, 1, 9)) is True

    # 갱신 창구: 만료 3개월 전 ~ 1개월 전 = 2026-10-10 ~ 2026-12-09
    assert disclosure.renewal_due(prof, date(2026, 8, 6)) is False    # 너무 이르다
    assert disclosure.renewal_due(prof, date(2026, 11, 1)) is True    # 창구 안
    assert disclosure.renewal_due(prof, date(2026, 12, 25)) is False  # 창구 지남
    assert disclosure.renewal_due(prof, date(2027, 2, 1)) is False    # 만료 후는 expired


def test_expired_registration_blocks_publish(temp_db, monkeypatch):
    _no_wait(monkeypatch)
    _fill_loan(monkeypatch)
    monkeypatch.setitem(config.PROFILE["compliance"]["mandatory"],
                        "reg_valid_to", "2025-01-01")     # 이미 만료
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    _, _, cid = _make_band_creative(_loan_caption())

    res = orchestrator.publish_creative(cid, dry_run=False)

    assert res.blocked is True
    assert "유효기간 만료" in (res.error or "")
    assert fake.calls == []


# ── 6) LLM 이 카피를 다시 써도 의무표기가 남는가 ─────────────
def test_llm_rewrite_cannot_strip_mandatory(temp_db, monkeypatch):
    """copy_engine.regenerate() 는 {headline, body, cta} 만 돌려준다.
    승인 콘솔에서 '수정'을 눌러도 의무표기가 사라지면 안 된다."""
    import approval
    import db
    _no_wait(monkeypatch)
    _fill_loan(monkeypatch)
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    _, _, cid = _make_band_creative(_loan_caption())
    aid = db.enqueue_approval(cid)

    # LLM 이 의무표기를 통째로 지우고 자기 문구만 돌려준 상황
    monkeypatch.setattr(approval.copy_engine, "regenerate",
                        lambda cap, note: {"headline": "새 제목",
                                           "body": "새 본문", "cta": "새 CTA"})
    out = approval.decide(aid, "edited", note="더 짧게")
    assert out["ok"] is True

    res = orchestrator.publish_creative(cid, dry_run=False)
    assert res.ok is True
    text = fake.calls[0]["text"]
    assert "새 본문" in text                       # 수정은 반영되고
    # LLM 은 headline/body/cta 만 돌려준다. 의무표기는 이미지 띠에 구워져 있어
    # 애초에 LLM 이 닿을 수 없다 - 그게 이 설계의 요점이다.
    blob = f"{text}\n{_band_blob()}"
    for needle in MUST_HAVE:
        assert needle in blob, f"카피 재생성이 의무표기를 지웠다: {needle}"


def test_mandatory_survives_even_if_caption_key_lost(temp_db, monkeypatch):
    """copy_json 에서 mandatory 키가 통째로 사라져도 발행 시점에 재주입된다.

    ⚠ 여기서는 **이미지 지문까지 함께 잃은** 최악을 본다. 그러면 띠가 있다는
      증거가 없으므로 본문이 다시 의무표기를 실어야 한다(안전망)."""
    _no_wait(monkeypatch)
    _fill_loan(monkeypatch)
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    cap = _loan_caption()
    cap.pop("mandatory")
    _, _, cid = _make_band_creative(cap)

    orchestrator.publish_creative(cid, dry_run=False)

    # 지문은 살아 있으므로(띠가 증명됨) 광고 전체로 판정한다.
    blob = f"{fake.calls[0]['text']}\n{_band_blob()}"
    for needle in MUST_HAVE:
        assert needle in blob, f"mandatory 키 분실 후 광고에서 사라졌다: {needle}"

    # 지문까지 잃으면 본문이 스스로 실어야 한다 - 프로필에서 재주입된다.
    lost = _loan_caption()
    lost.pop("mandatory")
    lost.pop("mandatory_img")
    text = orchestrator._caption_text(lost, "loan")
    for needle in MUST_HAVE:
        assert needle in text, f"증거 없는데 본문에도 없다: {needle}"


# ── 7) cp949 안전성 ─────────────────────────────────────────
def test_new_strings_are_cp949_encodable(monkeypatch):
    """이 프로젝트는 cp949 불가 문자 때문에 백그라운드 job 이 통째로 죽은
    실측 이력이 있다. 콘솔에 찍히는 문구는 전부 인코딩돼야 한다."""
    _fill_loan(monkeypatch)
    samples = [disclosure.build(config.PROFILE)]
    samples += disclosure.lines(config.PROFILE)
    samples += config.loan_compliance_gaps()
    samples += config.compliance_gaps("loan")
    samples.append(orchestrator._profile_gate("loan", "threads") or "")
    # 값이 빈 상태의 차단 사유(운영 중 실제로 찍히는 문자열)
    m = config.PROFILE["compliance"]["mandatory"]
    monkeypatch.setitem(m, "interest_rate", "")
    monkeypatch.setitem(m, "extra_costs", "")
    samples.append(orchestrator._profile_gate("loan", "band") or "")
    monkeypatch.setitem(m, "reg_valid_to", "2020-01-01")
    samples.append(orchestrator._profile_gate("loan", "band") or "")

    for s in samples:
        try:
            s.encode("cp949")
        except UnicodeEncodeError as e:
            pytest.fail(f"cp949 인코딩 불가: {e.object[e.start:e.end]!r} in {s!r}")


# ── 8) 이미지에 의무표기 텍스트층이 실제로 그려지는가 ────────
def _band_pixels(img, band_h):
    """덧붙인 띠 영역의 픽셀만."""
    W, H = img.size
    return list(img.crop((0, H - band_h, W, H)).getdata())


def _ink_row_runs(img, top, bottom, bg=None):
    """[top, bottom) 구간에서 '글자가 있는 픽셀 행'의 연속 덩어리 수.

    한 덩어리 = 한 줄의 글자. 픽셀 총량만 세면 한 줄만 그려도 통과한다
    (실측: 1줄만 그려도 7,464개 - 임계 500의 15배). 줄 수를 세야 '무엇이
    빠졌는지'를 잡을 수 있다.

    ⚠ **색으로 판정하지 않는다.** 예전 판정은 '흰 픽셀 = 글자'였는데,
      2026-08-11 띠 배색이 '진한 바탕 + 흰 글자' → '밝은 바탕 + 진한 글씨'로
      뒤집히자 띠 전체가 글자로 읽혀 13줄이 1줄로 세어졌다. 배경색과
      **얼마나 다른가**로 본다 - 어느 배색에서도 성립한다."""
    W = img.size[0]
    px = img.convert("RGB").load()
    if bg is None:
        # 구간 맨 아래 여백은 글자가 닿지 않는다 - 거기서 배경색을 읽는다.
        bg = px[1, max(top, bottom - 2)]

    def _far(p):
        return sum(abs(int(a) - int(b)) for a, b in zip(p, bg)) > 90

    runs, prev = 0, False
    for y in range(top, bottom):
        cur = any(_far(px[x, y]) for x in range(0, W, 3))
        if cur and not prev:
            runs += 1
        prev = cur
    return runs


def test_flyer_gets_mandatory_band(tmp_path, monkeypatch):
    _fill_loan(monkeypatch)
    lines = disclosure.lines(config.PROFILE)
    assert len(lines) == len(disclosure.required_keys(config.PROFILE)) == 13

    plain = pamphlet.render_from_template(
        "apart", "band", out_path=str(tmp_path / "plain.png"), disclosures=[])
    stamped = pamphlet.render_from_template(
        "apart", "band", out_path=str(tmp_path / "stamped.png"), disclosures=lines)

    from PIL import Image
    a, b = Image.open(plain), Image.open(stamped)
    assert a.size[0] == b.size[0], "폭이 바뀌면 전단 디자인이 왜곡된 것이다"
    band_h = b.size[1] - a.size[1]
    assert band_h > 0, "의무표기 띠가 안 붙었다"

    # 원본 영역은 한 픽셀도 안 바뀌어야 한다(전단 위에 덮어쓰지 않는다)
    assert list(a.getdata()) == list(b.crop((0, 0, a.size[0], a.size[1])).getdata())

    # ★ 띠에 **몇 줄이** 그려졌는가. 흰 픽셀 총량만 보면 한 줄만 그려도
    #   통과한다(= 필수기재 13종 중 1종만 인쇄돼도 초록불).
    H = b.size[1]
    rows = _ink_row_runs(b, H - band_h, H)
    assert rows >= len(lines), f"띠에 {rows}줄만 그려졌다(필요 {len(lines)}줄 이상)"


def test_no_band_for_profiles_without_mandatory(tmp_path):
    """의무표기를 선언하지 않은 업종은 이미지가 1비트도 안 바뀐다."""
    from PIL import Image
    base = pamphlet.render_from_template(
        "apart", "band", out_path=str(tmp_path / "a.png"), disclosures=[])
    same = pamphlet.render_from_template(
        "apart", "band", out_path=str(tmp_path / "b.png"),
        disclosures=config.mandatory_lines("mirizip"))
    assert list(Image.open(base).getdata()) == list(Image.open(same).getdata())


def test_mandatory_font_meets_one_third_of_largest_glyph():
    """[별표1] 1.다 - 필수기재 글자는 그 광고에 표시된 **최대글자의 1/3 이상**.

    기성 전단(1024x1536) 실측: 헤드라인 '아파트/담보대출' 약 122px
    (= 폭의 약 0.119). 필요 최소 = 122/3 = 40.7px.
    ⚠ 예전 값 0.036 은 36.8px 로 **미달**이었다. 시행령 제6조의2(상호와
      같거나 크게)만 보고 이 기준을 놓쳤다. 두 기준은 병존하고 엄격한
      쪽이 구속한다."""
    W = 1024
    measured_max_glyph_px = 122        # 실측(아파트담보대출-260602, 1024폭)
    need = measured_max_glyph_px / 3.0
    got = pamphlet.mandatory_font_px(W)
    assert got >= need, f"의무표기 {got}px < 최대글자/3 = {need:.1f}px"
    # 상수 자체도 전단 실측 비율과 일관되어야 한다
    assert pamphlet.FLYER_MAX_GLYPH_RATIO >= measured_max_glyph_px / W - 0.001
    # 리사이즈되는 배너 규격에서도 비율로 따라가야 한다(원본 폭에 곱하면 안 된다)
    assert pamphlet.mandatory_font_px(1080) > pamphlet.mandatory_font_px(1024)


def test_mandatory_font_is_larger_than_company_name():
    """시행령 제6조의2: 의무표기는 상호 글자와 같거나 크게.

    ⚠ stamp_contact_band 는 상호 30px vs 의무표기 21px 로 이 요건을 위반한다.
      그 비율(0.030 / 0.021)을 여기에 복제하면 처음부터 위반이다."""
    printed_company_ratio = 0.030      # stamp_contact_band 의 상호 비율(f_co)
    assert pamphlet.MANDATORY_FONT_RATIO >= printed_company_ratio

    # 실제로 그려지는 글자 높이도 확인한다(비율만 맞고 렌더가 작으면 소용없다)
    from PIL import Image, ImageDraw
    W = 1024
    font = pamphlet._font_strict(int(W * pamphlet.MANDATORY_FONT_RATIO), bold=True)
    co_font = pamphlet._font(int(W * printed_company_ratio), bold=True)
    d = ImageDraw.Draw(Image.new("RGB", (W, 200)))
    sample = "중개수수료를 요구하거나 받는 것은 불법입니다."
    h_mand = d.textbbox((0, 0), sample, font=font)[3]
    h_co = d.textbbox((0, 0), "(주)더스틴홀딩스대부중개", font=co_font)[3]
    assert h_mand >= h_co, f"의무표기({h_mand}px)가 상호({h_co}px)보다 작다"


def test_mandatory_text_survives_font_glyph_filter():
    """법정 표준문구가 맑은 고딕에서 두부(□)로 깨지지 않는가.
    깨진 글자는 미표기와 같다."""
    font = pamphlet._font_strict(46, bold=True)
    for s in (("※ 대부중개업 등록번호 2026-대구중구-0002",)
              + disclosure.STANDARD_OVERBORROW
              + disclosure.STANDARD_CREDIT
              + disclosure.STANDARD_BROKER_FEE
              + ("부대비용 근저당설정비·인지대 등",
                 "영업소 주소 대구광역시 중구 공평로 105, 노마즈하우스 10층 1014호 (교동)")):
        assert pamphlet._drawable(s, font) == s.strip(), f"글자가 걸러졌다: {s}"
        assert pamphlet._drawable_strict(s, font) == s.strip()


def test_font_failure_raises_instead_of_silent_tofu(monkeypatch):
    """폰트 로드 실패 시 조용히 기본폰트로 떨어지면 한글이 통째로 깨진다.
    법정 문구에서는 조용한 실패가 미표기와 같으므로 터져야 한다."""
    from PIL import ImageFont

    def _boom(*a, **k):
        raise OSError("cannot open resource")

    monkeypatch.setattr(ImageFont, "truetype", _boom)
    with pytest.raises(pamphlet.FontUnavailable):
        pamphlet._font_strict(37, bold=True)
    with pytest.raises(pamphlet.FontUnavailable):
        pamphlet.stamp_mandatory_band(
            __import__("PIL.Image", fromlist=["Image"]).new("RGB", (1024, 100)),
            ["대부중개업 등록번호 2026-대구중구-0002"])


# ── 9) 이미지 경로의 기본 분기(운영이 실제로 타는 길) ────────
# ⚠ 예전 이미지 테스트는 넷 다 disclosures= 를 명시로 넘겨서, 운영이 타는
#   `disclosures is None` 분기가 **한 번도 실행되지 않았다**. 그 줄을
#   `[] if disclosures is None else ...` 로 망가뜨려도 스위트가 전부 초록이었다.
def test_default_branch_stamps_band_for_loan(tmp_path, monkeypatch):
    _fill_loan(monkeypatch)
    from PIL import Image
    plain = pamphlet.render_from_template(
        "apart", "band", out_path=str(tmp_path / "p.png"), disclosures=[])
    auto = pamphlet.render_from_template(          # disclosures 를 주지 않는다
        "apart", "band", out_path=str(tmp_path / "auto.png"))
    a, b = Image.open(plain), Image.open(auto)
    assert b.size[1] > a.size[1], "기본 분기에서 의무표기 층이 안 붙었다"
    # 머리글(상호·등록번호)이 **위**에도 붙는다([별표1] 1.가 왼쪽상단)
    head = disclosure.header_lines(config.PROFILE)
    assert len(head) == 2
    assert _ink_row_runs(b, 0, (b.size[1] - a.size[1]) // 2) >= 1


def test_default_branch_does_not_stamp_other_profiles(tmp_path, monkeypatch):
    """활성 업종이 대출이 아니면 기본 분기에서도 이미지가 안 바뀐다."""
    from PIL import Image
    # ⚠ PROFILE 도 같이 갈아야 한다. config._profile_for() 는 key == PROFILE_KEY
    #   이면 디스크를 다시 읽지 않고 이미 로드된 PROFILE 을 그대로 준다.
    monkeypatch.setattr(config, "PROFILE", profiles.load("mirizip"))
    monkeypatch.setattr(config, "PROFILE_KEY", "mirizip")
    plain = pamphlet.render_from_template(
        "apart", "band", out_path=str(tmp_path / "p2.png"), disclosures=[])
    auto = pamphlet.render_from_template(
        "apart", "band", out_path=str(tmp_path / "a2.png"))
    assert list(Image.open(plain).getdata()) == list(Image.open(auto).getdata())


def test_default_branch_refuses_incomplete_profile(tmp_path, monkeypatch):
    """항목이 비면 소재를 굽지 않는다.

    구워버리면 '항목이 빠진 띠'가 이미지에 영구히 박히고, 나중에 값을
    채워 게이트가 열려도 그 이미지는 옛날 그대로 나간다."""
    _empty_loan(monkeypatch)
    with pytest.raises(pamphlet.MandatoryIncomplete):
        pamphlet.render_from_template(
            "apart", "band", out_path=str(tmp_path / "x.png"))


def test_run_campaign_creates_nothing_while_incomplete(temp_db, monkeypatch):
    import db
    _empty_loan(monkeypatch)
    # ⚠ enabled=True 를 빼면 list_channels(enabled_only=True) 가 빈 목록을
    #   돌려줘 이 테스트가 아무것도 검증하지 않는다(실제로 그랬다 - 사전
    #   게이트를 제거해도 통과했다).
    ch = db.add_channel("band", "https://band.us/band/55554444",
                        name="대구 소상공인방", enabled=True, audience="mixed")
    chans = [c for c in db.list_channels(enabled_only=True) if c["id"] == ch]
    assert chans, "채널이 안 잡히면 이 테스트는 아무것도 검증하지 못한다"
    res = orchestrator.run_campaign(
        {"title": "t", "goal": "g", "product": ""},
        copy_fn=lambda p: '{"headline":"h","body":"b","cta":"c"}',
        channels=chans)
    assert res["creatives"] == []


# ── 10) 이미지 지문 게이트 ───────────────────────────────────
def test_stale_image_is_blocked_even_after_profile_filled(temp_db, monkeypatch):
    """이자율이 비었을 때 만든 소재(그 줄이 빠진 띠)를, 나중에 값만 채워
    발행하면 프로필 게이트는 통과하고 이미지에는 그 항목이 없다."""
    _no_wait(monkeypatch)
    stale = config.mandatory_fingerprint("loan")     # 미완성 상태의 지문
    _fill_loan(monkeypatch)                          # 이제 채운다
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    cap = _loan_caption()
    cap["mandatory_img"] = stale
    _, _, cid = _make_band_creative(cap)

    res = orchestrator.publish_creative(cid, dry_run=False)
    assert res.blocked is True
    assert "이미지" in (res.error or "")
    assert fake.calls == []


def test_legacy_creative_without_fingerprint_is_blocked(temp_db, monkeypatch):
    """지문이 없는 옛 소재(DB에 남아 있다)도 막힌다 - fail-closed."""
    _no_wait(monkeypatch)
    _fill_loan(monkeypatch)
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    cap = _loan_caption()
    cap.pop("mandatory_img")
    _, _, cid = _make_band_creative(cap)

    res = orchestrator.publish_creative(cid, dry_run=False)
    assert res.blocked is True and fake.calls == []


def test_fingerprint_is_empty_for_profiles_without_mandatory():
    """선언 안 한 업종은 지문 검사 자체가 없어야 한다(무회귀)."""
    for key in ("mirizip", "inkcraft", "adstudio"):
        assert config.mandatory_fingerprint(key) == ""


# ── 11) 승인 콘솔이 LLM 출력에 게이트 선택자를 내주지 않는가 ──
def test_edit_cannot_inject_profile_key(temp_db, monkeypatch):
    """'수정' 버튼 한 번으로 업종 표식이 바뀌면 게이트가 통째로 무력화된다.

    regenerate() 는 프롬프트에 원본 카피를 실어 보낸다. 모델이 입력 구조를
    그대로 되돌려주는 것은 흔한 실패이고, merge 가 화이트리스트가 아니면
    그 값이 그대로 DB 에 저장된다."""
    import approval
    import db
    _fill_loan(monkeypatch)
    _, _, cid = _make_band_creative(_loan_caption())
    aid = db.enqueue_approval(cid)

    monkeypatch.setattr(approval.copy_engine, "regenerate",
                        lambda cap, note: {"headline": "H2", "body": "B2",
                                           "cta": "C2",
                                           "profile_key": "loan_v2",
                                           "mandatory": "가짜 문구",
                                           "disclaimer": "",
                                           "mandatory_img": "deadbeef"})
    approval.decide(aid, "edited", note="짧게")

    saved = approval._caption_of(cid)
    assert saved["headline"] == "H2"                 # 수정은 반영되고
    assert saved["profile_key"] == "loan"            # 게이트 선택자는 불변
    assert saved["mandatory"] != "가짜 문구"
    assert saved["disclaimer"] == config.DISCLAIMER
    assert saved["mandatory_img"] == config.mandatory_fingerprint("loan")


def test_regenerate_prompt_does_not_leak_profile_key():
    from content import copy_engine
    seen = {}

    def _spy(prompt):
        seen["p"] = prompt
        return '{"headline":"h","body":"b","cta":"c"}'

    copy_engine.regenerate({"headline": "h", "body": "b", "cta": "c",
                            "profile_key": "loan",
                            "mandatory": "법정 문구"}, "짧게", _llm=_spy)
    assert "profile_key" not in seen["p"]
    assert "법정 문구" not in seen["p"]


# ── 12) 프로필이 없을 때 fail-open 이 아닌가 ─────────────────
def test_missing_regulated_profile_fails_closed(monkeypatch):
    """profiles/loan.yaml 이 사라지면(배포 누락·이름 변경) 대출광고가
    아무 검사 없이 나가면 안 된다. 깨진 yaml 은 막히는데 없는 yaml 은
    통과하던 비대칭이 사고의 형태였다."""
    monkeypatch.setattr(config, "_PROFILE_CACHE", {})
    monkeypatch.setattr(config, "_ALLOW_CACHE", {})
    monkeypatch.setattr(config, "PROFILE_KEY", "somethingelse")
    monkeypatch.setattr(profiles, "DIR", profiles.DIR / "_nonexistent")
    assert config.platform_allowed("loan", "band") is False
    assert config.compliance_missing("loan")
    assert orchestrator._profile_gate("loan", "band")
    # 규제 대상이 아닌 업종은 종전대로 통과(레거시 소재를 죽이지 않는다)
    assert config.platform_allowed("nosuch_profile", "band") is True
    assert config.compliance_missing("nosuch_profile") == []


# ── 13) 표식을 잃은 대출 소재의 마지막 안전망 ────────────────
def test_loan_creative_without_profile_key_is_still_caught(temp_db, monkeypatch):
    """_LOAN_TOKENS 는 profile_key 를 잃은 대출 소재를 잡는 마지막 방어선인데
    이걸 지키는 테스트가 없었다(빈 튜플로 만들어도 스위트가 전부 초록).

    프로필을 비워 두는 이유: 완성된 프로필에서는 loan x band 가 정상 통과라
    차단이 안 일어나고, 그러면 '토큰으로 loan 이라고 알아봤는지'를 발행
    결과로 확인할 수 없다. 비워 두면 차단 자체가 게이트가 돌았다는 증거다."""
    _no_wait(monkeypatch)
    _empty_loan(monkeypatch)
    fake = _RecordingAdapter()
    monkeypatch.setattr(orchestrator, "get_adapter", lambda *a, **k: fake)
    cap = _loan_caption()
    cap.pop("profile_key")
    assert orchestrator._creative_profile(None, cap) == "loan"
    _, _, cid = _make_band_creative(cap)

    res = orchestrator.publish_creative(cid, dry_run=False)
    assert res.blocked is True and fake.calls == []


def test_loan_tokens_do_not_catch_other_industries():
    """토큰이 흔한 단어면 인테리어 광고가 대출로 오판돼 막힌다."""
    cap = {"headline": "인테리어 시안", "body": "사진 한 장으로 미리 봅니다.",
           "cta": "무료로 해보기"}
    assert orchestrator._creative_profile(None, cap) is None


# ── 14) _mandatory_for 폴백 방향 ─────────────────────────────
def test_resolved_profile_wins_over_stored_mandatory():
    """업종이 확정됐으면 그 업종의 값을 빈 문자열이라도 그대로 믿는다.

    빈 문자열일 때 저장된 값으로 폴백하면, mirizip 소재에 남아 있는 대출
    문구가 인테리어 광고에 그대로 붙는다(폴백 방향이 거꾸로였다)."""
    cap = {"profile_key": "mirizip",
           "mandatory": "[대부중개업 법정 필수 표기]\n등록번호"}
    assert orchestrator._mandatory_for(cap) == ""
    assert orchestrator._mandatory_for(cap, "mirizip") == ""
    # 업종을 모를 때만 저장된 값을 쓴다(레거시 소재)
    assert orchestrator._mandatory_for({"mandatory": "X"}) == "X"


# ── 15) 승인 화면이 법정 문구와 차단 사유를 보여주는가 ───────
def test_approval_preview_shows_mandatory_and_block_reason(temp_db, monkeypatch):
    import approval
    import db
    _fill_loan(monkeypatch)
    _, _, cid = _make_band_creative(_loan_caption())
    db.enqueue_approval(cid)

    row = [p for p in approval.pending() if p["creative_id"] == cid][0]
    assert "중개수수료를 요구하거나 받는 것은 불법입니다." in row["mandatory"]
    assert row["disclaimer"] == config.DISCLAIMER
    assert row["block_reason"] == ""      # 완비 상태에서는 막히지 않는다
    assert "중개수수료" in approval._caption_text(row["caption"])


def test_approval_preview_reports_why_blocked(temp_db, monkeypatch):
    """막힌 이유를 화면에서 못 보면 운영자가 헛짚는다."""
    import approval
    import db
    _empty_loan(monkeypatch)
    _, _, cid = _make_band_creative(_loan_caption())   # 미완성 상태
    db.enqueue_approval(cid)
    row = [p for p in approval.pending() if p["creative_id"] == cid][0]
    assert "필수기재" in row["block_reason"]


def test_approval_preview_empty_for_other_profiles(temp_db):
    import approval
    import db
    _, _, cid = _make_band_creative({
        "headline": "인테리어", "body": "b", "cta": "c",
        "profile_key": "mirizip", "disclaimer": "", "mandatory": ""})
    db.enqueue_approval(cid)
    row = [p for p in approval.pending() if p["creative_id"] == cid][0]
    assert row["mandatory"] == ""
    assert row["block_reason"] == ""


def test_approval_preview_uses_channel_profile_key(temp_db, monkeypatch):
    """채널 표식으로만 loan 인 소재도 승인 화면에서 같은 판정을 받아야 한다."""
    import approval
    import db
    _fill_loan(monkeypatch)
    ch = db.add_channel("band", "https://band.us/band/11112222", name="경북 사장님방")
    with db.get_conn() as conn:
        conn.execute("UPDATE channels SET profile_key=? WHERE id=?", ("loan", ch))
    camp = db.add_campaign("c")
    cap = _loan_caption()
    cap.pop("profile_key")
    cap.pop("mandatory")
    cid = db.add_creative(camp, ch, cap, None)
    db.enqueue_approval(cid)

    row = [p for p in approval.pending() if p["creative_id"] == cid][0]
    assert "중개수수료를 요구하거나 받는 것은 불법입니다." in row["mandatory"]


# ── 16) 글자 유실은 조용히 넘어가지 않는가 ───────────────────
def test_undrawable_char_in_mandatory_raises(monkeypatch):
    """운영자가 이자율에 전각 물결(U+FF5E)이나 이모지를 쓰면 그 글자만
    사라져 '연 5.9%20.0%' 처럼 의미가 바뀐 이자율이 인쇄된다.
    법정 문구에서 조용한 삭제는 두부와 같은 실패 등급이다."""
    from PIL import Image
    font = pamphlet._font_strict(46, bold=True)
    monkeypatch.setattr(pamphlet, "_drawable",
                        lambda t, f=None: str(t or "").replace("~", "").strip())
    with pytest.raises(pamphlet.GlyphUnavailable):
        pamphlet._drawable_strict("연 5.9% ~ 연 20.0%", font)
    with pytest.raises(pamphlet.GlyphUnavailable):
        pamphlet.stamp_mandatory_band(Image.new("RGB", (1024, 200)),
                                      ["대부이자율 연 5.9% ~ 연 20.0%"])


# ── 17) 타일 배너 시트는 대출 소재로 쓰지 않는다 ─────────────
def test_banner_sheets_are_not_picked_for_loan(temp_db):
    """시트 한 장에 완결된 광고 8개가 타일로 붙어 있다. 시트 하단에 띠를
    하나 붙여도 개별 타일은 필수기재를 갖추지 못한다."""
    assert config.PROFILE_KEY == "loan"
    picked = {orchestrator.pick_product({"id": i, "audience": "mixed"}, {})
              for i in range(1, 40)}
    picked.discard(None)
    assert picked, "전단이 하나도 안 골라졌다"
    assert not (picked & {"banner_sheet_01", "banner_sheet_02"}), picked


def test_banner_sheets_still_available_for_other_profiles(temp_db, monkeypatch):
    """무회귀 - 규제 업종이 아니면 배너 시트가 계속 후보에 남는다."""
    from content import registry
    monkeypatch.setattr(config, "PROFILE_KEY", "mirizip")
    cands = [p for p in registry.by_audience("mixed")
             if p.get("flyer") and not orchestrator._tiled_sheet_blocked(p)]
    assert any(p["key"].startswith("banner_sheet") for p in cands)


# ── 18) 쓰레드 자동발행에도 게이트가 붙었는가 ────────────────
def test_threads_auto_publish_is_gated():
    """자동발행 경로는 publish_creative() 를 안 거친다. 예전엔 점수가 낮은
    답글만 승인 큐에서 차단되고, **점수가 높은 답글은 무검사로 즉시** 나갔다
    (안전 성질이 뒤집혀 있었다)."""
    import inspect
    from threads import runner
    assert orchestrator._profile_gate("loan", "threads")
    src = inspect.getsource(runner.run_once)
    assert "_profile_gate" in src, "쓰레드 자동발행 경로에 업종 게이트가 없다"


# ── 19) 랜딩페이지(파이프라인 밖)에도 필수기재가 있는가 ──────
def test_landing_page_gap_checker_detects_missing_items(tmp_path, monkeypatch):
    """모든 loan 캡션의 CTA 가 정적 랜딩페이지로 보낸다. 그것도 대부중개업
    광고물인데 AutoAd 의 어떤 게이트도 그 경로를 보지 않는다 - 배포 전
    점검으로 못 박는 것이 유일한 방법이다."""
    import preflight
    _fill_loan(monkeypatch)
    empty = tmp_path / "empty.html"
    empty.write_text("<html><body>상담 접수</body></html>", encoding="utf-8")
    gaps = preflight.landing_mandatory_gaps("loan", path=empty)
    assert any("2026-대구중구-0002" in g for g in gaps)
    assert any("중개수수료" in g for g in gaps)

    full = tmp_path / "full.html"
    full.write_text("<html><body>"
                    + "".join(f"<p>{ln}</p>" for ln in
                              disclosure.lines(config.PROFILE))
                    + "</body></html>", encoding="utf-8")
    assert preflight.landing_mandatory_gaps("loan", path=full) == []


def test_landing_check_is_inert_for_other_profiles(tmp_path):
    import preflight
    empty = tmp_path / "e.html"
    empty.write_text("<html></html>", encoding="utf-8")
    assert preflight.landing_mandatory_gaps("mirizip", path=empty) == []


def test_real_landing_page_is_reported_as_incomplete():
    """현재 배포본에는 등록번호·경고문구 등이 없다. 그 사실이 드러나야 한다.
    (여기가 통과하기 시작하면 페이지가 보완된 것이다 - 그때 이 테스트를
     'gaps == []' 로 뒤집을 것.)"""
    import preflight
    gaps = preflight.landing_mandatory_gaps("loan")
    assert any("등록번호" in g for g in gaps), gaps
