import os
import sys
import json
import logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent
from crawler import get_context_for_ai

logger = logging.getLogger(__name__)


class AgentSearch(BaseAgent):
    """
    서치대리 (Search Agent)
    4각도 멀티쿼리로 자료를 수집하고 글작가가 풍성하게 활용할 수 있는 구조화 JSON으로 정제합니다.

    수집 각도:
      1) 기본 주제 — 최신 뉴스·블로그 흐름
      2) 주제 + "통계 수치" — 구체적 데이터
      3) 주제 + "전문가 의견 분석" — 전문가 인용구
      4) 주제 + "사례 실제 후기" — 케이스스터디
    """
    def __init__(self, client=None, model=None, temperature=None):
        super().__init__(agent_name="서치대리", client=client, model=model, temperature=temperature)

    def execute(self, topic: str, keywords: str, news_count: int = 10, blog_count: int = 10, notebook_data: str = "") -> dict:
        """
        주제와 키워드를 기반으로 4각도 자료를 조사하고 정제합니다.

        Args:
            topic (str): 메인 주제
            keywords (str): 관련 키워드
            news_count (int): 수집 뉴스 개수
            blog_count (int): 수집 블로그 개수
            notebook_data (str): NotebookLM 등 외부 MCP에서 가져온 전문 지식 데이터
        """
        # ── 1. 4각도 멀티쿼리 크롤링 ──────────────────────────────────────
        angle_queries = [
            (topic,                         "기본"),
            (f"{topic} 통계 수치 공공기관 발표", "통계+출처"),
            (f"{topic} 전문가 의견 분석",     "전문가"),
            (f"{topic} 사례 실제 후기",       "사례"),
            (f"{topic} 추천 순위 비교",       "비교/추천"),
        ]

        raw_parts = []
        for query, label in angle_queries:
            try:
                ctx = get_context_for_ai(
                    query,
                    news_count=max(3, news_count // 2),
                    blog_count=max(3, blog_count // 2),
                )
                if ctx:
                    raw_parts.append(f"【{label} 검색: '{query}'】\n{ctx}")
                    logger.info(f"[서치대리] {label} 쿼리 수집 완료 ({len(ctx)}자)")
            except Exception as e:
                logger.warning(f"[서치대리] {label} 쿼리 실패 (무시): {e}")

        naver_raw_context = "\n\n".join(raw_parts) if raw_parts else "검색 결과 없음"

        # ── 2. 데이터 병합 ────────────────────────────────────────────────
        combined_context = f"【네이버 멀티쿼리 검색 결과】\n{naver_raw_context}\n\n"
        if notebook_data:
            combined_context += f"【NotebookLM 전문 지식】\n{notebook_data}\n"

        # TPM 초과 방지 — 컨텍스트 최대 8,000자
        if len(combined_context) > 8000:
            combined_context = combined_context[:8000] + "\n...(이하 생략)"

        # ── 3. LLM 구조화 추출 (확장 필드 — 수치·출처·사례·전문가 원본 보존) ──
        prompt = f"""당신은 네이버 블로그 포스팅을 위한 최고의 자료 조사 전문가 '서치대리'입니다.
아래 수집된 4각도 원본 데이터를 바탕으로 글작가가 풍성하고 전문적인 글을 쓸 수 있도록
구체적 수치·출처·사례·전문가 의견을 최대한 원본 그대로 보존하여 추출하세요.

[검색 주제]: {topic}
[관련 키워드]: {keywords}

[수집된 원본 데이터]
{combined_context}

아래 JSON 형식으로만 응답하세요.
```json
{{
  "seo_title_suggestions": [
    "타겟 키워드 전방 배치 + 호기심 유발 제목안 1",
    "타겟 키워드 전방 배치 + 호기심 유발 제목안 2",
    "타겟 키워드 전방 배치 + 호기심 유발 제목안 3"
  ],
  "geo_summary_block": {{
    "conclusion_1": "소비자 만족도가 가장 높은 핵심 요소는 [...]",
    "conclusion_2": "대표 브랜드로는 A, B, C 등이 있으며...",
    "conclusion_3": "최종 선택 시 [...] 기준을 확인하는 것이 핵심"
  }},
  "recommended_hashtags": [
    "#메인키워드", "#서브키워드1", "#서브키워드2",
    "#가격정보", "#구매전확인", "#상품정보"
  ],
  "benchmark_queries": [
    "메인키워드 추천 순위 TOP 5",
    "타겟고객층이 많이 쓰는 메인키워드 브랜드",
    "메인키워드 솔직 이용 후기 장단점",
    "벤치마크 쿼리 4",
    "벤치마크 쿼리 5",
    "벤치마크 쿼리 6",
    "벤치마크 쿼리 7",
    "벤치마크 쿼리 8",
    "벤치마크 쿼리 9",
    "벤치마크 쿼리 10"
  ],
  "core_facts": [
    "핵심 사실 1 — 수치·날짜·출처를 원본 그대로 보존한 문장형",
    "핵심 사실 2",
    "핵심 사실 3"
  ],
  "trends": [
    "현재 트렌드 1 (구체적 수치 포함)",
    "트렌드 2",
    "트렌드 3"
  ],
  "statistics_or_quotes": [
    "정확한 통계 수치 (출처·연도 포함) 예: '2025년 기준 DSR 40% 초과 가구 비율 31%, 금융위원회 발표'",
    "전문가 인용구 (발언자·직책 포함) 예: '홍길동 한국은행 부총재, 2025.03 기자회견'",
    "실제 사례 수치 예: '연소득 5천만 원 직장인 A씨, DSR 40% 적용 시 월 상환 한도 166만 원'"
  ],
  "case_studies": [
    {{
      "title": "사례 제목 (실제 후기·사례·판례 등)",
      "story": "2~3문장 구체적 스토리 — 수치·상황·결과 포함"
    }}
  ],
  "expert_quotes": [
    {{
      "speaker": "발언자 이름/직책/기관 (불명확하면 '익명 전문가')",
      "quote": "원문 또는 요약 인용구",
      "context": "발언 맥락 (날짜·상황 등)"
    }}
  ],
  "key_data_points": [
    "수치 데이터 포인트 1 — 글작가가 인용할 수 있는 형태 (단위·출처 포함)",
    "수치 데이터 포인트 2"
  ],
  "recommended_angle": "이 자료를 바탕으로 글작가가 취해야 할 가장 매력적인 글의 방향성 및 도입부 컨셉 (2~3문장)",
  "source_summary": "주요 출처 요약 (뉴스명·블로그명·발표기관 등)"
}}
```"""

        response_data = self.generate_content_with_cost(prompt)
        parsed_json = self.parse_json_from_text(response_data["text"])

        return {
            "status": "success",
            "topic": topic,
            "data": parsed_json,
            "raw_context": combined_context,
            "usage": response_data.get("usage", {})
        }


if __name__ == "__main__":
    agent = AgentSearch()
    res = agent.execute("부동산 정책", "대출 규제, 청약", news_count=10, blog_count=10)
    print(json.dumps(res, ensure_ascii=False, indent=2))
