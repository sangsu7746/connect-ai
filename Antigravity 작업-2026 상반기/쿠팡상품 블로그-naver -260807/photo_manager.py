"""
photo_manager.py
지정된 사진 디렉토리에서 주제(키워드)에 맞는 사진을 골라옵니다.
"""
import os
import random

def get_matching_photos(photo_dir: str, topic: str, count: int = 3) -> list:
    """
    주어진 디렉토리에서 주제와 관련된 사진을 골라옵니다.
    로직: 파일명에 주제 키워드가 포함되어 있으면 우선 선택, 부족하면 랜덤 선택.
    
    Args:
        photo_dir (str): 사진이 있는 절대 경로
        topic (str): 글의 주제/키워드
        count (int): 가져올 최대 사진 수
        
    Returns:
        list of str: 선택된 사진의 절대 경로 리스트
    """
    if not photo_dir or not os.path.isdir(photo_dir):
        return []
        
    valid_ext = {'.png', '.jpg', '.jpeg', '.gif', '.webp'}
    all_photos = []
    
    for filename in os.listdir(photo_dir):
        ext = os.path.splitext(filename)[1].lower()
        if ext in valid_ext:
            all_photos.append(os.path.join(photo_dir, filename))
            
    if not all_photos:
        return []
        
    # 주제 단어를 띄어쓰기로 분리하여 키워드 매칭
    keywords = topic.split()
    matched_photos = []
    other_photos = []
    
    for p in all_photos:
        filename_lower = os.path.basename(p).lower()
        if any(kw.lower() in filename_lower for kw in keywords):
            matched_photos.append(p)
        else:
            other_photos.append(p)
            
    # 우선순위: 이름이 매칭된 사진 -> 나머지 랜덤
    random.shuffle(matched_photos)
    random.shuffle(other_photos)
    
    selected = matched_photos + other_photos
    return selected[:count]

if __name__ == "__main__":
    # Test
    res = get_matching_photos("C:/Users/Administrator/Desktop", "테스트", 2)
    print("Selected:", res)
