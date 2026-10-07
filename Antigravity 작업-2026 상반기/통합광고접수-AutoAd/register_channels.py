# ============================================================
#  register_channels.py — 발행 채널 등록 도구  (실가동 준비)
#  · 카카오 방은 대출앱 chatrooms.json 에서 가져옴 (기본 비활성)
#  · 밴드/페북은 add_band()/add_facebook() 또는 로그인 후 discover
#  ⚠ 안전: 모두 enabled=0(비활성)로 등록 → 검토 후 켜야 발행됨.
#  ⚠ 주의: chatrooms.json 방들은 대부분 B2B(대부업체 접수/답변방)!
#     소비자 광고 채널이 아니므로, 광고 대상 방만 골라 enable 할 것.
# ============================================================
import sys
import io
import json
from pathlib import Path
from collections import Counter

import config
import db


def _utf8_stdout():
    """콘솔 한글 깨짐 방지 — 스크립트로 실행될 때만.
    ⚠ 모듈 최상단에서 바꾸면 이 파일을 import 한 쪽의 출력이 망가진다
      (실제로 '[sync]' 계열에서 같은 결함을 겪었다)."""
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass


def import_kakao_rooms(enabled: bool = False, audience: str = "business") -> int:
    """대출앱 chatrooms.json → kakao 채널로 등록(기본 비활성)."""
    p = Path(config.KAKAO_PROJECT_DIR) / "chatrooms.json"
    if not p.exists():
        print(f"[skip] chatrooms.json 없음: {p}")
        return 0
    rooms = json.loads(p.read_text(encoding="utf-8"))
    n = 0
    for r in rooms:
        name = (r.get("room") if isinstance(r, dict) else str(r)) or ""
        name = name.strip()
        if not name:
            continue
        db.add_channel("kakao", name, name=name, audience=audience,
                       topic="담보", enabled=enabled)
        n += 1
    return n


def add_band(url: str, name: str, audience: str = "consumer", enabled: bool = False) -> int:
    return db.add_channel("band", url, name=name, audience=audience, enabled=enabled)


def add_facebook(url: str, name: str, audience: str = "consumer", enabled: bool = False) -> int:
    return db.add_channel("facebook", url, name=name, audience=audience, enabled=enabled)


def summary():
    chans = db.list_channels()
    by_plat = Counter(c["platform"] for c in chans)
    enabled = [c for c in chans if c.get("enabled")]
    print(f"\n등록 채널: 총 {len(chans)}개 " + (
        ", ".join(f"{k}:{v}" for k, v in by_plat.items()) or "없음"))
    print(f"활성(발행 대상): {len(enabled)}개")
    if enabled:
        for c in enabled:
            print(f"   ▸ [{c['platform']}] {c['name']} (성향:{c['audience']})")
    else:
        print("   (활성 0개 — 광고할 채널만 골라 set_channel_enabled 로 켜세요)")


if __name__ == "__main__":
    _utf8_stdout()
    db.init_db()
    n = import_kakao_rooms(enabled=False)
    print(f"[kakao] chatrooms.json 에서 {n}개 방 등록(비활성)")
    # 밴드/페북 예시(주석 해제하여 실제 채널로 교체):
    # add_band("https://band.us/band/XXXXXXXX", "우리동네 부동산 정보방", audience="consumer")
    # add_facebook("https://www.facebook.com/groups/XXXXXXXX/", "○○ 대출정보 그룹", audience="consumer")
    summary()
    print("\n다음: 광고 대상 채널만 켜기 →")
    print("  python -c \"import db; db.set_channel_enabled(<채널id>, True)\"")
    print("  (채널 id 확인: python -c \"import db,json; print(json.dumps(db.list_channels(),ensure_ascii=False,indent=2))\")")
