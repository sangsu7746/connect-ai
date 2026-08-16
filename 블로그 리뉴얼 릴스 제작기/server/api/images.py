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
    r = image_gen.generate(conn, scene.get("image_prompt") or "", style, fmt,
                           salt=salt)
    scene["image_file"] = r["file"]
    scene["image_fallback"] = r["fallback"]


@router.post("/scripts/{sid}/images")
def generate_images(sid: int, body: ImagesIn | None = None):
    force = bool(body and body.force)
    if jobs.has_running("images", str(sid)):
        raise HTTPException(409, "이미지 잡이 이미 실행 중입니다 — 완료 후 다시 시도하세요")
    conn = get_conn()
    try:
        row = _load_script(conn, sid)
        fmt, cid = row["fmt"], row["category_id"]
    finally:
        conn.close()

    def work(ctx: jobs.JobCtx) -> dict:
        conn = get_conn()
        try:
            row = _load_script(conn, sid)
            scenes = json.loads(row["scenes_json"])
            category = _category_name(conn, cid)
            # force가 아니어도 폴백 씬(SD 다운으로 그라디언트 대체)은 재충전 대상 (I5)
            todo = [s["idx"] for s in scenes
                    if force or not s.get("image_file") or s.get("image_fallback")]
            ctx.set_total(len(todo))
            done = 0
            for idx in todo:
                # 프롬프트·스타일은 매번 최신 씬에서 — 사용자가 잡 중 수정해도 반영 (C1)
                row = _load_script(conn, sid)
                scenes = json.loads(row["scenes_json"])
                scene = next((s for s in scenes if s["idx"] == idx), None)
                if scene is None:
                    continue
                # force는 캐시를 우회해 새 이미지를 뽑아야 하므로 리트라이 솔트 부여
                _gen_for_scene(conn, scene, category, fmt,
                               salt=secrets.token_hex(3) if force else "")
                # SD 호출(수 초~분) 도중 사용자가 다른 필드를 PATCH했을 수 있으므로,
                # 쓰기 직전에 scenes_json을 다시 읽어 이 씬의 image_* 두 필드만
                # 병합한다 — 그래야 읽기→쓰기 창이 SD 호출 시간이 아니라 이
                # 병합 자체(수 ms)로 줄어 concurrent 편집을 덮어쓰지 않는다.
                latest_row = _load_script(conn, sid)
                latest_scenes = json.loads(latest_row["scenes_json"])
                latest_scene = next((s for s in latest_scenes if s["idx"] == idx), None)
                if latest_scene is not None:
                    latest_scene["image_file"] = scene["image_file"]
                    latest_scene["image_fallback"] = scene["image_fallback"]
                    conn.execute("UPDATE scripts SET scenes_json=? WHERE id=?",
                                 (json.dumps(latest_scenes, ensure_ascii=False), sid))
                    conn.commit()
                done += 1
                ctx.tick()
            return {"generated": done}
        finally:
            conn.close()

    return {"job_id": jobs.start("images", 0, work, ref=str(sid))}


@router.get("/jobs/{jid}")
def get_job(jid: int):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@router.post("/scripts/{sid}/scenes/{idx}/image")
def regen_scene_image(sid: int, idx: int):
    if jobs.has_running("images", str(sid)):
        raise HTTPException(409, "이미지 잡이 이미 실행 중입니다 — 완료 후 다시 시도하세요")
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
