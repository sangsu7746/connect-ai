import os
import sys
import time
import logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.base_agent import BaseAgent
from prompts import PROMPT_TOPIC_AGENT_SINGLE, TOPIC_CATEGORY_KEYWORDS
from crawler import get_context_for_ai, get_naver_datalab_trends

# 키워드별 LLM 호출 사이의 쿨다운(초). Qwen3(6,000 TPM) 한도를
# 개별 요청 크기를 줄이는 것만으로는 피할 수 없어(짧은 간격 연속 호출 시 누적 초과),
# agent_writer.py와 동일하게 호출 간 쿨다운을 둔다.
TOPIC_LLM_COOLDOWN_SEC = 20

logger = logging.getLogger(__name__)

class AgentTopic(BaseAgent):
    """
    [발제 대리]
    특정 카테고리와 매핑된 해시태그를 기반으로 최신 트렌드를 크롤링하고,
    LLM을 통해 조회수 폭발을 유도할 수 있는 Top 5 블로그 주제를 발굴합니다.
    """
    def __init__(self, client=None, model=None, temperature=None):
        super().__init__(agent_name="발제대리", client=client, model=model, temperature=temperature)
        
    def execute(self, category: str) -> dict:
        """
        주제 발굴을 실행합니다. 발제 버튼을 누른 시점의 날짜를 기준으로
        네이버 데이터랩 실제 검색량 데이터를 바탕으로 상위 키워드를 분석합니다.

        Args:
            category: 대시보드 콤보박스에서 선택된 분야 (예: '📱 IT디지털')
        Returns:
            dict: {
                "status": "success",
                "topics": [ { "rank": 1, "keyword": "...", "recommended_title": "...", "reason": "..." }, ... ],
                "usage": {...}
            }
        """
        # ── 발제 버튼을 누른 시점의 날짜 캡처 ────────────────────────────
        now = datetime.now()
        year      = now.year
        month     = now.month
        month_str = f"{year}년 {month}월"
        date_str  = now.strftime("%Y년 %m월 %d일")

        logger.info(f"💡 [발제대리] '{category}' 분야 트렌드 분석 시작... (기준 시점: {date_str})")

        # 1. 분야별 해시태그 가져오기
        keywords_str = TOPIC_CATEGORY_KEYWORDS.get(
            category, TOPIC_CATEGORY_KEYWORDS.get("✨ 전문가 작성 (기본)")
        )
        keyword_list = [k.replace("#", "").strip() for k in keywords_str.split(",") if k.strip()]

        # 2. 네이버 데이터랩 실제 검색량 조회 (A안 — 실제 검색량 지수 기반)
        logger.info(f"💡 [발제대리] 데이터랩 검색량 조회 중... ({len(keyword_list)}개 키워드)")
        datalab_results = []
        try:
            datalab_results = get_naver_datalab_trends(keyword_list, days=30)
            logger.info(f"💡 [발제대리] 데이터랩 조회 완료 — {len(datalab_results)}개 키워드 데이터 확보")
        except Exception as e:
            logger.warning(f"[발제대리] 데이터랩 조회 실패: {e}")

        # 3. 데이터랩 결과를 키워드별로 조회할 수 있도록 매핑
        trend_icon = {"rising": "📈", "stable": "➡️", "falling": "📉"}
        datalab_map = {item["keyword"]: item for item in datalab_results}

        # 4. 상위 5개 키워드를 "키워드 1개당 크롤링 + LLM 호출 1회"로 분리 처리.
        #    5개를 한 프롬프트로 합치면 Qwen3(6,000 TPM) 한도를 넘기므로,
        #    키워드별로 쪼개 호출하고 사이사이 쿨다운을 둬서 분당 누적 토큰도 회피한다.
        top_keywords = [item["keyword"] for item in datalab_results[:5]] if datalab_results else keyword_list[:5]

        system_instruction = (
            f"당신은 네이버 블로그 검색 유입 트렌드를 분석하는 '발제 대리'입니다. "
            f"오늘은 {date_str}입니다. "
            f"제공된 데이터랩 실제 검색량 지수를 최우선 근거로 삼아 "
            f"반드시 {month_str} 기준의 최신 트렌드만 제안하세요."
        )

        topics = []
        usage_total = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}

        for idx, kw in enumerate(top_keywords):
            item = datalab_map.get(kw)
            if item:
                icon = trend_icon.get(item.get("trend", "stable"), "➡️")
                datalab_line = (
                    f"[{icon} {item['trend'].upper()}] \"{kw}\" "
                    f"| 최근2주 지수: {item['recent_ratio']} "
                    f"| 전체 평균: {item['avg_ratio']} "
                    f"| 최고: {item['peak_ratio']}"
                )
            else:
                datalab_line = f"데이터랩 조회 불가. {month_str} 기준 검색량을 추론해주세요."

            try:
                chunk = get_context_for_ai(f"{kw} {month_str}", news_count=5, blog_count=5)
                crawled_data_kw = chunk if chunk and len(chunk.strip()) > 30 else f"{month_str} 기준 '{kw}' 크롤링 데이터 없음."
                logger.info(f"💡 [발제대리] '{kw}' 뉴스·블로그 수집 완료")
            except Exception as e:
                crawled_data_kw = f"{month_str} 기준 '{kw}' 크롤링 데이터 없음."
                logger.warning(f"[발제대리] '{kw}' 뉴스·블로그 크롤링 실패: {e}")

            prompt = PROMPT_TOPIC_AGENT_SINGLE.format(
                category=category,
                keyword=kw,
                datalab_line=datalab_line,
                crawled_data=crawled_data_kw,
                today=date_str,
                year=year,
                month_str=month_str,
            )

            try:
                response_data = self.generate_content_with_cost(
                    prompt, system_instruction=system_instruction
                )
                parsed_json = self.parse_json_from_text(response_data["text"])
                if parsed_json.get("recommended_title"):
                    topics.append({
                        "rank": idx + 1,
                        "keyword": parsed_json.get("keyword", kw),
                        "recommended_title": parsed_json["recommended_title"],
                        "reason": parsed_json.get("reason", ""),
                    })
                for k in usage_total:
                    usage_total[k] += response_data.get("usage", {}).get(k, 0)
                logger.info(f"💡 [발제대리] '{kw}' 주제 분석 완료.")
            except Exception as e:
                logger.warning(f"[발제대리] '{kw}' LLM 분석 실패 (건너뜀): {e}")

            # 다음 키워드 호출 전 쿨다운 (분당 누적 토큰 한도 회피). 마지막 키워드는 대기 불필요.
            if idx < len(top_keywords) - 1:
                time.sleep(TOPIC_LLM_COOLDOWN_SEC)

        if not topics:
            logger.error("[발제대리] 모든 키워드 분석 실패 — 제안 가능한 주제 없음.")
            return {
                "status": "error",
                "topics": [],
                "error": "모든 키워드에 대한 주제 분석이 실패했습니다.",
            }

        logger.info(f"💡 [발제대리] 분석 완료. {len(topics)}개 주제 제안.")
        return {
            "status": "success",
            "topics": topics,
            "reference_date": date_str,
            "datalab_summary": datalab_results[:5],
            "usage": usage_total,
        }
