# -*- coding: utf-8 -*-
"""주기를 짧게 잡아도 업종이 굶지 않는다.

2026-08-14 실측 사고: 체크 주기를 20분→10분으로 줄였더니 per_cycle_cap() 이
10→4 로 같이 줄었다. do_generate 는 need(=4) 를 활성 업종 수(12)로 나눠
갖는데, need < len(profs) 라 나머지 배분이 앞쪽 4개(사전순: adstudio·
colorcraft·inkcraft·loan)에서 끝났다. 그 결과 뒤쪽 8개 업종(mirizip·
proheadshot·lifealbum 등)이 7시간 넘게 소재를 하나도 못 받았다 — 매 주기
반복해서.

고친 것: per_cycle_cap(min_n) 이 '이번에 나눠 가질 업종 수' 밑으로는
안 내려가게 바닥을 둔다. do_generate 가 len(profs) 를 그 바닥으로 넘긴다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import auto_loop as A


def test_cap_never_drops_below_profile_count():
    """이 사고의 핵심 단언 — 주기가 아무리 짧아도 업종 수 밑으로는 안 간다."""
    A._INTERVAL[0] = 600          # 사고를 일으켰던 그 주기(10분)
    try:
        assert A.per_cycle_cap(12) >= 12
        assert A.per_cycle_cap(20) >= 20   # 업종이 더 많아져도 마찬가지
    finally:
        A._INTERVAL[0] = 1200


def test_cap_still_scales_up_when_interval_is_generous():
    """바닥을 넣었다고 원래 계산이 죽으면 안 된다 — 넉넉한 주기에선 그대로 커야 한다."""
    A._INTERVAL[0] = 1200
    try:
        # 활성 업종이 2개뿐이면 시간 계산값(10)이 이겨야 한다(바닥에 안 눌린다)
        assert A.per_cycle_cap(2) == max(2, A.per_cycle_cap(0))
    finally:
        A._INTERVAL[0] = 1200


def test_cap_floor_prevents_the_exact_starvation_ratio():
    """실측 수치 재현 — 주기 600초일 때 옛 계산은 4, 업종 12개면 나머지 배분이
    앞 4개에서 끝난다. 바닥을 넣은 뒤에는 12 이상이라 전부 몫을 받는다."""
    A._INTERVAL[0] = 600
    try:
        old_style = max(2, int(A._INTERVAL[0] /
                               ((A.config.POST_INTERVAL_MIN + A.config.POST_INTERVAL_MAX) / 2 + 30)) * 2)
        assert old_style == 4, "실측 당시 수치(4)가 재현되지 않는다 - 전제가 바뀌었다"

        n_profiles = 12
        fixed = A.per_cycle_cap(n_profiles)
        assert fixed >= n_profiles

        # need = min(room, free_ch, cap) - have 상황을 흉내낸다.
        # room·free_ch 가 넉넉하다고 가정(문제는 cap 이 작아서 생겼다).
        need_old = old_style
        need_fixed = fixed
        profs = [f"p{i}" for i in range(n_profiles)]

        def shares(need):
            return [need // len(profs) + (1 if i < need % len(profs) else 0)
                    for i in range(len(profs))]

        starved_old = sum(1 for s in shares(need_old) if s == 0)
        starved_fixed = sum(1 for s in shares(need_fixed) if s == 0)

        assert starved_old == 8, "옛 계산으로는 8개 업종이 굶어야 사고가 재현된 것이다"
        assert starved_fixed == 0, "바닥을 넣었는데도 굶는 업종이 남아 있다"
    finally:
        A._INTERVAL[0] = 1200


def test_default_min_n_is_backward_compatible():
    """인자 없이 부르는 기존 호출부가 깨지면 안 된다."""
    A._INTERVAL[0] = 1200
    try:
        assert A.per_cycle_cap() == A.per_cycle_cap(0)
    finally:
        A._INTERVAL[0] = 1200
