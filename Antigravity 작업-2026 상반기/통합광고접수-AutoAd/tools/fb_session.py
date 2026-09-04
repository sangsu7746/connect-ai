# -*- coding: utf-8 -*-
"""fb_session.py — 창 하나로 로그인부터 페이스북 그룹 목록 수집까지

band_session.py 의 페이스북 판. 같은 원칙을 지킨다:
  · 로그인한 창을 닫지 않는다(닫으면 세션이 죽어 다시 로그인해야 한다)
  · 추가 인증(캡차·2단계)이 뜨면 그 창에서 사람이 통과하고, 스크립트는 기다린다
  · 가져온 그룹은 **전부 비활성**으로 등록한다 — 어디에 광고할지는 사람이 정한다

사용:
  python tools/fb_session.py                # 목록만 보기
  python tools/fb_session.py --register     # 비활성으로 DB 등록까지
  python tools/fb_session.py --wait 10      # 수동 인증 대기(분)
"""
import sys
import io
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

import config
import db
import orchestrator as O

BIZ = ("대부", "캐피탈", "저축", "신협", "금융", "업체", "접수", "답변",
       "법인", "사업자", "중개", "컨설팅", "p2p")


def _guess_audience(name: str) -> str:
    n = (name or "").lower()
    return "business" if any(k in n for k in BIZ) else "consumer"


def ensure_login_interactive(adapter, wait_min: int) -> bool:
    """자동 로그인 → 안 되면 같은 창에서 사람이 마무리하도록 기다린다."""
    ok, why = O.ensure_login(adapter)
    if ok:
        print("  로그인 완료(자동)")
        return True

    print(f"  자동 로그인 실패: {why[:130]}")
    auto = adapter._automator()
    if auto.driver is None:
        auto.driver = auto._create_driver()
    try:
        auto.driver.get("https://www.facebook.com/login")
    except Exception:
        pass

    print()
    print("  " + "=" * 58)
    print("  열려 있는 창에서 직접 로그인해 주세요.")
    print("  · 2단계 인증·캡차가 뜨면 그 창에서 통과하세요.")
    print("  · '로그인 상태 유지'가 보이면 체크해 주세요.")
    print("  · 창을 닫지 마세요 — 이 창 그대로 그룹 목록을 읽습니다.")
    print(f"  최대 {wait_min}분 기다립니다.")
    print("  " + "=" * 58)
    print()

    deadline = time.time() + wait_min * 60
    while time.time() < deadline:
        try:
            if auto._is_logged_in():
                try:
                    auto._save_cookies()
                except Exception:
                    pass
                adapter._logged_in = True
                adapter._login_at = time.time()
                print("\n  로그인 확인 — 창을 유지한 채 계속 진행합니다")
                return True
        except Exception:
            pass
        left = int(deadline - time.time())
        print(f"\r  대기 중... {left // 60}분 {left % 60:02d}초", end="", flush=True)
        time.sleep(3)
    print("\n  시간 초과")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true", help="찾은 그룹을 비활성으로 등록")
    ap.add_argument("--wait", type=int, default=10, help="수동 인증 대기(분)")
    a = ap.parse_args()

    db.init_db()
    acc = config.FACEBOOK_ACCOUNT
    if not acc:
        print(".env 의 FACEBOOK_ACCOUNT 가 비어 있습니다.")
        return 1

    print("=" * 62)
    print(" 페이스북 그룹 목록 수집 — 창 하나로 로그인부터 끝까지")
    print("=" * 62)
    print(f" 계정: {acc}")

    adapter = O.get_adapter("facebook", acc)
    adapter.headless = False        # 로그인 폼 조작은 창 없는 모드가 불안정하다

    try:
        print("\n[1] 로그인")
        if not ensure_login_interactive(adapter, a.wait):
            return 1

        print("\n[2] 그룹 목록 수집 (같은 창)")
        groups = adapter.discover_groups()
        print(f"  {len(groups)}개 발견")

        # 목록 화면에서 이름을 못 읽은 그룹은 각 그룹 페이지에서 제목을 읽어 채운다.
        # 이름을 모르면 어디에 광고할지 고를 수가 없다.
        missing = [g for g in groups if not (g.get("name") or "").strip()]
        if missing:
            print(f"\n[3] 이름 미확인 {len(missing)}개 — 그룹 페이지에서 직접 확인")
            groups = adapter._automator().resolve_group_names(
                groups, status_callback=lambda m: print(f"    {m}"))

        rows = [(g.get("name", ""), g["url"]) for g in groups if g.get("url")]

        if not rows:
            print("\n찾은 그룹이 없습니다.")
            print("  가입한 그룹이 없거나 페이스북 화면 구조가 바뀌었을 수 있습니다.")
            return 1

        print("\n" + "─" * 62)
        for i, (name, url) in enumerate(rows, 1):
            print(f"{i:3d}. {name[:40]:42s} [{_guess_audience(name)}]")
            print(f"     {url}")

        if not a.register:
            print(f"\n총 {len(rows)}개. 등록하려면 --register 를 붙여 다시 실행하세요.")
            print("  (등록해도 전부 비활성 — 광고할 곳만 따로 켜야 나갑니다)")
            return 0

        exist = {c["target_ref"] for c in db.list_channels(platform="facebook")}
        added = 0
        for name, url in rows:
            if url in exist:
                continue
            db.add_channel("facebook", url, (name or url)[:80],
                           audience=_guess_audience(name),
                           topic="부동산 담보대출", tone="친근하고 신뢰감 있게",
                           enabled=False, account=acc)
            added += 1
        print(f"\n등록: 신규 {added}개 (전부 비활성) · 기존 {len(rows) - added}개")
        allch = db.list_channels()
        print(f"전체 채널 {len(allch)}개 · 활성 {len([c for c in allch if c['enabled']])}개")
        print("\n광고할 그룹만 켜세요:")
        print('  python -c "import db; db.set_channel_enabled(<id>, True)"')
        return 0

    finally:
        # ⚠ 일부러 닫지 않는다 — 닫으면 세션이 사라져 다음 작업에서 또 로그인해야 한다.
        print("\n(브라우저를 열어 둡니다 — 닫으면 로그인 세션이 사라집니다)")
        print(" 정리하려면 그 크롬 창을 직접 닫으시면 됩니다.")


if __name__ == "__main__":
    sys.exit(main() or 0)
