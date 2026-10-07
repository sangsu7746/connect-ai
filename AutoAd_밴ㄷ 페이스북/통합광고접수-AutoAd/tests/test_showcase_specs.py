# -*- coding: utf-8 -*-
"""SPECS 는 프로필의 컴플라이언스와 함께 써야 한다.

⚠ stickerme 프로필은 note 가 "타 IP·캐릭터 연상 표현 금지" 다. note 를 안 보고
  모티프를 지으면 타 IP 연상 표현이 그대로 광고로 나간다.
"""
import re
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import profiles
from content import showcase as S
from content import sd_backend

NEW = ["printcraft", "mirizip", "proheadshot", "colorcraft",
       "petportrait", "wallpreview", "nailpreview"]


def _spec_blob(spec: dict) -> str:
    """SPECS 한 항목의 label·스타일 프롬프트·모티프를 전부 이어붙인다."""
    parts = [spec.get("label", "")]
    for label, prompt in spec["styles"]:
        parts.append(label)
        parts.append(prompt)
    parts.extend(spec.get("motifs") or [])
    return " ".join(parts)


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


def test_banned_phrases_not_in_specs():
    """profiles/<key>.yaml 의 compliance.banned_phrases 가 SPECS 문구에 섞이면
    안 된다 — 이 파일의 docstring 이 말하는 '프로필의 컴플라이언스와 함께
    써야 한다'를 실제로 확인하는 테스트가 이제까지 없었다(리뷰 지적)."""
    for k in NEW:
        prof = profiles.load(k)
        banned = (prof.get("compliance") or {}).get("banned_phrases") or []
        blob = _spec_blob(S.SPECS[k])
        for phrase in banned:
            assert phrase not in blob, f"{k}: SPECS 에 금칙어 '{phrase}' 포함"


# sd_backend.NEG_FORCE 상수에서 토큰을 동적으로 파싱한다. 복제본이 아닌
# 실제 상수를 사용함으로써, NEG_FORCE 가 수정되면 이 테스트도 자동으로
# 그 변경을 반영하게 된다. 복제본이면 NEG_FORCE 를 추가/삭제해도 이 테스트는
# 계속 통과하면서 실제로는 검증 불가능한 거짓 안정성을 준다.
_NEG_FORCE_TOKENS = [t.strip() for t in sd_backend.NEG_FORCE.split(",") if t.strip()]

# ⚠ 기존 항목 2개는 예외다. 상품 자체가 인물 사진이라 NEG_FORCE 와 구조적으로
#   충돌한다 — Gemini 엔진에서만 성립하고 SD 로는 돌릴 수 없다.
#   weddingstudio: hands, portrait      lifealbum: people, person, portrait, hands
#   여기 추가하지 말 것. 새 업종이 걸리면 그건 고칠 결함이지 예외가 아니다.
_NEG_FORCE_EXCEPTIONS = {
    "weddingstudio": {"hands", "portrait"},
    "lifealbum": {"people", "person", "portrait", "hands"},
}


def _neg_force_hits(blob: str) -> set:
    """단어 경계 매칭 — 컨트롤러가 measured 한 방식과 같아야 한다.
    부분 문자열 매칭이면 'typographic' 이 'typography' 로 오탐된다."""
    low = blob.lower()
    hits = set()
    for tok in _NEG_FORCE_TOKENS:
        if re.search(r"\b" + re.escape(tok) + r"\b", low):
            hits.add(tok)
    return hits


def test_no_neg_force_token_in_specs():
    """CARD_ENGINE=sd 에서는 sd_backend.NEG_FORCE 가 모든 호출의 부정
    프롬프트에 강제로 붙는다(sd_backend.py 상단 주석). SPECS 스타일
    프롬프트에 그 토큰이 있으면 긍정·부정이 서로 싸운다 — proheadshot 은
    이걸 피했는데 petportrait 는 'portrait' 를 4개 스타일 모두에 넣어
    똑같은 실수를 했다(리뷰 Finding 1).

    exception 2개(weddingstudio·lifealbum) 를 뺀 SPECS 전체를 검사한다."""
    for k, spec in S.SPECS.items():
        hits = _neg_force_hits(_spec_blob(spec))
        allowed = _NEG_FORCE_EXCEPTIONS.get(k, set())
        offending = hits - allowed
        assert not offending, f"{k}: NEG_FORCE 토큰과 충돌 {sorted(offending)}"
