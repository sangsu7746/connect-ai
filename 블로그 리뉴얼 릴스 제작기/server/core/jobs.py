"""최소 잡 러너 (spec §8 — §3 잡 큐의 M3 최소형). 스레드 1개/잡.
SQLite 커넥션은 스레드 간 공유 금지 — 잡 스레드가 자체 커넥션을 연다."""
import datetime
import json
import threading

from .db import get_conn


class JobCtx:
    def __init__(self, jid: int):
        self.jid = jid

    def tick(self) -> None:
        conn = get_conn()
        try:
            conn.execute("UPDATE jobs SET progress = progress + 1 WHERE id=?",
                         (self.jid,))
            conn.commit()
        finally:
            conn.close()

    def set_total(self, n: int) -> None:
        conn = get_conn()
        try:
            conn.execute("UPDATE jobs SET total=? WHERE id=?", (n, self.jid))
            conn.commit()
        finally:
            conn.close()


def start(kind: str, total: int, work, ref: str = "") -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO jobs(kind, total, ref, created_at) VALUES(?,?,?,?)",
            (kind, total, ref,
             datetime.datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        jid = cur.lastrowid
    finally:
        conn.close()

    def _run():
        ctx = JobCtx(jid)
        conn = get_conn()
        try:
            result = work(ctx)
            conn.execute("UPDATE jobs SET status='done', result_json=? WHERE id=?",
                         (json.dumps(result or {}, ensure_ascii=False), jid))
            conn.commit()
        except Exception as e:
            conn.execute("UPDATE jobs SET status='error', error=? WHERE id=?",
                         (f"{type(e).__name__}: {e}", jid))
            conn.commit()
        finally:
            conn.close()

    threading.Thread(target=_run, daemon=True).start()
    return jid


def get(jid: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def has_running(kind: str, ref: str) -> bool:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT 1 FROM jobs WHERE kind=? AND ref=? AND status='running'",
            (kind, ref)).fetchone() is not None
    finally:
        conn.close()


def has_running_kind(kind: str) -> bool:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT 1 FROM jobs WHERE kind=? AND status='running'",
            (kind,)).fetchone() is not None
    finally:
        conn.close()
