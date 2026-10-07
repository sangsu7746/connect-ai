# ============================================================
#  intake/bridge.py — 소비자 접수 → 대출프로그램 연결  (P1-9 스텁)
#  종착: 대출위젯-카카오 app.py  POST {LOAN_API_BASE}/api/intake/register
#  · 소비자 최소필드 → IntakeRegisterModel 매핑
#  · 전환추적: source_channel/utm 기록(consumers)
#  ⚠ 주민번호(ssn) 미수집. file_path 없는 소비자건은 빈값 허용 매핑.
# ============================================================
import requests
import config
import db

REGISTER_URL = f"{config.LOAN_API_BASE}/api/intake/register"


def _idem_key(consumer_id: int, form: dict) -> str:
    """이 리드의 고유 열쇠. 재시도·재배달에도 **반드시 같은 값**이어야 한다.

    클라우드 문서 id 가 있으면 그것을 쓴다 — 수신함이 같은 리드를 두 번 배달해도
    같은 열쇠가 나와야 대출앱에 한 건만 남는다.
    없으면(로컬 폼 직접 접수) consumer_id 를 쓴다. 둘 다 리드당 한 번만 발급된다.
    이 값이 흔들리면 재시도가 새 접수로 등록돼 같은 손님에게 두 번 전화하게 된다."""
    cid = form.get("cloud_id")
    return f"cloud:{cid}" if cid else f"autoad:{consumer_id}"


def _payload(form: dict) -> dict:
    """소비자 리드 → 대출앱 IntakeRegisterModel 매핑.

    연락처는 memo 문장에 묻지 않고 phone 필드로 보낸다 — 묻어 보내면 대출앱 화면에서
    검색·중복확인이 안 되고, 사장님이 전화를 걸려면 메모를 눈으로 훑어야 한다.
    (구버전 대출앱 호환을 위해 memo 에도 남긴다. 추가 필드는 서버에서 기본값 처리됨)"""
    phone = form.get("phone", "")
    src = form.get("source_channel", "")
    return {
        "file_path": "",                       # 소비자건은 서류 없음
        "file_name": "",
        "loan_type": form.get("collateral") or "상담요청",
        "owner":     form.get("name", ""),
        "amount":    form.get("amount", ""),
        "phone":     phone,
        "source":    src or "ad_intake",       # 광고 유입임을 대출앱에서 구분
        "created_at": form.get("created_at") or "",
        "memo":      f"[소비자접수] 연락처 {phone} / 유입 {src}",
    }


def _remember_unmarked(consumer_id: int, loan_id, err):
    """'대출앱 등록은 됐는데 그 사실을 DB에 못 적은' 상태를 파일로 남긴다.

    이 상태를 그냥 두면 다음 재시도가 같은 손님을 또 등록하려 든다.
    (서버가 멱등키로 막아주지만, 그 방어가 뚫려도 복구할 수 있게 흔적을 남긴다)"""
    try:
        import json
        from datetime import datetime as _dt
        p = config.DATA_DIR / "pending_marks.jsonl"
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"consumer_id": consumer_id, "loan_id": loan_id,
                                "at": _dt.now().isoformat(), "error": str(err)[:200]},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def register(consumer_id: int, form: dict) -> dict:
    """이미 consumers 에 저장된 리드 1건을 대출앱에 등록하고 결과를 기록한다.

    성공/실패를 반드시 DB 에 남긴다. 남기지 않으면 실패한 리드가 조용히 묻혀
    광고비로 만든 손님에게 연락이 안 간다."""
    payload = _payload(form)
    payload["idempotency_key"] = _idem_key(consumer_id, form)
    try:
        resp = requests.post(REGISTER_URL, json=payload, timeout=30)
        resp.raise_for_status()
        out = resp.json()
    except Exception as e:
        # 실패 기록 자체가 실패해도(디스크 풀·DB 잠금) 재시도 카운터가 멈추면 안 된다.
        try:
            db.mark_consumer_failed(consumer_id, f"{type(e).__name__}: {e}")
        except Exception as e2:
            print(f"[bridge] ⚠ 실패 기록도 실패(#{consumer_id}): {e2}")
        raise

    # ⚠ 여기부터는 '대출앱에는 이미 들어간' 상태다. 절대 실패로 취급하면 안 된다.
    #   실패로 올리면 재시도가 같은 손님을 또 등록하려 든다.
    try:
        db.mark_consumer_registered(consumer_id, out.get("loan_id"))
    except Exception as e:
        _remember_unmarked(consumer_id, out.get("loan_id"), e)
        print(f"[bridge] ⚠ 등록은 됐으나 기록 실패(#{consumer_id} → loan_id={out.get('loan_id')}): {e}")
    return out


def submit_lead(form: dict) -> dict:
    """
    form: {name, phone, amount, collateral, consent(bool), source_channel, utm}
    1) 동의 확인 → consumers 저장(PII·동의시각)
    2) 대출앱 register 호출 → 성공/실패를 consumers 에 기록
    반환: {ok, loan_id, consumer_id}
    """
    if not form.get("consent"):
        raise ValueError("개인정보 수집·이용 동의 필요")

    # ⚠ 이 INSERT 는 아래 register 호출보다 먼저 커밋된다.
    #   register 가 실패해도 리드는 여기 남아 있으므로, 호출부에서 다시 저장하면 중복이 된다.
    #   실패분은 registered=0 으로 남아 cloud_sync 가 나중에 재시도한다.
    consumer_id = db.add_consumer(
        name=form.get("name", ""), phone=form.get("phone", ""),
        amount=form.get("amount", ""), collateral=form.get("collateral", ""),
        source_channel=form.get("source_channel", ""), utm=form.get("utm", ""),
        consent_at=form.get("consent_at"),
        created_at=form.get("created_at"),   # 클라우드 경유 시 실제 접수 시각
        cloud_id=form.get("cloud_id"))       # 재배달 식별용

    # ★ 이 시점에서 리드는 이미 안전하게 저장됐다.
    #   대출앱 전달이 실패해도 '접수 실패'라고 알리면 안 된다 —
    #   손님이 다시 제출해서 같은 사람이 두 번 등록되고, 두 번 전화하게 된다.
    #   전달은 cloud_sync 가 자동으로 재시도한다.
    try:
        out = register(consumer_id, form)
    except Exception as e:
        print(f"[bridge] 대출앱 전달 보류(#{consumer_id}) — 자동 재시도 예정: "
              f"{type(e).__name__}: {e}")
        return {"success": True, "pending": True, "consumer_id": consumer_id,
                "loan_id": None}
    out["consumer_id"] = consumer_id
    out["pending"] = False
    return out
