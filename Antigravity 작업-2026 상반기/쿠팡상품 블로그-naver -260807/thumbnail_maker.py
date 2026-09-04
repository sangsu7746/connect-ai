"""
thumbnail_maker.py
블로그 포스팅 첫 화면에서 시선을 끌 수 있는 썸네일 이미지를 동적으로 생성합니다.
"""
from PIL import Image, ImageDraw, ImageFont
import os
import textwrap

def generate_thumbnail(text: str, output_path: str = "thumbnail.png", bg_color: tuple = (40, 42, 54), text_color: tuple = (248, 248, 242)):
    """
    주어진 텍스트를 이용해 1000x1000 썸네일 이미지를 생성합니다.
    
    Args:
        text (str): 썸네일에 들어갈 메인 텍스트
        output_path (str): 저장할 파일 경로
        bg_color (tuple): 배경색 (R, G, B)
        text_color (tuple): 텍스트색 (R, G, B)
    
    Returns:
        str: 생성된 파일 경로
    """
    width, height = 1000, 1000
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    # Windows 기본 폰트인 맑은 고딕 사용
    try:
        font_path = "C:/Windows/Fonts/malgunbd.ttf"
        font = ImageFont.truetype(font_path, 80)
    except IOError:
        # Fallback 폰트
        font = ImageFont.load_default()
        
    # 텍스트 줄바꿈 처리
    wrapped_text = "\n".join(textwrap.wrap(text, width=15))
    
    # 텍스트 크기 계산 후 가운데 정렬
    try:
        # Pillow >= 8.0.0
        bbox = draw.textbbox((0, 0), wrapped_text, font=font, align="center")
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except AttributeError:
        # Older Pillow
        text_w, text_h = draw.textsize(wrapped_text, font=font)
        
    x = (width - text_w) / 2
    y = (height - text_h) / 2
    
    # 테두리 그려주기 (간단한 디자인 효과)
    border_margin = 50
    draw.rectangle(
        [border_margin, border_margin, width - border_margin, height - border_margin],
        outline=(98, 114, 164), 
        width=10
    )
    
    # 글씨 그리기
    draw.text((x, y), wrapped_text, font=font, fill=text_color, align="center")
    
    img.save(output_path, "PNG")
    return os.path.abspath(output_path)

if __name__ == "__main__":
    path = generate_thumbnail("부동산 최신 정책\n완벽 분석 가이드")
    print(f"Thumbnail saved at {path}")
