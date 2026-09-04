import requests
import json
import os
import uuid
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

def get_naver_api_keys():
    """config.json에서 네이버 API 키를 로드합니다."""
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
            return config.get("naver_client_id"), config.get("naver_client_secret")
    except:
        return None, None

def crawl_naver_search(keyword: str, tab: str = "news", count: int = 3, days_limit: int = 10) -> list:
    """
    네이버 오픈 API를 사용하여 검색 결과를 가져옵니다.
    days_limit: 최근 N일 이내 게시된 글만 포함 (0이면 필터 없음)
    """
    client_id, client_secret = get_naver_api_keys()
    if not client_id or not client_secret:
        print("[Crawler Error] Naver API keys not found in config.json")
        return []

    # date 정렬로 최신 콘텐츠 우선 수집
    url = f"https://openapi.naver.com/v1/search/{tab}.json?query={keyword}&display={count}&sort=date"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }
    
    cutoff = datetime.now() - timedelta(days=days_limit) if days_limit > 0 else None

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for item in data.get("items", []):
            # pubDate 필터링 (뉴스/블로그 공통)
            if cutoff:
                pub_str = item.get("pubDate", "") or item.get("postdate", "")
                if pub_str:
                    try:
                        # 뉴스: "Mon, 02 Jun 2026 08:00:00 +0900"
                        from email.utils import parsedate_to_datetime
                        pub_dt = parsedate_to_datetime(pub_str).replace(tzinfo=None)
                        if pub_dt < cutoff:
                            continue
                    except Exception:
                        pass  # 파싱 실패 시 필터 무시

            results.append({
                "title": item["title"].replace("<b>", "").replace("</b>", ""),
                "description": item["description"].replace("<b>", "").replace("</b>", ""),
                "link": item["link"]
            })
        return results
    except Exception as e:
        print(f"[Crawler API Error] {e}")
        return []

def get_context_for_ai(keyword: str, news_count: int = 10, blog_count: int = 10) -> str:
    """
    API 데이터를 수집하여 AI 프롬프트용 문자열(컨텍스트)로 반환합니다.
    """
    news_data = crawl_naver_search(keyword, tab="news", count=news_count)
    blog_data = crawl_naver_search(keyword, tab="blog", count=blog_count)
    
    context_lines = []
    
    if news_data:
        context_lines.append("【네이버 공식 API 최신 뉴스 요약】")
        for i, doc in enumerate(news_data, 1):
            context_lines.append(f"{i}. 제목: {doc['title']}\n   내용: {doc['description']}")
            
    if blog_data:
        context_lines.append("\n【네이버 공식 API 최신 블로그 요약】")
        for i, doc in enumerate(blog_data, 1):
            context_lines.append(f"{i}. 제목: {doc['title']}\n   내용: {doc['description']}")
            
    return "\n".join(context_lines)


def crawl_naver_images(keyword: str, count: int = 1) -> list:
    """
    네이버 이미지 검색 API를 사용하여 키워드 관련 이미지를 다운로드합니다.
    - sort=date: 최신순 정렬로 오래된 이미지 방지
    - count=1: 키워드당 1컷만 저장 (중복 방지)
    - 중복 source_url 제거

    Args:
        keyword (str): 검색 키워드
        count (int): 다운로드할 최대 이미지 수 (기본 1컷)

    Returns:
        list of dict: [{"keyword": ..., "path": ..., "source_url": ...}, ...]
    """
    client_id, client_secret = get_naver_api_keys()
    if not client_id or not client_secret:
        print("[Crawler Error] Naver API keys not found in config.json")
        return []

    # 최신순(date) 정렬로 오래된 이미지 수집 방지
    # 후보를 count*3개 받아서 유효한 것 중 count개만 사용
    fetch_count = min(count * 3, 10)
    encoded_query = urllib.parse.quote(keyword)
    url = (
        f"https://openapi.naver.com/v1/search/image.json"
        f"?query={encoded_query}&display={fetch_count}&sort=date&filter=medium"
    )
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[Naver Image API Error] {e}")
        return []

    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_images")
    os.makedirs(temp_dir, exist_ok=True)

    downloaded = []
    seen_urls: set = set()  # 중복 source_url 제거

    for item in data.get("items", []):
        if len(downloaded) >= count:
            break

        # 원본 이미지 링크 우선, 없으면 썸네일
        img_url = item.get("link") or item.get("thumbnail", "")
        if not img_url or img_url in seen_urls:
            continue
        seen_urls.add(img_url)

        try:
            # 확장자 추출 (없으면 .jpg 기본값)
            parsed_path = urllib.parse.urlparse(img_url).path
            ext = os.path.splitext(parsed_path)[1].lower()
            if ext not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
                ext = ".jpg"

            filename = f"crawled_{uuid.uuid4().hex[:8]}{ext}"
            filepath = os.path.join(temp_dir, filename)

            req = urllib.request.Request(
                img_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, timeout=10) as r, open(filepath, "wb") as f:
                f.write(r.read())

            downloaded.append({
                "keyword": keyword,
                "path": filepath,
                "source_url": img_url
            })
        except Exception as e:
            print(f"[Image Download Failed] {keyword} — {e}")

    return downloaded


def crawl_images_for_keywords(topic: str, keywords_str: str, count_per_keyword: int = 1) -> list:
    """
    주제와 키워드 문자열을 받아 각 키워드별로 이미지를 1컷씩 다운로드합니다.
    - count_per_keyword=1: 키워드당 1컷만 저장 (중복/오래된 이미지 방지)
    - 주제(topic)를 대표 검색어로 우선 사용
    - source_url 기준 전역 중복 제거

    Args:
        topic (str): 메인 주제 (대표 검색어)
        keywords_str (str): 쉼표 구분 키워드 문자열
        count_per_keyword (int): 키워드당 저장 컷 수 (기본 1)

    Returns:
        list of dict: 전체 다운로드된 이미지 목록
    """
    keyword_list = [k.strip() for k in keywords_str.split(",") if k.strip()]
    # 주제가 키워드 목록에 없으면 맨 앞에 추가
    if topic.strip() not in keyword_list:
        keyword_list.insert(0, topic.strip())

    all_images = []
    global_seen_urls: set = set()  # 전역 중복 URL 제거

    for kw in keyword_list:
        print(f"[서치대리] '{kw}' 이미지 {count_per_keyword}컷 수집 중...")
        imgs = crawl_naver_images(kw, count=count_per_keyword)
        for img in imgs:
            if img.get("source_url") not in global_seen_urls:
                global_seen_urls.add(img["source_url"])
                all_images.append(img)
        print(f"  → {len(imgs)}컷 다운로드 완료")

    return all_images


def get_naver_datalab_trends(keywords: list, days: int = 30) -> list:
    """
    네이버 데이터랩 검색어 트렌드 API로 키워드별 실제 검색량 지수를 조회합니다.
    발제 버튼을 누른 시점 기준 최근 days일간 데이터를 가져옵니다.

    Args:
        keywords: 검색량을 조회할 키워드 리스트 (최대 20개 권장)
        days: 조회 기간 (기본 30일)

    Returns:
        list of dict, recent_ratio 내림차순 정렬:
        [
          {
            "keyword": "재테크",
            "avg_ratio": 72.4,      # 조회 기간 전체 평균 (0~100)
            "recent_ratio": 85.1,   # 최근 2주 평균 (높을수록 지금 핫함)
            "peak_ratio": 100.0,    # 기간 내 최고 검색량
            "trend": "rising"       # rising / falling / stable
          }, ...
        ]
    """
    client_id, client_secret = get_naver_api_keys()
    if not client_id or not client_secret:
        print("[DataLab] Naver API 키 없음 — 데이터랩 조회 불가")
        return []

    end_date   = datetime.now()
    start_date = end_date - timedelta(days=days)
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id":     client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type":          "application/json",
    }

    results: dict = {}

    # 데이터랩 API: 요청 1건당 최대 5개 그룹 → 5개씩 배치 처리
    for batch_start in range(0, len(keywords), 5):
        batch = keywords[batch_start: batch_start + 5]
        body = {
            "startDate":     start_date.strftime("%Y-%m-%d"),
            "endDate":       end_date.strftime("%Y-%m-%d"),
            "timeUnit":      "week",
            "keywordGroups": [
                {"groupName": kw, "keywords": [kw]}
                for kw in batch
            ],
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("results", []):
                kw    = item["title"]
                ratios = [d["ratio"] for d in item.get("data", []) if d.get("ratio") is not None]
                if not ratios:
                    continue

                avg_ratio    = round(sum(ratios) / len(ratios), 1)
                peak_ratio   = round(max(ratios), 1)
                # 최근 2주 평균 (마지막 2개 주간 데이터)
                recent_slice = ratios[-2:] if len(ratios) >= 2 else ratios
                recent_ratio = round(sum(recent_slice) / len(recent_slice), 1)
                # 초반 2주와 비교해서 트렌드 방향 판단
                early_slice  = ratios[:2] if len(ratios) >= 2 else ratios
                early_ratio  = sum(early_slice) / len(early_slice)

                if   recent_ratio >= early_ratio * 1.15:
                    trend = "rising"    # 15% 이상 상승 → 급상승
                elif recent_ratio <= early_ratio * 0.85:
                    trend = "falling"   # 15% 이상 하락
                else:
                    trend = "stable"

                results[kw] = {
                    "keyword":      kw,
                    "avg_ratio":    avg_ratio,
                    "recent_ratio": recent_ratio,
                    "peak_ratio":   peak_ratio,
                    "trend":        trend,
                }

        except Exception as e:
            print(f"[DataLab Error] 배치 {batch_start}~{batch_start+len(batch)-1}: {e}")

    # recent_ratio 기준 내림차순 정렬 → 지금 가장 핫한 키워드 순
    return sorted(results.values(), key=lambda x: x["recent_ratio"], reverse=True)


if __name__ == "__main__":
    # Test
    res = get_context_for_ai("부동산 정책", 10, 10)
    print(res)
    print("\n--- 이미지 수집 테스트 ---")
    imgs = crawl_images_for_keywords("부동산 정책", "대출 규제, 청약", count_per_keyword=2)
    for img in imgs:
        print(img)
