# -*- coding: utf-8 -*-
"""creatives.image_path 를 현재 폴더로 옮긴다.

⚠ 옛 경로는 백슬래시(윈도우)로도, 슬래시로도 저장돼 있을 수 있다.
  ntpath 를 쓰지 않고 두 구분자를 모두 자른다 — 리눅스에서 돌려도 같은 결과.
⚠ 새 위치에 파일이 없으면 None 을 돌려주고 **그 행은 건드리지 않는다.**
  없는 경로로 덮어쓰면 원래 경로 정보까지 잃는다.
"""
import io
import sys
import argparse
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))


def _utf8_stdout():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      line_buffering=True)
    except Exception:
        pass


def remap(old_path: str, creatives_dir) -> str | None:
    name = str(old_path or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        return None
    new = Path(creatives_dir) / name
    return str(new) if new.is_file() else None


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다(없으면 점검만)")
    a = ap.parse_args()

    import config
    import db

    with db.get_conn() as con:
        rows = con.execute(
            "SELECT id, image_path FROM creatives "
            "WHERE COALESCE(image_path,'') <> ''").fetchall()

    hit = miss = same = 0
    for r in rows:
        old = r["image_path"]
        if Path(old).is_file():
            same += 1
            continue
        new = remap(old, config.CREATIVES_DIR)
        if new is None:
            miss += 1
            continue
        hit += 1
        if a.apply:
            with db.get_conn() as con:
                con.execute("UPDATE creatives SET image_path=? WHERE id=?",
                            (new, r["id"]))

    print(f"이미 정상 {same}건 · 옮길 수 있음 {hit}건 · 원본 없음 {miss}건")
    if not a.apply:
        print("점검만 했습니다. 실제로 쓰려면 --apply 를 붙이세요.")


if __name__ == "__main__":
    main()
