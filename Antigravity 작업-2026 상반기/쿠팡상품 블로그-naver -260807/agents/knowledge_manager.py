import os
import sys
import json
import logging
import re
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

class AgentKnowledgeManager(BaseAgent):
    """
    지식정리대리 (AgentKnowledgeManager)
    작성 완료된 포스팅 본문에서 고신뢰성 팩트를 추출하여 지식(RAG)으로 축적하고,
    유사 주제 작성 시 공급해주는 지식 매니저입니다.
    """
    def __init__(self, client=None, model=None, temperature=None):
        super().__init__(agent_name="지식정리대리", client=client, model=model, temperature=temperature)
        
        # 지식 보관용 디렉토리 경로 지정
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.knowledge_dir = os.path.join(project_root, "knowledge")
        if not os.path.exists(self.knowledge_dir):
            os.makedirs(self.knowledge_dir)

    def _sanitize_filename(self, text: str) -> str:
        """파일명으로 사용할 수 없는 특수문자 제거"""
        return re.sub(r'[\/:*?"<>| ]', '_', text.strip())

    def save_knowledge(self, topic: str, keywords: str, content: str) -> dict:
        """
        포스팅 본문을 기반으로 팩트를 요약 정제하여 로컬 JSON 지식베이스에 축적합니다.
        """
        logger.info(f"[지식정리대리] '{topic}' 주제에서 핵심 팩트 추출 중...")

        system_instruction = (
            "당신은 정보의 왜곡 없이 고도로 압축된 상수의 팩트(제도, 수치, 기준, 금리 등)만 선별하는 '지식 구조화 전문가'입니다. "
            "주어진 글에서 영속적 가치를 갖는 정보성 데이터만 정밀하게 정형화(JSON)하여 추출하십시오."
        )

        prompt = f"""아래 네이버 블로그 원고 본문에서 향후 다른 글을 쓸 때 활용 가능한 핵심 정보(수치, 조건, 이율, 규정 등)를 3~5개 선별하여 한국어 문장 목록으로 요약하고, 관련 키워드를 추출하여 JSON 형식으로 출력하십시오.

[블로그 원고 본문]:
{content}

출력 형식 (반드시 아래 JSON 형태로만 작성, 다른 미사여구나 백틱 래퍼 외 텍스트는 배제):
```json
{{
  "verified_facts": [
    "DSR 40% 규제 적용 시, 연소득 5천만 원 기준 최대 대출 한도는 약 2억 원 내외임.",
    "2026년 청년 전용 버팀목 대출의 최저 적용 금리는 연 1.5% 수준임."
  ],
  "keywords": ["청년 전세대출", "버팀목대출", "DSR"]
}}
```
"""
        try:
            response_data = self.generate_content_with_cost(prompt, system_instruction=system_instruction)
            text = response_data["text"].strip()
            
            # JSON 블록 추출
            json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            json_text = json_match.group(1).strip() if json_match else text
            
            extracted = json.loads(json_text)
            verified_facts = extracted.get("verified_facts", [])
            extracted_keywords = extracted.get("keywords", [])
        except Exception as e:
            logger.warning(f"[지식정리대리] 팩트 요약 추출 실패 (폴백 적용): {e}")
            verified_facts = [f"{topic}에 관련된 데이터 및 핵심 수치 참고"]
            extracted_keywords = [k.strip() for k in keywords.split(",") if k.strip()]

        # 2) 파일명 생성 및 기존 지식 병합
        safe_name = self._sanitize_filename(topic)
        file_path = os.path.join(self.knowledge_dir, f"{safe_name}.json")

        existing_data = {}
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    existing_data = json.load(f)
            except Exception as re_err:
                logger.warning(f"[지식정리대리] 기존 지식 파일 로드 예외: {re_err}")

        # 병합 및 중복 제거
        combined_facts = existing_data.get("verified_facts", []) + verified_facts
        combined_facts = list(dict.fromkeys(combined_facts))  # 순서 보존 중복 제거

        combined_keywords = existing_data.get("keywords", []) + extracted_keywords
        combined_keywords = list(dict.fromkeys(combined_keywords))

        new_knowledge = {
            "topic": topic,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "verified_facts": combined_facts[:15],  # 최대 15개 팩트 누적 보존
            "keywords": combined_keywords[:10]      # 최대 10개 키워드 보존
        }

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(new_knowledge, f, ensure_ascii=False, indent=2)
            logger.info(f"[지식정리대리] 지식베이스에 성공적으로 저장/업데이트 완료: {file_path}")
        except Exception as we:
            logger.error(f"[지식정리대리] 지식베이스 파일 쓰기 실패: {we}")

        return new_knowledge

    def retrieve_knowledge(self, topic: str, keywords: str) -> str:
        """
        knowledge/ 디렉토리에 있는 모든 지식 파일들 중, 
        현재 주제 및 키워드와의 연관성 점수가 가장 높은 지식의 팩트 리스트를 문자열로 가져옵니다.
        """
        logger.info(f"[지식정리대리] '{topic}' 및 키워드 관련 과거 지식 검색 중...")
        
        search_words = set(re.findall(r'[a-zA-Z0-9가-힣]+', topic))
        for k in keywords.split(","):
            search_words.update(re.findall(r'[a-zA-Z0-9가-힣]+', k.strip()))

        best_score = 0
        best_data = None

        if not os.path.exists(self.knowledge_dir):
            return ""

        for file_name in os.listdir(self.knowledge_dir):
            if not file_name.endswith(".json"):
                continue
            
            file_path = os.path.join(self.knowledge_dir, file_name)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # 매칭 점수 계산
                score = 0
                # 1) 파일 카테고리/토픽명 매칭
                topic_words = set(re.findall(r'[a-zA-Z0-9가-힣]+', data.get("topic", "")))
                score += len(search_words.intersection(topic_words)) * 3
                
                # 2) 저장된 키워드 매칭
                stored_keywords = data.get("keywords", [])
                for sk in stored_keywords:
                    stored_words = set(re.findall(r'[a-zA-Z0-9가-힣]+', sk))
                    score += len(search_words.intersection(stored_words))

                if score > best_score:
                    best_score = score
                    best_data = data
            except Exception as e:
                logger.warning(f"[지식정리대리] 지식 파일 검색 실패: {file_name} | {e}")

        # 매칭된 가장 연관성이 높은 지식이 있을 경우 포맷팅
        # 최소 1점 이상의 연관성이 있는 경우에만 주입
        if best_data and best_score >= 1:
            facts = best_data.get("verified_facts", [])
            if facts:
                logger.info(f"[지식정리대리] 매칭 지식 발견 ✓ - 주제: '{best_data['topic']}' (매칭 점수: {best_score}점)")
                markdown_text = (
                    f"■ [과거 축적된 연관 지식 팩트 - 출처: {best_data['topic']}]:\n"
                    + "\n".join(f"  - {fact}" for fact in facts)
                )
                return markdown_text

        logger.info("[지식정리대리] 관련성이 높은 과거 축적 지식을 찾지 못했습니다. (생략)")
        return ""
