# -*- coding: utf-8 -*-
"""쿨다운은 '같은 방' 기준이다.

.env 주석이 그 근거를 이미 적어 뒀다 —
  "매 건 다른 문구로 나가고, 그림도 쿨다운 때문에 같은 것이 다시 쓰이지 않는다
   — '같은 방에 같은 글' 이 아니다"
목적이 같은 방에서의 반복 방지였는데 구현이 전역이라, 한 바퀴에 그림이
발행 건수만큼 필요했다. 스코프를 좁혀 '상품 1바퀴 = 그림 1장' 으로 만든다.
"""
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import db


def _seed(con, image_path, channel_id, when):
    # ⚠ creatives.created_at 은 TEXT NOT NULL 이고 기본값이 없다 — 안 넣으면
    #   이 INSERT 가 제약 위반으로 죽어서, 우리가 확인하려는 동작이 아니라
    #   엉뚱한 스키마 에러가 RED 로 뜬다. posts 의 when 과 같은 값을 쓴다.
    # ⚠ db.get_conn() 이 PRAGMA foreign_keys=ON 을 켜 두므로 campaign_id·channel_id
    #   가 가리키는 부모 행이 없으면 FK 위반으로 죽는다(이것도 스키마 에러이지
    #   우리가 보려는 동작이 아니다) — 최소한의 부모 행을 같이 만든다.
    con.execute(
        "INSERT OR IGNORE INTO campaigns (id, title, created_at) VALUES (1, 't', ?)",
        (when,))
    con.execute(
        "INSERT OR IGNORE INTO channels (id, platform, target_ref, created_at) "
        "VALUES (?, 'band', ?, ?)", (channel_id, f"ch-{channel_id}", when))
    cur = con.execute(
        "INSERT INTO creatives (campaign_id, channel_id, kind, image_path, created_at) "
        "VALUES (1, ?, 'ad', ?, ?)", (channel_id, image_path, when))
    cid = cur.lastrowid
    con.execute(
        "INSERT INTO posts (creative_id, channel_id, status, posted_at, created_at) "
        "VALUES (?, ?, 'posted', ?, ?)", (cid, channel_id, when, when))
    return cid


def test_same_image_blocked_in_same_channel(temp_db):
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        _seed(con, "/img/a.png", 11, now)
    assert db.image_cooldown_left("/img/a.png", 14, channel_id=11) > 0


def test_same_image_free_in_other_channel(temp_db):
    """이게 이 변경의 핵심 — 다른 방에는 나갈 수 있어야 한다."""
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        _seed(con, "/img/a.png", 11, now)
    assert db.image_cooldown_left("/img/a.png", 14, channel_id=22) == 0


def test_global_scope_unchanged_when_channel_omitted(temp_db):
    """하위호환 — channel_id 를 안 주면 예전 그대로 전역이다."""
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        _seed(con, "/img/a.png", 11, now)
    assert db.image_cooldown_left("/img/a.png", 14) > 0


def test_round_id_column_exists(temp_db):
    with db.get_conn() as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(creatives)")]
    assert "round_id" in cols
