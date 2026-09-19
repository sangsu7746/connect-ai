# -*- coding: utf-8 -*-
"""보랏빛 소 공용 조각(_purplecow.txt) · 규제 레일 · 새 검사기

왜 이 파일이 필요한가:
  _purplecow.txt 는 14업종 x 4프롬프트 **전부**에 붙는 단 하나의 조각이다
  (content/copy_engine.generate_copy). 여기가 흔들리면 모든 업종의 카피가
  같이 흔들리는데, 지금까지 이 조각을 다루는 테스트가 하나도 없었다.

  그리고 이 조각은 "평범하면 실패다 / 멈칫하게 만들어라"라고 시키는 조각이다.
  그 지시는 규제 업종에서 곧장 위법으로 간다 — 2026-08-10 에 실제로 그랬다.
  운영자가 확보한 광고 이미지 중 아래가 위법 판정돼 제외됐다:
      "★5 고객 후기 4건", "40대 직장인 김OO님"      (허위 후기)
      "신용평점 나빠도 상관無", "연체자 도 가능함"   (확정·과장)
      "조회기록 無 & 대출기록 無"
  당시 가드는 이 중 셋을 못 잡았다. 그래서 여기서 **실제 사고 문장**을
  회귀 케이스로 박아 둔다.

⚠ LLM 을 실제로 부르지 않는다. generate_copy(_llm=...) 주입으로만 검증한다.
⚠ sys.stdout 을 새 TextIOWrapper 로 갈아끼우지 마라 — pytest 세션이 통째로
  죽는다(수집 0건). reconfigure 만 쓸 것.
"""
import os
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import config
from content import copy_engine as CE


PROMPTS = ROOT / "content" / "prompts"


# ── 조립 도우미 ─────────────────────────────────────────────
def _campaign(form="ad"):
    """모든 채널 프롬프트의 자리표시자를 채우는 최소 캠페인."""
    return {
        "id": 1,
        "track_key": "c1-ch1",
        "title": "테스트 캠페인",
        "product": "테스트 상품",
        "goal": "상담 접수",
        "styles": "기본",
        "form": form,
        "brand_site": "example-brand.kr",
        "form_url": "https://example-brand.kr/apply",
        "disclosures": "",
    }


def _profile(platform="band"):
    return {"platform": platform, "tone": "담백하게",
            "audience": "일반 소비자", "topic": "생활정보"}


# 모든 검사를 통과하는 안전한 응답. 콘텐츠형은 도구 표기(brand_site)가 필수다.
_OK_JSON = ('{"headline": "접수하면 순서대로 안내드립니다",'
            ' "body": "무엇을 준비해야 하는지부터 알려드립니다.'
            ' 도구는 example-brand.kr 입니다.",'
            ' "cta": "어떤 쪽이 더 궁금하신가요?"}')

# 같은 응답에 관점(angle)만 붙인 것. 스키마 맨 앞에 온다.
_OK_JSON_ANGLE = ('{"angle": "절차를 먼저 펼쳐 보인다",'
                  ' "headline": "접수하면 순서대로 안내드립니다",'
                  ' "body": "무엇을 준비해야 하는지부터 알려드립니다.'
                  ' 도구는 example-brand.kr 입니다.",'
                  ' "cta": "어떤 쪽이 더 궁금하신가요?"}')


def _assemble(platform="band", form="ad"):
    """generate_copy 가 LLM 에게 실제로 보내는 프롬프트를 돌려준다."""
    seen = {}

    def fake_llm(prompt):
        seen.setdefault("prompt", prompt)
        return _OK_JSON

    CE.generate_copy(_campaign(form), _profile(platform), _llm=fake_llm)
    return seen["prompt"]


# ── 1. 자리표시자 ────────────────────────────────────────────
# _load_shared 는 _fill 을 거치지 않는다. 조각 안에 {key} 를 쓰면 조용히
# 프롬프트로 들어가고, LLM 이 그걸 베끼면 _find_leaks 가 '치환되지 않은
# 자리표시자'로 잡아 매 생성이 재시도 초과 → 폴백이 된다.
@pytest.mark.parametrize("name", ["_purplecow.txt", "_permission.txt",
                                  "_compliance_rail.txt"])
def test_shared_fragment_has_no_placeholder(name):
    text = (PROMPTS / name).read_text(encoding="utf-8")
    hit = CE._PLACEHOLDER_RE.search(text)
    assert hit is None, f"{name} 에 자리표시자가 있다: {hit.group(0) if hit else ''}"


# ── 2. 모든 채널·형태에 실제로 붙는가 ────────────────────────
_MARK = "보랏빛 소 자가 진단"


@pytest.mark.parametrize("platform", ["band", "facebook", "kakao"])
@pytest.mark.parametrize("form", ["ad", "content"])
def test_purplecow_reaches_every_channel_and_form(platform, form):
    prompt = _assemble(platform, form)
    assert _MARK in prompt
    # 4문항이 전부 살아 있는가 (기존 자산을 지우지 않았는지)
    for q in ("1초 안에 차별성", '"이게 뭐야?"', "퍼뜨릴 사람이 자랑할",
              "값을 깎지 않아도"):
        assert q in prompt, f"{platform}/{form}: 자가 진단 '{q}' 가 사라졌다"


# ── 3. 레일이 프롬프트에 실려 나가는가 ───────────────────────
# 전 업종 공통 레일(표시광고법 — 후기·순위·구체성). 업종을 가리지 않는다.
_UNIVERSAL_RAIL = [
    "지어내지 마라 — 마지막 관문",
    "지어낸 사람·후기·평점은 절대 금지",
    "순위·서열 주장 금지",
    "검증 가능한 구체성",
]

# 규제 업종 전용 레일(대부업법·금소법 — 심사·승인·처지·조건).
# ⚠ 이걸 전 업종에 붙이면 심사가 존재하지도 않는 업종에 "심사를 뒤집지 마라",
#   "가능합니다 를 쓰지 마라"라고 말하게 된다. mirizip 의 "주말에도 상담
#   가능합니다" 는 완전히 적법한데 프롬프트가 그걸 금지하고 있었다.
_REGULATED_RAIL = [
    "규제 업종 — 여기서는 멈춰라",
    "심사·승인·결과를 단정하지 마라",
    "심사·서류·확인 절차를 없다고 하거나 뒤로 미루지 마라",
    "사람의 처지를 대상으로 부르지 마라",
]


@pytest.mark.parametrize("line", _UNIVERSAL_RAIL)
def test_universal_rail_is_in_prompt(line):
    assert line in _assemble("band", "ad")


@pytest.mark.parametrize("line", _REGULATED_RAIL)
def test_regulated_rail_is_in_prompt_for_loan(line):
    """기본 프로필(loan)은 규제 업종이므로 이 레일이 붙어야 한다."""
    if not CE._is_regulated():
        pytest.skip("이 프로세스의 업종은 규제 업종이 아니다")
    assert line in _assemble("band", "ad")


def test_convention_lever_has_a_fence():
    """관행을 건드리라는 지시는 반드시 울타리와 함께 나가야 한다.

    울타리 없이 "다들 하는 방식을 뒤집어라"만 있으면 "다들 심사한다니
    우리는 심사 없다고 하자"로 간다. 실행 지침 6번이 규제 업종에서 가장
    위험한 이유다. 그래서 지시 자체를 **한 방향**으로만 남겼다 —
    관행을 부정하지 말고 설명하라."""
    p = _assemble("band", "ad")
    assert "관행은 부정하지 말고 설명해라" in p
    # 바꿔도 되는 것 / 바꾸면 안 되는 것이 함께 적혀 있어야 한다.
    for keep in ("말투", "조건", "심사", "자격", "법정 표기"):
        assert keep in p, f"울타리에서 '{keep}' 가 빠졌다"
    # 반대 방향(결과 예단)은 X 예시로 명시돼 있어야 한다.
    assert "다들 안 된다지만 우리는 됩니다" in p


def test_prompt_forbids_unfair_comparison():
    """부당비교 금지는 코드 가드와 프롬프트 양쪽에 있어야 한다."""
    assert "다른 업체를 끌어와 비교하지 마라" in _assemble("band", "ad")


def test_rail_comes_after_creative_instructions():
    """순서가 곧 강도다. 창의성 지시 뒤에 레일이 와야 한다.

    2026-08-10 사고의 구조적 원인: 각도 블록("직접 써 본 사람의 후기처럼")이
    규제 경고보다 **뒤에** 붙어 있었다. 지시가 충돌하면 뒤엣것이 이긴다."""
    p = _assemble("band", "ad")
    assert p.index("[이번 글의 각도]") < p.index("[지어내지 마라")


def test_prompt_is_not_bloated():
    """프롬프트는 길수록 나빠진다.

    공용 조각이 채널 프롬프트보다 커지면 밴드 글과 카톡 글을 다르게 만드는
    지시가 자기 프롬프트 안에서 소수의견이 된다(실측: 개편 직후
    _purplecow 2,329자 vs kakao_ad 899자 = 2.6배)."""
    pc = len((PROMPTS / "_purplecow.txt").read_text(encoding="utf-8"))
    ka = len((PROMPTS / "kakao_ad.txt").read_text(encoding="utf-8"))
    assert pc < ka * 2, f"공용 조각이 너무 크다: _purplecow {pc}자 vs kakao {ka}자"


@pytest.mark.parametrize("phrase", ["진짜 구체성", "예/아니오로 끝나지 않게",
                                    "모두에게 말하면 아무도 안 듣는다"])
def test_shared_lines_are_not_duplicated_in_channel_prompts(phrase):
    """같은 문장을 공용 조각과 채널 프롬프트 양쪽에 두면 모든 조립
    프롬프트가 그 문장을 두 번 담는다. 길어질 뿐 강해지지 않는다."""
    dup = [f.name for f in sorted(PROMPTS.glob("*_ad.txt")) +
           sorted(PROMPTS.glob("*_content.txt"))
           if phrase in f.read_text(encoding="utf-8")]
    assert not dup, f"'{phrase}' 가 채널 프롬프트에 남아 있다: {dup}"


# ── 4. 허락자산 조각은 콘텐츠형 전용 ─────────────────────────
def test_permission_fragment_only_on_content_prompt():
    """광고형 CTA 에는 접수 링크가 고정으로 들어간다. 거기에
    "질문으로 끝내라"를 얹으면 지시가 충돌한다."""
    assert "[다음 접점" in _assemble("facebook", "content")
    assert "[다음 접점" not in _assemble("facebook", "ad")
    # band/kakao 는 콘텐츠형 프롬프트가 없어 광고형으로 대체된다.
    # form 만 보고 붙이면 여기서 광고형에 붙는다.
    assert "[다음 접점" not in _assemble("band", "content")
    assert "[다음 접점" not in _assemble("kakao", "content")


# ── 5. 초소형 시장(지침2)이 공용으로 승격됐는가 ──────────────
@pytest.mark.parametrize("platform", ["band", "facebook", "kakao"])
def test_smallest_market_lever_is_shared(platform):
    """예전에는 facebook_ad.txt 에만 있었다 — band/kakao 는 못 받았다."""
    p = _assemble(platform, "ad")
    assert "한 사람" in p
    # 좁히기의 울타리. 이게 없으면 loan 에서 '연체자에게' 로 좁힌다.
    assert "처지로 좁히지 마라" in p


def test_smallest_market_lever_does_not_own_the_first_line():
    """첫 줄을 어디서 시작할지는 채널 프롬프트와 각도가 이미 소유하고 있다.

    공용 조각까지 "상황 하나에서 글을 시작해라"라고 하면 한 프롬프트 안에
    첫 줄 규정이 셋이 되고 서로 만족시킬 수 없다(실측: band_ad '구체적인
    하나를 던져라' / 공용 조각 '상황 하나에서 시작' / 각도 '질문에 답하는 식')."""
    pc = (PROMPTS / "_purplecow.txt").read_text(encoding="utf-8")
    assert "에서 글을 시작해라" not in pc


# ── 6. 지어낸 후기·평점·인물 (2026-08-10 실제 사고) ──────────
# (설명, 문구) — 반드시 차단
TESTIMONIAL_BLOCK = [
    ("실제 사고: 별점+후기건수", "★5 고객 후기 4건"),
    ("실제 사고: 별 다섯 개", "★★★★★ 상담이 정말 빨랐어요"),
    ("실제 사고: 지어낸 인물", "40대 직장인 김OO님 정말 만족합니다"),
    ("이름 가림 표기", "박○○님이 남기신 이야기입니다"),
    ("이름 가림 - 삼각형", "김△△님이 남긴 말입니다"),
    ("이름 가림 - 전각 O", "김Ｏ Ｏ님이 남긴 말입니다"),
    ("성씨 가림", "김O씨의 사례입니다"),
    ("익명 예시 이름", "홍길동님의 후기입니다"),
    ("고객 후기 라벨", "고객 후기를 모아봤습니다"),
    ("실제 후기 라벨", "실제 후기입니다"),
    ("평점 인용", "평점 4.8 을 받았습니다"),
    ("만점 표기", "5점 만점에 5점입니다"),
    ("별 다섯 개", "별 다섯 개짜리 상담이었습니다"),
    ("별 기호 + 후기", "★ 후기 모음"),
    ("나이+직업+님", "30대 주부님도 쓰고 계십니다"),
    ("제3자 인용", "이용하신 분의 이야기를 옮깁니다"),
    ("제3자 인용2", "상담받으신 분이 이렇게 말씀하셨습니다"),
    ("고객 말 인용", "저희 고객 한 분은 이렇게 말했습니다"),
    ("지어낸 사례", "실제 상담 사례입니다"),
]

# (설명, 문구) — 차단되면 안 되는 것. 거짓 차단이 더 비싸다.
TESTIMONIAL_PASS = [
    ("1인칭 없는 정상 문구", "무엇을 준비해야 하는지부터 알려드립니다."),
    ("'후기' 낱말만", "써 본 후기를 짧게 남깁니다."),
    ("각도 0 정상 사용", "직접 써 보니 선이 얇을수록 멀리서 잘 보였습니다."),
    ("대상 서술(나이만)", "40대 이상 이용자가 많습니다."),
    ("굵게 쓴 고객님", "**고객**님께 먼저 확인드립니다."),
    ("별표 없는 강조", "지금 확인 ▶ 자세히 보기"),
    ("점수 아닌 '점'", "이 점이 제일 아쉬웠습니다."),
    # ⚠ 아래 넷은 이번 개편이 **새로 시킨 것**의 산출물이다. 막으면 안 된다.
    ("후기 요청(허락자산 지침의 산출물)", "고객 후기가 궁금하시면 댓글 남겨주세요"),
    ("청중 묘사(초소형 시장 지침의 산출물)", "40대 직장인이라면 이 상황 아실 겁니다"),
    ("청중 묘사2", "30대 주부가 가장 많이 찾습니다"),
    ("별 불릿 2개", "★★ 이번 주 소식"),
    ("별 불릿 + 숫자+한글", "★ 3가지만 확인하세요"),
    ("정상 안내", "이용하신 분은 아래 링크로 들어오세요."),
]


@pytest.mark.parametrize("name,text", TESTIMONIAL_BLOCK,
                         ids=[n for n, _ in TESTIMONIAL_BLOCK])
def test_fake_testimonial_is_blocked(name, text):
    assert CE._find_fake_testimonial(text), f"놓침: {name} -> {text!r}"


@pytest.mark.parametrize("name,text", TESTIMONIAL_PASS,
                         ids=[n for n, _ in TESTIMONIAL_PASS])
def test_normal_copy_is_not_flagged_as_testimonial(name, text):
    hits = CE._find_fake_testimonial(text)
    assert not hits, f"거짓 차단: {name} -> {hits}"


# ── 7. 순위·서열 주장 (지침7의 역방향) ───────────────────────
SUPERLATIVE_BLOCK = [
    ("업계 최초", "업계 최초 비대면 상담"),
    ("국내 유일", "국내 유일한 방식입니다"),
    ("전국 최다", "전국 최다 상담 건수"),
    ("판매 1위", "판매 1위 상품입니다"),
    ("유일한 곳", "이런 걸 하는 유일한 곳입니다"),
    ("최초로 도입", "최초로 도입한 방식입니다"),
    # 조사 하나에 뚫리던 형태(실측)
    ("조사 삽입 - 업계에서", "업계에서 유일하게 금리를 먼저 알려드립니다"),
    ("조사 삽입 - 지역에서", "이 지역에서 유일하게 이 방식을 씁니다"),
    ("비교 최상급", "가장 빠른 상담"),
    ("최저 수준", "최저 수준의 금리"),
    ("제일 낮은", "업계에서 제일 낮은 금리"),
    ("만족도 최상", "만족도 최상입니다"),
]

SUPERLATIVE_PASS = [
    ("최초 1회", "최초 1회 상담은 무료입니다."),
    ("최고 온도", "최고 온도는 60도까지 올라갑니다."),
    ("유일 아님", "유일하게 남은 방법을 찾는 중입니다."),
    ("1위 아님", "대기 순번 1번으로 안내드립니다."),
    ("가장 먼저 안내", "가장 먼저 준비하실 것을 알려드립니다."),
]


@pytest.mark.parametrize("name,text", SUPERLATIVE_BLOCK,
                         ids=[n for n, _ in SUPERLATIVE_BLOCK])
def test_superlative_is_blocked(name, text):
    assert CE._find_superlatives(text), f"놓침: {name} -> {text!r}"


@pytest.mark.parametrize("name,text", SUPERLATIVE_PASS,
                         ids=[n for n, _ in SUPERLATIVE_PASS])
def test_ordinary_copy_is_not_flagged_as_superlative(name, text):
    hits = CE._find_superlatives(text)
    assert not hits, f"거짓 차단: {name} -> {hits}"


def test_region_prefixed_superlative_is_blocked_only_when_regulated():
    """'대구 최초' 는 지역명을 열거하지 않고는 일반 규칙으로 못 잡는다.

    대부중개 광고에 '최초·유일·1위' 가 정당하게 쓰일 자리는 없으므로
    규제 업종에서는 낱말째로 막는다. 비규제 업종까지 그렇게 하면
    '최초 공개' 같은 정상 문구가 대량으로 막힌다."""
    for t in ("대구 최초 비대면 대부중개", "경북 유일의 정식등록 중개소",
              "대구 1위 상담"):
        assert CE._find_superlatives(t, strict=True), f"놓침: {t!r}"
        assert not CE._find_superlatives(t, strict=False), f"과차단: {t!r}"
    # 순서 표현은 strict 에서도 통과해야 한다.
    assert not CE._find_superlatives("최초 1회 상담", strict=True)


def test_strict_superlative_is_wired_into_the_generation_guard():
    """검사기가 있어도 생성 루프가 안 물면 소용없다.

    _find_compliance_risks 가 규제 업종에서 strict 를 켜지 않으면
    '대구 최초' 가 그대로 발행된다(표시광고법 제5조 실증책임)."""
    regul = {"compliance": {"mandatory_required": ["company"]}}
    plain = {"compliance": {"banned_phrases": []}}
    assert CE._find_compliance_risks("대구 최초 비대면 대부중개", profile=regul)
    assert CE._find_compliance_risks("경북 유일의 정식등록 중개소", profile=regul)
    # 비규제 업종까지 낱말째로 막으면 '최초 공개' 같은 정상 문구가 죽는다.
    assert not CE._find_compliance_risks("대구 최초 공개합니다", profile=plain)


# ── 8. 부당비교 (전 업종 · 표시광고법 제3조) ─────────────────
# 이번 개편이 **새로 만든 위험**이다. 공용 조각이 관행을 건드리라고 시키는데,
# 그 지시의 가장 흔한 착지점이 "다른 곳은 X 합니다. 저희는 —" 이다.
# 실측: 유도문 10개가 전부 가드를 통과했다.
COMPARE_BLOCK = [
    ("타사와 달리", "타사와 달리 조건을 먼저 공개합니다."),
    ("타사보다", "타사보다 빠릅니다"),
    ("은행보다", "은행보다 문턱이 낮습니다."),
    ("다른 업체보다", "다른 대부중개보다 빠르게 연결해 드립니다."),
    ("다들 ~ 저희는", "다들 서류부터 내라고 합니다. 저희는 순서를 바꿨습니다."),
    ("다른 곳은 ~ 저희는", "다른 곳은 금리 얘기를 안 합니다. 저희는 먼저 말씀드립니다."),
    ("보통은 ~ 저희는", "보통은 안 된다고 합니다. 저희는 됩니다."),
    ("희소성 주장", "금리부터 말씀드리는 곳은 흔치 않습니다."),
]

COMPARE_PASS = [
    ("자기 절차 설명", "접수하면 저희가 무엇부터 확인하는지 알려드립니다."),
    ("다른 색상", "다른 색으로도 만들어 봤습니다."),
    ("우리 얘기만", "저희는 도안을 먼저 보여드립니다."),
]


@pytest.mark.parametrize("name,text", COMPARE_BLOCK,
                         ids=[n for n, _ in COMPARE_BLOCK])
def test_unfair_comparison_is_blocked(name, text):
    assert CE._find_unfair_comparison(text), f"놓침: {name} -> {text!r}"


@pytest.mark.parametrize("name,text", COMPARE_PASS,
                         ids=[n for n, _ in COMPARE_PASS])
def test_own_story_is_not_flagged_as_comparison(name, text):
    hits = CE._find_unfair_comparison(text)
    assert not hits, f"거짓 차단: {name} -> {hits}"


# ── 9. 승인·심사 예단 (규제 업종 전용) ───────────────────────
APPROVAL_BLOCK = [
    ("실제 사고: 상관無", "신용평점 나빠도 상관無"),
    ("실제 사고: 연체자", "연체자 도 가능함"),
    ("실제 사고: 기록無", "조회기록 無 & 대출기록 無"),
    ("연체자 가능", "연체자도 가능합니다"),
    ("신용점수 낮아도", "신용점수 낮아도 진행됩니다"),
    ("거절되신 분", "다른 곳에서 거절되신 분도 상담 가능합니다"),
    ("거절 경험", "거절 경험 있으신 분 환영합니다"),
    ("심사 없이", "심사 없이 바로 진행"),
    ("심사가 없습니다(서술형)", "심사가 없습니다"),
    ("심사 절차가 없습니다", "심사 절차가 없습니다"),
    ("서류 없이", "서류 없이 이야기부터 듣습니다"),
    ("절차를 뺐다", "확인 절차를 뺐습니다"),
    ("심사는 나중", "심사는 나중입니다"),
    ("조사 삽입 보장", "승인을 보장합니다"),
    ("한도 확정", "한도를 확정해 드립니다"),
    ("승인율", "승인율 높습니다"),
    ("전원 승인", "전원 승인"),
    ("결과 예단", "막힌 자금, 여기서 풀립니다"),
    ("대환 해결", "대환으로 해결됩니다"),
    ("후순위 가능", "후순위까지 가능합니다"),
    ("걱정 마라", "한도 걱정 없이 상담하세요"),
    ("저신용 명사형", "저신용도 상담 가능합니다"),
    ("무직", "무직이어도 괜찮습니다"),
    ("소득 증빙", "소득 증빙이 어려우신 분"),
    ("직장 없이", "직장 없이도 상담 가능합니다"),
    ("누구든(조사 우회)", "누구든 대출 가능"),
    ("누구나 다(조사 삽입)", "누구나 다 가능합니다"),
    ("묻지 마(공백 삽입)", "묻지 마 상담"),
    ("무 심사(공백 삽입)", "무 심사"),
    ("무 조건(공백 삽입)", "무 조건 도와드립니다"),
    ("관행 부정 수사", "신용점수 낮으면 안 된다고 누가 정했나요?"),
    ("1인칭 체험담", "제가 직접 접수해 보니 생각보다 단순했습니다"),
    ("1인칭 체험담2", "써 보니 상담이 이 정도로 담백할 줄은 몰랐습니다"),
    ("처지 좁히기 - 카드값", "이번 달 카드값이 밀린 분께"),
    ("처지 좁히기 - 잔고", "통장 잔고가 마이너스인 분"),
    ("처지 좁히기 - 신용점수", "신용점수 600점대인 분께"),
    ("처지 좁히기 - 등급", "4등급 이하이신 분들께"),
]

APPROVAL_PASS = [
    ("절차 설명", "보통 이런 순서로 진행됩니다."),
    ("상담 범위", "무엇을 상담할 수 있는지 알려드립니다."),
    ("일반 가능", "전화 상담도 가능합니다."),
    ("서류 안내", "준비하실 서류를 먼저 알려드립니다."),
    # ⚠ 정직하게 '안 된다'고 알리는 문장까지 막으면 loan 은 아무 말도 못 한다.
    ("정직한 경고", "연체 이력이 있으면 상담이 어려울 수 있습니다."),
    ("정직한 경고2", "연체 중이신 경우 진행이 어렵습니다."),
    ("확정 오탐", "대출 상담 확정 후 안내"),
    ("확정본 오탐", "금리 안내 확정본입니다"),
    ("업무 조건", "업무 조건을 먼저 확인합니다."),
]


@pytest.mark.parametrize("name,text", APPROVAL_BLOCK,
                         ids=[n for n, _ in APPROVAL_BLOCK])
def test_approval_claim_is_blocked(name, text):
    assert CE._find_approval_claims(text), f"놓침: {name} -> {text!r}"


@pytest.mark.parametrize("name,text", APPROVAL_PASS,
                         ids=[n for n, _ in APPROVAL_PASS])
def test_normal_process_copy_is_not_flagged(name, text):
    hits = CE._find_approval_claims(text)
    assert not hits, f"거짓 차단: {name} -> {hits}"


def test_yesterdays_illegal_copy_is_all_blocked():
    """2026-08-10 위법 판정 건. 당시 가드는 셋을 놓쳤다."""
    regul = {"compliance": {"mandatory_required": ["company"]}}
    for t in ("★5 고객 후기 4건",
              "★★★★★ 상담이 정말 빨랐어요 - 40대 직장인 김OO님",
              "신용평점 나빠도 상관無",
              "연체자 도 가능함",
              "조회기록 無 & 대출기록 無"):
        assert CE._find_compliance_risks(t, profile=regul), f"놓침: {t!r}"


def test_approval_check_is_regulated_industry_only():
    """규제 업종 표시가 없는 프로필에는 이 검사가 붙지 않아야 한다.

    붙이면 "예약 가능합니다" 같은 정상 문구가 13업종에서 대량으로 막힌다."""
    plain = {"compliance": {"banned_phrases": []}}
    regul = {"compliance": {"mandatory_required": ["company"]}}
    assert CE._is_regulated(regul) is True
    assert CE._is_regulated(plain) is False
    text = "연체자도 가능합니다"
    assert CE._find_compliance_risks(text, profile=regul)
    assert not CE._find_compliance_risks(text, profile=plain)
    # 비규제 업종의 정상 문구가 막히면 안 된다.
    for ok in ("주말에도 상담 가능합니다", "무료 체험 가능합니다",
               "심사 없이 바로 써 보세요", "직접 써 보니 좋았습니다"):
        assert not CE._find_compliance_risks(ok, profile=plain), ok


def test_legal_mandatory_text_is_not_blocked():
    """법정 지정문구를 검사기가 막으면 소재가 통째로 폴백된다."""
    regul = {"compliance": {"mandatory_required": ["company"]}}
    for t in ("과도한 빚은 당신에게 큰 불행을 안겨 줄 수 있습니다.",
              "대출 시 귀하의 신용등급이 하락할 수 있습니다.",
              "중개수수료를 요구하거나 받는 것은 불법입니다.",
              "※ 대출은 심사 기준에 따라 한도 및 금리가 달라질 수 있으며,"
              " 대출 실행이 보장되는 것은 아닙니다.",
              "보유 자산의 가치를 활용한 금융 솔루션."
              " 추가자금·대환·후순위까지 검토해 드립니다."):
        assert not CE._find_compliance_risks(t, profile=regul), t


# ── 10. 금칙어 정규화 회귀 ───────────────────────────────────
def test_banned_still_caught_plain():
    for b in config.BANNED_PHRASES[:3]:
        assert CE._find_banned(f"앞말 {b} 뒷말")


def test_banned_survives_fullwidth_and_extra_space():
    """실측: 표기만 바꾸면 그대로 새어 나갔다."""
    multi = [b for b in config.BANNED_PHRASES if " " in b]
    if not multi:
        pytest.skip("이 업종 프로필에는 여러 낱말 금칙어가 없다")
    b = multi[0]
    assert CE._find_banned(b.replace(" ", "  ")), "공백 두 개가 통과했다"
    assert CE._find_banned(b.replace(" ", "")), "공백 없는 형태가 통과했다"


def test_banned_normalization_does_not_overblock():
    """⚠ 한 낱말 금칙어에 공백 제거를 걸면 '업무 조건' 이 '무조건' 에 걸린다.

    거짓 차단이 더 비싸다. 아래가 통과하지 못하면 정상 문구가 폴백된다.
    공백 삽입 우회('무 조건')는 _find_approval_claims 가 앞 글자를 보고 잡는다."""
    for ok in ("업무 조건을 먼저 확인합니다.",
               "의무 조건이 하나 있습니다.",
               "직무 조건을 안내드립니다."):
        assert not CE._find_banned(ok), f"거짓 차단: {ok!r}"
        assert not CE._find_approval_claims(ok), f"거짓 차단: {ok!r}"


# ── 11. 지어낸 수치 ──────────────────────────────────────────
def test_unverified_numbers_regression():
    assert CE._find_unverified_numbers("40초 만에 나옵니다.", "")
    assert not CE._find_unverified_numbers("2026년에도 씁니다.", "")
    assert not CE._find_unverified_numbers("1~5분 걸립니다.", "생성 1~5분")
    assert CE._find_unverified_numbers("1분 만에 나옵니다.", "생성 1~5분")


WORD_NUM_BLOCK = [
    "서류 접수부터 결과까지 보통 이틀 걸립니다",
    "사흘이면 결과가 나옵니다",
    "당일 처리해 드립니다",
    "하루 만에 연결됩니다",
    "반나절이면 끝납니다",
    "두 배 빠르게",
    "한 시간이면 상담이 끝납니다",
]

WORD_NUM_PASS = [
    "하루가 다르게 좋아집니다",
    "이틀치 분량을 준비했습니다",
    "당일 방문도 상담 때 정합니다",
]


@pytest.mark.parametrize("text", WORD_NUM_BLOCK)
def test_korean_numeral_claims_are_blocked(text):
    """아라비아 숫자만 보던 규칙은 이걸 전부 놓쳤다(실측).

    하필 band_ad.txt 의 '좋음' 예시가 이 형태였다 — 프롬프트가 위반 사례를
    모범 답안으로 보여주고 있었다."""
    assert CE._find_unverified_numbers(text, ""), f"놓침: {text!r}"


@pytest.mark.parametrize("text", WORD_NUM_PASS)
def test_korean_numeral_idioms_are_not_blocked(text):
    assert not CE._find_unverified_numbers(text, ""), f"거짓 차단: {text!r}"


def test_korean_numeral_passes_when_registered_in_facts():
    assert not CE._find_unverified_numbers("보통 이틀 걸립니다", "접수~결과 이틀")


@pytest.mark.parametrize("name", ["band_ad.txt", "facebook_ad.txt",
                                  "kakao_ad.txt", "facebook_content.txt"])
def test_channel_prompt_examples_are_themselves_clean(name):
    """프롬프트가 보여주는 '좋음' 예시가 가드에 걸리면 안 된다.

    LLM 은 규칙보다 예시를 따른다. 예시가 위반 사례면 규칙은 무력해진다.
    실측 두 건:
      band_ad '서류 접수부터 결과까지 보통 이틀 걸립니다' → 실증 불가 기간
      facebook_ad '뽑는 건 커피 식기 전에 끝났습니다'    → 1인칭 체험담"""
    text = (PROMPTS / name).read_text(encoding="utf-8")
    good = [ln.split(":", 1)[1] for ln in text.splitlines()
            if ln.strip().startswith(("좋음:", "나음:"))]
    assert good, f"{name} 에 '좋음' 예시가 없다"
    regul = {"compliance": {"mandatory_required": ["company"]}}
    for ex in good:
        assert not CE._find_unverified_numbers(ex, ""), f"{name}: {ex!r}"
        assert not CE._find_compliance_risks(ex, profile=regul), f"{name}: {ex!r}"


# ── 12. 각도 회전 ────────────────────────────────────────────
def test_angle_selection_unchanged_when_profile_has_no_deny(monkeypatch):
    """무회귀: deny 를 선언하지 않은 업종은 예전 계산과 한 글자도 달라지면 안 된다."""
    monkeypatch.setattr(config, "PROFILE_DENY_ANGLES", [], raising=False)
    for i in range(300):
        key = f"c{i}-ch{i % 7}"
        old = CE.ANGLES[zlib.crc32(key.encode("utf-8")) % len(CE.ANGLES)]
        assert CE._pick_angle(key) == old


def test_denied_angles_are_never_selected(monkeypatch):
    """loan 이 금지한 0·2·5 는 단 한 번도 나오면 안 된다.

    이 세 각도는 각각 '후기처럼 / 전후 대비 / 실패했던 시도' 다. 규제 업종에서
    전부 1인칭 체험담·승인 암시로 직행한다. 균등분포이므로 막지 않으면
    소재의 약 37%가 위법 유도 각도를 배정받는다."""
    monkeypatch.setattr(config, "PROFILE_DENY_ANGLES", [0, 2, 5], raising=False)
    banned = {CE.ANGLES[i] for i in (0, 2, 5)}
    got = {CE._pick_angle(f"c{i}-ch{i % 7}") for i in range(500)}
    assert not (got & banned), f"금지 각도가 배정됐다: {got & banned}"
    # 남은 5개는 여전히 골고루 쓰여야 한다(한 각도로 쏠리면 스팸 판정).
    assert len(got) == len(CE.ANGLES) - 3


def test_loan_profile_denies_every_person_story_angle():
    """프로필 파일이 실제로 그렇게 선언돼 있는가.

    ⚠ 6·7 이 늦게 추가됐다. 얇음 분기에서 "구체성은 장면으로 만들어라"를 지운
      이유(장면의 착지점 = 사람 이야기)가 각도 7 "숫자 대신 구체적인 장면
      하나로" 에 글자 그대로 남아 있었고, deny 가 [0,2,5]일 때 남는 후보가
      5개라 loan 소재의 약 20%가 그 지시를 그대로 받았다."""
    import profiles
    loan = profiles.load("loan")
    assert (loan.get("copy") or {}).get("deny_angles") == [0, 2, 5, 6, 7]


def test_no_loan_angle_asks_for_a_scene_or_a_persons_situation(monkeypatch):
    """⚠ 각도는 8개 전부를 봐야 한다.

    이 파일의 조립 도우미는 track_key 가 'c1-ch1' 로 고정돼 있어 각도 하나만
    본다. 그래서 '장면' 지시가 얇음 분기에서 사라진 것만 확인하고 각도
    목록에서 되살아난 것은 못 봤다. 규제 업종이 **실제로 받을 수 있는 모든
    각도**를 훑는다."""
    monkeypatch.setattr(config, "PROFILE_DENY_ANGLES", [0, 2, 5, 6, 7],
                        raising=False)
    picked = {CE._pick_angle(f"c{i}-ch{i}") for i in range(200)}
    assert picked, "각도가 하나도 안 나온다"
    for a in picked:
        for word in ("장면", "후기", "공감할 상황", "달라졌는지", "실패했던"):
            assert word not in a, f"규제 업종에 사람 이야기 유도축이 남아 있다: {a}"


def test_angles_list_length_is_stable():
    """⚠ ANGLES 에서 항목을 넣거나 빼면 crc32 % len 이 달라져 진행 중인
    모든 소재의 각도가 재배정된다. deny_angles 의 인덱스도 전부 어긋난다."""
    assert len(CE.ANGLES) == 8


# ── 13. 필수 조각은 fail-closed ──────────────────────────────
def test_required_shared_fragment_raises_when_missing(tmp_path, monkeypatch):
    """조각이 사라지면 **조용히 넘어가면 안 된다**.

    실측(수정 전): 조각이 없어도 generate_copy 가 정상 반환했다 —
    예외도 경고도 폴백도 없이, 위법 방지 레일이 통째로 빠진 프롬프트로
    14업종이 계속 광고를 냈다. 배포 누락·git clean 어느 경로로도 발생한다."""
    monkeypatch.setattr(CE, "PROMPT_DIR", tmp_path)
    monkeypatch.setattr(CE, "_SHARED_CACHE", {})
    with pytest.raises(FileNotFoundError):
        CE._load_shared("_purplecow.txt")
    # 필수 목록에 없는 조각은 예전대로 빈 문자열이어야 한다(무회귀).
    assert CE._load_shared("_not_required.txt") == ""


def test_preflight_checks_prompt_fragments():
    """발행 시점에야 터지지 않도록 preflight 가 미리 본다."""
    import preflight
    assert preflight.prompt_fragment_gaps() == []


# ── 14. 생성 루프가 새 검사기를 실제로 물고 있는가 ───────────
def test_generate_copy_sends_illegal_copy_to_fallback():
    """어제 그대로의 문구를 LLM 이 뱉으면 발행되면 안 된다.

    ⚠ 예전에는 금칙어를 문자열로 잘라내고(_strip_banned) 그대로 발행했다.
      실측: {'headline': '누구나 가능한 상담'} -> '한 상담' 이 나갔다.
      뭉개진 한국어를 내보내느니 폴백 캡션이 낫다 → 예외로 던진다.
      (orchestrator.make_caption 이 잡아 _fallback_caption 으로 보낸다)"""
    bad_json = ('{"headline": "★5 고객 후기 4건",'
                ' "body": "40대 직장인 김OO님도 만족하셨습니다.",'
                ' "cta": "문의주세요"}')
    with pytest.raises(ValueError) as e:
        CE.generate_copy(_campaign(), _profile(), max_retries=1,
                         _llm=lambda _p: bad_json)
    assert "카피 검증 실패" in str(e.value)


def test_generate_copy_retries_then_accepts_clean_copy():
    """검사에 걸리면 재작성 지시가 붙어 다시 물어봐야 한다."""
    seen = []

    def llm(prompt):
        seen.append(prompt)
        if len(seen) == 1:
            return '{"headline": "업계 최초 서비스", "body": "본문", "cta": "확인"}'
        return _OK_JSON

    out = CE.generate_copy(_campaign(), _profile(), max_retries=3, _llm=llm)
    assert out["_attempts"] == 2
    assert "[재작성]" in seen[1]
    assert "순위·서열" in seen[1]


def test_regenerate_carries_the_rail_and_blocks_illegal_edits():
    """승인 콘솔 '수정' 한 번으로 방어가 통째로 풀리면 안 된다."""
    seen = {}

    def llm(prompt):
        seen["p"] = prompt
        return '{"headline": "★5 후기", "body": "40대 직장인 김OO님", "cta": "문의"}'

    with pytest.raises(ValueError) as e:
        CE.regenerate({"headline": "h", "body": "b", "cta": "c"},
                      "좀 더 눈에 띄게", _llm=llm)
    assert "수정본 검증 실패" in str(e.value)
    # 프롬프트에 규제 문맥이 실려 갔는가
    assert "지어내지 마라" in seen["p"]
    assert "[업종 주의사항]" in seen["p"]


def test_regenerate_no_longer_saves_mangled_banned_copy():
    """⚠ 생성 경로에서는 없앤 _strip_banned 발행이 수정 경로에만 남아 있었다.

    실측: {'headline': '누구나 가능한 상담'} -> '한 상담' 이 그대로 저장됐다.
    뭉개진 한국어를 저장하느니 운영자에게 되돌려야 한다."""
    bad = ('{"headline": "누구나 가능한 상담",'
           ' "body": "무조건 도와드립니다", "cta": "문의"}')
    with pytest.raises(ValueError) as e:
        CE.regenerate({"headline": "h", "body": "b", "cta": "c"},
                      "수정", _llm=lambda _p: bad)
    assert "금칙어" in str(e.value)


def test_regenerate_blocks_competitor_url():
    """_find_leaks 가 이 경로에만 빠져 있었다.

    _find_leaks 를 만들게 한 원래 사고(치환 실패 → LLM 이 Midjourney 를
    지어내 경쟁 서비스를 홍보)의 재발 경로다. 승인 콘솔에서 '수정' 한 번이면
    타사 주소가 그대로 저장됐다(실측)."""
    bad = ('{"headline": "안내", "body": "자세한 건 competitor.co.kr 에서",'
           ' "cta": "문의"}')
    with pytest.raises(ValueError) as e:
        CE.regenerate({"headline": "h", "body": "b",
                       "cta": "https://example-brand.kr/apply"},
                      "수정", _llm=lambda _p: bad)
    assert "우리 것이 아닌 주소" in str(e.value)


def test_regenerate_keeps_urls_that_were_already_approved():
    """원본에 이미 들어 있던 주소는 우리 것이다(생성 검증을 통과한 문구다).

    여기서 막으면 '수정' 버튼이 사실상 못 쓰게 된다 — 원본 CTA 의
    접수 링크를 모델이 그대로 되돌려주는 것이 정상 동작이기 때문이다."""
    same = ('{"headline": "안내", "body": "본문",'
            ' "cta": "신청은 https://example-brand.kr/apply"}')
    out = CE.regenerate({"headline": "h", "body": "b",
                         "cta": "https://example-brand.kr/apply"},
                        "수정", _llm=lambda _p: same)
    assert "example-brand.kr" in out["cta"]


def test_approval_console_shows_the_real_reason():
    """운영자가 원인을 못 보면 엉뚱한 곳(크레딧·네트워크)을 뒤진다.

    regenerate 가 위법 판정으로 던지는 ValueError 를
    "카피 재생성 실패 — 크레딧/네트워크 확인" 으로 뭉뚱그리면 안 된다."""
    src = (ROOT / "approval.py").read_text(encoding="utf-8")
    i = src.index("copy_engine.regenerate(_caption_of")
    tail = src[i:i + 700]
    assert "except ValueError as e:" in tail, "위법 사유가 여전히 뭉뚱그려진다"
    assert tail.index("except ValueError") < tail.index("크레딧/네트워크")


# ── 15. 무회귀 — loan 이 아닌 업종 ───────────────────────────
# ⚠ config 는 import 시점에 AUTOAD_PROFILE 을 읽어 굳는다. 같은 프로세스에서
#   업종을 갈아끼우면 BANNED_PHRASES 등이 어긋나므로 하위 프로세스로 돌린다.
_PROBE = r'''
import sys
sys.path.insert(0, r"{root}")
import config
from content import copy_engine as CE
camp = dict(id=1, track_key="c1-ch1", title="t", product="p", goal="g",
            styles="s", form="ad", brand_site="example-brand.kr",
            form_url="https://example-brand.kr/apply", disclosures="")
prof = dict(platform="{platform}", tone="담백", audience="일반", topic="생활")
seen = {{}}
def llm(p):
    seen.setdefault("p", p)
    return ('{{"headline": "접수하면 순서대로 안내드립니다",'
            ' "body": "무엇을 준비해야 하는지부터 알려드립니다.",'
            ' "cta": "어떤 쪽이 더 궁금하신가요?"}}')
CE.generate_copy(camp, prof, _llm=llm)
p = seen["p"]
assert "보랏빛 소 자가 진단" in p, "공용 조각 미부착"
assert "[지어내지 마라" in p, "공통 레일 미부착"
assert "순위·서열 주장 금지" in p, "공통 레일 미부착"
assert p.index("[이번 글의 각도]") < p.index("[지어내지 마라"), "순서 역전"
reg = CE._is_regulated()
# 규제 레일은 규제 업종에만 붙어야 한다(비규제 업종에 붙으면 정상 문구를 위축시킨다).
assert ("[규제 업종" in p) is reg, ("규제 레일 부착 오류", reg)
# ── 재료 깊이 게이트: 두 분기 중 **정확히 하나**만 붙어야 한다 ──
depth = CE.facts_depth(getattr(config, "PROFILE_FACTS", "") or "")
assert ("[재료 점검" in p) is (depth == 0), ("얇음 블록 부착 오류", depth)
assert ("[확인된 사실]" in p) is bool(getattr(config, "PROFILE_FACTS", "")), (
    "확인된 사실 블록 부착 오류", depth)
assert "장면으로 만들어라" not in p, "사고 유도축이 남아 있다"
# 얇음 전용 지시가 재료 있는 업종에 새면 그냥 비대다.
if depth:
    for w in ("철회한다", "술어가 있는 문장", "빈칸을 빈칸이라고"):
        assert w not in p, ("얇음 전용 지시 누출", w)
# 관점(angle)은 모든 채널 프롬프트의 출력 스키마 맨 앞에 있어야 한다.
assert '"angle"' in p and p.index('"angle"') < p.index('"headline"'), "angle 순서"
risk = CE._find_compliance_risks("전화 상담도 가능합니다. 예약도 가능합니다.")
assert not risk, ("정상 문구 거짓 차단", risk)
if not reg:
    for ok in ("주말에도 상담 가능합니다", "무료 체험 가능합니다"):
        assert not CE._find_compliance_risks(ok), ("거짓 차단", ok)
print("OK", config.PROFILE_KEY, reg, len(p))
'''


_ALL_PROFILES = sorted(p.stem for p in (ROOT / "profiles").glob("*.yaml")
                       if not p.stem.startswith("_"))


@pytest.mark.parametrize("profile_key", _ALL_PROFILES)
def test_other_profiles_still_assemble(profile_key):
    """공용 조각 변경은 14업종 전부에 걸린다. 하나라도 깨지면 그 업종의
    카피가 전부 폴백된다."""
    env = dict(os.environ, AUTOAD_PROFILE=profile_key, PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, "-c", _PROBE.format(root=str(ROOT), platform="band")],
        capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
    assert r.returncode == 0, f"{profile_key} 조립 실패:\n{r.stdout}\n{r.stderr}"
    assert r.stdout.startswith("OK ")


# ══════════════════════════════════════════════════════════════
#  16. 재료 깊이 게이트 (facts 빈약도)
#
#  왜 이게 가장 중요한가:
#    2026-08-09/10 사고의 기계적 원인이다. 14업종 중 11개는 PROFILE_FACTS 가
#    0자이고(캠페인 facts/promo 를 넣는 경로 자체가 DB 에 없다 — campaigns
#    테이블에 그 컬럼이 없다), 그 상태에서 채널 프롬프트는 전 업종에
#    "첫 줄에 구체적인 하나를 던져라"라고 시킨다. 재료가 없는데 구체성을
#    요구하면 그건 지어내라는 압력이다.
#    그리고 예전 else 분기는 그 압력을 한 번 더 밀었다 — "구체성은 숫자가
#    아니라 **장면**으로 만들어라". loan 에서 '장면'의 착지점은 사람 이야기 =
#    1인칭 체험담·제3자 후기다. 각도 0·2·5 는 deny_angles 로 껐는데 이 문장은
#    안 껐던 것이다.
# ══════════════════════════════════════════════════════════════
_THIN_MARK = "[재료 점검"
_THICK_MARK = "[확인된 사실]"


@pytest.mark.parametrize("facts,want", [
    ("", 0),
    ("   ", 0),
    # 수치가 하나도 없는 문장은 실증 근거가 아니다(쓸 수 있는 수치가 0개).
    ("무료 체험을 제공합니다", 0),
    # 실제 프로필 값 3종
    ("영상 생성에 걸리는 시간 1~3분", 1),                       # adstudio
    ("도안 생성에 걸리는 시간 30초~1분", 1),                     # inkcraft
    ("굿즈 도안 생성 30초~1분 / 제작 후 배송 3~7일", 2),          # printcraft
    # 한글 수사도 수치다(_find_unverified_numbers 와 같은 기준).
    ("접수부터 결과까지 이틀 걸립니다", 1),
])
def test_facts_depth_counts_what_the_number_guard_actually_licenses(facts, want):
    """⚠ 범위('30초~1분')는 두 개의 수치가 아니라 **한 개의 사실**이다.

    양끝을 따로 세면 범위 1건짜리 adstudio 가 범위 2건짜리 printcraft 와
    같은 점수가 되어 축이 변별력을 잃는다."""
    assert CE.facts_depth(facts) == want


def _assemble_with_facts(facts, monkeypatch, platform="band", form="ad"):
    monkeypatch.setattr(config, "PROFILE_FACTS", facts, raising=False)
    return _assemble(platform, form)


def test_thin_material_retracts_the_specificity_demand(monkeypatch):
    """재료가 얇으면 '구체적인 하나를 넣어라'를 **철회**해야 한다.

    추가가 아니라 교체다. 요구를 남겨 둔 채 "지어내지는 마라"만 덧붙이면
    모델은 두 지시를 동시에 만족시킬 수 없고, 실측 결과 형용사로 메운다
    (loan 카피 1건당 상투어 4.92개 — facts 를 가진 업종의 3.3배)."""
    p = _assemble_with_facts("", monkeypatch)
    assert _THIN_MARK in p
    # ⚠ 철회 범위를 명시한다. 채널 프롬프트에는 '구체적인 하나'가 두 군데
    #   있는데(첫 줄 요구 / [전달 테스트]의 '조건 하나·순서·디테일'), 뒤엣것은
    #   얇음 분기가 두 줄 뒤에 권하는 바로 그 축이라 **철회하면 안 된다**.
    assert "**수치로 만드는 구체성**만 철회한다" in p
    assert "조건 하나 · 순서 · 디테일" in p
    # 돌려야 할 축 — loan.yaml note 가 이미 가리키던 그 방향(규제 업종 전용).
    # ⚠ '무엇을 상담·이용할 수 있는가' 만으로 검사하면 안 된다. 같은 문구가
    #   _compliance_rail.txt 에도 있어서 규제 업종이면 항상 참이 된다.
    assert "쓸 축은 둘이다" in p
    assert "어떤 순서로 진행되는가" in p
    # 재료가 없으면 [확인된 사실] 머리표를 달지 않는다.
    assert _THICK_MARK not in p


def test_thin_block_does_not_push_loan_axes_onto_unregulated_profiles():
    """⚠ 무회귀. facts 가 빈 업종은 11개인데 그중 10개는 규제 업종이 아니다.

    '쓸 축은 상담·절차 둘뿐' 은 loan 형(型) 지시다. 그걸 전 업종에 붙이면
    프롬프트 **맨 끝**에서(순서가 곧 강도다) '이걸 왜 만들었는지 배경을
    밝히며 써라'는 콘텐츠형 각도를 덮어쓴다. 라벨형 헤드라인이 측정된 곳도
    loan 하나뿐이다(12건 중 4건, adstudio·printcraft 는 0건)."""
    common = CE._material_block("", regulated=False)
    reg = CE._material_block("", regulated=True)
    # 전 업종 공통은 '수치를 지어내지 마라' 두 줄뿐이다.
    assert "수치로 만드는 구체성" in common
    for loan_only in ("쓸 축은 둘이다", "어떤 순서로 진행되는가",
                      "결과를 말하지 마라", "~안내"):
        assert loan_only not in common, f"loan 형 지시가 비규제 업종에 샜다: {loan_only}"
        assert loan_only in reg


def test_scene_instruction_is_gone_from_the_thin_branch(monkeypatch):
    """⚠ 회귀 케이스. '구체성은 장면으로 만들어라'가 loan 의 사고 유도축이었다.

    광고주는 그 상품을 쓴 당사자가 아니므로, 규제 업종에서 '장면'의 착지점은
    1인칭 체험담이거나 제3자 후기다 — _APPROVAL_RES 와 deny_angles 가 막으려는
    바로 그 방향을 프롬프트가 시키고 있었다."""
    p = _assemble_with_facts("", monkeypatch)
    assert "장면으로 만들어라" not in p
    assert "숫자가 아니라 **장면**" not in p


def test_thick_material_keeps_the_old_instructions_and_skips_the_thin_block(monkeypatch):
    """무회귀: facts 를 가진 3업종(adstudio·inkcraft·printcraft)은 예전 분기 그대로."""
    p = _assemble_with_facts("영상 생성에 걸리는 시간 1~3분", monkeypatch)
    assert _THICK_MARK in p
    assert "영상 생성에 걸리는 시간 1~3분" in p
    assert "위에 있는 것만" in p
    assert "범위로 적힌 값은 범위 그대로" in p
    # 얇음 블록이 붙으면 안 된다 — 조건부 주입의 요점이 여기다.
    assert _THIN_MARK not in p
    assert "철회한다" not in p


def test_thin_and_thick_prompts_actually_differ(monkeypatch):
    """지시가 '달라지는가'가 이 게이트의 전부다. 같으면 게이트가 아니다."""
    thin = _assemble_with_facts("", monkeypatch)
    thick = _assemble_with_facts("영상 생성에 걸리는 시간 1~3분", monkeypatch)
    assert thin != thick


def test_two_or_more_facts_are_told_to_subtract(monkeypatch):
    """판정 사다리의 위쪽 칸 — 점수가 높으면 오히려 덜어내라.

    ⚠ 쿠팡의 5단 사다리는 가져오지 않았다. AutoAd 의 최고 점수 업종이
      printcraft(사실 2건)라 3~4점 칸의 문장은 영원히 안 쓰이는 죽은 문자열이고,
      죽은 문자열도 프롬프트에는 실린다."""
    p2 = _assemble_with_facts("생성 30초~1분 / 배송 3~7일", monkeypatch)
    assert "가장 강한 하나만" in p2
    p1 = _assemble_with_facts("영상 생성에 걸리는 시간 1~3분", monkeypatch)
    assert "가장 강한 하나만" not in p1


def test_label_headline_rewrite_is_fenced_away_from_result_predicates(monkeypatch):
    """라벨형 헤드라인은 재료가 얇을 때 나온다.

    실측: loan 헤드라인 12건 중 4건(33%)이 술어 없는 라벨이었고
    ('사업자 담보대출, 맞춤 비교로 현명하게'), facts 를 가진 adstudio·
    printcraft 는 0건이었다. 그래서 이 요구는 공용 조각이 아니라 **얇음 분기**에
    둔다 — 필요한 곳에만 실린다.

    ⚠ 그런데 규제 업종에서 '술어를 넣어라'는 그대로 위법 유도다. 라벨을 자연
      스럽게 술어형으로 고쳐 쓰면 결과를 말하는 서술어가 나온다('여기서는
      풀립니다'). 실측 20건 중 19건이 검사기를 통과했다. 그래서 요구와
      **착지 금지 지점을 한 문장에** 묶는다 — 축은 절차, 결과는 금지."""
    p = _assemble_with_facts("", monkeypatch)
    assert "라벨이면" in p and "~안내" in p
    i = p.index("~안내")
    assert "결과를 말하지 마라" in p[i:i + 200], \
        "라벨 교정 요구와 결과 예단 금지가 떨어져 있으면 뒤엣것이 이긴다"
    for verb in ("풀립니다", "해결됩니다", "마련해 드립니다"):
        assert verb in p, f"금지할 술어를 이름으로 못 박아야 한다: {verb}"
    thick = _assemble_with_facts("영상 생성에 걸리는 시간 1~3분", monkeypatch)
    assert "라벨이면" not in thick


# ══════════════════════════════════════════════════════════════
#  17. angle 필드 — 순서가 곧 장치다
# ══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("name", ["band_ad.txt", "facebook_ad.txt",
                                  "kakao_ad.txt", "facebook_content.txt"])
def test_angle_comes_first_in_the_output_schema(name):
    """헤드라인을 쓰기 전에 관점을 못 박게 한다. 훈계가 아니라 구조다.

    카드뉴스 구현의 실측: 프롬프트가 밀어주는 관점을 모델이 거의 100%
    따랐다(5/5·4/5·3/3). 그러니 관점을 **어디에** 놓느냐가 실제로 결과를 정한다."""
    text = (PROMPTS / name).read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.strip().startswith('{"'))
    for k in ("angle", "headline", "body", "cta"):
        assert f'"{k}"' in line, f"{name}: {k} 키가 스키마에 없다"
    assert line.index('"angle"') < line.index('"headline"'), \
        f"{name}: angle 이 headline 뒤에 있다 — 순서가 장치인데 뒤집혔다"


def test_generate_copy_returns_angle_first():
    out = CE.generate_copy(_campaign(), _profile(), _llm=lambda _p: _OK_JSON_ANGLE)
    assert list(out)[0] == "angle"
    assert out["angle"] == "절차를 먼저 펼쳐 보인다"


def test_legacy_response_without_angle_still_works():
    """⚠ 하위호환. 기존 소재의 copy_json 에는 angle 키가 없다."""
    out = CE.generate_copy(_campaign(), _profile(), _llm=lambda _p: _OK_JSON)
    assert out["angle"] == ""
    assert out["headline"]


def test_angle_never_reaches_the_published_text():
    """angle 은 기획 메모다. 광고 본문으로 새면 그 자체가 사고다."""
    import orchestrator
    cap = {"angle": "이 문장은 절대 발행되면 안 된다", "headline": "머리글",
           "body": "본문", "cta": "링크", "disclaimer": "", "profile_key": "x"}
    text = orchestrator._caption_text(cap)
    assert "이 문장은 절대 발행되면 안 된다" not in text
    assert "머리글" in text and "본문" in text and "링크" in text
    # angle 이 아예 없던 시절의 소재도 그대로 만들어져야 한다.
    legacy = {k: v for k, v in cap.items() if k != "angle"}
    assert orchestrator._caption_text(legacy) == text


def test_angle_is_not_part_of_the_compliance_blob():
    """⚠ 명시적 결정이다.

    angle 은 발행되지 않는데(_caption_text 가 안 읽는다), 검사 blob 에 넣으면
    적법한 카피가 재시도 초과 → 폴백으로 간다. 발행되지 않는 문자열 때문에
    발행 가능한 문구를 버리는 셈이다. 위법 판정은 실제로 나가는
    headline/body/cta 에서 한다."""
    bad_angle = ('{"angle": "업계 최초라는 점을 앞세운다",'
                 ' "headline": "접수하면 순서대로 안내드립니다",'
                 ' "body": "무엇을 준비해야 하는지부터 알려드립니다.",'
                 ' "cta": "어떤 쪽이 더 궁금하신가요?"}')
    out = CE.generate_copy(_campaign(), _profile(), max_retries=1,
                           _llm=lambda _p: bad_angle)
    # 적법한 카피가 기획 메모 때문에 폴백으로 가면 안 된다(재시도 0회).
    assert out["_attempts"] == 1
    assert out["headline"] == "접수하면 순서대로 안내드립니다"
    # 같은 문장이 body 에 있으면 그때는 반드시 막힌다.
    leaks = ('{"angle": "담백하게", "headline": "업계 최초 비대면 상담",'
             ' "body": "본문", "cta": "문의"}')
    with pytest.raises(ValueError):
        CE.generate_copy(_campaign(), _profile(), max_retries=1,
                         _llm=lambda _p: leaks)


def test_approval_edit_drops_the_stale_angle(temp_db):
    """승인 콘솔 '수정' 후에는 관점 뱃지가 남아 있으면 안 된다.

    ⚠ _EDITABLE_KEYS 화이트리스트에 angle 을 넣어 '덮어쓰는' 것이 아니다.
      그 목록이 좁은 이유는 모델이 입력 구조를 되돌려줄 때 profile_key 가
      오염되는 것을 막기 위해서고 그건 그대로 지킨다. regenerate() 는 angle 을
      돌려주지 않으므로, 두면 headline/body/cta 만 새 값이고 관점은 수정 전
      값이 남는다 — 그 뱃지가 헤드라인 **위**에 그려져 운영자가 지금 화면의
      카피와 무관한 관점을 근거로 두 번째 검토를 하게 된다."""
    import db, approval
    assert "angle" not in approval._EDITABLE_KEYS
    cid = db.add_creative(
        db.add_campaign("t", "상담"), db.add_channel("band", "@t", "t"),
        {"angle": "절차를 펼쳐 보인다", "headline": "h", "body": "b",
         "cta": "c", "profile_key": "loan"})
    merged = approval._update_caption(
        cid, {"headline": "H", "body": "B", "cta": "C",
              "profile_key": "loan_v2"})
    assert merged.get("angle", "") == ""
    assert merged["headline"] == "H"
    # 업종 표식은 절대 바뀌면 안 된다(화이트리스트의 원래 목적).
    assert merged["profile_key"] == "loan"


def test_approval_preview_labels_the_angle_as_unpublished():
    """운영자가 관점을 볼 수 있어야 하되, 발행 본문으로 오해하면 안 된다."""
    import approval
    txt = approval._caption_text({"angle": "절차를 펼쳐 보인다", "headline": "h",
                                  "body": "b", "cta": "c"})
    assert txt.startswith("[관점")
    assert "발행 안 됨" in txt
    # angle 이 없던 소재는 그 줄이 아예 없어야 한다(빈 라벨만 뜨면 더 헷갈린다).
    assert not approval._caption_text({"headline": "h"}).startswith("[관점")


def test_new_operator_facing_strings_survive_cp949():
    """⚠ cp949 콘솔·작업 스케줄러 경로에서 터지면 안 된다.

    실측: em dash(—)·⚠·✔ 는 cp949 로 인코딩되지 않는다. 새로 넣는 문자열에는
    쓰지 않는다(· ○ △ ★ ─ 는 안전하다)."""
    import approval
    txt = approval._caption_text({"angle": "절차를 펼쳐 보인다", "headline": "h",
                                  "body": "b", "cta": "c"})
    txt.split("\n")[0].encode("cp949")      # 이번에 추가한 라벨 줄
    src = (ROOT / "content" / "copy_engine.py").read_text(encoding="utf-8")
    i = src.index("[재료 점검")
    src[i:i + 12].encode("cp949")


# ══════════════════════════════════════════════════════════════
#  18. 비대화 방지 — 조건부 주입은 프롬프트를 늘리려고 넣은 게 아니다
# ══════════════════════════════════════════════════════════════
def test_shared_fragment_did_not_grow():
    """공용 조각은 14업종 x 4프롬프트 **전부**에 붙는다. 여기가 가장 비싸다.

    이번 이식은 조각에 세 가지를 넣었다(정확성 우선 선언 · 리마커블≠자극적 ·
    인쇄된 최상급 옮겨쓰기 금지). 그래도 총량은 줄어야 한다 — 늘릴 자리가
    있으면 줄일 자리도 있다는 뜻이다."""
    pc = len((PROMPTS / "_purplecow.txt").read_text(encoding="utf-8"))
    assert pc <= 1586, f"공용 조각이 예전(1,586자)보다 커졌다: {pc}자"


def test_thin_block_is_not_sent_to_industries_that_have_facts(monkeypatch):
    """조건부 주입의 정의. 필요 없는 업종에 실리면 그냥 비대다."""
    thick = _assemble_with_facts("굿즈 도안 생성 30초~1분 / 제작 후 배송 3~7일",
                                 monkeypatch)
    for phrase in ("철회한다", "라벨이면", "쓸 축은 둘이다", "[재료 점검"):
        assert phrase not in thick, f"얇음 전용 지시가 새어 나갔다: {phrase}"


def test_accuracy_beats_remarkability_is_declared_up_front():
    """서두가 방향을 정한다.

    예전 1~3행은 "평범함은 실패다 / 답할 수 없으면 다시 써라"였다. 재료가
    13자뿐인 상태에서 '다시 써라'는 **재료를 만들어내라는 압력**이다."""
    pc = (PROMPTS / "_purplecow.txt").read_text(encoding="utf-8")
    head = pc[:pc.index("1) 1초")]
    assert "정확성을 택한다" in head
    assert "밋밋한 갈색 소가 거짓말하는 보랏빛 소보다 낫다" in head
    assert "평범함은 안전한 선택이 아니라 실패다" not in pc


def test_remarkable_is_not_the_same_as_sensational():
    """어제 사고가 정확히 '더 세게 말해서 눈에 띄기'였다.

    금지형("지어내지 마라")만으로는 방향이 안 나온다. 이 대비는 생성 방향까지
    제시한다 — 진짜 각도를 짚어라."""
    p = _assemble("band", "ad")
    assert "진짜 각도" in p
    assert "더 세게 말해서" in p
    # 자리를 바꿔 넣은 것이지 덧붙인 게 아니다.
    assert "검증 가능한 구체성" in p


def test_printed_superlatives_must_not_be_transcribed():
    """소재·서류에 인쇄돼 있어도 옮겨 적으면 안 된다.

    ⚠ 지금 카피 LLM 은 전단 이미지를 보지 않는다(orchestrator.make_caption 이
      주는 것은 registry 의 상품명뿐이다). 그러나 이 지시는 **regenerate 경로**
      에서 실제로 쓰인다 — 운영자가 승인 콘솔에서 전단에 인쇄된 문구를
      그대로 수정 요청으로 적어 넣을 수 있고, 그때 이 조각이 함께 실린다."""
    pc = (PROMPTS / "_purplecow.txt").read_text(encoding="utf-8")
    assert "인쇄돼" in pc and "옮겨 적지 마라" in pc


def test_only_regulated_profile_denies_angles():
    """무회귀: deny_angles 를 선언한 업종은 loan 뿐이어야 한다.

    다른 업종에 잘못 들어가면 그 업종의 진행 중인 소재 각도가 전부 바뀐다."""
    import profiles
    with_deny = [k for k in _ALL_PROFILES
                 if (profiles.load(k).get("copy") or {}).get("deny_angles")]
    assert with_deny == ["loan"], f"예상 밖의 업종에 deny_angles 가 있다: {with_deny}"


# ══════════════════════════════════════════════════════════════
#  19. 적대적 검증에서 나온 결함들 (2차)
#
#  전부 "재현했다 → 고쳤다" 순서로 붙은 회귀 케이스다.
# ══════════════════════════════════════════════════════════════
def test_facts_that_carry_no_usable_number_do_not_contradict_themselves(monkeypatch):
    """⚠ 재현된 결함: `if facts:` 와 `if depth:` 의 술어가 달랐다.

    facts='상담 접수부터 1차 회신까지 1~3영업일' 은 **비어 있지 않은데 depth 0**
    이다(_CLAIM_NUM_RE 가 '영업일'을 모른다). 예전 코드는 그 값을 [확인된 사실]
    로 실어 놓고 바로 아래에서 "확인된 수치가 하나도 없다"고 선언했다. 운영자가
    이 작업의 결론대로 loan.yaml 에 절차 사실을 채우면, 방금 등록한 유일한
    사실이 조용히 못 쓰는 값이 된다."""
    facts = "상담 접수부터 1차 회신까지 1~3영업일"
    assert CE.facts_depth(facts) == 0 and facts        # 전제 확인
    p = _assemble_with_facts(facts, monkeypatch)
    assert _THICK_MARK in p and facts in p
    assert "확인된 수치가 하나도 없다" not in p
    # 범위 축소('1~3영업일'→'1영업일')를 막는 레일은 facts 를 따라와야 한다.
    #   _find_unverified_numbers 는 '영업일'을 못 보므로 코드 방어도 없는 자리다.
    assert "범위로 적힌 값은 범위 그대로" in p
    assert "위에 있는 것만" in p
    # 그래도 새 수치를 지어내는 것은 여전히 막는다(depth 0 이므로 게이트는 붙는다).
    assert _THIN_MARK in p


def test_material_block_says_what_is_true_in_both_thin_cases():
    """문구 하나로 두 경우(facts 없음 / facts 는 있는데 쓸 수치가 없음)를 모두
    참으로 만든다. '확인된 수치가 하나도 없다'는 뒤쪽에서 거짓이었다."""
    for facts in ("", "상담 가능 시간 오전 9시부터"):
        blk = CE._material_block(facts, regulated=True)
        assert "이 글에 쓸 수 있는 수치가 없다" in blk


def test_regenerate_carries_the_material_block_and_the_number_guard(monkeypatch):
    """⚠ 재현된 결함: 코드 방어가 가장 얇은 경로에 프롬프트 방어도 없었다.

    regenerate() 는 _find_unverified_numbers 를 걸지 않았고(facts 를 모른다는
    이유였다) 재료 깊이 블록도 안 붙였다. 운영자가 '좀 더 구체적으로 써줘'를
    한 번 누르면 재료 0인 loan 카피에 수치가 들어와도 그대로 저장됐다.
    facts 의 실제 출처는 업종 프로필이고 그건 이 경로에도 있다."""
    monkeypatch.setattr(config, "PROFILE_FACTS", "", raising=False)
    seen = {}

    def fake(p):
        seen["p"] = p
        return '{"headline": "접수 순서를 정리했습니다", "body": "본문", "cta": "문의"}'

    CE.regenerate({"headline": "h", "body": "b", "cta": "c"}, "구체적으로", _llm=fake)
    assert _THIN_MARK in seen["p"]
    assert "수치로 만드는 구체성" in seen["p"]

    # 지어낸 수치는 저장하지 말고 운영자에게 되돌린다.
    with pytest.raises(ValueError, match="근거 없는 수치"):
        CE.regenerate({"headline": "h", "body": "b", "cta": "c"}, "구체적으로",
                      _llm=lambda _p: '{"headline": "40초 만에 끝납니다",'
                                      ' "body": "본문", "cta": "문의"}')


def test_regenerate_still_allows_numbers_that_the_profile_registered(monkeypatch):
    """무회귀: 등록된 사실은 수정 경로에서도 쓸 수 있어야 한다."""
    monkeypatch.setattr(config, "PROFILE_FACTS", "영상 생성에 걸리는 시간 1~3분",
                        raising=False)
    out = CE.regenerate({"headline": "h", "body": "b", "cta": "c"}, "구체적으로",
                        _llm=lambda _p: '{"headline": "생성은 1~3분 걸립니다",'
                                        ' "body": "본문", "cta": "문의"}')
    assert "1~3분" in out["headline"]


@pytest.mark.parametrize("angle,why", [
    ("거절된 사람도 된다는 걸 보여준다", "거절 이력"),
    ("신용점수 낮아도 상관없다는 인상을 준다", "신용상태 무관"),
    ("40대 직장인 김OO님의 후기처럼 쓴다", "지어낸 인물"),
    ("업계 유일이라는 점을 앞세운다", "순위 주장"),
    ("심사 없이 진행된다는 점을 부각한다", "무심사"),
    ("다른 곳보다 빠르다는 걸 보여준다", "부당비교"),
])
def test_illegal_angle_is_blanked_but_the_copy_survives(angle, why):
    """⚠ 재현된 결함: angle 은 어떤 검사기도 안 거치는데 승인 콘솔에서
    헤드라인 **바로 위**에, cta 와 같은 accent 색으로 그려진다.

    그 화면이 법적 게이트다. 검증되지 않은 문장을 검증된 문장과 같은 시각
    계층에 놓으면 게이트가 흐려진다 — 운영자가 그걸 소재의 기획 의도로 읽고
    승인한다. 그렇다고 검사 blob 에 넣으면 적법한 카피가 폴백으로 간다.
    → 따로 검사해 **그 줄만** 지운다."""
    import json as _json
    resp = _json.dumps({"angle": angle,
                        "headline": "접수하면 순서대로 안내드립니다",
                        "body": "무엇을 준비해야 하는지부터 알려드립니다.",
                        "cta": "어떤 쪽이 더 궁금하신가요?"}, ensure_ascii=False)
    assert CE._find_compliance_risks(angle), f"검사기가 {why} 를 잡지 못한다"
    out = CE.generate_copy(_campaign(), _profile(), max_retries=1,
                           _llm=lambda _p: resp)
    assert out["angle"] == "", "위법한 기획 의도가 승인 화면에 그대로 뜬다"
    assert out["_attempts"] == 1, "적법한 카피가 기획 메모 때문에 버려졌다"
    assert out["headline"] == "접수하면 순서대로 안내드립니다"


def test_lawful_angle_is_kept():
    """무회귀: 멀쩡한 관점까지 지우면 그 칸이 없는 것과 같다."""
    out = CE.generate_copy(_campaign(), _profile(), max_retries=1,
                           _llm=lambda _p: _OK_JSON_ANGLE)
    assert out["angle"] == "절차를 먼저 펼쳐 보인다"


@pytest.mark.parametrize("text", [
    "복잡한 담보대출도 여기서는 풀립니다",
    "막막했던 자금 문제가 정리됩니다",
    "필요한 자금을 마련해 드립니다",
    "많은 분들이 여기서 해결하셨습니다",
    # ⚠ 이 두 건은 제3자 실적 규칙만 잡는다. 다른 규칙이 우연히 덮고 있으면
    #   그 규칙을 지워도 테스트가 통과해 버린다(뮤테이션에서 실제로 그랬다).
    "여러 사장님들이 이미 진행하셨습니다",
    "많은 고객분들이 이용하셨습니다",
    "왜 안 된다고만 할까요?",
])
def test_bare_result_predicates_are_caught(text):
    """⚠ 재현된 결함: 얇음 분기가 규제 업종에 '라벨 말고 술어형으로 써라'고
    시키는데, 그 술어가 착지할 자리를 검사기가 안 보고 있었다.

    _APPROVAL_RES 의 결과 예단 규칙 둘은 **선행 명사**를 요구했다
    ('막힌…풀립니다' / '한도…해결'). 맨 '풀립니다·정리됩니다·마련해 드립니다'
    는 어떤 규칙에도 안 걸렸다 — 라벨 헤드라인을 자연스럽게 술어형으로 고쳐
    쓴 20건 중 19건이 통과했다."""
    assert CE._find_compliance_risks(text, {"compliance": {"mandatory_required": ["x"]}}), \
        f"규제 업종에서 통과하면 안 되는 문장: {text}"


@pytest.mark.parametrize("text", [
    # loan fallback_copy 가 실제로 쓰는 표현.
    "추가자금·대환·후순위까지 검토해 드립니다.",
    # 변경 후 실제로 생성된 운영 카피(읽기 전용 조회).
    "접수 후 어떤 순서로 확인이 진행되는지 정리했습니다",
    "담보 종류별로 먼저 확인하는 서류가 다릅니다",
    "무엇을 준비해야 하는지부터 알려드립니다",
    # 법정 의무표기·면책문구.
    "과도한 빚은 당신에게 큰 불행을 안겨줄 수 있습니다",
    "중개수수료를 요구하거나 받는 것은 불법입니다",
    "대출 조건은 심사 결과에 따라 달라질 수 있습니다",
])
def test_new_rules_do_not_false_block_lawful_copy(text):
    """⚠ 오차단이 더 나쁘다. 정상 문구가 막히면 매 생성이 폴백으로 간다."""
    assert not CE._find_compliance_risks(
        text, {"compliance": {"mandatory_required": ["x"]}}), \
        f"적법한 문구가 막힌다: {text}"


def test_thread_reply_preview_is_not_labeled_as_a_copy_angle():
    """⚠ 재현된 결함: threads/runner.py 가 **같은 키 이름**으로 '답글을 어떤
    각도로 달 것인가'를 저장해 왔다(실 DB 의 angle 보유 85행 중 68행이 그쪽).

    웹 UI 는 is_reply 분기 안에 뱃지를 넣어 안전했는데 텔레그램 프리뷰만
    분기가 없어, 답글 각도에 카피 관점 라벨이 붙었다."""
    import approval
    txt = approval._caption_text({"angle": "[업계] 시뮬레이션 도구로 접근하기",
                                  "reply": "답글 본문입니다"})
    assert not txt.startswith("[관점"), "답글 각도에 카피 관점 라벨이 붙는다"
    # 카피 소재는 예전대로 라벨이 붙어야 한다(무회귀).
    assert approval._caption_text(
        {"angle": "절차를 펼쳐 보인다", "headline": "h"}).startswith("[관점")


def test_web_console_badge_says_it_is_not_published():
    """법적 게이트 화면에서 관점 뱃지가 카피처럼 보이면 안 된다.

    텔레그램 프리뷰는 처음부터 '[관점 · 발행 안 됨]' 라벨을 달았는데 웹
    콘솔에만 그 표식이 없었다 — 뱃지가 헤드라인 위, cta 와 같은 accent 색이다."""
    html = (ROOT / "ui" / "approvals.html").read_text(encoding="utf-8")
    i = html.index("c.angle?")
    assert "발행 안 됨" in html[i:i + 200]


def test_facebook_content_also_points_at_the_material_section():
    """다리 문장이 한 파일만 빠져 있었다. 네 파일 다 '구체적인 하나'를 요구한다."""
    for name in ("band_ad.txt", "kakao_ad.txt", "facebook_ad.txt",
                 "facebook_content.txt"):
        text = (PROMPTS / name).read_text(encoding="utf-8")
        assert "맨 아래 재료 항목이 정한다" in text, f"{name}: 다리 문장 없음"


def test_thin_block_did_not_grow():
    """⚠ 조건부 주입은 프롬프트를 늘리려고 넣은 게 아니다.

    1차 이식은 얇음 블록이 360자였고 그게 11업종에 통째로 실렸다. 지금은
    공통 두 줄만 전 업종, loan 형 두 줄은 규제 업종에만 간다."""
    common = len(CE._material_block("", regulated=False))
    reg = len(CE._material_block("", regulated=True))
    assert common <= 200, f"비규제 업종 얇음 블록이 {common}자다(예전 360자)"
    assert reg <= 360, f"규제 업종 얇음 블록이 {reg}자다"
