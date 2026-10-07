"""BGM 결정론 선택 (spec §9 — EstateReels bgmService 무드 구조 이식).
파일은 server/data/bgm/(git 미추적)에 두고, 없으면 무음 진행."""
import os
import pathlib

_MOOD = {"부동산": "documentary_calm", "재테크": "documentary_calm",
         "IT": "documentary_calm", "요리": "family_warm",
         "건강": "family_warm", "여행": "emotional_daily"}
_DEFAULT_MOOD = "documentary_calm"


def bgm_dir() -> pathlib.Path:
    p = os.environ.get("APP_BGM_DIR")
    d = pathlib.Path(p) if p else \
        pathlib.Path(__file__).resolve().parents[1] / "data" / "bgm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pick(category: str, seed: int) -> pathlib.Path | None:
    mood = _MOOD.get(category, _DEFAULT_MOOD)
    files = sorted(bgm_dir().glob(f"{mood}-*.mp3"))
    if not files:
        files = sorted(bgm_dir().glob("*.mp3"))
    if not files:
        return None
    return files[seed % len(files)]
