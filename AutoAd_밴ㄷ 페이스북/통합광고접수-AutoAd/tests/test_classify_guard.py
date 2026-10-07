# -*- coding: utf-8 -*-
"""분류기가 대출 광고를 아무 데나 보내지 못하게 막는 가드.

분류기는 LLM 이라 매번 흔들린다. 실측(2026-08-12)에서 '유머·게임·낚시' 밴드가
loan 판정을 받았는데, 소개글에 온갖 주제가 나열돼 있어 그 안에 '대출·부동산'이
실제로 들어 있었던 탓이다. 키워드만으로는 못 거른다.

대출은 업종 하나가 아니라 **대부업 광고**다. 잘못 보내면 신고·강퇴로 이어지고,
loan 은 이미 활성 채널의 절반이라 쏠림 위험도 가장 크다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import classify_channels as C


def _guard(name, intro="", key="loan"):
    return C._loan_needs_topic((1, name, intro), key)


# ── 진짜 대출 대상 모임은 통과해야 한다 ──────────────────────────────
@pytest.mark.parametrize("name, intro", [
    ("부산.울산.김해.양산부동산-부산부동산.김해부동산", "부동산 정보 공유"),
    ("무료 부동산", "회원 여러분 부동산 매물 자유롭게 올려주세요 광고 홍보"),
    ("부동산 경매 정보 평생교육원 월간 굿옥션", "경매 교육 정보"),
    ("부산♥경남 부자농부의 귀농귀촌 시골집 농가주택 전원주택", ""),
    ("아파트 분양114 부동산,분양구인구직", ""),
])
def test_real_money_group_keeps_loan(name, intro):
    assert _guard(name, intro) == "loan"


# ── 아무거나 다 받는 모임은 막아야 한다 ─────────────────────────────
@pytest.mark.parametrize("name, intro, why", [
    # 이름 자체가 주제 나열 — 영역이 너무 넓다
    ("◈놀다자자◈ 광고 홍보 유머 게임 낚시 등산 골프 중고 마케팅 대출 신용 웹툰",
     "부동산 금융 창업 재테크 분양 취업정보 요리 다이어트",
     "이름이 서로 무관한 영역 5개 이상을 걸친다"),
    # 문턱은 통과하지만 이름이 '주제 없음'을 내걸었다
    ("❤자유롭게 글쓰는 밴드❤각종품앗이,게임,성인,유머,사진,부업,구인구직",
     "부동산 주식 재테크 아파트 투자 코인 명품",
     "'자유롭게' — 스스로 아무 얘기나 하는 곳이라고 말한다"),
    ("무엇이든 자유롭게 공유하세요", "부동산 여행 건강 반려동물 유머 게임",
     "'무엇이든'"),
])
def test_catchall_group_loses_loan(name, intro, why):
    assert _guard(name, intro) == C.NONE, why


def test_no_money_context_loses_loan():
    """돈·부동산 맥락이 아예 없으면 근거가 없다."""
    assert _guard("반려동물 사랑 모임", "강아지 고양이 자랑해요") == C.NONE


def test_guard_only_touches_loan():
    """다른 업종은 건드리지 않는다 — 대출만 규제 광고다."""
    catchall = "❤자유롭게 글쓰는 밴드❤ 부동산 주식 게임 유머"
    for key in ("petportrait", "lifealbum", "adstudio", "mirizip", C.NONE):
        assert _guard(catchall, key=key) == key


# ── 일반 커뮤니티가 갈 곳이 있어야 한다 ─────────────────────────────
def test_general_profiles_exist():
    """GENERAL_OK 가 비면 일반 커뮤니티가 전부 none 으로 떨어진다.

    이 프로젝트가 실제로 겪은 사고다(미배정 28곳 → 28곳 모두 none).
    프로필을 지우거나 이름을 바꿀 때 이 목록도 같이 고쳐야 한다.
    """
    assert C.GENERAL_OK, "일반 커뮤니티용 업종이 하나도 없다"
    unknown = [k for k in C.GENERAL_OK if k not in C.HINT]
    assert not unknown, f"HINT 에 없는 업종을 권하고 있다: {unknown}"


def test_prompt_tells_model_what_to_do_with_general_communities():
    p = C.build_prompt([(1, "무엇이든 자유롭게 공유하세요", "사진, 여행, 반려동물")])
    assert "[일반 커뮤니티]" in p
    # 일반 커뮤니티에 권할 업종이 프롬프트에 실제로 박혀 나가는지
    assert any(k in p for k in C.GENERAL_OK)
