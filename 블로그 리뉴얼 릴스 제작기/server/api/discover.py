import datetime, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.db import get_conn
from core import naver, google_search, crawler, image_facts, purple_cow_blog

router = APIRouter(prefix="/api/categories", tags=["discover"])

class DiscoverIn(BaseModel):
    keyword: str

@router.post("/{cid}/discover")
def discover(cid: int, body: DiscoverIn):
    conn = get_conn()
    try:
        if not conn.execute("SELECT 1 FROM categories WHERE id=?", (cid,)).fetchone():
            raise HTTPException(404, "category not found")
        items: list = []
        errors: list[str] = []
        try:
            items += naver.search_blog(body.keyword, display=10)
        except Exception as e:
            errors.append(f"naver: {type(e).__name__}")
        gitems: list = []
        try:
            gitems = google_search.search_blog(body.keyword, num=10)
            if not gitems and not google_search.available():
                gitems = google_search.search_blog_playwright(body.keyword)
        except Exception as e:
            errors.append(f"google: {type(e).__name__}")
        items += gitems
        if not items:
            detail = "검색 결과 없음 — API 키 설정을 확인하세요"
            if errors:
                detail += " (" + "; ".join(errors) + ")"
            raise HTTPException(502, detail)
        now = datetime.datetime.now().isoformat(timespec="seconds")

        ids = []
        for it in items:
            conn.execute("""INSERT INTO posts(category_id,keyword,source,title,url,
                            summary,blogger,posted_at,fetched_at)
                            VALUES(?,?,?,?,?,?,?,?,?)
                            ON CONFLICT(url) DO UPDATE SET
                            category_id=excluded.category_id,
                            keyword=excluded.keyword, fetched_at=excluded.fetched_at""",
                         (cid, body.keyword, it["source"], it["title"], it["url"],
                          it["summary"], it["blogger"], it["posted_at"], now))
            ids.append(conn.execute("SELECT id FROM posts WHERE url=?",
                                    (it["url"],)).fetchone()["id"])
        conn.commit()

        # 본문 크롤 (없는 것만) — 네트워크 I/O 동안 트랜잭션을 열지 않는다
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM posts WHERE id IN ({','.join('?'*len(ids))})", ids)]
        crawled: list[tuple[str, str, int]] = []
        for row in rows:
            if not row["content"]:
                content = crawler.fetch_content(row["url"])
                crawled.append((content, now, row["id"]))
                row["content"] = content
        for content, ts, pid in crawled:
            conn.execute("UPDATE posts SET content=?, crawled_at=? WHERE id=?",
                         (content, ts, pid))
        conn.commit()

        # 본문 이미지 수집 + 이미지 속 사실 판독 (spec §12-B).
        # 이미지 실패는 조용히 건너뛴다 — 수집 전체가 멈추면 안 된다.
        # 판독 결과는 글에 캐시해 재수집 시 비전 호출을 반복하지 않는다.
        for row in rows:
            if json.loads(row.get("image_urls_json") or "[]"):
                row["image_urls"] = json.loads(row["image_urls_json"])
                row["image_facts"] = json.loads(row.get("image_facts_json") or "[]")
                continue
            try:
                urls = crawler.fetch_images(row["url"])
            except Exception:
                urls = []
            row["image_urls"] = urls
            row["image_facts"] = image_facts.extract_facts(row) if urls else []
            conn.execute(
                "UPDATE posts SET image_urls_json=?, image_facts_json=? WHERE id=?",
                (json.dumps(urls, ensure_ascii=False),
                 json.dumps(row["image_facts"], ensure_ascii=False), row["id"]))
        conn.commit()

        # 진단 (순수 계산 — 트랜잭션 짧음)
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
                      p.posted_at, p.keyword, p.image_urls_json, p.image_facts_json,
                      d.score, d.verdict, d.hooks_json
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
            row["image_urls"] = json.loads(row.pop("image_urls_json") or "[]")
            row["image_facts"] = json.loads(row.pop("image_facts_json") or "[]")
            out.append(row)
        return out
    finally:
        conn.close()
