import os
import sys
import tempfile
from pathlib import Path

import pytest

# 프로젝트 루트를 import 경로에 넣는다 (tests/ 에서 실행해도 config·db 를 찾도록)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def temp_db(monkeypatch):
    """테스트마다 빈 DB. 실제 data/autoad.db 를 절대 건드리지 않는다."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import config
    monkeypatch.setattr(config, "DB_PATH", Path(path))
    import db
    monkeypatch.setattr(db, "DB_PATH", Path(path), raising=False)
    db.init_db()
    yield Path(path)
    try:
        Path(path).unlink()
    except OSError:
        pass


# pytest 훅의 인자 이름은 hookspec 과 정확히 같아야 한다(pluggy 가 이름으로
# 매칭해서 주입한다) -- pytest_configure(config), pytest_collection_modifyitems
# (session, config, items). task-8-brief.md 의 원안은 이 프로젝트의 config
# 모듈과 헷갈리지 않으려고 인자를 pyconfig 로 이름을 바꿨는데, 그러면 pluggy 가
# hookspec 에서 "pyconfig" 라는 인자를 못 찾아 PluginValidationError 로
# conftest.py 로딩 자체가 깨진다(테스트 전체가 한 개도 못 돈다). 그래서 여기서는
# hookspec 대로 config 를 쓰고, 이 프로젝트의 config 모듈과 헷갈리지 않게
# 이 두 함수 안에서는 project config 를 import/참조하지 않는다.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "golden: 실제 LLM 을 호출하는 골든셋 테스트 (할당량 소모)")


def pytest_collection_modifyitems(config, items):
    """평소엔 golden 을 건너뛴다. 돌리려면 `pytest -m golden`."""
    if config.getoption("-m") == "golden":
        return
    skip = pytest.mark.skip(reason="골든셋은 `pytest -m golden` 으로만")
    for item in items:
        if "golden" in item.keywords:
            item.add_marker(skip)
