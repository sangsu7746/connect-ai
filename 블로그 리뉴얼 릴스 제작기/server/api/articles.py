import datetime, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.db import get_conn
from core import analysis, article_gen, gemini, publisher_bridge
from core.gemini import GeminiError

router = APIRouter(prefix="/api", tags=["articles"])


class ArticleIn(BaseModel):
    category_id: int
    post_ids: list[int]


class ArticleEdit(BaseModel):
    title: str | None = None
    body_md: str | None = None


class PublishIn(BaseModel):
    platform: str
    force: bool = False


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
        try:
            out = article_gen.generate_article(posts)
        except GeminiError as e:
            raise HTTPException(502, f"글 생성 실패: {e}")
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
