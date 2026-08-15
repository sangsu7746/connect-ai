import datetime, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.db import get_conn
from core import geo, script_gen

router = APIRouter(prefix="/api", tags=["scripts"])


class ScriptIn(BaseModel):
    category_id: int
    post_ids: list[int]
    fmt: str
    duration: int


class SceneEdit(BaseModel):
    caption: str | None = None
    sub: str | None = None
    narration: str | None = None
    image_prompt: str | None = None


def _load_posts(conn, post_ids: list[int]) -> list[dict]:
    if not post_ids:
        raise HTTPException(404, "선택된 글이 없다")
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM posts WHERE id IN ({','.join('?' * len(post_ids))})",
        post_ids)]
    if len(rows) != len(set(post_ids)):
        raise HTTPException(404, "존재하지 않는 글이 포함돼 있다")
    return rows


def _row_to_script(row) -> dict:
    d = dict(row)
    d["scenes"] = json.loads(d.pop("scenes_json"))
    analysis_data = json.loads(d.pop("analysis_json"))
    d["fact_sheet"] = analysis_data.get("fact_sheet", [])
    d["diag"] = analysis_data.get("diag", {})
    d["chapters"] = analysis_data.get("chapters", [])
    d["post_ids"] = json.loads(d.pop("post_ids_json"))
    return d


@router.post("/scripts")
def create_script(body: ScriptIn):
    if (body.fmt, body.duration) not in (
            ("reels", 30), ("reels", 60), ("long", 60),
            ("long", 180), ("long", 300), ("long", 600)):
        raise HTTPException(422, "지원하지 않는 형식/길이")
    conn = get_conn()
    try:
        posts = _load_posts(conn, body.post_ids)
        out = script_gen.generate_script(posts, body.fmt, body.duration)
        summary_scene = next((s for s in out["scenes"] if s["role"] == "summary"), None)
        summary_lines = [x for x in (
            summary_scene and summary_scene.get("narration"),
            out["diag"].get("hooks", [None])[0] if out["diag"].get("hooks") else None,
            f"{len(posts)}개 상위 글을 종합해 재구성한 내용이다.",
        ) if x]
        desc = geo.build_description(out["scenes"], out["chapters"], posts,
                                     summary_lines)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cur = conn.execute(
            """INSERT INTO scripts(category_id, post_ids_json, fmt, duration_sec,
               analysis_json, scenes_json, description_md, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (body.category_id, json.dumps(body.post_ids),
             body.fmt, body.duration,
             json.dumps({"fact_sheet": out["fact_sheet"], "diag": out["diag"],
                         "chapters": out["chapters"]}, ensure_ascii=False),
             json.dumps(out["scenes"], ensure_ascii=False), desc, now))
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@router.get("/scripts/{sid}")
def get_script(sid: int):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "script not found")
        return _row_to_script(row)
    finally:
        conn.close()


@router.get("/categories/{cid}/scripts")
def list_scripts(cid: int):
    conn = get_conn()
    try:
        return [{"id": r["id"], "fmt": r["fmt"], "duration_sec": r["duration_sec"],
                 "created_at": r["created_at"]}
                for r in conn.execute(
                    "SELECT * FROM scripts WHERE category_id=? ORDER BY id DESC",
                    (cid,))]
    finally:
        conn.close()


def _update_scene(sid: int, idx: int, mutate, needs_posts: bool) -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "script not found")
        scenes = json.loads(row["scenes_json"])
        target = next((s for s in scenes if s["idx"] == idx), None)
        if not target:
            raise HTTPException(404, "scene not found")
        analysis_data = json.loads(row["analysis_json"])
        posts = _load_posts(conn, json.loads(row["post_ids_json"])) if needs_posts else []
        mutate(target, posts, analysis_data.get("diag", {}))
        conn.execute("UPDATE scripts SET scenes_json=? WHERE id=?",
                     (json.dumps(scenes, ensure_ascii=False), sid))
        conn.commit()
        return target
    finally:
        conn.close()


@router.post("/scripts/{sid}/scenes/{idx}/regen")
def regen_scene_ep(sid: int, idx: int):
    def mutate(target, posts, diag):
        target.update(script_gen.regen_scene(target, posts, diag))
    return _update_scene(sid, idx, mutate, needs_posts=True)


@router.patch("/scripts/{sid}/scenes/{idx}")
def edit_scene(sid: int, idx: int, body: SceneEdit):
    def mutate(target, posts, diag):
        for k, v in body.model_dump(exclude_none=True).items():
            if k == "caption":
                v = v[:18]
            elif k == "sub":
                v = v[:22]
            target[k] = v
    return _update_scene(sid, idx, mutate, needs_posts=False)
