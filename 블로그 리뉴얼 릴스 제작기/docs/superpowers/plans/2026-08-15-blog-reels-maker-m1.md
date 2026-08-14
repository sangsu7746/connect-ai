# 블로그 리뉴얼 릴스 제작기 — M1 (수집·카테고리 리스트·보랏빛 배지) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 네이버+구글 검색 상위 블로그 글을 카테고리별로 수집·진단(보랏빛 점수)해 웹 UI 리스트로 보여주는 동작물을 만든다.

**Architecture:** FastAPI(8792) 로컬 서버가 네이버 검색/DataLab·구글 CSE 수집, 본문 크롤링(폴백 체인), 보랏빛소 블로그판 진단을 수행하고 SQLite에 저장. React+Vite(5175) 프론트가 카테고리 대시보드와 카테고리별 글 리스트(소스 필터·보랏빛 배지)를 렌더. 프론트→서버는 Vite 프록시(/api) 경유라 CORS 불필요.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, httpx, BeautifulSoup4, trafilatura, sqlite3(stdlib), pytest / React 19 + TypeScript + Vite, react-router-dom

**Spec:** `docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md`

## Global Constraints

- 포트: 서버 **8792**, 웹 **5175** (spec §3)
- DB: SQLite, 경로 `server/data/app.db`, 테스트는 env `APP_DB_PATH`로 격리
- .env 키 이름(정확히): `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `GOOGLE_CSE_KEY`, `GOOGLE_CSE_ID` (spec §3)
- posts.source 값은 `naver` | `google` 두 가지뿐 (spec §5)
- 진단은 **수집 데이터에서만** 판정한다 — LLM 추론 금지 (spec §6)
- verdict 5단계 문자열(정확히): `보랏빛 소`(4) / `보랏빛에 가깝다`(3) / `회색 소`(2) / `갈색 소`(1) / `완전한 갈색 소`(0)
- 외부 API 호출 코드는 전부 mock/fixture로 테스트 (spec §11 — 오프라인 CI 가능)
- 커밋은 태스크마다. 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 모든 명령은 프로젝트 루트 `D:\블로그 리뉴얼 릴스 제작기` 기준. Windows PowerShell에서는 `&&` 대신 `;` 사용

---

### Task 1: 서버 스캐폴드 (config·DB·health)

**Files:**
- Create: `server/requirements.txt`
- Create: `server/core/__init__.py`, `server/api/__init__.py`, `server/tests/__init__.py`
- Create: `server/core/config.py`
- Create: `server/core/db.py`
- Create: `server/main.py`
- Create: `server/tests/conftest.py`
- Test: `server/tests/test_db.py`
- Create: `.env.example`, `.gitignore`

**Interfaces:**
- Produces: `core.config.settings` (속성: `naver_client_id`, `naver_client_secret`, `google_cse_key`, `google_cse_id`, `server_port:int=8792`), `core.db.get_conn() -> sqlite3.Connection`(row_factory=sqlite3.Row, FK ON), `core.db.init_db()`, FastAPI `app`(main.py) — 이후 모든 태스크가 사용

- [ ] **Step 1: 환경 파일 작성**

`server/requirements.txt`:
```
fastapi
uvicorn[standard]
httpx
python-dotenv
beautifulsoup4
trafilatura
playwright
pytest
```

`.env.example`:
```
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
GOOGLE_CSE_KEY=
GOOGLE_CSE_ID=
SERVER_PORT=8792
```

`.gitignore` (프로젝트 루트, 없으면 생성):
```
.env
server/.venv/
server/data/
__pycache__/
web/node_modules/
web/dist/
```

- [ ] **Step 2: venv 생성 + 의존성 설치**

Run: `cd server; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt`
Expected: 오류 없이 설치 완료

- [ ] **Step 3: 실패하는 테스트 작성**

`server/tests/conftest.py`:
```python
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
```

`server/tests/test_db.py`:
```python
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
```

- [ ] **Step 4: 실패 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_db.py -v`
Expected: FAIL (`ModuleNotFoundError: core` 또는 테이블 없음)

- [ ] **Step 5: 구현**

`server/core/config.py`:
```python
import os, pathlib
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

class Settings:
    naver_client_id = os.getenv("NAVER_CLIENT_ID", "")
    naver_client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
    google_cse_key = os.getenv("GOOGLE_CSE_KEY", "")
    google_cse_id = os.getenv("GOOGLE_CSE_ID", "")
    server_port = int(os.getenv("SERVER_PORT", "8792"))

settings = Settings()
```

`server/core/db.py`:
```python
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
```

`server/main.py`:
```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fastapi import FastAPI
from core.db import init_db

app = FastAPI(title="blog-reels-maker")
init_db()

@app.get("/api/health")
def health():
    return {"ok": True}
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_db.py -v`
Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add server/ .env.example .gitignore
git commit -m "feat(blog-reels): M1 서버 스캐폴드 — config·SQLite 스키마·health"
```

---

### Task 2: 카테고리·시드 키워드 API + 초기 데이터

**Files:**
- Create: `server/api/categories.py`
- Create: `server/core/seed_data.py`
- Modify: `server/main.py` (라우터 등록 + 시드 주입)
- Test: `server/tests/test_categories.py`

**Interfaces:**
- Consumes: `core.db.get_conn/init_db`
- Produces: REST — `GET /api/categories`(각 항목 `{id,name,emoji,keywords:[str],top_keywords:[{keyword,rise_pct}]}`), `POST /api/categories {name,emoji?}`, `DELETE /api/categories/{cid}`, `POST /api/categories/{cid}/keywords {keyword}`, `DELETE /api/categories/{cid}/keywords/{keyword}` · `core.seed_data.ensure_seed(conn)` — 카테고리 0개일 때 기본 6종+시드 5개씩 주입

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_categories.py`:
```python
from fastapi.testclient import TestClient

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def test_seed_categories_exist(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    cats = c.get("/api/categories").json()
    assert len(cats) == 6
    assert {"부동산", "재테크", "건강", "요리", "여행", "IT"} == {x["name"] for x in cats}
    assert all(len(x["keywords"]) == 5 for x in cats)

def test_add_delete_category_and_keyword(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    r = c.post("/api/categories", json={"name": "육아", "emoji": "🍼"})
    cid = r.json()["id"]
    c.post(f"/api/categories/{cid}/keywords", json={"keyword": "이유식"})
    cats = {x["name"]: x for x in c.get("/api/categories").json()}
    assert cats["육아"]["keywords"] == ["이유식"]
    c.delete(f"/api/categories/{cid}/keywords/이유식")
    c.delete(f"/api/categories/{cid}")
    assert "육아" not in {x["name"] for x in c.get("/api/categories").json()}
```

- [ ] **Step 2: 실패 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_categories.py -v`
Expected: FAIL (라우트 404)

- [ ] **Step 3: 구현**

`server/core/seed_data.py`:
```python
SEED = {
    "부동산": ("🏠", ["전세 보증보험", "청약 가점", "재개발 투자", "월세 계약", "등기부등본 보는법"]),
    "재테크": ("💰", ["ISA 계좌", "연금저축펀드", "파킹통장 금리", "배당주 투자", "연말정산 절세"]),
    "건강":   ("💪", ["단백질 섭취량", "수면의 질", "혈당 관리", "허리 통증 스트레칭", "간헐적 단식"]),
    "요리":   ("🍳", ["에어프라이어 레시피", "밑반찬 만들기", "자취 요리", "도시락 메뉴", "김치찌개 황금레시피"]),
    "여행":   ("✈️", ["제주 여행 코스", "일본 여행 준비물", "국내 당일치기", "캠핑 준비물", "호텔 싸게 예약"]),
    "IT":     ("💻", ["아이폰 숨은기능", "노션 활용법", "챗GPT 활용", "윈도우 단축키", "갤럭시 설정"]),
}

def ensure_seed(conn) -> None:
    if conn.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"]:
        return
    for name, (emoji, kws) in SEED.items():
        cur = conn.execute(
            "INSERT INTO categories(name, emoji) VALUES(?,?)", (name, emoji))
        for kw in kws:
            conn.execute(
                "INSERT INTO seed_keywords(category_id, keyword) VALUES(?,?)",
                (cur.lastrowid, kw))
    conn.commit()
```

`server/api/categories.py`:
```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.db import get_conn

router = APIRouter(prefix="/api/categories", tags=["categories"])

class CategoryIn(BaseModel):
    name: str
    emoji: str = "📁"

class KeywordIn(BaseModel):
    keyword: str

@router.get("")
def list_categories():
    conn = get_conn()
    try:
        out = []
        for c in conn.execute("SELECT * FROM categories ORDER BY id"):
            kws = [r["keyword"] for r in conn.execute(
                "SELECT keyword FROM seed_keywords WHERE category_id=? ORDER BY id",
                (c["id"],))]
            top = [dict(r) for r in conn.execute(
                """SELECT keyword, rise_pct FROM trends WHERE category_id=?
                   ORDER BY rise_pct DESC LIMIT 5""", (c["id"],))]
            out.append({"id": c["id"], "name": c["name"], "emoji": c["emoji"],
                        "keywords": kws, "top_keywords": top})
        return out
    finally:
        conn.close()

@router.post("")
def add_category(body: CategoryIn):
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO categories(name, emoji) VALUES(?,?)",
                           (body.name, body.emoji))
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()

@router.delete("/{cid}")
def delete_category(cid: int):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM categories WHERE id=?", (cid,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

@router.post("/{cid}/keywords")
def add_keyword(cid: int, body: KeywordIn):
    conn = get_conn()
    try:
        if not conn.execute("SELECT 1 FROM categories WHERE id=?", (cid,)).fetchone():
            raise HTTPException(404, "category not found")
        conn.execute(
            "INSERT OR IGNORE INTO seed_keywords(category_id, keyword) VALUES(?,?)",
            (cid, body.keyword))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()

@router.delete("/{cid}/keywords/{keyword}")
def delete_keyword(cid: int, keyword: str):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM seed_keywords WHERE category_id=? AND keyword=?",
                     (cid, keyword))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
```

`server/main.py` 전체 교체:
```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fastapi import FastAPI
from core.db import init_db, get_conn
from core.seed_data import ensure_seed
from api.categories import router as categories_router

app = FastAPI(title="blog-reels-maker")
init_db()
_conn = get_conn()
ensure_seed(_conn)
_conn.close()

app.include_router(categories_router)

@app.get("/api/health")
def health():
    return {"ok": True}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/ -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add server/
git commit -m "feat(blog-reels): 카테고리·시드 키워드 CRUD + 기본 6종 시드"
```

---

### Task 3: 네이버 블로그 검색 클라이언트

**Files:**
- Create: `server/core/naver.py`
- Test: `server/tests/test_naver.py`

**Interfaces:**
- Consumes: `core.config.settings`
- Produces: `core.naver.search_blog(query: str, display: int = 10) -> list[dict]` — dict 키: `source('naver'), title, url, summary, blogger, posted_at` · `core.naver.clean_html(s: str) -> str`

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_naver.py`:
```python
import httpx
from core import naver

FAKE = {"items": [{
    "title": "전세 <b>보증보험</b> 가입법 &amp; 비용",
    "link": "https://blog.naver.com/abc/123",
    "description": "보증료는 <b>연 0.128%</b>입니다",
    "bloggername": "부동산왕", "postdate": "20260810",
}]}

def test_search_blog_parses(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        assert "openapi.naver.com" in url
        assert headers["X-Naver-Client-Id"] == "test-id"
        return httpx.Response(200, json=FAKE, request=httpx.Request("GET", url))
    monkeypatch.setattr(naver.settings, "naver_client_id", "test-id")
    monkeypatch.setattr(naver.settings, "naver_client_secret", "test-sec")
    monkeypatch.setattr(httpx, "get", fake_get)
    items = naver.search_blog("전세 보증보험")
    assert items[0]["title"] == "전세 보증보험 가입법 & 비용"
    assert items[0]["summary"] == "보증료는 연 0.128%입니다"
    assert items[0]["source"] == "naver"
    assert items[0]["posted_at"] == "20260810"

def test_clean_html():
    assert naver.clean_html("a<b>b</b> &quot;c&quot; &lt;d&gt;") == 'ab "c" <d>'
```

- [ ] **Step 2: 실패 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_naver.py -v`
Expected: FAIL (`ModuleNotFoundError` 또는 함수 없음)

- [ ] **Step 3: 구현**

`server/core/naver.py`:
```python
import html, re
import httpx
from .config import settings

def clean_html(s: str) -> str:
    return html.unescape(re.sub(r"</?b>", "", s or "")).strip()

def _headers() -> dict:
    return {"X-Naver-Client-Id": settings.naver_client_id,
            "X-Naver-Client-Secret": settings.naver_client_secret}

def search_blog(query: str, display: int = 10) -> list[dict]:
    r = httpx.get("https://openapi.naver.com/v1/search/blog.json",
                  params={"query": query, "display": display, "sort": "sim"},
                  headers=_headers(), timeout=10)
    r.raise_for_status()
    return [{
        "source": "naver",
        "title": clean_html(it.get("title", "")),
        "url": it.get("link", ""),
        "summary": clean_html(it.get("description", "")),
        "blogger": it.get("bloggername", ""),
        "posted_at": it.get("postdate", ""),
    } for it in r.json().get("items", [])]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_naver.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add server/core/naver.py server/tests/test_naver.py
git commit -m "feat(blog-reels): 네이버 블로그 검색 클라이언트"
```

---

### Task 4: DataLab 트렌드 순위화 + refresh API

**Files:**
- Modify: `server/core/naver.py` (datalab 함수 추가)
- Create: `server/api/trends.py`
- Modify: `server/main.py` (라우터 등록 1줄)
- Test: `server/tests/test_trends.py`

**Interfaces:**
- Consumes: `core.naver._headers`, `core.db.get_conn`
- Produces: `core.naver.datalab_ratios(keywords: list[str]) -> dict[str, tuple[float, float]]` — 키워드→(최근주 ratio, 이전주 ratio), 5개씩 배치 호출 · `core.naver.rise_pct(last: float, prev: float) -> float` · REST `POST /api/categories/{cid}/trends/refresh` → `[{keyword, rise_pct}]` rise 내림차순

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_trends.py`:
```python
import httpx
from core import naver

def _fake_datalab_response(groups):
    return {"results": [
        {"title": g["groupName"],
         "data": [{"period": "2026-08-03", "ratio": 10.0},
                  {"period": "2026-08-10", "ratio": 25.0}]}
        for g in groups]}

def test_datalab_batches_of_five(monkeypatch):
    calls = []
    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(len(json["keywordGroups"]))
        return httpx.Response(200, json=_fake_datalab_response(json["keywordGroups"]),
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    out = naver.datalab_ratios([f"kw{i}" for i in range(7)])
    assert calls == [5, 2]                # 5개씩 배치
    assert out["kw0"] == (25.0, 10.0)     # (last, prev)

def test_rise_pct():
    assert naver.rise_pct(25.0, 10.0) == 150.0
    assert naver.rise_pct(10.0, 0.0) == 1000.0   # prev=0 → max(prev,1) 분모
```

- [ ] **Step 2: 실패 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_trends.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/naver.py`에 추가:
```python
import datetime as _dt

def rise_pct(last: float, prev: float) -> float:
    return round((last - prev) / max(prev, 1.0) * 100.0, 1)

def datalab_ratios(keywords: list[str]) -> dict[str, tuple[float, float]]:
    """키워드별 (최근주, 이전주) 검색 트렌드 ratio. 5개씩 배치 호출."""
    end = _dt.date.today() - _dt.timedelta(days=1)
    start = end - _dt.timedelta(weeks=8)
    out: dict[str, tuple[float, float]] = {}
    for i in range(0, len(keywords), 5):
        batch = keywords[i:i + 5]
        body = {
            "startDate": start.isoformat(), "endDate": end.isoformat(),
            "timeUnit": "week",
            "keywordGroups": [{"groupName": k, "keywords": [k]} for k in batch],
        }
        r = httpx.post("https://openapi.naver.com/v1/datalab/search",
                       json=body,
                       headers={**_headers(), "Content-Type": "application/json"},
                       timeout=15)
        r.raise_for_status()
        for res in r.json().get("results", []):
            data = res.get("data", [])
            last = data[-1]["ratio"] if data else 0.0
            prev = data[-2]["ratio"] if len(data) > 1 else 0.0
            out[res["title"]] = (last, prev)
    return out
```

`server/api/trends.py`:
```python
import datetime
from fastapi import APIRouter, HTTPException
from core.db import get_conn
from core import naver

router = APIRouter(prefix="/api/categories", tags=["trends"])

@router.post("/{cid}/trends/refresh")
def refresh_trends(cid: int):
    conn = get_conn()
    try:
        kws = [r["keyword"] for r in conn.execute(
            "SELECT keyword FROM seed_keywords WHERE category_id=?", (cid,))]
        if not kws:
            raise HTTPException(404, "no seed keywords")
        ratios = naver.datalab_ratios(kws)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        rows = []
        for kw, (last, prev) in ratios.items():
            rp = naver.rise_pct(last, prev)
            conn.execute("""INSERT INTO trends(category_id,keyword,ratio_last,
                            ratio_prev,rise_pct,fetched_at) VALUES(?,?,?,?,?,?)
                            ON CONFLICT(category_id,keyword) DO UPDATE SET
                            ratio_last=excluded.ratio_last,
                            ratio_prev=excluded.ratio_prev,
                            rise_pct=excluded.rise_pct,
                            fetched_at=excluded.fetched_at""",
                         (cid, kw, last, prev, rp, now))
            rows.append({"keyword": kw, "rise_pct": rp})
        conn.commit()
        return sorted(rows, key=lambda x: -x["rise_pct"])
    finally:
        conn.close()
```

`server/main.py`에 추가:
```python
from api.trends import router as trends_router
app.include_router(trends_router)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/ -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add server/
git commit -m "feat(blog-reels): DataLab 시드 키워드 트렌드 순위화"
```

---

### Task 5: 구글 CSE 검색 + SERP 파서 폴백

**Files:**
- Create: `server/core/google_search.py`
- Test: `server/tests/test_google.py`

**Interfaces:**
- Consumes: `core.config.settings`
- Produces: `core.google_search.search_blog(query: str, num: int = 10) -> list[dict]` — naver.search_blog와 동일 dict 형태(`source='google'`). CSE 키 있으면 API, 없으면 `[]` 반환 + `available() -> bool`. `BLOG_DOMAINS` 필터(티스토리·브런치·네이버·벨로그·미디엄), `parse_serp_html(html: str) -> list[dict]`(Playwright 폴백용 파서 — M1은 파서까지 구현, 브라우저 구동은 discover에서 CSE 부재 시에만 시도)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_google.py`:
```python
import httpx
from core import google_search as g

FAKE = {"items": [
    {"title": "ISA 계좌 총정리", "link": "https://abc.tistory.com/12",
     "snippet": "비과세 한도 200만원"},
    {"title": "ISA 광고", "link": "https://ad.example.com/x",
     "snippet": "광고"},
    {"title": "브런치 글", "link": "https://brunch.co.kr/@x/3",
     "snippet": "에세이"},
]}

def test_cse_filters_blog_domains(monkeypatch):
    monkeypatch.setattr(g.settings, "google_cse_key", "k")
    monkeypatch.setattr(g.settings, "google_cse_id", "cx")
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(
        200, json=FAKE, request=httpx.Request("GET", "u")))
    items = g.search_blog("ISA")
    assert [i["url"] for i in items] == [
        "https://abc.tistory.com/12", "https://brunch.co.kr/@x/3"]
    assert all(i["source"] == "google" for i in items)

def test_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(g.settings, "google_cse_key", "")
    assert g.search_blog("x") == []
    assert g.available() is False

def test_parse_serp_html():
    html = '''<div class="g"><a href="https://x.tistory.com/1"><h3>제목A</h3></a>
              <div class="VwiC3b">요약A</div></div>
              <div class="g"><a href="https://news.example.com/2"><h3>뉴스</h3></a></div>'''
    items = g.parse_serp_html(html)
    assert items == [{"source": "google", "title": "제목A",
                      "url": "https://x.tistory.com/1", "summary": "요약A",
                      "blogger": "", "posted_at": ""}]
```

- [ ] **Step 2: 실패 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_google.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/google_search.py`:
```python
import httpx
from bs4 import BeautifulSoup
from .config import settings

BLOG_DOMAINS = ("tistory.com", "brunch.co.kr", "blog.naver.com",
                "velog.io", "medium.com", "post.naver.com")

def _is_blog(url: str) -> bool:
    return any(d in url for d in BLOG_DOMAINS)

def available() -> bool:
    return bool(settings.google_cse_key and settings.google_cse_id)

def search_blog(query: str, num: int = 10) -> list[dict]:
    if not available():
        return []
    r = httpx.get("https://www.googleapis.com/customsearch/v1",
                  params={"key": settings.google_cse_key,
                          "cx": settings.google_cse_id,
                          "q": query, "num": min(num, 10)},
                  timeout=10)
    r.raise_for_status()
    return [{
        "source": "google",
        "title": it.get("title", ""),
        "url": it.get("link", ""),
        "summary": it.get("snippet", ""),
        "blogger": "", "posted_at": "",
    } for it in r.json().get("items", []) if _is_blog(it.get("link", ""))]

def parse_serp_html(html: str) -> list[dict]:
    """Playwright로 받은 구글 SERP HTML에서 블로그 결과만 추출 (CSE 키 부재 시 폴백)."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for block in soup.select("div.g"):
        a = block.select_one("a[href]")
        h3 = block.select_one("h3")
        if not a or not h3 or not _is_blog(a["href"]):
            continue
        sn = block.select_one("div.VwiC3b")
        out.append({"source": "google", "title": h3.get_text(strip=True),
                    "url": a["href"],
                    "summary": sn.get_text(strip=True) if sn else "",
                    "blogger": "", "posted_at": ""})
    return out

def search_blog_playwright(query: str, num: int = 10) -> list[dict]:
    """CSE 키가 없을 때의 폴백. 설치된 Chrome 채널로 구글 SERP를 연다.
    실패는 조용히 [] — 수집은 네이버만으로도 진행돼야 한다 (spec §10)."""
    from urllib.parse import quote_plus
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome", headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)
            page = browser.new_page(locale="ko-KR")
            page.goto(f"https://www.google.com/search?q={quote_plus(query)}&num={num}",
                      timeout=15000)
            html = page.content()
            browser.close()
        return parse_serp_html(html)
    except Exception:
        return []
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_google.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add server/core/google_search.py server/tests/test_google.py
git commit -m "feat(blog-reels): 구글 CSE 검색 + SERP 파서 폴백 (블로그 도메인 필터)"
```

---

### Task 6: 본문 크롤러 (네이버 모바일 → trafilatura → jina 폴백)

**Files:**
- Create: `server/core/crawler.py`
- Test: `server/tests/test_crawler.py`

**Interfaces:**
- Consumes: httpx, BeautifulSoup, trafilatura
- Produces: `core.crawler.fetch_content(url: str) -> str` — 본문 텍스트(실패 시 ""). 내부: `to_mobile_naver(url) -> str|None`, `extract_naver(html) -> str`, `extract_generic(html, url) -> str`(trafilatura), 마지막 폴백 `fetch_jina(url) -> str`(`https://r.jina.ai/<url>`)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_crawler.py`:
```python
from core import crawler

def test_to_mobile_naver():
    assert crawler.to_mobile_naver("https://blog.naver.com/abc/223999") == \
        "https://m.blog.naver.com/abc/223999"
    assert crawler.to_mobile_naver("https://x.tistory.com/1") is None

def test_extract_naver_smarteditor():
    html = '<div class="se-main-container"><p>본문 첫줄</p><p>둘째 줄 3,000원</p></div>'
    assert crawler.extract_naver(html) == "본문 첫줄\n둘째 줄 3,000원"

def test_extract_naver_legacy():
    html = '<div id="postViewArea"><p>옛날 에디터 본문</p></div>'
    assert crawler.extract_naver(html) == "옛날 에디터 본문"

def test_fetch_content_falls_back_to_jina(monkeypatch):
    monkeypatch.setattr(crawler, "_get", lambda url: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(crawler, "fetch_jina", lambda url: "지나 본문")
    assert crawler.fetch_content("https://x.tistory.com/1") == "지나 본문"
```

- [ ] **Step 2: 실패 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_crawler.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/crawler.py`:
```python
import re
import httpx
import trafilatura
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

def _get(url: str) -> str:
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text

def to_mobile_naver(url: str) -> str | None:
    m = re.match(r"https?://blog\.naver\.com/([^/]+)/(\d+)", url)
    if m:
        return f"https://m.blog.naver.com/{m.group(1)}/{m.group(2)}"
    return None

def extract_naver(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one("div.se-main-container") or soup.select_one("#postViewArea")
    if not box:
        return ""
    lines = [t.strip() for t in box.stripped_strings]
    return "\n".join(x for x in lines if x)

def extract_generic(html: str, url: str) -> str:
    return trafilatura.extract(html, url=url) or ""

def fetch_jina(url: str) -> str:
    try:
        r = httpx.get(f"https://r.jina.ai/{url}",
                      headers={"User-Agent": UA}, timeout=20)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""

def fetch_content(url: str) -> str:
    try:
        mobile = to_mobile_naver(url)
        if mobile:
            text = extract_naver(_get(mobile))
        else:
            text = extract_generic(_get(url), url)
        if text and len(text) >= 80:
            return text
    except Exception:
        pass
    return fetch_jina(url)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_crawler.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add server/core/crawler.py server/tests/test_crawler.py
git commit -m "feat(blog-reels): 본문 크롤러 — 네이버 모바일·trafilatura·jina 폴백"
```

---

### Task 7: 보랏빛소 블로그판 진단 (purple_cow_blog)

**Files:**
- Create: `server/core/purple_cow_blog.py`
- Test: `server/tests/test_purple_cow_blog.py`

**Interfaces:**
- Consumes: 없음 (순수 함수, stdlib만 — 원본 purple_cow.py 원칙: 수집 데이터만으로 판정)
- Produces: `core.purple_cow_blog.diagnose(post: dict, corpus: list[dict]) -> dict` — post는 `{title, summary, content, source}`, corpus는 같은 수집 배치의 다른 글들. 반환 `{score:int(0~4), verdict:str, answers:[{key,q,yes,evidence}], hooks:[str]}` · `VERDICTS: dict[int,str]` · 내부 `extract_numbers(text) -> list[tuple[str,float,str]]`(원문표기,값,단위)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_purple_cow_blog.py`:
```python
from core import purple_cow_blog as pc

RICH = {"title": "전세 보증보험 가입 총정리", "source": "naver", "summary": "",
        "content": ("전세 보증보험은 보증료가 연 0.128%입니다. 3억 전세면 연 38만원."
                    "\n하지만 사실 집주인 동의는 필요 없습니다. 잘못 알려진 상식이죠."
                    "\n가입 방법\n1. 서류 준비\n2. 앱 신청\n3. 보증료 납부"
                    "\n체크리스트를 꼭 확인하세요.")}
POOR = {"title": "오늘의 일기", "source": "naver", "summary": "",
        "content": "오늘은 날씨가 좋았다. 산책을 했다."}
CORPUS = [
    {"title": "전세 보증보험 가입방법 정리", "source": "naver"},
    {"title": "전세 보증보험 비용 후기", "source": "google"},
    {"title": "고양이 간식 추천", "source": "naver"},
]

def test_rich_post_scores_high():
    d = pc.diagnose(RICH, CORPUS)
    assert d["score"] == 4
    assert d["verdict"] == "보랏빛 소"
    assert len(d["answers"]) == 4
    assert d["hooks"]                       # 훅 후보 존재
    assert any("0.128%" in h for h in d["hooks"])

def test_poor_post_scores_zero():
    d = pc.diagnose(POOR, [])
    assert d["score"] == 0
    assert d["verdict"] == "완전한 갈색 소"

def test_both_source_bonus():
    # 유사 글 1개뿐이어도 네이버+구글 양쪽 노출이면 no_discount YES (spec §5 가점)
    post = {"title": "파킹통장 금리 비교", "source": "naver", "summary": "", "content": ""}
    corpus = [{"title": "파킹통장 금리 총정리", "source": "google"}]
    d = pc.diagnose(post, corpus)
    nd = next(a for a in d["answers"] if a["key"] == "no_discount")
    assert nd["yes"] is True

def test_extract_numbers():
    nums = pc.extract_numbers("연 0.128%이고 3억이며 38만원, 2026년")
    units = [u for _, _, u in nums]
    assert "%" in units and "억" in units and "만원" in units

def test_evidence_only_from_data():
    # 진단 근거는 반드시 원문 부분 문자열 (LLM 추론 금지 원칙)
    d = pc.diagnose(RICH, CORPUS)
    for a in d["answers"]:
        if a["yes"] and a["key"] != "no_discount":
            assert a["evidence"] in (RICH["content"] + RICH["title"] + RICH["summary"])
```

- [ ] **Step 2: 실패 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_purple_cow_blog.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/purple_cow_blog.py`:
```python
"""보랏빛소 4문항 진단 — 블로그 콘텐츠판.

원본(쿠팡 purple_cow.py)의 원칙 유지:
- 판정은 수집 데이터에서만. 모델 추론으로 YES를 만들지 않는다.
- evidence는 항상 원문에서 잘라낸 문자열.
원본 4문항을 콘텐츠 기준으로 각색 (spec §6 표):
  one_second   구체 숫자 훅 후보 존재
  what_is_that 통념 반박 마커 존재
  sneezer      실행 가능한 팁 구조(목록/단계) 존재
  no_discount  검색 상위 다수 노출(유사 제목) — 양 소스 노출 시 가점
"""
import re

CHECKLIST = [
    ("one_second", "단 1초 만에 시선을 잡을 구체 숫자·사실이 있는가?"),
    ("what_is_that", "'이건 뭐야?' 반응을 부를 통념 반박·의외성이 있는가?"),
    ("sneezer", "보는 사람이 저장·공유할 실행 팁(단계·체크리스트)이 있는가?"),
    ("no_discount", "검색 상위 다수가 다루는 검증된 수요 주제인가?"),
]

VERDICTS = {4: "보랏빛 소", 3: "보랏빛에 가깝다", 2: "회색 소",
            1: "갈색 소", 0: "완전한 갈색 소"}

_NUM = re.compile(r"(\d[\d,\.]*)\s*(만원|억원|억|원|%|퍼센트|배|년|개월|주|일|시간|평|건|명|kg|km)")
_COUNTER = ("하지만 사실", "의외로", "오해", "반대로", "잘못 알", "잘못 알려진",
            "착각", "진짜 이유", "숨겨진", "하지 마세요", "필요 없습니다", "없습니다만")
_TIP_LINE = re.compile(r"^\s*(\d+[\.\)]|[①-⑩]|[-•·])\s*\S", re.M)
_TIP_WORDS = ("체크리스트", "방법", "단계", "순서", "꿀팁", "준비물")
_HOOK_UNITS = {"만원", "억", "억원", "%", "퍼센트", "배"}


def extract_numbers(text: str) -> list[tuple[str, float, str]]:
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0)
        try:
            val = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        out.append((raw, val, m.group(2)))
    return out


def _sentence_around(text: str, needle: str) -> str:
    """needle이 포함된 줄 전체를 반환. 마침표 기준으로 자르면 '0.128%' 같은
    소수점 숫자를 중간에서 끊으므로 줄 단위로만 자른다."""
    idx = text.find(needle)
    if idx < 0:
        return needle
    start = text.rfind("\n", 0, idx) + 1
    end = text.find("\n", idx + len(needle))
    if end == -1:
        end = len(text)
    return text[start:end].strip() or needle


def _title_tokens(title: str) -> set[str]:
    return {t for t in re.split(r"[^\w가-힣]+", title or "") if len(t) >= 2}


def diagnose(post: dict, corpus: list[dict]) -> dict:
    text = "\n".join(x for x in (post.get("title"), post.get("summary"),
                                 post.get("content")) if x)
    answers, hooks = [], []

    # Q1 one_second — 훅이 될 구체 숫자
    hook_nums = [(raw, val, unit) for raw, val, unit in extract_numbers(text)
                 if unit in _HOOK_UNITS or (unit == "원" and val >= 10000)]
    q1 = bool(hook_nums)
    ev1 = _sentence_around(text, hook_nums[0][0]) if q1 else ""
    if q1:
        hooks = [_sentence_around(text, raw) for raw, _, _ in hook_nums[:3]]
    answers.append({"key": "one_second", "q": CHECKLIST[0][1], "yes": q1,
                    "evidence": ev1})

    # Q2 what_is_that — 통념 반박 마커
    marker = next((mk for mk in _COUNTER if mk in text), None)
    answers.append({"key": "what_is_that", "q": CHECKLIST[1][1],
                    "yes": marker is not None,
                    "evidence": _sentence_around(text, marker) if marker else ""})

    # Q3 sneezer — 실행 팁 구조
    tip_lines = _TIP_LINE.findall(post.get("content") or "")
    tip_word = next((w for w in _TIP_WORDS if w in text), None)
    q3 = len(tip_lines) >= 3 or (len(tip_lines) >= 2 and tip_word is not None)
    ev3 = ""
    if q3:
        m = _TIP_LINE.search(post.get("content") or "")
        ev3 = _sentence_around(post.get("content") or "", m.group(0).strip()) if m \
            else _sentence_around(text, tip_word)
    answers.append({"key": "sneezer", "q": CHECKLIST[2][1], "yes": q3,
                    "evidence": ev3})

    # Q4 no_discount — 유사 제목 다수 노출 (+양 소스 가점, spec §5)
    mine = _title_tokens(post.get("title", ""))
    similar = []
    for other in corpus:
        toks = _title_tokens(other.get("title", ""))
        union = mine | toks
        if union and len(mine & toks) / len(union) >= 0.25:
            similar.append(other)
    sources = {post.get("source")} | {o.get("source") for o in similar}
    q4 = len(similar) >= 2 or (len(similar) >= 1 and {"naver", "google"} <= sources)
    answers.append({"key": "no_discount", "q": CHECKLIST[3][1], "yes": q4,
                    "evidence": f"유사 상위 글 {len(similar)}건, 소스 {sorted(s for s in sources if s)}"})

    score = sum(1 for a in answers if a["yes"])
    return {"score": score, "verdict": VERDICTS[score],
            "answers": answers, "hooks": hooks}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_purple_cow_blog.py -v`
Expected: 5 PASS. 실패하면 휴리스틱 임계값이 아니라 **테스트 픽스처가 규칙에 맞는지 먼저 확인**(원문 문자열 evidence 규칙).

- [ ] **Step 5: Commit**

```bash
git add server/core/purple_cow_blog.py server/tests/test_purple_cow_blog.py
git commit -m "feat(blog-reels): 보랏빛소 블로그판 4문항 진단 — 데이터 기반 판정"
```

---

### Task 8: discover 파이프라인 (수집→크롤→진단→저장) + posts API

**Files:**
- Create: `server/api/discover.py`
- Modify: `server/main.py` (라우터 등록 1줄)
- Test: `server/tests/test_discover.py`

**Interfaces:**
- Consumes: `naver.search_blog`, `google_search.search_blog/available`, `crawler.fetch_content`, `purple_cow_blog.diagnose`, `core.db.get_conn`
- Produces: REST — `POST /api/categories/{cid}/discover {keyword}` → 수집·진단 후 글 목록. `GET /api/categories/{cid}/posts?source=all|naver|google` → `[{id,source,title,url,summary,blogger,posted_at,keyword,score,verdict,hooks:[str]}]` score 내림차순

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_discover.py`:
```python
from fastapi.testclient import TestClient

NAVER_ITEMS = [
    {"source": "naver", "title": "전세 보증보험 총정리", "url": "https://blog.naver.com/a/1",
     "summary": "보증료 연 0.128%", "blogger": "b1", "posted_at": "20260810"},
    {"source": "naver", "title": "전세 보증보험 가입방법", "url": "https://blog.naver.com/a/2",
     "summary": "", "blogger": "b2", "posted_at": "20260809"},
]
GOOGLE_ITEMS = [
    {"source": "google", "title": "전세 보증보험 비용 후기", "url": "https://x.tistory.com/3",
     "summary": "3억 기준 38만원", "blogger": "", "posted_at": ""},
]

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    import api.discover as disc
    monkeypatch.setattr(disc.naver, "search_blog", lambda q, display=10: NAVER_ITEMS)
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: GOOGLE_ITEMS)
    monkeypatch.setattr(disc.crawler, "fetch_content",
                        lambda url: "본문. 보증료 연 0.128%입니다.\n1. 서류\n2. 신청\n3. 납부")
    return TestClient(main.app)

def test_discover_stores_and_diagnoses(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    r = c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    assert r.status_code == 200
    posts = c.get("/api/categories/1/posts").json()
    assert len(posts) == 3
    assert all(p["score"] is not None for p in posts)
    assert posts == sorted(posts, key=lambda p: -p["score"])

def test_discover_idempotent_by_url(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    assert len(c.get("/api/categories/1/posts").json()) == 3   # URL UNIQUE upsert

def test_source_filter(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    assert {p["source"] for p in
            c.get("/api/categories/1/posts?source=google").json()} == {"google"}

def test_google_playwright_fallback_when_no_cse(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    import api.discover as disc
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: [])
    monkeypatch.setattr(disc.google_search, "available", lambda: False)
    monkeypatch.setattr(disc.google_search, "search_blog_playwright",
                        lambda q, num=10: GOOGLE_ITEMS)
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    assert any(p["source"] == "google"
               for p in c.get("/api/categories/1/posts").json())
```

- [ ] **Step 2: 실패 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_discover.py -v`
Expected: FAIL

- [ ] **Step 3: 구현**

`server/api/discover.py`:
```python
import datetime, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.db import get_conn
from core import naver, google_search, crawler, purple_cow_blog

router = APIRouter(prefix="/api/categories", tags=["discover"])

class DiscoverIn(BaseModel):
    keyword: str

@router.post("/{cid}/discover")
def discover(cid: int, body: DiscoverIn):
    conn = get_conn()
    try:
        if not conn.execute("SELECT 1 FROM categories WHERE id=?", (cid,)).fetchone():
            raise HTTPException(404, "category not found")
        items = naver.search_blog(body.keyword, display=10)
        gitems = google_search.search_blog(body.keyword, num=10)
        if not gitems and not google_search.available():
            gitems = google_search.search_blog_playwright(body.keyword)
        items += gitems
        if not items:
            raise HTTPException(502, "검색 결과 없음 — API 키 설정을 확인하세요")
        now = datetime.datetime.now().isoformat(timespec="seconds")

        ids = []
        for it in items:
            conn.execute("""INSERT INTO posts(category_id,keyword,source,title,url,
                            summary,blogger,posted_at,fetched_at)
                            VALUES(?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(url) DO UPDATE SET
                            keyword=excluded.keyword, fetched_at=excluded.fetched_at""",
                         (cid, body.keyword, it["source"], it["title"], it["url"],
                          it["summary"], it["blogger"], it["posted_at"], now))
            ids.append(conn.execute("SELECT id FROM posts WHERE url=?",
                                    (it["url"],)).fetchone()["id"])
        conn.commit()

        # 본문 크롤 (없는 것만) → 진단
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM posts WHERE id IN ({','.join('?'*len(ids))})", ids)]
        for row in rows:
            if not row["content"]:
                content = crawler.fetch_content(row["url"])
                conn.execute("UPDATE posts SET content=?, crawled_at=? WHERE id=?",
                             (content, now, row["id"]))
                row["content"] = content
        for row in rows:
            corpus = [{"title": r["title"], "source": r["source"]}
                      for r in rows if r["id"] != row["id"]]
            d = purple_cow_blog.diagnose(row, corpus)
            conn.execute("""INSERT INTO diagnoses(post_id,score,verdict,answers_json,
                            hooks_json,diagnosed_at) VALUES(?,?,?,?,?,?)
                            ON CONFLICT(post_id) DO UPDATE SET
                            score=excluded.score, verdict=excluded.verdict,
                            answers_json=excluded.answers_json,
                            hooks_json=excluded.hooks_json,
                            diagnosed_at=excluded.diagnosed_at""",
                         (row["id"], d["score"], d["verdict"],
                          json.dumps(d["answers"], ensure_ascii=False),
                          json.dumps(d["hooks"], ensure_ascii=False), now))
        conn.commit()
        return {"count": len(rows)}
    finally:
        conn.close()

@router.get("/{cid}/posts")
def list_posts(cid: int, source: str = "all"):
    conn = get_conn()
    try:
        q = """SELECT p.id, p.source, p.title, p.url, p.summary, p.blogger,
                      p.posted_at, p.keyword, d.score, d.verdict, d.hooks_json
               FROM posts p LEFT JOIN diagnoses d ON d.post_id = p.id
               WHERE p.category_id=?"""
        args: list = [cid]
        if source in ("naver", "google"):
            q += " AND p.source=?"
            args.append(source)
        q += " ORDER BY COALESCE(d.score,-1) DESC, p.id DESC"
        out = []
        for r in conn.execute(q, args):
            row = dict(r)
            row["hooks"] = json.loads(row.pop("hooks_json") or "[]")
            out.append(row)
        return out
    finally:
        conn.close()
```

`server/main.py`에 추가:
```python
from api.discover import router as discover_router
app.include_router(discover_router)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/ -v`
Expected: 전부 PASS

- [ ] **Step 5: Commit**

```bash
git add server/
git commit -m "feat(blog-reels): discover 파이프라인 — 수집·크롤·진단·저장 + posts API"
```

---

### Task 9: 웹 스캐폴드 + 카테고리 대시보드

**Files:**
- Create: `web/` (Vite react-ts 스캐폴드)
- Create: `web/vite.config.ts` (포트 5175 + /api 프록시)
- Create: `web/src/api.ts`
- Create: `web/src/pages/Dashboard.tsx`
- Create: `web/src/App.tsx`, `web/src/index.css` (교체)

**Interfaces:**
- Consumes: Task 2·4 REST API
- Produces: `api.ts` — `getCategories(): Promise<Category[]>`, `refreshTrends(cid): Promise<TrendRow[]>`, `addCategory(name)`, `addKeyword(cid, kw)` · 타입 `Category {id,name,emoji,keywords,top_keywords}` · 라우트 `/`(Dashboard), `/category/:id`(Task 10)

- [ ] **Step 1: 스캐폴드 생성**

Run: `npm create vite@latest web -- --template react-ts; cd web; npm i; npm i react-router-dom`
Expected: web/ 생성, 의존성 설치 완료

- [ ] **Step 2: 설정·API 클라이언트·대시보드 구현**

`web/vite.config.ts` 전체 교체:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5175,
    proxy: { '/api': 'http://127.0.0.1:8792' },
  },
})
```

`web/src/api.ts`:
```ts
export interface TrendRow { keyword: string; rise_pct: number }
export interface Category {
  id: number; name: string; emoji: string
  keywords: string[]; top_keywords: TrendRow[]
}
export interface Post {
  id: number; source: 'naver' | 'google'; title: string; url: string
  summary: string; blogger: string; posted_at: string; keyword: string
  score: number | null; verdict: string | null; hooks: string[]
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}
export const getCategories = () =>
  fetch('/api/categories').then(r => j<Category[]>(r))
export const addCategory = (name: string) =>
  fetch('/api/categories', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }) }).then(r => j<{ id: number }>(r))
export const addKeyword = (cid: number, keyword: string) =>
  fetch(`/api/categories/${cid}/keywords`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword }) }).then(r => j<{ ok: boolean }>(r))
export const refreshTrends = (cid: number) =>
  fetch(`/api/categories/${cid}/trends/refresh`, { method: 'POST' })
    .then(r => j<TrendRow[]>(r))
export const discover = (cid: number, keyword: string) =>
  fetch(`/api/categories/${cid}/discover`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword }) }).then(r => j<{ count: number }>(r))
export const getPosts = (cid: number, source: string) =>
  fetch(`/api/categories/${cid}/posts?source=${source}`).then(r => j<Post[]>(r))
```

`web/src/pages/Dashboard.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Category, getCategories, addCategory, refreshTrends } from '../api'

export default function Dashboard() {
  const [cats, setCats] = useState<Category[]>([])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState<number | null>(null)

  const load = () => getCategories().then(setCats)
  useEffect(() => { load() }, [])

  const onRefresh = async (cid: number) => {
    setBusy(cid)
    try { await refreshTrends(cid); await load() }
    catch (e) { alert(`트렌드 갱신 실패: ${e}`) }
    finally { setBusy(null) }
  }

  return (
    <div className="page">
      <h1>📋 카테고리</h1>
      <div className="cards">
        {cats.map(c => (
          <div className="card" key={c.id}>
            <Link to={`/category/${c.id}`} className="card-title">
              {c.emoji} {c.name}
            </Link>
            <div className="chips">
              {(c.top_keywords.length ? c.top_keywords
                : c.keywords.slice(0, 5).map(k => ({ keyword: k, rise_pct: 0 })))
                .map(t => (
                  <span className="chip" key={t.keyword}>
                    {t.keyword}
                    {t.rise_pct !== 0 &&
                      <em className={t.rise_pct > 0 ? 'up' : 'down'}>
                        {t.rise_pct > 0 ? '▲' : '▼'}{Math.abs(t.rise_pct)}%
                      </em>}
                  </span>
                ))}
            </div>
            <button onClick={() => onRefresh(c.id)} disabled={busy === c.id}>
              {busy === c.id ? '갱신 중…' : '🔄 트렌드 갱신'}
            </button>
          </div>
        ))}
      </div>
      <div className="add-row">
        <input value={name} placeholder="새 카테고리 이름"
               onChange={e => setName(e.target.value)} />
        <button onClick={async () => {
          if (!name.trim()) return
          await addCategory(name.trim()); setName(''); load()
        }}>+ 추가</button>
      </div>
    </div>
  )
}
```

`web/src/App.tsx` 전체 교체:
```tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import PostList from './pages/PostList'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/category/:id" element={<PostList />} />
      </Routes>
    </BrowserRouter>
  )
}
```

`web/src/index.css` 전체 교체:
```css
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #0f1115; color: #e6e6ea;
       font-family: 'Segoe UI', 'Malgun Gothic', sans-serif; }
.page { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
h1 { font-size: 22px; margin: 8px 0 20px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
         gap: 14px; }
.card { background: #171a21; border: 1px solid #262b36; border-radius: 12px;
        padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.card-title { font-size: 17px; font-weight: 700; color: #e6e6ea;
              text-decoration: none; }
.card-title:hover { color: #a78bfa; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { background: #20242e; border-radius: 20px; padding: 3px 10px;
        font-size: 12px; }
.chip em { font-style: normal; margin-left: 4px; font-size: 11px; }
.chip .up { color: #f87171; } .chip .down { color: #60a5fa; }
button { background: #7c3aed; color: #fff; border: 0; border-radius: 8px;
         padding: 8px 14px; cursor: pointer; font-size: 13px; }
button:disabled { opacity: .5; cursor: default; }
button.ghost { background: #262b36; }
input { background: #171a21; color: #e6e6ea; border: 1px solid #262b36;
        border-radius: 8px; padding: 8px 12px; font-size: 14px; }
.add-row { display: flex; gap: 8px; margin-top: 18px; }
.tabs { display: flex; gap: 8px; margin: 14px 0; }
.tabs button.active { outline: 2px solid #a78bfa; }
.post { background: #171a21; border: 1px solid #262b36; border-radius: 10px;
        padding: 12px 14px; margin-bottom: 10px; display: flex; gap: 12px;
        align-items: flex-start; }
.badge { min-width: 44px; text-align: center; border-radius: 8px;
         padding: 6px 4px; font-weight: 800; font-size: 15px; }
.badge.s4 { background: #7c3aed; } .badge.s3 { background: #8b5cf6cc; }
.badge.s2 { background: #4b5563; } .badge.s1 { background: #6b4f3f; }
.badge.s0 { background: #3f2f26; }
.badge small { display: block; font-size: 10px; font-weight: 400; }
.src { font-size: 11px; border-radius: 4px; padding: 1px 6px; margin-right: 6px; }
.src.naver { background: #03c75a33; color: #6ee7a0; }
.src.google { background: #4285f433; color: #93b7f5; }
.post h3 { margin: 0 0 4px; font-size: 15px; }
.post h3 a { color: #e6e6ea; text-decoration: none; }
.post h3 a:hover { color: #a78bfa; }
.post p { margin: 2px 0; font-size: 13px; color: #9aa0ae; }
.hooks { font-size: 12px; color: #c4b5fd; margin-top: 4px; }
```

(`web/src/main.tsx`는 Vite 기본 그대로 — `index.css` import 유지, `App` 렌더)

- [ ] **Step 3: 수동 확인**

Run: 터미널1 `server\.venv\Scripts\python -m uvicorn main:app --app-dir server --port 8792`, 터미널2 `cd web; npm run dev`
Expected: http://localhost:5175 에 카테고리 카드 6개. (트렌드 갱신은 네이버 API 키 설정 후 동작 — 키 없으면 실패 alert가 뜨는 것까지가 정상)

주의: 이 시점에 `web/src/pages/PostList.tsx`가 없으면 빌드가 깨진다. Step 2에서 임시 파일을 함께 생성한다:
```tsx
export default function PostList() { return <div className="page">준비 중</div> }
```

- [ ] **Step 4: Commit**

```bash
git add web/
git commit -m "feat(blog-reels): 웹 스캐폴드 + 카테고리 대시보드 (트렌드 TOP5 칩)"
```

---

### Task 10: 블로그 리스트 페이지 (탭·소스 필터·보랏빛 배지) + README

**Files:**
- Modify: `web/src/pages/PostList.tsx` (전체 교체)
- Create: `web/src/components/PurpleBadge.tsx`
- Create: `README.md`

**Interfaces:**
- Consumes: `api.ts`의 `discover/getPosts/getCategories/addKeyword`, Task 8 REST
- Produces: `/category/:id` 화면 — 키워드 칩(트렌드+시드) 클릭→수집, 소스 필터 탭(전체/네이버/구글), 글 카드(보랏빛 배지+소스 배지+제목 링크+요약+훅 미리보기)

- [ ] **Step 1: 구현**

`web/src/components/PurpleBadge.tsx`:
```tsx
export default function PurpleBadge({ score, verdict }:
  { score: number | null; verdict: string | null }) {
  if (score === null) return <div className="badge s0">–<small>미진단</small></div>
  return (
    <div className={`badge s${score}`} title={verdict ?? ''}>
      {score}<small>{verdict}</small>
    </div>
  )
}
```

`web/src/pages/PostList.tsx` 전체 교체:
```tsx
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Category, Post, discover, getCategories, getPosts } from '../api'
import PurpleBadge from '../components/PurpleBadge'

const SOURCES = [
  { id: 'all', label: '전체' },
  { id: 'naver', label: 'N 네이버' },
  { id: 'google', label: 'G 구글' },
] as const

export default function PostList() {
  const { id } = useParams()
  const cid = Number(id)
  const [cat, setCat] = useState<Category | null>(null)
  const [posts, setPosts] = useState<Post[]>([])
  const [source, setSource] = useState<string>('all')
  const [busyKw, setBusyKw] = useState<string | null>(null)

  const load = (src = source) => getPosts(cid, src).then(setPosts)
  useEffect(() => {
    getCategories().then(cs => setCat(cs.find(c => c.id === cid) ?? null))
    load()
  }, [cid])

  const keywords = useMemo(() => {
    if (!cat) return []
    const trend = cat.top_keywords.map(t => t.keyword)
    return [...new Set([...trend, ...cat.keywords])]
  }, [cat])

  const onDiscover = async (kw: string) => {
    setBusyKw(kw)
    try { await discover(cid, kw); await load() }
    catch (e) { alert(`수집 실패: ${e}`) }
    finally { setBusyKw(null) }
  }

  return (
    <div className="page">
      <h1><Link to="/">←</Link> {cat?.emoji} {cat?.name} 블로그 리스트</h1>
      <div className="chips">
        {keywords.map(kw => (
          <button key={kw} className="ghost" disabled={busyKw !== null}
                  onClick={() => onDiscover(kw)}>
            {busyKw === kw ? '수집 중…' : `🔍 ${kw}`}
          </button>
        ))}
      </div>
      <div className="tabs">
        {SOURCES.map(s => (
          <button key={s.id} className={source === s.id ? 'active ghost' : 'ghost'}
                  onClick={() => { setSource(s.id); load(s.id) }}>
            {s.label}
          </button>
        ))}
      </div>
      {posts.length === 0 && <p>키워드를 눌러 상위 글을 수집하세요.</p>}
      {posts.map(p => (
        <div className="post" key={p.id}>
          <PurpleBadge score={p.score} verdict={p.verdict} />
          <div>
            <h3>
              <span className={`src ${p.source}`}>
                {p.source === 'naver' ? 'N' : 'G'}
              </span>
              <a href={p.url} target="_blank" rel="noreferrer">{p.title}</a>
            </h3>
            <p>{p.summary}</p>
            {p.hooks.length > 0 && <div className="hooks">🪝 {p.hooks[0]}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}
```

`README.md`:
```markdown
# 블로그 리뉴얼 릴스 제작기

네이버·구글 상위 블로그 글 → 보랏빛소 진단 → SD 이미지 → 릴스/롱폼 자동 제작.
설계: docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md

## 실행 (M1)

1. `.env` 작성 (`.env.example` 참고 — 네이버 개발자센터 검색/데이터랩 API 키 필수,
   구글 CSE 키는 선택. CSE 키가 없으면 구글 수집은 설치된 Chrome을 통한
   Playwright 폴백으로 동작)
2. 서버: `server\.venv\Scripts\python -m uvicorn main:app --app-dir server --port 8792`
3. 웹: `cd web && npm run dev` → http://localhost:5175
4. 테스트: `server\.venv\Scripts\python -m pytest server/tests -v`
```

- [ ] **Step 2: 전체 테스트 + 수동 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests -v` 후 서버·웹 기동
Expected: 테스트 전부 PASS. 카테고리 → 키워드 칩 클릭 → 수집 → 보랏빛 배지 달린 글 리스트 표시, 소스 탭 필터 동작 (API 키 있으면 실데이터, 없으면 수집 실패 alert)

- [ ] **Step 3: Commit**

```bash
git add web/ README.md
git commit -m "feat(blog-reels): 블로그 리스트 — 카테고리 탭·소스 필터·보랏빛 배지"
```

---

## M1 완료 기준 (spec §12 마일스톤 1)

- [ ] 카테고리별 대시보드에서 트렌드 TOP5 확인 가능
- [ ] 키워드로 네이버(+구글) 상위 글 수집, 카테고리별 리스트로 표시
- [ ] 글마다 보랏빛 점수 배지(0~4)·소스 배지(N/G)·원문 링크
- [ ] 소스 필터(전체/네이버/구글) 동작
- [ ] `pytest server/tests` 전부 통과 (외부 API 없이)

M2(대본 엔진)는 M1 완료 후 별도 계획서로 작성한다.
