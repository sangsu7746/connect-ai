import datetime
import json
import os
import pathlib
import tempfile

from fastapi import APIRouter, HTTPException

from core.db import get_conn
from core import bgm, jobs, renderer

router = APIRouter(prefix="/api", tags=["render"])


def videos_dir() -> pathlib.Path:
    p = os.environ.get("APP_VIDEOS_DIR")
    d = pathlib.Path(p) if p else \
        pathlib.Path(__file__).resolve().parents[1] / "data" / "videos"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/scripts/{sid}/render")
def start_render(sid: int):
    if jobs.has_running("images", str(sid)) or jobs.has_running("render", str(sid)):
        raise HTTPException(409, "이 스크립트의 잡이 이미 실행 중입니다 — 완료 후 다시 시도하세요")
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "script not found")
        cat = conn.execute("SELECT name FROM categories WHERE id=?",
                           (row["category_id"],)).fetchone()
        category = cat["name"] if cat else ""
        fmt, duration = row["fmt"], row["duration_sec"]
    finally:
        conn.close()

    def work(ctx: jobs.JobCtx) -> dict:
        conn = get_conn()
        try:
            row = conn.execute("SELECT * FROM scripts WHERE id=?",
                               (sid,)).fetchone()
            scenes = json.loads(row["scenes_json"])
            ctx.set_total(len(scenes) + 1)
            bgm_path = bgm.pick(category, seed=sid)
            with tempfile.TemporaryDirectory(prefix=f"render_{sid}_") as td:
                now = datetime.datetime.now().isoformat(timespec="seconds")
                cur = conn.execute(
                    """INSERT INTO renders(script_id, file, duration_sec,
                       created_at) VALUES(?,?,?,?)""",
                    (sid, "", duration, now))
                conn.commit()
                rid = cur.lastrowid
                fname = f"{sid}_{rid}.mp4"
                out = videos_dir() / fname
                try:
                    renderer.render_script(scenes, fmt, category, bgm_path,
                                           out, pathlib.Path(td),
                                           on_scene=ctx.tick)
                except Exception:
                    conn.execute("DELETE FROM renders WHERE id=?", (rid,))
                    conn.commit()
                    raise
                conn.execute("UPDATE renders SET file=? WHERE id=?",
                             (fname, rid))
                conn.commit()
                ctx.tick()
                return {"render_id": rid, "file": fname}
        finally:
            conn.close()

    return {"job_id": jobs.start("render", 0, work, ref=str(sid))}


@router.get("/scripts/{sid}/renders")
def list_renders(sid: int):
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT id, file, duration_sec, created_at FROM renders
               WHERE script_id=? AND file != '' ORDER BY id DESC""", (sid,))]
    finally:
        conn.close()
