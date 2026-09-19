import os
import sys
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.base_agent import BaseAgent
from prompts import get_theme_prompt, TEMPLATE_LISTICLE

# ══════════════════════════════════════════════════════════════════════════════
# 네이버 블로그 SmartEditor ONE 검증 이모지 세트
# 네이버 블로그에서 정상 표시되는 유니코드 이모지를 맥락별로 정리했습니다.
# 글작가는 반드시 이 목록에서만 선택하여 사용합니다.
# ══════════════════════════════════════════════════════════════════════════════
NAVER_EMOJI_SET = {
    "제목·포인트": "⭐ 🌟 ✨ 🎯 🔥 💥 🏆 🥇 👑 💎",
    "확인·체크":   "✅ ☑️ ✔️ 🆗 💯 👌",
    "번호·순서":   "1️⃣ 2️⃣ 3️⃣ 4️⃣ 5️⃣ 6️⃣ 7️⃣ 8️⃣ 9️⃣ 🔢",
    "화살표·방향": "➡️ ⬆️ ⬇️ ↗️ 👉 👆 👇 🔽 🔼",
    "팁·정보":     "💡 📌 📝 📢 📣 ℹ️ 🔔 📍 🗒️",
    "돈·재테크":   "💰 💵 💳 📈 📉 📊 🤑 💹 🏦",
    "부동산·집":   "🏠 🏡 🏢 🔑 🏗️ 🏘️ 🛖 🏛️",
    "사람·감정":   "😊 😍 🥰 😎 🤔 😮 🙌 👏 💪 🤝",
    "좋아요·응원": "👍 ❤️ 🧡 💛 💚 💙 💜 🖤 🤍",
    "주의·경고":   "⚠️ ❗ ❕ 🚨 🔴 🟡 🟢",
    "시간·날짜":   "📅 🗓️ ⏰ 🕐 🕑 🕒 📆",
    "검색·분석":   "🔍 🔎 🧐 📋 📑 🗂️ 📂",
    "결론·마무리": "🎉 🥳 👏 🙏 🎊 🎈 🎁",
    "기타유용":    "🌈 ☀️ 🌙 ⚡ 🌊 🍀 🚀 🛡️ 🔒 📱",
}

# 프롬프트에 삽입할 이모지 가이드 문자열
_EMOJI_GUIDE = "\n".join(
    f"  [{cat}]: {emojis}"
    for cat, emojis in NAVER_EMOJI_SET.items()
)


# ══════════════════════════════════════════════════════════════════════════════
# 테마별 전문가 페르소나 매핑
# 블로그 분야(테마)가 선택되면 글작가는 해당 분야의 10년 이상 최고 전문가가 됩니다.
# ══════════════════════════════════════════════════════════════════════════════
_THEME_PERSONA = {
    "💼 비즈니스":         "비즈니스·창업·마케팅·경영",
    "🏃 운동건강":         "운동·건강·다이어트·피트니스",
    "🏠 일상라이프":       "생활 꿀팁·라이프스타일·정리정돈·살림",
    "🧠 자기계발":         "자기계발·성장·습관·마인드셋",
    "💰 재테크":           "재테크·투자·부동산·금융",
    "🛍️ 제품리뷰":        "제품 리뷰·소비자 가이드·가성비 분석",
    "🎬 취미엔터":         "취미·엔터테인먼트·문화생활·여가",
    "📱 IT디지털":         "IT·디지털·테크·소프트웨어",
    "✨ 전문가 작성 (기본)": "네이버 블로그 콘텐츠 기획·작성",
}


class AgentWriter(BaseAgent):
    """
    글작가 (Writer Agent)
    서치대리가 수집한 자료와 편집장의 톤앤매너 지시를 바탕으로 원고 초안(HTML)을 작성합니다.

    작성 방식 (3단계):
        1단계 _make_outline()  : 목차(H2 3~4개) 확정
        2단계 _write_sections(): 각 목차별 핵심 단락 간략 작성
        3단계 execute()        : 목차+단락 조합으로 최종 HTML 완성

    원칙:
        - 선택된 테마 분야의 10년 이상 현장 전문가 페르소나로 작성
        - 서론·결론 없이 본문 핵심 내용에만 집중
        - 이미지 마커 최소 4컷 보장 (각 H2 단락 1:1 대응), 단락 맞춤 상세 영문 프롬프트 생성
        - 네이버 SmartEditor ONE 검증 이모지만 사용
    """
    def __init__(self, client=None, model=None, temperature=None):
        super().__init__(agent_name="글작가", client=client, model=model, temperature=temperature)

    @staticmethod
    def _get_persona(theme_name: str) -> str:
        """테마 이름으로부터 전문가 페르소나 문자열을 반환합니다."""
        field = _THEME_PERSONA.get(theme_name, "네이버 블로그 콘텐츠 기획·작성")
        return (
            # '10년 경력 최고 전문가'는 사실이 아니다. 페르소나가 경력을 사칭하면
            # 모델이 그 경력을 근거로 없는 현장 경험을 지어낸다.
            f"나는 {field} 분야를 조사해 정리하는 블로그 글작가입니다. "
            f"직접 겪지 않은 일을 겪은 것처럼 쓰지 않고, 확인한 자료를 근거로, "
            f"독자가 바로 실행에 옮길 수 있는 구체적이고 신뢰도 높은 글을 쓰는 것이 나의 사명입니다."
        )

    # ──────────────────────────────────────────────────────────────
    # [1단계] 목차 확정
    # ──────────────────────────────────────────────────────────────
    def _make_outline(self, topic: str, keywords: str, search_data: dict,
                      tone_and_manner: str,
                      theme_name: str = "✨ 전문가 작성 (기본)",
                      article_type: str = "📝 일반 포스팅 (기본)",
                      brand_name: str = "") -> list[str]:
        """
        주제와 조사 자료를 바탕으로 H2 목차 3~4개를 확정합니다.
        서론·결론 섹션은 포함하지 않습니다.

        Returns:
            list[str]: 목차 제목 리스트 (예: ["핵심 변화 3가지", "실전 활용법", "주의할 점"])
        """
        import logging
        logger = logging.getLogger(__name__)
        search_summary = json.dumps(search_data, ensure_ascii=False, indent=2)
        persona = self._get_persona(theme_name)

        knowledge_context = search_data.get("knowledge_context", "")
        knowledge_block = ""
        if knowledge_context:
            knowledge_block = f"\n[로컬 검증 지식 데이터베이스 (우선 반영)]: \n{knowledge_context}\n"

        prompt = f"""[전문가 페르소나]: {persona}

당신은 위 페르소나를 가진 네이버 블로그 글의 목차를 설계하는 전문 편집자입니다.

[주제]: {topic}
[키워드]: {keywords}
[편집 방향]: {tone_and_manner}
[글 유형]: {article_type} (리스티클인 경우 반드시 추천 TOP 5 비교 구조 포함)
[조사 자료 요약]:
{search_summary}
{knowledge_block}

아래 조건을 엄수하여 목차를 설계해주세요:
- H2 섹션 3~4개만 구성 (서론/결론/마무리 섹션 절대 포함하지 말 것)
- 각 섹션은 독자에게 실질적인 정보를 전달하는 핵심 제목으로 작성
- 제목은 독자의 궁금증을 해소하거나 행동을 유도하는 방향으로
- 각 섹션에 어떤 이미지가 필요한지 한 줄로 메모 추가

JSON 배열로만 응답하세요:
```json
[
  {{"title": "목차 제목1 (독자 관심 유발형)", "image_hint": "이 섹션에 어울리는 이미지 한 줄 설명"}},
  {{"title": "목차 제목2", "image_hint": "이미지 힌트"}},
  {{"title": "목차 제목3", "image_hint": "이미지 힌트"}}
]
```"""

        res = self.generate_content_with_cost(prompt)
        try:
            outline = self.parse_json_from_text(res["text"])
            if isinstance(outline, list) and len(outline) >= 2:
                logger.info(f"[글작가] 1단계 목차 확정: {[o.get('title') for o in outline]}")
                return outline
        except Exception:
            pass
        # 파싱 실패 시 기본 목차 반환
        logger.warning("[글작가] 목차 파싱 실패 — 기본 목차 사용")
        return [
            {"title": f"{topic} 핵심 정리", "image_hint": f"{topic} 관련 정보 이미지"},
            {"title": "실전 활용 방법",      "image_hint": "실제 활용 장면 이미지"},
            {"title": "꼭 알아야 할 주의점", "image_hint": "주의/경고 관련 이미지"},
        ]

    # ──────────────────────────────────────────────────────────────
    # [2단계] 목차별 핵심 단락 작성
    # ──────────────────────────────────────────────────────────────
    def _write_sections(self, topic: str, outline: list[dict],
                        search_data: dict, tone_and_manner: str,
                        theme_name: str = "✨ 전문가 작성 (기본)",
                        section_briefs: list = None,
                        article_type: str = "📝 일반 포스팅 (기본)",
                        brand_name: str = "") -> list[dict]:
        """
        확정된 목차 각각에 대해 핵심 단락을 간략히 작성합니다.
        서론·결론 없이 해당 섹션의 정보에만 집중합니다.

        Returns:
            list[dict]: [{"title": ..., "body": ...(HTML 단편), "image_hint": ...}, ...]
        """
        import logging
        logger = logging.getLogger(__name__)
        search_summary = json.dumps(search_data, ensure_ascii=False, indent=2)
        persona = self._get_persona(theme_name)

        knowledge_context = search_data.get("knowledge_context", "")
        knowledge_block = ""
        if knowledge_context:
            knowledge_block = f"\n[로컬 검증 지식 데이터베이스 (우선 반영)]: \n{knowledge_context}\n"

        sections = []

        for idx, section in enumerate(outline, 1):
            sec_title = section.get("title", f"섹션{idx}")
            image_hint = section.get("image_hint", "")

            # 자료정리대리 브리프 — 이 섹션에 쓸 팩트·수치·사례 묶음
            brief = section_briefs[idx - 1] if section_briefs and idx - 1 < len(section_briefs) else {}
            brief_block = ""
            if brief:
                brief_parts = []
                if brief.get("facts"):
                    brief_parts.append("  [반드시 언급할 핵심 사실]:\n" +
                                       "\n".join(f"    • {f}" for f in brief["facts"]))
                if brief.get("data_points"):
                    brief_parts.append("  [인용할 수치·통계 (단위·출처 그대로 사용)]:\n" +
                                       "\n".join(f"    • {d}" for d in brief["data_points"]))
                if brief.get("case_study"):
                    cs = brief["case_study"]
                    brief_parts.append(f"  [실제 사례 — 스토리로 녹여낼 것]:\n"
                                       f"    제목: {cs.get('title','')}\n"
                                       f"    내용: {cs.get('story','')}")
                if brief.get("expert_quote"):
                    eq = brief["expert_quote"]
                    brief_parts.append(f"  [전문가 인용구 — 글에 녹여낼 것]:\n"
                                       f"    발언자: {eq.get('speaker','')}\n"
                                       f"    인용: {eq.get('quote','')}\n"
                                       f"    맥락: {eq.get('context','')}")
                if brief.get("writing_tip"):
                    brief_parts.append(f"  [이 섹션 글쓰기 방향]: {brief['writing_tip']}")
                if brief_parts:
                    brief_block = "\n[자료정리대리 섹션 브리프 — 이 자료를 반드시 본문에 녹여낼 것]:\n" + "\n".join(brief_parts) + "\n"

            # 이전 섹션 맥락 — 톤·용어·흐름 일관성을 위해 앞 섹션 스니펫 전달
            if sections:
                prev_lines = []
                for s in sections:
                    snippet = s["body"][:200].replace("\n", " ")
                    prev_lines.append(f"  ▶ [{s['title']}]: {snippet}…")
                prev_context_block = (
                    "\n[앞에서 이미 작성된 섹션 — 문체·핵심 용어·어조를 반드시 이어받을 것]:\n"
                    + "\n".join(prev_lines)
                    + "\n"
                )
            else:
                prev_context_block = ""

            prompt = f"""[전문가 페르소나]: {persona}

당신은 위 페르소나를 가진 네이버 블로그 전문 글작가입니다.
해당 분야의 10년 이상 현장 경험에서 나오는 구체적인 실전 노하우와 데이터로 아래 섹션을 작성하세요.

[전체 주제]: {topic}
[편집 방향]: {tone_and_manner}
[조사 자료]:
{search_summary}
{knowledge_block}
{brief_block}{prev_context_block}
[작성할 섹션]: {sec_title}
[이 섹션의 이미지 힌트]: {image_hint}

작성 규칙:
1. 이 섹션의 핵심 정보만 구체적으로 작성 (서론·결론 문장 절대 금지)
2. "안녕하세요", "오늘은 ~에 대해", "마지막으로" 등 군더더기 표현 절대 금지
3. 본문 첫 문장부터 임팩트 있는 핵심 정보 또는 통계 수치로 시작
4. HTML 태그를 제외한 순수 텍스트 기준 최소 500자 이상 — 실질적인 통계, 팁, 상세 예시를 포함해 풍부하게 서술
5. 동일 단어·문장 구조·이모지가 연속 반복되지 않도록 다양한 표현 사용
6. 이모지는 단락당 최대 1개 — 아래 [허용 이모지] 목록에서만 선택
7. 글자색(color) CSS 속성 절대 사용 금지
8. 한자(漢字)는 절대 사용 금지 — 모든 한자어는 한글로 표기 (예: 不動産 → 부동산, 金利 → 금리)
9. 문맥 일관성 (앞 섹션이 있을 경우 필수):
   ▸ 앞 섹션에서 사용한 핵심 용어·비유는 이 섹션에서도 동일하게 사용 (다른 단어로 바꾸지 말 것)
   ▸ 앞 섹션과 동일한 문체(구어체/문어체) 유지 — 갑작스러운 어조 전환 절대 금지
   ▸ 독자 입장에서 "같은 필자가 연속으로 쓴 글"임이 자연스럽게 느껴져야 함
10. 네이버 DIA+ 알고리즘 최적화 — 단, 체험을 지어내지 말 것:
    ▸ DIA+ 가 보는 것은 '체험한 척'이 아니라 **구체성**이다. 없는 경험을 만들지 말고,
      조건·기준·수치를 구체적으로 써서 정보의 밀도를 올려라.
    ▸ 금지: "써보니 좋더라고요", "비교해 보니 알겠더라고요" 같은 1인칭 체험 인용구.
      실제로 겪지 않은 일이고, 광고 글에서는 허위 후기가 된다.
    ▸ 권장: "○○ 기준으로는 △△이다", "□□인 경우에는 맞지 않는다" 처럼 판단 근거를 밝힌다.
    ▸ 하이퍼링크 남발 금지 — 텍스트 자체에 브랜드명을 자연스럽게 녹여 앵커 텍스트 효과를 낼 것
11. 통계 + 출처 신뢰도 강화 (AI 검색 엔진 Authority 점수 향상):
    ▸ 자료정리대리가 제공한 data_points에 출처가 있으면 반드시 아래 패턴으로 인용:
      "최근 [공공기관/학회/연구소]에서 발표한 자료에 따르면, 전체 이용자의 약 XX%가 [문제점]을 가장 큰 고민으로 꼽았습니다."
    ▸ 자체 데이터가 있으면: "자체 분석 결과 기존 대비 XX%의 효율성 개선을 기록하며..."

[허용 이모지]:
{_EMOJI_GUIDE}

출력 형식:

[섹션 제목]
(이 섹션의 제목 — HTML 태그 없이 순수 텍스트만. 예: "실전 활용 방법")

[섹션 본문]
(완성된 HTML 단편. <h2>, <p>, <strong>, <ul><li> 등 사용)
"""

            res = self.generate_content_with_cost(prompt)
            body_text = res["text"].strip()

            # [섹션 제목] / [섹션 본문] 구분 파싱
            import re as _re
            if "[섹션 본문]" in body_text:
                parts = body_text.split("[섹션 본문]", 1)
                parsed_title = parts[0].replace("[섹션 제목]", "").strip() or sec_title
                parsed_body  = parts[1].strip()
            else:
                parsed_title = sec_title
                parsed_body  = body_text

            # 제목에 HTML 태그가 섞여 오면(예: "<h2>제목</h2>") 순수 텍스트만 남긴다.
            # 이후 execute()에서 "## {title}" 형태로 마크다운 접두사를 또 붙이므로,
            # 태그가 남아있으면 "## <h2>...</h2>" 같은 깨진 헤딩이 생성된다.
            parsed_title = _re.sub(r"<[^>]+>", "", parsed_title).strip() or sec_title

            # 마크다운 코드블록 래퍼 제거
            parsed_body = _re.sub(r"^```[a-zA-Z]*\n?", "", parsed_body)
            parsed_body = _re.sub(r"\n?```$", "", parsed_body.strip())

            sections.append({
                "title":      parsed_title,
                "body":       parsed_body,
                "image_hint": image_hint,
            })
            logger.info(f"[글작가] 2단계 섹션 {idx}/{len(outline)} 완성: '{parsed_title}' ({len(parsed_body)}자)")

        return sections

    # ──────────────────────────────────────────────────────────────
    # [4단계] 자기검토 — 품질 점검 후 부족 섹션 보완
    # ──────────────────────────────────────────────────────────────
    def _self_review(self, topic: str, content: str, sections: list,
                     theme_name: str = "✨ 전문가 작성 (기본)") -> str:
        """
        완성 원고를 스스로 점검하고 부족한 섹션을 선택적으로 보완합니다.

        점검 항목:
          1. 각 섹션에 구체적 수치·데이터가 있는가?
          2. 맥락이 갑자기 끊기는 문장이 있는가?
          3. 전문가 의견·실제 사례가 없는 섹션이 있는가?
          4. 일반론만 가득하고 실질 정보가 없는 섹션이 있는가?

        Returns:
            str: 보완된 HTML (변경 없으면 원본 그대로)
        """
        import logging as _log
        _logger = _log.getLogger(__name__)

        persona = self._get_persona(theme_name)
        section_list = "\n".join(f"  {i+1}. {s['title']}" for i, s in enumerate(sections))

        # 원고가 너무 길면 잘라서 검토 (8,000자 기준)
        content_preview = content if len(content) <= 8000 else content[:8000] + "\n...(이하 생략)"

        review_prompt = f"""[전문가 페르소나]: {persona}

당신은 완성된 블로그 원고를 최종 점검하는 수석 글작가입니다.
아래 원고를 읽고 품질 기준에 미달하는 섹션을 찾아 보완하세요.

[주제]: {topic}
[목차 구성]:
{section_list}

[완성 원고]:
{content_preview}

━━━━━━━━━━━━━━━━━━━━━━━━
【점검 및 보완 기준】

1. 수치·데이터 부재 — 각 H2 섹션에 구체적 수치(%, 원, 건수, 날짜 등)가 최소 1개 이상 있어야 함
   → 없으면 관련 수치를 추가하거나 수치를 뒷받침하는 구체적 설명으로 보완

2. 전문성 부족 — "중요합니다", "필요합니다", "좋습니다" 같은 일반론만 있고 전문 지식이 없는 섹션
   → 해당 분야 전문가 시각의 구체적 노하우·메커니즘·절차로 교체

3. 맥락 단절 — 앞 섹션과 흐름이 끊기는 도입 문장
   → 자연스럽게 이어지도록 첫 1~2문장 수정

4. 근거 부족 — 전체 글에 구체적 기준이나 수치가 전혀 없는 경우
   → 자료에 있는 사실로 기준을 1개 보강한다.
     **없는 사례나 후기를 만들어 채우지 마라** — 그게 이 항목의 원래 문제였다.

━━━━━━━━━━━━━━━━━━━━━━━━
【출력 규칙】
- 보완이 필요한 부분만 수정하고 나머지는 원본 그대로 유지
- 원본 HTML 구조(태그·이미지 마커·[박스] 표시)는 절대 변경하지 말 것
- 보완 후 HTML 전체를 출력 (```html 래퍼 없이)
- 보완할 내용이 없으면 원본 HTML 그대로 출력
- 보완/수정하는 모든 텍스트는 100% 한국어로만 작성 (영어 단어·문장 절대 금지, 브랜드명·고유명사·속담·명언·인용문은 예외)"""

        try:
            res = self.generate_content_with_cost(review_prompt)
            reviewed = res["text"].strip()

            import re as _re
            reviewed = _re.sub(r"^```[a-zA-Z]*\n?", "", reviewed)
            reviewed = _re.sub(r"\n?```$", "", reviewed.strip())

            # 너무 짧아지면 원본 사용 (AI가 내용을 날린 경우)
            if len(reviewed) < len(content_preview) * 0.6:
                _logger.warning("[글작가] 4단계 자기검토 결과 너무 짧음 — 원본 사용")
                return content

            _logger.info(f"[글작가] 4단계 자기검토 완료 — {len(content)}자 → {len(reviewed)}자")
            return reviewed
        except Exception as e:
            _logger.warning(f"[글작가] 4단계 자기검토 실패 ({e}) — 원본 사용")
            return content

    # ──────────────────────────────────────────────────────────────
    # [3단계] 최종 HTML 완성 + 이미지 프롬프트 생성
    # ──────────────────────────────────────────────────────────────
    def execute(self, topic: str, keywords: str, search_data: dict,
                tone_and_manner: str, theme_name: str,
                article_type: str = "📝 일반 포스팅 (기본)",
                brand_name: str = "",
                feedback: str = None) -> dict:
        """
        3단계 생성으로 최종 원고를 완성합니다.

        Args:
            search_data (dict): 서치대리의 execute() 결과 중 'data' 부분
            tone_and_manner (str): 편집장이 지시한 보도 방향
            theme_name (str): 적용할 테마 양식 (prompts.py 참고)
            feedback (str): 이전 검수 시 반려 피드백 의견

        Returns:
            dict: {status, title, content(HTML), image_prompts, usage}
        """
        import re, logging, time
        logger = logging.getLogger(__name__)

        if feedback:
            logger.info(f"[글작가] ⚠️ 이전 검수 피드백 수신: {feedback}")
            tone_and_manner = f"【이전 검수 반려 피드백 및 수정 지시사항】\n{feedback}\n\n" + tone_and_manner

        # ── 강화 학습 메모리 반영 ──────────────────────────────────────────
        from agents.agent_memory import get_memory as _get_mem
        _mem   = _get_mem()
        _fs    = _mem.build_fewshot_block("글작가", k=2)
        _adj   = _mem.get_param_adjustments("글작가")
        if _fs or _adj.get("extra_instruction"):
            _rl_block = "\n".join(filter(None, [_fs, _adj.get("extra_instruction", "")]))
            tone_and_manner = _rl_block + "\n\n" + tone_and_manner
            logger.info(f"[글작가] 강화학습 반영 — 평균 점수 {_adj.get('avg_score','N/A')}/10")
        # ──────────────────────────────────────────────────────────────────

        theme_prompt = get_theme_prompt(theme_name)
        persona      = self._get_persona(theme_name)
        total_usage  = {}

        # ── 1단계: 목차 확정 ──
        logger.info("[글작가] 1단계: 목차 확정 중...")
        outline = self._make_outline(topic, keywords, search_data, tone_and_manner, theme_name, article_type, brand_name)
        time.sleep(20)  # 쿨다운

        # ── 1.5단계: 자료정리대리 — 섹션별 팩트 브리프 생성 ──
        logger.info("[글작가] 1.5단계: 자료정리대리 섹션 브리프 요청 중...")
        try:
            from agents.agent_briefer import AgentBriefer as _AgentBriefer
            _briefer = _AgentBriefer(self.client, self.model, self.temperature)
            briefer_res = _briefer.execute(topic, search_data, outline)
            section_briefs = briefer_res.get("section_briefs", [])
            total_usage["자료정리대리"] = briefer_res.get("usage", {})
            logger.info(f"[글작가] 자료정리대리 브리프 수신 완료 ({len(section_briefs)}섹션)")
        except Exception as _be:
            logger.warning(f"[글작가] 자료정리대리 실패 (무시): {_be}")
            section_briefs = []
        time.sleep(20)  # 쿨다운

        # ── 2단계: 섹션별 단락 작성 ──
        logger.info("[글작가] 2단계: 섹션별 핵심 단락 작성 중...")
        sections = self._write_sections(topic, outline, search_data, tone_and_manner, theme_name,
                                        section_briefs=section_briefs, article_type=article_type, brand_name=brand_name)
        time.sleep(20)  # 쿨다운

        # ── 3단계: 단락 단위 세분화 생성 (Qwen3 TPM 회피 핵심) ──
        logger.info("[글작가] 3단계: 단락 단위 세분화 생성 및 이미지 프롬프트 기획 시작...")
        
        system_instruction = (
            f"{persona}\n"
            "나는 '네이버 블로그 전문 작가 프롬프트 v1.1' 가이드를 완벽하게 숙지하고 이행하는 탑클래스 블로거이기도 합니다. "
            "내 전문 분야의 깊이 있는 실전 경험을 바탕으로, "
            "독자가 모바일에서 스크롤하며 읽을 때 멈칫하게 만드는 '임팩트 있는 도입부'와 '시각적 컬러 박스(최소 30% 비율)'를 반드시 구현해 냅니다. "
            "독자가 실제로 읽는 텍스트(제목, 단락 본문, GEO 요약 등)는 예외 없이 100% 한국어로만 작성하며 "
            "영어 단어나 문장을 절대 섞지 않습니다(브랜드명·고유명사·속담·명언·인용문은 예외). "
            "오직 JSON의 prompt_en 필드(이미지 생성용)만 영어로 작성합니다."
        )

        title = ""
        intro_content = ""
        body_sections = []
        image_prompts = []

        # 3.1) 도입부 및 GEO 요약 블록 생성
        logger.info("[글작가] 3.1단계: 도입부 및 GEO 요약 블록 생성 중...")
        prompt_intro = f"""[메인 키워드]: {keywords}
[보도 방향 및 톤앤매너]: {tone_and_manner}

위 정보를 바탕으로 네이버 블로그 포스팅의 매력적인 제목과 최상단 도입부 HTML(공백/줄바꿈 포함) 및 GEO 요약 블록을 작성하세요.

제목은 클릭률을 높이도록 작성하고,
도입부는 "안녕하세요" 등 상투적 인사말을 절대 배제하고 독자의 시선을 끄는 임팩트 있는 사실/통계로 시작하세요.
도입부 직후에 반드시 [GEO 요약 블록]을 아래 형식과 문맥을 준수하여 삽입하세요.
제목과 본문은 100% 한국어로만 작성하고 영어 단어·문장을 섞지 마세요(브랜드명·고유명사·속담·명언·인용문은 예외).

출력 형식:
[제목]
(여기에 제목만 작성)

[본문]
(도입부 문장 HTML + [박스]...[/박스] GEO 요약 블록)
"""
        intro_res = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt_intro}
            ],
            temperature=self.temperature,
            max_tokens=1200
        )
        intro_text = self.strip_think_tags(intro_res.choices[0].message.content)
        total_usage["글작가_도입부"] = {
            "prompt_tokens": intro_res.usage.prompt_tokens,
            "completion_tokens": intro_res.usage.completion_tokens,
            "total_tokens": intro_res.usage.total_tokens
        }

        # 도입부 파싱
        if "[제목]" in intro_text and "[본문]" in intro_text:
            parts = intro_text.split("[본문]")
            title = parts[0].replace("[제목]", "").strip()
            intro_content = parts[1].strip()
        else:
            title_match = re.search(r"\\[제목\\]\s*(.*?)\n", intro_text)
            title = title_match.group(1).strip() if title_match else f"{topic} 분석 리포트"
            intro_content = intro_text

        time.sleep(20)  # 쿨다운

        # 3.2) 각 소제목 단락 생성 및 이미지 마커 매핑
        for idx, s in enumerate(sections, 1):
            logger.info(f"[글작가] 3.2단계: {idx}번째 단락 '{s['title']}' 생성 중...")
            
            prompt_section = f"""[섹션 소제목]: {s['title']}
[섹션 초안 내용]: {s['body']}
[섹션 이미지 힌트]: {s['image_hint']}
[이미지 번호]: [이미지{idx}]
[보도 방향]: {tone_and_manner}

위 정보를 바탕으로 모바일 화면에 최적화된 완성형 HTML 단락 본문을 작성하고, 이에 대응하는 영문 이미지 생성 프롬프트를 작성하세요.

작성 규칙:
1. 단락 내 모바일 환경을 배려해 45자 내외에서 의도적인 줄바꿈(<br> 또는 <p>)을 적용하세요.
2. 2~4문장 단위로 시각적 여백(<br><br>)을 충분히 확보하세요.
3. 이 단락의 핵심 수치/결론을 담은 요약 박스를 [박스]...[/박스] 형태로 단락 중간 또는 끝에 삽입하세요.
4. 대응 이미지 프롬프트는 텍스트(글자) 렌더링 오염을 배제한 고품질의 영문 프롬프트로 작성하세요.
5. [단락 본문]은 100% 한국어로만 작성하고 영어 단어·문장을 절대 섞지 마세요(브랜드명·고유명사·속담·명언·인용문은 예외).
   영어는 오직 아래 JSON의 prompt_en 필드에만 사용하세요.
6. [단락 본문]의 맨 첫 줄은 반드시 "<h2>{s['title']}</h2>" 형태로 시작하세요.
   제목 텍스트 안에 다른 HTML 태그를 중첩하지 말고, 정확히 이 문구 그대로 사용하세요.

출력 형식:
[단락 본문]
(<h2>{s['title']}</h2>로 시작하는 완성형 HTML 단락 본문, 끝부분에 [이미지{idx}] 마커 삽입 필수)

[이미지 프롬프트]
```json
{{
  "marker": "[이미지{idx}]",
  "section": "{s['title']}",
  "description_kr": "시각화 설명 (한국어)",
  "prompt_en": "Highly detailed English prompt (No text inside)"
}}
```
"""
            sec_res = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt_section}
                ],
                temperature=self.temperature,
                max_tokens=1500
            )
            sec_text = self.strip_think_tags(sec_res.choices[0].message.content)
            total_usage[f"글작가_단락_{idx}"] = {
                "prompt_tokens": sec_res.usage.prompt_tokens,
                "completion_tokens": sec_res.usage.completion_tokens,
                "total_tokens": sec_res.usage.total_tokens
            }

            # 단락 및 이미지 프롬프트 파싱
            sec_body = ""
            json_blocks = re.findall(r"```json\s*(.*?)\s*```", sec_text, re.DOTALL)
            for block in json_blocks:
                try:
                    parsed = self.parse_json_from_text(block.strip())
                    if isinstance(parsed, dict) and parsed.get("marker") == f"[이미지{idx}]":
                        image_prompts.append(parsed)
                except Exception as pe:
                    logger.warning(f"[글작가] 단락 {idx} 이미지 JSON 파싱 실패: {pe}")

            if "[단락 본문]" in sec_text:
                sec_body = sec_text.split("[단락 본문]")[1]
                if "[이미지 프롬프트]" in sec_body:
                    sec_body = sec_body.split("[이미지 프롬프트]")[0]
                sec_body = sec_body.strip()
            else:
                body_match = re.search(r"\\[단락 본문\\]\s*(.*?)(?=\\[이미지 프롬프트\\]|```json|$)", sec_text, re.DOTALL)
                sec_body = body_match.group(1).strip() if body_match else sec_text

            # 본문 내 마크다운 코드블록 제거
            sec_body = re.sub(r"^```[a-zA-Z]*\n?", "", sec_body)
            sec_body = re.sub(r"\n?```$", "", sec_body.strip())
            
            # 본문에 마커가 혹시 없을 경우 자동으로 덧붙임 보장
            if f"[이미지{idx}]" not in sec_body:
                sec_body = sec_body + f"\n\n[이미지{idx}]"

            # 모델이 규칙 6(맨 앞 <h2> 삽입)을 놓친 경우를 대비한 안전장치.
            # 예전에는 여기서 무조건 "## {title}"을 덧붙였는데, sec_body 안에도
            # 모델이 자체적으로 <h2>를 넣는 경우가 많아 "## <h2>...</h2>" 같은
            # 중복·깨진 헤딩이 발생했다. 이제는 <h2>가 없을 때만 보충한다.
            if not re.match(r"\s*<h2[\s>]", sec_body, re.IGNORECASE):
                sec_body = f"<h2>{s['title']}</h2>\n\n{sec_body}"

            body_sections.append(sec_body)
            time.sleep(20)  # 쿨다운

        # 3.3) 전체 요약 썸네일 프롬프트 생성
        logger.info("[글작가] 3.3단계: 메인 썸네일 프롬프트 생성 중...")
        prompt_thumb = f"""[블로그 제목]: {title}
[블로그 전체 주제]: {topic}

블로그 전체 내용을 아우르는 임팩트 있는 메인 썸네일 영문 프롬프트를 작성하세요.
글자/텍스트가 절대로 포함되지 않아야 합니다.

출력 형식:
```json
{{
  "description_kr": "썸네일 한국어 설명",
  "visual_style": "cinematic photorealistic",
  "prompt_en": "Highly detailed English hero thumbnail prompt"
}}
```
"""
        thumb_res = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt_thumb}
            ],
            temperature=self.temperature,
            max_tokens=800
        )
        thumb_text = self.strip_think_tags(thumb_res.choices[0].message.content)
        total_usage["글작가_썸네일"] = {
            "prompt_tokens": thumb_res.usage.prompt_tokens,
            "completion_tokens": thumb_res.usage.completion_tokens,
            "total_tokens": thumb_res.usage.total_tokens
        }

        thumbnail_prompt = {}
        json_blocks = re.findall(r"```json\s*(.*?)\s*```", thumb_text, re.DOTALL)
        for block in json_blocks:
            try:
                parsed = self.parse_json_from_text(block.strip())
                if isinstance(parsed, dict):
                    thumbnail_prompt = parsed
            except Exception as pe:
                logger.warning(f"[글작가] 썸네일 JSON 파싱 실패: {pe}")

        # 썸네일 2차 검사 및 폴백 빌드
        if not thumbnail_prompt or not isinstance(thumbnail_prompt, dict) or "prompt_en" not in thumbnail_prompt:
            logger.warning("[글작가] 썸네일 프롬프트 없음 — 글작가 자체 자동 폴백 프롬프트 생성")
            thumbnail_prompt = {
                "description_kr": f"{title} 메인 썸네일",
                "visual_style": "cinematic photorealistic",
                "prompt_en": f"A powerful visual summarizing the topic '{topic}' and '{title}'. Cinematic photorealistic, soft warm lighting, professional composition, 8k resolution, highly detailed, text-free."
            }

        # 3.4) 전체 본문 병합
        content = intro_content + "\n\n" + "\n\n".join(body_sections)

        # ── 4단계: 자기검토 — 수치 부재·맥락 단절·일반론 보완 ──
        time.sleep(20)  # 쿨다운
        logger.info("[글작가] 4단계: 자기검토 및 품질 보완 중...")
        if content:
            content = self._self_review(topic, content, sections, theme_name)

        return {
            "status":           "success",
            "title":            title,
            "content":          content,
            "image_prompts":    image_prompts,
            "thumbnail_prompt": thumbnail_prompt,
            "outline":          outline,
            "usage":            total_usage,
        }
