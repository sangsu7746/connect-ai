import os, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import pytest

@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "test.db"))
    from core import db as dbm
    dbm.init_db()
    conn = dbm.get_conn()
    yield conn
    conn.close()
