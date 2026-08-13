"""
ai_image_generator.py
Gemini API를 사용하여 블로그 본문의 핵심 장면을 영문 프롬프트로 추출한 뒤,
Pollinations.ai 무료 API를 통해 이미지를 실시간으로 생성하여 로컬에 저장합니다.
"""
import os
import urllib.request
import urllib.parse
import uuid
from google import genai
from google.genai import types

def generate_ai_images(api_key: str, topic: str, content: str, num_images: int = 3, width: int = 1000, height: int = 1000) -> list[str]:
    """
    본문 내용을 바탕으로 n개의 이미지를 자동 생성하여 저장합니다.
    """
    client = genai.Client(api_key=api_key)

    prompt = f"""
다음은 '{topic}' 주제의 블로그 글입니다.
이 글을 시각적으로 잘 나타낼 수 있는 고품질 사진 촬영용 프롬프트를 영어로 {num_images}개 작성해주세요.

블로그 내용:
{content[:1500]}...

작성 규칙:
1. 각 프롬프트는 DALL-E와 같은 이미지 생성기에 적합한 전문 사진작가 스타일의 간결한 영어 문장이어야 합니다.
2. 부가 설명, 번호 표시, 따옴표 없이 오직 프롬프트 텍스트만 한 줄에 하나씩 출력하세요.
3. 정확히 {num_images}줄만 출력하세요. 무조건 영어로만 출력하세요.
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        lines = [line.strip() for line in response.text.strip().split("\n") if line.strip()]
    except Exception as e:
        print(f"[Error in AI prompt generation]: {e}")
        lines = [f"{topic} aesthetic high quality photo" for _ in range(num_images)]

    # Limit to num_images
    lines = lines[:num_images]

    temp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__ if '__file__' in globals() else '.'), "temp_images"))
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    downloaded_paths = []

    for i, p in enumerate(lines):
        try:
            encoded_prompt = urllib.parse.quote(p)
            # seed to pseudo-randomize based on string content somewhat
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&seed={uuid.uuid4().int % 100000}"
            filename = f"ai_gen_{uuid.uuid4().hex[:8]}.png"
            filepath = os.path.join(temp_dir, filename)
            
            # Add user-agent header to avoid 403 Forbidden with standard urllib
            req = urllib.request.Request(
                url, 
                data=None, 
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
            )
            with urllib.request.urlopen(req) as response_stream, open(filepath, 'wb') as out_file:
                out_file.write(response_stream.read())
                
            downloaded_paths.append(filepath)
        except Exception as e:
            print(f"Failed to download image {i+1}: {e}")

    return downloaded_paths
