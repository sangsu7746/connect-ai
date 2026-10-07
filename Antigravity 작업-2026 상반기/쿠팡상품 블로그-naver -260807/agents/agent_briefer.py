"""
agent_briefer.py
자료정리대리 (Research Brief Agent)

서치대리의 원자료 + 글작가의 목차(outline)를 받아
각 섹션에 실제로 써야 할 팩트·수치·사례·전문가 의견을 매핑합니다.

글작가의 2단계 섹션 작성 시 주입되어
"빈 섹션" / "일반론만 가득한 섹션" 현상을 방지합니다.
"""
import os
import sys
import json
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class AgentBriefer(BaseAgent):
    """
    자료정리대리 — 섹션별 팩트 묶음 생성

    입력:
      - search_data: 서치대리 execute()['data'] — 확장 필드 포함
      - outline:     글작가 1단계 목차 리스트 [{"title": ..., "image_hint": ...}, ...]
      - topic:       메인 주제

    출력:
      - section_briefs: [
          {
            "title": "섹션 제목",
            "image_hint": "이미지 힌트",
            "facts": ["이 섹션에 쓸 핵심 사실 1", ...],
            "data_points": ["수치·통계 1", ...],
            "case_study": {"title": ..., "story": ...} | None,
            "expert_quote": {"speaker": ..., "quote": ..., "context": ...} | None,
            "writing_tip": "이 섹션의 글쓰기 방향 한 줄 요약"
          },
          ...
        ]
    """
    def __init__(self, client=None, model=None, temperature=None):
        super().__init__(agent_name="자료정리대리", client=client, model=model, temperature=temperature)

    def execute(self, topic: str, search_data: dict, outline: list) -> dict:
        """
        섹션별 팩트 매핑 테이블을 생성합니다.

        Args:
            topic (str): 메인 주제
            search_data (dict): 서치대리 정제 결과
            outline (list): 글작가 1단계 목차

        Returns:
            dict: {"section_briefs": [...], "usage": {...}}
        """
        if not outline:
            logger.warning("[자료정리대리] 목차가 비어있어 브리프 생성 생략")
            return {"section_briefs": [], "usage": {}}

        search_summary = json.dumps(search_data, ensure_ascii=False, indent=2)
        outline_text = "\n".join(
            f"  {i+1}. {s.get('title', '')} (이미지힌트: {s.get('image_hint', '')})"
            for i, s in enumerate(outline)
        )

        prompt = f"""당신은 블로그 원고 작성을 위한 섹션별 자료 배분 전문가 '자료정리대리'입니다.
아래 [조사 자료]를 분석하여 각 [목차 섹션]에 가장 적합한 팩트·수치·사례·전문가 의견을 배분하세요.

[전체 주제]: {topic}

[목차 섹션 목록]:
{outline_text}

[조사 자료 (서치대리 수집 결과)]:
{search_summary}

규칙:
- 각 섹션에 겹치지 않게 자료를 배분할 것 (같은 수치를 두 섹션에 중복 배치하지 말 것)
- 자료가 부족한 섹션은 writing_tip으로 글쓰기 방향을 구체적으로 안내할 것
- case_study와 expert_quote는 가장 잘 맞는 섹션에 1개씩만 배치 (없으면 null)
- 수치는 반드시 단위·출처까지 포함하여 원본 그대로 기재

아래 JSON 형식으로만 응답하세요.
```json
[
  {{
    "title": "섹션 1 제목 (목차와 동일하게)",
    "image_hint": "이미지 힌트 (목차와 동일하게)",
    "facts": [
      "이 섹션에서 글작가가 반드시 언급해야 할 핵심 사실 1",
      "핵심 사실 2"
    ],
    "data_points": [
      "이 섹션에서 인용할 구체적 수치·통계 (단위·출처 포함)",
      "수치 2"
    ],
    "case_study": {{
      "title": "사례 제목",
      "story": "구체적 스토리 2~3문장"
    }},
    "expert_quote": {{
      "speaker": "발언자/직책/기관",
      "quote": "인용구",
      "context": "발언 맥락"
    }},
    "writing_tip": "이 섹션을 어떤 방향·각도로 쓰면 좋은지 한 줄 요약"
  }},
  {{
    "title": "섹션 2 제목",
    "image_hint": "이미지 힌트",
    "facts": ["사실 1", "사실 2"],
    "data_points": ["수치 1"],
    "case_study": null,
    "expert_quote": null,
    "writing_tip": "섹션 2 글쓰기 방향"
  }}
]
```"""

        try:
            res = self.generate_content_with_cost(prompt)
            parsed = self.parse_json_from_text(res["text"])

            if not isinstance(parsed, list):
                raise ValueError("응답이 리스트 형태가 아님")

            # outline과 길이가 다르면 outline 기준으로 채움
            section_briefs = []
            for i, sec in enumerate(outline):
                if i < len(parsed):
                    brief = parsed[i]
                    brief.setdefault("title", sec.get("title", ""))
                    brief.setdefault("image_hint", sec.get("image_hint", ""))
                    brief.setdefault("facts", [])
                    brief.setdefault("data_points", [])
                    brief.setdefault("case_study", None)
                    brief.setdefault("expert_quote", None)
                    brief.setdefault("writing_tip", "")
                    section_briefs.append(brief)
                else:
                    # 자료 부족 시 기본 브리프
                    section_briefs.append({
                        "title": sec.get("title", ""),
                        "image_hint": sec.get("image_hint", ""),
                        "facts": [],
                        "data_points": [],
                        "case_study": None,
                        "expert_quote": None,
                        "writing_tip": f"'{sec.get('title','')}' 주제와 관련된 전문 지식과 실전 경험을 풀어서 작성",
                    })

            logger.info(f"[자료정리대리] 섹션 브리프 생성 완료 ({len(section_briefs)}개 섹션)")
            return {"section_briefs": section_briefs, "usage": res.get("usage", {})}

        except Exception as e:
            logger.warning(f"[자료정리대리] 브리프 생성 실패 ({e}) — 빈 브리프로 폴백")
            return {
                "section_briefs": [
                    {
                        "title": s.get("title", ""),
                        "image_hint": s.get("image_hint", ""),
                        "facts": [],
                        "data_points": [],
                        "case_study": None,
                        "expert_quote": None,
                        "writing_tip": "",
                    }
                    for s in outline
                ],
                "usage": {},
            }
