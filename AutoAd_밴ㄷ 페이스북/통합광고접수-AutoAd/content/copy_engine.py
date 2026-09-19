# ============================================================
#  content/copy_engine.py — 광고 카피 생성  (P1-1)
#  이식: Sns 자동화/claude_engine.py (generate/regenerate 패턴)
#  확장: 채널별 프롬프트(band/facebook/kakao) + 금칙어 가드 재생성 루프
#  · Anthropic 은 지연 import (키 없이도 목으로 로직 검증 가능)
# ============================================================
import json
import re
import unicodedata
import urllib.request
import zlib
from pathlib import Path
import config

PROMPT_DIR = Path(__file__).parent / "prompts"

# 금칙어는 업종 프로필(profiles/*.yaml)에서 온다.
# 대출=확정·과장 표현 금지, 미용=의료 표현 금지 … 업종마다 다르다.
BANNED_PHRASES = config.BANNED_PHRASES

# 자리표시자는 {소문자_식별자} 형태만 인식한다.
# JSON 출력 예시의 {"headline": ...} 는 여는 중괄호 뒤가 따옴표라 매치되지 않는다.
# ⚠ 과거엔 허용 키를 손으로 나열했는데, 새 프롬프트가 {brand_site} 를 쓰자
#   목록에 없어 치환이 안 됐고 → LLM 이 빈칸을 'Midjourney' 로 지어냈다(실측).
#   목록을 유지보수하는 대신 '있는 값은 전부 치환, 없는 키는 오류'로 바꾼다.
_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def _prompt_file(channel: str, form: str = "ad") -> Path:
    """실제로 읽히는 프롬프트 파일.

    ⚠ 요청한 form 과 읽히는 파일이 다를 수 있다. band/kakao 는 콘텐츠형
      프롬프트가 없어 form='content' 여도 광고형(band_ad.txt)으로 대체된다.
      '콘텐츠형 전용' 조각을 붙일지는 form 이 아니라 **이 파일 이름**으로
      판단해야 한다(광고형에 붙이면 CTA 규칙과 정면으로 충돌한다)."""
    for name in (f"{channel}_{form}.txt", f"{channel}_ad.txt", "band_ad.txt"):
        p = PROMPT_DIR / name
        if p.exists():
            return p
    raise FileNotFoundError(f"프롬프트 파일 없음: {channel}/{form}")


def _load_prompt(channel: str, form: str = "ad") -> str:
    """form: ad(광고형) | content(콘텐츠형)

    콘텐츠형은 '결과물을 나누는 글'이다. 홍보를 금지하지 않지만 주제를 지켜야 하는
    모임(topic_only)이나 규정이 없는 모임(unknown)에 쓴다.
    광고형 배너를 그런 곳에 올리면 승인 대기에 걸리거나 규칙 위반이 된다(실측)."""
    return _prompt_file(channel, form).read_text(encoding="utf-8")


_SHARED_CACHE = {}

# 없으면 **조용히 넘어가면 안 되는** 조각.
#   이 조각들은 창의성 조언이 아니라 위법 방지 레일을 담고 있다. 파일이
#   사라지면 예전 코드는 빈 문자열을 돌려주고 generate_copy 가 정상 반환했다
#   (실측: 예외도 경고도 폴백도 없이 레일 없는 프롬프트가 그대로 나갔다).
#   배포 누락·git clean·패키징 실수 어느 경로로도 발생하고 징후가 전혀 없다.
#   → 여기 이름이 있으면 없을 때 터진다. 터지면 orchestrator 가 폴백 캡션을 쓴다.
_REQUIRED_SHARED = {"_purplecow.txt", "_permission.txt", "_compliance_rail.txt"}


def _load_shared(name: str) -> str:
    """모든 프롬프트가 함께 쓰는 조각(_로 시작하는 파일).

    ⚠ 자리표시자 치환({key})을 거치지 않는다. 업종·채널과 무관한 '기준'만
      여기에 둔다. 값이 필요한 문장은 각 프롬프트 파일에 적을 것.
    """
    if name not in _SHARED_CACHE:
        p = PROMPT_DIR / name
        if not p.exists():
            if name in _REQUIRED_SHARED:
                raise FileNotFoundError(
                    f"필수 프롬프트 조각 없음: {p} — 규제 레일이 빠진 채로 "
                    "광고를 만들 수 없다.")
            _SHARED_CACHE[name] = ""
        else:
            _SHARED_CACHE[name] = p.read_text(encoding="utf-8")
    return _SHARED_CACHE[name]


def _fill(template: str, campaign: dict, profile: dict) -> str:
    """{key} 자리표시자 치환 (str.format 미사용 — JSON 예시 중괄호 보호).

    프롬프트가 요구한 키가 아예 없으면 예외를 던진다.
    빈 프롬프트 구멍을 LLM 이 그럴듯하게 메우는 사고를 막기 위해서다."""
    src = {
        # 업종별 금칙어·주의사항을 프롬프트에 주입 → 프롬프트 파일은 업종 중립 유지
        "banned": ", ".join(f'"{b}"' for b in BANNED_PHRASES) or "(없음)",
        "industry_note": config.COMPLIANCE_NOTE,
        **campaign, **profile,
    }
    missing = []

    def _sub(m):
        key = m.group(1)
        if key not in src:
            missing.append(key)
            return m.group(0)
        return str(src[key] if src[key] is not None else "")

    out = _PLACEHOLDER_RE.sub(_sub, template)
    if missing:
        raise KeyError(f"프롬프트 자리표시자에 넣을 값이 없음: {sorted(set(missing))}")
    return out


def _extract_json(raw: str) -> dict:
    """LLM 응답에서 JSON 객체 추출 (코드펜스/앞뒤 잡텍스트 허용)."""
    if not raw:
        raise ValueError("빈 응답")
    text = raw.strip()
    # ```json ... ``` 펜스 제거
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # 첫 { ~ 마지막 } 사이 추출
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"JSON 없음: {raw[:120]!r}")
    return json.loads(text[start:end + 1])


def _norm(text: str) -> str:
    """비교 전용 정규화 — 전각·호환문자를 접고 연속 공백을 하나로 줄인다.

    ⚠ 공백을 **지우지는** 않는다. 한 낱말 금칙어에서 공백을 지우면
      '업무 조건' → '업무조건' 이 '무조건' 에 걸려 정상 문구가 차단된다.
      공백을 지운 형태는 _find_banned 에서 **여러 낱말 금칙어에만** 쓴다.
    """
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or ""))


def _find_banned(text: str, extra=None) -> list:
    """포함된 금칙어 목록(없으면 빈 리스트).

    ⚠ 예전에는 `b in text` 단순 포함 검사였다. 표기만 살짝 바꾸면 그대로
      새어 나갔다(실측 2026-08-10):
        '１００% 승인'(전각 숫자) → 통과
        '100%  승인'(공백 두 개)  → 통과
      → NFKC 로 접고 공백을 하나로 줄인 뒤 비교한다. 여러 낱말로 된
        금칙어는 공백을 아예 지운 형태('승인보장')까지 본다.

    ⚠ 조사가 끼어든 형태('승인을 보장합니다')는 여기서 못 잡는다.
      목록을 늘려 막을 수 있는 종류가 아니라서 정규식 검사기
      (_find_approval_claims)로 따로 뺐다.
    """
    banned = BANNED_PHRASES + list(extra or [])
    raw = text or ""
    norm = _norm(raw)
    tight = norm.replace(" ", "")
    hits = []
    for b in banned:
        nb = _norm(b)
        if b in raw or nb in norm:
            hits.append(b)
        elif " " in nb and nb.replace(" ", "") in tight:
            hits.append(b)
    return hits


# ── 지어낸 후기·평점·인물 ────────────────────────────────────
# 2026-08-10 실측: 운영자가 확보한 광고 이미지 중 아래가 **위법 판정**돼 제외됐다.
#     "★5 고객 후기 4건", "40대 직장인 김OO님"
# 금칙어 목록으로는 못 막는다 — 이름·나이·별점을 매번 다르게 지어내기 때문이다.
# 실측 결과 기존 가드(_find_banned/_find_foreign/_find_unverified_numbers)는
# 이 네 문장 중 셋을 놓쳤다(★는 허용 기호 범위 안, \u7121는 한자 범위 안,
# '40대'는 수치 단위에 해당 없음).
#
# ⚠ '후기' 라는 낱말 자체는 막지 않는다. 콘텐츠형 글과 각도 0("직접 써 본
#   사람의 후기처럼")에서 정상적으로 쓰이는 말이다. 막는 것은 **제3자 후기를
#   인용한 형태**(고객/실제/이용 후기, 별점, 지어낸 인물)뿐이다.
# ⚠ 별점 기호를 _FOREIGN_SCRIPT_RE 로 막으려 하지 마라. 그 범위(℀-➿)를
#   좁히면 화살표·기호가 전부 막혀 14업종 카피가 대량 폴백된다.
# ⚠ 기호·문자범위는 반드시 \uXXXX 이스케이프로 쓴다(파일 상단 경고와 같은 이유 —
#   문자를 그대로 넣으면 편집·인코딩을 거치며 뭉개져 import 불가가 된다).
#     ★ 검은 별 / ☆ 흰 별 / ⭐ 별 이모지
#     ○ 흰 동그라미 / 가-힣 한글 음절
_STAR = "\u2605\u2606\u2b50"   # ★ ☆ ⭐ 별점 기호
_HAN = "\uac00-\ud7a3"       # 한글 음절
# 이름 가림 기호. ○ ◯ △ ▽
# ⚠ 전각 Ｏ(U+FF2F)는 여기 넣지 않는다 — _find_fake_testimonial 이
#   _norm(NFKC) 을 먼저 걸어 반각 O 로 접기 때문이다
#   (실측: 접기 전에는 '김Ｏ Ｏ님' 이 그대로 통과했다).
_CIRC = "\u25cb\u25ef\u25b3\u25bd"             # ○ 흰 동그라미 (김○○님)
# 후기를 '요청'하는 문장까지 막으면 안 된다.
#   _permission.txt(허락자산 지침)가 "답이 오는 글로 끝내라"고 시키는데,
#   그 가장 자연스러운 형태가 "고객 후기가 궁금하시면 댓글 남겨주세요" 다.
#   후기를 **인용**한 것이 아니라 **요청**한 것이므로 위법이 아니다.
#   실측: 예전 규칙은 비규제 업종에서 이 문장을 막아 폴백으로 보냈다.
_ASK = (r"(?![^.\n]{0,12}(?:궁금|남겨|남기|알려\s*주|여쭈|보내\s*주|부탁"
        r"|있으신|계신|주세요|기다립))")
_TESTIMONIAL_RES = [
    # ⚠ 별 두 개까지는 한국어 광고에서 흔한 불릿이다(실측: '★★ 이번 주 소식').
    #   별점으로 읽히는 건 세 개부터다. 거짓 차단이 더 비싸다.
    (re.compile(rf"[{_STAR}]{{3,}}"),                           "별점 표시"),
    # '★5' 는 별점, '★ 3가지' 는 불릿이다. 숫자 뒤에 한글이 붙으면 불릿으로 본다.
    (re.compile(rf"[{_STAR}]\s*[1-5](?![{_HAN}])"),             "별점 표시"),
    (re.compile(rf"[1-5]\s*[{_STAR}]"),                         "별점 표시"),
    (re.compile(rf"[{_STAR}]\s*(?:후기|평점|평가|리뷰)"),        "별점 표시"),
    (re.compile(r"(?:별점|평점)\s*\d"),                         "평점 인용"),
    (re.compile(r"\d\s*점\s*(?:만점|/\s*5)"),                   "평점 인용"),
    (re.compile(r"별\s*(?:다섯|넷|네|셋|세)\s*개"),              "평점 인용"),
    (re.compile(rf"(?:고객|실제|이용자?|사용자|방문자|생생한)\s*후기{_ASK}"),
                                                                "제3자 후기 인용"),
    (re.compile(r"후기\s*\d+\s*건"),                            "제3자 후기 인용"),
    (re.compile(r"(?:실제|고객)\s*(?:상담|이용|구매)?\s*사례"
                r"(?:입니다|예요|를\s*소개|를\s*공유|가\s*있)"),  "제3자 후기 인용"),
    # 제3자의 말을 옮기는 형태. "이용하신 분의 이야기", "상담받으신 분이 이렇게…"
    # ⚠ 뒤에 '말·이야기·후기' 같은 인용 표지가 붙을 때만 잡는다.
    #   "이용하신 분은 아래 링크로" 같은 정상 안내를 막으면 안 된다.
    (re.compile(r"(?:이용|상담|구매|사용)\s*(?:하신|받으신|해\s*보신)\s*분"
                r"[^.\n]{0,12}(?:말씀|말했|이야기|후기|사례|만족|추천|소감)"),
                                                                "제3자 후기 인용"),
    (re.compile(r"(?:고객|이용자|회원|손님)[^.\n]{0,10}(?:이렇게|이런)\s*말"),
                                                                "제3자 후기 인용"),
    # '40대 직장인' 형태. 나이+직업은 지어낸 후기 인물의 상투구다.
    # ⚠ 인용 표지(님·씨·말·만족…)가 함께 있을 때만 잡는다. 나이+직업만으로
    #   막으면 '누구 한 사람에게 말하라'가 시키는 대상 서술까지 막힌다 —
    #   "40대 직장인이라면 이 상황 아실 겁니다" 는 후기가 아니라 청중 묘사다.
    (re.compile(r"\d0\s*대\s*(?:직장인|주부|자영업자|사장님|아버님|어머님|가장)"
                r"[^.\n]{0,12}(?:님|씨|말씀|말했|후기|사례|만족|추천|소감|쓰고)"),
                                                                "지어낸 인물"),
    # '김OO님' / '박○○님' / '김O O님'(전각을 NFKC 로 접은 뒤).
    # ** 는 넣지 않는다 — '**고객**님' 이 걸린다.
    (re.compile(rf"[{_HAN}]\s*(?:[Oo{_CIRC}Xx]\s*){{2}}님"),      "지어낸 인물"),
    (re.compile(rf"[{_HAN}]\s*[{_CIRC}O]{{1,2}}\s*씨"),           "지어낸 인물"),
    # 익명 예시 이름. 광고 본문에 나오면 언제나 지어낸 사람이다.
    (re.compile(r"홍길동|김철수|이영희"),                        "지어낸 인물"),
]


def _find_fake_testimonial(text: str) -> list:
    """지어낸 후기·평점·인물을 잡아낸다(전 업종 공통).

    표시광고법 제3조(거짓·과장), 제5조(실증책임) 대상이다. 광고주는 그 상품을
    쓴 당사자가 아니므로 이 화법은 업종을 가리지 않고 언제나 거짓이다.

    ⚠ _norm(NFKC) 을 먼저 건다. 걸지 않으면 전각 표기가 그대로 새어 나간다
      (실측: '김Ｏ Ｏ님' 통과). _find_banned 는 정규화를 받았는데 이 검사기만
      못 받아 생긴 구멍이었다."""
    src = _norm(text)
    seen, bad = set(), []
    for rx, label in _TESTIMONIAL_RES:
        m = rx.search(src)
        if m and label not in seen:
            seen.add(label)
            bad.append(f"{label}: {m.group(0).strip()}")
    return bad


# ── 순위·서열 주장 ───────────────────────────────────────────
# '업계 최초' 는 그 자체가 실증책임 대상(표시광고법 제5조)이다.
# 14업종 중 11개는 facts 가 비어 있어 실증자료가 아예 0이다.
# ⚠ 여기서는 **명백한 형태만** 잡는다. 맨 '최초'(예: "최초 1회 상담")까지
#   막으면 거짓 차단이 난다. 나머지는 _purplecow.txt 의 금지 지시가 맡는다.
#
# ⚠ 조사 하나에 뚫리면 안 된다. 예전 규칙은 두 낱말이 **붙어 있을 때만** 잡아
#   '업계에서 유일하게', '이 지역에서 유일하게' 가 전부 통과했다(실측).
#   _find_banned 가 이미 겪은 것과 같은 실패 유형이다 → 조사를 허용한다.
_SUPERLATIVE_RE = re.compile(
    r"(?:업계|국내|세계|전국|시장|지역|동종|권역)(?:\s*\S{0,3})?\s*"
    r"(?:최초|최고|최대|최다|최상|유일|1\s*위|일\s*위|넘버\s*원|제일)"
    r"|유일(?:한|하게)\s*(?:곳|업체|서비스|브랜드|제품|방법|기술)"
    r"|(?:판매|매출|점유율|만족도)\s*(?:1\s*위|최상|최고)"
    r"|최초로\s*(?:선보|출시|도입|시작|공개)"
    # 비교 최상급. '가장 먼저 확인하세요' 같은 안내문은 막지 않도록
    # **우위를 주장하는 서술어**가 붙을 때만 잡는다.
    r"|(?:가장|제일)\s*(?:빠른|빠릅니다|빠르게|저렴|싼|많은)"
    r"|(?:가장|제일)\s*먼저\s*(?:시작|도입|선보|만들|내놓)"
    r"|최저\s*(?:수준|금리|요금|가격|비용)"
)

# 규제 업종 전용 — '최초·유일·1위' 는 통째로 막는다.
#   '대구 최초' 처럼 지역명을 앞세우면 위 규칙을 피해 가는데(실측), 지역명을
#   열거하기 시작하면 목록이 끝없이 브리틀해진다. 대부중개 광고에 '최초·유일'
#   이 정당하게 쓰일 자리는 없으므로 규제 업종에서는 낱말째로 금지한다.
#   ⚠ '최초 1회 상담' 같은 순서 표현만 예외로 둔다(숫자가 바로 뒤에 온다).
_SUPERLATIVE_STRICT_RE = re.compile(
    r"최초(?!\s*\d)|유일|1\s*위|최다|넘버\s*원|최상위"
)


def _find_superlatives(text: str, strict: bool = False) -> list:
    src = _norm(text)
    m = _SUPERLATIVE_RE.search(src)
    if not m and strict:
        m = _SUPERLATIVE_STRICT_RE.search(src)
    return [f"근거 없는 순위·서열 주장: {m.group(0).strip()}"] if m else []


# ── 부당비교 (전 업종) ───────────────────────────────────────
# 표시광고법 제3조(부당비교)·제5조(실증책임)는 업종을 가리지 않는다.
# 이 검사기가 필요한 이유는 이번 개편이 만든 위험 때문이다 — 공용 조각이
# "업계에서 다들 하는 방식이 있으면 반대로 해 봐라"라고 시키는데, 그 지시의
# 가장 흔한 착지점이 "다른 곳은 X 합니다. 저희는 —" 이다(실측 10/10 통과).
# 프롬프트 울타리는 부탁이고 이 검사는 강제다.
_COMPARE_RES = [
    (re.compile(r"(?:다른\s*[가-힣]{0,6}(?:곳|업체|데|회사|브랜드|서비스|중개|업소)"
                r"|타사|타\s*업체|경쟁사|남들|시중|은행|동종\s*업계)"
                r"\s*(?:보다|과\s*달리|와\s*달리|랑\s*달리|에\s*비해)"),
     "타사 비교 우위 주장"),
    (re.compile(r"(?:다른\s*(?:곳|업체|데|회사)|타사|남들|다들|보통은|대부분은)"
                r"[^\n]{0,40}(?:저희는|우리는|여기는|저희가|우리가)"),
     "타사 대비 서술(부당비교)"),
    (re.compile(r"(?:곳|업체|서비스|브랜드)(?:은|는|이|가)?\s*"
                r"(?:흔치\s*않|드뭅니다|드문|찾기\s*어렵|저희뿐|우리뿐)"),
     "희소성 주장(실증 대상)"),
]


def _find_unfair_comparison(text: str) -> list:
    return _scan(text, _COMPARE_RES)


# ── 승인·심사 예단 (규제 업종 전용) ──────────────────────────
# 대부업법 제9조의2, 금융소비자보호법 제22조.
# ⚠ 이 검사는 **의무표기를 선언한 업종에만** 적용한다. 그 표시가 곧
#   '법정 광고규제 대상'이라는 뜻이고, 지금은 loan 만 갖고 있다.
#   전 업종에 걸면 "예약 가능합니다" 같은 정상 문구가 대량으로 막힌다.
# 실측(2026-08-10): 아래 형태가 기존 금칙어 목록을 전부 통과했다.
#   '연체자도 가능합니다' / '신용점수 낮아도 진행됩니다' /
#   '다른 곳에서 거절되신 분도 상담 가능합니다' / '심사 없이 바로 진행' /
#   '승인을 보장합니다'(조사 삽입) / '신용평점 나빠도 상관\u7121'
# ⚠ '어렵다·불가하다'라고 정직하게 알리는 문장까지 막으면 안 된다.
#   실측: "연체 이력이 있으면 상담이 어려울 수 있습니다" 가 차단됐다.
#   막아야 할 것은 '된다'는 쪽이지 '안 된다'는 쪽이 아니다.
_NEG = r"(?![^.\n]{0,14}(?:어렵|어려|불가|제한|않습니다|안\s*됩|아닙니다))"
_APPROVAL_RES = [
    (re.compile(r"연체\s*(?:자|중|이력)[^.\n]{0,10}"
                r"(?:가능|됩니다|해\s*드|상담|진행|신청)" + _NEG),
     "연체 관련 확정·가능 표현"),
    (re.compile(r"(?:신용|점수|등급|평점)[^.\n]{0,12}"
                r"(?:낮아도|낮으셔도|나빠도|안\s*좋아도|상관\s*없|상관\s*無|무관|관계\s*없)"),
     "신용상태 무관 암시"),
    # 처지를 가리키는 **명사형** 대상 지칭. 예전 규칙은 부사형('낮아도')만 봐서
    # '저신용도 상담 가능합니다' / '무직이어도 괜찮습니다' 가 전부 통과했다(실측).
    (re.compile(r"(?:저신용|신용회복|개인회생|파산|무직|소득\s*증빙|일용직|프리랜서)"
                r"[^.\n]{0,12}(?:가능|됩니다|해\s*드|환영|괜찮|상담|진행|신청|분|고객)"
                + _NEG),
     "처지 지칭(대상 차별·승인 암시)"),
    (re.compile(r"(?:직장|소득|수입|재직|담보|보증인?)\s*"
                r"(?:없이|없어도|없으셔도|안\s*계셔도)"),
     "자격 요건 무관 암시"),
    # 금칙어 목록의 조사·공백 우회. '누구나 가능' 은 목록에 있는데
    # '누구나 다 가능합니다' / '누구든 대출 가능' 은 통과했다(실측).
    (re.compile(r"누구(?:나|든|라도)\s*(?:다\s*)?(?:가능|대출|승인|신청|받으)"),
     "대상 무제한 암시"),
    (re.compile(r"묻지\s*마"),
     "무심사 암시"),
    # 1인칭 체험담. 광고주는 그 상품을 쓴 당사자가 아니다.
    #   ⚠ 규제 업종에만 건다. 콘텐츠형 글(비규제)은 실제로 만들어 본 사람이
    #     쓰는 글이라 "써 보니" 가 정상 화법이다.
    (re.compile(r"(?:써|해|받아|이용해|접수해|겪어|맡겨)\s*보니"
                r"|제가\s*(?:직접|한번|해|써)"
                r"|저(?:도|는)\s*(?:됐|받았|해\s*봤|써\s*봤)"),
     "1인칭 체험담(광고주는 당사자가 아니다)"),
    (re.compile(r"거절\s*(?:되신|당하신|된|났던|이력|경험|기록)"
                r"[^.\n]{0,10}(?:분|고객|경우|건|도|만|있으신|환영)"),
     "거절 이력 언급(승인 암시)"),
    # 서술형('심사가 없습니다')과 절차 부정('서류 없이', '확인 절차를 뺐')까지 본다.
    #   '반대로 해 봐라'(실행 지침 6)가 규제 업종에서 가장 먼저 착지하는 자리다.
    #   실측: 예전 규칙은 부사형·관형형만 봐서 '심사가 없습니다' 가 통과했다.
    (re.compile(r"심사\s*(?:절차\s*)?(?:가|는|를)?\s*"
                r"(?:없이|없는|없습|없다|안\s*하|안\s*합|생략|면제|불필요)"
                r"|無\s*심사|심사\s*無|(?<![가-힣])무\s+심사"),
     "무심사 암시"),
    # ⚠ '무 조건'(공백 삽입)은 _find_banned 가 못 잡는다 — 한 낱말 금칙어에
    #   공백 제거를 걸면 '업무 조건'·'의무 조건'이 14업종에서 전부 막힌다.
    #   앞에 한글이 붙지 않은 '무 조건' 만 잡아 그 거짓 차단을 피한다.
    (re.compile(r"(?<![가-힣])무\s+조건"),
     "확정 표현(무조건)"),
    (re.compile(r"(?:서류|절차|확인|증빙|검토)[^.\n]{0,6}"
                r"(?:없이|생략|면제|뺐|빼고|안\s*받)"),
     "절차 부정(무심사 암시)"),
    (re.compile(r"심사(?:는|가)?\s*(?:나중|이후|뒤로|천천히)"),
     "심사 순서 부정"),
    # ⚠ 맨 '확정' 을 막으면 "상담 확정 후 안내" 같은 정상 문구가 걸린다(실측).
    #   결과를 약속하는 서술어가 붙을 때만 잡는다.
    (re.compile(r"(?:승인|한도|금리|대출)[^.\n]{0,4}"
                r"(?:보장|확정해|확정됩|확정드|확정\s*지)"),
     "승인·한도 보장"),
    (re.compile(r"(?:승인|통과)\s*(?:율|확률|가능성)|전원\s*승인|모두\s*승인"),
     "승인 확률 주장"),
    (re.compile(r"(?:조회|대출)\s*기록\s*(?:無|없음|없이)"),
     "조회기록 관련 확정 표현"),
    (re.compile(r"(?:막힌|막혔던)[^.\n]{0,10}(?:풀립니다|풀려|해결됩니다)"),
     "결과 예단"),
    # '대환으로 해결됩니다' / '후순위까지 가능합니다' — 상품을 결과로 약속한다.
    #   ⚠ '검토해 드립니다' 는 막지 않는다(loan fallback_copy 가 쓰는 표현이다).
    (re.compile(r"(?:대환|추가자금|후순위|한도|자금)[^.\n]{0,6}"
                r"(?:해결|풀립|풀려|가능합니다|가능해|됩니다)"),
     "결과 예단"),
    # 앞의 두 규칙은 둘 다 **선행 명사**를 요구한다('막힌…풀립니다',
    #   '한도…해결'). 그래서 맨 '풀립니다 · 정리됩니다 · 마련해 드립니다' 는
    #   전부 통과했다(실측: 라벨 헤드라인을 술어형으로 자연스럽게 고쳐 쓴
    #   20건 중 19건 미탐). 얇음 분기가 규제 업종에 "라벨 대신 문장으로 써라"
    #   라고 시키는 이상, 그 술어가 착지할 수 있는 자리를 열어 두면 안 된다.
    #   ⚠ '검토해 드립니다'·'정리했습니다'(우리가 한 일 서술)는 건드리지
    #     않는다 — loan fallback_copy 와 실제 운영 카피가 쓰는 표현이다.
    #   ⚠ 맨 '해결해 드립니다' 는 넣지 않는다. 저장된 소재 122건을 새 규칙으로
    #     다시 훑자 걸린 것이 **"궁금증을 해결해 드립니다"** 였다(id 137·138).
    #     그건 상담 안내이지 결과 약속이 아니다. 위험한 쪽('자금 문제를
    #     해결해…')은 바로 위 규칙이 목적어로 이미 잡는다. 오차단은 매 생성을
    #     폴백으로 보내므로 미탐보다 비싸다.
    (re.compile(r"풀립니다|풀렸|풀려\s*(?:납|드)"
                r"|정리됩니다|정리돼|정리되었"
                r"|해결(?:하셨|되셨)"
                r"|마련해\s*(?:드립|드렸|드릴)"),
     "결과 예단(절차가 아니라 결과)"),
    # 제3자 실적 주장. 실증책임(표시광고법 제5조) 대상인데 검사기에도
    #   프롬프트에도 없었다. 실측: '많은 분들이 여기서 해결하셨습니다' 통과.
    (re.compile(r"(?:많은|여러|수많은|다수의)\s*(?:분|고객|사장님|사람)(?:들)?"
                r"[^.\n]{0,12}(?:해결|받으셨|받았|성공|승인|이용하셨|진행하셨)"),
     "제3자 실적 주장(실증 불가)"),
    (re.compile(r"(?:신용|한도|심사|승인|자격)[^.\n]{0,8}걱정"
                r"[^.\n]{0,8}(?:없|마세요|마시|접어|덜)"),
     "결과 예단(걱정 마라)"),
    # '왜 안 되는데?'(실행 지침 8)가 그대로 문장이 된 형태.
    # ⚠ '되'(U+B418)만 보던 규칙은 '왜 안 된다고만 할까요?'(U+B41C)를 놓쳤다.
    (re.compile(r"(?:누가\s*정했|왜\s*안\s*(?:되|된|돼|됐)|안\s*된다고\s*누가)"),
     "관행 부정 수사(승인 암시)"),
    (re.compile(r"(?:안\s*된다|어렵다|불가능)[^.\n]{0,12}"
                r"(?:저희는|우리는|여기(?:는|서는))[^.\n]{0,8}(?:됩니다|가능|해\s*드)"),
     "관행 부정 수사(승인 암시)"),
]

# ── 처지로 좁히기 (규제 업종 전용) ───────────────────────────
# '누구 한 사람에게 말하라'는 좁히라고 시킨다. 규제 업종에서 그 좁히기가
# 상황이 아니라 **처지**로 흐르면 그대로 위법이다(대부업법 제9조의2).
# _purplecow.txt 가 "처지로 좁히지 마라"라고 적어 두었지만 그건 부탁이고,
# 각도 6("공감할 상황 하나를 먼저 그리며")이 loan 에서 이 방향을 직접 유도한다.
_TARGETING_RES = [
    (re.compile(r"(?:신용\s*(?:점수|등급)|평점)\s*\d+\s*(?:점|등급)?\s*"
                r"(?:대|이하|미만|아래|초반)"),
     "신용상태로 대상 좁힘"),
    (re.compile(r"\d\s*등급\s*(?:이하|미만|아래)"),
     "신용상태로 대상 좁힘"),
    # ⚠ _NEG 를 붙인다. "연체 중이신 경우 진행이 어렵습니다" 처럼 정직하게
    #   안 된다고 알리는 문장까지 막으면 loan 은 아무 말도 못 한다(실측).
    (re.compile(r"(?:연체|밀린|밀려|밀리신|마이너스|잔고|카드값|월세|공과금)"
                r"[^.\n]{0,12}(?:분|사장님|고객|님께|이신|계신)" + _NEG),
     "경제적 곤궁으로 대상 좁힘"),
]


def _is_regulated(profile: dict = None) -> bool:
    """법정 광고규제 업종인가.

    판별 기준은 프로필이 `compliance.mandatory_required` 를 선언했는가다.
    그 목록이 있다는 건 법이 광고에 실을 항목을 정해 뒀다는 뜻이다.
    선언하지 않은 업종에는 아래 검사가 붙지 않는다(무회귀)."""
    prof = profile if profile is not None else (getattr(config, "PROFILE", None) or {})
    return bool((prof.get("compliance") or {}).get("mandatory_required"))


def _scan(text: str, rules) -> list:
    src = _norm(text)
    seen, bad = set(), []
    for rx, label in rules:
        m = rx.search(src)
        if m and label not in seen:
            seen.add(label)
            bad.append(f"{label}: {m.group(0).strip()}")
    return bad


def _find_approval_claims(text: str) -> list:
    """승인·심사·결과 예단 (규제 업종 전용)."""
    return _scan(text, _APPROVAL_RES) + _scan(text, _TARGETING_RES)


def _find_compliance_risks(text: str, profile: dict = None) -> list:
    """'리마커블하게 쓰라'는 지시가 위법으로 넘어간 지점을 잡아낸다.

    프롬프트는 지키라는 부탁이고 이 검사는 강제다. 2026-08-10 사고 이후
    프롬프트에 레일을 넣었지만, 프롬프트만으로는 재발을 막을 수 없다.

    ⚠ profile 인자는 **업종 프로필**(profiles/*.yaml)이지 채널 dict 가 아니다.
      생략하면 프로세스에 굳어 있는 config.PROFILE 을 본다 — 프로세스당 업종은
      하나뿐이라 그게 맞는 값이다. 인자는 테스트·명시적 판별용이다.

    전 업종 공통(표시광고법 제3조·제5조):
      지어낸 후기 / 순위·서열 주장 / 부당비교.
    규제 업종 전용(대부업법 제9조의2, 금소법 제22조):
      승인·심사 예단 / 처지로 대상 좁히기 / '최초·유일·1위' 통짜 금지."""
    reg = _is_regulated(profile)
    bad = (_find_fake_testimonial(text)
           + _find_superlatives(text, strict=reg)
           + _find_unfair_comparison(text))
    if reg:
        bad += _find_approval_claims(text)
        bad += _find_fake_brand(text, profile)
    return bad


# 회사 이름처럼 읽히는 꼬리표. 앞에 한글 2자 이상이 붙어 있어야 이름으로 본다
# ('주식회사' 단독, '대부중개업 등록번호' 같은 일반어를 잡지 않기 위해서다).
# ⚠ '론' 뒤에 부정형 전방탐색을 두면 안 된다. 한국어는 조사가 붙는다 -
#   '헤드림론에서' 는 뒤가 한글이라 그대로 빠져나간다(실측). 대신 아래
#   _NOT_BRAND_RON 으로 일반어를 걸러낸다.
_BRANDISH_RE = re.compile(
    r"[가-힣A-Za-z0-9]{2,}(?:주식회사|컴퍼니|홀딩스|파이낸셜|캐피탈|대부중개|저축은행)"
    r"|(?:㈜|\(주\))\s*[가-힣A-Za-z0-9]{2,}"
    r"|[가-힣]{2,}론")

# '…론' 으로 끝나지만 회사 이름이 아닌 흔한 낱말. 광고 문구에 실제로 나온다.
_NOT_BRAND_RON = frozenset((
    "물론", "결론", "이론", "여론", "서론", "본론", "총론", "각론", "반론",
    "토론", "추론", "공론", "정론", "언론", "방법론", "원론", "개론", "지론",
))


def _find_fake_brand(text: str, profile: dict = None) -> list:
    """등록 상호가 아닌 **회사 이름을 지어낸** 경우를 잡는다.

    ⚠ 규제 업종(대부)에서만 돈다. 대부광고는 등록된 상호로만 할 수 있으므로,
      없는 상호가 실리면 문구 품질 문제가 아니라 법 위반이다.

    실측 사고(2026-08-11): 업종 note 에 '상호를 본문에 남겨라'라고만 적고
      **어떤 상호인지 적지 않았더니** 모델이 빈칸을 지어냈다 -
      '에이치디컴퍼니', '헤드림론', '한국대부중개 주식회사' 세 건. note 는
      고쳤지만 프롬프트는 부탁이고 이 검사가 강제다(_find_compliance_risks 주석).

    ⚠ 등록 상호 자체와 그 조각은 통과시킨다. '(주)더스틴홀딩스대부중개' 는
      '더스틴홀딩스', '홀딩스대부중개' 처럼 부분만 적히기도 한다.
    """
    brand = ""
    try:
        p = profile if isinstance(profile, dict) else config.PROFILE
        brand = str(((p or {}).get("brand") or {}).get("company") or "")
    except Exception:
        brand = ""
    if not brand:
        brand = str(getattr(config, "BRAND_COMPANY", "") or "")
    bnorm = "".join(brand.split()).replace("(주)", "").replace("㈜", "")

    out = []
    for m in _BRANDISH_RE.finditer(text or ""):
        tok = m.group(0).strip()
        t = "".join(tok.split()).replace("(주)", "").replace("㈜", "")
        if not t or len(t) < 3:
            continue
        if bnorm and (t in bnorm or bnorm in t):
            continue                      # 등록 상호(또는 그 조각)
        if t.endswith("론") and t in _NOT_BRAND_RON:
            continue                      # 물론·결론 같은 일반어
        out.append(f"등록되지 않은 상호로 읽히는 표현: {tok}")
    return out


# 문구에 나와도 되는 주소 = 우리 것뿐이다.
_URL_RE = re.compile(r"\b(?:https?://)?([a-z0-9][a-z0-9.-]*\.(?:com|net|org|io|ai|app|kr|co\.kr))",
                     re.I)


# 한국어 광고 문구에 나올 수 있는 문자만 허용한다.
#   한글 / 한자 / 가나 / 라틴·숫자·기호 / 이모지 — 그 밖의 문자체계는 LLM 이
#   흘린 것이다. 실측 사고: "눈이 ఎక్కువగా 가는 편입니다" (텔루구 문자 혼입).
#   금칙어 목록으로는 못 막는다. 어떤 문자가 섞일지 미리 알 수 없으므로
#   '허용된 문자체계가 아니면 전부 거른다'.
# ⚠ 범위는 반드시 \uXXXX 이스케이프로 쓴다. 문자를 그대로 넣으면
#   편집·인코딩을 거치며 제어문자로 뭉개져 파일 전체가 import 불가가 된다(실측).
_FOREIGN_SCRIPT_RE = re.compile(
    "[^"
    "\t\n\r"                    # 탭·줄바꿈
    "\u0020-\u024f"             # 라틴·숫자·기호·공백
    "\u2000-\u206f"             # 일반 구두점
    "\u20a0-\u20cf"             # 통화기호
    "\u2100-\u27bf"             # 문자꼴 기호·화살표·딩백
    "\u3000-\u303f"             # CJK 구두점
    "\u3040-\u30ff"             # 가나
    "\u3130-\u318f"             # 호환 자모
    "\u3200-\u33ff"             # CJK 괄호·단위
    "\u4e00-\u9fff"             # 한자
    "\uac00-\ud7a3"             # 한글 음절
    "\ufe00-\ufe0f"             # 이모지 변이 선택자
    "\uff00-\uffef"             # 전각 형태
    "\U0001f000-\U0001faff"     # 이모지
    "]"
)


def _find_foreign(text: str) -> list:
    """한국어 문구에 섞인 낯선 문자체계를 잡아낸다."""
    hits = sorted(set(_FOREIGN_SCRIPT_RE.findall(text)))
    if not hits:
        return []
    return [f"낯선 문자 혼입: {''.join(hits)[:20]}"]


# '리마커블하게 써라'고 시키면 LLM 은 구체성을 흉내내려고 **숫자를 지어낸다**.
#   실측(2026-08-09, 프롬프트 개편 직후): 근거가 전혀 없는데도
#   "40초 만에", "1분 만에 튀어나옵니다" 가 나왔다.
#   표시광고법상 실증할 수 없는 성능·속도 표시는 그 자체가 위법이다.
#   → 성능을 주장하는 수치는 **캠페인이 실제로 준 사실 안에 있을 때만** 허용한다.
#   ⚠ '년' 은 넣지 않는다 — "2026년" 같은 연도까지 잡아 거짓 차단이 된다.
#     날짜(8월 9일)는 promo 로 들어오므로 facts 에 자동 포함시켜 통과시킨다.
_CLAIM_NUM_RE = re.compile(
    r"(\d+\s*(?:초|분|시간|일|주|개월|배|퍼센트|%)"             # 40초 / 3배 / 90%
    r"|\d+\s*(?:만|억)?\s*(?:건|명|개|장|회)"                   # 1만건 / 300명
    r")")

# 한글 수사로 쓴 성능 주장. 아라비아 숫자만 보던 예전 규칙은 이걸 전부 놓쳤다
#   (실측: "보통 이틀 걸립니다", "당일 처리해 드립니다", "두 배 빠르게").
#   하필 band_ad.txt 의 '좋음' 예시가 이 형태였다 — 프롬프트가 위반 사례를
#   모범 답안으로 보여주고 있었다(예시도 함께 교체했다).
# ⚠ 낱말만으로 잡으면 안 된다. '하루가 다르게' 같은 관용구까지 막힌다 →
#   시간을 **재는** 표현("~만에/이면/걸립니다")이 붙을 때만 수치 주장으로 본다.
_WORD_NUM_RE = re.compile(
    r"(?P<n>하루|이틀|사흘|나흘|닷새|반나절|한나절"
    r"|(?:한|두|세|네|다섯|열)\s*(?:시간|달|주|해))"
    r"\s*(?:만에|이면|면|안에|내로|걸|정도\s*걸)"
    r"|(?P<d>당일)\s*(?:처리|발송|접수|상담|가능|출고|연결|안내)"
    r"|(?P<b>(?:두|세|네|다섯|열|몇)\s*배)"
)
# 가격·금액은 여기서 다루지 않는다(업종별 의무표기·게이트가 따로 본다).


_UNIT = "초|분|시간|일|주|개월|배|퍼센트|%"
# facts 에 적힌 범위. 왼쪽 단위는 생략될 수 있다("1~3분") 또는 둘 다 붙는다("30초~1분").
_RANGE_RE = re.compile(rf"(\d+\s*(?:{_UNIT})?)\s*~\s*(\d+\s*(?:{_UNIT}))")


def _ranges(facts: str) -> list:
    """facts 안의 범위를 (허용표기들, 양끝값) 목록으로. 전부 공백 제거된 형태.

    ⚠ 표기는 한 가지가 아니다. '1~5분' 은 왼쪽 단위가 생략된 형태이고,
      단위를 물려 '1분~5분' 으로도 쓸 수 있다. 둘 다 같은 범위를 뜻하므로
      **양쪽 다 인정**해야 한다. 한쪽만 인정하면 정상 문구가 차단된다(실측).
    """
    out = []
    for lo, hi in _RANGE_RE.findall(facts or ""):
        lo, hi = lo.replace(" ", ""), hi.replace(" ", "")
        forms = {f"{lo}~{hi}"}                 # facts 에 적힌 그대로
        # '1~3분' 처럼 왼쪽에 단위가 없으면 오른쪽 단위를 물려받은 형태도 만든다.
        full_lo = lo
        if not re.search(rf"(?:{_UNIT})$", lo):
            unit = re.search(rf"({_UNIT})$", hi)
            full_lo = lo + (unit.group(1) if unit else "")
            forms.add(f"{full_lo}~{hi}")
        out.append((forms, {full_lo, hi}))
    return out


def _find_unverified_numbers(text: str, facts: str = "") -> list:
    """근거 없이 지어낸 성능 수치를 잡아낸다.

    facts 는 운영자가 실제로 측정해 등록한 사실이다. 거기 등장하는 수치만
    통과시킨다. 확인할 길이 없는 수치는 구체성이 아니라 허위다.

    ⚠ 범위로 등록된 값은 **범위째로만** 쓸 수 있다.
      '30초~1분' 을 '30초 만에' 라고 적으면 가장 빠른 경우만 내세우는 것이라
      실증 범위를 벗어난다. 단순 부분문자열 검사로는 이게 표기에 따라 새는데
      ('1~3분' 은 '1분' 이 문자열에 없어 우연히 막히고, '30초~1분' 은 '30초'
       가 그대로 들어 있어 통과했다), 아래에서 양끝값을 명시적으로 막는다.
    """
    src = (facts or "").replace(" ", "")
    body = (text or "").replace(" ", "")
    rngs = _ranges(facts)
    bad = []
    # 한글 수사 주장은 범위 개념이 없다 — facts 에 그대로 적혀 있지 않으면 허위다.
    #   ⚠ 비교 대상은 **수사 낱말만**이다. 매치 전체("이틀 걸")로 비교하면
    #     facts 에 '이틀' 이 등록돼 있어도 통과하지 못한다.
    for m in _WORD_NUM_RE.finditer(text or ""):
        hit = m.group("n") or m.group("d") or m.group("b") or ""
        if hit and hit.replace(" ", "") not in src:
            bad.append(f"근거 없는 수치: {hit.strip()}")
    for m in sorted(set(_CLAIM_NUM_RE.findall(text))):
        norm = m.replace(" ", "")
        if not norm:
            continue
        if norm not in src:
            bad.append(f"근거 없는 수치: {m.strip()}")
            continue
        # facts 에 있긴 한데, 범위의 한쪽 끝만 떼어 쓴 것은 아닌가.
        for forms, ends in rngs:
            if norm in ends and not any(f in body for f in forms):
                bad.append(f"범위를 좁혀 씀: {m.strip()} "
                           f"(등록값 {sorted(forms)[0]})")
                break
    return bad


def facts_depth(facts: str) -> int:
    """이 소재가 실제로 쥔 재료의 두께. 0(없음) / 1(사실 1건) / 2(2건 이상).

    왜 점수가 이것 하나뿐인가:
      쿠팡 구현은 4문항을 실데이터로 채점한다(할인률·스펙·리뷰수·가격이력).
      AutoAd 에는 그 네 축 중 **어느 것도 존재하지 않는다** — 가격도 스펙도
      리뷰도 없고(상품을 파는 게 아니라 상담을 받는다), 리뷰 축은 있어도
      못 쓴다(_find_fake_testimonial 이 제3자 후기 인용을 전 업종에서 막는다).
      없는 데이터로 축을 흉내내면 상수 축 3개의 '보강 문구'가 매 프롬프트에
      실린다. 그건 진단이 아니라 비대다. 그래서 채점은 **변별력이 실재하는
      한 축**(수치 근거 밀도)만 남긴다.

    무엇을 세는가:
      _find_unverified_numbers 가 실제로 **허용해 주는 것**만 센다. 그래야
      "재료가 있다"는 판정과 "그 재료를 쓸 수 있다"는 판정이 어긋나지 않는다.
      ⚠ 범위('30초~1분')는 두 개의 수치가 아니라 한 개의 사실이다. 양끝을
        따로 세면 adstudio(범위 1건)가 printcraft(범위 2건)와 같은 점수가 된다.
        그래서 범위를 먼저 걷어낸 뒤 남은 수치를 센다.

    성과 데이터(클릭·발행수)로 이 축을 확장하지 마라. DB 전체 클릭이 세 자리인데
    활성 채널이 수백 개라 채널당 표본이 0~1이다. 쿠팡이 enough_history 로 배운
    함정(관측 첫날 값 1개 → max==min → 상시가로 오판)의 AutoAd 판이고, 지금
    넣으면 클릭 한 건으로 지시가 뒤집힌다."""
    src = (facts or "").strip()
    if not src:
        return 0
    rest, n = _RANGE_RE.subn(" ", src)
    n += len({m.replace(" ", "") for m in _CLAIM_NUM_RE.findall(rest)})
    n += len({(m.group("n") or m.group("d") or m.group("b") or "").replace(" ", "")
              for m in _WORD_NUM_RE.finditer(rest)} - {""})
    return min(n, 2)


def _material_block(facts: str, regulated: bool = None) -> str:
    """재료 깊이에 따라 달라지는 지시. 생성·수정 두 경로가 함께 쓴다.

    ⚠ 분기 술어가 두 개다. 하나로 합치면 안 된다:
      · `facts` 가 비어 있지 않다  → [확인된 사실]과 '위에 있는 것만' 레일.
      · `facts_depth` 가 0이다     → 구체성 요구 철회(얇음 게이트).
      둘은 겹치지 않는다. 예: facts='접수부터 회신까지 1~3영업일' 은
      **비어 있지 않은데 depth 0** 이다(_CLAIM_NUM_RE 가 '영업일'을 모른다).
      예전 코드는 이 경우 '확인된 사실'을 실어 놓고 바로 아래에서 "확인된
      수치가 하나도 없다"고 선언해, 방금 등록한 사실을 조용히 못 쓰게 만들고
      범위 축소('1~3영업일'→'1영업일')를 막던 레일까지 함께 떨어뜨렸다.
      → 레일은 facts 를 따라가고, 게이트는 depth 를 따라간다.

    ⚠ 얇음 블록의 뒤 두 줄(쓸 축 · 라벨 헤드라인)은 **규제 업종 전용**이다.
      facts 가 빈 업종은 11개인데 그중 10개는 규제 업종이 아니고, 라벨형
      헤드라인이 측정된 곳은 loan 하나뿐이다(12건 중 4건). 전 업종에 붙이면
      '만든 배경을 이야기하라'는 콘텐츠형 각도를 프롬프트 맨 끝에서
      '쓸 축은 상담·절차 둘뿐'이 덮어쓴다(순서가 곧 강도다).
    """
    reg = _is_regulated() if regulated is None else regulated
    depth = facts_depth(facts)
    out = ""
    if facts:
        out += f"\n\n[확인된 사실]\n{facts}"
        out += (
            "\n- 시간·횟수·배수·퍼센트·기간은 **위에 있는 것만** 쓴다. 그 밖의"
            " 수치는 지어낸 것이므로 절대 쓰지 마라.\n"
            "- 범위로 적힌 값은 범위 그대로 써라(예: '1~5분'을 '1분'으로"
            " 줄이지 마라). 줄이면 근거를 벗어난다.")
        if depth >= 2:
            # 점수가 높으면 오히려 덜어내라(쿠팡 판정 사다리의 위쪽 칸).
            out += (
                "\n- 사실이 둘 이상 주어졌다. 전부 늘어놓지 말고 가장 강한 하나만"
                " 남겨라. 나열은 힘을 뺀다.")
    if not depth:
        out += (
            "\n\n[재료 점검 · 얇음]\n"
            "- 이 글에 쓸 수 있는 수치가 없다. 시간·횟수·배수·퍼센트를 새로"
            " 만들지 마라('40초 만에', '3배 빠르게'). '이틀'·'당일'도 수치다.\n"
            "- **수치로 만드는 구체성**만 철회한다. 없는 재료로 수치를 요구하면"
            " 지어내라는 말이 된다. 구체성은 조건 하나 · 순서 · 디테일에서"
            " 만들어라.")
        if reg:
            out += (
                "\n- 쓸 축은 둘이다: 무엇을 상담·이용할 수 있는가 /"
                " 어떤 순서로 진행되는가.\n"
                "- 헤드라인이 '~안내 / ~찾기 / ~비교 / ~정리'로 끝나는 라벨이면"
                " 그 축 하나를 문장으로 풀어 써라. 단 **결과를 말하지 마라** —"
                " '풀립니다 · 정리됩니다 · 해결됩니다 · 마련해 드립니다'는"
                " 절차가 아니라 결과 예단이다.")
    return out


# 매 생성마다 다른 각도에서 쓰게 만든다.
#   LLM 은 직전 생성물을 기억하지 못하므로 "매번 바꿔라"라고 적어도 소용없다.
#   실측: 같은 프롬프트로 3번 돌리자 1·2회차 헤드라인이 글자까지 동일했다.
#   같은 문구가 여러 모임에 올라가면 그 자체가 스팸 판정 사유다.
ANGLES = [
    "직접 써 본 사람의 후기처럼",
    "흔한 오해를 하나 바로잡는 식으로",
    "쓰기 전과 쓴 뒤가 어떻게 달라졌는지 대비해서",
    "이걸 왜 만들었는지 배경을 짧게 밝히며",
    "가장 자주 받는 질문 하나에 답하는 식으로",
    "실패했던 시도를 먼저 이야기하며",
    "이 모임 사람이라면 공감할 상황 하나를 먼저 그리며",
    "숫자 대신 구체적인 장면 하나로",
]


def _pick_angle(key: str) -> str:
    """이 소재가 쓸 각도. 업종이 금지한 각도는 후보에서 뺀다.

    왜 필요한가: 각도 0("직접 써 본 사람의 후기처럼")·2("쓰기 전과 쓴 뒤 대비")·
    5("실패했던 시도를 먼저")는 규제 업종에서 그대로 위법 유도축이다.
    광고주는 그 상품을 쓴 당사자가 아니므로 1인칭 체험담은 언제나 거짓이고,
    '전에는 안 됐는데 지금은 됐다'는 승인 암시가 된다(2026-08-10 실측 사고).
    프롬프트로 "쓰지 마라"라고 적는 것보다 **애초에 시키지 않는 편**이 확실하다.

    ⚠ ANGLES 에서 원소를 지우면 안 된다. 선택이 crc32 % len(ANGLES) 라
      길이가 바뀌는 순간 진행 중인 모든 소재의 각도가 재배정돼
      '같은 소재는 늘 같은 각도' 재현성이 깨진다. 인덱스는 그대로 두고
      **후보 목록에서만** 뺀다.
    ⚠ deny_angles 를 선언하지 않은 업종은 계산이 예전과 한 글자도 다르지
      않아야 한다(무회귀). 그래서 deny 가 비면 바로 예전 식으로 간다.
    """
    seed = zlib.crc32((key or "").encode("utf-8"))
    deny = {int(i) for i in (getattr(config, "PROFILE_DENY_ANGLES", None) or ())}
    if not deny:
        return ANGLES[seed % len(ANGLES)]
    # 전부 금지해 버린 프로필은 설정 실수다. 각도 없이 쓰게 두느니 원래대로.
    pool = [i for i in range(len(ANGLES)) if i not in deny] or list(range(len(ANGLES)))
    return ANGLES[pool[seed % len(pool)]]


def _find_leaks(text: str, brand_site: str, extra_urls=()) -> list:
    """치환 실패·타사 홍보를 잡아낸다.

    실측 사고: {brand_site} 가 치환되지 않자 LLM 이 'Midjourney' 를 지어내
    경쟁 서비스를 홍보하는 글이 만들어졌다. 금칙어 목록으로는 못 막는다
    (어떤 이름을 지어낼지 미리 알 수 없으므로) → '우리 것이 아니면 전부 거른다'."""
    bad = []
    if _PLACEHOLDER_RE.search(text):
        bad.append("치환되지 않은 자리표시자")
    own = re.sub(r"^https?://", "", (brand_site or "").strip().lower()).rstrip("/")
    # 클릭 추적 리다이렉트 주소도 우리 것이다.
    # 짧은 경로(/t/…)를 못 쓰는 사이트에는 이 긴 형태가 링크로 들어가는데,
    # 여기서 걸러내면 카피가 매번 재생성 실패로 폴백된다.
    allow = {own} if own else set()
    tracker = re.sub(r"^https?://", "", (config.AD_CLICK_URL or "").lower())
    if tracker:
        allow.add(tracker.split("/")[0])
    # 우리가 직접 만들어 넣은 링크(form_url) 안의 호스트도 당연히 우리 것이다.
    # ⚠ 대출 업종은 BRAND_SITE 가 비어 있어(접수폼으로 보내므로) own 이 없다.
    #   그 상태로 두면 우리 접수폼 주소(headjim-loan.web.app)조차 '남의 주소'로
    #   걸려 카피가 매번 재생성 실패 → 폴백 캡션이 된다(실측: loan 6건 전부).
    #   추적 주소의 u= 파라미터 안에 목적지 호스트가 그대로 들어가는 것도 같은 이유.
    for u in extra_urls:
        for h in _URL_RE.findall(str(u or "")):
            allow.add(h.lower())
    for host in _URL_RE.findall(text):
        h = host.lower()
        if not allow or not any(h in a or a in h for a in allow):
            bad.append(f"우리 것이 아닌 주소: {host}")
    return bad


# ── LLM 호출 (제공자 전환: gemini | claude | ollama) ─────────
def _require_key():
    p = config.COPY_PROVIDER
    if p == "ollama":
        return          # 로컬 데몬. API 키 없음
    if p == "gemini" and not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 미설정 — .env 확인")
    if p == "claude" and not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY 미설정 — .env 확인")


def _call_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model=config.COPY_MODEL,
        max_tokens=1200,
        thinking={"type": "disabled"},          # 캡션엔 추론 불필요 → 출력비 절감
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _call_gemini(prompt: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    base = dict(temperature=0.8, max_output_tokens=1200,
                response_mime_type="application/json")   # 순수 JSON 응답
    try:
        cfg = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0), **base)  # thinking 끔(비용)
        resp = client.models.generate_content(
            model=config.COPY_MODEL_GEMINI, contents=prompt, config=cfg)
    except Exception:
        # 일부 모델은 thinking_budget=0 미지원 → thinking 옵션 없이 재시도
        resp = client.models.generate_content(
            model=config.COPY_MODEL_GEMINI, contents=prompt,
            config=types.GenerateContentConfig(**base))
    return resp.text or ""


def _loads_loose(txt: str) -> dict:
    """LLM 의 JSON 응답을 관대하게 읽는다.

    ⚠ format:"json" 을 줘도 ```json 펜스로 감싸 오는 경우가 있다(2026-09-08 실측).
      그대로 json.loads 하면 터진다. 첫 { 부터 마지막 } 까지만 떼어 읽는다.
    """
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _call_ollama(prompt: str) -> str:
    """Ollama 로 캡션을 만든다. 반환은 응답 본문 문자열(기존 provider 와 같은 계약).

    ⚠ 인코딩을 명시하지 않으면 한글이 깨져 프롬프트가 통째로 무시된다.
      2026-09-08 스파이크에서 실제로 밟았다 — "AI 광고영상 서비스" 브리프를 넣었는데
      화장품 세럼 제품샷 프롬프트가 나왔다. 원인은 모델이 아니라 인코딩이었다.
    """
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.7},
    }
    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        body = json.loads(r.read().decode("utf-8"))
    return body.get("response", "")


def _call_llm(prompt: str) -> str:
    """설정된 제공자로 호출 (config.COPY_PROVIDER = gemini | claude | ollama)."""
    if config.COPY_PROVIDER == "ollama":
        return _call_ollama(prompt)
    return _call_gemini(prompt) if config.COPY_PROVIDER == "gemini" else _call_claude(prompt)


def generate_copy(campaign: dict, channel_profile: dict,
                  max_retries: int = 3, _llm=None) -> dict:
    """
    campaign: {title, product, goal, disclosures?}
    channel_profile: {platform, tone, audience, topic, banned_words?}
    반환: {headline, body, cta, disclosures, _attempts}

    금칙어가 나오면 프롬프트를 강화해 max_retries 까지 재생성.
    _llm 을 주입하면 API 없이 테스트 가능(기본은 실제 Claude 호출).
    """
    llm = _llm or _call_llm
    if _llm is None:
        _require_key()

    platform = channel_profile.get("platform", "band")
    # 소재 형태에 따라 프롬프트가 달라진다(광고형 vs 콘텐츠형).
    form = (campaign.get("form") or channel_profile.get("form") or "ad")
    pfile = _prompt_file(platform, form)
    base_prompt = _fill(pfile.read_text(encoding="utf-8"), campaign, channel_profile)
    extra_banned = channel_profile.get("banned_words") or []
    brand_site = str(campaign.get("brand_site") or channel_profile.get("brand_site") or "")
    # 우리가 만든 링크. 여기 들어 있는 호스트는 검증에서 우리 것으로 인정한다.
    own_urls = [campaign.get("form_url"), channel_profile.get("form_url")]

    # 캠페인이 실제로 준 사실. 이 안에 있는 수치만 문구에 쓸 수 있다.
    #   promo(행사 기간·할인 등)도 운영자가 넣은 사실이므로 함께 인정한다.
    #   업종 프로필에 등록해 둔 사실(config.PROFILE_FACTS)도 같은 자격이다.
    facts = " ".join([
        *(str(campaign.get(k) or "") for k in ("facts", "promo")),
        getattr(config, "PROFILE_FACTS", "") or "",
    ]).strip()
    # 각도 회전 — 같은 채널·같은 업종이라도 매번 다른 쪽에서 접근하게 한다.
    #   track_key(캠페인-채널)를 씨앗으로 쓰면 같은 소재는 늘 같은 각도,
    #   다른 소재는 다른 각도가 되어 재현 가능하면서도 서로 겹치지 않는다.
    #   ⚠ 내장 hash() 는 프로세스마다 값이 달라진다(PYTHONHASHSEED).
    #     소재마다 프로세스가 새로 뜨는 구조라 재현이 안 되므로 crc32 를 쓴다.
    key = str(campaign.get("track_key") or campaign.get("id") or "")
    angle = _pick_angle(key)
    # 허락자산 — 콘텐츠형 전용 조각.
    #   ⚠ 광고형에는 붙이지 않는다. 광고형 CTA 에는 접수 링크가 고정으로
    #     들어가는데 "질문으로 끝내라"가 그것과 정면으로 충돌한다.
    #     band/kakao 는 콘텐츠형 프롬프트가 없어 form='content' 여도 광고형
    #     파일로 대체되므로, form 이 아니라 **읽힌 파일 이름**으로 판단한다.
    if pfile.name.endswith("_content.txt"):
        base_prompt += "\n\n" + _load_shared("_permission.txt")
    # ⚠ angle 을 출력 JSON 의 **첫 키**로 요구한다.
    #   근거는 카드뉴스 구현의 실측 하나뿐이다: 프롬프트가 밀어주는 관점을
    #   모델이 거의 그대로 따랐다(5/5·4/5·3/3 세 배치). 그게 지지하는 명제는
    #   "각도 지시 자체가 듣는다"이고, ANGLES·deny_angles 로 각도를 코드가
    #   정하는 설계가 옳다는 외부 증거다.
    #   ⚠ 여기서 더 나가지 마라. AutoAd 는 각도를 코드가 정해 주므로 모델이
    #     첫 키에 적는 것은 **자기가 고른 관점이 아니라 받아쓴 복창**이다.
    #     저장된 angle 을 _pick_angle 과 대조해 봐야 잴 수 있는 건 복창 일치이지
    #     본문 준수가 아니다(그 대조 코드도 아직 없다). 운영자가 관점을 눈으로
    #     확인할 칸이 생겼다 — 지금 확실한 건 거기까지다.
    # ⚠ angle 은 기획 메모일 뿐 광고 본문이 아니다. 발행 본문은
    #   orchestrator._caption_text 가 headline/body/cta 세 키로만 만들므로
    #   여기서 새는 경로는 없다. 검사 blob 에도 넣지 않는다(아래 주석 참조).
    base_prompt += (
        f"\n\n[이번 글의 각도]\n- {angle} 써라."
        "\n- 앞서 쓴 다른 글과 첫 문장이 겹치면 안 된다."
        "\n- 헤드라인을 쓰기 **전에** 이 각도를 한 줄로 확정해 출력의 첫 키"
        " angle 에 적어라. angle 은 기획 메모이고 본문으로 나가지 않는다."
    )
    # 업종·플랫폼과 무관하게 모든 소재에 같은 기준을 적용한다.
    #   프롬프트 파일마다 복사해 두면 한쪽만 고쳐져 기준이 갈라진다.
    # ⚠ 순서가 곧 강도다. 이 조각의 **맨 끝**이 규제 레일([리마커블과 위법의
    #   경계])이므로, 그 뒤에 창의성을 요구하는 지시를 붙이면 안 된다.
    #   예전에는 각도 블록이 레일 뒤에 왔다 — "반대로 해 봐라"와 "후기처럼
    #   써라"가 규제 경고보다 뒤에 놓여, 충돌 시 뒤엣것이 이겼다.
    #   2026-08-10 사고의 구조적 원인이라 각도를 레일 **앞**으로 옮겼다.
    #   아래 [확인된 사실]/[수치 금지]는 창의성 지시가 아니라 제약이므로
    #   레일 뒤에 와도 된다.
    base_prompt += "\n\n" + _load_shared("_purplecow.txt")
    # 심사·승인·조건에 관한 레일은 **규제 업종에만** 붙인다.
    #   전 업종에 붙이면 심사가 존재하지도 않는 업종에 "심사를 뒤집지 마라",
    #   "가능합니다 를 쓰지 마라"라고 말하게 된다. mirizip 의 "주말에도 상담
    #   가능합니다" 는 완전히 적법한데 프롬프트가 그걸 금지하고 있었다.
    #   후기·순위·수치 레일은 표시광고법이라 업종 불문이므로 _purplecow 에 남는다.
    if _is_regulated():
        base_prompt += "\n\n" + _load_shared("_compliance_rail.txt")
    # ── 재료 깊이가 카피의 깊이를 정한다 ────────────────────
    #   ⚠ 여기가 2026-08-09/10 사고의 기계적 원인이다. 14업종 중 11개는
    #     facts 가 0자인데(캠페인 facts/promo 를 넣는 경로도 존재하지 않는다)
    #     채널 프롬프트는 전 업종에 "첫 줄에 구체적인 하나를 던져라"라고 시킨다.
    #     재료가 없는 상태에서 구체성을 요구하면 그건 **지어내라는 압력**이다.
    #   ⚠ 예전 else 분기는 그 압력을 한 번 더 밀었다 — "구체성은 숫자가 아니라
    #     장면으로 만들어라". 광고주는 당사자가 아니므로 loan 에서 '장면'의
    #     착지점은 사람 이야기 = 1인칭 체험담·제3자 후기다. 각도 0·2·5 는
    #     deny_angles 로 껐는데 이 문장은 안 껐던 것이다. 그래서 지운다.
    #   → 요구를 **추가**하지 않고 **교체**한다. 재료가 얇으면 수치로 만드는
    #     구체성 요구를 철회하고 다른 축(조건·순서·디테일)으로 돌린다.
    #   ⚠ 분기 조건과 문구는 _material_block 이 갖는다. 여기서 다시 쓰지 마라 —
    #     regenerate() 경로가 같은 블록을 써야 하는데, 두 곳에 적으면 한쪽만
    #     고쳐진다(실제로 그래서 수정 경로에만 방어가 빠져 있었다).
    base_prompt += _material_block(facts)

    prompt = base_prompt
    last = None
    for attempt in range(1, max_retries + 1):
        raw = llm(prompt)
        try:
            data = _extract_json(raw)
        except ValueError:
            if attempt == max_retries:
                raise
            prompt = base_prompt + "\n\n[재작성] 반드시 JSON 객체만 출력하라(설명 금지)."
            continue

        # 관점(angle)은 기획 메모다. 없으면 빈 문자열 — 이 키가 없던 시절의
        #   소재와 폴백 캡션이 그대로 살아 있어야 한다(하위호환).
        data["angle"] = str(data.get("angle") or "").strip()
        # ⚠ angle 은 검사 blob 에 넣지 않는다(아래 주석). 그렇다고 **아무 검사도
        #   안 거친 문자열**을 승인 콘솔에 띄우면 안 된다 — 그 화면이 법적
        #   게이트이고, 뱃지는 헤드라인 바로 위에 카피와 같은 시각 계층으로
        #   그려진다. 운영자가 "거절된 사람도 된다는 걸 보여준다"를 소재의
        #   기획 의도로 읽고 승인하면 게이트가 흐려진다.
        #   → 따로 검사해서 위법한 기획 의도면 **그 줄만** 지운다. 카피
        #     자체는 통과시킨다(발행되는 문구는 아래 blob 이 이미 본다).
        if data["angle"] and _find_compliance_risks(data["angle"]):
            data["angle"] = ""
        # ⚠ blob 은 여전히 세 키뿐이다. angle 을 넣으면 안 된다:
        #   angle 은 발행되지 않는데(=_caption_text 가 안 읽는다) 검사에 걸리면
        #   적법한 카피까지 재시도 초과 → 폴백으로 간다. 발행되지 않는 문자열
        #   때문에 발행 가능한 문구를 버리는 셈이다. 위법 여부는 실제로 나가는
        #   headline/body/cta 에서 판정한다.
        blob = " ".join(str(data.get(k, "")) for k in ("headline", "body", "cta"))
        bad = (_find_banned(blob, extra_banned)
               + _find_leaks(blob, brand_site, own_urls)
               + _find_foreign(blob)
               + _find_unverified_numbers(blob, facts)
               + _find_compliance_risks(blob))
        # 콘텐츠형은 '만든 도구'를 밝히는 글이다. 우리 주소가 없으면
        # LLM 이 엉뚱한 도구를 적었다는 뜻 → 그대로 내보내면 남의 홍보가 된다.
        if form == "content" and brand_site and brand_site.lower() not in blob.lower():
            bad.append(f"도구 표기 누락(반드시 {brand_site})")
        if not bad:
            data["disclosures"] = campaign.get("disclosures", "")
            data["_attempts"] = attempt
            return data

        last = data
        prompt = (base_prompt +
                  f"\n\n[재작성] 다음 문제를 고쳐라: {', '.join(bad)}. "
                  f"도구는 반드시 '{brand_site}' 로만 표기하고 다른 서비스 이름·주소는 "
                  "절대 쓰지 마라. 확정·과장 없이 사실 기반으로 다시 작성하라.")

    # 재시도 초과 — 여기까지 왔다는 건 마지막 시도도 검사를 통과하지 못했다는 뜻이다.
    # 남의 서비스를 홍보하느니 폴백 캡션을 쓰는 편이 낫다 → 호출부가 잡도록 던진다.
    # (orchestrator.make_caption 이 잡아 _fallback_caption 으로 보낸다)
    #
    # ⚠ 지어낸 수치는 잘라낼 수 없다. 실증 못 하는 성능 표시는 표시광고법 위반이라
    #   '조금 아쉬운 문구'가 아니라 '내보내면 안 되는 문구'다 → 폴백으로 보낸다.
    # ⚠ 금칙어도 이제 여기 합류시킨다. 예전에는 금칙어만 문자열로 잘라내고
    #   (_strip_banned) 그대로 발행했는데, 실측 결과 이렇게 나갔다:
    #     {'headline': '누구나 가능한 상담', 'body': '무조건 도와드립니다'}
    #       -> {'headline': '한 상담',       'body': '도와드립니다'}
    #   뭉개진 한국어가 광고로 나가는 것이 폴백 캡션보다 나을 이유가 없고,
    #   잘라낸 자리에 남은 문장은 뜻이 달라져 있어 오히려 위험하다.
    blob = " ".join(str((last or {}).get(k, "")) for k in ("headline", "body", "cta"))
    leaks = (_find_banned(blob, extra_banned)
             + _find_leaks(blob, brand_site, own_urls)
             + _find_foreign(blob)
             + _find_unverified_numbers(blob, facts)
             + _find_compliance_risks(blob))
    if form == "content" and brand_site and brand_site.lower() not in blob.lower():
        leaks.append(f"도구 표기 누락({brand_site})")
    raise ValueError(
        f"카피 검증 실패(재시도 {max_retries}회): {', '.join(leaks) or '원인 불명'}")


def _strip_banned(data: dict, extra=None) -> dict:
    banned = BANNED_PHRASES + list(extra or [])
    out = dict(data)
    for k in ("headline", "body", "cta"):
        v = str(out.get(k, ""))
        for b in banned:
            v = v.replace(b, "")
        out[k] = re.sub(r"\s{2,}", " ", v).strip()
    return out


def regenerate(original: dict, edit_request: str, channel_profile: dict = None,
               _llm=None) -> dict:
    """승인 콘솔 '수정' 요청 반영 재생성 (구조화 카피 dict in/out)."""
    llm = _llm or _call_llm
    if _llm is None:
        _require_key()
    # ⚠ 원본 dict 를 통째로 싣지 않는다. 예전엔 copy_json 전체(profile_key·
    #   법정 mandatory 블록 포함)를 json.dumps 로 프롬프트에 넣었는데,
    #   모델이 입력 구조를 그대로 되돌려주면 그 값들이 반환 dict 에 실려
    #   저장 단계까지 흘러간다(approval._update_caption). 모델에게 보여줄
    #   이유도 없는 값이므로 편집 대상 3개만 싣는다.
    seed = {k: str((original or {}).get(k) or "")
            for k in ("headline", "body", "cta")}
    # ⚠ 이 경로에는 예전에 규제 문맥이 하나도 실리지 않았다. 업종 주의사항도,
    #   보랏빛소 레일도, facts 도 없이 "확정·과장 금지" 한 줄뿐이었다.
    #   운영자가 승인 콘솔에서 "좀 더 눈에 띄게" 라고 한 번 누르면 생성 단계의
    #   방어가 통째로 풀리고, 그 결과가 approval._update_caption 으로 그대로
    #   저장된다. 생성 때 지키던 기준은 수정 때도 같아야 한다.
    # ⚠ 재료 깊이 블록도 여기 붙인다. 예전에는 안 붙였는데, 하필 이 경로가
    #   코드 방어가 가장 얇은 경로다("좀 더 구체적으로 써줘" 한 번이면 재료
    #   0인 카피에 수치를 요구하게 된다). 프롬프트 방어가 더 필요한 쪽에
    #   빠져 있었다.
    # ⚠ facts 의 출처는 업종 프로필뿐이다. 캠페인 facts/promo 를 넣는 경로는
    #   DB 에 존재하지 않고(campaigns 에 그 컬럼이 없다), 프로세스당 업종은
    #   하나이므로 config.PROFILE_FACTS 가 generate_copy 가 쓰는 값과 같다.
    facts = str(getattr(config, "PROFILE_FACTS", "") or "").strip()
    prompt = (
        "아래는 기존 광고 카피(JSON)다.\n"
        f"{json.dumps(seed, ensure_ascii=False)}\n\n"
        f"수정 요청: {edit_request}\n\n"
        "요청을 반영해 같은 JSON 형식 {\"headline\",\"body\",\"cta\"} 으로만 다시 출력하라. "
        "확정·과장 표현 금지.\n\n"
        f"[업종 주의사항]\n{config.COMPLIANCE_NOTE}\n\n"
        + _load_shared("_purplecow.txt")
        + (("\n\n" + _load_shared("_compliance_rail.txt")) if _is_regulated() else "")
        + _material_block(facts)
    )
    data = _extract_json(llm(prompt))
    extra = (channel_profile or {}).get("banned_words") or []
    blob = " ".join(str(data.get(k, "")) for k in ("headline", "body", "cta"))
    # 지어낸 후기·순위 주장·승인 예단은 잘라낼 수 없다(잘라내면 문장이 깨진다).
    #   수정 요청이 위법한 방향이었다는 뜻이므로 저장하지 말고 운영자에게 돌린다.
    #   approval._decide 가 이 예외를 잡아 화면에 실패로 표시한다.
    # ⚠ _find_unverified_numbers 를 이제 여기서도 건다. 예전 주석은 "이 경로엔
    #   facts 가 없어 정당한 수치까지 막힌다"였는데, 그 전제가 틀렸다 —
    #   facts 의 실제 출처는 업종 프로필이고 그건 이 프로세스에도 있다.
    #   재료가 없는 업종에서 수치가 들어오면 그건 지어낸 것이 맞다. 저장하지
    #   말고 운영자에게 되돌린다(이 경로가 유일하게 수치 방어가 0이었다).
    #
    # ⚠ _find_leaks 는 반드시 건다. 이게 빠져 있던 탓에 '수정' 한 번으로
    #   경쟁 서비스 주소가 그대로 저장됐다(실측: competitor.co.kr 통과).
    #   _find_leaks 를 만들게 한 원래 사고(치환 실패 → LLM 이 Midjourney 를
    #   지어내 홍보)의 재발 경로다.
    #   허용 주소는 **승인 전 원본에 이미 들어 있던 것**으로 잡는다. 원본은
    #   generate_copy 의 검증을 통과한 문구이므로 거기 있는 호스트는 우리 것이다.
    #   (이 경로에는 campaign 이 없어 form_url 을 따로 받을 방법이 없다.)
    orig_blob = " ".join(str((original or {}).get(k) or "")
                         for k in ("headline", "body", "cta"))
    brand_site = str((channel_profile or {}).get("brand_site")
                     or getattr(config, "BRAND_SITE", "") or "")
    risks = (_find_compliance_risks(blob) + _find_foreign(blob)
             + _find_unverified_numbers(blob, facts)
             + _find_leaks(blob, brand_site, [orig_blob]))
    # ⚠ 금칙어를 문자열로 잘라내(_strip_banned) 저장하던 경로가 여기 남아 있었다.
    #   실측: {'headline': '누구나 가능한 상담'} → '한 상담' 이 그대로 저장됐다.
    #   생성 경로에서는 이미 없앤 동작인데 수정 경로에만 남아 있었다.
    #   뭉개진 한국어를 저장하느니 운영자에게 되돌리는 편이 낫다.
    risks += [f"금칙어: {b}" for b in _find_banned(blob, extra)]
    if risks:
        raise ValueError(f"수정본 검증 실패: {', '.join(risks)}")
    return data
