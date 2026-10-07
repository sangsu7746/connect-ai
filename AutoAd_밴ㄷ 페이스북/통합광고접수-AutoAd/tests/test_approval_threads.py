def test_pending_exposes_reply_fields(temp_db):
    import approval
    import db

    ch = db.add_channel("threads", "@tester", name="쓰레드 @tester")
    camp = db.add_campaign("쓰레드 답글")
    cid = db.add_creative(camp, ch, {
        "reply": "저도 그 고민 했어요 https://x.test",
        "target_url": "https://www.threads.net/@a/post/1",
        "target_author": "@a",
        "target_excerpt": "셀카 보정 앱 뭐 쓰세요?",
        "score": 78,
        "profile_key": "photomagic",
        "brand": "PhotoMagic",
    }, kind="threads_reply")
    db.enqueue_approval(cid)

    item = approval.pending()[0]
    assert item["is_reply"] is True
    assert item["target_author"] == "@a"
    assert item["score"] == 78
    assert "고민" in item["reply_text"]
    assert "셀카" in item["target_excerpt"]


def test_pending_keeps_normal_creatives_intact(temp_db):
    """기존 이미지 소재가 망가지지 않아야 한다."""
    import approval
    import db

    ch = db.add_channel("band", "https://band.us/band/1", name="테스트밴드")
    camp = db.add_campaign("일반 캠페인")
    cid = db.add_creative(camp, ch, {"headline": "제목", "body": "본문", "cta": "문의"},
                          image_path="x.png")
    db.enqueue_approval(cid)

    item = approval.pending()[0]
    assert item["is_reply"] is False
    assert item["caption"]["headline"] == "제목"
