# ============================================================
#  cloud_sync.py — 클라우드 수신함 → 대출앱 동기화  (사무실 PC에서 실행)
#  흐름: loanIntakePull(미처리 리드 가져오기) → consumers 저장 → 대출앱 register
#  · PC가 꺼져 있어도 리드는 Firestore에 안전하게 쌓이고, 켜지면 이 스크립트가 회수.
#  · 서비스계정 키 불필요 — LEAD_PULL_TOKEN(공유 비밀)만 사용.
#  실행: python cloud_sync.py          (1회 동기화)
#        python cloud_sync.py --watch  (주기 반복)
# ============================================================
import sys
import io
import time
import argparse

import requests

import config
import db
import singleton
from intake import bridge


# 감독기와 약속된 종료코드 — '중복이라 비켰다'(실패가 아님). service.py 가 이 값을 본다.
EXIT_ALREADY_RUNNING = 3

# pull 원본 보관함. 클라우드는 가져가는 즉시 pulled 로 마킹해 재수신이 불가능하므로,
# 등록 도중 프로세스가 강제 종료되면 남은 리드가 영영 사라진다. 이 파일이 마지막 복구 수단.
RAW_DIR = config.DATA_DIR / "leads_raw"


def _archive(leads: list) -> str:
    """pull 한 원본을 등록 전에 먼저 디스크에 남긴다."""
    if not leads:
        return ""
    try:
        import json
        from datetime import datetime as _dt
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        p = RAW_DIR / f"{_dt.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        p.write_text(json.dumps(leads, ensure_ascii=False, indent=1), encoding="utf-8")
        return str(p)
    except Exception as e:
        # 보관 실패가 회수를 막아선 안 되지만, 반드시 눈에 띄게 남긴다.
        print(f"[sync] ⚠ 원본 보관 실패({type(e).__name__}: {e}) — "
              f"이 회차는 중간에 끊기면 복구 불가")
        return ""


def pull(limit: int = 50) -> list:
    """클라우드 수신함에서 미처리 리드를 가져온다(가져간 즉시 pulled 처리됨)."""
    if not config.LEAD_PULL_URL or not config.LEAD_PULL_TOKEN:
        raise RuntimeError("LEAD_PULL_URL / LEAD_PULL_TOKEN 미설정 — .env 확인")
    r = requests.get(
        config.LEAD_PULL_URL,
        params={"limit": limit},
        headers={"Authorization": f"Bearer {config.LEAD_PULL_TOKEN}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("leads", [])


def _to_local_iso(z):
    """클라우드의 UTC ISO('...Z') → 로컬 naive ISO.
    로컬 폼 경유 행(datetime.now().isoformat())과 같은 체계로 맞춰야
    stats 의 날짜 비교(_today/_days_ago 는 로컬 기준)가 어긋나지 않는다."""
    if not z:
        return None
    try:
        from datetime import datetime as _dt
        return (_dt.fromisoformat(str(z).replace("Z", "+00:00"))
                .astimezone().replace(tzinfo=None).isoformat())
    except Exception:
        return None          # 파싱 실패 시 현재 시각으로 안전 폴백


def ack(ids: list) -> bool:
    """처리가 끝난 리드를 클라우드에 '확인'시켜 재배달 목록에서 뺀다.

    ⚠ 반드시 _archive() 로 원본을 남긴 뒤에 부를 것.
      확인이 먼저 가면 그 뒤 죽었을 때 리드가 복구 불가로 사라진다.
    확인이 실패해도 문제 없다 — 클라우드가 나중에 다시 배달하고,
    받는 쪽은 cloud_id 로 이미 처리한 건임을 알아본다."""
    if not ids:
        return True
    url = (config.LEAD_ACK_URL or "").strip()
    if not url:
        return False          # 구버전 클라우드(확인 없이 즉시 확정) — 부를 곳이 없다
    try:
        r = requests.post(url, json={"ids": list(ids)},
                          headers={"Authorization": f"Bearer {config.LEAD_PULL_TOKEN}"},
                          timeout=30)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[sync] 확인 응답 실패({type(e).__name__}: {e}) — "
              f"클라우드가 나중에 재배달합니다(중복은 걸러집니다)")
        return False


def push(lead: dict) -> dict:
    """리드 1건을 대출앱에 접수 등록 (consumers 저장 + register 호출).
    ⚠ created_at 은 '실제 접수 시각'을 넘긴다. 안 넘기면 PC 동기화 시각으로 기록되어
      주말에 쌓인 리드가 전부 월요일 접수로 집계된다."""
    at = _to_local_iso(lead.get("created_at"))
    return bridge.submit_lead({
        "name": lead.get("name", ""),
        "phone": lead.get("phone", ""),
        "amount": lead.get("amount", ""),
        "collateral": lead.get("collateral", ""),
        "consent": True,                       # 폼에서 동의 없으면 저장 자체가 안 됨
        "source_channel": lead.get("source_channel", ""),
        "utm": lead.get("utm", ""),
        "created_at": at,
        "consent_at": _to_local_iso(lead.get("consent_at")) or at,
        "cloud_id": lead.get("id"),            # 재배달돼도 같은 건으로 알아보게
    })


def sync_once(limit: int = 50) -> tuple:
    """반환: (등록건수, 수신함_조회_성공여부, 오류문구)

    조회 성공/실패를 반드시 구분해서 올린다. 뭉뚱그리면 '한 건도 못 받는 상태'와
    '받을 게 없는 상태'가 화면에서 똑같아 보인다."""
    db.init_db()
    try:
        leads = pull(limit)
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"[sync] 수신함 조회 실패: {msg}")
        # 확인 응답 방식이면 못 받은 리드는 잠시 뒤 다시 배달된다.
        return 0, False, msg
    if not leads:
        print("[sync] 새 접수 없음")
        return 0, True, ""

    # ★ 등록보다 먼저 원본을 남긴다. 여기서 죽어도 리드는 파일로 남는다.
    raw = _archive(leads)
    if raw:
        print(f"[sync] 원본 {len(leads)}건 보관 → {raw}")

    # 원본을 확보한 뒤에야 클라우드에 '받았다'고 알린다.
    # 이 순서가 뒤집히면 확인 직후 죽었을 때 리드가 복구 불가로 사라진다.
    ack([ld.get("id") for ld in leads if ld.get("id")])

    done = 0
    for ld in leads:
        # 재배달된 리드는 이미 consumers 에 있다 — 새 접수로 만들지 않는다.
        already = db.consumer_by_cloud_id(ld.get("id"))
        if already:
            print(f"[sync] 재배달 무시 · {ld.get('name')} (이미 받은 리드 #{already['id']})")
            continue
        try:
            res = push(ld)
            if res.get("pending"):
                print(f"[sync] 보류 · {ld.get('name')} — 리드는 저장됨, 대출앱 전달은 재시도 예정")
                continue
            print(f"[sync] 등록 완료 · {ld.get('name')} / {ld.get('amount') or '-'} "
                  f"/ 유입 {ld.get('source_channel') or '-'} → loan_id={res.get('loan_id')}")
            done += 1
        except Exception as e:
            # bridge.submit_lead 는 register 호출 **전에** consumers 에 커밋한다.
            # 따라서 등록 실패해도 리드는 이미 로컬에 남아 있다.
            # 여기서 다시 add_consumer 하면 같은 리드가 2행이 되어 접수·전환 지표가 부풀려진다.
            print(f"[sync] 대출앱 등록 실패({type(e).__name__}) · {ld.get('name')} "
                  f"— 리드는 로컬 consumers 에 보관됨(중복저장 안 함): {e}")
    print(f"[sync] {done}/{len(leads)}건 대출앱 등록")
    return done, True, ""


def retry_pending(limit: int = 50) -> int:
    """대출앱 등록에 실패한 리드를 다시 시도한다.

    대출앱이 꺼져 있거나 일시적 오류로 실패한 리드는 consumers 에 registered=0 으로
    남는다. 재시도가 없으면 그 리드는 영영 대출앱에 들어가지 않는다 —
    손님은 접수했다고 믿고 기다리는데 사장님은 존재 자체를 모른다."""
    rows = db.pending_consumers(limit=limit)
    if not rows:
        return 0
    print(f"[sync] 미등록 리드 {len(rows)}건 재시도")
    ok = 0
    for r in rows:
        form = {
            "name": r.get("name", ""), "phone": r.get("phone", ""),
            "amount": r.get("amount", ""), "collateral": r.get("collateral", ""),
            "source_channel": r.get("source_channel", ""), "utm": r.get("utm", ""),
            "created_at": r.get("created_at"),
        }
        try:
            db.mark_consumer_attempting(r["id"])
            res = bridge.register(r["id"], form)
            print(f"[sync] 재시도 성공 · {r.get('name')} → loan_id={res.get('loan_id')}")
            ok += 1
        except Exception as e:
            print(f"[sync] 재시도 실패({type(e).__name__}) · {r.get('name')} "
                  f"(누적 {r.get('retry_count', 0) + 1}회): {e}")
    stuck = db.stuck_consumers()
    if stuck:
        print(f"[sync] ⚠ 재시도 상한 초과 {len(stuck)}건 — 사람이 직접 확인해야 합니다: "
              + ", ".join(f"#{s['id']} {s.get('name', '')}" for s in stuck[:10]))
    return ok


HEARTBEAT = config.DATA_DIR / "sync_heartbeat.json"


def _beat(pull_ok: bool, error: str = ""):
    """생존 신호. '프로세스가 돌고 있음'과 '수신함을 실제로 읽었음'을 나눠 적는다.

    ⚠ 둘을 합치면, 토큰 만료 등으로 회수가 100% 실패하는 중에도 대시보드는
      계속 초록불로 보인다. 리드가 클라우드에만 쌓이는데 아무도 모른다."""
    import json as _json
    from datetime import datetime as _dt
    prev = {}
    try:
        prev = _json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except Exception:
        pass
    now = _dt.now().isoformat()
    data = {
        "at": now,
        "last_pull_ok": now if pull_ok else prev.get("last_pull_ok"),
        "fail_streak": 0 if pull_ok else int(prev.get("fail_streak", 0)) + 1,
        "last_error": "" if pull_ok else (error or prev.get("last_error", "")),
    }
    try:
        HEARTBEAT.write_text(_json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def pull_clicks(limit: int = 500) -> int:
    """광고 링크 클릭 기록을 회수해 소재별 성과에 반영한다.

    클릭은 접수보다 훨씬 자주 발생하는 신호라, 문구·이미지 조정의 근거가 된다.
    회수 실패는 치명적이지 않다(다음 회차에 다시 가져온다)."""
    url = (config.AD_CLICK_PULL_URL or "").strip()
    if not url or not config.LEAD_PULL_TOKEN:
        return 0
    try:
        r = requests.get(url, params={"limit": limit},
                         headers={"Authorization": f"Bearer {config.LEAD_PULL_TOKEN}"},
                         timeout=30)
        r.raise_for_status()
        clicks = r.json().get("clicks", [])
    except Exception as e:
        print(f"[sync] 클릭 회수 실패({type(e).__name__}: {e})")
        return 0
    if not clicks:
        return 0
    ok = 0
    for c in clicks:
        if db.add_click(c.get("creative_id") or ""):
            ok += 1
    print(f"[sync] 클릭 {len(clicks)}건 회수 · {ok}건 소재에 반영")
    return ok


def cycle(limit: int = 50) -> int:
    """한 바퀴 = 새 리드 회수 + 실패분 재시도 + 클릭 회수 + 생존 신호."""
    done, pull_ok, err = sync_once(limit)
    done += retry_pending(limit)
    try:
        pull_clicks()
    except Exception as e:
        print(f"[sync] 클릭 회수 중 오류({type(e).__name__}) — 계속 진행")
    _beat(pull_ok, err)
    return done


def main():
    # 콘솔 한글 깨짐 방지 — 스크립트로 실행될 때만 적용(모듈 임포트 시 부작용 없음)
    # line_buffering=True: 파일로 리다이렉트돼도 한 줄씩 즉시 기록된다.
    # (없으면 감독기가 남기는 sync.log 가 몇 시간이고 빈 파일로 남는다 — 2026-07-31 확인)
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      line_buffering=True)
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true", help="주기 반복 실행")
    ap.add_argument("--interval", type=int, default=180, help="반복 간격(초)")
    ap.add_argument("--limit", type=int, default=50)
    a = ap.parse_args()

    # 두 벌이 돌면 같은 리드를 두 번 회수·등록해 손님에게 두 번 전화하게 된다.
    # 1회 실행(--watch 없음)도 감시 모드와 겹치면 안 되므로 똑같이 막는다.
    try:
        singleton.acquire("cloud_sync")
    except singleton.AlreadyRunning as e:
        print(f"[sync] 이미 실행 중입니다 (pid {e.pid}) — 이 실행은 종료합니다.")
        # ⚠ 종료코드 0 으로 나가면 안 된다.
        #   감독기(service.py)가 '크래시'로 세어 5회 만에 sync 를 포기해 버리고,
        #   그러면 접수 리드를 아무도 회수하지 않는 상태가 계속된다.
        #   전용 코드로 '내 잘못이 아니라 중복이라 비켰다'를 알린다.
        sys.exit(EXIT_ALREADY_RUNNING)

    if not a.watch:
        cycle(a.limit)
        return
    print(f"[sync] 감시 모드 시작 — {a.interval}초 간격")
    while True:
        try:
            cycle(a.limit)
        except KeyboardInterrupt:
            print("\n[sync] 종료")
            return
        except Exception as e:
            print(f"[sync] 오류: {e}")
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
