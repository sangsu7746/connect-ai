# -*- coding: utf-8 -*-
"""예산은 '목표' 가 아니라 '천장' 이다.

실제 생성량은 재고 목표치가 정하고, 목표에 닿으면 need=0 이 되어 저절로 멈춘다.
⚠ 엔진별로 나눈 이유: 하나로 두면 CARD_ENGINE=gemini 로 되돌리는 순간
  같은 천장이 그대로 '과금' 이 된다 — 롤백 스위치가 과금 스위치가 되어 버린다.

⚠ 예산의 단위는 **이미지 생성 횟수**다. 소재(creatives) 행 수가 아니다.
  둘을 헷갈리면 재사용(공짜)·로컬 합성(loan 전단, Pillow)까지 예산을 쓴 것으로
  세어, 하루 천장이 그대로 '하루 소재 총량' 이 된다(2026-09-08 전수 리뷰 C1).
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


def _seed_creatives(n: int):
    """오늘 날짜로 image_path 가 있는 소재 n건. **이미지를 만든 적은 없다** —
    재고를 재사용했거나 loan 전단을 Pillow 로 합성한 경우가 여기 해당한다."""
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        _seed_parent_rows(con, now)
        for i in range(n):
            con.execute(
                "INSERT INTO creatives (campaign_id, channel_id, kind, "
                "image_path, created_at) VALUES (1,1,'ad',?,?)",
                (f"/stock_{i}.png", now))


def test_budget_follows_engine(monkeypatch):
    import config
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_SD", 12)
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_GEMINI", 2)
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    assert config.image_daily_budget() == 12
    monkeypatch.setattr(config, "CARD_ENGINE", "gemini")
    assert config.image_daily_budget() == 2


# ── 카운터: 실제로 그림이 나온 지점에서만 오른다 ──────────────────────

def test_counter_starts_at_zero(temp_db):
    assert db.images_generated_today() == 0


def test_counter_adds_up(temp_db):
    db.note_image_generated()
    db.note_image_generated(3)
    assert db.images_generated_today() == 4


def test_counter_is_scoped_to_today(temp_db):
    """어제 쓴 예산이 오늘을 잡아먹으면 안 된다."""
    db.note_image_generated(9, day="2020-01-01")
    assert db.images_generated_today() == 0
    db.note_image_generated(2)
    assert db.images_generated_today() == 2


def test_creatives_alone_do_not_spend_budget(temp_db):
    """재사용은 공짜다 — 소재만 쌓여도 예산은 그대로여야 한다.

    이게 C1 의 핵심이다. 예전 분모(creatives 행 수)는 재고를 돌려 쓴 소재와
    loan 의 로컬 합성 전단까지 세어, 소재 2건이 생긴 순간 하루 예산이 말랐다.
    """
    import config
    import auto_loop as A
    _seed_creatives(50)
    assert db.images_generated_today() == 0
    assert A.remaining_image_budget() == config.image_daily_budget()


def test_remaining_budget_clamps_at_zero(monkeypatch, temp_db):
    import config
    import auto_loop as A
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_SD", 2)
    monkeypatch.setattr(db, "images_generated_today", lambda: 5)
    assert A.remaining_image_budget() == 0


def test_remaining_budget_reports_leftover(monkeypatch, temp_db):
    import config
    import auto_loop as A
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_SD", 12)
    monkeypatch.setattr(db, "images_generated_today", lambda: 5)
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
    assert "재고 목표 42장 충족" in joined, "facebook 은 재고 충족을 알려야 한다"
    assert "재고 목표 14장 충족" not in joined, "band 는 재고 미달이니 충족이라 하면 안 된다"
    assert any("printcraft:" in m and "건 생성" in m for m in logs), \
        "band 몫은 실제로 생성 로그가 찍혀야 한다"


# ── 통합: 진짜 예산 함수 + 기본 설정으로 do_generate 를 돌린다 ──────────
# ⚠ 위 테스트들이 remaining_image_budget 을 통째로 갈아끼우기 때문에, 기본
#   설정에서의 실제 천장은 스위트 어디에서도 한 번도 지나가지 않았다. C1 이
#   전 과제 리뷰를 초록으로 통과한 이유가 정확히 이것이다. 아래 둘은 그 이음매를
#   갈아끼우지 않고 그대로 지난다.

def _stub_platform_math(monkeypatch, A, logs):
    """플랫폼 수급 계산만 고정한다 — 예산 계산에는 손대지 않는다."""
    monkeypatch.setattr(A, "log", lambda *a, **k: logs.append(a[0] if a else ""))
    monkeypatch.setattr(A, "platforms_in_use",
                        lambda profiles=None: {"band": {"printcraft"}})
    monkeypatch.setattr(A, "remaining_today", lambda platform, profiles=None: 10)
    monkeypatch.setattr(A, "pending_count", lambda platform=None: 0)
    monkeypatch.setattr(A, "free_channels", lambda platform, profiles=None: 10)
    monkeypatch.setattr(A, "per_cycle_cap", lambda min_n=0: 10)
    monkeypatch.setattr(A, "free_images", lambda prof, platform: None)
    monkeypatch.setattr(A, "stock_target", lambda prof, platform: 14)
    monkeypatch.setattr(A, "stock_count", lambda prof, platform: 0)


def test_do_generate_runs_with_real_budget_after_a_day_of_creatives(
        monkeypatch, temp_db):
    """하루치 소재가 이미 쌓여 있어도, 그림을 만든 적이 없으면 생성은 계속된다.

    고치기 전에는 db.images_made_today() 가 **creatives 행**을 세어 소재 몇 건
    만에 예산이 0 이 됐고, need 가 음수가 되어 그날의 생성이 통째로 멈췄다
    (실측 DB 는 가동일 하루 130~290건을 만든다 — 천장 2 는 즉시 걸린다).
    remaining_image_budget 을 갈아끼우지 않고 진짜 값으로 돌린다.
    """
    import config
    import auto_loop as A

    budget = config.image_daily_budget()
    assert budget > 0, "기본 설정의 하루 천장이 0 이면 이 테스트가 의미를 잃는다"
    # 예전 분모를 확실히 넘긴다 — 옛 코드라면 여기서 예산이 0 이 된다.
    _seed_creatives(budget + 3)

    # 예산 천장이 실제로 need 를 조이는 상태에서 본다(생성 잠금 해제).
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", False, raising=False)
    logs = []
    _stub_platform_math(monkeypatch, A, logs)

    A.do_generate({"printcraft"}, dry=True)

    joined = "\n".join(str(m) for m in logs)
    assert f"오늘 예산 {budget}" in joined, \
        f"소재만 쌓였을 뿐 그림은 한 장도 안 만들었으니 예산은 {budget} 그대로여야 한다: {joined}"
    assert any("printcraft:" in m and "건 생성" in m for m in logs), \
        f"재고가 비어 있는 업종은 계속 만들어야 한다: {joined}"


def test_reuse_only_cycle_is_not_capped_by_the_image_budget(monkeypatch, temp_db):
    """예산을 다 쓴 뒤에도 '재사용만 하는 주기' 는 계속 돈다.

    IMAGE_GEN_LOCKED=1 은 2026-08-14 운영자 지시로 켜져 있는 실제 운영 상태다.
    그 상태에서는 _gen_one 이 아예 막혀 있어 이번 주기가 그림을 한 장도
    만들 수 없다 — 그런 주기까지 '이미지 생성 천장' 으로 조이면, 돈 한 푼
    안 드는 재고 순환 발행까지 함께 멈춘다.
    """
    import config
    import auto_loop as A

    db.note_image_generated(config.image_daily_budget() + 5)   # 천장 소진
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", True, raising=False)
    logs = []
    _stub_platform_math(monkeypatch, A, logs)

    A.do_generate({"printcraft"}, dry=True)

    joined = "\n".join(str(m) for m in logs)
    assert any("printcraft:" in m and "건 생성" in m for m in logs), \
        f"생성이 잠긴 주기는 재고로 도는 중이라 예산에 막히면 안 된다: {joined}"
