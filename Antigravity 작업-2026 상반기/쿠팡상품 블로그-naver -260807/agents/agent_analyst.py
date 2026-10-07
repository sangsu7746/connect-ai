import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent

class AgentAnalyst(BaseAgent):
    """
    제시대리 (Strategy/Analysis Agent)
    포스팅된 글의 반응(조회수, 체류시간 등)을 평가하고, 과거 메모리를 학습하여
    네이버 로직(지침)에 부합하는 새로운 글쓰기 방향성(파라미터)을 제안합니다.
    (야간 배치 및 피드백 루프의 핵심 에이전트)
    """
    def __init__(self, client=None, model=None, temperature=None):
        super().__init__(agent_name="제시대리", client=client, model=model, temperature=temperature)

    def execute(self, post_title: str, stats_data: dict) -> dict:
        """
        포스팅 성과를 분석하고 메모리에 학습한 뒤, 다음 전략을 제안합니다.
        
        Args:
            post_title (str): 평가 대상 블로그 글 제목
            stats_data (dict): 조회수, 댓글수, 공감수 등의 통계 데이터 
                               (예: {"views": 1500, "comments": 12, "likes": 45, "score": 8.5})
        """
        system_instruction = "당신은 블로그 성과 데이터를 분석하고 다음 포스팅의 핵심 전략을 기획하는 똑똑한 '제시대리'입니다."
        
        # 1. 과거 메모리 로드
        memory = self.load_memory(days=30)
        
        # 2. 현재 환경 파라미터 로드
        current_params = self.load_params()
        
        # 성과 점수 산정 로직 (임의)
        score = stats_data.get("score", 0.0)
        if "views" in stats_data:
            # 조회수가 1000이상이면 긍정, 이하면 부정 등으로 score 조정 가능
            pass

        prompt = f"""
최근에 발행한 블로그 글의 성과 분석 및 차기 전략 기획을 요청합니다.

[최근 포스팅 제목]: {post_title}
[성과 데이터]:
{stats_data}

[과거 학습 메모리 (최근 30일)]:
{memory if memory else "기록 없음"}

[현재 시스템 파라미터]:
{current_params if current_params else "초기 상태"}

작업 지시:
1. 이번 성과(데이터)를 과거 메모리와 비교하여 평가해주세요.
2. 네이버 블로그 검색 노출 로직을 고려하여 다음 글 작성 시 적용할 전략(추천 주제, 피해야 할 키워드, 톤앤매너 변경 등)을 제시하세요.
3. 업데이트할 시스템 파라미터(JSON)를 반환해주세요.

아래 JSON 형식으로만 응답하세요.
```json
{{
  "analysis_summary": "오늘 성과에 대한 종합 평가 (2-3문장)",
  "next_strategy": "다음 글을 위한 핵심 제안 방향",
  "updated_params": {{
    "preferred_tone": "다음 글에 적용할 톤앤매너",
    "recommended_topic": "추천하는 차기 메인 주제",
    "keywords_to_avoid": ["피해야할단어1", "어뷰징키워드2"],
    "image_count_target": 7
  }}
}}
```
"""
        response_data = self.generate_content_with_cost(prompt, system_instruction=system_instruction)
        parsed_json = self.parse_json_from_text(response_data["text"])
        
        # 3. 파라미터 자동 갱신 저장
        if "updated_params" in parsed_json:
            self.save_params(parsed_json["updated_params"])
            
        # 4. 메모리에 성과 저장 (score가 기준 이상이면 reward, 미만이면 punishment)
        summary_text = f"제목: {post_title}\n성과: {stats_data}"
        self.save_memory(result_text=parsed_json.get("analysis_summary", "분석 실패"), score=score, summary=summary_text)

        return {
            "status": "success",
            "analysis": parsed_json,
            "usage": response_data.get("usage", {})
        }
