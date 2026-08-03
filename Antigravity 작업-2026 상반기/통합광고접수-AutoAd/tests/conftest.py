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
