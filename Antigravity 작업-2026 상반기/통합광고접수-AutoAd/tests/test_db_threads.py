import json
import sqlite3

import pytest

from threads.models import RawPost


def _post(url="https://www.threads.net/@a/post/1", author="@a"):
    return RawPost(url=url, author=author, text="사진 보정 뭐 쓰세요?",
                   posted_at="2026-08-03T10:00:00", likes=3, replies=1)


def test_upsert_returns_id_and_dedupes(temp_db):
    import db
    first = db.threads_target_upsert(_post(), "photomagic")
    second = db.threads_target_upsert(_post(), "photomagic")
    assert first == second, "같은 post_url 은 한 행이어야 한다"


def test_verdict_updates_score(temp_db):
    import db
    tid = db.threads_target_upsert(_post(), "photomagic")
    db.threads_target_verdict(tid, 87, "passed", "보정 고민 글")
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT score, verdict, reason FROM threads_targets WHERE id=?",
            (tid,)).fetchone()
    assert row["score"] == 87
    assert row["verdict"] == "passed"


def test_author_cooldown_detects_recent_reply(temp_db):
    import db
    tid = db.threads_target_upsert(_post(), "photomagic")
    assert db.threads_author_replied_since("@a", 30) is False
    # 실제 creatives 행을 만들어 진짜 id 를 연결한다(FK 강제 대상이므로 999 같은
    # 가짜 id 는 안 된다 — creative_id 는 creatives(id) 를 참조한다).
    creative_id = db.add_creative(None, None, {})
    db.threads_target_link_creative(tid, creative_id)
    assert db.threads_author_replied_since("@a", 30) is True


def test_pending_excludes_decided(temp_db):
    import db
    t1 = db.threads_target_upsert(_post("https://x/1", "@a"), "photomagic")
    db.threads_target_upsert(_post("https://x/2", "@b"), "photomagic")
    db.threads_target_verdict(t1, 10, "dropped", "관련 없음")
    pending = db.threads_targets_pending(10)
    assert len(pending) == 1
    assert pending[0]["author"] == "@b"


def _posted_threads_reply(kind="threads_reply", metrics=None):
    """threads_reply 발행 흐름 최소 재현: creative → post → posted 전환.

    metrics_json 을 쓰는 전용 setter 는 아직 없다(발행 태스크가 나중에 만든다).
    후속 태스크가 실제로 쓸 값과 정확히 같은 형태(json.dumps({"auto": True}))로
    직접 UPDATE 해서, 그 계약이 깨지면 이 테스트가 실패하도록 고정한다."""
    import db
    creative_id = db.add_creative(None, None, {}, kind=kind)
    post_id = db.record_post(creative_id, None, status="dry")
    db.update_post_status(post_id, "posted")
    if metrics is not None:
        with db.get_conn() as conn:
            conn.execute("UPDATE posts SET metrics_json=? WHERE id=?",
                         (json.dumps(metrics), post_id))
    return post_id


def test_replies_today_counts_posted_threads_reply(temp_db):
    import db
    _posted_threads_reply()
    assert db.threads_replies_today() == 1


def test_replies_today_excludes_other_kind(temp_db):
    import db
    _posted_threads_reply(kind="image")
    assert db.threads_replies_today() == 0


def test_replies_today_excludes_dry_status(temp_db):
    import db
    creative_id = db.add_creative(None, None, {}, kind="threads_reply")
    post_id = db.record_post(creative_id, None, status="dry")
    # record_post() 는 posted_at 을 안 채운다 — 정상 경로로는 status='dry' 이면서
    # posted_at 이 오늘인 행이 안 나온다. 그러면 substr(posted_at,1,10)=오늘 조건
    # 자체가 이미 이 행을 걸러내 버려서, status='posted' 조건을 지워도 이 테스트가
    # 계속 통과하는 가짜 커버리지가 된다. 그래서 posted_at 을 직접 오늘 날짜로
    # 채워, status='posted' 조건 하나만으로 걸러지는지를 검증한다.
    with db.get_conn() as conn:
        conn.execute("UPDATE posts SET posted_at=?, status='dry' WHERE id=?",
                     (db._now(), post_id))
    assert db.threads_replies_today() == 0


def test_replies_today_auto_only_matches_marker(temp_db):
    import db
    _posted_threads_reply(metrics={"auto": True})
    assert db.threads_replies_today(auto_only=True) == 1


def test_replies_today_auto_only_excludes_unmarked(temp_db):
    import db
    _posted_threads_reply()   # metrics_json 없음 — 수동 발행으로 취급
    assert db.threads_replies_today() == 1
    assert db.threads_replies_today(auto_only=True) == 0


_OLD_THREADS_TARGETS_DDL = """
    CREATE TABLE threads_targets (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        post_url     TEXT NOT NULL UNIQUE,
        author       TEXT NOT NULL,
        text         TEXT,
        posted_at    TEXT,
        likes        INTEGER DEFAULT 0,
        replies      INTEGER DEFAULT 0,
        profile_key  TEXT,
        score        INTEGER,
        verdict      TEXT DEFAULT 'pending',
        reason       TEXT,
        creative_id  INTEGER,
        harvested_at TEXT NOT NULL,
        replied_at   TEXT
    )
"""


def test_migrate_threads_targets_fk_rebuilds_old_table(temp_db):
    """최초 배포(커밋 45459faad)가 남긴, FK 없는 threads_targets 상태를 재현하고
    _migrate_threads_targets_fk() 가 이를 안전하게 복구하는지 검증한다."""
    import db
    with db.get_conn() as conn:
        conn.execute("DROP TABLE threads_targets")
        conn.execute(_OLD_THREADS_TARGETS_DDL)
        conn.execute(
            """INSERT INTO threads_targets
               (post_url, author, text, posted_at, likes, replies,
                profile_key, verdict, harvested_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            ("https://x/old", "@old", "old row", "2026-08-01T00:00:00", 1, 0,
             "photomagic", "pending", "2026-08-01T00:00:00"))

    db._migrate_threads_targets_fk()

    # (a) 기존 행이 살아남았는가
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM threads_targets WHERE post_url=?",
            ("https://x/old",)).fetchone()
    assert row is not None
    assert row["author"] == "@old"

    # (b) sqlite_master 가 이제 FK 를 보여주는가
    with db.get_conn() as conn:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='threads_targets'"
        ).fetchone()["sql"]
    assert "REFERENCES creatives" in sql

    # (c) 이제 존재하지 않는 creative_id 를 넣으면 막히는가
    with pytest.raises(sqlite3.IntegrityError):
        with db.get_conn() as conn:
            conn.execute(
                "UPDATE threads_targets SET creative_id=? WHERE post_url=?",
                (999999, "https://x/old"))

    # 두 번째 호출은 아무 것도 바꾸지 않는다(멱등) — 행 수가 그대로인지로 확인
    db._migrate_threads_targets_fk()
    with db.get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM threads_targets").fetchone()["n"]
    assert n == 1
