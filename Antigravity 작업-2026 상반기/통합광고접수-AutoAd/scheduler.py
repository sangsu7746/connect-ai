# ============================================================
#  scheduler.py — 예약 발행  (P1-7)
#  · APScheduler + SQLAlchemyJobStore(sqlite) → 앱 재시작에도 예약 복구
#  · 승인된 크리에이티브만 예약 가능
#  · 발행 콜백은 top-level 함수(_publish_job) — 영속 jobstore 역직렬화용
#  참고 재사용: 페이스북-광고글/app/scheduler.py (once/daily/weekly/monthly)
# ============================================================
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

import config

TZ = ZoneInfo(config.TIMEZONE)
JOBSTORE_URL = f"sqlite:///{(config.DATA_DIR / 'scheduler.db').as_posix()}"

_SCHED = None


def get_scheduler() -> BackgroundScheduler:
    global _SCHED
    if _SCHED is None:
        _SCHED = BackgroundScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=JOBSTORE_URL)},
            timezone=TZ,
            job_defaults={"misfire_grace_time": 3600, "coalesce": True},
        )
    return _SCHED


def start() -> BackgroundScheduler:
    s = get_scheduler()
    if not s.running:
        s.start()
    return s


def shutdown(wait: bool = False):
    global _SCHED
    if _SCHED is not None and _SCHED.running:
        _SCHED.shutdown(wait=wait)
    _SCHED = None


# ── 발행 콜백 (top-level — jobstore 역직렬화 가능해야 함) ────
def _publish_job(creative_id: int, dry_run=None):
    import orchestrator          # 지연 import (순환 회피)
    orchestrator.publish_creative(creative_id, dry_run=dry_run)


def run_scheduled_campaign(campaign_id: int, copy_fn_ref=None):
    """주기 캠페인용 top-level 러너(예: 매일 09시). 저장된 캠페인을 다시 실행.
    ※ 실 카피는 크레딧 필요 → 실패 시 orchestrator가 폴백 캡션 사용."""
    import db, orchestrator
    with db.get_conn() as conn:
        r = conn.execute("SELECT title, goal, product FROM campaigns WHERE id=?",
                         (campaign_id,)).fetchone()
    if not r:
        return
    orchestrator.run_campaign({"title": r["title"], "goal": r["goal"],
                               "product": r["product"]})


# ── 예약 API ────────────────────────────────────────────────
def schedule_publish(creative_id: int, run_at: datetime, dry_run=None):
    """승인된 크리에이티브를 run_at 에 발행 예약(재시작 복구됨)."""
    import db
    with db.get_conn() as conn:
        r = conn.execute("SELECT approved FROM creatives WHERE id=?",
                         (creative_id,)).fetchone()
    if not r:
        raise ValueError(f"크리에이티브 없음: {creative_id}")
    if not r["approved"]:
        raise ValueError(f"미승인 크리에이티브는 예약 불가: {creative_id}")
    s = get_scheduler()
    return s.add_job(_publish_job, "date", run_date=run_at,
                     args=[creative_id, dry_run], id=f"pub-{creative_id}",
                     replace_existing=True)


def schedule_recurring_campaign(campaign_id: int, hour: int = 9, minute: int = 0,
                                day_of_week=None):
    """주기 캠페인 예약(기본 매일 09:00 KST). day_of_week='mon-fri' 등 지정 가능."""
    s = get_scheduler()
    trig = {"hour": hour, "minute": minute}
    if day_of_week:
        trig["day_of_week"] = day_of_week
    return s.add_job(run_scheduled_campaign, "cron", args=[campaign_id],
                     id=f"camp-{campaign_id}", replace_existing=True, **trig)


def cancel(job_id: str):
    try:
        get_scheduler().remove_job(job_id)
        return True
    except Exception:
        return False


def list_jobs() -> list:
    out = []
    for j in get_scheduler().get_jobs():
        out.append({
            "id": j.id,
            "next_run": j.next_run_time.strftime("%Y-%m-%d %H:%M:%S %Z") if j.next_run_time else None,
            "args": list(j.args),
        })
    return out
