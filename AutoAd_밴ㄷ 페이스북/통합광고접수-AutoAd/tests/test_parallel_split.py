# -*- coding: utf-8 -*-
"""병렬 발행을 계정+플랫폼으로 나눈다 — 갈래가 서로를 침범하면 안 된다.

나누는 근거는 '한 채널은 한 계정, 한 플랫폼에만 속한다'이다. 그래서 둘 중
하나만 달라도 대상 채널이 겹치지 않고, 같은 방에 두 번 올라갈 수 없다.

⚠ 이 성질이 깨지면 조용히 깨진다. 두 프로세스가 같은 대기건을 각각 집어가
  같은 그룹에 광고가 2번 올라가는데, 로그에는 양쪽 다 '발행 성공'으로 찍힌다.
"""
import sys
import sqlite3
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import db
import auto_loop as A
import publish_campaign as PC


@pytest.fixture
def two_platform_db(tmp_path, monkeypatch):
    """한 계정이 밴드·페이스북 채널을 모두 가진 상황을 만든다.

    한 캠페인 안에 두 플랫폼이 섞여 있어야 의미가 있다 — 갈래를 나눈 뒤
    서로의 몫을 집어가는지 보려는 것이므로.
    """
    dbf = tmp_path / "t.db"
    monkeypatch.setattr(db, "DB_PATH", dbf, raising=False)
    monkeypatch.setenv("AUTOAD_DB", str(dbf))

    con = sqlite3.connect(dbf)
    con.executescript("""
        CREATE TABLE channels (id INTEGER PRIMARY KEY, platform TEXT, name TEXT,
                               account TEXT, enabled INT, ad_policy TEXT);
        CREATE TABLE campaigns (id INTEGER PRIMARY KEY);
        -- ⚠ copy_json 은 실제 스키마에 있고 발행 질의가 읽는다(폴백 차단).
        --   빼면 'no such column' 로 터진다 — 픽스처는 실제 스키마를 따라간다.
        CREATE TABLE creatives (id INTEGER PRIMARY KEY, campaign_id INT,
                                channel_id INT, image_path TEXT, copy_json TEXT);
        CREATE TABLE approvals (id INTEGER PRIMARY KEY, creative_id INT, state TEXT);
        INSERT INTO campaigns (id) VALUES (1);
    """)
    rows = [
        # id, platform,   account,    enabled
        (1, "band",     "a@x.com", 1),
        (2, "band",     "a@x.com", 1),
        (3, "facebook", "a@x.com", 1),
        (4, "facebook", "b@x.com", 1),
        (5, "facebook", "a@x.com", 0),      # 꺼진 채널 - 어디에도 안 나와야 한다
    ]
    for cid, plat, acct, en in rows:
        con.execute("INSERT INTO channels (id,platform,name,account,enabled,ad_policy)"
                    " VALUES (?,?,?,?,?,'allow')", (cid, plat, f"방{cid}", acct, en))
        con.execute("INSERT INTO creatives (id,campaign_id,channel_id,image_path,copy_json)"
                    " VALUES (?,1,?,'','{\"headline\":\"정상 문구\"}')", (cid, cid))
        con.execute("INSERT INTO approvals (id,creative_id,state)"
                    " VALUES (?,?,'pending')", (cid, cid))
    con.commit()
    con.close()
    return dbf


def test_groups_split_by_account_and_platform(two_platform_db):
    groups = A.pending_by_account()
    assert set(groups) == {
        ("a@x.com", "band"),
        ("a@x.com", "facebook"),
        ("b@x.com", "facebook"),
    }, "계정이 같아도 플랫폼이 다르면 갈래가 나뉘어야 한다"


def test_each_branch_sees_only_its_own_channels(two_platform_db):
    """핵심 안전성 — 갈래끼리 대상이 겹치면 같은 방에 두 번 올라간다."""
    seen = {}
    for acct, plat in [("a@x.com", "band"), ("a@x.com", "facebook"),
                       ("b@x.com", "facebook")]:
        ids = {it["aid"] for it in PC.pending(1, acct, plat)}
        seen[(acct, plat)] = ids

    assert seen[("a@x.com", "band")] == {1, 2}
    assert seen[("a@x.com", "facebook")] == {3}
    assert seen[("b@x.com", "facebook")] == {4}

    # 어느 두 갈래도 공통 원소가 없어야 한다
    keys = list(seen)
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            overlap = seen[keys[i]] & seen[keys[j]]
            assert not overlap, f"{keys[i]} 와 {keys[j]} 가 {overlap} 을 함께 집는다"


def test_disabled_channel_is_in_no_branch(two_platform_db):
    """꺼진 채널은 '여기 더 올리지 마라'는 뜻이다."""
    everywhere = set()
    for acct, plat in [("a@x.com", "band"), ("a@x.com", "facebook"),
                       ("b@x.com", "facebook")]:
        everywhere |= {it["aid"] for it in PC.pending(1, acct, plat)}
    assert 5 not in everywhere


def test_platform_filter_alone_still_narrows(two_platform_db):
    """--platform 만 줘도 그 플랫폼만 나와야 한다(수동 실행용)."""
    assert {it["aid"] for it in PC.pending(1, platform="band")} == {1, 2}
    assert {it["aid"] for it in PC.pending(1, platform="facebook")} == {3, 4}


def test_no_filter_returns_everything_enabled(two_platform_db):
    """필터 없이 부르던 기존 호출은 그대로 동작해야 한다(무회귀)."""
    assert {it["aid"] for it in PC.pending(1)} == {1, 2, 3, 4}


def test_child_command_carries_both_filters(two_platform_db, monkeypatch):
    """자식 프로세스에 --account 와 --platform 이 **둘 다** 실려야 한다.

    하나라도 빠지면 그 프로세스가 다른 갈래의 대기건까지 발행한다.
    """
    calls = []

    def fake_run(cmd, env=None, timeout=1800):
        calls.append(cmd)
        return True, ""

    monkeypatch.setattr(A, "run", fake_run)
    monkeypatch.setattr(A, "_tally", lambda out, pre: (0, False))
    # ⚠ log() 는 data/auto_loop.log 에 **실제로** 쓴다. 막지 않으면 테스트가
    #   운영 로그에 가짜 '3갈래 병렬 발행' 줄을 남긴다(2026-08-13 실제로 남겼다).
    monkeypatch.setattr(A, "log", lambda *a, **k: None)
    A._publish_parallel(A.pending_by_account())

    assert len(calls) == 3, "갈래 수만큼 프로세스를 띄워야 한다"
    for cmd in calls:
        assert "--account" in cmd, f"계정 필터가 빠졌다: {cmd}"
        assert "--platform" in cmd, f"플랫폼 필터가 빠졌다: {cmd}"
        # 짝이 맞는지 — band 갈래에 facebook 이 실리면 안 된다
        acct = cmd[cmd.index("--account") + 1]
        plat = cmd[cmd.index("--platform") + 1]
        assert (acct, plat) in {("a@x.com", "band"), ("a@x.com", "facebook"),
                                ("b@x.com", "facebook")}
