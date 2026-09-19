# -*- coding: utf-8 -*-
"""band_session.py — 창 하나로 로그인부터 목록 수집까지 끝낸다

왜 이렇게 하는가:
  밴드가 주는 세션(band_session·JSESSIONID)은 '브라우저 닫으면 만료'짜리다.
  그래서 로그인한 창을 닫고 새 창을 열면 반드시 로그아웃 상태가 된다.
  포스팅 프로그램(페이스북-광고글/main.py)도 _automators 딕셔너리에 인스턴스를
  붙들어 두고 브라우저를 계속 살려두는 방식으로 이 문제를 피한다.

  → 이 스크립트는 **한 창에서** 로그인 → 밴드 목록 → 채팅방 목록 → 등록까지 한다.
    중간에 브라우저를 닫지 않는다.

추가 인증(캡차·이메일 확인)이 걸리면 그 창에서 직접 통과하면 되고,
스크립트가 기다렸다가 이어서 진행한다.

사용:
  python tools/band_session.py                # 목록만 보기
  python tools/band_session.py --register     # 비활성으로 DB 등록까지
  python tools/band_session.py --wait 10      # 수동 인증 대기(분)
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


def _guess_audience(name: str) -> str:
    n = (name or "").lower()
    biz = ("대부", "캐피탈", "저축", "신협", "금융", "업체", "접수", "답변",
           "법인", "사업자", "중개", "컨설팅", "p2p")
    return "business" if any(k in n for k in biz) else "consumer"


def ensure_login_interactive(adapter, wait_min: int) -> bool:
    """자동 로그인 시도 → 안 되면 같은 창에서 사람이 마무리하도록 기다린다."""
    ok, why = O.ensure_login(adapter)
    if ok:
        print("  로그인 완료(자동)")
        return True

    print(f"  자동 로그인 실패: {why[:120]}")
    auto = adapter._automator()
    if auto.driver is None:
        auto.driver = auto._create_driver()
    try:
        auto.driver.get("https://auth.band.us/email_login")
    except Exception:
        pass

    print()
    print("  " + "=" * 58)
    print("  열려 있는 창에서 직접 로그인해 주세요.")
    print("  · 추가 인증(캡차·이메일 확인)이 뜨면 그 창에서 통과하세요.")
    print("  · 로그인 화면에 '로그인 상태 유지'가 있으면 체크해 주세요.")
    print("  · 창을 닫지 마세요 — 이 창 그대로 목록을 읽습니다.")
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
    ap.add_argument("--register", action="store_true", help="찾은 채널을 비활성으로 등록")
    ap.add_argument("--wait", type=int, default=10, help="수동 인증 대기(분)")
    ap.add_argument("--chats", action="store_true", help="채팅방 목록도 수집")
    a = ap.parse_args()

    db.init_db()
    acc = config.BAND_ACCOUNT
    if not acc:
        print(".env 의 BAND_ACCOUNT 가 비어 있습니다.")
        return 1

    print("=" * 62)
    print(" 밴드 목록 수집 — 창 하나로 로그인부터 끝까지")
    print("=" * 62)
    print(f" 계정: {acc}")

    # 창을 띄운다. 로그인 폼 조작은 창 없는 모드에서 불안정하다.
    adapter = O.get_adapter("band", acc)
    adapter.headless = False

    try:
        print("\n[1] 로그인")
        if not ensure_login_interactive(adapter, a.wait):
            return 1

        print("\n[2] 밴드 목록 수집 (같은 창)")
        bands = adapter.discover_bands()
        print(f"  {len(bands)}개 발견")

        chats = []
        if a.chats:
            print("\n[3] 채팅방 목록 수집 (같은 창)")
            chats = adapter._automator().get_chat_list(
                status_callback=lambda m: print(f"    {m}"))
            print(f"  {len(chats)}개 발견")

        print("\n" + "─" * 62)
        rows = []
        for b in bands:
            if not b.get("url"):
                continue
            rows.append(("band", b.get("name", ""), b["url"],
                         " · ".join(x for x in (b.get("folder"),
                                                b.get("member_count")) if x)))
        for c in chats:
            if c.get("url"):
                rows.append(("chat", c.get("name", ""), c["url"],
                             c.get("member_count", "")))

        if not rows:
            print("찾은 것이 없습니다. 가입한 밴드가 없거나 페이지 구조가 바뀌었을 수 있습니다.")
            return 1

        for i, (kind, name, url, extra) in enumerate(rows, 1):
            aud = _guess_audience(name)
            print(f"{i:3d}. [{kind}] {name[:32]:34s} [{aud}]" + (f"  {extra}" if extra else ""))
            print(f"     {url}")

        if not a.register:
            print(f"\n총 {len(rows)}개. 등록하려면 --register 를 붙여 다시 실행하세요.")
            print("  (등록해도 전부 비활성 — 광고할 곳만 따로 켜야 나갑니다)")
            return 0

        exist = {(c["platform"], c["target_ref"]) for c in db.list_channels()}
        added = 0
        for kind, name, url, _ in rows:
            if ("band", url) in exist:
                continue
            db.add_channel("band", url, name or url,
                           audience=_guess_audience(name), enabled=False,
                           account=acc)
            added += 1
        print(f"\n등록: 신규 {added}개 (전부 비활성) · 기존 {len(rows) - added}개")
        chans = db.list_channels()
        print(f"현재 채널 {len(chans)}개 · 활성 {len([c for c in chans if c['enabled']])}개")
        print("\n광고할 채널만 켜세요:")
        print('  python -c "import db; db.set_channel_enabled(<id>, True)"')
        return 0

    finally:
        # ⚠ 일부러 브라우저를 닫지 않는다.
        #   닫는 순간 밴드 세션이 사라져 다음 작업에서 또 로그인해야 한다.
        print("\n(브라우저를 열어 둡니다 — 닫으면 로그인 세션이 사라집니다)")
        print(" 정리하려면 그 크롬 창을 직접 닫으시면 됩니다.")


if __name__ == "__main__":
    sys.exit(main() or 0)
