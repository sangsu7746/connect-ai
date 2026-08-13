class GroqModelConfig:
    """
    각 에이전트의 역할과 모델 특성에 맞춘 Groq 모델 ID와 하이퍼파라미터(temperature) 설정 클래스.
    """
    CONFIG = {
        "orchestrator": {
            "model_id": "qwen-3-32b",
            "temperature": 0.4,
            "description": "전체 에이전트 조율 및 의사결정"
        },
        "search": {
            "model_id": "qwen-3-32b",
            "temperature": 0.1,
            "description": "뉴스 및 트렌드 수집 자료 분석"
        },
        "analyst": {
            "model_id": "qwen-3-32b",
            "temperature": 0.2,
            "description": "네이버 블로그 지표 분석 및 피드백"
        },
        "topic": {
            "model_id": "qwen-3-32b",
            "temperature": 0.7,
            "description": "블로그 주제 발제 및 트렌드 키워드 도출"
        },
        "writer": {
            "model_id": "qwen-3-32b",
            "temperature": 0.6,
            "description": "블로그 포스트 원고 초안 작성 (HTML)"
        },
        "briefer": {
            "model_id": "qwen-3-32b",
            "temperature": 0.1,
            "description": "섹션별 팩트·수치·사례 매핑 (자료정리대리)"
        },
        "editor": {
            "model_id": "qwen-3-32b",
            "temperature": 0.1,
            "description": "최종 검토, 이모지 필터링 및 포스팅 서식 변환"
        },
        "accountant": {
            "model_id": "llama-3.1-8b-instant",
            "temperature": 0.2,
            "description": "API 비용 정산 및 토큰 사용량 모니터링"
        }
    }

    # 비공식/단축 모델명 → Groq 정식 모델 ID 매핑
    REAL_MODEL_MAP = {
        "qwen-3-32b": "qwen/qwen3-32b",
    }

    @classmethod
    def get_config(cls, agent_key: str) -> dict:
        """
        에이전트 키에 따른 모델 ID와 temperature 설정을 가져옵니다.
        존재하지 않는 키의 경우 기본값(editor 설정)을 반환합니다.
        실존하지 않는 비공식 모델의 경우 실제 작동하는 공식 Groq 모델 ID로 자동 매핑합니다.
        """
        config = cls.CONFIG.get(agent_key, cls.CONFIG["editor"]).copy()
        model_id = config.get("model_id")
        if model_id in cls.REAL_MODEL_MAP:
            config["model_id"] = cls.REAL_MODEL_MAP[model_id]
        return config
