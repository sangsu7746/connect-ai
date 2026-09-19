# ============================================================
#  profiles.py — 업종 프로필 로더
#  엔진(오케스트레이터·채널어댑터·승인콘솔·대시보드·스케줄러)은 업종과 무관하다.
#  업종마다 달라지는 것(브랜드·의무표기·금칙어·소재 출처·접수 종착점)만
#  profiles/{key}.yaml 로 분리해 갈아끼운다.
#
#  전환: .env 의 AUTOAD_PROFILE=loan  (기본 loan)
#  목록: python profiles.py
# ============================================================
import os
from pathlib import Path

BASE = Path(__file__).parent
DIR = BASE / "profiles"

_REQUIRED = ["key", "name", "brand", "compliance", "content"]


def available() -> list:
    if not DIR.exists():
        return []
    return sorted(p.stem for p in DIR.glob("*.yaml") if not p.stem.startswith("_"))


def load(key: str = None) -> dict:
    """프로필 로드. 없으면 기동을 막는다(조용히 대출 설정으로 광고가 나가면 안 된다)."""
    key = (key or os.getenv("AUTOAD_PROFILE", "loan")).strip()
    path = DIR / f"{key}.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"업종 프로필 없음: {path}\n"
            f"  사용 가능: {', '.join(available()) or '(없음)'}\n"
            f"  .env 의 AUTOAD_PROFILE 을 확인하세요."
        )
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in _REQUIRED if k not in data]
    if missing:
        raise ValueError(f"{path.name}: 필수 항목 누락 {missing}")

    # 기본값 채우기 — 프로필이 일부만 적어도 동작하게
    data.setdefault("fallback_copy", {})
    data.setdefault("intake", {})
    b = data["brand"]
    for f in ("company", "roman", "phone", "region", "channels", "registered", "reg_no"):
        b.setdefault(f, "")
    c = data["compliance"]
    c.setdefault("disclaimer", "")
    c.setdefault("banned_phrases", [])
    c.setdefault("note", "")
    ct = data["content"]
    ct.setdefault("source", "flyers")
    ct.setdefault("flyers_dir", "")
    ct.setdefault("docs_dir", "")
    ct.setdefault("doc", "")            # 업종의 기본 설명서 파일명
    data["_path"] = str(path)
    return data


def resolve_dir(rel: str) -> Path:
    """프로필의 상대경로를 리포 기준 절대경로로. 절대경로면 그대로."""
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else (BASE / rel)


if __name__ == "__main__":
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    cur = os.getenv("AUTOAD_PROFILE", "loan")
    print(f"사용 가능한 업종 프로필 ({DIR})\n")
    for k in available():
        try:
            p = load(k)
            mark = "◉" if k == cur else "○"
            src = p["content"]["source"]
            print(f"  {mark} {k:14s} {p['name']}")
            print(f"      브랜드: {p['brand']['company'] or '(없음)'}"
                  f"   소재: {'기성 전단' if src == 'flyers' else '설명서에서 생성'}"
                  f"   접수: {p['intake'].get('target', 'none')}")
        except Exception as e:
            print(f"  ✗ {k:14s} 로드 실패: {e}")
    print(f"\n현재 선택(AUTOAD_PROFILE): {cur}")
