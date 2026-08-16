import json
import secrets
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.db import get_conn
from core import image_gen, jobs, style_packs

router = APIRouter(prefix="/api", tags=["images"])


class ImagesIn(BaseModel):
    force: bool = False


def _load_script(conn, sid: int):
    row = conn.execute("SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
    if not row:
        raise HTTPException(404, "script not found")
    return row


def _category_name(conn, cid: int) -> str:
    row = conn.execute("SELECT name FROM categories WHERE id=?", (cid,)).fetchone()
    return row["name"] if row else ""


def _gen_for_scene(conn, scene: dict, category: str, fmt: str,
                   salt: str = "") -> None:
    style = style_packs.pick(scene["role"], category)
    prompt = (scene.get("image_prompt") or "") + (f" |r{salt}" if salt else "")
    r = image_gen.generate(conn, prompt, style, fmt)
    scene["image_file"] = r["file"]
    scene["image_fallback"] = r["fallback"]


@router.post("/scripts/{sid}/images")
def generate_images(sid: int, body: ImagesIn | None = None):
    force = bool(body and body.force)
    conn = get_conn()
    try:
        row = _load_script(conn, sid)
        scenes = json.loads(row["scenes_json"])
        todo = [s for s in scenes
                if force or not s.get("image_file")]
        fmt, cid = row["fmt"], row["category_id"]
    finally:
        conn.close()

    def work(ctx: jobs.JobCtx) -> dict:
        conn = get_conn()
        try:
            row = _load_script(conn, sid)
            scenes = json.loads(row["scenes_json"])
            category = _category_name(conn, cid)
            done = 0
            for scene in scenes:
                if not force and scene.get("image_file"):
                    continue
                # force는 캐시를 우회해 새 이미지를 뽑아야 하므로 리트라이 솔트 부여
                _gen_for_scene(conn, scene, category, fmt,
                               salt=secrets.token_hex(3) if force else "")
                done += 1
                ctx.tick()
                conn.execute("UPDATE scripts SET scenes_json=? WHERE id=?",
                             (json.dumps(scenes, ensure_ascii=False), sid))
                conn.commit()
            return {"generated": done}
        finally:
            conn.close()

    return {"job_id": jobs.start("images", len(todo), work)}


@router.get("/jobs/{jid}")
def get_job(jid: int):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@router.post("/scripts/{sid}/scenes/{idx}/image")
def regen_scene_image(sid: int, idx: int):
    conn = get_conn()
    try:
        row = _load_script(conn, sid)
        scenes = json.loads(row["scenes_json"])
        target = next((s for s in scenes if s["idx"] == idx), None)
        if not target:
            raise HTTPException(404, "scene not found")
        _gen_for_scene(conn, target, _category_name(conn, row["category_id"]),
                       row["fmt"], salt=secrets.token_hex(3))
        conn.execute("UPDATE scripts SET scenes_json=? WHERE id=?",
                     (json.dumps(scenes, ensure_ascii=False), sid))
        conn.commit()
        return target
    finally:
        conn.close()
