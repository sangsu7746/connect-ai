import sqlite3
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
        try:
            cur = conn.execute("INSERT INTO categories(name, emoji) VALUES(?,?)",
                               (body.name, body.emoji))
            conn.commit()
            return {"id": cur.lastrowid}
        except sqlite3.IntegrityError:
            raise HTTPException(409, "이미 있는 카테고리")
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
