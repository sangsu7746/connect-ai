def test_init_creates_tables(db):
    names = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"categories", "seed_keywords", "trends", "posts", "diagnoses"} <= names

def test_init_adds_columns_to_existing_db(tmp_path, monkeypatch):
    """이미 만들어진 DB에도 나중에 추가된 컬럼이 붙어야 한다.

    SCHEMA는 CREATE TABLE IF NOT EXISTS 라서 기존 테이블을 건드리지 않는다 —
    마이그레이션이 없으면 새 DB인 테스트만 통과하고 사용자 DB는 "no such column"
    으로 죽는다(실제 발생). 그래서 구버전 DB를 직접 만들어 검증한다.
    """
    import sqlite3
    path = tmp_path / "old.db"
    monkeypatch.setenv("APP_DB_PATH", str(path))
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE categories(id INTEGER PRIMARY KEY AUTOINCREMENT,
                                name TEXT UNIQUE NOT NULL, emoji TEXT DEFAULT '');
        CREATE TABLE posts(id INTEGER PRIMARY KEY AUTOINCREMENT,
                           category_id INTEGER NOT NULL, keyword TEXT,
                           source TEXT NOT NULL, title TEXT NOT NULL,
                           url TEXT NOT NULL UNIQUE, content TEXT DEFAULT '');
        INSERT INTO categories(name) VALUES('보존됨');
        INSERT INTO posts(category_id,source,title,url,content)
        VALUES(1,'naver','옛 글','http://old','본문');
    """)
    old.commit()
    old.close()

    from core import db as dbm
    dbm.init_db()

    conn = dbm.get_conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(posts)")}
    assert {"image_urls_json", "image_facts_json"} <= cols
    # 기존 행은 살아 있고 새 컬럼은 기본값으로 채워진다
    row = conn.execute("SELECT title, image_urls_json FROM posts").fetchone()
    assert row["title"] == "옛 글" and row["image_urls_json"] == "[]"
    conn.close()


def test_posts_url_unique(db):
    db.execute("INSERT INTO categories(name) VALUES('t')")
    db.execute("""INSERT INTO posts(category_id,source,title,url)
                  VALUES(1,'naver','a','http://x')""")
    import sqlite3, pytest
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("""INSERT INTO posts(category_id,source,title,url)
                      VALUES(1,'google','b','http://x')""")
