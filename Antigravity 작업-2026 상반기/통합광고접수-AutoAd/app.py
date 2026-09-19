# ============================================================
#  app.py — AutoAd 웹 서버 (FastAPI)
#  · 소비자 접수폼 + /api/intake/lead → bridge → 대출앱 register
#  · (향후) 승인 대시보드/웹훅 라우트도 여기에
#  실행: python -m uvicorn app:app --port 8010
# ============================================================
import re
import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
import db
import approval
import scheduler
from intake import bridge

db.init_db()


def _guard_bind():
    """⚠ 이 서버는 인증이 없고 /api/dashboard 는 접수자 개인정보(이름·연락처)를 반환한다.
    외부 바인딩(0.0.0.0 등)은 사고이므로 기동을 막는다.
    의도적으로 열어야 한다면 .env 에 ALLOW_PUBLIC_BIND=1 (권장하지 않음)."""
    import os
    if os.getenv("ALLOW_PUBLIC_BIND", "").strip() == "1":
        return
    argv = " ".join(sys.argv)
    host = os.getenv("UVICORN_HOST", "")
    m = re.search(r"--host[= ]+(\S+)", argv)
    if m:
        host = m.group(1)
    if host and host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(
            f"외부 바인딩 차단: --host {host}\n"
            "  이 서버는 인증이 없고 개인정보를 반환합니다. 127.0.0.1 로 실행하세요.\n"
            "  소비자용 공개 창구는 Firebase(headjim-loan.web.app)입니다.\n"
            "  그래도 열어야 한다면 .env 에 ALLOW_PUBLIC_BIND=1 (권장하지 않음)."
        )


@asynccontextmanager
async def lifespan(_app):
    # 서버와 함께 예약 스케줄러 기동/종료 → uvicorn app:app 하나로 상주
    _guard_bind()
    db.init_db()
    scheduler.start()
    print("[AutoAd] 서버·스케줄러 기동 (로컬 전용)")
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="AutoAd 통합 광고·접수 API", lifespan=lifespan)
INTAKE_DIR = Path(__file__).parent / "intake"
UI_DIR = Path(__file__).parent / "ui"


class LeadModel(BaseModel):
    name: str
    phone: str
    amount: str = ""
    collateral: str = ""
    consent: bool = False
    source_channel: str = ""
    utm: str = ""


def _dump(model) -> dict:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


@app.get("/")
def root():
    return {
        "service": "AutoAd",
        "brand": config.BRAND_COMPANY,
        "loan_api": config.LOAN_API_BASE,
        "endpoints": ["/intake", "POST /api/intake/lead", "/approvals", "/api/approvals"],
    }


# ── 승인 대시보드 (P1-6) ─────────────────────────────────────
class DecideModel(BaseModel):
    decision: str            # approved | rejected | edited
    note: str = ""
    reviewer: str = "operator"


@app.get("/dashboard")
def dashboard_page():
    """운영 대시보드 — 채널상태·발행·승인대기·접수·전환율."""
    return FileResponse(str(UI_DIR / "dashboard.html"))


@app.get("/api/dashboard")
def api_dashboard(days: int = 30):
    import stats
    return stats.dashboard(days=max(1, min(days, 365)))


@app.get("/approvals")
def approvals_page():
    """웹 승인 콘솔(전단 사진+캡션 보고 승인/거절/수정)."""
    return FileResponse(str(UI_DIR / "approvals.html"))


@app.get("/api/approvals")
def api_approvals():
    return approval.pending()


@app.post("/api/approvals/{approval_id}/decide")
def api_decide(approval_id: int, payload: DecideModel):
    try:
        return approval.decide(approval_id, payload.decision, payload.reviewer, payload.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/creatives/{name}")
def creative_image(name: str):
    """승인 대시보드용 크리에이티브 이미지 서빙(경로 traversal 차단)."""
    p = config.CREATIVES_DIR / Path(name).name
    if not p.exists():
        raise HTTPException(status_code=404, detail="이미지 없음")
    return FileResponse(str(p))


@app.get("/intake")
def intake_form():
    """소비자 접수폼(개인정보 동의 포함)."""
    return FileResponse(str(INTAKE_DIR / "form.html"))


@app.post("/api/intake/lead")
def intake_lead(payload: LeadModel):
    """
    소비자 접수 → consumers 저장 → 대출앱 /api/intake/register 로 브릿지.
    ⚠ 동의 없으면 거부. 주민번호는 애초에 폼/모델에 없음.
    """
    if not payload.consent:
        raise HTTPException(status_code=400, detail="개인정보 수집·이용 동의가 필요합니다.")
    try:
        result = bridge.submit_lead(_dump(payload))
        return {"ok": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"대출접수 연결 실패: {e}")
