"""
ai_writer.py
google-genai SDK를 사용하여 블로그 글을 자동 생성하는 모듈
"""
import random
import time

from google import genai
from google.genai import types

#: 쓸 모델.
#: gemini-2.5-flash 는 2026-08 기준 새로 발급한 키에서 404 를 낸다
#: ("This model is no longer available to new users"). 키가 죽은 게 아니라 모델이 은퇴한 것이다.
#: '-latest' 별칭은 구글이 최신으로 유지하므로, 다음 은퇴 때 이 파일을 또 고치지 않아도 된다.
MODEL = "gemini-flash-latest"

#: 순서대로 시도할 모델. 앞이 실패하면 다음으로 넘어간다.
#: 무료 등급 키는 혼잡할 때 503(UNAVAILABLE)을 자주 내는데,
#: 이 글쓰기는 밤중에 사람 없이 10건씩 도는 작업이라 한 번 503이면 그 글이 통째로 날아간다.
#: 할당량(429)도 모델마다 따로 세므로 모델을 바꾸면 살아나는 경우가 있다.
#: 뒤로 갈수록 글이 짧고 성기다 — 그래서 품질 좋은 것부터 쓰고 lite 는 마지막 보루로 둔다.
#: 2026-08-21 실측으로 살아 있는 것만 남겼다. gemini-2.5-flash 는 은퇴해서
#: 404 만 내고 있었다 — 폴백에 죽은 모델이 끼어 있으면 그 자리에서 한 번씩 헛돈다.
#: 무료 등급은 '모델별로 하루 20회'라(GenerateRequestsPerDayPerProjectPerModel)
#: 모델을 넓게 두는 것이 곧 하루 한도를 늘리는 것이다. 4종이면 80회가 된다.
FALLBACK_MODELS = [MODEL, "gemini-3.6-flash", "gemini-2.5-flash-lite",
                   "gemini-flash-lite-latest"]

#: 같은 모델에 붙어서 재시도할 횟수. 503 은 대개 몇 초 뒤에 풀린다.
_TRIES_PER_MODEL = 2


def _generate(client, prompt: str, log=None):
    """
    모델을 바꿔 가며 생성한다. 어떤 모델로 성공했는지도 돌려준다.

    되살릴 수 있는 실패(503 혼잡·429 한도·404 은퇴)만 넘어간다.
    키가 잘못됐다면 어느 모델로 바꿔도 마찬가지이므로 즉시 세운다 —
    죽은 키로 열두 번 두드려 봐야 시간만 버리고 원인도 가려진다.
    """
    last = None
    for model in FALLBACK_MODELS:
        for attempt in range(_TRIES_PER_MODEL):
            try:
                resp = client.models.generate_content(model=model, contents=prompt)
                text = (resp.text or "").strip()
                if not text:
                    raise RuntimeError("응답이 비었습니다")
                if log and model != MODEL:
                    log(f"  ↳ {model} 로 생성했습니다 (앞 모델 실패)")
                return text, model
            except Exception as e:
                s = str(e)
                last = e
                fatal = ("API_KEY_INVALID" in s or "API key not valid" in s
                         or "PERMISSION_DENIED" in s)
                if fatal:
                    raise
                retryable = ("503" in s or "UNAVAILABLE" in s or "429" in s
                             or "RESOURCE_EXHAUSTED" in s or "500" in s
                             or "404" in s or "deadline" in s.lower())
                if not retryable:
                    raise
                # 404(모델 은퇴)는 기다려도 안 생긴다. 바로 다음 모델로.
                if "404" in s:
                    break
                if attempt + 1 < _TRIES_PER_MODEL:
                    # 지터를 섞는다. 10건이 한꺼번에 같은 초에 다시 두드리면 또 막힌다.
                    time.sleep(random.uniform(3.0, 7.0))
    raise last if last else RuntimeError("생성 실패")


def generate_blog_post(api_key: str, topic: str, keywords: str = "", context: str = "",
                       theme_prompt: str = "", log=None) -> dict:
    """
    주제, 키워드, 크롤링 컨텍스트를 받아 네이버 블로그용 글을 생성합니다.

    Returns:
        {"title": str, "content": str, "model": str} 형태의 딕셔너리
    """
    client = genai.Client(api_key=api_key)

    keyword_text = f"\n키워드: {keywords}" if keywords else ""
    context_text = f"\n\n[참조 문서(최신 뉴스/블로그 요약)]:\n{context}\n\n위 참조 문서를 바탕으로 트렌드와 사실이 포함된 유익한 글을 작성해주세요." if context else ""

    theme_text = f"\n\n[테마 및 작성 가이드 (매우 중요)]:\n{theme_prompt}" if theme_prompt else ""

    # 테마 지침이 오면 그것이 최우선이다.
    # 예전에는 아래 일반 규칙(서론-본론-맺음말 / 이모지 활용 / 클릭률 높은 제목)이
    # 항상 붙어서, 보랏빛 소 지침처럼 "그 정형을 쓰지 말라"는 테마와 정면으로 충돌했다.
    # 상반된 지시가 한 프롬프트에 들어가면 결과가 뭉개진다.
    # 발행 직전 검사(guardrails)가 막는 표현을 미리 알려 준다.
    # 검사는 그대로 두고 — 믿을 건 검사다 — 헛생성만 줄이려는 것이다.
    try:
        import guardrails
        ban_text = "\n\n" + guardrails.PROMPT_BAN_TEXT
    except Exception:
        ban_text = ""

    if theme_prompt:
        rules = """작성 규칙:
1. 위 [테마 및 작성 가이드]가 최우선이다. 아래 항목과 충돌하면 가이드를 따른다.
2. 가이드가 금지한 표현·구조를 절대 쓰지 마라.
3. 제공된 [참조 문서]에 있는 수치·사실만 쓴다. 없는 값을 지어내지 마라.
4. 문단은 네이버 블로그에서 읽기 좋게 짧게 끊는다.""" + ban_text
    else:
        rules = """작성 규칙:
1. 제목은 클릭률을 높이는 매력적인 한국어 제목 (30자 이내)
2. 본문은 1500~2500자 내외
3. 자연스럽고 친근한 블로그 문체 사용
4. 소제목을 3~5개 포함
5. 서론 → 본론(소제목별 내용) → 맺음말 구조
6. SEO를 위해 주제 키워드를 적절히 반복
7. 독자에게 유용한 실용적인 정보 포함
8. 이모지를 적절히 활용하여 가독성 향상""" + ban_text

    prompt = f"""당신은 네이버 블로그 글을 쓰는 전문 블로거입니다.

아래 주제로 글을 작성해주세요.

주제: {topic}{keyword_text}{context_text}{theme_text}

{rules}

출력 형식 (반드시 이 형식으로):
[제목]
(여기에 제목만 작성)

[본문]
(여기에 본문 전체 작성)
"""

    text, used_model = _generate(client, prompt, log=log)

    # 제목과 본문 파싱
    title = ""
    content = ""

    if "[제목]" in text and "[본문]" in text:
        parts = text.split("[본문]")
        title_part = parts[0].replace("[제목]", "").strip()
        title = title_part.strip()
        content = parts[1].strip() if len(parts) > 1 else ""
    else:
        # 파싱 실패 시 첫 줄을 제목으로
        lines = text.split("\n")
        title = lines[0].strip().lstrip("#").strip()
        content = "\n".join(lines[1:]).strip()

    return {"title": title, "content": content, "model": used_model}


def generate_title_only(api_key: str, topic: str) -> str:
    """주제로 블로그 제목 후보 5개 생성"""
    client = genai.Client(api_key=api_key)
    prompt = f"""네이버 블로그에서 클릭률이 높은 제목을 "{topic}" 주제로 5개 만들어주세요.
각 제목은 한 줄씩, 번호 없이 출력해주세요. 30자 이내로."""
    text, _ = _generate(client, prompt)
    return text
