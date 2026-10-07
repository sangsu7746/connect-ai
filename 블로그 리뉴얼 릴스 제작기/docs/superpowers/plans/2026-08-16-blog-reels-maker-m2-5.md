# 블로그 리뉴얼 릴스 제작기 — M2.5 (블로그 글 생성·발행) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 선택한 블로그 글들로부터 게이트를 통과한 블로그 원고를 생성·편집하고, 쿠팡 프로젝트의 검증된 발행 코드를 외부 프로세스로 호출해 네이버·티스토리에 자동 발행한다.

**Architecture:** M2의 분석·진단·게이트 위에 글 계층을 얹는다: article_gen(지침+문단 게이트) → articles 테이블/API → publisher_bridge(handoff JSON→subprocess→result JSON) → 쿠팡 프로젝트의 publish_generic.py(기존 세션·에디터 자산 재사용, 쿠팡 특화 미호출) → /article/:id UI.

**Tech Stack:** M2와 동일. 외부: `D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807`의 naver_poster.py(Selenium)·tistory_poster.py(Playwright).

**Spec:** `docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md` §12-A

## Global Constraints

- .env 키 추가(정확히): `PUBLISHER_DIR` — 쿠팡 블로그 프로젝트 경로. settings 속성 `publisher_dir`
- articles.status 값: `draft` | `published` 두 가지뿐
- 글 게이트는 대본과 동일 원칙을 **문단 단위**로: guardrails.check + check_copy, 위반 문단 재생성 예산 **요청당 10회**, 최종 실패 문단은 **삭제 + warnings 기록** (spec §12-A)
- 제목 ≤ **32자**, 본문 목표 1,200~1,800자, 구조: `■ 핵심 요약` 3줄 → h2 3~4개 → 단점/주의 → 마무리
- 발행 직전 재게이트 — 경고 있으면 **409**, `force: true`로만 통과 (spec §12-A)
- Gemini 부재 시 글 생성 503 (M2 대본과 동일 정책)
- 티스토리 발행은 **기본 비공개**(공개 전환은 사람) — 원본 설계 철학 유지
- 이 앱은 크리덴셜을 다루지 않는다 — 로그인은 쿠팡 프로젝트의 세션·쿠키 그대로
- Gemini·subprocess 호출 전부 mock 테스트(오프라인 CI). publish_generic은 수동 스모크
- web은 `verbatimModuleSyntax: true` — 타입은 `import { type X }`
- 커밋은 태스크마다, 변경 파일만 `git add`(루트 D:\ 전체 — `git add -A` 금지), 메시지 끝 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 테스트: `server/.venv/Scripts/python.exe -m pytest server/tests -v` (PYTHONUTF8=1 필요 시)

---

### Task 1: 글 생성 엔진 (article_gen)

**Files:**
- Create: `server/core/article_gen.py`
- Test: `server/tests/test_article_gen.py`

**Interfaces:**
- Consumes: `analysis.build_fact_sheet/corpus_text`, `purple_cow_blog.diagnose/_pick_principles/PRINCIPLES`, `banned_words.prompt_ban_list`, `guardrails.check/check_copy`, `gemini.generate/parse_json/available/GeminiError`
- Produces: `generate_article(posts: list[dict]) -> dict{title: str, body_md: str, warnings: [str]}` · `gate_article(title: str, body_md: str, corpus: str, sources: list[str]) -> list[str]`(문단별 위반 메시지 — Task 2 PATCH·Task 3 발행 재게이트가 재사용) · `build_article_guide(diag: dict) -> str` · `ARTICLE_REGEN_BUDGET = 10`

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_article_gen.py`:
```python
import json
from core import article_gen

POSTS = [
    {"title": "전세 보증보험 총정리", "url": "https://a/1", "source": "naver",
     "summary": "",
     "content": "보증료는 연 0.128%다.\n3억이면 연 38만원이다.\n"
                "하지만 사실 집주인 동의는 필요 없다.\n1. 서류\n2. 신청\n3. 납부"},
]

GOOD_MD = ("■ 핵심 요약\n- 전세 보증보험 보증료는 연 0.128%다.\n"
           "- 3억 전세면 연 38만원 수준이다.\n- 집주인 동의 없이 가입된다.\n\n"
           "## 보증료 계산\n전세 보증보험 보증료는 연 0.128%로 확인됐다.\n\n"
           "## 가입 절차\n전세 보증보험 가입은 서류 준비부터 시작한다.\n\n"
           "## 주의할 점\n전세 보증보험이 맞지 않는 경우도 있다.\n\n"
           "## 마무리\n전세 보증보험 조건은 원문에서 확인하자.")

def _gen_ok(prompt, **kw):
    return json.dumps({"title": "전세 보증보험 핵심 정리",
                       "body_md": GOOD_MD}, ensure_ascii=False)

def test_generate_article_ok(monkeypatch):
    monkeypatch.setattr(article_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(article_gen.gemini, "generate", _gen_ok)
    out = article_gen.generate_article(POSTS)
    assert out["title"] == "전세 보증보험 핵심 정리" and len(out["title"]) <= 32
    assert out["body_md"].startswith("■ 핵심 요약")
    assert out["warnings"] == []

def test_fabricated_paragraph_dropped(monkeypatch):
    bad_md = GOOD_MD + "\n\n## 추가\n가입자의 92%가 만족했다."
    monkeypatch.setattr(article_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(article_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(
                            {"title": "전세 보증보험 핵심 정리", "body_md": bad_md},
                            ensure_ascii=False))
    out = article_gen.generate_article(POSTS)
    assert "92" not in out["body_md"]          # 재생성도 같은 응답 → 문단 삭제
    assert out["warnings"]                     # 삭제 사실이 경고로 남음

def test_copied_paragraph_dropped(monkeypatch):
    bad_md = GOOD_MD + "\n\n## 복사\n하지만 사실 집주인 동의는 필요 없다."
    monkeypatch.setattr(article_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(article_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(
                            {"title": "전세 보증보험 핵심 정리", "body_md": bad_md},
                            ensure_ascii=False))
    out = article_gen.generate_article(POSTS)
    assert "하지만 사실 집주인 동의는 필요 없다" not in out["body_md"]

def test_title_truncated_and_gated(monkeypatch):
    monkeypatch.setattr(article_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(article_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(
                            {"title": "역대급 최저가 " + "가" * 40, "body_md": GOOD_MD},
                            ensure_ascii=False))
    out = article_gen.generate_article(POSTS)
    assert len(out["title"]) <= 32
    assert "역대급" not in out["title"]        # 금지어 제목 → 안전 제목으로 교체
    assert out["warnings"]

def test_gate_article_reusable():
    probs = article_gen.gate_article("제목", "가입자의 92%가 만족했다.",
                                     "본문 숫자 없음", ["본문 숫자 없음"])
    assert probs and any("92" in p for p in probs)

def test_unavailable_raises(monkeypatch):
    import pytest
    from core.gemini import GeminiError
    monkeypatch.setattr(article_gen.gemini, "available", lambda: False)
    with pytest.raises(GeminiError):
        article_gen.generate_article(POSTS)
```

- [ ] **Step 2: 실패 확인** — Run: `server\.venv\Scripts\python -m pytest server/tests/test_article_gen.py -v`, Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/article_gen.py`:
```python
"""블로그 글 생성 엔진 (spec §12-A). 대본 엔진과 같은 분석·진단·게이트 위에서
글(제목+마크다운)을 만든다. 게이트는 문단 단위 — 위반 문단만 재생성(예산 10회),
최종 실패 문단은 삭제하고 경고로 남긴다(글은 씬과 달리 삭제가 자연스럽다)."""
import json

from . import analysis, gemini, guardrails, purple_cow_blog
from .banned_words import prompt_ban_list
from .gemini import GeminiError

ARTICLE_REGEN_BUDGET = 10
TITLE_MAX = 32
SAFE_TITLE = "핵심 정리"


def build_article_guide(diag: dict) -> str:
    principles = "\n".join(
        f"  원칙 {p['n']}. {p['name']} — {p['apply']}"
        for p in purple_cow_blog._pick_principles(diag)[:3])
    weak = "\n".join(f"  - {w}" for w in diag["weak"]) or "  - 없음"
    hooks = " / ".join(diag["hooks"][:3]) or "(훅 후보 없음)"
    return f"""[보랏빛소 진단] 점수 {diag['score']}/4 — {diag['verdict']}
보완할 약점:
{weak}
훅 후보(수집 데이터 원문): {hooks}
적용 원칙:
{principles}
[글 규칙]
- 제목 {TITLE_MAX}자 이내, 낚시 금지, 구체 숫자가 있으면 제목에 쓴다.
- 구조: "■ 핵심 요약" 단정문 3줄 → ## 소제목 3~4개 → ## 단점/주의 → ## 마무리.
- 본문 1,200~1,800자. 각 ## 문단은 앞뒤 없이 단독으로 읽혀야 한다(GEO):
  문단마다 주제어를 다시 쓰고("이 방법"·"그것" 금지), 숫자마다 확인 시점을 붙인다.
- 장점보다 단점·안 맞는 사람을 먼저 쓴다.
- 수집 글에 있는 숫자만 사용. 원문 문장을 그대로 베끼지 말고 재구성.
{prompt_ban_list()}"""


def _paragraphs(body_md: str) -> list[str]:
    """빈 줄 기준 문단 분리. ## 헤딩은 다음 문단에 붙인다."""
    blocks, cur = [], []
    for line in (body_md or "").splitlines():
        if not line.strip():
            if cur:
                blocks.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur))
    return blocks


def gate_article(title: str, body_md: str, corpus: str,
                 sources: list[str]) -> list[str]:
    """문단별 게이트 위반 목록. 제목도 하나의 문단으로 검사한다."""
    problems = []
    for label, text in [("제목", title)] + [
            (f"문단 {i+1}", p) for i, p in enumerate(_paragraphs(body_md))]:
        r = guardrails.check(text, corpus)
        problems += [f"{label}: {b}" for b in r["blocking"]]
        problems += [f"{label}: 원문 복사 — {s}"
                     for s in guardrails.check_copy(text, sources)]
    return problems


def _regen_paragraph(par: str, guide: str, facts_text: str) -> str:
    prompt = f"""{guide}
[팩트 시트] — 아래 문장의 숫자만 사용할 수 있다.
{facts_text}
[이번 출력 범위] 아래 문단 하나만 규칙에 맞게 다시 써라. 마크다운 헤딩은 유지.
JSON 오브젝트 하나만 출력: {{"paragraph": "..."}}
[문제 문단]
{par}"""
    gen = gemini.parse_json(gemini.generate(prompt, max_tokens=1024))
    if isinstance(gen, list):
        gen = gen[0] if gen else {}
    return (gen.get("paragraph") or "") if isinstance(gen, dict) else ""


def generate_article(posts: list[dict]) -> dict:
    if not gemini.available():
        raise GeminiError("GEMINI_API_KEY 미설정")
    diag = purple_cow_blog.diagnose(
        {"title": posts[0].get("title", ""), "source": posts[0].get("source", ""),
         "summary": " ".join(p.get("summary", "") for p in posts),
         "content": analysis.corpus_text(posts)},
        [{"title": p.get("title", ""), "source": p.get("source", "")}
         for p in posts])
    guide = build_article_guide(diag)
    facts = analysis.build_fact_sheet(posts)
    facts_text = "\n".join(f"- {f['fact']}" for f in facts)
    corpus = analysis.corpus_text(posts)
    sources = [p.get("content") or "" for p in posts]

    raw = gemini.generate(f"""{guide}
[팩트 시트] — 아래 문장의 숫자만 사용할 수 있다. 여기 없는 숫자는 절대 쓰지 마라.
{facts_text}
[출력] JSON 오브젝트 하나만: {{"title": "제목({TITLE_MAX}자 이내)", "body_md": "마크다운 본문"}}""",
                          max_tokens=8192)
    gen = gemini.parse_json(raw)
    if not isinstance(gen, dict):
        raise GeminiError("글 생성 응답이 JSON 오브젝트가 아니다")

    warnings: list[str] = []
    title = (gen.get("title") or "").strip()[:TITLE_MAX]
    if not title or guardrails.check(title, corpus)["blocking"] \
            or guardrails.check_copy(title, sources):
        if title:
            warnings.append(f"제목이 게이트에 걸려 교체됨: {title}")
        hook = (diag["hooks"][0][:TITLE_MAX] if diag["hooks"] else "")
        title = hook if hook and not guardrails.check(hook, corpus)["blocking"] \
            else SAFE_TITLE

    paragraphs = _paragraphs(gen.get("body_md") or "")
    budget = ARTICLE_REGEN_BUDGET
    kept: list[str] = []
    for par in paragraphs:
        problems = gate_article("", par, corpus, sources)
        while problems and budget > 0:
            budget -= 1
            try:
                cand = _regen_paragraph(par, guide, facts_text)
            except Exception:
                cand = ""
            if cand and not gate_article("", cand, corpus, sources):
                par, problems = cand, []
                break
            problems = gate_article("", par, corpus, sources)
        if problems:
            warnings.append(f"게이트 실패로 문단 삭제: {par[:40]}…"
                            if len(par) > 40 else f"게이트 실패로 문단 삭제: {par}")
            continue
        kept.append(par)

    return {"title": title, "body_md": "\n\n".join(kept), "warnings": warnings}
```

- [ ] **Step 4: 테스트 통과 확인** — 6 PASS + 전체 스위트 1회
- [ ] **Step 5: Commit**

```bash
git add server/core/article_gen.py server/tests/test_article_gen.py
git commit -m "feat(blog-reels): 블로그 글 엔진 — 지침·문단 게이트·재생성 예산·삭제 경고"
```

---

### Task 2: articles 테이블 + API

**Files:**
- Modify: `server/core/db.py` (articles 테이블)
- Create: `server/api/articles.py`
- Modify: `server/main.py` (라우터 등록)
- Test: `server/tests/test_articles_api.py`

**Interfaces:**
- Consumes: `article_gen.generate_article/gate_article`, `analysis.corpus_text`, `core.db.get_conn`
- Produces: DB `articles(id, category_id, post_ids_json, title, body_md, warnings_json, status CHECK('draft','published'), published_urls_json, created_at)`. REST: `POST /api/articles {category_id, post_ids}` → `{id}`(카테고리 404·Gemini 부재 503 — scripts와 동일 패턴) · `GET /api/articles/{aid}` → 전체+`post_ids` · `GET /api/categories/{cid}/articles` → 목록 · `PATCH /api/articles/{aid} {title?, body_md?}` → 저장 후 재게이트 `{...article, warnings:[...]}`. Task 3이 발행 엔드포인트를 이 라우터에 추가

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_articles_api.py`:
```python
import json
from fastapi.testclient import TestClient

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def _seed_posts(c, monkeypatch):
    import api.discover as disc
    items = [{"source": "naver", "title": "전세 보증보험 총정리",
              "url": "https://blog.naver.com/a/1", "summary": "보증료 0.128%",
              "blogger": "b", "posted_at": "20260810"}]
    monkeypatch.setattr(disc.naver, "search_blog", lambda q, display=10: items)
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: [])
    monkeypatch.setattr(disc.google_search, "available", lambda: True)
    monkeypatch.setattr(disc.crawler, "fetch_content",
                        lambda url: "보증료는 연 0.128%다.\n3억이면 연 38만원이다.")
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    return [p["id"] for p in c.get("/api/categories/1/posts").json()]

def _mock_engine(monkeypatch):
    import api.articles as art
    monkeypatch.setattr(art.gemini, "available", lambda: True)
    monkeypatch.setattr(art.article_gen, "generate_article",
                        lambda posts: {"title": "전세 보증보험 핵심 정리",
                                       "body_md": "■ 핵심 요약\n- 보증료는 연 0.128%다.",
                                       "warnings": []})
    return art

def test_create_get_list(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    aid = c.post("/api/articles",
                 json={"category_id": 1, "post_ids": ids}).json()["id"]
    got = c.get(f"/api/articles/{aid}").json()
    assert got["title"].startswith("전세") and got["status"] == "draft"
    assert [a["id"] for a in c.get("/api/categories/1/articles").json()] == [aid]

def test_patch_regates(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    aid = c.post("/api/articles",
                 json={"category_id": 1, "post_ids": ids}).json()["id"]
    r = c.patch(f"/api/articles/{aid}",
                json={"body_md": "가입자의 92%가 만족했다."}).json()
    assert r["warnings"]                       # 날조 숫자 경고 동봉(저장은 됨)
    assert c.get(f"/api/articles/{aid}").json()["body_md"].startswith("가입자")

def test_create_503_without_gemini(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    import api.articles as art
    monkeypatch.setattr(art.gemini, "available", lambda: False)
    assert c.post("/api/articles",
                  json={"category_id": 1, "post_ids": ids}).status_code == 503

def test_create_404_bad_category(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    _mock_engine(monkeypatch)
    assert c.post("/api/articles",
                  json={"category_id": 9999, "post_ids": [1]}).status_code == 404
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/db.py` SCHEMA 끝에 추가:
```sql
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
```

`server/api/articles.py`:
```python
import datetime, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.db import get_conn
from core import analysis, article_gen, gemini

router = APIRouter(prefix="/api", tags=["articles"])


class ArticleIn(BaseModel):
    category_id: int
    post_ids: list[int]


class ArticleEdit(BaseModel):
    title: str | None = None
    body_md: str | None = None


def _load_posts(conn, post_ids: list[int]) -> list[dict]:
    if not post_ids:
        raise HTTPException(404, "선택된 글이 없다")
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM posts WHERE id IN ({','.join('?' * len(post_ids))})",
        post_ids)]
    if len(rows) != len(set(post_ids)):
        raise HTTPException(404, "존재하지 않는 글이 포함돼 있다")
    return rows


def _row(row) -> dict:
    d = dict(row)
    d["warnings"] = json.loads(d.pop("warnings_json") or "[]")
    d["published_urls"] = json.loads(d.pop("published_urls_json") or "{}")
    d["post_ids"] = json.loads(d.pop("post_ids_json"))
    return d


@router.post("/articles")
def create_article(body: ArticleIn):
    if not gemini.available():
        raise HTTPException(503, "GEMINI_API_KEY 미설정 — 글 생성은 키가 필요합니다")
    conn = get_conn()
    try:
        if not conn.execute("SELECT 1 FROM categories WHERE id=?",
                            (body.category_id,)).fetchone():
            raise HTTPException(404, "category not found")
        posts = _load_posts(conn, body.post_ids)
        out = article_gen.generate_article(posts)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cur = conn.execute(
            """INSERT INTO articles(category_id, post_ids_json, title, body_md,
               warnings_json, created_at) VALUES(?,?,?,?,?,?)""",
            (body.category_id, json.dumps(body.post_ids), out["title"],
             out["body_md"], json.dumps(out["warnings"], ensure_ascii=False), now))
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@router.get("/articles/{aid}")
def get_article(aid: int):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "article not found")
        return _row(row)
    finally:
        conn.close()


@router.get("/categories/{cid}/articles")
def list_articles(cid: int):
    conn = get_conn()
    try:
        return [{"id": r["id"], "title": r["title"], "status": r["status"],
                 "created_at": r["created_at"]}
                for r in conn.execute(
                    "SELECT * FROM articles WHERE category_id=? ORDER BY id DESC",
                    (cid,))]
    finally:
        conn.close()


@router.patch("/articles/{aid}")
def edit_article(aid: int, body: ArticleEdit):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "article not found")
        title = body.title if body.title is not None else row["title"]
        title = title[:article_gen.TITLE_MAX]
        body_md = body.body_md if body.body_md is not None else row["body_md"]
        posts = _load_posts(conn, json.loads(row["post_ids_json"]))
        corpus = analysis.corpus_text(posts)
        sources = [p.get("content") or "" for p in posts]
        warnings = article_gen.gate_article(title, body_md, corpus, sources)
        conn.execute(
            "UPDATE articles SET title=?, body_md=?, warnings_json=? WHERE id=?",
            (title, body_md, json.dumps(warnings, ensure_ascii=False), aid))
        conn.commit()
        row = conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        return _row(row)
    finally:
        conn.close()
```

`server/main.py`에 추가:
```python
from api.articles import router as articles_router
app.include_router(articles_router)
```

- [ ] **Step 4: 테스트 통과 확인** — 4 PASS + 전체 1회
- [ ] **Step 5: Commit**

```bash
git add server/core/db.py server/api/articles.py server/main.py server/tests/test_articles_api.py
git commit -m "feat(blog-reels): articles 테이블·API — 생성·조회·편집(재게이트 경고)"
```

---

### Task 3: 발행 브릿지 + publish API

**Files:**
- Modify: `server/core/config.py` (publisher_dir 1줄)
- Modify: `.env.example` (PUBLISHER_DIR= 1줄)
- Create: `server/core/publisher_bridge.py`
- Modify: `server/api/articles.py` (publish 엔드포인트 추가)
- Test: `server/tests/test_publisher_bridge.py`

**Interfaces:**
- Consumes: `settings.publisher_dir`, `article_gen.gate_article`
- Produces: `publisher_bridge.available() -> bool`(PUBLISHER_DIR 설정+publish_generic.py 존재) · `publisher_bridge.publish(platform: str, title: str, body_md: str, category: str = "") -> dict{ok, url, error}`(handoff JSON 임시파일 → `[sys.executable, publish_generic.py, --file, ...]` cwd=PUBLISHER_DIR, 타임아웃 300s → result JSON stdout 마지막 줄 파싱) · REST `POST /api/articles/{aid}/publish {platform: 'naver'|'tistory', force: bool=false}` — 재게이트 경고 시 409(force 우회), 브릿지 미가용 503, 성공 시 published_urls·status 갱신

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_publisher_bridge.py`:
```python
import json
import subprocess
from fastapi.testclient import TestClient
from core import publisher_bridge as pb

def test_available_requires_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(pb.settings, "publisher_dir", "")
    assert pb.available() is False
    monkeypatch.setattr(pb.settings, "publisher_dir", str(tmp_path))
    assert pb.available() is False              # publish_generic.py 없음
    (tmp_path / "publish_generic.py").write_text("# stub", encoding="utf-8")
    assert pb.available() is True

def test_publish_parses_result(monkeypatch, tmp_path):
    (tmp_path / "publish_generic.py").write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(pb.settings, "publisher_dir", str(tmp_path))
    def fake_run(cmd, cwd=None, capture_output=None, text=None,
                 timeout=None, encoding=None):
        class R:
            returncode = 0
            stdout = 'log line\n{"ok": true, "url": "https://blog/1", "error": ""}'
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    r = pb.publish("tistory", "제목", "본문")
    assert r["ok"] and r["url"] == "https://blog/1"

def test_publish_handles_timeout(monkeypatch, tmp_path):
    (tmp_path / "publish_generic.py").write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(pb.settings, "publisher_dir", str(tmp_path))
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="x", timeout=300)
    monkeypatch.setattr(subprocess, "run", boom)
    r = pb.publish("naver", "제목", "본문")
    assert not r["ok"] and "타임아웃" in r["error"]

# ── publish API (articles 라우터) ──
def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def _setup(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    import api.discover as disc
    monkeypatch.setattr(disc.naver, "search_blog", lambda q, display=10: [
        {"source": "naver", "title": "전세 보증보험 총정리",
         "url": "https://blog.naver.com/a/1", "summary": "",
         "blogger": "b", "posted_at": "20260810"}])
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: [])
    monkeypatch.setattr(disc.google_search, "available", lambda: True)
    monkeypatch.setattr(disc.crawler, "fetch_content",
                        lambda url: "보증료는 연 0.128%다.")
    c.post("/api/categories/1/discover", json={"keyword": "전세"})
    ids = [p["id"] for p in c.get("/api/categories/1/posts").json()]
    import api.articles as art
    monkeypatch.setattr(art.gemini, "available", lambda: True)
    monkeypatch.setattr(art.article_gen, "generate_article",
                        lambda posts: {"title": "전세 보증보험 정리",
                                       "body_md": "보증료는 연 0.128% 수준이다.",
                                       "warnings": []})
    aid = c.post("/api/articles",
                 json={"category_id": 1, "post_ids": ids}).json()["id"]
    return c, art, aid

def test_publish_endpoint_success(monkeypatch, tmp_path):
    c, art, aid = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(art.publisher_bridge, "available", lambda: True)
    monkeypatch.setattr(art.publisher_bridge, "publish",
                        lambda platform, title, body_md, category="": {
                            "ok": True, "url": f"https://{platform}/1", "error": ""})
    r = c.post(f"/api/articles/{aid}/publish", json={"platform": "tistory"})
    assert r.status_code == 200
    got = c.get(f"/api/articles/{aid}").json()
    assert got["status"] == "published"
    assert got["published_urls"]["tistory"] == "https://tistory/1"

def test_publish_409_on_warnings_unless_force(monkeypatch, tmp_path):
    c, art, aid = _setup(monkeypatch, tmp_path)
    c.patch(f"/api/articles/{aid}", json={"body_md": "가입자의 92%가 만족했다."})
    monkeypatch.setattr(art.publisher_bridge, "available", lambda: True)
    monkeypatch.setattr(art.publisher_bridge, "publish",
                        lambda platform, title, body_md, category="": {
                            "ok": True, "url": "https://x/1", "error": ""})
    assert c.post(f"/api/articles/{aid}/publish",
                  json={"platform": "naver"}).status_code == 409
    assert c.post(f"/api/articles/{aid}/publish",
                  json={"platform": "naver", "force": True}).status_code == 200

def test_publish_503_without_bridge(monkeypatch, tmp_path):
    c, art, aid = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(art.publisher_bridge, "available", lambda: False)
    assert c.post(f"/api/articles/{aid}/publish",
                  json={"platform": "naver"}).status_code == 503
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/config.py` Settings에 추가:
```python
    publisher_dir = os.getenv("PUBLISHER_DIR", "")
```

`.env.example`에 추가:
```
PUBLISHER_DIR=
```

`server/core/publisher_bridge.py`:
```python
"""발행 브릿지 (spec §12-A, B안). 쿠팡 블로그 프로젝트의 publish_generic.py를
subprocess로 호출한다. 이 앱은 크리덴셜을 다루지 않는다 — 세션은 그쪽 프로젝트
소관. handoff/result는 JSON 파일·stdout 마지막 줄."""
import json
import pathlib
import subprocess
import sys
import tempfile

from .config import settings

TIMEOUT_S = 300


def _script() -> pathlib.Path | None:
    if not settings.publisher_dir:
        return None
    p = pathlib.Path(settings.publisher_dir) / "publish_generic.py"
    return p if p.exists() else None


def available() -> bool:
    return _script() is not None


def publish(platform: str, title: str, body_md: str, category: str = "") -> dict:
    script = _script()
    if not script:
        return {"ok": False, "url": "",
                "error": "PUBLISHER_DIR 미설정 또는 publish_generic.py 없음"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump({"platform": platform, "title": title,
                   "body_md": body_md, "category": category},
                  f, ensure_ascii=False)
        handoff = f.name
    try:
        r = subprocess.run([sys.executable, str(script), "--file", handoff],
                           cwd=settings.publisher_dir, capture_output=True,
                           text=True, timeout=TIMEOUT_S, encoding="utf-8")
        for line in reversed((r.stdout or "").strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    out = json.loads(line)
                    return {"ok": bool(out.get("ok")),
                            "url": out.get("url", ""),
                            "error": out.get("error", "")}
                except json.JSONDecodeError:
                    continue
        return {"ok": False, "url": "",
                "error": f"발행 결과를 파싱하지 못함 (exit {r.returncode})"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "url": "", "error": "발행 타임아웃(5분) — 브라우저 로그인 대기 중일 수 있음"}
    except Exception as e:
        return {"ok": False, "url": "", "error": f"발행 실행 실패: {type(e).__name__}"}
    finally:
        try:
            pathlib.Path(handoff).unlink(missing_ok=True)
        except OSError:
            pass
```

`server/api/articles.py`에 추가 (import에 `publisher_bridge` 추가):
```python
class PublishIn(BaseModel):
    platform: str
    force: bool = False


@router.post("/articles/{aid}/publish")
def publish_article(aid: int, body: PublishIn):
    if body.platform not in ("naver", "tistory"):
        raise HTTPException(422, "platform은 naver|tistory")
    if not publisher_bridge.available():
        raise HTTPException(503, "PUBLISHER_DIR 미설정 — 발행 불가")
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM articles WHERE id=?", (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "article not found")
        posts = _load_posts(conn, json.loads(row["post_ids_json"]))
        corpus = analysis.corpus_text(posts)
        sources = [p.get("content") or "" for p in posts]
        warnings = article_gen.gate_article(row["title"], row["body_md"],
                                            corpus, sources)
        if warnings and not body.force:
            raise HTTPException(409, "게이트 경고가 있어 발행 보류: "
                                + " / ".join(warnings[:3]))
        r = publisher_bridge.publish(body.platform, row["title"], row["body_md"])
        if not r["ok"]:
            raise HTTPException(502, f"발행 실패: {r['error']}")
        urls = json.loads(row["published_urls_json"] or "{}")
        urls[body.platform] = r["url"]
        conn.execute("""UPDATE articles SET status='published',
                        published_urls_json=? WHERE id=?""",
                     (json.dumps(urls, ensure_ascii=False), aid))
        conn.commit()
        return {"ok": True, "url": r["url"]}
    finally:
        conn.close()
```

- [ ] **Step 4: 테스트 통과 확인** — 6 PASS + 전체 1회
- [ ] **Step 5: Commit**

```bash
git add server/core/config.py server/core/publisher_bridge.py server/api/articles.py server/tests/test_publisher_bridge.py .env.example
git commit -m "feat(blog-reels): 발행 브릿지·publish API — 재게이트 409·force·타임아웃"
```

---

### Task 4: 쿠팡 프로젝트에 publish_generic.py 추가

**Files:**
- Create: `D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807\publish_generic.py`

**Interfaces:**
- Consumes(그쪽 프로젝트): `tistory_poster`의 세션·에디터 함수(`_ctx`/`_page`/`ensure_login`/`text_to_html` 또는 기존 `post <원고.md>` CLI 흐름 — **파일을 읽고 실제 발행 함수를 확인해 재사용**), `naver_poster.NaverBlogPoster`(`write_post(title, content, category)`)
- Produces: CLI `python publish_generic.py --file handoff.json` — handoff `{platform, title, body_md, category}` 읽기 → 발행 → **stdout 마지막 줄에 result JSON** `{"ok": bool, "url": str, "error": str}`. 쿠팡 특화(제휴링크 치환·대가성 고지·상품 위젯·guardrails-쿠팡 검사)는 호출하지 않는다. 티스토리는 기존 흐름의 **비공개 발행** 유지

- [ ] **Step 1: 기존 포스터 정독**

`tistory_poster.py` 전체(특히 `post <원고.md>` CLI가 부르는 함수 체인, `text_to_html`의 쿠팡 인자 무시 방법 — `affiliate_url=""`이면 제휴 없음인지 확인)와 `naver_poster.py`의 `write_post` 시그니처·로그인 흐름(`_load_cookies_and_check`)을 읽고, 재사용할 함수 체인을 fix report에 기록.

- [ ] **Step 2: 구현**

`publish_generic.py` 골격 (정독 결과에 맞춰 세부 조정 — 조정 내용은 report에 명시):
```python
"""블로그 리뉴얼 릴스 제작기용 범용 발행 CLI.
쿠팡 파이프라인(제휴·고지·위젯)을 태우지 않고 세션·에디터 자산만 재사용한다.
입력: --file handoff.json {platform, title, body_md, category}
출력: stdout 마지막 줄에 {"ok": bool, "url": str, "error": str}
"""
import argparse
import json
import sys


def _result(ok: bool, url: str = "", error: str = "") -> None:
    print(json.dumps({"ok": ok, "url": url, "error": error}, ensure_ascii=False))


def publish_tistory(title: str, body_md: str, category: str) -> str:
    """tistory_poster의 기존 원고 발행 흐름 재사용(비공개 발행). 반환: 글 URL."""
    import tistory_poster as tp
    # 정독 결과에 따라: tp의 md→발행 함수 체인 호출 (post CLI가 쓰는 함수).
    # affiliate/고지 관련 인자는 빈 값으로 — 쿠팡 특화 경로 미진입 확인 필수.
    ...


def publish_naver(title: str, body_md: str, category: str) -> str:
    """NaverBlogPoster.write_post 재사용. 반환: 글 URL."""
    from naver_poster import NaverBlogPoster
    poster = NaverBlogPoster(headless=False)
    # 정독 결과에 따라: 쿠키 로그인 확인 → write_post(title, 텍스트 변환분, category)
    ...


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    args = ap.parse_args()
    try:
        with open(args.file, encoding="utf-8") as f:
            h = json.load(f)
        fn = {"tistory": publish_tistory, "naver": publish_naver}.get(h["platform"])
        if not fn:
            _result(False, error=f"지원하지 않는 platform: {h['platform']}")
            return
        url = fn(h["title"], h["body_md"], h.get("category", ""))
        _result(True, url=url or "")
    except Exception as e:
        _result(False, error=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
```

`...` 부분은 Step 1 정독에서 확인한 실제 함수 체인으로 채운다 — 이 플레이스홀더를 남긴 채 커밋하는 것은 실패다. 발행 URL을 얻는 방법(발행 후 page.url 또는 poster 반환값)도 정독에서 확인.

- [ ] **Step 3: 문법·임포트 검증**

Run: `cd "D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807"; python -c "import ast; ast.parse(open('publish_generic.py', encoding='utf-8').read()); print('syntax ok')"`
(실발행 스모크는 로그인 세션이 필요하므로 사용자 수동 확인 항목으로 남긴다 — README에 기재)

- [ ] **Step 4: Commit**

```bash
git add "Antigravity 작업-2026 상반기/쿠팡상품 블로그-naver -260807/publish_generic.py"
git commit -m "feat(coupang-blog): publish_generic — blog-reels용 범용 발행 CLI (쿠팡 특화 미호출)"
```
(주의: 저장소 루트 D:\ 기준 상대 경로로 add — 이 태스크만 프로젝트 밖 파일)

---

### Task 5: 글 편집·발행 UI + README

**Files:**
- Modify: `web/src/api.ts` (Article 타입·헬퍼)
- Modify: `web/src/pages/PostList.tsx` (글 만들기 버튼)
- Create: `web/src/pages/Article.tsx`
- Modify: `web/src/App.tsx` (라우트)
- Modify: `web/src/index.css` (경고 패널·발행 바)
- Modify: `README.md` (M2.5 사용법)

**Interfaces:**
- Consumes: Task 2·3 REST
- Produces: `/article/:id` 페이지, PostList make-bar `📝 블로그 글 만들기`

- [ ] **Step 1: 구현**

`web/src/api.ts`에 추가:
```ts
export interface Article {
  id: number; category_id: number; title: string; body_md: string
  warnings: string[]; status: 'draft' | 'published'
  published_urls: Record<string, string>; post_ids: number[]; created_at: string
}
export const createArticle = (category_id: number, post_ids: number[]) =>
  fetch('/api/articles', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category_id, post_ids }) }).then(r => j<{ id: number }>(r))
export const getArticle = (id: number) =>
  fetch(`/api/articles/${id}`).then(r => j<Article>(r))
export const patchArticle = (id: number, body: { title?: string; body_md?: string }) =>
  fetch(`/api/articles/${id}`, { method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }).then(r => j<Article>(r))
export const publishArticle = (id: number, platform: string, force = false) =>
  fetch(`/api/articles/${id}/publish`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ platform, force }) }).then(r => j<{ ok: boolean; url: string }>(r))
```

`web/src/pages/PostList.tsx` — make-bar의 대본 버튼 옆에 추가 (import에 `createArticle` 추가):
```tsx
          <button className="ghost" disabled={making} onClick={async () => {
            setMaking(true)
            try {
              const { id } = await createArticle(cid, picked)
              nav(`/article/${id}`)
            } catch (e) { alert(`글 생성 실패: ${e}`) }
            finally { setMaking(false) }
          }}>📝 블로그 글 만들기</button>
```

`web/src/pages/Article.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Article, getArticle, patchArticle, publishArticle } from '../api'

export default function ArticlePage() {
  const { id } = useParams()
  const aid = Number(id)
  const [article, setArticle] = useState<Article | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => { getArticle(aid).then(setArticle).catch(e => alert(e)) }, [aid])
  if (!article) return <div className="page">불러오는 중…</div>

  const save = async (patch: { title?: string; body_md?: string }) => {
    try { setArticle(await patchArticle(aid, patch)) }
    catch (e) { alert(`저장 실패: ${e}`) }
  }

  const publish = async (platform: string) => {
    setBusy(platform)
    try {
      const r = await publishArticle(aid, platform)
      alert(`발행 완료: ${r.url || '(URL 미확인 — 블로그 관리에서 확인)'}`)
      setArticle(await getArticle(aid))
    } catch (e) {
      const msg = String(e)
      if (msg.includes('409') &&
          confirm(`게이트 경고가 있습니다.\n${msg}\n무시하고 발행할까요?`)) {
        try {
          const r = await publishArticle(aid, platform, true)
          alert(`발행 완료: ${r.url || ''}`)
          setArticle(await getArticle(aid))
        } catch (e2) { alert(`발행 실패: ${e2}`) }
      } else { alert(`발행 실패: ${msg}`) }
    } finally { setBusy(null) }
  }

  return (
    <div className="page">
      <h1><Link to={`/category/${article.category_id}`}>←</Link> 블로그 글
        <span className="meta">{article.status === 'published' ? '발행됨' : '초안'}</span>
      </h1>
      <input key={`t:${article.title}`} defaultValue={article.title} maxLength={32}
             placeholder="제목(≤32자)"
             onBlur={e => e.target.value !== article.title &&
               save({ title: e.target.value })} />
      <textarea key={`b:${article.body_md.length}`} className="desc"
                defaultValue={article.body_md} rows={22}
                onBlur={e => e.target.value !== article.body_md &&
                  save({ body_md: e.target.value })} />
      {article.warnings.length > 0 && (
        <div className="warn-panel">
          <b>⚠ 게이트 경고 {article.warnings.length}건</b>
          {article.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}
      <div className="make-bar">
        <button disabled={busy !== null} onClick={() => publish('naver')}>
          {busy === 'naver' ? '발행 중…' : 'N 네이버 발행'}
        </button>
        <button disabled={busy !== null} onClick={() => publish('tistory')}>
          {busy === 'tistory' ? '발행 중…' : 'T 티스토리 발행(비공개)'}
        </button>
        {Object.entries(article.published_urls).map(([p, u]) => (
          <a key={p} href={u} target="_blank" rel="noreferrer">🔗 {p}</a>
        ))}
      </div>
      <p className="meta">발행은 수 분 걸릴 수 있습니다. 세션이 만료됐으면 브라우저
        창이 열립니다 — 직접 로그인하면 이어서 발행됩니다. 티스토리는 비공개로
        올라가며 공개 전환은 블로그 관리에서 직접 합니다.</p>
    </div>
  )
}
```

`web/src/App.tsx` — import + 라우트:
```tsx
import ArticlePage from './pages/Article'
        <Route path="/article/:id" element={<ArticlePage />} />
```

`web/src/index.css`에 추가:
```css
.warn-panel { background: #3a2b12; border: 1px solid #b45309; border-radius: 10px;
              padding: 10px 14px; margin: 10px 0; font-size: 13px;
              display: flex; flex-direction: column; gap: 4px; }
.page > input { width: 100%; margin-bottom: 10px; font-size: 16px; }
.make-bar a { color: #a78bfa; font-size: 13px; }
```

`README.md`에 추가:
```markdown
### M2.5 — 블로그 글 발행

블로그 리스트에서 글 체크 → "📝 블로그 글 만들기" → /article 페이지에서 제목·본문
검토(게이트 경고 확인) → 네이버/티스토리 발행 버튼.

- `.env`에 `PUBLISHER_DIR` = 쿠팡 블로그 프로젝트 경로 필요(발행 코드 재사용).
- 첫 발행 전 수동 스모크 1회 권장: 해당 프로젝트에서
  `python publish_generic.py --file test.json` (세션 만료 시 창에서 직접 로그인).
- 티스토리는 비공개로 올라감 — 공개 전환은 블로그 관리에서 직접.
```

- [ ] **Step 2: 검증**

Run: `cd web; npm run build` 통과 + `server/.venv/Scripts/python.exe -m pytest server/tests -q` 통과.

- [ ] **Step 3: Commit**

```bash
git add web/src/ README.md
git commit -m "feat(blog-reels): 글 편집·발행 UI — 경고 패널·409 force 확인·발행 URL"
```

---

## M2.5 완료 기준 (spec §12-A)

- [ ] 글 선택 → 블로그 글 생성(제목 32자·요약 3줄·h2 구조), 게이트 위반 문단은 삭제+경고
- [ ] /article 페이지에서 편집(재게이트 경고 동봉), 경고 있으면 발행 409(force로만 우회)
- [ ] 발행 브릿지가 handoff→subprocess→result 왕복, 실패·타임아웃 시 draft 유지
- [ ] publish_generic이 쿠팡 특화 경로를 태우지 않음(정독 확인 기록), 티스토리 비공개 발행
- [ ] `pytest server/tests` 전부 통과(외부 API·subprocess 없이), `npm run build` 통과
- [ ] 실발행 스모크 1회는 사용자 수동 확인 항목(README 기재)
