import os
import sys
import logging
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.model_config import GroqModelConfig
from agents.base_agent import BaseAgent
from agents.agent_topic import AgentTopic
from agents.agent_search import AgentSearch
from agents.agent_writer import AgentWriter
from agents.agent_image import AgentImage
from agents.agent_editor import AgentEditor
from agents.agent_accountant import AgentAccountant
from agents.agent_analyst import AgentAnalyst
from agents.knowledge_manager import AgentKnowledgeManager

# (기존 포스팅 모듈이 있다고 가정 - naver_poster.py 연동)
# from naver_poster import NaverBlogPoster

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class MasterOrchestrator:
    """
    편집장(네블기)의 지시를 받아 에이전트들을 순차적으로 지휘하는 마스터 컨트롤러.
    """
    def __init__(self):
        logger.info("👨‍💼 편집장(네블기) 시스템 초기화 중...")
        # 실행 위치와 무관하게 이 파일 기준 상위 폴더의 .env를 명시적으로 로드
        _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        load_dotenv(dotenv_path=os.path.join(_project_root, ".env"))

        # llm_provider(config.json) 에 따라 Groq 또는 로컬(OpenAI 호환) 클라이언트를
        # 생성한다. BaseAgent와 동일한 헬퍼를 써야, 대시보드 개별 버튼(BaseAgent 단독
        # 사용)과 이 오케스트레이터 경유(전체 파이프라인)의 provider가 어긋나지 않는다.
        config_data = BaseAgent.load_config_json()
        llm_provider = BaseAgent.resolve_llm_provider(config_data)
        self.groq_client = BaseAgent.build_llm_client(config_data)

        if not self.groq_client:
            raise ValueError("[오류] 연동할 LLM API Key를 찾을 수 없습니다. .env 혹은 설정을 확인하세요.")

        def _resolve_model(cfg: dict) -> str:
            """provider가 local이면 로컬에 로드된 단일 모델로, 아니면 역할별 Groq 모델로."""
            if llm_provider == "local":
                _, local_model = BaseAgent.get_local_llm_config(config_data)
                return local_model
            return cfg["model_id"]

        # 오케스트레이터 설정
        orch_cfg = GroqModelConfig.get_config("orchestrator")
        self.model_id = _resolve_model(orch_cfg)
        self.temperature = orch_cfg["temperature"]

        # 각 에이전트에 동기식 클라이언트와 모델 설정을 주입합니다.
        # (온도는 provider와 무관하게 역할별 값을 그대로 유지)
        topic_cfg = GroqModelConfig.get_config("topic")
        self.agent_topic = AgentTopic(self.groq_client, _resolve_model(topic_cfg), topic_cfg["temperature"])

        search_cfg = GroqModelConfig.get_config("search")
        self.agent_search = AgentSearch(self.groq_client, _resolve_model(search_cfg), search_cfg["temperature"])

        writer_cfg = GroqModelConfig.get_config("writer")
        self.agent_writer = AgentWriter(self.groq_client, _resolve_model(writer_cfg), writer_cfg["temperature"])

        editor_cfg = GroqModelConfig.get_config("editor")
        self.agent_image = AgentImage(self.groq_client, _resolve_model(editor_cfg), editor_cfg["temperature"])
        self.agent_editor = AgentEditor(self.groq_client, _resolve_model(editor_cfg), editor_cfg["temperature"])

        accountant_cfg = GroqModelConfig.get_config("accountant")
        self.agent_accountant = AgentAccountant(self.groq_client, _resolve_model(accountant_cfg), accountant_cfg["temperature"])

        analyst_cfg = GroqModelConfig.get_config("analyst")
        self.agent_analyst = AgentAnalyst(self.groq_client, _resolve_model(analyst_cfg), analyst_cfg["temperature"])

        # 지식 매니저 초기화
        self.agent_knowledge = AgentKnowledgeManager(self.groq_client, _resolve_model(search_cfg), search_cfg["temperature"])

    def run_daily_posting(self, topic: str, keywords: str, tone_and_manner: str,
                          theme_name: str = "✨ 전문가 작성 (기본)",
                          article_type: str = "📝 일반 포스팅 (기본)",
                          brand_name: str = "",
                          progress_callback=None, desking_callback=None):
        """전체 파이프라인 실행.

        progress_callback(agent_name, status): status는 'running' | 'done' | 'error'
        desking_callback(editor_res) -> bool: True면 포스팅 진행, False면 취소
        """
        def _progress(agent, status):
            if progress_callback:
                progress_callback(agent, status)

        logger.info(f"🚀 블로기이 파이프라인 가동: [{topic}]")
        usage_logs = []

        # 1. 제시대리의 파라미터(메모리) 적용
        ai_params = self.agent_analyst.load_params()
        if "recommended_tone" in ai_params:
            tone_and_manner += f" (제시대리 추가 제안: {ai_params['recommended_tone']})"

        # 편집장의 네이버 블로그 전문 작가 v1.1 마스터 가이드 엄수 지시
        tone_and_manner += "\n[편집장 특별 지시]: '네이버 블로그 전문 작가 프롬프트 v1.1' 가이드를 철저히 참조하고, 시각적 박스 30% 배치와 모바일 가독성(45자 줄바꿈) 제약을 반드시 엄수하라!"

        # 2. 서치대리
        _progress("서치대리", "running")
        logger.info("🔎 [서치대리] 자료 수집 시작...")
        search_res = self.agent_search.execute(topic, keywords, news_count=10, blog_count=10)
        if search_res.get("status") != "success":
            _progress("서치대리", "error")
            logger.error("서치대리 오류 발생. 중단합니다.")
            return False
        _progress("서치대리", "done")
        usage_logs.append({"agent": "서치대리", "usage": search_res.get("usage", {})})

        # 로컬 지식베이스(RAG) 검색 및 컨텍스트 주입
        knowledge_context = self.agent_knowledge.retrieve_knowledge(topic, keywords)
        if "data" in search_res:
            search_res["data"]["knowledge_context"] = knowledge_context

        # 벤치마크 쿼리 로깅
        benchmark_qs = search_res.get("data", {}).get("benchmark_queries", [])
        if benchmark_qs:
            logger.info("📊 [모니터링] 매주 검색해 볼 벤치마크 질문:")
            for i, q in enumerate(benchmark_qs, 1):
                logger.info(f"  {i}. {q}")
            
            # 파일로 누적 저장
            try:
                from datetime import datetime
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                benchmark_file = os.path.join(project_root, "benchmark_queries.txt")
                with open(benchmark_file, "a", encoding="utf-8") as f:
                    f.write(f"=== {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 주제: {topic} ===\n")
                    for i, q in enumerate(benchmark_qs, 1):
                        f.write(f"{i}. {q}\n")
                    f.write("\n")
                logger.info(f"💾 [모니터링] 벤치마크 질문이 파일에 누적 저장되었습니다: {benchmark_file}")
            except Exception as _fe:
                logger.warning(f"[경고] 벤치마크 질문 파일 저장 실패: {_fe}")

        # --- 품질 평가 및 반려 루프 (최대 3회) ---
        max_attempts = 3
        attempt = 0
        writer_feedback = None
        image_feedback = None

        writer_res = None
        image_res = None
        editor_res = None

        while attempt < max_attempts:
            attempt += 1
            logger.info(f"🔄 [오케스트레이터] 파이프라인 품질 검사 시도 {attempt}/{max_attempts}")

            # 3. 글작가
            _progress("글작가", "running")
            logger.info(f"✍️ [글작가] 원고 작성 시작 (시도 {attempt})...")
            writer_res = self.agent_writer.execute(
                topic=topic,
                keywords=keywords,
                search_data=search_res["data"],
                tone_and_manner=tone_and_manner,
                theme_name=theme_name,
                article_type=article_type,
                brand_name=brand_name,
                feedback=writer_feedback
            )
            _progress("글작가", "done")
            usage_logs.append({"agent": "글작가", "usage": writer_res.get("usage", {})})

            # 4. 이미지대리 — 글작가가 제시한 프롬프트(최대 30컷) + 썸네일 프롬프트 사용
            _progress("이미지대리", "running")
            writer_image_prompts = writer_res.get("image_prompts", [])
            writer_thumbnail_prompt = writer_res.get("thumbnail_prompt", {})
            logger.info(
                f"🎨 [이미지대리] 이미지 기획 시작 "
                f"(글작가 섹션 프롬프트 {len(writer_image_prompts)}컷 + "
                f"썸네일 프롬프트 {'수신 ✓' if writer_thumbnail_prompt else '없음'}) (시도 {attempt})"
            )
            image_res = self.agent_image.execute(
                title=writer_res["title"],
                content=writer_res["content"],
                min_images=max(4, len(writer_image_prompts)),
                writer_image_prompts=writer_image_prompts,
                thumbnail_prompt=writer_thumbnail_prompt,
                feedback=image_feedback
            )
            _progress("이미지대리", "done")
            usage_logs.append({"agent": "이미지대리", "usage": image_res.get("usage", {})})

            # 5. 편집과장
            _progress("편집과장", "running")
            logger.info(f"🗂️ [편집과장] 레이아웃 결합 및 제목 다듬기 (품질 평가 진행) (시도 {attempt})...")
            editor_res = self.agent_editor.execute(
                title=writer_res["title"],
                content=writer_res["content"],
                images_data=image_res.get("images", []),
            )
            _progress("편집과장", "done")
            usage_logs.append({"agent": "편집과장", "usage": editor_res.get("usage", {})})

            # 📊 품질 점수 확인 및 반려 여부 결정
            w_score = editor_res.get("writer_score", 100)
            i_score = editor_res.get("image_score", 100)
            w_fb = editor_res.get("writer_feedback", "우수함")
            i_fb = editor_res.get("image_feedback", "우수함")

            if w_score >= 90 and i_score >= 90:
                logger.info(f"🎉 [오케스트레이터] 품질 검수 최종 통과! (글작가: {w_score}점, 이미지대리: {i_score}점)")
                break
            else:
                logger.warning(
                    f"⚠️ [오케스트레이터] 품질 검수 미달로 반려 발생 (시도 {attempt}/{max_attempts})\n"
                    f"  - 글작가: {w_score}점 (피드백: {w_fb})\n"
                    f"  - 이미지대리: {i_score}점 (피드백: {i_fb})"
                )
                if attempt < max_attempts:
                    writer_feedback = w_fb if w_score < 90 else None
                    image_feedback = i_fb if i_score < 90 else None
                    logger.info("🔄 [오케스트레이터] 반려된 에이전트의 재작성을 진행합니다.")
                else:
                    logger.error(
                        f"🛑 [오케스트레이터] 최대 반려 횟수({max_attempts}회)를 초과했습니다. "
                        f"현재 생성본(글작가: {w_score}점, 이미지대리: {i_score}점)으로 포스팅을 계속합니다."
                    )

        # --- 편집장 데스킹 (Human-in-the-loop) ---
        logger.info(f"✨ [편집장 데스킹] 최종 제목: {editor_res['final_title']} | 키워드: {editor_res['tags']}")

        post_data = None
        if desking_callback:
            # 반환값: {"title":.., "content":.., "tags":.., "image_paths":[..]} 또는 None(취소)
            post_data = desking_callback(editor_res, writer_res["content"])
            if post_data is None:
                logger.info("🛑 편집장이 포스팅을 취소했습니다.")
                return False
            # desking_callback이 segments를 빠뜨린 경우 editor_res에서 보충
            if "segments" not in post_data:
                post_data["segments"] = editor_res.get("segments", [])
        else:
            # desking_callback 없을 때 editor_res로 자동 구성
            post_data = {
                "title":       editor_res["final_title"],
                "content":     editor_res["final_content"],
                "tags":        editor_res["tags"],
                "image_paths": editor_res.get("image_paths", []),
                "segments":    editor_res.get("segments", []),  # ← 서식 세그먼트
            }

        # 6. 실제 네이버 포스팅
        if post_data:
            logger.info("🚀 네이버 블로그 포스팅 시작...")
            try:
                import config as cfg
                from naver_poster import NaverBlogPoster
                conf = cfg.load_config()
                poster = NaverBlogPoster(
                    headless=conf.get("headless_mode", False),
                    log_callback=logger.info,
                )
                success = poster.run_full_post(
                    naver_id=conf.get("naver_id", ""),
                    naver_pw=conf.get("naver_pw", ""),
                    title=post_data["title"],
                    content=post_data["content"],
                    tags=post_data["tags"],
                    category=conf.get("default_category", ""),
                    image_paths=post_data.get("image_paths", []),
                    segments=post_data.get("segments"),  # ← 서식 세그먼트 전달
                )
                if success:
                    logger.info("🎉 네이버 블로그 포스팅 완료!")
                else:
                    logger.error("❌ 포스팅 실패. 로그를 확인하세요.")
                    return False
            except Exception as e:
                logger.error(f"❌ 포스팅 오류: {e}")
                return False
        else:
            logger.info("🚀 (가상) 포스팅 완료 — 네이버 계정 정보 없음")

        # 로컬 지식베이스(RAG) 지식 요약 축적
        try:
            self.agent_knowledge.save_knowledge(topic, keywords, post_data["content"])
        except Exception as ke:
            logger.warning(f"[경고] 지식베이스 저장 실패: {ke}")

        # 7. 경리과장
        _progress("경리과장", "running")
        logger.info("🧮 [경리과장] 비용 분석 및 최적화 리포트 작성 중...")
        accountant_res = self.agent_accountant.execute(usage_logs)
        _progress("경리과장", "done")
        logger.info(f"[경리과장 보고]: 총 토큰 소모량 = {accountant_res['total_tokens']} 토큰")
        for agent, tokens in accountant_res.get("agent_usage", {}).items():
            logger.info(f"  - {agent}: {tokens} 토큰")
        logger.info(f"[비용 절감 팁]: {accountant_res['analysis'].get('cost_saving_tip', '')}")

        # 8. 강화학습 세션 스냅샷 저장 (야간 배치에서 지표 수신 시 기록에 활용)
        try:
            from agents.agent_memory import get_memory as _get_mem
            _get_mem().save_session({
                "글작가": {
                    "input_summary":  f"주제: {topic} | 키워드: {keywords}",
                    "output_summary": f"제목: {writer_res.get('title','')} | "
                                      f"이미지프롬프트 {len(writer_res.get('image_prompts',[]))}컷",
                    "output_snippet": (writer_res.get("content", "")[:300]),
                    "params":         {"theme": theme_name},
                },
                "이미지대리": {
                    "input_summary":  f"주제: {topic} | 이미지프롬프트 {len(writer_image_prompts)}컷",
                    "output_summary": f"확보 이미지 {image_res.get('image_count', 0)}컷",
                    "output_snippet": "",
                    "params":         {"image_count": image_res.get("image_count", 0)},
                },
                "편집과장": {
                    "input_summary":  f"제목: {writer_res.get('title','')}",
                    "output_summary": f"최종 제목: {editor_res.get('final_title','')} | "
                                      f"태그: {editor_res.get('tags','')}",
                    "output_snippet": (editor_res.get("final_content", "")[:300]),
                    "params":         {},
                },
                "서치대리": {
                    "input_summary":  f"주제: {topic} | 키워드: {keywords}",
                    "output_summary": f"뉴스 {len(search_res.get('data', {}).get('news', []))}건 수집",
                    "output_snippet": "",
                    "params":         {},
                },
            })
            logger.info("📦 [강화학습] 세션 스냅샷 저장 완료 — 야간 배치 대기 중")
        except Exception as _e:
            logger.warning(f"[강화학습] 세션 저장 실패 (무시): {_e}")

        return True

    def run_nightly_batch(self, post_title: str, stats: dict):
        """
        야간에 실행되는 피드백/분석 파이프라인.
        stats: {"views": int, "likes": int, "comments": int, ...}
        """
        logger.info("🌙 [제시대리] 야간 성과 분석 및 메모리 학습 가동...")

        # ── 강화학습: 세션 지표 기록 ─────────────────────────────────────
        try:
            from agents.agent_memory import get_memory as _get_mem
            mem       = _get_mem()
            score_map = mem.record_session(stats)
            if score_map:
                logger.info(
                    "🧠 [강화학습] 성과 기록 완료 — "
                    + " | ".join(f"{k} {v:.1f}점" for k, v in score_map.items())
                )
                logger.info("\n" + mem.get_trend_report())
        except Exception as _e:
            logger.warning(f"[강화학습] 기록 실패 (무시): {_e}")
        # ──────────────────────────────────────────────────────────────────

        analyst_res = self.agent_analyst.execute(post_title, stats)
        logger.info(f"분석 결과: {analyst_res['analysis'].get('analysis_summary', '')}")
        logger.info(f"다음 전략: {analyst_res['analysis'].get('next_strategy', '')}")

if __name__ == "__main__":
    orchestrator = MasterOrchestrator()
    # 편집장 지시사항
    orchestrator.run_daily_posting(
        topic="2026년 부동산 청약 트렌드",
        keywords="부동산, 청약, 내집마련, 신혼부부",
        tone_and_manner="전문적이고 신뢰감을 주지만, 사회초년생도 이해하기 쉽게 비유를 많이 써주세요.",
        theme_name="💰 재테크"
    )
    
    # 가상의 야간 성과 분석 테스트
    print("\n")
    orchestrator.run_nightly_batch(
        post_title="2026 부동산 청약 트렌드",
        stats={"views": 1500, "comments": 25, "score": 8.5}
    )

# 하위 호환성 및 사용자 정의 템플릿 대응용 별칭(alias) 선언
BlogEOrchestrator = MasterOrchestrator

