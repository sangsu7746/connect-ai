# -*- coding: utf-8 -*-
"""전단 성향(audience) 분리 + 수집 도구 안전장치.

이 파일이 지키는 것
  1) 자동인식 전단의 기본값은 '발행 제외' 다. mixed 로 돌아가면 사업자
     전용 광고가 개인 소비자 방으로 나간다(운영자 지시 정면 위반).
  2) 사이드카가 깨져도 예외로 캠페인을 죽이지 않고 '전건 제외' 로 무너진다.
  3) 수집 도구의 출력 파일명이 기존 17종 match 를 품지 않는다
     (registry._find 가 부분일치라, 품는 순간 기존 상품 전단이 바뀐다).
  4) 두 도구의 print() 문자열이 cp949 로 인코딩된다(콘솔이 통째로 죽는 사고).
"""
import ast
import importlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _reload_registry(monkeypatch, flyers_dir):
    from content import registry
    monkeypatch.setattr(registry, "FLYERS_DIR", Path(flyers_dir))
    return registry


def _mkflyer(d, name):
    Image.new("RGB", (40, 60), (10, 20, 30)).save(Path(d) / name)


# ── 1) 기본값은 발행 제외 ────────────────────────────────────
def test_discovered_defaults_to_excluded(tmp_path, monkeypatch):
    _mkflyer(tmp_path, "새전단-01.jpg")
    r = _reload_registry(monkeypatch, tmp_path)
    got = r.discovered()
    assert len(got) == 1
    assert got[0]["audience"] is None, "사이드카 없는 전단이 발행 후보가 됐다"
    assert got[0].get("blocked_reason")
    # 어느 채널에도 배정되지 않는다
    for aud in ("consumer", "business", "mixed"):
        assert not [p for p in r.by_audience(aud) if p.get("auto")]


def test_sidecar_assigns_audience_and_by_audience_respects_it(tmp_path, monkeypatch):
    _mkflyer(tmp_path, "사업자-01.jpg")
    _mkflyer(tmp_path, "개인-01.jpg")
    (tmp_path / "_audience.json").write_text(json.dumps(
        {"default": "exclude",
         "files": {"사업자-01.jpg": "business", "개인-01.jpg": "consumer"}},
        ensure_ascii=False), encoding="utf-8")
    r = _reload_registry(monkeypatch, tmp_path)
    biz = {p["match"] for p in r.by_audience("business") if p.get("auto")}
    con = {p["match"] for p in r.by_audience("consumer") if p.get("auto")}
    assert biz == {"사업자-01.jpg"}
    assert con == {"개인-01.jpg"}
    # 핵심: 사업자 전단이 소비자 채널 후보에 절대 없다
    assert "사업자-01.jpg" not in con


def test_sidecar_exclude_value_blocks_publication(tmp_path, monkeypatch):
    _mkflyer(tmp_path, "보류-01.jpg")
    (tmp_path / "_audience.json").write_text(
        json.dumps({"files": {"보류-01.jpg": "exclude"}}, ensure_ascii=False),
        encoding="utf-8")
    r = _reload_registry(monkeypatch, tmp_path)
    assert r.discovered()[0]["audience"] is None
    for aud in ("consumer", "business", "mixed"):
        assert not [p for p in r.by_audience(aud) if p.get("auto")]


# ── 2) 사이드카가 깨져도 안전하게 무너진다 ───────────────────
def test_broken_sidecar_fails_closed(tmp_path, monkeypatch):
    _mkflyer(tmp_path, "새전단-01.jpg")
    (tmp_path / "_audience.json").write_text("{ 이건 JSON 이 아니다", encoding="utf-8")
    r = _reload_registry(monkeypatch, tmp_path)
    meta = r.load_audience_map()          # 예외를 올리면 캠페인 전체가 죽는다
    assert meta["errors"], "깨진 사이드카를 조용히 넘겼다"
    assert r.discovered()[0]["audience"] is None


def test_sidecar_itself_is_not_picked_up_as_a_flyer(tmp_path, monkeypatch):
    _mkflyer(tmp_path, "_보류중-01.jpg")   # '_' 로 시작하면 후보에서 뺀다
    _mkflyer(tmp_path, "정상-01.jpg")
    r = _reload_registry(monkeypatch, tmp_path)
    assert [p["match"] for p in r.discovered()] == ["정상-01.jpg"]


# ── 3) 실제 폴더에서 기존 17종이 가로채이지 않았는가 ─────────
def test_existing_products_still_resolve_to_their_own_flyer():
    from content import registry
    for p in registry.products():
        if p.get("auto") or not p.get("flyer"):
            continue
        assert p["match"] in Path(p["flyer"]).name, \
            "%s 의 전단이 다른 파일로 바뀌었다: %s" % (p["key"], p["flyer"])


def test_ingest_output_names_never_contain_existing_match():
    from content import registry
    from tools import ingest_flyers
    assert not ingest_flyers.check_names()
    for e in ingest_flyers.MANIFEST:
        for p in registry.PRODUCTS:
            assert p["match"] not in e["out"], (e["out"], p["match"])


def test_ingest_manifest_has_no_mixed_audience():
    """구분 발행이 목적이다. mixed 를 쓰면 그 목적이 무너진다."""
    from tools import ingest_flyers
    for e in ingest_flyers.MANIFEST:
        assert e["audience"] in ("consumer", "business"), e


def test_ingest_refuses_to_write_into_the_source_folder(tmp_path):
    from tools import ingest_flyers
    with pytest.raises(SystemExit):
        ingest_flyers.guard_paths(tmp_path, tmp_path)
    with pytest.raises(SystemExit):
        ingest_flyers.guard_paths(tmp_path, tmp_path / "안쪽")


def test_ingest_manifest_declares_printed_mandatory(tmp_path):
    """이미 법정 필수기재가 인쇄된 그림은 넣지 않는다.

    pamphlet.stamp_mandatory_band() 는 그림을 보지 않고 13줄을 통째로 얹는다.
    이미 인쇄된 항목이 있으면 한 장에 등록번호가 두 번, 경고문구가 서로 다른
    자구로 두 번 나온다(법인매출유동화 전단에서 실제로 그랬다).
    """
    from tools import ingest_flyers
    for e in ingest_flyers.MANIFEST:
        assert e.get("printed_mandatory") == [], e["out"]


def test_ingest_rejects_entry_with_printed_mandatory():
    from tools import ingest_flyers
    e = dict(ingest_flyers.MANIFEST[0])
    e["printed_mandatory"] = ["reg_no"]
    r = ingest_flyers.process_entry(e, ingest_flyers.DEFAULT_SRC)
    assert r["ok"] is False and "이중표기" in r["why"]
    e2 = {k: v for k, v in ingest_flyers.MANIFEST[0].items()
          if k != "printed_mandatory"}
    r2 = ingest_flyers.process_entry(e2, ingest_flyers.DEFAULT_SRC)
    assert r2["ok"] is False, "printed_mandatory 를 안 적었는데 통과했다"


# ── 4) 선언한 old 를 실제로 대조하는가 (G1/G2) ───────────────
#
#  실측 사고(2026-08-09): old 는 어디에도 대조되지 않았다. 박스를 45px
#  어긋나게 적으면 '상담문의' 라벨을 새 번호로 덮고 인쇄된 옛 번호는 그대로
#  남은 그림이 전 검증을 통과했다. 아래 두 테스트가 그 구멍을 지킨다.
def _sample_entry():
    from tools import ingest_flyers
    for e in ingest_flyers.MANIFEST:
        if (ingest_flyers.DEFAULT_SRC / e["src"]).exists():
            return e
    pytest.skip("소스 폴더가 없다")


def test_wrong_old_string_is_rejected():
    import copy
    from tools import ingest_flyers
    e = copy.deepcopy(_sample_entry())
    for ph in e["phones"]:
        ph["old"] = "010-9999-9999"      # 이 전단에 없는 번호
    r = ingest_flyers.process_entry(e, ingest_flyers.DEFAULT_SRC)
    assert r["ok"] is False, "old 를 아무 번호로 적어도 통과한다"


def test_offset_box_is_rejected():
    import copy
    from tools import ingest_flyers
    e = copy.deepcopy(_sample_entry())
    b = list(e["phones"][0]["box"])
    b[1] -= 45
    b[3] -= 45
    e["phones"][0]["box"] = tuple(b)
    r = ingest_flyers.process_entry(e, ingest_flyers.DEFAULT_SRC)
    assert r["ok"] is False, "번호가 아닌 자리를 덮어쓰고도 통과한다"


def test_structure_gate_reads_digit_hyphen_layout():
    """G1 은 old 의 '숫자/하이픈' 배치와 정확히 맞아야 통과한다."""
    import numpy as np
    from tools import ingest_flyers as g
    a = np.zeros((20, 130), np.float32)
    x = 2
    for ch in "010-5681-2552":            # 숫자는 크게, 하이픈은 납작하게
        if ch == "-":
            a[9:11, x:x + 6] = 1.0
        else:
            a[2:18, x:x + 6] = 1.0
        x += 10
    assert g.structure_gate(a, 16, "010-5681-2552") == ""
    assert g.structure_gate(a, 16, "0507-1394-5685")   # 글자 수가 다르다
    assert g.structure_gate(a, 16, "053-661-2655")     # 하이픈 위치가 다르다


def test_auto_flyer_that_would_hijack_an_existing_product_is_blocked(tmp_path, monkeypatch):
    """운영자가 손으로 떨어뜨린 파일이 기존 상품 전단을 가로채지 못하게.

    registry._find() 는 `match in p.name` 부분일치다. 'A_토지담보대출-99.jpg'
    를 폴더에 넣으면 정렬 순서에 따라 toji 상품이 그 파일을 가리킨다(실증함).
    사이드카에 성향을 줘도 후보에서 빠져야 한다.
    """
    _mkflyer(tmp_path, "토지담보대출-260602_091730575.jpg")   # 원래 전단
    _mkflyer(tmp_path, "A_토지담보대출-신규-99.jpg")            # 나중에 떨어뜨린 것
    (tmp_path / "_audience.json").write_text(json.dumps(
        {"files": {"A_토지담보대출-신규-99.jpg": "business"}}, ensure_ascii=False),
        encoding="utf-8")
    r = _reload_registry(monkeypatch, tmp_path)
    toji = [p for p in r.products() if p["key"] == "toji"][0]
    assert toji.get("ambiguous"), "전단 후보가 둘인데 조용히 하나를 골랐다"
    assert toji["audience"] is None, "어느 것이 맞는지 모르는데 발행 후보로 뒀다"
    for aud in ("consumer", "business", "mixed"):
        assert not [p for p in r.by_audience(aud) if p["key"] == "toji"]


# ── 파트너 모집이 섞인 전단은 어느 채널에도 안 나간다 ────────
def test_partner_recruitment_flyer_is_not_publishable():
    """대출광고-03 하단에 '협력업체도 모집!' 패널이 인쇄돼 있다.

    이 전단은 mixed 라 개인·사업자 양쪽으로 나가고 있었다. 운영자 지시는
    파트너 모집 공고를 대출광고 채널 자동발행 대상에서 빼는 것이다.
    """
    from content import registry
    g3 = [p for p in registry.products() if p["key"] == "general_03"]
    assert g3, "general_03 이 사라졌다"
    assert g3[0]["audience"] is None
    for aud in ("consumer", "business", "mixed"):
        assert not [p for p in registry.by_audience(aud) if p["key"] == "general_03"]


# ── 6) 오타 교정('동'->'등')이 실제로 돌기를 지우는가 ────────
def test_typo_fix_actually_removes_the_spur():
    """실측 사고: 마스크가 돌기를 빗나가 ㄷ 밑변을 깎고 돌기는 남았는데
    '돌기 잉크 잔존 0' 검증이 통과했다. 같은 탐지기로 재검출해 막는다."""
    import numpy as np
    from PIL import Image as _I
    from tools import fix_flyer_phone as f
    src = ROOT / "content" / "templates" / "flyers"
    if not src.exists():
        pytest.skip("원본 전단 폴더가 없다")
    for tf in f.TYPO_FIXES:
        p = src / tf["file"]
        if not p.exists():
            pytest.skip("원본이 없다: %s" % tf["file"])
        arr = np.asarray(_I.open(p).convert("RGB")).astype(np.uint8).copy()
        ok, info = f.apply_typo_fix(arr, tf)
        assert ok, (tf["file"], tf["box"], info)
        a2, _, _ = f._typo_alpha(arr, tf["box"])
        again, _ = f._find_spur(a2)
        assert again is None, "수정 후에도 돌기가 남아 있다: %s" % tf["file"]


def test_typo_fix_rejects_a_misaligned_box():
    import numpy as np
    from PIL import Image as _I
    from tools import fix_flyer_phone as f
    src = ROOT / "content" / "templates" / "flyers"
    tf = dict(f.TYPO_FIXES[0])
    p = src / tf["file"]
    if not p.exists():
        pytest.skip("원본이 없다")
    x0, y0, x1, y1 = tf["box"]
    tf["box"] = (x0 + 40, y0, x1 + 40, y1)      # 옆 글자로 옮긴다
    arr = np.asarray(_I.open(p).convert("RGB")).astype(np.uint8).copy()
    ok, _ = f.apply_typo_fix(arr, tf)
    assert ok is False, "'동' 이 아닌 글자를 깎고도 성공으로 봤다"


# ── 5) cp949 콘솔 안전 ──────────────────────────────────────
@pytest.mark.parametrize("rel", ["tools/ingest_flyers.py", "tools/fix_flyer_phone.py",
                                 "content/registry.py"])
def test_print_strings_are_cp949_safe(rel):
    """실측 사고: print 에 cp949 밖 글자가 있어 백그라운드 작업이 통째로 죽었다."""
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print"):
            continue
        for lit in ast.walk(node):
            if isinstance(lit, ast.Constant) and isinstance(lit.value, str):
                try:
                    lit.value.encode("cp949")
                except UnicodeEncodeError:
                    bad.append((node.lineno, lit.value))
    assert not bad, bad
