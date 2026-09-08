# -*- coding: utf-8 -*-
"""SPECS 는 프로필의 컴플라이언스와 함께 써야 한다.

⚠ stickerme 프로필은 note 가 "타 IP·캐릭터 연상 표현 금지" 다. note 를 안 보고
  모티프를 지으면 타 IP 연상 표현이 그대로 광고로 나간다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from content import showcase as S

NEW = ["printcraft", "mirizip", "proheadshot", "colorcraft",
       "petportrait", "wallpreview", "nailpreview"]


def test_new_profiles_registered():
    for k in NEW:
        assert k in S.SPECS, f"{k} SPECS 없음"


def test_each_spec_has_label_styles_motifs():
    for k in NEW:
        spec = S.SPECS[k]
        assert spec.get("label")
        assert len(spec.get("styles") or []) >= 4, f"{k}: 기법이 4개 미만"
        assert len(spec.get("motifs") or []) >= 6, f"{k}: 소재가 6개 미만"


def test_styles_are_label_prompt_pairs():
    for k in NEW:
        for item in S.SPECS[k]["styles"]:
            assert isinstance(item, tuple) and len(item) == 2
            assert "{subject}" in item[1], f"{k}: 프롬프트에 {{subject}} 없음"


def test_styles_for_is_deterministic():
    """make() 의 인덱스 계산식과 같아야 한다(기존 주석의 경고)."""
    a = S.styles_for("printcraft", 0, tiles_n=4)
    b = S.styles_for("printcraft", 0, tiles_n=4)
    assert a == b and len(a) == 4


def test_no_named_ip_in_motifs():
    """타 IP 연상 금지 — 대표적인 상표명이 모티프에 없어야 한다."""
    banned = ["mickey", "pikachu", "hello kitty", "disney", "pokemon",
              "marvel", "snoopy", "doraemon"]
    for k in NEW:
        blob = " ".join(S.SPECS[k]["motifs"]).lower()
        for b in banned:
            assert b not in blob, f"{k}: 모티프에 '{b}'"
