import os, pathlib, sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  emoji TEXT DEFAULT '📁'
);
CREATE TABLE IF NOT EXISTS seed_keywords(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  keyword TEXT NOT NULL,
  UNIQUE(category_id, keyword)
);
CREATE TABLE IF NOT EXISTS trends(
  category_id INTEGER NOT NULL,
  keyword TEXT NOT NULL,
  ratio_last REAL, ratio_prev REAL, rise_pct REAL,
  fetched_at TEXT,
  PRIMARY KEY(category_id, keyword)
);
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  keyword TEXT,
  source TEXT NOT NULL CHECK(source IN('naver','google')),
  title TEXT NOT NULL,
  url TEXT NOT NULL UNIQUE,
  summary TEXT DEFAULT '',
  blogger TEXT DEFAULT '',
  posted_at TEXT DEFAULT '',
  content TEXT DEFAULT '',
  image_urls_json TEXT DEFAULT '[]',
  image_facts_json TEXT DEFAULT '[]',
  crawled_at TEXT,
  fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS diagnoses(
  post_id INTEGER PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  score INTEGER NOT NULL,
  verdict TEXT NOT NULL,
  answers_json TEXT NOT NULL,
  hooks_json TEXT NOT NULL,
  diagnosed_at TEXT
);
CREATE TABLE IF NOT EXISTS scripts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  post_ids_json TEXT NOT NULL,
  fmt TEXT NOT NULL CHECK(fmt IN('reels','long')),
  duration_sec INTEGER NOT NULL,
  analysis_json TEXT NOT NULL,
  scenes_json TEXT NOT NULL,
  description_md TEXT DEFAULT '',
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS articles(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  post_ids_json TEXT NOT NULL,
  title TEXT NOT NULL,
  body_md TEXT NOT NULL,
  warnings_json TEXT DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN('draft','published')),
  published_urls_json TEXT DEFAULT '{}',
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS images(
  hash TEXT PRIMARY KEY,
  style_id TEXT NOT NULL,
  prompt TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  file TEXT NOT NULL,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN('running','done','error')),
  progress INTEGER DEFAULT 0,
  total INTEGER DEFAULT 0,
  result_json TEXT DEFAULT '{}',
  error TEXT DEFAULT '',
  ref TEXT DEFAULT '',
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS renders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
  file TEXT NOT NULL,
  duration_sec INTEGER NOT NULL,
  created_at TEXT
);
"""

def db_path() -> str:
    p = os.environ.get("APP_DB_PATH")
    if p:
        return p
    d = pathlib.Path(__file__).resolve().parents[1] / "data"
    d.mkdir(exist_ok=True)
    return str(d / "app.db")

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
