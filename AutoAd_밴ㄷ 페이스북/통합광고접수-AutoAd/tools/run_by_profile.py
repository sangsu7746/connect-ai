# -*- coding: utf-8 -*-
"""run_by_profile.py — 업종별로 캠페인을 돌린다

업종(브랜드·의무표기·소재출처)은 프로세스 시작 때 config 에 박히므로,
한 프로세스에서 여러 업종을 섞을 수 없다. 업종마다 **별도 프로세스**로 실행한다.

채널은 channels.profile_key 로 골라진다(tools/classify_channels.py 가 배정).

⚠ 소재를 만들고 승인 대기열에 넣기만 한다. 발행은 승인 콘솔에서 사람이 결정한다.

사용:
  python tools/run_by_profile.py --profile inkcraft            # 그 업종만
  python tools/run_by_profile.py --profile inkcraft --limit 5  # 채널 5개만
  python tools/run_by_profile.py --all                         # 활성 채널이 있는 모든 업종
  python tools/run_by_profile.py --profile inkcraft --list     # 대상만 보기
"""
import os
import re
import sys
import io
import json
import argparse
import subprocess
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

import db
import profiles as P


# 자식 프로세스(해당 업종 설정으로 뜬다)에서 실행되는 본체
CHILD = r'''
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
import config, db, orchestrator as O

ids = json.loads(sys.argv[1])
title = sys.argv[2]
# "1" 이면 새 그림을 만들지 않고 재고만 돌린다(auto_loop 의 재고 목표 충족).
reuse_only = len(sys.argv) > 3 and sys.argv[3] == "1"
chans = [c for c in db.list_channels(enabled_only=True) if c["id"] in ids]
if not chans:
    print("대상 채널 없음"); raise SystemExit(0)
print(f"업종 {config.PROFILE_KEY} ({config.PROFILE_NAME}) · 채널 {len(chans)}개"
      + (" · 재고 재사용만" if reuse_only else ""))
res = O.run_campaign({"title": title, "goal": "상담·유입", "product": ""},
                     channels=chans, reuse_only=reuse_only)
print("@@" + json.dumps({"campaign_id": res["campaign_id"],
                         "n": len(res["creatives"])}, ensure_ascii=False))
'''


def run_profile(key: str, limit: int, title: str, list_only: bool,
                reuse_only: bool = False) -> dict:
    chans = db.channels_for_profile(key, enabled_only=True)
    if limit:
        chans = chans[:limit]
    label = P.load(key)["name"]
    print(f"\n{'='*62}\n■ {key} — {label} · 활성 채널 {len(chans)}개\n{'='*62}")
    if not chans:
        print("  활성 채널이 없습니다(비활성이거나 배정 없음).")
        return {"key": key, "n": 0}
    for c in chans[:10]:
        print(f"   · [{c['platform']}] {c['name'][:52]}")
    if len(chans) > 10:
        print(f"     ... 외 {len(chans)-10}개")
    if list_only:
        return {"key": key, "n": 0, "listed": len(chans)}

    env = dict(os.environ, AUTOAD_PROFILE=key, PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, "-c", CHILD, json.dumps([c["id"] for c in chans]), title,
         "1" if reuse_only else "0"],
        cwd=str(BASE), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=1800)
    made = None
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("@@"):
            made = json.loads(ln[2:])
        else:
            print("  " + ln)
    if made is None:
        # ⚠ 마지막 한 줄만 찍으면 원인이 안 보인다. 자식이 진행 상황을 계속
        #   출력하므로 '마지막 줄'은 대개 진행 라벨이고 진짜 예외는 그 앞에 있다
        #   (2026-08-13: '실패: 업종 adstudio · 채널 2개' 만 나와 원인을 못 찾았다).
        #   예외 흔적이 있으면 그쪽을, 없으면 꼬리 여러 줄을 보여준다.
        tail = ((r.stderr or "") + "\n" + (r.stdout or "")).strip().splitlines()
        err = [ln for ln in tail
               if ("Error" in ln or "Exception" in ln or "Traceback" in ln
                   or "실패" in ln)]
        show = (err[-3:] if err else tail[-5:]) or ["알 수 없는 오류"]
        print("  실패:")
        for ln in show:
            print(f"    {ln[:220]}")
        return {"key": key, "n": 0, "error": True}
    print(f"  → 소재 {made['n']}건 생성 · 승인 대기열 등록 (캠페인 #{made['campaign_id']})")
    return {"key": key, "n": made["n"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", help="업종 key (예: inkcraft)")
    ap.add_argument("--all", action="store_true", help="활성 채널이 있는 모든 업종")
    ap.add_argument("--limit", type=int, default=0, help="업종당 채널 수 제한")
    ap.add_argument("--title", default="", help="캠페인 제목")
    ap.add_argument("--list", action="store_true", help="대상만 보고 만들지 않음")
    # 재고 목표를 채운 업종에 auto_loop 이 붙여 보낸다. 소재는 그대로 만들되
    # 그림만 재고에서 꺼내 쓴다 — '생성이 0 으로 수렴' 이지 '소재가 0' 이 아니다.
    ap.add_argument("--reuse-only", action="store_true",
                    help="새 그림을 만들지 않고 기존 재고만 재사용한다")
    a = ap.parse_args()

    db.init_db()
    if a.all:
        keys = sorted({c["profile_key"] for c in db.list_channels(enabled_only=True)
                       if c["profile_key"]})
    elif a.profile:
        keys = [a.profile]
    else:
        ap.error("--profile 또는 --all 이 필요합니다")

    avail = set(P.available())
    bad = [k for k in keys if k not in avail]
    if bad:
        print(f"없는 업종: {', '.join(bad)}")
        return 1

    from datetime import datetime
    title = a.title or f"자동 {datetime.now():%m-%d}"
    total = 0
    for k in keys:
        total += run_profile(k, a.limit, title, a.list,
                             reuse_only=a.reuse_only).get("n", 0)

    if not a.list:
        print(f"\n{'-'*62}")
        print(f" 총 {total}건 소재 생성 → 승인 콘솔에서 확인하세요")
        print(" http://127.0.0.1:8010/approvals")
        print(" ⚠ 승인해야 발행됩니다. 지금은 아무것도 게시되지 않았습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
