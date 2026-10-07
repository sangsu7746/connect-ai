# -*- coding: utf-8 -*-
"""폴백 문구는 발행 큐에 들어가지 못한다.

2026-08-13 사고: 구글 프로젝트가 미결제로 막히자(403) 카피 생성이 전량
폴백으로 떨어졌다. 폴백은 업종마다 문장이 고정이라, 같은 방에 똑같은 글이
6번씩 나갔다(ch471·ch472). 로그는 '발행 성공'만 찍어 조용했다.

'다른 문구로 올리니 하루 여러 번 괜찮다'가 발행 상한을 올린 근거였는데,
폴백이 나가는 순간 그 근거가 사라진다. 그래서 **생성이 아니라 발행**에서 막는다.
"""
import sys
import json
import sqlite3
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import db
import auto_loop as A
import publish_campaign as PC

GOOD = json.dumps({"headline": "직접 써 본 후기", "body": "이러이러했습니다",
                   "cta": "어떻게 보세요?"}, ensure_ascii=False)
FALLBACK = json.dumps({"headline": "미리집 안내", "body": "자세한 내용은…",
                       "cta": "자세히 보기", "_fallback": True}, ensure_ascii=False)


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    dbf = tmp_path / "t.db"
    monkeypatch.setattr(db, "DB_PATH", dbf, raising=False)
    monkeypatch.setenv("AUTOAD_DB", str(dbf))
    monkeypatch.delenv("BLOCK_FALLBACK_PUBLISH", raising=False)

    con = sqlite3.connect(dbf)
    con.executescript("""
        CREATE TABLE channels (id INTEGER PRIMARY KEY, platform TEXT, name TEXT,
                               account TEXT, enabled INT, ad_policy TEXT);
        CREATE TABLE campaigns (id INTEGER PRIMARY KEY);
        CREATE TABLE creatives (id INTEGER PRIMARY KEY, campaign_id INT,
                                channel_id INT, image_path TEXT, copy_json TEXT);
        CREATE TABLE approvals (id INTEGER PRIMARY KEY, creative_id INT, state TEXT);
        INSERT INTO campaigns (id) VALUES (1);
    """)
    # aid 1,2 = 정상 / aid 3,4 = 폴백
    for cid, copy in ((1, GOOD), (2, GOOD), (3, FALLBACK), (4, FALLBACK)):
        con.execute("INSERT INTO channels (id,platform,name,account,enabled,ad_policy)"
                    " VALUES (?,'band',?,'a@x.com',1,'allow')", (cid, f"방{cid}"))
        con.execute("INSERT INTO creatives (id,campaign_id,channel_id,image_path,copy_json)"
                    " VALUES (?,1,?,'',?)", (cid, cid, copy))
        con.execute("INSERT INTO approvals (id,creative_id,state)"
                    " VALUES (?,?,'pending')", (cid, cid))
    con.commit()
    con.close()
    return dbf


def test_fallback_never_reaches_the_publisher(seeded):
    """핵심 — 발행 대상에서 폴백이 빠져야 한다."""
    aids = {it["aid"] for it in PC.pending(1)}
    assert aids == {1, 2}, "폴백이 발행 대상에 남아 있다"


def test_loop_does_not_count_fallback_as_work(seeded):
    """'대기 N건'이라 찍고 0건 발행하면 로그와 실제가 어긋난다."""
    assert A.pending_campaigns() == [1]
    groups = A.pending_by_account()
    assert groups == {("a@x.com", "band"): [1]}


def test_held_count_is_reported(seeded):
    """보류 건수가 보여야 한다 — 이 사고의 본질은 침묵이었다."""
    assert A.held_fallback_count() == 2


def test_all_fallback_means_nothing_publishes(seeded):
    """API 가 죽어 전량 폴백이면 아무것도 나가지 않아야 한다."""
    with sqlite3.connect(seeded) as con:
        con.execute("UPDATE creatives SET copy_json=?", (FALLBACK,))
    assert PC.pending(1) == []
    assert A.pending_campaigns() == []
    assert A.held_fallback_count() == 4


def test_recovers_by_itself_when_copy_works_again(seeded):
    """결제가 풀려 정상 문구가 생기면 사람 개입 없이 다시 나가야 한다."""
    with sqlite3.connect(seeded) as con:
        con.execute("UPDATE creatives SET copy_json=? WHERE id IN (3,4)", (GOOD,))
    assert {it["aid"] for it in PC.pending(1)} == {1, 2, 3, 4}
    assert A.held_fallback_count() == 0


def test_switch_can_be_turned_off(seeded, monkeypatch):
    """되돌릴 수 있어야 한다 — 코드를 고치지 않고."""
    monkeypatch.setenv("BLOCK_FALLBACK_PUBLISH", "0")
    assert {it["aid"] for it in PC.pending(1)} == {1, 2, 3, 4}
    assert A.held_fallback_count() == 0


def test_sql_and_python_judge_the_same_thing(seeded):
    """두 판정이 어긋나면 한쪽만 막혀 더 헷갈린다."""
    assert db.is_fallback_copy(FALLBACK) is True
    assert db.is_fallback_copy(GOOD) is False
    assert db.is_fallback_copy(None) is False
    blocked = {3, 4}
    assert {it["aid"] for it in PC.pending(1)}.isdisjoint(blocked)


def test_filter_composes_with_account_and_platform(seeded):
    """병렬 갈래 필터와 함께 걸어도 폴백은 여전히 빠져야 한다."""
    aids = {it["aid"] for it in PC.pending(1, "a@x.com", "band")}
    assert aids == {1, 2}
