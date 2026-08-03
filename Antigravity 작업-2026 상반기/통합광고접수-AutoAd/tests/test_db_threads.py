import json

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
    db.record_post(creative_id, None, status="dry")   # posted 로 전환하지 않음
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
