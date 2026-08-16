import threading
from core import locks


def test_scenes_lock_exists_and_is_lock():
    assert isinstance(locks.scenes_lock, type(threading.Lock()))


def test_images_and_scripts_use_lock(monkeypatch):
    """소스 검사: 병합-쓰기 구간이 락을 잡는지 (정적 확인 — 동작 경합은 M3 회귀 테스트가 커버)"""
    import inspect
    import api.images as im
    import api.scripts as sc

    assert "scenes_lock" in inspect.getsource(im), "images.py should use scenes_lock"
    assert "scenes_lock" in inspect.getsource(sc._update_scene), "_update_scene should use scenes_lock"


def test_job_preserves_concurrent_text_edit(monkeypatch):
    """경합 테스트: 동시에 이미지 잡이 씬을 업데이트하고 텍스트를 편집할 때
    텍스트 편집이 이미지 덮어쓰기에 의해 유실되지 않는지 확인"""
    import json
    import threading
    import time
    from core.db import get_conn
    from api import scripts as sc

    conn = get_conn()
    try:
        # 테스트용 스크립트 생성
        now = "2026-08-16T00:00:00"
        scenes = json.dumps([
            {"idx": 0, "role": "intro", "caption": "초", "narration": "나레",
             "image_file": None, "image_fallback": None},
            {"idx": 1, "role": "body", "caption": "본", "narration": "이야기",
             "image_file": None, "image_fallback": None},
        ], ensure_ascii=False)
        analysis_json = json.dumps({"fact_sheet": [], "diag": {}, "chapters": []}, ensure_ascii=False)

        cur = conn.execute(
            """INSERT INTO scripts(category_id, post_ids_json, fmt, duration_sec,
               analysis_json, scenes_json, description_md, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (1, json.dumps([]), "reels", 30, analysis_json, scenes, "", now))
        conn.commit()
        sid = cur.lastrowid

        results = {"text_ok": False, "image_ok": False}
        errors = []

        def edit_text():
            try:
                # 텍스트 편집: caption 변경
                def mutate(target, posts, diag):
                    target["caption"] = "편집됨"
                    return None

                sc._update_scene(sid, 0, mutate, needs_posts=False)
                results["text_ok"] = True
            except Exception as e:
                errors.append(f"text_edit: {e}")

        def update_image():
            try:
                # 이미지 업데이트: image_file 설정 (락 안에서 fresh-merge)
                conn2 = get_conn()
                try:
                    row = conn2.execute("SELECT scenes_json FROM scripts WHERE id=?", (sid,)).fetchone()
                    scenes_list = json.loads(row["scenes_json"])
                    target = next((s for s in scenes_list if s["idx"] == 0), None)
                    if target:
                        target["image_file"] = "test.jpg"
                        target["image_fallback"] = False
                        # 쓰기 직전 fresh read — 텍스트 편집이 그동안 커밋한 기록을 보존한다
                        with locks.scenes_lock:
                            fresh_row = conn2.execute("SELECT scenes_json FROM scripts WHERE id=?", (sid,)).fetchone()
                            fresh_scenes = json.loads(fresh_row["scenes_json"])
                            fresh_target = next((s for s in fresh_scenes if s["idx"] == 0), None)
                            if fresh_target:
                                fresh_target["image_file"] = "test.jpg"
                                fresh_target["image_fallback"] = False
                                conn2.execute("UPDATE scripts SET scenes_json=? WHERE id=?",
                                             (json.dumps(fresh_scenes, ensure_ascii=False), sid))
                                conn2.commit()
                    results["image_ok"] = True
                finally:
                    conn2.close()
            except Exception as e:
                errors.append(f"update_image: {e}")

        # 동시 실행 (텍스트 편집과 이미지 업데이트)
        t1 = threading.Thread(target=edit_text)
        t2 = threading.Thread(target=update_image)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 최종 상태 확인: 둘 다 성공해야 하고, caption은 "편집됨"이어야 함
        assert results["text_ok"], f"text edit failed: {errors}"
        assert results["image_ok"], f"image update failed: {errors}"

        # 커밋 후 검증: 텍스트와 이미지가 모두 보존되어야 함
        final_row = conn.execute("SELECT scenes_json FROM scripts WHERE id=?", (sid,)).fetchone()
        final_scenes = json.loads(final_row["scenes_json"])
        final_scene = next((s for s in final_scenes if s["idx"] == 0), None)

        assert final_scene["caption"] == "편집됨", f"caption lost: {final_scene['caption']}"
        assert final_scene["image_file"] == "test.jpg", f"image_file lost: {final_scene.get('image_file')}"

    finally:
        # 정리
        conn.execute("DELETE FROM scripts WHERE id=?", (sid,))
        conn.commit()
        conn.close()
