# -*- coding: utf-8 -*-
"""일일 상한·발행 간격이 **계정별로** 세어지는가

왜 필요한가:
  상한의 목적은 계정 잠김 방지다. 위험은 계정마다 따로 쌓이므로 세는 것도
  계정마다 따로여야 한다. 플랫폼으로만 세면 같은 플랫폼의 두 번째 계정이
  첫 번째 계정의 발행 때문에 막힌다 — 보호가 아니라 손해다.
  (밴드 계정이 하나뿐이던 동안에는 드러나지 않던 결함)

⚠ 가장 위험한 회귀는 '상한이 통째로 풀리는' 쪽이다.
  account 를 빈 문자열로 넘기면 account='' 인 채널만 세게 되어 0건이 나오고
  상한이 사라진다. 그 경우를 반드시 확인한다.
"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import db


_SEQ = [0]


def _fresh(tmp: Path):
    """이 테스트 전용 DB. 운영 DB(data/autoad.db)는 절대 건드리지 않는다."""
    db.DB_PATH = str(tmp)
    if tmp.exists():
        tmp.unlink()
    db.init_db()


def _ch(account, platform="band", name=None):
    _SEQ[0] += 1
    return db.add_channel(platform, f"https://band.us/band/{_SEQ[0]:09d}",
                          name or f"{account}-방", account=account, enabled=True)


def main():
    tmp = Path(__file__).parent / "_tmp_per_account.db"
    _fresh(tmp)

    a = _ch("계정A", name="A-1")
    b = _ch("계정B", name="B-1")
    # 계정 A 로 3건 발행한 것으로 기록
    cid = db.add_campaign("t")
    for _ in range(3):
        crid = db.add_creative(cid, a, {"body": "x"}, "")
        db.record_post(crid, a, status="posted")

    checks = []

    n_all = db.posts_today(platform="band")
    checks.append(("플랫폼 전체", n_all, 3))

    n_a = db.posts_today(platform="band", account="계정A")
    checks.append(("계정A", n_a, 3))

    n_b = db.posts_today(platform="band", account="계정B")
    checks.append(("계정B(다른 계정은 안 셈)", n_b, 0))

    # ⚠ 회귀 방지: 빈 문자열은 '계정 구분 없음' 이어야 한다.
    #   여기서 account='' 로 필터가 걸리면 0 이 나오고 상한이 통째로 풀린다.
    n_empty = db.posts_today(platform="band", account="")
    checks.append(("빈 계정 = 필터 안 걸림", n_empty, 3))

    n_none = db.posts_today(platform="band", account=None)
    checks.append(("None = 필터 안 걸림", n_none, 3))

    # BaseAdapter._account() 도 같은 규칙이어야 한다.
    from channels.base import BaseAdapter

    class WithAcc(BaseAdapter):
        platform = "band"
        account_id = "계정A"

    class NoAcc(BaseAdapter):
        platform = "kakao"          # 카카오는 로그인 계정 개념이 없다

    class BlankAcc(BaseAdapter):
        platform = "band"
        account_id = "   "

    checks.append(("_account() 계정있음", WithAcc()._account(), "계정A"))
    checks.append(("_account() 계정없음", NoAcc()._account(), None))
    checks.append(("_account() 공백만", BlankAcc()._account(), None))

    fails = []
    for name, got, want in checks:
        ok = got == want
        print(f"  {'OK ' if ok else 'NG '} {name:<26} got={got!r} want={want!r}")
        if not ok:
            fails.append(name)

    print("\n" + "-" * 52)
    # ⚠ db.py 는 `with get_conn()` 을 쓰는데, sqlite3 에서 그 with 는 트랜잭션
    #   컨텍스트지 연결을 닫지 않는다. 윈도우에서는 연결이 GC 될 때까지 파일이
    #   잠겨 unlink 가 조용히 실패하고 임시 DB 가 저장소에 쌓인다.
    import gc
    gc.collect()
    try:
        tmp.unlink()
    except OSError as e:
        print(f"  (임시 DB 삭제 실패: {e} — 다음 실행 때 덮어씁니다)")
    if fails:
        print(f" {len(fails)}건 실패: {fails}")
        return 1
    print(f" {len(checks)}건 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
