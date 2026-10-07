# -*- coding: utf-8 -*-
"""engine.py — 발행 엔진(자동포스팅 프로그램) 불러오기

밴드·페북 발행은 별도 프로그램의 자동화 엔진을 그대로 쓴다.
그 엔진들은 `from app.paths import get_data_dir` 처럼 **자기 패키지 이름 `app`**
을 쓰는데, AutoAd 에도 `app.py`(FastAPI 서버)가 있어 이름이 부딪힌다.
서버 프로세스에서는 sys.modules['app'] 이 이미 AutoAd 것이라 엔진 임포트가 깨진다.

→ 임포트하는 동안만 프로그램 루트를 경로 맨 앞에 두고, `app` 을 잠시 치워 둔다.
  끝나면 원래대로 되돌려 AutoAd 쪽에 영향이 남지 않게 한다.
"""
import sys
import importlib
import threading
from pathlib import Path

_LOCK = threading.Lock()
_CACHE = {}


def load(app_dir: str, module: str):
    """app_dir(프로그램의 app 폴더)에서 module 을 불러온다.

    module 예: 'facebook_automator' / 'band_automator'
    """
    key = (str(app_dir), module)
    if key in _CACHE:
        return _CACHE[key]

    root = str(Path(app_dir).parent)          # 프로그램 루트(= app 의 부모)
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
        saved = {k: sys.modules.pop(k) for k in list(sys.modules)
                 if k == "app" or k.startswith("app.")}
        sys.path.insert(0, root)
        try:
            mod = importlib.import_module(f"app.{module}")
            _CACHE[key] = mod
            return mod
        finally:
            try:
                sys.path.remove(root)
            except ValueError:
                pass
            # 엔진이 자기 하위 모듈을 계속 쓸 수 있게 남겨두되,
            # AutoAd 의 app 은 반드시 원상 복구한다.
            for k in list(sys.modules):
                if k == "app" or k.startswith("app."):
                    if k in saved:
                        continue
                    sys.modules.pop(k, None)
            sys.modules.update(saved)
