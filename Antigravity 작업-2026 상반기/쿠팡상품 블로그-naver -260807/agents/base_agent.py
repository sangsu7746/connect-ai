import os
import re
import json
import glob
import logging
from datetime import datetime, timedelta
from typing import Any, Dict

from groq import Groq
from dotenv import load_dotenv

# 프로젝트 루트의 .env 파일을 찾아 로드
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path=os.path.join(_project_root, ".env"))

logger = logging.getLogger(__name__)

class BaseAgent:
    """
    블로기이 멀티 에이전트 시스템의 공통 베이스 클래스.
    모든 대리/과장 에이전트는 이 클래스를 상속받습니다.
    (Groq API 기반의 완전한 동기식으로 전환)
    """

    # ── LLM provider 결정 로직 (BaseAgent·MasterOrchestrator 공유 단일 진실 공급원) ──
    # orchestrator.py가 파이프라인 전체에 쓸 클라이언트를 미리 만들어 각 에이전트에
    # 명시적으로 주입하기 때문에, provider 분기는 반드시 여기 한 곳에만 있어야
    # BaseAgent 단독 사용(대시보드 개별 버튼)과 orchestrator 경유(전체 파이프라인)가
    # 서로 다른 provider를 쓰는 불일치가 생기지 않는다.

    @staticmethod
    def load_config_json() -> dict:
        """config.json을 로드합니다. 없거나 파싱 실패 시 빈 dict."""
        config_path = os.path.join(os.getcwd(), "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"config.json 로드 실패: {e}")
        return {}

    @staticmethod
    def resolve_llm_provider(config_data: dict = None) -> str:
        """"groq"(기본) 또는 "local"(LM Studio·ConnectAI·Ollama 등 OpenAI 호환
        로컬 서버, TPM/TPD 한도 없음)."""
        if config_data is None:
            config_data = BaseAgent.load_config_json()
        return os.getenv("LLM_PROVIDER") or config_data.get("llm_provider", "groq")

    @staticmethod
    def get_local_llm_config(config_data: dict = None) -> tuple:
        """(base_url, model) 로컬 LLM 설정값을 반환합니다."""
        if config_data is None:
            config_data = BaseAgent.load_config_json()
        base_url = os.getenv("LOCAL_LLM_BASE_URL") or config_data.get(
            "local_llm_base_url", "http://127.0.0.1:1235/v1"
        )
        model = os.getenv("LOCAL_LLM_MODEL") or config_data.get(
            "local_llm_model", "gemma-4-12B-it-QAT-Q4_0.gguf"
        )
        return base_url, model

    @staticmethod
    def build_llm_client(config_data: dict = None):
        """llm_provider 설정에 따라 Groq 또는 로컬(OpenAI 호환) 클라이언트를 생성합니다."""
        if config_data is None:
            config_data = BaseAgent.load_config_json()
        provider = BaseAgent.resolve_llm_provider(config_data)

        if provider == "local":
            # LM Studio·ConnectAI(llama-server 내장)·Ollama 등은 표준 OpenAI 스펙의
            # /v1/chat/completions 를 그대로 쓴다. groq SDK는 내부적으로 항상
            # "/openai/v1/chat/completions" 경로를 강제로 붙여서(Groq 전용 라우팅) 이런
            # 서버들과는 404가 나므로, 표준 openai SDK를 써야 한다(경로를 그대로 존중함).
            from openai import OpenAI
            base_url, _ = BaseAgent.get_local_llm_config(config_data)
            logger.info(f"로컬 LLM 서버 사용 — {base_url}")
            return OpenAI(api_key="local-llm", base_url=base_url)

        # 기존 Groq API 경로 (유연한 키 로드 규칙 유지)
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            # 1순위: groq_api_key, 2순위: gemini_api_key (하위 호환 폴백)
            api_key = config_data.get("groq_api_key") or config_data.get("gemini_api_key")
            if api_key:
                logger.info(".env에 GROQ_API_KEY가 없어 config.json의 키를 호출합니다.")
        return Groq(api_key=api_key) if api_key else None

    def __init__(self, agent_name: str, client: Any = None, model: str = None, temperature: float = None, memory_root: str = ".agent"):
        self.agent_name = agent_name

        config_data  = self.load_config_json()
        llm_provider = self.resolve_llm_provider(config_data)

        # 클라이언트 인스턴스화 (이미 주어졌으면 그대로 사용 — orchestrator가 주입하는 경우)
        self.client = client if client is not None else self.build_llm_client(config_data)

        # 모델 및 Temperature 설정 주입
        from agents.model_config import GroqModelConfig
        NAME_MAP = {
            "편집장": "orchestrator",
            "MasterOrchestrator": "orchestrator",
            "서치대리": "search",
            "제시대리": "analyst",
            "발제대리": "topic",
            "글작가": "writer",
            "편집과장": "editor",
            "경리과장": "accountant"
        }
        config_key = NAME_MAP.get(agent_name, "editor")
        cfg = GroqModelConfig.get_config(config_key)

        if llm_provider == "local" and model is None:
            # 로컬 서버에서는 Groq 전용 모델 ID(GroqModelConfig)가 통하지 않으므로
            # 로컬 앱에 로드해둔 모델 식별자를 그대로 사용한다.
            _, self.model = self.get_local_llm_config(config_data)
        else:
            self.model = model if model is not None else cfg["model_id"]
            # 사용자가 제공한 모델명이 실제 지원되지 않는 비공식 모델명인 경우, 유효한 모델 ID로 매핑
            if self.model in GroqModelConfig.REAL_MODEL_MAP:
                self.model = GroqModelConfig.REAL_MODEL_MAP[self.model]
        self.temperature = temperature if temperature is not None else cfg["temperature"]

        # 메모리 보존을 위한 디렉토리 세팅
        self.reward_dir  = os.path.join(os.getcwd(), memory_root, "reward")
        self.punish_dir  = os.path.join(os.getcwd(), memory_root, "punishment")
        self.params_path = os.path.join(os.getcwd(), "ai_params.json")
        os.makedirs(self.reward_dir, exist_ok=True)
        os.makedirs(self.punish_dir, exist_ok=True)

    @staticmethod
    def strip_think_tags(text: str) -> str:
        """
        Qwen3·DeepSeek-R1·Gemma 등 추론 모델의 <think>...</think> 사고 과정을 제거합니다.
        여는 <think> 태그 없이 닫는 </think>만 오는 경우(응답이 사고 과정 중간부터
        캡처된 경우)도 있으므로, </think> 존재 여부만으로 판단해 그 이후만 남긴다.
        """
        if "</think>" in text:
            return text.split("</think>")[-1].strip()
        return text

    def _call_groq(self, system_prompt: str, user_prompt: str, require_json: bool = False) -> str:
        """
        [안전] Tkinter GUI 호환을 위해 완전한 동기식(Sync) 메서드로 호출합니다.
        """
        if not self.client:
            raise ValueError(f"[{self.agent_name}] Groq API 키가 설정되지 않았습니다. .env 혹은 설정을 확인하세요.")
            
        try:
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": self.temperature
            }
            
            if require_json:
                kwargs["response_format"] = {"type": "json_object"}

            response = self.client.chat.completions.create(**kwargs)
            text_content = response.choices[0].message.content

            # DeepSeek-R1 등 추론 모델의 생각 태그가 포함되어 있을 경우 정제
            text_content = self.strip_think_tags(text_content)

            return text_content
            
        except Exception as e:
            logger.error(f"[{self.agent_name} API 연동 오류]: {e}")
            raise e

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """DeepSeek-R1 등 추론 모델의 생각 태그를 필터링하고 JSON을 파싱합니다."""
        try:
            text = self.strip_think_tags(text)

            # 기존 parse_json_from_text의 풍부한 파싱 기법 적용하여 견고성 보장
            # 1순위: ```json ... ``` 블록에서 객체 또는 배열 추출
            match = re.search(
                r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```',
                text,
                re.DOTALL
            )
            if match:
                return json.loads(match.group(1))

            # 2순위: 백틱 없이 텍스트 전체가 JSON인 경우
            stripped = text.strip()
            if stripped.startswith(("{", "[")):
                return json.loads(stripped)

            # 3순위: 텍스트 중간에 삽입된 JSON 블록 탐색 (객체 우선, 배열 fallback)
            for pattern in (r'(\{[^`]*?\})', r'(\[[^`]*?\])'):
                m = re.search(pattern, text, re.DOTALL)
                if m:
                    return json.loads(m.group(1))

            return json.loads(text)
        except Exception as e:
            logger.error(f"[{self.agent_name} JSON 파싱 실패]: {e} | 원문: {text[:200]}")
            return {"error": "Invalid JSON format", "raw_text": text}

    def generate_content_with_cost(self, prompt: str, system_instruction: str = None) -> dict:
        """
        [하위 호환성 준수] Groq API를 호출하고 토큰 사용량과 텍스트를 반환합니다.
        (속도 제한 429 에러 발생 시 자동 재시도 로직 포함)
        """
        if not self.client:
            raise ValueError(f"[{self.agent_name}] Groq API 키가 설정되지 않았습니다. .env 혹은 설정을 확인하세요.")
            
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        # 413(TPM 초과) 진단용 — 어느 호출이 얼마나 큰 프롬프트를 보냈는지 사전 확인
        _total_chars = len(prompt) + (len(system_instruction) if system_instruction else 0)
        _snippet = prompt.strip().replace("\n", " ")[:40]
        logger.info(f"[{self.agent_name}] Groq 호출 — 프롬프트 {_total_chars:,}자 (미리보기: \"{_snippet}...\")")

        max_retries = 3
        retry_delay = 5 # 초
        
        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature
                )
                
                # 토큰 사용량 추출 (Groq SDK)
                usage = {}
                try:
                    usage_meta = response.usage
                    usage = {
                        "prompt_tokens": getattr(usage_meta, "prompt_tokens", 0),
                        "candidates_tokens": getattr(usage_meta, "completion_tokens", 0),
                        "total_tokens": getattr(usage_meta, "total_tokens", 0)
                    }
                except Exception:
                    pass
                
                text_content = response.choices[0].message.content

                # DeepSeek-R1 등 추론 모델의 생각 태그가 포함되어 있을 경우 정제
                text_content = self.strip_think_tags(text_content)

                return {
                    "text": text_content.strip(),
                    "usage": usage,
                    "model": self.model
                }
                
            except Exception as e:
                error_str = str(e)
                # 413(요청 자체가 TPM 한도보다 큼)은 동일 payload로 재시도해도 항상
                # 같은 결과이므로, 429(일시적 속도 제한)와 구분해 즉시 실패시킨다.
                if "413" in error_str or "Request too large" in error_str or "reduce your message size" in error_str:
                    logger.error(
                        f"[{self.agent_name}] 요청 크기가 TPM 한도를 초과했습니다(413) — "
                        f"재시도로 해결되지 않으므로 즉시 중단합니다: {error_str[:200]}"
                    )
                    raise
                # TPD(일일 토큰 한도) 도달 — 초기화까지 수 분~수십 분이 걸려 짧은
                # 재시도 대기(5~15초)로는 절대 해결되지 않으므로 즉시 실패시킨다.
                if "tokens per day" in error_str or "TPD" in error_str:
                    wait_match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", error_str)
                    if wait_match:
                        minutes = int(wait_match.group(1) or 0)
                        seconds = float(wait_match.group(2))
                        wait_desc = f"{minutes}분 {seconds:.0f}초" if minutes else f"{seconds:.0f}초"
                    else:
                        wait_desc = "안내된 시간"
                    logger.error(
                        f"[{self.agent_name}] 일일 토큰 한도(TPD)에 도달했습니다 — "
                        f"약 {wait_desc} 후 재시도 가능. 재시도로 즉시 해결되지 않으므로 중단합니다: {error_str[:200]}"
                    )
                    raise
                if "429" in error_str or "rate_limit" in error_str:
                    if attempt < max_retries - 1:
                        logger.warning(f"[{self.agent_name}] Groq API 속도 제한 도달(429). {retry_delay}초 대기 후 재시도합니다... (시도 {attempt+1}/{max_retries})")
                        import time
                        time.sleep(retry_delay)
                        retry_delay += 5
                        continue
                raise e

    # ── 메모리 및 파라미터 공통 기능 (기존 로직 보존) ─────────────────────────────
    def load_memory(self, days: int = 30) -> str:
        """과거 성공/실패 기록 로드 (제시대리 및 기타 분석 에이전트 용)"""
        all_files = []
        for d in [self.reward_dir, self.punish_dir]:
            all_files.extend(glob.glob(os.path.join(d, "memory_*.md")))
        cutoff = datetime.now() - timedelta(days=days)
        recent = []
        for f in sorted(all_files, reverse=True):
            try:
                date_part = os.path.basename(f).replace("memory_", "")[:8]
                if datetime.strptime(date_part, "%Y%m%d") >= cutoff:
                    recent.append(f)
            except Exception:
                continue
        texts = []
        for f in recent[:10]: # 토큰 절약을 위해 최근 10개만 로드
            try:
                with open(f, encoding="utf-8") as fp:
                    texts.append(fp.read())
            except Exception:
                continue
        return "\n\n".join(texts)

    def save_memory(self, result_text: str, score: float, summary: str):
        """성과 기반 메모리 저장"""
        label      = "REWARD" if score >= 0 else "PUNISHMENT"
        target_dir = self.reward_dir if score >= 0 else self.punish_dir
        ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
        path       = os.path.join(target_dir, f"memory_{ts}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# [{label}] {datetime.now().strftime('%Y-%m-%d %H:%M')}  |  점수: {score:+,.1f}\n\n")
            f.write("## 오늘 요약\n")
            f.write(summary)
            f.write(f"\n\n## {self.agent_name} 메모리\n")
            f.write(result_text)
        logger.info(f"[{self.agent_name}] {label} 메모리 저장 → {path}")

    def save_params(self, params: dict):
        """환경 설정/파라미터 저장"""
        params["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.params_path, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        logger.info(f"[{self.agent_name}] 파라미터 업데이트 → {self.params_path}")

    def load_params(self) -> dict:
        """환경 설정/파라미터 로드"""
        try:
            with open(self.params_path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
            
    def parse_json_from_text(self, text: str):
        """[하위 호환성 준수] 응답 텍스트에서 JSON을 추출합니다."""
        return self._parse_json(text)
