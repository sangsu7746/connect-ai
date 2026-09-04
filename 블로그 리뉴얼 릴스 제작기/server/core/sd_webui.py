"""SD WebUI(A1111) API 클라이언트 (spec §8). DreamShaper 8 로드 상태를 전제로
현재 모델을 그대로 사용한다(모델 전환 API는 쓰지 않는다 — 단일 체크포인트 환경)."""
import base64

import httpx

from .config import settings


class SDError(RuntimeError):
    pass


def available() -> bool:
    try:
        r = httpx.get(f"{settings.sd_webui_url}/sdapi/v1/sd-models", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def txt2img(prompt: str, negative: str, width: int, height: int) -> bytes:
    try:
        r = httpx.post(f"{settings.sd_webui_url}/sdapi/v1/txt2img",
                       json={"prompt": prompt, "negative_prompt": negative,
                             "width": width, "height": height,
                             "steps": 25, "cfg_scale": 7,
                             "sampler_name": "DPM++ 2M Karras", "seed": -1},
                       timeout=180)
    except Exception as e:
        raise SDError(f"SD WebUI 호출 실패: {type(e).__name__}")
    if r.status_code != 200:
        raise SDError(f"SD WebUI HTTP {r.status_code}")
    try:
        images = r.json().get("images") or []
        if not images:
            raise SDError("SD WebUI가 이미지를 반환하지 않음")
        return base64.b64decode(images[0], validate=True)
    except SDError:
        raise
    except Exception as e:
        raise SDError(f"SD WebUI 응답 파싱 실패: {type(e).__name__}")
