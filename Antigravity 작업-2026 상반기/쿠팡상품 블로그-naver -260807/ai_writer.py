"""
ai_writer.py
google-genai SDK를 사용하여 블로그 글을 자동 생성하는 모듈
"""
from google import genai
from google.genai import types

#: 쓸 모델.
#: gemini-2.5-flash 는 2026-08 기준 새로 발급한 키에서 404 를 낸다
#: ("This model is no longer available to new users"). 키가 죽은 게 아니라 모델이 은퇴한 것이다.
#: '-latest' 별칭은 구글이 최신으로 유지하므로, 다음 은퇴 때 이 파일을 또 고치지 않아도 된다.
MODEL = "gemini-flash-latest"


def generate_blog_post(api_key: str, topic: str, keywords: str = "", context: str = "", theme_prompt: str = "") -> dict:
    """
    주제, 키워드, 크롤링 컨텍스트를 받아 네이버 블로그용 글을 생성합니다.

    Returns:
        {"title": str, "content": str} 형태의 딕셔너리
    """
    client = genai.Client(api_key=api_key)

    keyword_text = f"\n키워드: {keywords}" if keywords else ""
    context_text = f"\n\n[참조 문서(최신 뉴스/블로그 요약)]:\n{context}\n\n위 참조 문서를 바탕으로 트렌드와 사실이 포함된 유익한 글을 작성해주세요." if context else ""

    theme_text = f"\n\n[테마 및 작성 가이드 (매우 중요)]:\n{theme_prompt}" if theme_prompt else ""

    # 테마 지침이 오면 그것이 최우선이다.
    # 예전에는 아래 일반 규칙(서론-본론-맺음말 / 이모지 활용 / 클릭률 높은 제목)이
    # 항상 붙어서, 보랏빛 소 지침처럼 "그 정형을 쓰지 말라"는 테마와 정면으로 충돌했다.
    # 상반된 지시가 한 프롬프트에 들어가면 결과가 뭉개진다.
    if theme_prompt:
        rules = """작성 규칙:
1. 위 [테마 및 작성 가이드]가 최우선이다. 아래 항목과 충돌하면 가이드를 따른다.
2. 가이드가 금지한 표현·구조를 절대 쓰지 마라.
3. 제공된 [참조 문서]에 있는 수치·사실만 쓴다. 없는 값을 지어내지 마라.
4. 문단은 네이버 블로그에서 읽기 좋게 짧게 끊는다."""
    else:
        rules = """작성 규칙:
1. 제목은 클릭률을 높이는 매력적인 한국어 제목 (30자 이내)
2. 본문은 1500~2500자 내외
3. 자연스럽고 친근한 블로그 문체 사용
4. 소제목을 3~5개 포함
5. 서론 → 본론(소제목별 내용) → 맺음말 구조
6. SEO를 위해 주제 키워드를 적절히 반복
7. 독자에게 유용한 실용적인 정보 포함
8. 이모지를 적절히 활용하여 가독성 향상"""

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

    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )
    text = response.text.strip()

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

    return {"title": title, "content": content}


def generate_title_only(api_key: str, topic: str) -> str:
    """주제로 블로그 제목 후보 5개 생성"""
    client = genai.Client(api_key=api_key)
    prompt = f"""네이버 블로그에서 클릭률이 높은 제목을 "{topic}" 주제로 5개 만들어주세요.
각 제목은 한 줄씩, 번호 없이 출력해주세요. 30자 이내로."""
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
    )
    return response.text.strip()
