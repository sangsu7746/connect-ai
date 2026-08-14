def test_init_creates_tables(db):
    names = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"categories", "seed_keywords", "trends", "posts", "diagnoses"} <= names

def test_posts_url_unique(db):
    db.execute("INSERT INTO categories(name) VALUES('t')")
    db.execute("""INSERT INTO posts(category_id,source,title,url)
                  VALUES(1,'naver','a','http://x')""")
    import sqlite3, pytest
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("""INSERT INTO posts(category_id,source,title,url)
                      VALUES(1,'google','b','http://x')""")
