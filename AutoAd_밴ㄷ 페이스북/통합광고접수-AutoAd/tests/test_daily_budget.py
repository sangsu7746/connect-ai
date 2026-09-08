# -*- coding: utf-8 -*-
"""예산은 '목표' 가 아니라 '천장' 이다.

실제 생성량은 재고 목표치가 정하고, 목표에 닿으면 need=0 이 되어 저절로 멈춘다.
⚠ 엔진별로 나눈 이유: 하나로 두면 CARD_ENGINE=gemini 로 되돌리는 순간
  같은 천장이 그대로 '과금' 이 된다 — 롤백 스위치가 과금 스위치가 되어 버린다.
"""
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import db


def _seed_parent_rows(con, when):
    # ⚠ db.get_conn() 이 PRAGMA foreign_keys=ON 을 켜 두므로 creatives.campaign_id·
    #   channel_id 가 가리키는 부모 행이 없으면 INSERT 가 FOREIGN KEY 위반으로
    #   죽는다(실측 확인) — 이건 우리가 보려는 동작이 아니라 스키마 에러다.
    #   test_cooldown_scope.py 의 _seed() 와 같은 최소 부모 행 패턴을 쓴다.
    con.execute(
        "INSERT OR IGNORE INTO campaigns (id, title, created_at) VALUES (1, 't', ?)",
        (when,))
    con.execute(
        "INSERT OR IGNORE INTO channels (id, platform, target_ref, created_at) "
        "VALUES (1, 'band', 'ch-1', ?)", (when,))


def test_budget_follows_engine(monkeypatch):
    import config
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_SD", 12)
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_GEMINI", 2)
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    assert config.image_daily_budget() == 12
    monkeypatch.setattr(config, "CARD_ENGINE", "gemini")
    assert config.image_daily_budget() == 2


def test_images_made_today_counts_only_today(temp_db):
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        _seed_parent_rows(con, now)
        con.execute("INSERT INTO creatives (campaign_id, channel_id, kind, "
                    "image_path, created_at) VALUES (1,1,'ad','/a.png',?)", (now,))
        con.execute("INSERT INTO creatives (campaign_id, channel_id, kind, "
                    "image_path, created_at) VALUES (1,1,'ad','/b.png',"
                    "'2020-01-01T00:00:00')")
    assert db.images_made_today() == 1


def test_images_made_today_ignores_rows_without_image(temp_db):
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        _seed_parent_rows(con, now)
        con.execute("INSERT INTO creatives (campaign_id, channel_id, kind, "
                    "image_path, created_at) VALUES (1,1,'ad','',?)", (now,))
    assert db.images_made_today() == 0


def test_remaining_budget_clamps_at_zero(monkeypatch, temp_db):
    import config
    import auto_loop as A
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_SD", 2)
    monkeypatch.setattr(db, "images_made_today", lambda: 5)
    assert A.remaining_image_budget() == 0


def test_remaining_budget_reports_leftover(monkeypatch, temp_db):
    import config
    import auto_loop as A
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_SD", 12)
    monkeypatch.setattr(db, "images_made_today", lambda: 5)
    assert A.remaining_image_budget() == 7


def test_do_generate_still_makes_images_for_unstocked_platform(monkeypatch, temp_db):
    """수정 사항의 핵심 단언 — printcraft 실측 재현.

    facebook 은 재고 53장(목표 42장) 충족, band 는 재고 0장(목표 14장) 미달인
    상태에서, 업종 하나가 두 플랫폼에 걸쳐 있을 때 band 몫은 계속 만들어져야
    한다. profile 단위로만 재고를 봤다면(수정 전) facebook 의 넉넉한 재고가
    band 의 재고 부족을 가려 둘 다 건너뛰었을 것이다.
    """
    import auto_loop as A

    logs = []
    # ⚠ log() 는 data/auto_loop.log 에 실제로 쓴다(test_parallel_split.py 의
    #   경고 참고) — 막지 않으면 테스트가 운영 로그에 가짜 줄을 남긴다.
    monkeypatch.setattr(A, "log", lambda *a, **k: logs.append(a[0] if a else ""))
    monkeypatch.setattr(
        A, "platforms_in_use",
        lambda profiles=None: {"band": {"printcraft"}, "facebook": {"printcraft"}})
    monkeypatch.setattr(A, "remaining_today", lambda platform, profiles=None: 10)
    monkeypatch.setattr(A, "pending_count", lambda platform=None: 0)
    monkeypatch.setattr(A, "free_channels", lambda platform, profiles=None: 10)
    monkeypatch.setattr(A, "per_cycle_cap", lambda min_n=0: 10)
    monkeypatch.setattr(A, "remaining_image_budget", lambda: 100)
    monkeypatch.setattr(A, "free_images", lambda prof, platform: None)
    monkeypatch.setattr(A, "stock_target",
                        lambda prof, platform: 14 if platform == "band" else 42)
    monkeypatch.setattr(A, "stock_count",
                        lambda prof, platform: 0 if platform == "band" else 53)

    A.do_generate({"printcraft"}, dry=True)

    joined = "\n".join(str(m) for m in logs)
    assert "재고 목표 42장 충족 → 건너뜀" in joined, "facebook 은 재고 충족이라 건너뛰어야 한다"
    assert "재고 목표 14장 충족" not in joined, "band 는 재고 미달이니 건너뛰면 안 된다"
    assert any("printcraft:" in m and "건 생성" in m for m in logs), \
        "band 몫은 실제로 생성 로그가 찍혀야 한다"
