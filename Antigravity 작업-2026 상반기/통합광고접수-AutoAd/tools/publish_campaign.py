# -*- coding: utf-8 -*-
"""publish_campaign.py — 승인 대기 중인 캠페인 소재를 실제 채널에 발행

⚠ 되돌릴 수 없다. 공개 게시물이 실제로 올라간다.
  그래서 --yes 없이는 계획만 출력하고 아무것도 하지 않는다.

무엇을 하는가:
  1) 로그인을 **먼저** 확인한다. 실패하면 한 건도 발행하지 않는다.
     (로그인이 안 된 채로 돌리면 전부 blocked 로 소진되고, 승인 상태만
      approved 로 바뀌어 다시 승인할 수 없게 된다)
  2) 승인 대기 건을 하나씩 approve_and_publish(dry_run=False) 한다.
     발행 간격·시간대·이미지 쿨다운·채널 상한은 orchestrator 가 잠금 안에서 본다.
  3) 연속 실패가 쌓이면 즉시 멈춘다. 막힌 계정에 계속 두드리면 상태가 더 나빠진다.

사용:
  python tools/publish_campaign.py --profile inkcraft            # 계획만 (안전)
  python tools/publish_campaign.py --profile inkcraft --yes      # 실제 발행
"""
import sys
import io
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _utf8_stdout():
    """콘솔 한글 깨짐 방지 — 스크립트로 실행될 때만.
    ⚠ 모듈 최상단에서 바꾸면 이 파일을 import 한 쪽의 출력이 닫혀버린다."""
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      line_buffering=True)
    except Exception:
        pass


import config          # noqa: E402
import db              # noqa: E402
import orchestrator as O   # noqa: E402

MAX_CONSECUTIVE_FAILS = 2


def pending(campaign_id: int):
    with db.get_conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT a.id aid, cr.id crid, ch.name, ch.platform, ch.ad_policy, "
            "       cr.image_path "
            "FROM approvals a "
            "JOIN creatives cr ON cr.id = a.creative_id "
            "JOIN channels ch ON ch.id = cr.channel_id "
            "WHERE cr.campaign_id = ? AND a.state = 'pending' "
            "ORDER BY a.id", (campaign_id,))]


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign", type=int, default=0, help="기본: 가장 최근")
    ap.add_argument("--profile", help="업종 key (표시용 — 캡션은 이미 소재에 저장됨)")
    ap.add_argument("--limit", type=int, default=0)
    # 이미 원인이 밝혀진 건(예: 가입 안 된 그룹)을 대기열 앞에 두면
    # 연속 실패 2회로 뒤의 정상 건까지 못 나간다. 그럴 때 빼고 돌린다.
    ap.add_argument("--skip", default="", help="건너뛸 승인번호(쉼표 구분)")
    ap.add_argument("--show", action="store_true", help="브라우저 창을 띄운다")
    ap.add_argument("--yes", action="store_true", help="실제로 발행한다")
    a = ap.parse_args()

    db.init_db()
    cid = a.campaign
    if not cid:
        with db.get_conn() as c:
            row = c.execute("SELECT MAX(id) m FROM campaigns").fetchone()
        cid = row["m"] if row else 0
    if not cid:
        print("캠페인이 없습니다.")
        return 1

    items = pending(cid)
    skip = {int(x) for x in a.skip.replace(" ", "").split(",") if x.isdigit()}
    if skip:
        before = len(items)
        items = [it for it in items if it["aid"] not in skip]
        print(f"  건너뜀 {before - len(items)}건: {sorted(skip)}")
    if a.limit:
        items = items[:a.limit]
    if not items:
        print(f"캠페인 #{cid}: 승인 대기 건이 없습니다.")
        return 0

    print(f"\n캠페인 #{cid} — 발행 대기 {len(items)}건")
    print("-" * 66)
    for it in items:
        form = "콘텐츠" if Path(it["image_path"] or "").name.startswith("showcase") else "광고 "
        print(f"  승인#{it['aid']:<4} {form} {it['ad_policy']:10s} {it['name'][:34]}")
    print("-" * 66)

    if not a.yes:
        print(" 계획만 출력했습니다. 실제로 발행하려면 --yes 를 붙이세요.")
        return 0

    # ⚠ 마스터 스위치를 여기서 먼저 본다.
    #   어댑터(channels/*.py)도 자체적으로 GLOBAL_DRY_RUN 을 검사하므로
    #   publish_creative(dry_run=False) 만으로는 실발행이 되지 않는다.
    #   이 확인이 없으면 한 건당 발행 간격(최대 300초)을 다 기다린 뒤 차단되고,
    #   그 사이 approve_and_publish 가 승인을 이미 소모해 되돌릴 수 없다(실측).
    if config.GLOBAL_DRY_RUN:
        print("\n GLOBAL_DRY_RUN=1 이라 실발행이 되지 않습니다.")
        print(" 이 실행에만 적용하려면 환경변수로 켜세요(.env 는 그대로 둡니다):")
        print("   GLOBAL_DRY_RUN=0 python tools/publish_campaign.py --yes ...")
        return 2

    # ── 로그인 먼저. 실패하면 승인 상태를 건드리지 않고 끝낸다. ──
    plats = {it["platform"] for it in items}
    for p in sorted(plats):
        adapter = O.get_adapter(p, O.default_account(p))
        if a.show:
            adapter.headless = False
        ok, why = O.ensure_login(adapter)
        print(f"[login] {p}: {'성공' if ok else '실패 — ' + str(why)[:120]}")
        if not ok:
            print(" 로그인 실패 → 아무것도 발행하지 않고 중단합니다.")
            return 1

    print(f"\n실발행 시작 — 간격 {config.POST_INTERVAL_MIN}~{config.POST_INTERVAL_MAX}초\n")
    done = {"posted": 0, "blocked": 0, "failed": 0}
    fails = 0
    for i, it in enumerate(items, 1):
        t0 = time.time()
        try:
            res = O.approve_and_publish(it["aid"], reviewer="operator", dry_run=False)
            ok = bool(getattr(res, "ok", False))
            blocked = bool(getattr(res, "blocked", False))
            err = getattr(res, "error", None)
        except Exception as e:
            ok, blocked, err = False, False, f"{type(e).__name__}: {e}"

        kind = "posted" if ok else ("blocked" if blocked else "failed")
        done[kind] += 1
        mark = {"posted": "발행", "blocked": "차단", "failed": "실패"}[kind]
        print(f"  [{i}/{len(items)}] {mark}  {it['name'][:30]}  ({int(time.time()-t0)}초)"
              + (f"  — {str(err)[:90]}" if err else ""))

        # 차단(안전장치)은 정상 동작이므로 연속 실패로 세지 않는다.
        # 진짜 실패만 센다 — 계정이 막혔을 때 계속 두드리지 않기 위해서다.
        fails = fails + 1 if kind == "failed" else 0
        if fails >= MAX_CONSECUTIVE_FAILS:
            print(f"\n 연속 실패 {fails}회 → 중단합니다. 남은 {len(items)-i}건은 "
                  f"승인 대기 상태로 남습니다.")
            break

    print("\n" + "-" * 66)
    print(f" 발행 {done['posted']} · 차단 {done['blocked']} · 실패 {done['failed']}")
    print(" (브라우저는 열어 둡니다 — 닫으면 세션이 사라집니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
