# ============================================================
#  approval.py — 승인 로직 + 콘솔  (P1-6)
#  · pending()/decide() = 프론트 무관 로직(웹 대시보드·텔레그램 공용)
#  · decide: approved→발행 / rejected→종료 / edited→카피 재생성 후 재큐
#  · run_bot() = 텔레그램 봇(지연 import, TELEGRAM_TOKEN 필요)
#  ⚠ 승인 전에는 어떤 것도 실채널로 나가지 않는다.
# ============================================================
import json
from pathlib import Path

import config
import db
import orchestrator
from content import copy_engine


# ── 조회 ────────────────────────────────────────────────────
def pending() -> list:
    """대기 승인 목록(UI 공용): 채널·상품·캡션·이미지 해석."""
    out = []
    for r in db.list_pending_approvals():   # a.*, c.copy_json, c.image_path, c.channel_id
        cap = json.loads(r["copy_json"]) if r.get("copy_json") else {}
        with db.get_conn() as conn:
            ch = conn.execute("SELECT name, platform FROM channels WHERE id=?",
                              (r["channel_id"],)).fetchone()
        img = r.get("image_path") or ""
        is_reply = bool(cap.get("reply"))
        out.append({
            "approval_id": r["id"],
            "creative_id": r["creative_id"],
            "channel": ch["name"] if ch else "?",
            "platform": ch["platform"] if ch else "?",
            "caption": cap,
            "image_name": Path(img).name if img else None,
            # ⚠ 이 소재가 어느 업종 것인지. 서버는 대출 업종으로 떠 있으므로
            #   이걸 안 실어주면 타투 광고 검토 화면에 대출 상호가 붙는다.
            "profile_key": cap.get("profile_key") or "",
            "brand": cap.get("brand") or "",
            # ── 쓰레드 답글 ──
            # 승인자가 원글을 못 보면 답글이 적절한지 판단할 수 없다.
            # 이 필드들이 없으면 승인 게이트가 형식만 남는다.
            "is_reply": is_reply,
            "reply_text": cap.get("reply") or "",
            "target_url": cap.get("target_url") or "",
            "target_author": cap.get("target_author") or "",
            "target_excerpt": cap.get("target_excerpt") or "",
            "score": cap.get("score") or 0,
        })
    return out


# ── 내부 헬퍼 ───────────────────────────────────────────────
def _creative_of(approval_id: int):
    with db.get_conn() as conn:
        r = conn.execute("SELECT creative_id FROM approvals WHERE id=?",
                         (approval_id,)).fetchone()
    return r["creative_id"] if r else None


def _caption_of(creative_id: int) -> dict:
    with db.get_conn() as conn:
        r = conn.execute("SELECT copy_json FROM creatives WHERE id=?",
                         (creative_id,)).fetchone()
    return json.loads(r["copy_json"]) if r and r["copy_json"] else {}


def _update_caption(creative_id: int, caption: dict):
    with db.get_conn() as conn:
        conn.execute("UPDATE creatives SET copy_json=?, approved=0 WHERE id=?",
                     (json.dumps(caption, ensure_ascii=False), creative_id))


# ── 결정 ────────────────────────────────────────────────────
def decide(approval_id: int, decision: str, reviewer: str = "operator",
           note: str = "", dry_run: bool = None) -> dict:
    """
    decision: approved | rejected | edited
      · approved → orchestrator.approve_and_publish (기본 dry-run)
      · rejected → 큐에서 종료
      · edited   → copy_engine.regenerate(캡션, note) → 크리에이티브 갱신 → 재큐
    """
    decision = (decision or "").lower()

    if decision == "approved":
        res = orchestrator.approve_and_publish(approval_id, reviewer=reviewer, dry_run=dry_run)
        return {"ok": True, "decision": "approved",
                "published": bool(getattr(res, "ok", False)),
                "dry_run": getattr(res, "dry_run", None),
                # 안 나갔으면 왜 안 나갔는지 화면에 그대로 보여준다.
                # (상한·시간대·쿨다운·세션만료를 구분 못 하면 운영자가 헛짚는다)
                "reason": getattr(res, "error", None),
                "blocked": bool(getattr(res, "blocked", False)),
                "perm_url": getattr(res, "perm_url", None)}

    if decision == "rejected":
        db.decide_approval(approval_id, "rejected", reviewer, note)
        return {"ok": True, "decision": "rejected"}

    if decision == "edited":
        cid = _creative_of(approval_id)
        if not cid:
            return {"ok": False, "error": f"승인 항목 없음: {approval_id}"}
        try:
            new_cap = copy_engine.regenerate(_caption_of(cid), note)
        except Exception as e:
            return {"ok": False, "decision": "edited",
                    "error": f"카피 재생성 실패({type(e).__name__}) — 크레딧/네트워크 확인"}
        _update_caption(cid, new_cap)
        db.decide_approval(approval_id, "edited", reviewer, note)
        new_aid = db.enqueue_approval(cid)          # 갱신본을 다시 승인 대기로
        return {"ok": True, "decision": "edited", "caption": new_cap, "approval_id": new_aid}

    raise ValueError(f"알 수 없는 결정: {decision}")


# ── 텔레그램 봇 (지연 import · 토큰 필요) ────────────────────
def _caption_text(cap: dict) -> str:
    return "\n".join(x for x in (cap.get("headline"), cap.get("body"), cap.get("cta")) if x)


def run_bot():
    """텔레그램 승인 콘솔. 폰에서 전단 사진+캡션 보고 승인/거절.
    ※ TELEGRAM_TOKEN + `pip install python-telegram-bot` 필요."""
    if not config.TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN 미설정 — .env 확인")
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler

    async def cmd_queue(update, ctx):
        items = pending()
        if not items:
            await update.message.reply_text("승인 대기 없음 ✅"); return
        for it in items:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ 승인", callback_data=f"approved:{it['approval_id']}"),
                InlineKeyboardButton("❌ 거절", callback_data=f"rejected:{it['approval_id']}"),
            ]])
            caption = (f"[{it['platform']}] {it['channel']}\n"
                       f"{_caption_text(it['caption'])}")
            img = config.CREATIVES_DIR / (it["image_name"] or "")
            if img.exists():
                with open(img, "rb") as fh:
                    await update.message.reply_photo(fh, caption=caption, reply_markup=kb)
            else:
                await update.message.reply_text(caption, reply_markup=kb)

    async def on_button(update, ctx):
        q = update.callback_query
        await q.answer()
        decision, aid = q.data.split(":")
        res = decide(int(aid), decision, reviewer="telegram")
        await q.edit_message_caption(caption=f"처리됨: {decision} · {res}")

    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CallbackQueryHandler(on_button))
    print("[approval] 텔레그램 봇 시작 (/queue 로 대기 목록 조회)")
    app.run_polling()


if __name__ == "__main__":
    run_bot()
