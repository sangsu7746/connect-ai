import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "gemini_api_key": "",  # 실제 키는 config.json 에 둔다. 여기 적으면 저장소에 그대로 올라간다,
    "groq_api_key": "",
    "naver_id": "",
    "naver_pw": "",
    "default_topic": "",
    "default_keywords": "",
    "default_category": "",
    "schedule_enabled": False,
    "schedule_time": "09:00",
    "schedule_topic": "",
    "schedule_keywords": "",
    "headless_mode": False,
}


def load_config() -> dict:
    """설정 파일을 불러옵니다."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 새로 추가된 키는 기본값으로 채움
            for k, v in DEFAULT_CONFIG.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """설정을 파일에 저장합니다."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
