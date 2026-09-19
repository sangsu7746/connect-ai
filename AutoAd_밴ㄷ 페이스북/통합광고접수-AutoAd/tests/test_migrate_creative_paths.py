# -*- coding: utf-8 -*-
"""옛 PC 경로를 현재 폴더로 옮긴다.

2026-09-08 실측: creatives.image_path 1,448건이 전부
C:\\Users\\Samsung\\OneDrive\\바탕 화면\\AutoAd_이사\\... 를 가리켜 실제 파일 0건.
파일명은 1,448건 모두 현재 data/creatives 에 있다 — 앞부분만 갈면 살아난다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import migrate_creative_paths as M


def test_remap_uses_basename(tmp_path):
    (tmp_path / "showcase_inkcraft_facebook_v0.png").write_bytes(b"x")
    old = r"C:\Users\Samsung\OneDrive\바탕 화면\AutoAd_이사\통합광고접수-AutoAd\data\creatives\showcase_inkcraft_facebook_v0.png"
    assert M.remap(old, tmp_path) == str(tmp_path / "showcase_inkcraft_facebook_v0.png")


def test_remap_returns_none_when_file_missing(tmp_path):
    old = r"C:\Users\Samsung\OneDrive\바탕 화면\없는파일.png"
    assert M.remap(old, tmp_path) is None


def test_remap_handles_posix_separators(tmp_path):
    """옛 경로가 / 로 저장돼 있어도 파일명을 뽑아야 한다."""
    (tmp_path / "doc_mirizip_band_v3.png").write_bytes(b"x")
    old = "C:/Users/Samsung/OneDrive/AutoAd_이사/data/creatives/doc_mirizip_band_v3.png"
    assert M.remap(old, tmp_path) == str(tmp_path / "doc_mirizip_band_v3.png")
