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
    db.threads_target_link_creative(tid, 999)
    assert db.threads_author_replied_since("@a", 30) is True


def test_pending_excludes_decided(temp_db):
    import db
    t1 = db.threads_target_upsert(_post("https://x/1", "@a"), "photomagic")
    db.threads_target_upsert(_post("https://x/2", "@b"), "photomagic")
    db.threads_target_verdict(t1, 10, "dropped", "관련 없음")
    pending = db.threads_targets_pending(10)
    assert len(pending) == 1
    assert pending[0]["author"] == "@b"
