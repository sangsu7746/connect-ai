# ============================================================
#  stats.py — 운영 대시보드 집계
#  ⚠ 전환 계산 주의사항
#   · posts.status: dry(모의) | queued | posted(실발행) | failed
#     → "발행"으로 세는 건 posted 뿐. dry 를 섞으면 전환율이 거짓이 된다.
#   · consumers.source_channel 형식은 "{platform}_{channel_id}" (orchestrator.intake_url)
#     → 채널 매칭은 문자열 파싱이 아니라 이 규칙으로 정확히 대조한다.
# ============================================================
from datetime import datetime, timedelta

import db

REAL_POST = "posted"          # 실제로 나간 것만 발행으로 집계


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _days_ago(n: int) -> str:
    return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")


def _scalar(conn, sql, args=()) -> int:
    row = conn.execute(sql, args).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _blocked_top(conn, since: str) -> str:
    """최근 차단 중 가장 많은 사유 한 줄. 없으면 빈 문자열.
    posts.error 가 없는 예전 행도 있으므로 조용히 넘어간다."""
    try:
        rows = conn.execute(
            "SELECT error, COUNT(*) n FROM posts "
            "WHERE status='blocked' AND substr(created_at,1,10)>=? "
            "GROUP BY error ORDER BY n DESC LIMIT 1", (since,)).fetchall()
    except Exception:
        return ""
    if not rows or not rows[0][0]:
        return ""
    msg = str(rows[0][0])
    return (msg[:60] + "…") if len(msg) > 60 else msg


def channel_key(platform: str, channel_id) -> str:
    """광고 링크에 실리는 유입 식별자. orchestrator.intake_url 과 반드시 동일 규칙."""
    return f"{platform}_{channel_id}"


# ── 요약 카드 ───────────────────────────────────────────────
def summary() -> dict:
    today, week = _today(), _days_ago(7)
    with db.get_conn() as c:
        return {
            "pending_approvals": _scalar(c, "SELECT COUNT(*) FROM approvals WHERE state='pending'"),
            "channels_enabled": _scalar(c, "SELECT COUNT(*) FROM channels WHERE enabled=1"),
            "channels_total": _scalar(c, "SELECT COUNT(*) FROM channels"),
            "posted_today": _scalar(c,
                "SELECT COUNT(*) FROM posts WHERE status=? AND substr(COALESCE(posted_at,created_at),1,10)=?",
                (REAL_POST, today)),
            "posted_week": _scalar(c,
                "SELECT COUNT(*) FROM posts WHERE status=? AND substr(COALESCE(posted_at,created_at),1,10)>=?",
                (REAL_POST, week)),
            "dry_week": _scalar(c,
                "SELECT COUNT(*) FROM posts WHERE status='dry' AND substr(created_at,1,10)>=?", (week,)),
            # 실제 발행 실패 — 안전장치 차단(blocked)과 분리해야 오진하지 않는다
            "failed_week": _scalar(c,
                "SELECT COUNT(*) FROM posts WHERE status='failed' AND substr(created_at,1,10)>=?", (week,)),
            "blocked_week": _scalar(c,
                "SELECT COUNT(*) FROM posts WHERE status='blocked' AND substr(created_at,1,10)>=?", (week,)),
            # 가장 흔한 차단 사유. 건수만 보여주면 '상한 도달'인지 '세션 만료'인지
            # 알 수 없어 고칠 수가 없다.
            "blocked_top": _blocked_top(c, week),
            # 발행 시작 후 결과가 기록되지 않은 것(중단·예외로 멈춘 흔적) — 조용히 사라지면 안 된다
            "stuck_week": _scalar(c,
                "SELECT COUNT(*) FROM posts WHERE status='queued' AND substr(created_at,1,10)>=?", (week,)),
            "leads_today": _scalar(c,
                "SELECT COUNT(*) FROM consumers WHERE substr(created_at,1,10)=?", (today,)),
            "leads_week": _scalar(c,
                "SELECT COUNT(*) FROM consumers WHERE substr(created_at,1,10)>=?", (week,)),
            "leads_total": _scalar(c, "SELECT COUNT(*) FROM consumers"),
        }


# ── 채널별 성과 (발행 → 접수 전환) ──────────────────────────
def channel_performance(days: int = 30) -> list:
    """활성/비활성 무관 전 채널. posted 만 발행으로 집계."""
    since = _days_ago(days)
    out = []
    with db.get_conn() as c:
        channels = [dict(r) for r in c.execute(
            "SELECT id, platform, name, audience, enabled FROM channels ORDER BY platform, id")]
        for ch in channels:
            posted = _scalar(c,
                "SELECT COUNT(*) FROM posts WHERE channel_id=? AND status=? "
                "AND substr(COALESCE(posted_at,created_at),1,10)>=?",
                (ch["id"], REAL_POST, since))
            dry = _scalar(c,
                "SELECT COUNT(*) FROM posts WHERE channel_id=? AND status='dry' "
                "AND substr(created_at,1,10)>=?", (ch["id"], since))
            key = channel_key(ch["platform"], ch["id"])
            leads = _scalar(c,
                "SELECT COUNT(*) FROM consumers WHERE source_channel=? AND substr(created_at,1,10)>=?",
                (key, since))
            out.append({
                **ch,
                "key": key,
                "posted": posted,
                "dry": dry,
                "leads": leads,
                # 전환율: 실발행이 없으면 정의되지 않음(0으로 위장하지 않는다)
                "conversion": (round(leads / posted * 100, 1) if posted else None),
            })
    # 접수 많은 순 → 발행 많은 순
    out.sort(key=lambda r: (r["leads"], r["posted"]), reverse=True)
    return out


def unattributed_leads(days: int = 30) -> int:
    """유입 채널이 비었거나 등록된 채널과 매칭되지 않는 접수(직접 방문·수동 배포 등)."""
    since = _days_ago(days)
    with db.get_conn() as c:
        known = {channel_key(r["platform"], r["id"])
                 for r in c.execute("SELECT id, platform FROM channels")}
        rows = c.execute(
            "SELECT source_channel FROM consumers WHERE substr(created_at,1,10)>=?", (since,)).fetchall()
    return sum(1 for r in rows if not (r["source_channel"] or "").strip() or r["source_channel"] not in known)


# ── 최근 접수 (연락처는 마스킹) ─────────────────────────────
def mask_phone(p: str) -> str:
    """⚠ 앞3+뒤4 방식은 7~8자리 번호에서 원본이 그대로 드러난다(3+4=7).
    자릿수에 따라 가리는 양을 보장한다."""
    d = "".join(ch for ch in str(p or "") if ch.isdigit())
    if len(d) < 5:
        return "***"
    if len(d) >= 10:                      # 휴대폰/지역번호 포함 — 관례대로 뒤 4자리
        return f"{d[:3]}-****-{d[-4:]}"
    # 5~9자리(지역번호 없는 유선 등): 뒤 2자리만 노출
    return "*" * (len(d) - 2) + d[-2:]


def recent_leads(limit: int = 12) -> list:
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT name, phone, amount, collateral, source_channel, utm, created_at "
            "FROM consumers ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["phone"] = mask_phone(d.get("phone"))
        d["created_at"] = (d.get("created_at") or "")[:16].replace("T", " ")
        out.append(d)
    return out


def recent_posts(limit: int = 12) -> list:
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT p.id, p.status, p.posted_at, p.created_at, ch.name AS channel, ch.platform "
            "FROM posts p LEFT JOIN channels ch ON p.channel_id=ch.id "
            "ORDER BY p.id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["at"] = ((d.get("posted_at") or d.get("created_at") or "")[:16]).replace("T", " ")
        out.append(d)
    return out


# ── 준비 상태 (지금 어디까지 됐나 / 뭐가 막혀 있나) ────────
_READY_CACHE = {"at": 0.0, "val": None}


def _reachable(url: str, timeout: float = 1.0) -> bool:
    try:
        import requests
        return requests.get(url, timeout=timeout).status_code < 500
    except Exception:
        return False


def readiness(ttl: float = 30.0) -> dict:
    """대시보드에 띄우는 준비 상태. 외부 확인이 섞여 있어 짧게 캐시한다."""
    import time as _t
    if _READY_CACHE["val"] and (_t.time() - _READY_CACHE["at"]) < ttl:
        return _READY_CACHE["val"]

    import subprocess
    from pathlib import Path
    import config

    items = []

    def add(name, ok, detail, todo="", warn=False):
        items.append({"name": name, "state": ("ok" if ok else ("warn" if warn else "todo")),
                      "detail": detail, "todo": todo})

    # 1) 카피 생성
    key = config.GEMINI_API_KEY if config.COPY_PROVIDER == "gemini" else config.ANTHROPIC_API_KEY
    model = config.COPY_MODEL_GEMINI if config.COPY_PROVIDER == "gemini" else config.COPY_MODEL
    add("카피 생성", bool(key), f"{config.COPY_PROVIDER} · {model}",
        f"{config.COPY_PROVIDER.upper()} 키를 .env 에 설정하세요")

    # 2) 팜플렛 전단
    try:
        from content import registry
        n = len([p for p in registry.products() if p.get("flyer")])
        add("광고 전단", n > 0, f"{n}종 사용 가능", "전단 이미지를 content/templates/flyers 에 넣으세요")
    except Exception as e:
        add("광고 전단", False, f"불러오기 실패: {e}", "content/registry.py 확인")

    # 3) 접수 링크 공개
    local = any(h in config.PUBLIC_BASE for h in ("127.0.0.1", "localhost"))
    add("접수 링크 공개", not local, config.PUBLIC_BASE,
        "PUBLIC_BASE 를 외부 주소로 바꾸세요(광고 링크가 죽습니다)")

    # 4) 대출앱 연결
    loan_ok = _reachable(config.LOAN_API_BASE + "/api/loans")
    add("대출앱 연결", loan_ok, config.LOAN_API_BASE + ("  응답" if loan_ok else "  응답 없음"),
        "python service.py 로 대출앱을 함께 띄우세요")

    # 4-1) 접수 회수(동기화) 생존 — 이게 죽으면 손님이 접수해도 아무 일도 안 일어난다.
    #      화면상 다른 항목은 다 초록불이라 조용한 실패가 되기 쉬워 별도 항목으로 뺀다.
    try:
        import json as _json
        from datetime import datetime as _dt
        hb = Path(config.DATA_DIR) / "sync_heartbeat.json"
        if not hb.exists():
            add("접수 회수 동기화", False, "아직 한 번도 돌지 않음",
                "python service.py 로 cloud_sync 를 함께 띄우세요")
        else:
            h = _json.loads(hb.read_text(encoding="utf-8"))
            age = (_dt.now() - _dt.fromisoformat(h["at"])).total_seconds()
            streak = int(h.get("fail_streak", 0))
            ok_at = h.get("last_pull_ok")
            pull_age = ((_dt.now() - _dt.fromisoformat(ok_at)).total_seconds()
                        if ok_at else None)
            # 프로세스가 살아 있어도 수신함 조회가 계속 실패하면 리드는 한 건도 안 들어온다.
            # 그 상태를 초록불로 두면 클라우드에만 리드가 쌓이고 아무도 모른다.
            if age >= 900:
                add("접수 회수 동기화", False, f"{int(age // 60)}분째 멈춤",
                    "data/logs/sync.log 를 확인하세요")
            elif streak >= 3 or pull_age is None or pull_age >= 1800:
                last = f"{int(pull_age // 60)}분 전" if pull_age is not None else "없음"
                add("접수 회수 동기화", False,
                    f"돌고는 있으나 회수 실패 {streak}회 연속 (마지막 성공 {last})",
                    f"{h.get('last_error', '')[:80] or 'LEAD_PULL_TOKEN·네트워크 확인'}")
            else:
                add("접수 회수 동기화", True, f"{int(age // 60)}분 전 정상 회수")
    except Exception as e:
        add("접수 회수 동기화", False, f"확인 실패: {e}", "data/sync_heartbeat.json 확인")

    # 4-2) 대출앱에 못 들어간 리드
    try:
        stuck = db.stuck_consumers()
        pend = db.pending_consumers(limit=500)
        n = len(pend) + len(stuck)
        add("미등록 리드", n == 0,
            "없음" if n == 0 else f"{n}건 대출앱 미등록"
                                 + (f" (재시도 포기 {len(stuck)}건)" if stuck else ""),
            "대출앱이 떠 있는지 확인하세요 — 자동 재시도 중입니다",
            warn=(n > 0 and not stuck))
    except Exception as e:
        add("미등록 리드", False, f"확인 실패: {e}", "db.py 마이그레이션 확인")

    # 5) 발행 채널
    chans = list_channels_safe()
    on = [c for c in chans if c.get("enabled")]
    add("발행 채널", len(on) > 0, f"활성 {len(on)}개 / 등록 {len(chans)}개",
        "register_channels.py 로 등록 후 광고할 채널만 켜세요")

    # 6) 로그인 세션
    # ⚠ '쿠키가 아무거나 있다'로 판정하면 안 된다. 발행 때 열리는 파일은 계정 이름으로
    #   정해지므로, 다른 계정 쿠키가 있어도 발행은 전건 실패한다(초록불인데 0건 발행).
    try:
        for plat, label, acc in (("band", "밴드 로그인", config.BAND_ACCOUNT),
                                 ("facebook", "페북 로그인", config.FACEBOOK_ACCOUNT)):
            if not acc:
                add(label, False, "계정 미설정",
                    f".env 에 {plat.upper()}_ACCOUNT= 를 넣으세요(login.py --account 와 동일)")
                continue
            p = config.cookie_path(plat, acc)
            if p is None or not p.exists():
                add(label, False, f"{acc} · 세션 파일 없음",
                    f"python login.py {plat} --account {acc}")
                continue
            age = (_t.time() - p.stat().st_mtime) / 86400
            fresh = age <= 14
            add(label, fresh, f"{acc} · {age:.0f}일 전",
                f"오래돼 만료됐을 수 있습니다 — python login.py {plat} --account {acc}",
                warn=not fresh)
    except Exception:
        add("로그인 세션", False, "확인 실패", "python login.py --check")

    # 7) 자동 시작 — 작업 스케줄러 또는 시작프로그램 폴더 어느 쪽이든 인정한다.
    #    (관리자 권한이 없는 PC 에서는 시작프로그램 폴더로만 등록된다)
    try:
        import service as _svc
        reg = _svc.startup_registered()
        how = "등록됨" if reg else "등록 안 됨 — PC를 껐다 켜면 접수 회수가 멈춥니다"
    except Exception:
        reg, how = False, "확인 실패"
    add("자동 시작", reg, how, "python service.py --install")

    ok_n = sum(1 for i in items if i["state"] == "ok")
    val = {"items": items, "ok": ok_n, "total": len(items),
           "dry_run": config.GLOBAL_DRY_RUN}
    _READY_CACHE.update({"at": _t.time(), "val": val})
    return val


def list_channels_safe() -> list:
    try:
        with db.get_conn() as c:
            return [dict(r) for r in c.execute("SELECT id, enabled FROM channels")]
    except Exception:
        return []


def dashboard(days: int = 30) -> dict:
    import config
    return {
        "brand": config.BRAND_COMPANY,
        "profile": config.PROFILE_NAME,
        "profile_key": config.PROFILE_KEY,
        "dry_run": config.GLOBAL_DRY_RUN,
        "copy_provider": config.COPY_PROVIDER,
        "public_base": config.PUBLIC_BASE,
        "daily_limit": config.DAILY_POST_LIMIT,
        "days": days,
        "readiness": readiness(),
        "summary": summary(),
        "channels": channel_performance(days),
        "unattributed": unattributed_leads(days),
        "recent_leads": recent_leads(),
        "recent_posts": recent_posts(),
    }
