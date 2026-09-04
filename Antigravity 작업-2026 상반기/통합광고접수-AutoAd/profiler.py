# ============================================================
#  profiler.py — 채널 성향 분석  (P1 스텁)
#  입력: 대출앱 chatrooms.json(방 목록) + 어댑터가 긁는 게시물/반응
#  출력: {tone, audience, topic, active_hours, banned_words} → db.add_channel
#  ⚠ chatrooms.json 의 방들은 대부분 B2B(대부업체 접수방).
#     소비자 광고채널과 성격이 반대라 먼저 분류해야 라우팅이 맞다.
# ============================================================
import json
from pathlib import Path
import db


def profile_from_chatrooms(chatrooms_path: str) -> list:
    """chatrooms.json → 채널 후보 목록.
    TODO(P1): 방 이름/최근메시지를 claude_engine 요약 프롬프트로 → 구조화 태그."""
    rooms = json.loads(Path(chatrooms_path).read_text(encoding="utf-8"))
    out = []
    for r in rooms:
        name = r.get("room") if isinstance(r, dict) else str(r)
        # TODO(P1): audience 분류(b2b_daebu vs consumer), tone/topic 태깅
        out.append({"platform": "kakao", "target_ref": name, "name": name,
                    "audience": "b2b_daebu"})
    return out


def sync_channels(chatrooms_path: str):
    """분석 결과를 channels 테이블에 upsert (기본 enabled=0)."""
    for c in profile_from_chatrooms(chatrooms_path):
        db.add_channel(**c)
