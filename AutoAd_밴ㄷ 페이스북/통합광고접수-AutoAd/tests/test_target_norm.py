# -*- coding: utf-8 -*-
"""discover_channels.norm_target — 같은 방을 같은 방으로 알아보는가

실측 사고(2026-08-10, 두 번째 밴드 계정 추가 중):
  밴드 목록 조회는 '.../band/123/post' 를 주는데 기존 채널은
  '.../band/123' 으로 저장돼 있었다. 문자열 그대로 비교하니 93개 전부
  '신규'로 판정됐다. 그중 44개는 **이미 켜져 있는 밴드**여서, 등록했다면
  같은 밴드에 두 계정이 같은 광고를 올리는 상태가 됐다.

⚠ 여기서 틀리면 두 방향 다 비싸다.
  · 다른 방을 같다고 하면 → 밴드가 통째로 누락된다
  · 같은 방을 다르다고 하면 → 중복 등록 → 같은 방에 이중 게시(스팸)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tools.discover_channels import norm_target as N


# 같은 방으로 봐야 하는 짝
SAME = [
    ("실제 사고 형태", "https://www.band.us/band/59057162",
                       "https://www.band.us/band/59057162/post"),
    ("끝 슬래시", "https://www.band.us/band/123",
                  "https://www.band.us/band/123/"),
    ("http/https", "http://band.us/band/123",
                   "https://www.band.us/band/123/post"),
    ("www 유무", "https://band.us/band/123",
                 "https://www.band.us/band/123"),
    ("뒤에 다른 경로", "https://www.band.us/band/123",
                       "https://www.band.us/band/123/post/456"),
]

# 서로 다른 방으로 봐야 하는 짝
DIFF = [
    ("다른 밴드 id", "https://www.band.us/band/123",
                     "https://www.band.us/band/1234"),
    ("id 앞부분만 같음", "https://www.band.us/band/59057162",
                         "https://www.band.us/band/59057"),
]


def main():
    fails = []
    print("── 같은 방으로 봐야 하는 것 ──────────────────")
    for name, a, b in SAME:
        na, nb = N("band", a), N("band", b)
        ok = na == nb
        print(f"  {'OK ' if ok else 'NG '} {name:<16} {na}  ==  {nb}")
        if not ok:
            fails.append(f"같은 방을 다르다고 함: {name}")

    print("\n── 다른 방으로 봐야 하는 것 ──────────────────")
    for name, a, b in DIFF:
        na, nb = N("band", a), N("band", b)
        ok = na != nb
        print(f"  {'OK ' if ok else 'NG '} {name:<16} {na}  !=  {nb}")
        if not ok:
            fails.append(f"다른 방을 같다고 함: {name}")

    print("\n── 밴드가 아닌 플랫폼은 건드리지 않는다 ────────")
    fb = "https://www.facebook.com/groups/383377075343800/"
    got = N("facebook", fb)
    ok = got == fb.rstrip("/")
    print(f"  {'OK ' if ok else 'NG '} facebook 그대로     {got}")
    if not ok:
        fails.append("facebook 주소가 바뀜")

    print("\n" + "-" * 50)
    if fails:
        for f in fails:
            print("  X", f)
        print(f" {len(fails)}건 실패")
        return 1
    print(f" {len(SAME) + len(DIFF) + 1}건 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
