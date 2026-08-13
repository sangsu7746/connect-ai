"""
keyword_collector.py
주제(프라이머리 키워드)를 기반으로 세부 키워드/연관 검색어를 수집하거나 
AI를 통해 트래픽을 유도할 황금 키워드를 추출합니다.
"""
from google import genai

def generate_golden_keywords(api_key: str, topic: str, count: int = 5) -> list:
    """
    주제를 입력받아 AI를 사용해 SEO상 유리하고 검색량이 많을 것으로 예상되는
    '황금 키워드'를 생성하여 리스트 형태로 반환합니다.
    """
    client = genai.Client(api_key=api_key)
    
    prompt = f"""
당신은 네이버 블로그 SEO 및 키워드 분석 전문가입니다.
메인 주제: "{topic}"

이 주제로 블로그 글을 작성할 때, 단기간에 트래픽을 유도하기 좋은 세부 '황금 키워드' (롱테일 키워드 포함) {count}개를 추출해주세요.
네이버 검색 특성을 고려하여, 사람들이 실제로 많이 검색할 만한 실용적이고 구체적인 키워드여야 합니다.

출력 형식:
각 키워드만 한 줄에 하나씩 출력 (앞에 번호나 기호 금지)
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        keywords = [line.strip() for line in text.split("\n") if line.strip()]
        return keywords[:count]
    except Exception as e:
        print(f"[Keyword Collector] API 오류로 기본 키워드 사용: {e}")
        # API 실패 시 주제 단어를 분리해서 기본 키워드 생성
        base_words = [w.strip() for w in topic.replace(",", " ").replace("·", " ").split() if w.strip()]
        fallback = base_words[:count] if base_words else [topic]
        return fallback[:count]

if __name__ == "__main__":
    import config as cfg
    config = cfg.load_config()
    key = config.get("gemini_api_key", "")
    if key:
        print("Generated Keywords:", generate_golden_keywords(key, "서울 카페 추천", 5))
