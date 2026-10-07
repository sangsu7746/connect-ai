# ============================================================
#  content/copy_engine.py — 광고 카피 생성  (P1-1)
#  이식: Sns 자동화/claude_engine.py (generate/regenerate 패턴)
#  확장: 채널별 프롬프트(band/facebook/kakao) + 금칙어 가드 재생성 루프
#  · Anthropic 은 지연 import (키 없이도 목으로 로직 검증 가능)
# ============================================================
import json
import re
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


def _load_prompt(channel: str, form: str = "ad") -> str:
    """form: ad(광고형) | content(콘텐츠형)

    콘텐츠형은 '결과물을 나누는 글'이다. 홍보를 금지하지 않지만 주제를 지켜야 하는
    모임(topic_only)이나 규정이 없는 모임(unknown)에 쓴다.
    광고형 배너를 그런 곳에 올리면 승인 대기에 걸리거나 규칙 위반이 된다(실측)."""
    for name in (f"{channel}_{form}.txt", f"{channel}_ad.txt", "band_ad.txt"):
        p = PROMPT_DIR / name
        if p.exists():
            return p.read_text(encoding="utf-8")
    raise FileNotFoundError(f"프롬프트 파일 없음: {channel}/{form}")


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


def _find_banned(text: str, extra=None) -> list:
    """포함된 금칙어 목록(없으면 빈 리스트)."""
    banned = BANNED_PHRASES + list(extra or [])
    return [b for b in banned if b in text]


# 문구에 나와도 되는 주소 = 우리 것뿐이다.
_URL_RE = re.compile(r"\b(?:https?://)?([a-z0-9][a-z0-9.-]*\.(?:com|net|org|io|ai|app|kr|co\.kr))",
                     re.I)


def _find_leaks(text: str, brand_site: str) -> list:
    """치환 실패·타사 홍보를 잡아낸다.

    실측 사고: {brand_site} 가 치환되지 않자 LLM 이 'Midjourney' 를 지어내
    경쟁 서비스를 홍보하는 글이 만들어졌다. 금칙어 목록으로는 못 막는다
    (어떤 이름을 지어낼지 미리 알 수 없으므로) → '우리 것이 아니면 전부 거른다'."""
    bad = []
    if _PLACEHOLDER_RE.search(text):
        bad.append("치환되지 않은 자리표시자")
    own = re.sub(r"^https?://", "", (brand_site or "").strip().lower()).rstrip("/")
    for host in _URL_RE.findall(text):
        h = host.lower()
        if not own or (h not in own and own not in h):
            bad.append(f"우리 것이 아닌 주소: {host}")
    return bad


# ── LLM 호출 (제공자 전환: gemini | claude) ─────────────────
def _require_key():
    p = config.COPY_PROVIDER
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


def _call_llm(prompt: str) -> str:
    """설정된 제공자로 호출 (config.COPY_PROVIDER = gemini | claude)."""
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
    base_prompt = _fill(_load_prompt(platform, form), campaign, channel_profile)
    extra_banned = channel_profile.get("banned_words") or []
    brand_site = str(campaign.get("brand_site") or channel_profile.get("brand_site") or "")

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

        blob = " ".join(str(data.get(k, "")) for k in ("headline", "body", "cta"))
        bad = _find_banned(blob, extra_banned) + _find_leaks(blob, brand_site)
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

    # 재시도 초과 — 금칙어는 잘라낼 수 있지만 '지어낸 도구 이름'은 잘라낼 수 없다.
    # 남의 서비스를 홍보하느니 폴백 캡션을 쓰는 편이 낫다 → 호출부가 잡도록 던진다.
    blob = " ".join(str((last or {}).get(k, "")) for k in ("headline", "body", "cta"))
    leaks = _find_leaks(blob, brand_site)
    if form == "content" and brand_site and brand_site.lower() not in blob.lower():
        leaks.append(f"도구 표기 누락({brand_site})")
    if leaks:
        raise ValueError(f"카피 검증 실패(재시도 {max_retries}회): {', '.join(leaks)}")

    cleaned = _strip_banned(last or {}, extra_banned)
    cleaned["disclosures"] = campaign.get("disclosures", "")
    cleaned["_attempts"] = max_retries
    cleaned["_guard_forced"] = True
    return cleaned


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
    prompt = (
        "아래는 기존 광고 카피(JSON)다.\n"
        f"{json.dumps(original, ensure_ascii=False)}\n\n"
        f"수정 요청: {edit_request}\n\n"
        "요청을 반영해 같은 JSON 형식 {\"headline\",\"body\",\"cta\"} 으로만 다시 출력하라. "
        "확정·과장 표현 금지."
    )
    data = _extract_json(llm(prompt))
    extra = (channel_profile or {}).get("banned_words") or []
    if _find_banned(" ".join(str(data.get(k, "")) for k in ("headline", "body", "cta")), extra):
        data = _strip_banned(data, extra)
    return data
