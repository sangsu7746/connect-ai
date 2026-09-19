# ============================================================
#  threads/models.py — 파이프라인이 주고받는 값 객체
#  · 브라우저·DB·LLM 을 전혀 모른다. 순수 데이터.
# ============================================================
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawPost:
    """추천 피드에서 긁어온 원글 1건."""
    url: str
    author: str
    text: str = ""
    posted_at: str = ""          # ISO 시각. 못 읽으면 빈 문자열
    likes: int = 0
    replies: int = 0


@dataclass
class Verdict:
    """이 글에 답글을 달 것인가에 대한 판정."""
    passed: bool
    score: int = 0               # 0~100. 키워드 단계 탈락은 0
    reason: str = ""             # 왜 떨어졌나 / 왜 통과했나
    angle: str = ""              # 어떤 각도로 답할 것인가 (reply_writer 가 씀)
    # 판정 자체를 못 한 경우(LLM 할당량·네트워크·파싱 실패). 이 글은
    # '부적합'이 아니라 '아직 모름'이다. runner 가 pending 으로 남겨
    # 다음 회차에 재판정한다. 이걸 구분 안 하면 할당량이 떨어진 회차의
    # 수집분이 통째로 dropped 가 되어 영영 재시도되지 않는다.
    retryable: bool = False


@dataclass
class Reply:
    """생성된 답글."""
    text: str
    guard_notes: list = field(default_factory=list)   # 가드가 잡아 고친 내역
