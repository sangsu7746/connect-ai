# -*- coding: utf-8 -*-
"""카피 API 가 죽었을 때 예전 문구를 돌려 쓴다.

폴백이 위험한 이유는 '생성 실패'가 아니라 **문장이 하나뿐**이라는 것이다.
DB 에는 예전에 LLM 이 만들어 검증까지 통과한 문구가 수백 개 남아 있으니,
그걸 쓰면 API 없이도 문구가 갈린다.

⚠ 본문에 박힌 추적 경로(/t/{캠페인}-{채널})는 반드시 새 것으로 바꿔야 한다.
  그대로 두면 클릭이 예전 추적키로 잡히고, 죽은 링크가 나갈 수 있다.
"""
import sys
import json
import sqlite3
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import db
import config
import orchestrator as O


def _copy(h, b, cta="자세히", **extra):
    d = {"headline": h, "body": b, "cta": cta}
    d.update(extra)
    return json.dumps(d, ensure_ascii=False)


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    dbf = tmp_path / "t.db"
    monkeypatch.setattr(db, "DB_PATH", dbf, raising=False)
    monkeypatch.setenv("AUTOAD_DB", str(dbf))
    monkeypatch.setattr(config, "PROFILE_KEY", "inkcraft", raising=False)

    con = sqlite3.connect(dbf)
    con.executescript("""
        CREATE TABLE channels (id INTEGER PRIMARY KEY, platform TEXT, name TEXT,
                               profile_key TEXT, enabled INT);
        CREATE TABLE creatives (id INTEGER PRIMARY KEY, channel_id INT,
                                image_path TEXT, copy_json TEXT);
        CREATE TABLE posts (id INTEGER PRIMARY KEY, creative_id INT, channel_id INT,
                            status TEXT);
    """)
    for cid in (1, 2, 3):
        con.execute("INSERT INTO channels (id,platform,name,profile_key,enabled)"
                    " VALUES (?,'band',?, 'inkcraft',1)", (cid, f"타투방{cid}"))
    # 과거 문구 — 추적 경로가 박혀 있다. IMG_A 두 건, IMG_B 한 건.
    con.execute("INSERT INTO creatives (id,channel_id,image_path,copy_json) VALUES (1,1,?,?)",
                (IMG_A, _copy("블랙워크 도안 모음",
                              "라인워크부터 도트워크까지 모아봤습니다. headjim-ink.web.app/t/16-193 에서 봅니다."),))
    con.execute("INSERT INTO creatives (id,channel_id,image_path,copy_json) VALUES (2,2,?,?)",
                (IMG_A, _copy("여름 타투 고민",
                              "과하지 않은 도안을 찾는 분들께. headjim-ink.web.app/t/16-195 참고하세요."),))
    # 다른 그림의 문구 — 이게 섞여 나오면 그림과 글이 어긋난다
    con.execute("INSERT INTO creatives (id,channel_id,image_path,copy_json) VALUES (4,1,?,?)",
                (IMG_B, _copy("레터링 도안 안내",
                              "레터링만 모아봤습니다. headjim-ink.web.app/t/16-200 보세요."),))
    # 폴백은 재활용 대상이 아니다
    con.execute("INSERT INTO creatives (id,channel_id,image_path,copy_json) VALUES (3,2,?,?)",
                (IMG_A, _copy("InkCraft 안내", "자세한 내용은…", _fallback=True),))
    con.commit()
    con.close()
    return dbf


IMG_A = r"C:\creatives\showcase_inkcraft_black_band.png"
IMG_B = r"C:\creatives\showcase_inkcraft_lettering_band.png"
CH = {"id": 3, "platform": "band", "name": "타투방3"}
NEW = "headjim-ink.web.app/t/99-3"


def _camp(img=None):
    return {"_image_path": IMG_A if img is None else img}


def test_recycles_past_copy(seeded):
    cap = O._recycled_caption(_camp(), CH, NEW)
    assert cap is not None, "재활용할 문구가 있는데 못 찾았다"
    assert cap.get("_recycled") is True
    assert not cap.get("_fallback"), "재활용은 폴백이 아니다 — 발행 가드에 막히면 안 된다"


def test_old_tracking_path_is_replaced(seeded):
    """이 기능의 핵심 1 — 추적 경로를 새 것으로 바꾼다."""
    cap = O._recycled_caption(_camp(), CH, NEW)
    blob = f"{cap['headline']} {cap['body']} {cap['cta']}"
    assert NEW in blob, "새 추적 경로가 안 들어갔다"
    for stale in ("/t/16-193", "/t/16-195"):
        assert stale not in blob, f"옛 추적 경로 {stale} 가 그대로 남았다 — 클릭이 뒤섞인다"


def test_only_recycles_copy_written_for_the_same_image(seeded):
    """이 기능의 핵심 2 — 그림과 글이 같은 상품을 말해야 한다.

    실측(2026-08-13): 업종만 맞췄더니 임야담보 전단에 토지담보 문구가 붙었다.
    3건 전부 불일치였다. 대부업 광고에서는 오인 소지가 된다.
    """
    for _ in range(12):
        cap = O._recycled_caption(_camp(IMG_A), CH, NEW)
        assert "레터링" not in f"{cap['headline']}{cap['body']}", \
            "다른 그림에 붙었던 문구를 골랐다 — 전단과 본문이 어긋난다"


def test_no_copy_for_this_image_means_no_recycling(seeded):
    """같은 그림 문구가 없으면 어설프게 맞추지 말고 포기한다."""
    assert O._recycled_caption(_camp(r"C:\creatives\처음보는그림.png"), CH, NEW) is None


def test_missing_image_path_means_no_recycling(seeded):
    """이미지를 안 넘기면 짝을 보장할 수 없으니 재활용하지 않는다."""
    assert O._recycled_caption({}, CH, NEW) is None


def test_never_recycles_a_fallback(seeded):
    """폴백을 재활용하면 그냥 폴백이다."""
    for _ in range(8):
        cap = O._recycled_caption(_camp(), CH, NEW)
        assert "자세한 내용은" not in (cap or {}).get("body", "")


def test_skips_text_already_posted_to_this_channel(seeded):
    """같은 방에 이미 나간 글을 다시 내면 재활용의 의미가 없다."""
    with sqlite3.connect(seeded) as con:
        # 소재1의 문구가 채널3 에 이미 나갔다고 기록
        con.execute("INSERT INTO creatives (id,channel_id,image_path,copy_json)"
                    " VALUES (9,3,?,?)",
                    (IMG_A, _copy("블랙워크 도안 모음",
                                  "라인워크부터 도트워크까지 모아봤습니다. headjim-ink.web.app/t/16-193 에서 봅니다."),))
        con.execute("INSERT INTO posts (creative_id,channel_id,status)"
                    " VALUES (9,3,'posted')")
    cap = O._recycled_caption(_camp(), CH, NEW)
    if cap:
        assert "블랙워크 도안 모음" not in cap["headline"], "이 방에 이미 나간 글을 또 골랐다"


def test_returns_none_when_nothing_to_recycle(seeded, monkeypatch):
    """재활용할 게 없으면 None — 호출부가 폴백으로 간다."""
    monkeypatch.setattr(config, "PROFILE_KEY", "존재하지않는업종", raising=False)
    assert O._recycled_caption(_camp(), CH, NEW) is None


def test_choice_is_stable_for_the_same_channel(seeded):
    """같은 채널은 늘 같은 선택이어야 재현이 된다(hash() 는 프로세스마다 다르다)."""
    a = O._recycled_caption(_camp(), CH, NEW)
    b = O._recycled_caption(_camp(), CH, NEW)
    assert a == b


def test_different_channels_get_different_copy(seeded):
    """채널이 다르면 문구도 갈려야 한다 — 그게 목적이다."""
    picks = set()
    for chid in range(10, 30):
        cap = O._recycled_caption(_camp(), {"id": chid, "platform": "band"},
                                  f"headjim-ink.web.app/t/99-{chid}")
        if cap:
            picks.add(cap["headline"])
    assert len(picks) > 1, "채널이 달라도 늘 같은 문구를 고른다"


def test_no_track_path_still_works(seeded):
    """새 추적 경로가 없으면 옛 경로를 걷어내고라도 내보낸다."""
    cap = O._recycled_caption(_camp(), CH, "")
    assert cap is not None
    blob = f"{cap['headline']} {cap['body']}"
    assert "/t/16-" not in blob, "추적 경로가 없는데 옛 경로가 남았다"
