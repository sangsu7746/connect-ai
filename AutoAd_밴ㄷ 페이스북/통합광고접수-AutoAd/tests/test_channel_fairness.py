# -*- coding: utf-8 -*-
"""channels_for_profile() 이 특정 계정·채널을 영원히 굶기지 않는다.

2026-08-17 실측 사고: run_by_profile.py 는 이 함수가 돌려준 목록을
chans[:limit] 로 자른다. 정렬 없이(=SQLite 기본순, 사실상 채널 id 순)
반환하면 id 가 낮은 채널이 매번 이겨서, id 가 높은 채널은 그 업종이
존재하는 한 영원히 안 뽑힌다 — headjim100 계정의 밴드 채널 47곳이
2026-08-12 이후 단 한 번도 새 소재를 못 받은 원인이었다.

'가장 오래 안 나간 채널을 우선'으로 처음 고쳤다가 다시 사고를 봤다 —
channel 이 이 프로젝트 규모(371개)에서는 '한 번도 안 나간 채널' 풀이
절대 마르지 않아서, 한 번이라도 나갔던 채널은 그 순간부터 영원히
밀린다. 그래서 이력을 아예 안 보고 순수 무작위로 섞는다.
"""
import sys
import sqlite3
import collections
from pathlib import Path

import pytest

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import db


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    dbf = tmp_path / "t.db"
    monkeypatch.setattr(db, "DB_PATH", dbf, raising=False)
    monkeypatch.setenv("AUTOAD_DB", str(dbf))

    con = sqlite3.connect(dbf)
    con.executescript("""
        CREATE TABLE channels (
            id INTEGER PRIMARY KEY, platform TEXT, target_ref TEXT, name TEXT,
            audience TEXT, tone TEXT, topic TEXT, active_hours TEXT,
            banned_words TEXT, profile_json TEXT, enabled INT,
            created_at TEXT, account TEXT, profile_key TEXT,
            ad_policy TEXT, rules_text TEXT, rules_checked_at TEXT
        );
    """)
    # 낮은 id 20개는 계정A, 높은 id 5개는 계정B — 옛 코드라면 계정B 가
    # chans[:limit] 에 절대 안 들었을 배치다.
    for cid in range(1, 21):
        con.execute("INSERT INTO channels (id,platform,name,account,enabled,profile_key)"
                    " VALUES (?,'band',?,'a@x.com',1,'loan')", (cid, f"방{cid}"))
    for cid in range(101, 106):
        con.execute("INSERT INTO channels (id,platform,name,account,enabled,profile_key)"
                    " VALUES (?,'band',?,'b@x.com',1,'loan')", (cid, f"b방{cid}"))
    con.commit()
    con.close()
    return dbf


def test_low_id_account_no_longer_monopolizes_the_prefix(seeded):
    """이 사고의 핵심 단언 — 계정B(고id)가 여러 번 부르면 앞자리에 들어야 한다."""
    seen_b_in_top3 = 0
    for _ in range(80):
        chans = db.channels_for_profile("loan", enabled_only=True)
        top3_ids = {c["id"] for c in chans[:3]}
        if top3_ids & {101, 102, 103, 104, 105}:
            seen_b_in_top3 += 1
    assert seen_b_in_top3 > 0, "고id 계정이 80번 중 단 한 번도 상위 3에 못 들었다 - 사고가 재현됐다"


def test_every_channel_eventually_leads(seeded):
    """모든 채널이 결국 1순위로 뽑혀야 한다 — 25개 중 1개도 영구 배제되면 안 된다."""
    firsts = collections.Counter()
    for _ in range(300):
        chans = db.channels_for_profile("loan", enabled_only=True)
        firsts[chans[0]["id"]] += 1
    assert len(firsts) == 25, f"일부 채널이 1순위로 한 번도 안 뽑혔다: {25 - len(firsts)}개 누락"


def test_disabled_channels_excluded(seeded):
    with sqlite3.connect(seeded) as con:
        con.execute("UPDATE channels SET enabled=0 WHERE id=1")
    ids = {c["id"] for c in db.channels_for_profile("loan", enabled_only=True)}
    assert 1 not in ids


def test_other_profile_not_mixed_in(seeded):
    with sqlite3.connect(seeded) as con:
        con.execute("UPDATE channels SET profile_key='adstudio' WHERE id=1")
    ids = {c["id"] for c in db.channels_for_profile("loan", enabled_only=True)}
    assert 1 not in ids
    assert len(ids) == 24


def test_returns_full_row_dicts(seeded):
    """호출부(run_by_profile.py)가 c['id']·c['platform']·c['name'] 을 바로 쓴다."""
    chans = db.channels_for_profile("loan", enabled_only=True)
    c = chans[0]
    assert set(("id", "platform", "name", "account")).issubset(c.keys())
