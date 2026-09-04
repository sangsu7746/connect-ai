import os
import sys
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent

class AgentAccountant(BaseAgent):
    """
    경리과장 (Accounting Manager Agent)
    파이프라인 실행 중 각 에이전트(서치, 글작가, 이미지, 편집)가 소모한
    API 토큰과 비용을 종합하여 분석하고, 향후 비용 절감을 위한 최적화 방안을 제시합니다.
    """
    def __init__(self, client=None, model=None, temperature=None):
        # 경리과장 전용 메모리를 사용할 수도 있지만 기본 베이스 메모리 구조 활용
        super().__init__(agent_name="경리과장", client=client, model=model, temperature=temperature)

    def execute(self, usage_data_list: list) -> dict:
        """
        비용 및 토큰 사용량을 분석하고 절감 방안을 제안합니다.
        
        Args:
            usage_data_list (list): 각 에이전트의 {"agent": "이름", "usage": {"total_tokens": 1000, ...}} 형태의 리스트
        """
        system_instruction = "당신은 AI API 사용량과 비용을 깐깐하게 관리하고, 품질 저하 없이 비용을 줄이는 팁을 제안하는 꼼꼼한 '경리과장'입니다."
        
        total_tokens = 0
        agent_usage = {}
        usage_summary = []
        for data in usage_data_list:
            agent_name = data.get("agent", "Unknown")
            tokens = data.get("usage", {}).get("total_tokens", 0)
            total_tokens += tokens
            agent_usage[agent_name] = tokens
            usage_summary.append(f"- {agent_name}: {tokens} 토큰")

        # 메모리 로드: 과거 경리과장의 비용 절감 메모리가 있는지 확인
        memory = self.load_memory(days=15)

        prompt = f"""
아래는 이번 블로그 포스팅 파이프라인에서 각 에이전트가 소모한 API 토큰 내역입니다.

[사용 내역]:
{chr(10).join(usage_summary)}
총합: {total_tokens} 토큰

[과거 학습 메모리 (비용 절감 성공/실패 사례)]:
{memory if memory else "기록 없음"}

작업 지시:
1. 이번 작업의 비용 효율성을 평가해주세요. (어느 에이전트가 가장 많이 썼는지 파악)
2. 품질을 유지하면서 다음 작업 시 토큰을 절감할 수 있는 구체적인 프롬프트 최적화 방안이나 모델 변경 제안을 작성해주세요.

아래 JSON 형식으로 응답하세요.
```json
{{
  "evaluation": "이번 비용 효율성에 대한 짧은 평가",
  "cost_saving_tip": "다음 글 작성 시 절감 팁 (예: 서치대리 문서 요약본 길이 제한 등)",
  "recommended_model_adjustments": "특정 에이전트에 더 가벼운 모델 적용 권장 여부 등"
}}
```
"""
        response_data = self.generate_content_with_cost(prompt, system_instruction=system_instruction)
        parsed_json = self.parse_json_from_text(response_data["text"])
        
        # 비용 효율성이 아주 떨어지는 경우(예: 기준치 초과) Punishment로 기록 가능
        # 여기서는 단순히 분석 결과를 반환
        
        return {
            "status": "success",
            "total_tokens": total_tokens,
            "agent_usage": agent_usage,
            "analysis": parsed_json,
            "usage": response_data.get("usage", {})
        }
