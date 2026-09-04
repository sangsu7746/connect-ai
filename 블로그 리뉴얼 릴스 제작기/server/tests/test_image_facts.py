import httpx
import pytest
from core import image_facts

POST = {"title": "전세보증보험 총정리", "url": "https://blog.naver.com/a/1",
        "image_urls": ["https://x.net/a.jpg", "https://x.net/b.jpg"]}

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200


def _setup(monkeypatch, gen_out='["보증료는 연 0.128%다.", "한도는 7억원이다."]'):
    monkeypatch.setattr(image_facts.gemini, "available", lambda: True)
    monkeypatch.setattr(image_facts.gemini, "generate_vision",
                        lambda prompt, images, **kw: gen_out)
    monkeypatch.setattr(image_facts, "_download", lambda url: PNG)


def test_extract_returns_fact_sheet_rows(monkeypatch):
    _setup(monkeypatch)
    facts = image_facts.extract_facts(POST)
    assert len(facts) == 2
    assert facts[0]["fact"] == "보증료는 연 0.128%다."
    assert facts[0]["source_url"] == POST["url"]
    assert facts[0]["from_image"] is True


def test_extract_drops_factless_lines(monkeypatch):
    # 숫자 없는 문장은 팩트로 쓰지 않는다 — 날조 게이트의 근거가 못 된다
    _setup(monkeypatch, '["보증보험은 유용합니다.", "보증료는 연 0.128%다."]')
    facts = image_facts.extract_facts(POST)
    assert [f["fact"] for f in facts] == ["보증료는 연 0.128%다."]


def test_extract_empty_when_no_images(monkeypatch):
    # 이미지가 없으면 사실도 없다 — 실패가 아니므로 캐시에 굳혀도 된다
    _setup(monkeypatch)
    assert image_facts.extract_facts({**POST, "image_urls": []}) == []


def test_extract_returns_empty_list_when_model_finds_nothing(monkeypatch):
    # 판독은 성공했으나 쓸 사실이 없는 경우 — None 이 아니라 [] 여야 캐시된다
    _setup(monkeypatch, "[]")
    assert image_facts.extract_facts(POST) == []


# 아래 넷은 "판독 실패"라 None 이어야 한다. [] 로 돌려주면 호출부가 빈 결과를
# 캐시에 굳혀 그 글의 이미지 사실을 영구히 잃는다(2026-08-17 실제 발생).
def test_extract_survives_download_failure(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(image_facts, "_download",
                        lambda url: (_ for _ in ()).throw(OSError("down")))
    assert image_facts.extract_facts(POST) is None


def test_extract_survives_gemini_failure(monkeypatch):
    _setup(monkeypatch)
    def boom(prompt, images, **kw):
        raise RuntimeError("gemini down")
    monkeypatch.setattr(image_facts.gemini, "generate_vision", boom)
    assert image_facts.extract_facts(POST) is None


def test_extract_skips_when_gemini_unavailable(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(image_facts.gemini, "available", lambda: False)
    assert image_facts.extract_facts(POST) is None


def test_extract_handles_non_list_response(monkeypatch):
    _setup(monkeypatch, '{"facts": "wrong shape"}')
    assert image_facts.extract_facts(POST) is None


@pytest.mark.parametrize("text", [
    # 블로거가 자기 계약서를 찍어 올린 경우 (실측 #9)
    "부동산 계약서에 적힌 매매대금은 금 500,000,000원이다.",
    "부동산 계약서에 적힌 계약금은 금 50,000,000원이다.",
    "부동산 계약서에 적힌 계약 날짜는 2024년 05월 20일이다.",
    # 자기 대출 명세서를 찍어 올린 경우 (실측 #10) — 절대 날짜 + 개인 일정 맥락
    "KB 청년전용 버팀목 전세자금대출의 대출 만기일은 2026년 6월 21일이다.",
    "기한연장을 위한 서류 제출 완료 기한은 2026년 5월 27일까지이다.",
    "대출 심사 완료 후 약정 기한은 2026년 6월 2일까지이다.",
])
def test_is_personal_blocks_private_documents(text):
    assert image_facts.is_personal(text) is True


@pytest.mark.parametrize("text", [
    # 같은 대출 서류에서 나왔어도 이건 누구에게나 적용되는 은행 규칙이다
    "대출금 기한연장은 만기일 1개월 이전부터 가능하다.",
    "은행 지점 방문을 통한 대출금 기한연장 신청은 만기일 5일 전까지 해야 한다.",
    "행정기관에서 발급받은 제출 서류는 최근 1개월 이내 발급분이어야 한다.",
    # 일반 기준·요율·한도
    "HUG 주택도시보증공사의 수도권 보증 한도는 7억 원이다.",
    "SGI 서울보증의 보증료율은 연 0.192%에서 0.218%이다.",
    "임대차신고는 계약 후 30일 이내에 해야 한다.",
    "대법원 인터넷등기소에서 등기부등본을 발급받는 수수료는 1,000원이다.",
    # 절대 날짜라도 개인 일정 맥락이 없으면 살린다 (법 시행일 등)
    "개정된 전세보증보험 기준은 2026년 1월 1일부터 시행된다.",
    # 실측 오탐 2건 — 둘 다 누구에게나 적용되는 일반 규칙이다.
    # 첫 문장은 "계약서"·절대 날짜·"계약"을 모두 담고도 제도의 경계선("이후")이라 살아야 한다.
    "전세보증보험 가입을 위한 계약서의 기준일은 2020년 4월 1일 이후여야 한다.",
    "대출계좌 확인은 만기일로부터 1개월 이내에 인터넷뱅킹에서 가능하다.",
    # 일반 관행으로서의 계약금 비율 — 남의 계약서 금액이 아니다
    "계약금은 통상 매매가의 10%로 정한다.",
])
def test_is_personal_keeps_general_rules(text):
    assert image_facts.is_personal(text) is False


def test_extract_drops_personal_facts(monkeypatch):
    """일반 규칙은 남기고 개인 서류의 숫자만 빠져야 한다."""
    _setup(monkeypatch, '["대출금 기한연장은 만기일 1개월 이전부터 가능하다.",'
                        ' "대출 만기일은 2026년 6월 21일이다.",'
                        ' "매매대금은 금 500,000,000원이다."]')
    facts = image_facts.extract_facts(POST)
    assert [f["fact"] for f in facts] == ["대출금 기한연장은 만기일 1개월 이전부터 가능하다."]


def test_prompt_tells_model_to_skip_private_documents():
    # 사후 필터만 믿지 않는다 — 모델에게도 먼저 걸러 달라고 지시한다
    assert "계약서" in image_facts._PROMPT and "건너뛴다" in image_facts._PROMPT


def test_download_resizes_large_image(monkeypatch):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2000, 3000), (120, 60, 200)).save(buf, format="PNG")
    big = buf.getvalue()
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None,
                        follow_redirects=None: httpx.Response(
                            200, content=big, request=httpx.Request("GET", url)))
    out = image_facts._download("https://x.net/big.png")
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"
    w, h = im.size
    assert max(w, h) <= image_facts.MAX_EDGE
    assert len(out) < len(big)
