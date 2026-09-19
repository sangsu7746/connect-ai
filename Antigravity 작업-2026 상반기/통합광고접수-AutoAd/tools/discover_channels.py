# -*- coding: utf-8 -*-
"""discover_channels.py — 내 밴드·페북그룹·카톡방을 읽어와 채널 후보로 등록

주소를 손으로 옮겨 적지 않아도 되게, 저장된 로그인 세션으로 실제 목록을 가져온다.
읽기 전용이다 — 글을 쓰거나 가입/탈퇴를 하지 않는다.

⚠ 가져온 채널은 **전부 비활성(enabled=0)** 으로 등록한다.
  어디에 광고할지는 사람이 정해야 한다. 전체를 켜면 사적인 모임·거래처 방까지
  광고가 나가 계정이 정지된다.

사용:
  python tools/discover_channels.py                 # 목록만 보기
  python tools/discover_channels.py --register      # 비활성으로 DB 등록
  python tools/discover_channels.py --platform band # 밴드만
"""
import sys
import io
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

import config
import db
import orchestrator as O


def _guess_audience(name: str) -> str:
    """방 이름으로 대략의 성향 추정. 어디까지나 초안이고 사람이 고쳐야 한다."""
    n = (name or "").lower()
    biz = ("대부", "캐피탈", "저축", "신협", "금융", "업체", "접수", "답변",
           "법인", "사업자", "중개", "컨설팅", "p2p")
    return "business" if any(k in n for k in biz) else "consumer"


def discover(platform: str) -> list:
    """플랫폼별 목록 조회. 반환 [{name, target, extra}]"""
    acc = O.default_account(platform)
    if platform in ("band", "facebook") and not acc:
        print(f"  [{platform}] 계정 미설정 — .env 의 "
              f"{'BAND_ACCOUNT' if platform == 'band' else 'FACEBOOK_ACCOUNT'} 를 채우세요")
        return []

    adapter = O.get_adapter(platform, acc)
    # 조회는 로그인을 새로 해야 할 때가 많다. 창 없는 모드는 로그인 폼 조작이
    # 불안정해서(버튼 활성화 타이밍) 여기서는 창을 띄운다.
    adapter.headless = False
    ok, why = O.ensure_login(adapter)
    if not ok:
        print(f"  [{platform}] {why}")
        return []

    try:
        if platform == "band":
            rows = adapter.discover_bands()
            return [{"name": r.get("name", ""), "target": r.get("url", ""),
                     "extra": " · ".join(x for x in (r.get("folder"),
                                                     r.get("member_count")) if x)}
                    for r in rows if r.get("url")]
        if platform == "facebook":
            rows = adapter.discover_groups()
            return [{"name": r.get("name", ""), "target": r.get("url", ""),
                     "extra": r.get("member_count", "")}
                    for r in rows if r.get("url")]
    except Exception as e:
        print(f"  [{platform}] 조회 실패: {type(e).__name__}: {e}")
    return []


def discover_kakao_chats() -> list:
    """밴드 채팅방 목록(밴드 엔진이 함께 제공). 카카오톡 방과는 별개다."""
    acc = O.default_account("band")
    if not acc:
        return []
    adapter = O.get_adapter("band", acc)
    ok, _ = O.ensure_login(adapter)
    if not ok:
        return []
    try:
        rows = adapter._automator().get_chat_list(
            status_callback=lambda m: print(f"    {m}"))
        return [{"name": r.get("name", ""), "target": r.get("url", ""),
                 "extra": r.get("member_count", "")} for r in rows if r.get("url")]
    except Exception as e:
        print(f"  [band-chat] 조회 실패: {type(e).__name__}: {e}")
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="all",
                    choices=["all", "band", "facebook", "bandchat"])
    ap.add_argument("--register", action="store_true",
                    help="찾은 채널을 DB에 비활성으로 등록")
    a = ap.parse_args()

    db.init_db()
    print("=" * 62)
    print(" 발행 대상 후보 조회 — 읽기 전용(글을 쓰지 않습니다)")
    print("=" * 62)

    plats = (["band", "facebook"] if a.platform == "all"
             else ([a.platform] if a.platform != "bandchat" else []))
    found = {}
    for p in plats:
        print(f"\n[{p}] 조회 중...")
        found[p] = discover(p)

    if a.platform in ("all", "bandchat"):
        print("\n[band-chat] 밴드 채팅방 조회 중...")
        found["bandchat"] = discover_kakao_chats()

    total = 0
    for p, rows in found.items():
        if not rows:
            continue
        print(f"\n── {p} — {len(rows)}개 " + "─" * 34)
        for i, r in enumerate(rows, 1):
            aud = _guess_audience(r["name"])
            print(f"  {i:2d}. {r['name'][:34]:36s} [{aud}]"
                  + (f"  {r['extra']}" if r["extra"] else ""))
            print(f"      {r['target']}")
            total += 1

    if not total:
        print("\n찾은 채널이 없습니다. 세션이 만료됐거나 가입한 곳이 없을 수 있습니다.")
        print("  세션 확인: python login.py --check")
        return 0

    if not a.register:
        print(f"\n총 {total}개 발견. DB에 등록하려면 --register 를 붙여 다시 실행하세요.")
        print("  (등록해도 전부 비활성입니다 — 광고할 곳만 따로 켜야 나갑니다)")
        return 0

    print("\n── DB 등록(전부 비활성) " + "─" * 33)
    added = 0
    exist = {(c["platform"], c["target_ref"]) for c in db.list_channels()}
    for p, rows in found.items():
        plat = "band" if p in ("band", "bandchat") else p
        for r in rows:
            if (plat, r["target"]) in exist:
                continue
            db.add_channel(plat, r["target"], r["name"] or r["target"],
                           audience=_guess_audience(r["name"]), enabled=False)
            added += 1
    print(f"  신규 {added}개 등록 · 기존 {total - added}개는 이미 있음")

    chans = db.list_channels()
    print(f"\n현재 등록 {len(chans)}개 · 활성 "
          f"{len([c for c in chans if c['enabled']])}개")
    print("\n광고할 채널을 고르려면 승인 콘솔이 아니라 아래로 켭니다:")
    print('  python -c "import db; db.set_channel_enabled(<채널id>, True)"')
    print("  채널 id 확인: python tools/discover_channels.py 후 DB 목록 참조")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    finally:
        O.close_all_adapters()      # 브라우저 정리
