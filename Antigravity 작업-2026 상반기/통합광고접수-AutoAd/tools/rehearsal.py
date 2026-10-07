# -*- coding: utf-8 -*-
"""rehearsal.py — 발행 경로 전구간 리허설 (실제 게시 없음)

왜 필요한가:
  이 시스템은 소재 생성 → 승인 → 발행 → 기록까지를 **끝까지 한 번도 통과해본 적이 없었다**.
  로그인 호출 누락 같은 결함이 그래서 오래 숨어 있었다.
  실발행을 켜기 전에 이 리허설을 통과시켜, 남은 구멍을 미리 드러낸다.

무엇을 하는가:
  임시 리허설 채널을 만들어 캠페인 1건을 돌리고, 승인 후 dry-run 발행까지 간 다음
  각 단계의 산출물을 실제로 검사한다. 끝나면 만든 것을 전부 지운다.

⚠ dry-run 이므로 어떤 채널에도 글이 올라가지 않는다.
   채널 이름에 '[데모]' 를 넣어, 혹시 남더라도 발행 직전 가드가 다시 막는다.

사용: python tools/rehearsal.py [--keep]
"""
import sys
import io
import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

import config
import db
import orchestrator as O

MARK = "[데모] 리허설 채널"
TARGET = "https://band.us/band/REHEARSAL-DRY-RUN-ONLY"

_fail = []
_warn = []


def check(cond, label, detail=""):
    print(f"  {'✅' if cond else '❌'} {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        _fail.append(label)
    return cond


def warn(cond, label, detail=""):
    print(f"  {'✅' if cond else '⚠️ '} {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        _warn.append(label)
    return cond


def setup_channel() -> int:
    for c in db.list_channels():
        if c["name"] == MARK:
            db.set_channel_enabled(c["id"], True, allow_demo=True)
            return c["id"]
    cid = db.add_channel("band", TARGET, MARK, audience="consumer",
                         tone="친근하고 신뢰감 있게", topic="부동산 담보", enabled=False)
    # 데모 표식이 있는 채널이라 의도적 우회가 필요하다(리허설 전용).
    db.set_channel_enabled(cid, True, allow_demo=True)
    return cid


def cleanup(chan_id, campaign_id, creative_ids):
    with db.get_conn() as c:
        for cr in creative_ids:
            c.execute("DELETE FROM posts WHERE creative_id=?", (cr,))
            c.execute("DELETE FROM approvals WHERE creative_id=?", (cr,))
            c.execute("DELETE FROM creatives WHERE id=?", (cr,))
        if campaign_id:
            c.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))
        c.execute("DELETE FROM channels WHERE id=?", (chan_id,))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="만든 데이터를 지우지 않는다")
    a = ap.parse_args()

    print("=" * 62)
    print(" 발행 경로 리허설 — 실제 게시 없음(dry-run)")
    print("=" * 62)
    print(f" 업종 프로필 : {config.PROFILE_KEY} ({config.PROFILE_NAME})")
    print(f" 발행 모드   : {'DRY-RUN' if config.GLOBAL_DRY_RUN else '⚠ 실발행 ON'}")
    print(f" 접수폼 주소 : {config.PUBLIC_BASE}")

    db.init_db()
    chan_id = setup_channel()
    campaign_id, creative_ids = None, []

    try:
        # ── 1) 소재 생성 ───────────────────────────────────
        print("\n[1] 캠페인 → 소재 생성 (카피는 실제 LLM 호출)")
        ch = [c for c in db.list_channels(enabled_only=True) if c["id"] == chan_id]
        res = O.run_campaign({"title": "리허설", "goal": "발행경로 점검",
                              "product": ""}, channels=ch)
        campaign_id = res["campaign_id"]
        creative_ids = [c["creative_id"] for c in res["creatives"]]
        if not check(res["creatives"], "소재가 만들어졌는가"):
            return
        cr = res["creatives"][0]

        img = Path(cr["image"])
        check(img.exists(), "전단 이미지 파일 생성", img.name)
        check(img.exists() and img.stat().st_size > 10_000, "이미지 크기 정상",
              f"{img.stat().st_size // 1024}KB" if img.exists() else "")

        cap = cr["caption"]
        text = O._caption_text(cap)
        print("\n  ── 실제로 나갈 문구 " + "─" * 34)
        for ln in text.splitlines():
            print(f"  │ {ln}")
        print("  " + "─" * 52)

        check(bool(text.strip()), "캡션 본문 있음")
        check(config.PUBLIC_BASE in text, "접수 링크 포함",
              "없으면 광고를 봐도 접수할 방법이 없다")
        check(f"channel=band_{chan_id}" in text, "유입 추적 파라미터",
              "없으면 어느 광고가 손님을 데려왔는지 모른다")
        if config.DISCLAIMER:
            check(config.DISCLAIMER.split()[0] in text or config.DISCLAIMER in text,
                  "의무 표기 포함", config.DISCLAIMER[:30])
        banned = [w for w in config.BANNED_PHRASES if w in text]
        check(not banned, "금칙어 없음", ", ".join(banned) if banned else "")
        warn(not cap.get("_fallback"), "LLM 카피 사용",
             "폴백 문구로 대체됨(LLM 호출 실패)" if cap.get("_fallback") else "")

        # ── 2) 승인 대기열 ─────────────────────────────────
        print("\n[2] 승인 대기열")
        pend = db.pending_approvals() if hasattr(db, "pending_approvals") else []
        check(cr["approval_id"] is not None, "승인 항목 등록", f"승인#{cr['approval_id']}")

        # ── 3) 승인 → 발행(dry) ────────────────────────────
        print("\n[3] 승인 → 발행 (dry-run)")
        pr = O.approve_and_publish(cr["approval_id"], reviewer="rehearsal", dry_run=True)
        check(getattr(pr, "ok", False), "발행 호출 성공")
        check(getattr(pr, "dry_run", False), "실제 게시 안 함(dry_run 플래그)")

        # ── 4) 기록 확인 ───────────────────────────────────
        print("\n[4] 기록")
        with db.get_conn() as c:
            row = c.execute("SELECT status, error FROM posts WHERE creative_id=? "
                            "ORDER BY id DESC LIMIT 1", (cr["creative_id"],)).fetchone()
            appr = c.execute("SELECT state FROM approvals WHERE id=?",
                             (cr["approval_id"],)).fetchone()
        check(row is not None, "발행 기록 남음")
        if row:
            check(row["status"] == "dry", "상태 = dry", f"실제: {row['status']}")
        check(appr is not None and appr["state"] == "approved", "승인 상태 반영",
              f"실제: {appr['state']}" if appr else "승인 항목 없음")

        # ── 5) 실발행 차단 확인 ────────────────────────────
        print("\n[5] 안전장치 — 지금 실발행을 시도하면?")
        pr2 = O.publish_creative(cr["creative_id"], dry_run=False)
        check(not pr2.ok and pr2.blocked, "차단됨", pr2.error or "")
        with db.get_conn() as c:
            b = c.execute("SELECT status, error FROM posts WHERE creative_id=? "
                          "ORDER BY id DESC LIMIT 1", (cr["creative_id"],)).fetchone()
        check(b and b["status"] == "blocked", "차단 사유가 기록됨",
              (b["error"] or "")[:60] if b else "")

    finally:
        if a.keep:
            print(f"\n(--keep) 채널 #{chan_id} · 캠페인 #{campaign_id} 유지")
        else:
            cleanup(chan_id, campaign_id, creative_ids)
            print("\n리허설 데이터 정리 완료")

    print("\n" + "=" * 62)
    if _fail:
        print(f" 판정: 실패 {len(_fail)}건 — {', '.join(_fail)}")
        print(" 실발행을 켜기 전에 위 항목을 먼저 해결하세요.")
    else:
        print(" 판정: 발행 경로 전구간 통과 ✅")
        if _warn:
            print(f" (참고 {len(_warn)}건: {', '.join(_warn)})")
        print(" 실발행은 실제 채널 등록 + GLOBAL_DRY_RUN=0 이 필요합니다.")
    print("=" * 62)
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main() or 0)
