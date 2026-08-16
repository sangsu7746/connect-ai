"""이미지 스타일팩 6종 로더 + 씬 롤/카테고리 매핑 (spec §8)."""
import json
import pathlib
from functools import lru_cache

COMMON_NEGATIVE = ("text, watermark, letters, typography, logo, signature, "
                   "low quality, blurry, deformed")

_ROLE_FIXED = {"hook": "cinematic", "summary": "neon_abstract",
               "cta": "neon_abstract", "twist": "papercut"}
_CATEGORY_DEFAULT = {"부동산": "isometric", "재테크": "flat_vector",
                     "IT": "flat_vector", "건강": "pastel_anime",
                     "요리": "pastel_anime", "여행": "pastel_anime"}
_FALLBACK = "flat_vector"


@lru_cache(maxsize=1)
def load() -> dict:
    p = pathlib.Path(__file__).with_name("style_packs.json")
    return json.loads(p.read_text(encoding="utf-8"))


def pick(role: str, category_name: str) -> str:
    if role in _ROLE_FIXED:
        return _ROLE_FIXED[role]
    return _CATEGORY_DEFAULT.get(category_name, _FALLBACK)
