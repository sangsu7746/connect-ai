# 쓰레드 답글 자동광고 (1단계) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Threads 추천 피드의 글을 수집·판정해, 맥락에 맞는 1단 통합 답글(공감 + 홍보 + 추적링크)을 생성하고 점수에 따라 자동 발행 또는 승인 큐로 보내는 파이프라인을 만든다.

**Architecture:** `threads/` 패키지에 5개 모듈(harvester → gate → reply_writer → publisher → runner)을 만든다. `gate`와 `reply_writer`는 브라우저를 전혀 모르는 순수 로직이라 계정 없이 테스트된다. 발행부만 `BaseAdapter`를 상속하되 상한 계산은 오버라이드한다. 승인 큐·DB·대시보드·컴플라이언스 가드는 기존 AutoAd 것을 그대로 재사용한다.

**Tech Stack:** Python 3.14 · Selenium + webdriver-manager(기존 스택) · SQLite(`data/autoad.db`) · Gemini/Claude(`copy_engine` 제공자 전환) · pytest(신규)

**설계서:** `docs/superpowers/specs/2026-08-03-threads-reply-ad-design.md`

## Global Constraints

- **작업 디렉터리:** `D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd`
- **기존 코드 수정 최소화.** `channels/base.py`, `db.py` 스키마, `approval.py` 의 기존 함수 시그니처는 바꾸지 않는다. `db.py` 컬럼 추가가 필요하면 `_MIGRATIONS` 리스트에 등록해 멱등 마이그레이션으로 처리한다.
- **콘솔 인코딩:** Windows cp949. 로그의 한글이 깨져 보이는 것은 정상이며 파일·DB는 UTF-8이다. **테스트 assert 를 콘솔 출력에 의존시키지 말 것.**
- **`print()` 에 cp949 로 인코딩 안 되는 문자를 쓰지 말 것 — 크래시한다.**
  실측(Task 1): `print()` 안의 em dash 하나가 `UnicodeEncodeError` 로
  `python db.py` 를 죽였다. pytest 는 출력을 가로채 이 경로를 안 타므로
  **테스트는 전부 통과하는데 실제 실행만 죽는다.**
  - 금지(콘솔 출력 경로): `—`(em dash U+2014) · `⚠` · `✅` · `❌` · 이모지 전반
  - 허용: 한글 · ASCII · `→` · `─` · `·` · `…`
  - 대체 표기: `—`→`-`, `✅`→`[OK]`, `❌`→`[NG]`, `⚠`→`[!]`
  - 주석·docstring·`.md`·`.html` 파일 안에서는 무엇이든 써도 된다(UTF-8).
    제약은 **stdout 으로 나가는 문자열**에만 적용된다.
- **모든 신규 파일은 UTF-8**로 쓴다. 파일 읽기·쓰기 시 항상 `encoding="utf-8"` 을 명시한다.
- **안전 기본값:** 새로 추가하는 모든 안전장치 설정의 기본값은 "가장 안전한 값"이다. `THREADS_ENABLED=0`, dry_run 인자 기본값은 `True`.
- **`blocked` 와 `error` 를 섞지 않는다.** `blocked=True` = 안전장치가 막음(상한·시간대·쿨다운·미로그인), `error` = 진짜 실패(셀렉터·네트워크·차단). `channels/base.py:18-20` 주석 규칙을 따른다.
- **LLM 호출은 반드시 `_llm=None` 주입 가능하게.** 기존 `copy_engine.generate_copy(_llm=...)` 패턴과 동일. 테스트는 목 LLM으로 돈다.
- **금칙어·브랜드·의무표기는 프로필에서 온다.** 코드에 업종을 하드코딩하지 않는다 (`config.BANNED_PHRASES`, `config.BRAND_*`).
- **커밋 메시지는 한국어**, 기존 저장소 관행을 따른다. 커밋은 저장소 루트 `D:\` 에서 하되 이 프로젝트 경로만 스테이징한다.

---

## File Structure

**신규 생성**

| 파일 | 책임 |
|---|---|
| `threads/__init__.py` | 패키지 선언 |
| `threads/models.py` | `RawPost` · `Verdict` · `Reply` 데이터클래스 |
| `threads/gate.py` | 키워드 1차 + LLM 2차 판정 (브라우저 무관) |
| `threads/reply_writer.py` | 답글 생성 + 가드 (브라우저 무관) |
| `threads/automator.py` | Selenium 드라이버·쿠키·스텔스 (facebook_automator 이식) |
| `threads/harvester.py` | 추천 피드 수집 |
| `threads/publisher.py` | `ThreadsPublisher(BaseAdapter)` — 발행·삭제·상한 |
| `threads/runner.py` | 5개 모듈 조립 + 점수 분기 |
| `threads/prompts/screen.txt` | gate LLM 프롬프트 |
| `threads/prompts/reply.txt` | reply_writer LLM 프롬프트 |
| `tests/conftest.py` | pytest 설정 · 공용 픽스처 |
| `tests/fixtures/sample_posts.json` | gate 골든셋 |
| `tests/fixtures/feed_page.html` | harvester 파싱용 HTML 픽스처 |
| `tests/test_gate.py` · `test_reply_writer.py` · `test_publisher.py` · `test_runner.py` · `test_harvester.py` | 각 모듈 테스트 |

**수정**

| 파일 | 변경 |
|---|---|
| `config.py` | `THREADS_*` 설정 12개 추가 |
| `db.py` | `threads_targets` 테이블 + 헬퍼 함수 6개 |
| `profiles/photomagic.yaml` | `threads:` 섹션 추가 |
| `ui/approvals.html` | 원글 표시 블록 |
| `requirements.txt` | `pytest` 추가 |
| `login.py` | `threads` 대상 추가 |

**의존 순서:** models → (config, db) → gate → reply_writer → automator → harvester → publisher → runner → UI/login

---

## Task 1: 설정 · DB 스키마 · 데이터 모델

파이프라인 전체가 딛고 설 바닥. 이것 없이는 어떤 모듈도 저장할 곳이 없다.

**Files:**
- Create: `threads/__init__.py`, `threads/models.py`, `tests/conftest.py`, `tests/test_db_threads.py`
- Modify: `config.py`(끝에 추가), `db.py`(SCHEMA 상수 + 헬퍼 함수), `requirements.txt`

**Interfaces:**
- Produces:
  - `threads.models.RawPost(url, author, text, posted_at, likes, replies)` — 전부 필드, `likes`/`replies`는 `int` 기본 0
  - `threads.models.Verdict(passed: bool, score: int, reason: str, angle: str, retryable: bool)`
  - `threads.models.Reply(text: str, guard_notes: list)`
  - `db.threads_target_upsert(post: RawPost, profile_key: str) -> int` — 반환 = row id. `post_url` 중복이면 기존 id 반환하고 갱신하지 않음
  - `db.threads_target_verdict(target_id: int, score: int, verdict: str, reason: str)`
  - `db.threads_target_link_creative(target_id: int, creative_id: int)`
  - `db.threads_replies_today(auto_only: bool = False) -> int`
  - `db.threads_author_replied_since(author: str, days: int) -> bool`
  - `db.threads_targets_pending(limit: int) -> list` — `verdict='pending'` 인 행
  - `config.THREADS_*` 12개 상수

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/conftest.py`:
```python
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 프로젝트 루트를 import 경로에 넣는다 (tests/ 에서 실행해도 config·db 를 찾도록)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture
def temp_db(monkeypatch):
    """테스트마다 빈 DB. 실제 data/autoad.db 를 절대 건드리지 않는다."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import config
    monkeypatch.setattr(config, "DB_PATH", Path(path))
    import db
    monkeypatch.setattr(db, "DB_PATH", Path(path), raising=False)
    db.init_db()
    yield Path(path)
    try:
        Path(path).unlink()
    except OSError:
        pass
```

`tests/test_db_threads.py`:
```python
from threads.models import RawPost


def _post(url="https://www.threads.net/@a/post/1", author="@a"):
    return RawPost(url=url, author=author, text="사진 보정 뭐 쓰세요?",
                   posted_at="2026-08-03T10:00:00", likes=3, replies=1)


def test_upsert_returns_id_and_dedupes(temp_db):
    import db
    first = db.threads_target_upsert(_post(), "photomagic")
    second = db.threads_target_upsert(_post(), "photomagic")
    assert first == second, "같은 post_url 은 한 행이어야 한다"


def test_verdict_updates_score(temp_db):
    import db
    tid = db.threads_target_upsert(_post(), "photomagic")
    db.threads_target_verdict(tid, 87, "passed", "보정 고민 글")
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT score, verdict, reason FROM threads_targets WHERE id=?",
            (tid,)).fetchone()
    assert row["score"] == 87
    assert row["verdict"] == "passed"


def test_author_cooldown_detects_recent_reply(temp_db):
    import db
    tid = db.threads_target_upsert(_post(), "photomagic")
    assert db.threads_author_replied_since("@a", 30) is False
    db.threads_target_link_creative(tid, 999)
    assert db.threads_author_replied_since("@a", 30) is True


def test_pending_excludes_decided(temp_db):
    import db
    t1 = db.threads_target_upsert(_post("https://x/1", "@a"), "photomagic")
    db.threads_target_upsert(_post("https://x/2", "@b"), "photomagic")
    db.threads_target_verdict(t1, 10, "dropped", "관련 없음")
    pending = db.threads_targets_pending(10)
    assert len(pending) == 1
    assert pending[0]["author"] == "@b"
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_db_threads.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'threads'` (pytest 미설치면 먼저 `pip install pytest`)

- [ ] **Step 3: `requirements.txt` 에 pytest 추가**

파일 끝에 추가:
```
# 테스트 (신규 — threads/ 파이프라인 검증용)
pytest
```

설치:
```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && pip install pytest
```

- [ ] **Step 4: `threads/models.py` 작성**

`threads/__init__.py` 는 빈 파일로 생성한다.

`threads/models.py`:
```python
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
```

- [ ] **Step 5: `config.py` 에 설정 추가**

`config.py` 의 `REQUIRED_SECRETS` 줄 **앞**에 추가한다 (`if __name__` 블록보다 위):

```python
# ── 쓰레드 답글 자동광고 (1단계) ────────────────────────────
# 마스터 스위치. GLOBAL_DRY_RUN 과 AND — 둘 중 하나라도 꺼지면 실발행 없음.
THREADS_ENABLED = os.getenv("THREADS_ENABLED", "0") == "1"
# 쿠키 파일명을 결정한다. login.py --account 에 쓴 값과 반드시 같아야 한다.
THREADS_ACCOUNT = _secret("THREADS_ACCOUNT")
THREADS_DAILY_LIMIT = int(os.getenv("THREADS_DAILY_LIMIT", "20"))
# 자동 발행분 전용 상한. 총 상한과 분리하는 이유 —
# 자동분은 사람이 안 본 채 나간다. gate 가 오작동해 전부 고득점을 주면
# 총 상한만으로는 하루치가 통째로 무검수 발행된다. 사고 크기를 여기서 묶는다.
THREADS_AUTO_DAILY_LIMIT = int(os.getenv("THREADS_AUTO_DAILY_LIMIT", "3"))
# 자동 발행 임계. 골든셋 실측 전까지는 근거가 없으므로 높게 시작한다.
THREADS_AUTO_THRESHOLD = int(os.getenv("THREADS_AUTO_THRESHOLD", "90"))
THREADS_GATE_THRESHOLD = int(os.getenv("THREADS_GATE_THRESHOLD", "70"))
THREADS_REPLY_INTERVAL_MIN = int(os.getenv("THREADS_REPLY_INTERVAL_MIN", "180"))
THREADS_REPLY_INTERVAL_MAX = int(os.getenv("THREADS_REPLY_INTERVAL_MAX", "600"))
# 같은 사람에게 반복 답글이 붙는 것이 신고로 가는 가장 빠른 경로다.
THREADS_AUTHOR_COOLDOWN_DAYS = int(os.getenv("THREADS_AUTHOR_COOLDOWN_DAYS", "30"))
# 오래된 글의 답글은 아무도 보지 않는다. 노출 없는 리스크일 뿐이다.
THREADS_POST_MAX_AGE_MIN = int(os.getenv("THREADS_POST_MAX_AGE_MIN", "90"))
THREADS_REPLY_MAX_CHARS = int(os.getenv("THREADS_REPLY_MAX_CHARS", "280"))
THREADS_HARVEST_LIMIT = int(os.getenv("THREADS_HARVEST_LIMIT", "60"))
```

`.env.example` 끝에도 같은 키를 주석과 함께 추가한다:
```
# ── 쓰레드 답글 자동광고 ──
THREADS_ENABLED=0
THREADS_ACCOUNT=
THREADS_DAILY_LIMIT=20
THREADS_AUTO_DAILY_LIMIT=3
THREADS_AUTO_THRESHOLD=90
THREADS_GATE_THRESHOLD=70
```

- [ ] **Step 6: `db.py` 에 테이블과 헬퍼 추가**

`db.py` 의 `SCHEMA` 문자열 안, 마지막 `CREATE INDEX` 들 **앞**에 테이블을 추가한다:

```sql
CREATE TABLE IF NOT EXISTS threads_targets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    post_url     TEXT NOT NULL UNIQUE,
    author       TEXT NOT NULL,
    text         TEXT,
    posted_at    TEXT,
    likes        INTEGER DEFAULT 0,
    replies      INTEGER DEFAULT 0,
    profile_key  TEXT,
    score        INTEGER,
    verdict      TEXT DEFAULT 'pending',
    reason       TEXT,
    creative_id  INTEGER REFERENCES creatives(id),
    harvested_at TEXT NOT NULL,
    replied_at   TEXT
);
```

같은 `SCHEMA` 문자열 끝 인덱스 구역에 추가:
```sql
CREATE INDEX IF NOT EXISTS idx_threads_targets_author  ON threads_targets(author);
CREATE INDEX IF NOT EXISTS idx_threads_targets_verdict ON threads_targets(verdict);
```

`db.py` 끝(모듈 함수들 뒤, `if __name__` 블록 앞)에 헬퍼를 추가한다:

```python
# ── 쓰레드 답글 (threads/) ──────────────────────────────────
def threads_target_upsert(post, profile_key: str) -> int:
    """수집한 원글 1건 기록. post_url 이 이미 있으면 기존 id 를 그대로 준다.

    갱신하지 않는 이유 — 이미 판정·답글까지 끝난 글을 재수집했을 때
    score/verdict 를 덮어쓰면 같은 글에 두 번 답글이 나간다."""
    with get_conn() as conn:
        row = conn.execute("SELECT id FROM threads_targets WHERE post_url=?",
                           (post.url,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            """INSERT INTO threads_targets
               (post_url, author, text, posted_at, likes, replies,
                profile_key, verdict, harvested_at)
               VALUES (?,?,?,?,?,?,?,'pending',?)""",
            (post.url, post.author, post.text, post.posted_at,
             post.likes, post.replies, profile_key, _now()))
        return cur.lastrowid


def threads_target_verdict(target_id: int, score: int, verdict: str, reason: str = ""):
    """판정 결과 기록. verdict: pending | passed | dropped"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE threads_targets SET score=?, verdict=?, reason=? WHERE id=?",
            (score, verdict, reason, target_id))


def threads_target_link_creative(target_id: int, creative_id: int):
    """생성된 답글(creative)을 원글에 잇고 답글 시각을 찍는다.

    replied_at 이 작성자 쿨다운의 기준이 된다."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE threads_targets SET creative_id=?, replied_at=? WHERE id=?",
            (creative_id, _now(), target_id))


def threads_replies_today(auto_only: bool = False) -> int:
    """오늘 실제로 나간 답글 수.

    posts 를 센다(threads_targets 가 아니라). 답글이 생성됐어도
    승인 대기 중이면 계정에 부하를 준 것이 아니기 때문이다."""
    today = _now()[:10]
    sql = """SELECT COUNT(*) AS n FROM posts p
             JOIN creatives c ON c.id = p.creative_id
             WHERE c.kind='threads_reply'
               AND p.status='posted' AND substr(p.posted_at,1,10)=?"""
    params = [today]
    if auto_only:
        sql += " AND p.metrics_json LIKE '%\"auto\": true%'"
    with get_conn() as conn:
        return conn.execute(sql, params).fetchone()["n"]


def threads_author_replied_since(author: str, days: int) -> bool:
    """이 작성자에게 최근 days 일 안에 답글을 단 적이 있나."""
    import datetime as _dt
    cutoff = (_dt.datetime.now() - _dt.timedelta(days=days)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT 1 FROM threads_targets
               WHERE author=? AND replied_at IS NOT NULL AND replied_at >= ?
               LIMIT 1""", (author, cutoff)).fetchone()
    return row is not None


def threads_targets_pending(limit: int = 50) -> list:
    """아직 판정 안 된 원글."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM threads_targets WHERE verdict='pending'
               ORDER BY id LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 7: 테스트 통과 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_db_threads.py -v
```
Expected: 4 passed

기존 DB가 깨지지 않았는지도 확인한다:
```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python db.py && python config.py
```
Expected: 오류 없이 테이블 생성 로그 출력

- [ ] **Step 8: 커밋**

```bash
cd /d && git add "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/threads" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/tests" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/config.py" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/db.py" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/requirements.txt" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/.env.example"
```
```bash
cd /d && git commit -m "feat(threads): 답글 파이프라인 바닥 — 설정·threads_targets 테이블·값객체"
```

---

## Task 2: gate — 키워드 1차 + LLM 2차 판정

이 프로젝트에서 유일하게 예측 불가능한 부분. 브라우저를 모르므로 계정 없이 전부 테스트된다.

**Files:**
- Create: `threads/gate.py`, `threads/prompts/screen.txt`, `tests/test_gate.py`, `tests/fixtures/sample_posts.json`
- Modify: `profiles/photomagic.yaml`

**Interfaces:**
- Consumes: `threads.models.RawPost`, `threads.models.Verdict` (Task 1)
- Produces:
  - `gate.keyword_pass(text: str, tcfg: dict) -> tuple[bool, str]` — `(통과여부, 사유)`. 하드블록이 우선
  - `gate.screen(posts: list[RawPost], tcfg: dict, _llm=None) -> list[Verdict]` — 입력과 **같은 길이·같은 순서**로 반환
  - `gate.threads_config(profile: dict) -> dict` — 프로필에서 `threads:` 섹션을 꺼내고 기본값을 채움. 키: `interest_keywords`, `hard_block`, `landing`, `brand`

- [ ] **Step 1: 프로필에 `threads:` 섹션 추가**

`profiles/photomagic.yaml` 끝에 추가한다 (기존 키 구조는 건드리지 않는다):
```yaml
threads:
  interest_keywords:
    - 사진
    - 셀카
    - 프로필사진
    - 보정
    - 인생네컷
    - 증명사진
    - 포토샵
    - 필터
    - 화질
    - 흑백
  hard_block:
    - 부고
    - 삼가
    - 조의
    - 사고
    - 확진
    - 투병
    - 수술
    - 고소
    - 소송
    - 정당
    - 대선
    - 시위
    - 사망
  landing: "https://headjim-photomagic.web.app"
```

- [ ] **Step 2: 골든셋 픽스처를 만든다**

`tests/fixtures/sample_posts.json` — 최소 12건. 라벨은 사람이 붙인 정답이다.
```json
[
  {"url": "https://www.threads.net/@a/post/1", "author": "@a",
   "text": "셀카 보정 앱 뭐 쓰세요? 계속 어색하게 나와서 고민이에요",
   "posted_at": "2026-08-03T10:00:00", "label": "reply",
   "note": "관심 주제 + 도구 고민 = 정답 케이스"},
  {"url": "https://www.threads.net/@b/post/2", "author": "@b",
   "text": "증명사진 다시 찍어야 하나 배경만 바꾸면 될 것 같은데",
   "posted_at": "2026-08-03T10:05:00", "label": "reply"},
  {"url": "https://www.threads.net/@c/post/3", "author": "@c",
   "text": "오늘 점심 뭐 먹지 고민된다",
   "posted_at": "2026-08-03T10:10:00", "label": "skip",
   "note": "무관"},
  {"url": "https://www.threads.net/@d/post/4", "author": "@d",
   "text": "아버지 부고 소식 전합니다. 장례식장은 아래와 같습니다",
   "posted_at": "2026-08-03T10:15:00", "label": "skip",
   "note": "하드블록 — 절대 답글 금지"},
  {"url": "https://www.threads.net/@e/post/5", "author": "@e",
   "text": "어제 사고 사진 보정해서 올려도 되나요 너무 참혹한데",
   "posted_at": "2026-08-03T10:20:00", "label": "skip",
   "note": "관심 키워드(사진·보정)가 있지만 하드블록이 이긴다 — 핵심 케이스"},
  {"url": "https://www.threads.net/@f/post/6", "author": "@f",
   "text": "포토샵 배우는 중인데 누끼 따는 게 제일 어렵네요",
   "posted_at": "2026-08-03T10:25:00", "label": "reply"},
  {"url": "https://www.threads.net/@g/post/7", "author": "@g",
   "text": "정당 지지율 보고 놀랐다 이게 맞나",
   "posted_at": "2026-08-03T10:30:00", "label": "skip"},
  {"url": "https://www.threads.net/@h/post/8", "author": "@h",
   "text": "인생네컷 화질이 왜 이래요 확대하면 다 깨짐",
   "posted_at": "2026-08-03T10:35:00", "label": "reply"},
  {"url": "https://www.threads.net/@i/post/9", "author": "@i",
   "text": "주식 물타기 해야 하나 고민",
   "posted_at": "2026-08-03T10:40:00", "label": "skip"},
  {"url": "https://www.threads.net/@j/post/10", "author": "@j",
   "text": "필터 없이 찍은 사진이 제일 예쁜 것 같아요 요즘",
   "posted_at": "2026-08-03T10:45:00", "label": "borderline",
   "note": "관심 주제지만 '도구 필요 없다'는 취지 — 광고 붙이면 눈치 없어 보인다"},
  {"url": "https://www.threads.net/@k/post/11", "author": "@k",
   "text": "투병 중인데 사진이라도 남겨두고 싶어서요",
   "posted_at": "2026-08-03T10:50:00", "label": "skip",
   "note": "하드블록 — 사진 주제지만 절대 광고 금지"},
  {"url": "https://www.threads.net/@l/post/12", "author": "@l",
   "text": "흑백 보정 잘하는 법 아시는 분",
   "posted_at": "2026-08-03T10:55:00", "label": "reply"}
]
```

- [ ] **Step 3: 실패하는 테스트를 쓴다**

`tests/test_gate.py`:
```python
import json
from pathlib import Path

import pytest

from threads import gate
from threads.models import RawPost

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tcfg():
    return {
        "interest_keywords": ["사진", "셀카", "보정", "인생네컷", "증명사진",
                              "포토샵", "필터", "화질", "흑백", "프로필사진"],
        "hard_block": ["부고", "삼가", "사고", "확진", "투병", "정당", "사망"],
        "landing": "https://example.test",
        "brand": "PhotoMagic",
    }


def _golden():
    data = json.loads((FIXTURES / "sample_posts.json").read_text(encoding="utf-8"))
    return [(RawPost(url=d["url"], author=d["author"], text=d["text"],
                     posted_at=d["posted_at"]), d["label"]) for d in data]


def test_hardblock_beats_interest(tcfg):
    """관심 키워드가 있어도 하드블록이 이긴다. 이게 뒤집히면 부고 글에 광고가 붙는다."""
    ok, reason = gate.keyword_pass("어제 사고 사진 보정해서 올려도 되나요", tcfg)
    assert ok is False
    assert "사고" in reason


def test_keyword_pass_needs_interest(tcfg):
    assert gate.keyword_pass("오늘 점심 뭐 먹지", tcfg)[0] is False
    assert gate.keyword_pass("셀카 보정 앱 추천좀", tcfg)[0] is True


def test_screen_returns_same_length_and_order(tcfg):
    posts = [p for p, _ in _golden()]
    mock = lambda prompt: json.dumps({"results": [
        {"index": i, "score": 80, "reason": "ok", "angle": "도구 추천", "safe": True}
        for i in range(len(posts))]}, ensure_ascii=False)
    verdicts = gate.screen(posts, tcfg, _llm=mock)
    assert len(verdicts) == len(posts)


def test_hardblocked_posts_never_reach_llm(tcfg):
    """하드블록 글이 LLM 까지 가면 안 된다 — 비용도 낭비지만
    LLM 이 높은 점수를 줄 여지를 아예 없애는 것이 핵심."""
    posts = [p for p, _ in _golden()]
    seen = {}

    def mock(prompt):
        seen["prompt"] = prompt
        return json.dumps({"results": []}, ensure_ascii=False)

    gate.screen(posts, tcfg, _llm=mock)
    assert "부고" not in seen["prompt"]
    assert "투병" not in seen["prompt"]


def test_llm_failure_is_retryable_not_rejection(tcfg):
    """LLM 이 쓰레기를 뱉어도 예외로 죽지 않는다. 그리고 그 글들은
    '부적합'이 아니라 '아직 모름'(retryable)이어야 한다 —
    할당량이 떨어진 회차의 수집분을 영영 버리지 않기 위해."""
    posts = [p for p, _ in _golden()]
    verdicts = gate.screen(posts, tcfg, _llm=lambda p: "이건 JSON 이 아님")
    assert all(v.passed is False for v in verdicts)
    # 키워드에서 이미 떨어진 글은 retryable 이 아니다(재판정해도 결과가 같다)
    llm_stage = [v for v in verdicts if "LLM" in v.reason]
    assert llm_stage and all(v.retryable for v in llm_stage)


def test_keyword_rejection_is_not_retryable(tcfg):
    posts = [RawPost(url="u", author="@a", text="오늘 점심 뭐 먹지")]
    assert gate.screen(posts, tcfg, _llm=lambda p: "")[0].retryable is False


def test_unsafe_flag_forces_fail(tcfg):
    """LLM 이 safe=False 를 주면 점수가 높아도 떨어뜨린다."""
    posts = [RawPost(url="u", author="@a", text="셀카 보정 고민")]
    mock = lambda p: json.dumps({"results": [
        {"index": 0, "score": 99, "reason": "민감", "angle": "", "safe": False}]},
        ensure_ascii=False)
    assert gate.screen(posts, tcfg, _llm=mock)[0].passed is False
```

- [ ] **Step 4: 실패를 확인한다**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_gate.py -v
```
Expected: FAIL — `ImportError: cannot import name 'gate'`

- [ ] **Step 5: 프롬프트를 쓴다**

`threads/prompts/screen.txt`:
```
너는 SNS 마케팅 담당자다. 아래는 쓰레드(Threads) 추천 피드에서 수집한 글 목록이다.
우리 서비스는 "{brand}" 이고, 하는 일은 다음과 같다: {brand_desc}

각 글에 대해 "우리가 답글을 달았을 때 자연스럽고 환영받을 것인가"를 판정하라.

점수 기준 (0~100):
  90~100 : 이 주제로 도움을 구하고 있어, 도구를 알려주면 고마워할 글
  70~89  : 관련 주제이고 답글이 어색하지 않은 글
  40~69  : 주제는 스치지만 광고를 붙이면 뜬금없는 글
  0~39   : 무관하거나 답글이 폐가 되는 글

safe=false 로 표시해야 하는 글 (점수와 무관하게 답글 금지):
  · 부고·사고·질병·죽음 등 상심 중인 글
  · 정치·종교·젠더 등 분쟁 소지가 있는 글
  · 남을 비난하거나 싸우는 중인 글
  · 미성년자로 보이는 사람의 신상이 드러난 글

angle 에는 "어떤 각도로 답해야 자연스러운가"를 한 문장으로 쓴다.
광고 문구를 쓰는 것이 아니라, 답글의 방향만 적는다.

반드시 아래 JSON 형식만 출력하라. 설명 금지.
{"results": [{"index": 0, "score": 85, "reason": "...", "angle": "...", "safe": true}]}

--- 글 목록 ---
{posts_block}
```

- [ ] **Step 6: `threads/gate.py` 를 쓴다**

```python
# ============================================================
#  threads/gate.py — 답글 달 글 선별 (키워드 1차 → LLM 2차)
#  · 브라우저를 모른다. 계정 없이 골든셋으로 반복 검증 가능.
#  · 자동 발행 임계값은 이 모듈의 점수 분포에서 나온다.
# ============================================================
from __future__ import annotations

import json
import re
from pathlib import Path

import config
from threads.models import RawPost, Verdict

PROMPT_DIR = Path(__file__).parent / "prompts"
# LLM 한 번에 넘기는 글 수. 너무 크면 index 대응이 어긋나고, 너무 작으면 호출이 잦다.
BATCH_SIZE = 12


def threads_config(profile: dict) -> dict:
    """프로필에서 threads: 섹션을 꺼내고 빠진 값을 채운다."""
    t = dict((profile or {}).get("threads") or {})
    t.setdefault("interest_keywords", [])
    t.setdefault("hard_block", [])
    t.setdefault("landing", config.BRAND_SITE or "")
    t.setdefault("brand", config.BRAND_COMPANY or "")
    t.setdefault("brand_desc", config.PROFILE_NAME or "")
    return t


def keyword_pass(text: str, tcfg: dict) -> tuple:
    """1차 필터. 반환 (통과여부, 사유).

    ⚠ 하드블록이 관심 키워드를 이긴다. 순서가 뒤집히면
    '사고 사진 보정' 같은 글이 통과해 부고·사고 글에 광고가 붙는다."""
    body = text or ""
    for bad in tcfg.get("hard_block") or []:
        if bad and bad in body:
            return False, f"하드블록 '{bad}'"
    hits = [k for k in (tcfg.get("interest_keywords") or []) if k and k in body]
    if not hits:
        return False, "관심 키워드 없음"
    return True, f"키워드 {', '.join(hits[:3])}"


def _load_prompt() -> str:
    return (PROMPT_DIR / "screen.txt").read_text(encoding="utf-8")


def _posts_block(items: list) -> str:
    """LLM 에 넘길 글 목록. index 는 배치 안에서의 위치다."""
    lines = []
    for i, (_, post) in enumerate(items):
        body = (post.text or "").replace("\n", " ").strip()
        lines.append(f"[{i}] {body[:400]}")
    return "\n".join(lines)


def _extract_json(raw: str) -> dict:
    """copy_engine._extract_json 과 같은 규칙 (코드펜스·앞뒤 잡텍스트 허용)."""
    if not raw:
        raise ValueError("빈 응답")
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"JSON 없음: {raw[:120]!r}")
    return json.loads(text[start:end + 1])


def _call_llm(prompt: str) -> str:
    """copy_engine 의 제공자 전환을 그대로 재사용한다."""
    from content import copy_engine
    return copy_engine._call_llm(prompt)


def screen(posts: list, tcfg: dict, _llm=None) -> list:
    """입력과 같은 길이·같은 순서로 Verdict 를 돌려준다.

    1차에서 떨어진 글은 LLM 을 아예 보지 않는다. 비용도 있지만,
    하드블록 글에 LLM 이 높은 점수를 줄 여지를 없애는 것이 더 큰 이유다."""
    llm = _llm or _call_llm
    verdicts = [None] * len(posts)
    survivors = []                      # [(원래 index, post)]

    for idx, post in enumerate(posts):
        ok, reason = keyword_pass(post.text, tcfg)
        if ok:
            survivors.append((idx, post))
        else:
            verdicts[idx] = Verdict(passed=False, score=0, reason=reason)

    template = _load_prompt()
    for start in range(0, len(survivors), BATCH_SIZE):
        batch = survivors[start:start + BATCH_SIZE]
        prompt = (template
                  .replace("{brand}", str(tcfg.get("brand", "")))
                  .replace("{brand_desc}", str(tcfg.get("brand_desc", "")))
                  .replace("{posts_block}", _posts_block(batch)))
        try:
            data = _extract_json(llm(prompt))
            results = {int(r["index"]): r for r in data.get("results", [])}
        except Exception as e:
            # 배치 하나가 망가져도 나머지 배치는 계속 간다.
            # 판정 못 한 것은 '부적합'이 아니라 '아직 모름' → retryable.
            # (할당량이 떨어진 회차의 수집분을 통째로 버리지 않기 위해)
            for orig_idx, _ in batch:
                verdicts[orig_idx] = Verdict(
                    passed=False, score=0, retryable=True,
                    reason=f"LLM 판정 실패({type(e).__name__})")
            continue

        for local_i, (orig_idx, _) in enumerate(batch):
            r = results.get(local_i)
            if not r:
                verdicts[orig_idx] = Verdict(passed=False, score=0, retryable=True,
                                             reason="LLM 응답에 이 글이 없음")
                continue
            score = int(r.get("score") or 0)
            safe = bool(r.get("safe", False))
            # safe=False 면 점수가 아무리 높아도 떨어뜨린다.
            passed = safe and score >= config.THREADS_GATE_THRESHOLD
            verdicts[orig_idx] = Verdict(
                passed=passed, score=score,
                reason=str(r.get("reason") or ("" if safe else "LLM 안전판정 실패")),
                angle=str(r.get("angle") or ""))

    # 방어 — 어떤 경로로도 None 이 남지 않게
    return [v or Verdict(passed=False, score=0, retryable=True, reason="미판정")
            for v in verdicts]
```

- [ ] **Step 7: 테스트 통과 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_gate.py -v
```
Expected: 8 passed

- [ ] **Step 8: 커밋**

```bash
cd /d && git add "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/threads" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/tests" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/profiles/photomagic.yaml"
```
```bash
cd /d && git commit -m "feat(threads): gate — 키워드 1차·LLM 2차 판정 (하드블록 우선)"
```

---

## Task 3: reply_writer — 답글 생성과 가드

**Files:**
- Create: `threads/reply_writer.py`, `threads/prompts/reply.txt`, `tests/test_reply_writer.py`

**Interfaces:**
- Consumes: `RawPost`, `Verdict`, `Reply` (Task 1) · `gate.threads_config()` 의 dict (Task 2)
- Produces:
  - `reply_writer.validate(text: str, tcfg: dict) -> list[str]` — 문제 목록. 빈 리스트면 통과
  - `reply_writer.write(post: RawPost, verdict: Verdict, tcfg: dict, _llm=None) -> Reply` — 가드 위반 시 1회 재생성, 재차 위반이면 `ValueError`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_reply_writer.py`:
```python
import json

import pytest

from threads import reply_writer
from threads.models import RawPost, Verdict


@pytest.fixture
def tcfg():
    return {"interest_keywords": ["사진"], "hard_block": [],
            "landing": "https://photomagic.test", "brand": "PhotoMagic",
            "brand_desc": "사진 보정 웹서비스"}


@pytest.fixture
def post():
    return RawPost(url="https://www.threads.net/@a/post/1", author="@a",
                   text="셀카 보정 앱 뭐 쓰세요?", posted_at="2026-08-03T10:00:00")


@pytest.fixture
def verdict():
    return Verdict(passed=True, score=88, reason="보정 고민", angle="도구 추천")


def test_validate_rejects_foreign_link(tcfg):
    bad = "저는 Midjourney 써요 https://midjourney.com 좋아요"
    assert any("주소" in p for p in reply_writer.validate(bad, tcfg))


def test_validate_rejects_too_long(tcfg):
    assert any("길이" in p for p in reply_writer.validate("가" * 500, tcfg))


def test_validate_rejects_emoji_flood(tcfg):
    text = "좋아요" + "😀" * 8 + " https://photomagic.test"
    assert any("이모지" in p for p in reply_writer.validate(text, tcfg))


def test_validate_rejects_multiple_links(tcfg):
    text = "여기 https://photomagic.test 랑 https://photomagic.test/b 보세요"
    assert any("링크" in p for p in reply_writer.validate(text, tcfg))


def test_validate_rejects_unfilled_placeholder(tcfg):
    assert any("자리표시자" in p for p in reply_writer.validate("{brand} 좋아요", tcfg))


def test_validate_accepts_clean_reply(tcfg):
    good = "저도 그 고민 했어요. 배경만 정리해도 확 달라지더라고요 https://photomagic.test"
    assert reply_writer.validate(good, tcfg) == []


def test_write_retries_once_then_succeeds(post, verdict, tcfg):
    calls = []

    def mock(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps({"reply": "Midjourney 쓰세요 https://midjourney.com"},
                              ensure_ascii=False)
        return json.dumps({"reply": "저도 그 고민요. https://photomagic.test"},
                          ensure_ascii=False)

    result = reply_writer.write(post, verdict, tcfg, _llm=mock)
    assert "photomagic.test" in result.text
    assert len(calls) == 2
    assert result.guard_notes, "1차 위반 내역이 남아야 한다"


def test_write_raises_after_second_violation(post, verdict, tcfg):
    mock = lambda p: json.dumps({"reply": "https://midjourney.com 최고"},
                                ensure_ascii=False)
    with pytest.raises(ValueError):
        reply_writer.write(post, verdict, tcfg, _llm=mock)
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_reply_writer.py -v
```
Expected: FAIL — `ImportError: cannot import name 'reply_writer'`

- [ ] **Step 3: 프롬프트를 쓴다**

`threads/prompts/reply.txt`:
```
너는 쓰레드(Threads)를 오래 써 온 평범한 사용자다. 광고 담당자가 아니다.

아래 원글에 답글을 하나 쓴다.

원글 작성자: {author}
원글 내용: {post_text}
답글 각도: {angle}

우리 서비스: {brand} — {brand_desc}
링크: {landing}

규칙:
1. 먼저 원글에 진짜로 반응한다. 공감이든 경험이든 한두 문장.
2. 그 흐름에서 자연스럽게 서비스를 언급하고 링크를 붙인다.
3. 전체 {max_chars}자 이내. 짧을수록 좋다.
4. 링크는 {landing} 하나만. 다른 서비스 이름이나 주소는 절대 쓰지 않는다.
5. 원글을 그대로 인용하거나 따라 쓰지 않는다.
6. 이모지는 최대 2개.
7. "홍보합니다", "광고입니다" 같은 말은 쓰지 않는다. 동시에 속이지도 않는다.
8. 반말/존댓말은 원글 톤에 맞춘다.

절대 쓰면 안 되는 표현: {banned}

아래 JSON 형식만 출력하라. 설명 금지.
{"reply": "답글 전문"}
```

- [ ] **Step 4: `threads/reply_writer.py` 를 쓴다**

```python
# ============================================================
#  threads/reply_writer.py — 1단 통합 답글 생성 + 가드
#  · 브라우저를 모른다. 목 LLM 으로 전부 테스트된다.
#  · 가드는 copy_engine 의 실측 교훈을 그대로 가져온다
#    (자리표시자 미치환 → LLM 이 남의 서비스를 지어내 홍보한 사고).
# ============================================================
from __future__ import annotations

import json
import re
from pathlib import Path

import config
from threads.models import RawPost, Reply, Verdict

PROMPT_DIR = Path(__file__).parent / "prompts"

MAX_EMOJI = 2
_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_URL_RE = re.compile(
    r"\b(?:https?://)?([a-z0-9][a-z0-9.-]*\.(?:com|net|org|io|ai|app|kr|co\.kr|test))",
    re.I)
# 이모지 대략 범위 (정확한 유니코드 분류 대신 실용적 근사)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")


def _own_host(landing: str) -> str:
    return re.sub(r"^https?://", "", (landing or "").strip().lower()).split("/")[0]


def validate(text: str, tcfg: dict) -> list:
    """문제 목록을 돌려준다. 빈 리스트면 통과."""
    problems = []
    body = text or ""

    if _PLACEHOLDER_RE.search(body):
        problems.append("치환되지 않은 자리표시자")

    max_chars = config.THREADS_REPLY_MAX_CHARS
    if len(body) > max_chars:
        problems.append(f"길이 초과({len(body)}/{max_chars}자)")
    if not body.strip():
        problems.append("길이 부족(빈 답글)")

    emoji_n = len(_EMOJI_RE.findall(body))
    if emoji_n > MAX_EMOJI:
        problems.append(f"이모지 과다({emoji_n}개, 최대 {MAX_EMOJI})")

    own = _own_host(tcfg.get("landing", ""))
    hosts = [h.lower() for h in _URL_RE.findall(body)]
    for h in hosts:
        if not own or (h not in own and own not in h):
            problems.append(f"우리 것이 아닌 주소: {h}")
    if len(hosts) > 1:
        problems.append(f"링크 과다({len(hosts)}개, 최대 1개)")

    for b in config.BANNED_PHRASES:
        if b and b in body:
            problems.append(f"금칙어 '{b}'")

    return problems


def _load_prompt() -> str:
    return (PROMPT_DIR / "reply.txt").read_text(encoding="utf-8")


def _build_prompt(post: RawPost, verdict: Verdict, tcfg: dict) -> str:
    banned = ", ".join(f'"{b}"' for b in config.BANNED_PHRASES) or "(없음)"
    return (_load_prompt()
            .replace("{author}", post.author or "")
            .replace("{post_text}", (post.text or "").replace("\n", " ")[:600])
            .replace("{angle}", verdict.angle or "")
            .replace("{brand}", str(tcfg.get("brand", "")))
            .replace("{brand_desc}", str(tcfg.get("brand_desc", "")))
            .replace("{landing}", str(tcfg.get("landing", "")))
            .replace("{max_chars}", str(config.THREADS_REPLY_MAX_CHARS))
            .replace("{banned}", banned))


def _extract_reply(raw: str) -> str:
    if not raw:
        raise ValueError("빈 응답")
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"JSON 없음: {raw[:120]!r}")
    return str(json.loads(text[start:end + 1]).get("reply", "")).strip()


def _call_llm(prompt: str) -> str:
    from content import copy_engine
    return copy_engine._call_llm(prompt)


def write(post: RawPost, verdict: Verdict, tcfg: dict, _llm=None) -> Reply:
    """답글 1건 생성. 가드 위반이면 문제를 알려 1회 재생성하고,
    그래도 위반이면 예외를 던진다.

    잘라내기로 넘어가지 않는 이유 — 남의 서비스 이름을 지어낸 경우
    잘라내면 문장이 깨지고, 무엇보다 '왜 그랬는지'가 로그에 안 남는다."""
    llm = _llm or _call_llm
    base = _build_prompt(post, verdict, tcfg)

    prompt = base
    notes = []
    for attempt in (1, 2):
        text = _extract_reply(llm(prompt))
        problems = validate(text, tcfg)
        if not problems:
            return Reply(text=text, guard_notes=notes)
        notes.append(f"{attempt}차 위반: {', '.join(problems)}")
        prompt = (base + "\n\n[재작성] 다음 문제를 고쳐라: "
                  + ", ".join(problems)
                  + f". 링크는 반드시 {tcfg.get('landing', '')} 하나만 쓰고 "
                    "다른 서비스 이름·주소는 절대 쓰지 마라.")

    raise ValueError(f"답글 가드 통과 실패: {' / '.join(notes)}")
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_reply_writer.py -v
```
Expected: 8 passed

- [ ] **Step 6: 커밋**

```bash
cd /d && git add "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/threads" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/tests"
```
```bash
cd /d && git commit -m "feat(threads): reply_writer — 1단 통합 답글 생성·가드(링크1개·타사주소 차단)"
```

---

## Task 4: automator + harvester — Selenium 수집

**Files:**
- Create: `threads/automator.py`, `threads/harvester.py`, `tests/test_harvester.py`, `tests/fixtures/feed_page.html`
- Modify: `login.py`, `config.py`(`cookie_path` 에 threads 분기)

**Interfaces:**
- Consumes: `RawPost` (Task 1)
- Produces:
  - `automator.ThreadsAutomator(account: str, headless: bool = True)` — `.driver` / `.start()` / `.load_session() -> bool` / `.is_logged_in() -> bool` / `.save_cookies()` / `.quit()`
  - `harvester.parse_feed(html: str) -> list[RawPost]` — **브라우저 무관 순수 함수.** 테스트는 이것만 본다
  - `harvester.harvest(account: str, limit: int, headless: bool = True) -> list[RawPost]`

- [ ] **Step 1: HTML 픽스처를 만든다**

실제 threads.net DOM은 클래스명이 난독화되어 있으므로, **파싱은 클래스명이 아니라 구조·속성에 건다.** 픽스처는 그 계약을 고정한다.

`tests/fixtures/feed_page.html`:
```html
<div id="barcelona-page-layout">
  <div data-pressable-container="true">
    <a href="/@alice/post/AAA111" role="link"><time datetime="2026-08-03T10:00:00.000Z">1시간</time></a>
    <span dir="auto">셀카 보정 앱 뭐 쓰세요? 계속 어색하게 나와요</span>
    <a href="/@alice" role="link"><span>alice</span></a>
  </div>
  <div data-pressable-container="true">
    <a href="/@bob/post/BBB222" role="link"><time datetime="2026-08-03T10:20:00.000Z">40분</time></a>
    <span dir="auto">오늘 점심 뭐 먹지</span>
    <a href="/@bob" role="link"><span>bob</span></a>
  </div>
  <div data-pressable-container="true">
    <a href="/@carol/post/CCC333" role="link"><time datetime="2026-08-03T09:00:00.000Z">2시간</time></a>
    <span dir="auto">인생네컷 화질이 왜 이래요</span>
    <a href="/@carol" role="link"><span>carol</span></a>
  </div>
</div>
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_harvester.py`:
```python
from pathlib import Path

from threads import harvester

FIXTURES = Path(__file__).parent / "fixtures"


def _html():
    return (FIXTURES / "feed_page.html").read_text(encoding="utf-8")


def test_parse_feed_extracts_all_posts():
    posts = harvester.parse_feed(_html())
    assert len(posts) == 3


def test_parse_feed_builds_absolute_url():
    posts = harvester.parse_feed(_html())
    assert posts[0].url == "https://www.threads.net/@alice/post/AAA111"


def test_parse_feed_reads_author_and_text():
    posts = harvester.parse_feed(_html())
    assert posts[0].author == "@alice"
    assert "셀카 보정" in posts[0].text


def test_parse_feed_reads_posted_at():
    posts = harvester.parse_feed(_html())
    assert posts[0].posted_at.startswith("2026-08-03T10:00:00")


def test_parse_feed_survives_garbage():
    """DOM 이 바뀌어도 예외로 죽지 않고 빈 목록을 준다.
    죽으면 runner 가 멈추지만, 빈 목록이면 '수집 0건' 강등 로직이 받는다."""
    assert harvester.parse_feed("<html><body>nothing</body></html>") == []
    assert harvester.parse_feed("") == []
```

- [ ] **Step 3: 실패를 확인한다**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_harvester.py -v
```
Expected: FAIL — `ImportError: cannot import name 'harvester'`

- [ ] **Step 4: `threads/automator.py` 를 쓴다**

`facebook_automator.py:130-181` 의 드라이버·쿠키 패턴을 threads.net 도메인으로 이식한다.

```python
# ============================================================
#  threads/automator.py — Selenium 드라이버·쿠키·스텔스
#  이식: 페이스북-회원자동포스팅/app/facebook_automator.py:130-181
#  · 스레드도 Meta라 같은 탐지 계열을 받는다. 실전에서 살아남은
#    설정을 그대로 쓴다(navigator.webdriver 은폐·excludeSwitches).
#  · selenium 은 지연 import — 테스트가 브라우저 없이 돌아야 한다.
# ============================================================
from __future__ import annotations

import json
import time
from pathlib import Path

import config

THREADS_HOME = "https://www.threads.net"


def cookie_dir() -> Path:
    """페북 자동포스팅 프로그램의 쿠키 폴더를 함께 쓴다.
    (같은 PC·같은 사람이 관리하므로 흩어놓을 이유가 없다)"""
    root = Path(config.FB_PROJECT_APP_DIR).parent
    d = root / "data" / "cookies"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ThreadsAutomator:
    def __init__(self, account: str = "", headless: bool = True):
        self.account = account or config.THREADS_ACCOUNT
        self.headless = headless
        self.driver = None

    def _cookie_path(self) -> Path:
        return cookie_dir() / f"threads_{self.account}.json"

    def start(self):
        if self.driver is not None:
            return self.driver
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument("--lang=ko-KR")
        opts.add_argument("--disable-notifications")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        try:
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), options=opts)
        except Exception:
            self.driver = webdriver.Chrome(options=opts)
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
        self.driver.set_page_load_timeout(30)
        return self.driver

    def save_cookies(self):
        if not self.driver:
            return
        try:
            self._cookie_path().write_text(
                json.dumps(self.driver.get_cookies(), ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            pass

    def load_session(self) -> bool:
        """저장된 쿠키로 세션 복원. 성공하면 True."""
        self.start()
        p = self._cookie_path()
        if not p.exists():
            return False
        try:
            cookies = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        self.driver.get(THREADS_HOME)
        time.sleep(2)
        for c in cookies:
            try:
                self.driver.add_cookie(c)
            except Exception:
                continue
        self.driver.get(THREADS_HOME)
        time.sleep(3)
        return self.is_logged_in()

    def is_logged_in(self) -> bool:
        """작성창 진입점이 보이면 로그인 상태로 본다.
        (로그인 페이지의 '로그인' 버튼 유무보다 안정적이다)"""
        if not self.driver:
            return False
        try:
            from selenium.webdriver.common.by import By
            if self.driver.find_elements(By.CSS_SELECTOR, "[href='/login']"):
                return False
            return bool(self.driver.find_elements(
                By.CSS_SELECTOR, "[data-pressable-container], svg[aria-label]"))
        except Exception:
            return False

    def quit(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
```

- [ ] **Step 5: `threads/harvester.py` 를 쓴다**

```python
# ============================================================
#  threads/harvester.py — 추천 피드 수집
#  · parse_feed() 는 브라우저를 모르는 순수 함수 → 픽스처로 테스트.
#  · 셀렉터는 난독화된 클래스명이 아니라 구조·속성에 건다.
#    (Meta 는 클래스명을 수시로 바꾸지만 role/href/datetime 은 오래간다)
# ============================================================
from __future__ import annotations

import re
import time

import config
from threads.automator import THREADS_HOME, ThreadsAutomator
from threads.models import RawPost

# /@handle/post/XXXX 형태의 링크가 글 1건의 고유 주소다.
_POST_HREF_RE = re.compile(r'href="(/@([^/"]+)/post/([^"?]+))"')


def parse_feed(html: str) -> list:
    """피드 HTML 에서 글 목록을 뽑는다. 못 뽑으면 빈 목록(예외 아님).

    빈 목록으로 돌려주는 이유 — 예외로 죽으면 runner 가 멈추지만,
    빈 목록이면 '3회 연속 0건 → 자동 강등' 로직이 받아 처리한다."""
    if not html:
        return []
    try:
        return _parse(html)
    except Exception:
        return []


def _parse(html: str) -> list:
    from html import unescape

    posts, seen = [], set()
    # 글 카드 단위로 자른다.
    chunks = html.split('data-pressable-container="true"')[1:]
    for chunk in chunks:
        m = _POST_HREF_RE.search(chunk)
        if not m:
            continue
        path, handle, _pid = m.group(1), m.group(2), m.group(3)
        url = THREADS_HOME + path
        if url in seen:
            continue
        seen.add(url)

        tm = re.search(r'<time[^>]*datetime="([^"]+)"', chunk)
        posted_at = tm.group(1) if tm else ""

        # dir="auto" 스팬들이 본문. 여러 조각으로 쪼개져 오므로 이어 붙인다.
        parts = re.findall(r'<span[^>]*dir="auto"[^>]*>(.*?)</span>', chunk, re.DOTALL)
        text = " ".join(unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in parts)
        text = re.sub(r"\s{2,}", " ", text).strip()

        posts.append(RawPost(url=url, author=f"@{handle}",
                             text=text, posted_at=posted_at))
    return posts


def harvest(account: str = "", limit: int = 0, headless: bool = True) -> list:
    """추천 피드를 스크롤하며 limit 건까지 모은다.

    ⚠ 로그인 실패 시 빈 목록을 준다(예외 아님). 호출부가 '수집 0건'과
    같은 경로로 다루면 되고, 로그인 상태는 preflight 에서 따로 본다."""
    limit = limit or config.THREADS_HARVEST_LIMIT
    auto = ThreadsAutomator(account, headless=headless)
    try:
        if not auto.load_session():
            print("[threads:harvest] 세션 없음/만료 - python login.py threads 필요")
            return []
        auto.driver.get(THREADS_HOME)
        time.sleep(3)

        collected, stale_rounds = {}, 0
        for _ in range(20):                      # 스크롤 상한 (무한루프 방지)
            for p in parse_feed(auto.driver.page_source):
                collected.setdefault(p.url, p)
            if len(collected) >= limit:
                break
            before = len(collected)
            auto.driver.execute_script("window.scrollBy(0, window.innerHeight*2)")
            time.sleep(2)
            stale_rounds = stale_rounds + 1 if len(collected) == before else 0
            if stale_rounds >= 3:                # 더 안 늘면 그만
                break
        return list(collected.values())[:limit]
    finally:
        auto.quit()
```

- [ ] **Step 6: `login.py` 에 threads 대상을 추가한다**

`login.py` 를 열어 기존 대상 분기(band/facebook)를 찾고, 같은 형태로 threads 분기를 추가한다. 핵심은 **직접 로그인을 코드로 하지 않는 것** — 창을 띄워 사람이 직접 로그인(2FA·캡차 포함)하게 하고 쿠키만 저장한다.

```python
def login_threads(account: str):
    """창을 띄워 사람이 직접 로그인한다. 2FA·캡차는 사람이 통과한다.
    로그인이 끝나면 Enter — 그 시점의 쿠키를 저장한다."""
    from threads.automator import THREADS_HOME, ThreadsAutomator
    auto = ThreadsAutomator(account, headless=False)   # 반드시 창 띄움
    auto.start()
    auto.driver.get(THREADS_HOME + "/login")
    print(f"[threads:login] 열린 창에서 '{account}' 계정으로 로그인하세요.")
    input("        로그인 완료 후 Enter: ")
    if auto.is_logged_in():
        auto.save_cookies()
        print(f"[threads:login] 쿠키 저장 완료 → {auto._cookie_path()}")
    else:
        print("[threads:login] 로그인 상태가 확인되지 않았습니다. 다시 시도하세요.")
    auto.quit()
```

`config.py` 의 `cookie_path()` 에 threads 분기를 추가한다:
```python
    if platform == "threads":
        acc = account or THREADS_ACCOUNT
        if not acc:
            return None
        return _P(FB_PROJECT_APP_DIR).parent / "data" / "cookies" / f"threads_{acc}.json"
```
(함수 앞부분, 기존 `acc = account or (BAND_ACCOUNT if ...)` 줄 **위**에 넣는다.)

- [ ] **Step 7: 테스트 통과 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_harvester.py -v
```
Expected: 5 passed

- [ ] **Step 8: 커밋**

```bash
cd /d && git add "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/threads" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/tests" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/login.py" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/config.py"
```
```bash
cd /d && git commit -m "feat(threads): automator·harvester — Selenium 세션·추천피드 수집(구조기반 파싱)"
```

---

## Task 5: publisher — 발행·삭제·상한

**Files:**
- Create: `threads/publisher.py`, `tests/test_publisher.py`

**Interfaces:**
- Consumes: `ThreadsAutomator` (Task 4) · `channels.base.BaseAdapter`, `PostResult`
- Produces:
  - `ThreadsPublisher(account: str = "", headless: bool = None)` — `BaseAdapter` 상속, `platform = "threads"`
  - `.login() -> bool`
  - `.reply(post_url: str, text: str, dry_run: bool = True, auto: bool = False) -> PostResult`
  - `.delete_reply(reply_url: str, dry_run: bool = True) -> bool`
  - `._rate_ok(channel_id=None, auto: bool = False) -> bool` — **오버라이드**
  - `._rate_reason(channel_id=None, auto: bool = False) -> str` — **오버라이드**

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_publisher.py`:
```python
import pytest

import config
from threads.publisher import ThreadsPublisher


@pytest.fixture
def pub(monkeypatch):
    monkeypatch.setattr(config, "THREADS_ENABLED", True)
    monkeypatch.setattr(config, "GLOBAL_DRY_RUN", False)
    monkeypatch.setattr(config, "THREADS_DAILY_LIMIT", 20)
    monkeypatch.setattr(config, "THREADS_AUTO_DAILY_LIMIT", 3)
    p = ThreadsPublisher(account="tester")
    p._logged_in = True
    return p


def test_dry_run_never_touches_browser(pub):
    r = pub.reply("https://www.threads.net/@a/post/1", "안녕하세요", dry_run=True)
    assert r.ok is True and r.dry_run is True


def test_invalid_url_is_blocked_not_error(pub):
    r = pub.reply("https://facebook.com/groups/1", "hi", dry_run=False)
    assert r.blocked is True and r.ok is False


def test_master_switch_blocks(pub, monkeypatch):
    monkeypatch.setattr(config, "THREADS_ENABLED", False)
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True
    assert "THREADS_ENABLED" in r.error


def test_global_dry_run_blocks(pub, monkeypatch):
    monkeypatch.setattr(config, "GLOBAL_DRY_RUN", True)
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True
    assert "GLOBAL_DRY_RUN" in r.error


def test_not_logged_in_is_blocked(pub):
    pub._logged_in = False
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True
    assert "로그인" in r.error


def test_total_limit_blocks(pub, monkeypatch):
    monkeypatch.setattr("db.threads_replies_today", lambda auto_only=False: 20)
    assert pub._rate_ok() is False
    assert "총 상한" in pub._rate_reason()


def test_auto_limit_blocks_independently(pub, monkeypatch):
    """총 상한엔 여유가 있어도 자동분 상한이 차면 자동 발행은 막힌다.
    이게 gate 오작동 시 사고 크기를 묶는 장치다."""
    def counts(auto_only=False):
        return 3 if auto_only else 5
    monkeypatch.setattr("db.threads_replies_today", counts)
    assert pub._rate_ok(auto=False) is True
    assert pub._rate_ok(auto=True) is False
    assert "자동 발행 상한" in pub._rate_reason(auto=True)
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_publisher.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'threads.publisher'`

- [ ] **Step 3: `threads/publisher.py` 를 쓴다**

```python
# ============================================================
#  threads/publisher.py — 답글 발행·삭제
#  · BaseAdapter 를 상속하되 상한 계산은 오버라이드한다.
#    기존 _rate_ok() 는 CHANNEL_DAILY_LIMIT(=1)을 보는데, 답글은 전부
#    채널 1행(@계정핸들)에 귀속되므로 그대로 쓰면 하루 첫 건 이후
#    전부 차단된다. 이건 dry-run 에선 안 드러나고 실발행 첫날에야 보인다.
#  · selenium 은 실발행 시에만 지연 import.
# ============================================================
from __future__ import annotations

import time

import config
import db
from channels.base import BaseAdapter, PostResult


class ThreadsPublisher(BaseAdapter):
    platform = "threads"

    def __init__(self, account: str = "", headless: bool = None):
        self.account = account or config.THREADS_ACCOUNT
        self.headless = config.PUBLISH_HEADLESS if headless is None else headless
        self._auto = None
        self._logged_in = False

    # ── 상한 (오버라이드) ───────────────────────────────────
    def _rate_ok(self, channel_id=None, auto: bool = False) -> bool:
        if db.threads_replies_today() >= config.THREADS_DAILY_LIMIT:
            return False
        if auto and db.threads_replies_today(auto_only=True) >= \
                config.THREADS_AUTO_DAILY_LIMIT:
            return False
        return True

    def _rate_reason(self, channel_id=None, auto: bool = False) -> str:
        n = db.threads_replies_today()
        if n >= config.THREADS_DAILY_LIMIT:
            return f"오늘 답글 총 상한 도달({n}/{config.THREADS_DAILY_LIMIT}건) — 계정 보호"
        if auto:
            m = db.threads_replies_today(auto_only=True)
            if m >= config.THREADS_AUTO_DAILY_LIMIT:
                return (f"자동 발행 상한 도달({m}/{config.THREADS_AUTO_DAILY_LIMIT}건) — "
                        "무검수 발행량 제한. 승인 큐로는 계속 나갈 수 있습니다")
        return ""

    # ── 세션 ────────────────────────────────────────────────
    def _automator(self):
        if self._auto is None:
            from threads.automator import ThreadsAutomator
            self._auto = ThreadsAutomator(self.account, headless=self.headless)
        return self._auto

    def login(self, cred: dict = None) -> bool:
        """저장된 쿠키만으로 복원. 세션은 `python login.py threads` 로 만든다."""
        self._logged_in = self._automator().load_session()
        if not self._logged_in:
            print("[threads:login] 세션 만료 - python login.py threads 로 재로그인 필요")
        return self._logged_in

    @staticmethod
    def _valid_target(url: str) -> bool:
        return bool(url) and "threads.net" in url and "/post/" in url

    # ── 발행 ────────────────────────────────────────────────
    def reply(self, post_url: str, text: str, dry_run: bool = True,
              auto: bool = False) -> PostResult:
        if not self._valid_target(post_url):
            return PostResult(ok=False, blocked=True,
                              error=f"유효한 쓰레드 글 주소 아님: {post_url!r}")
        if not (text or "").strip():
            return PostResult(ok=False, blocked=True, error="빈 답글")

        if dry_run:
            self._log_dry("REPLY", post_url, text)
            return PostResult(ok=True, dry_run=True)

        if not config.THREADS_ENABLED:
            return PostResult(ok=False, blocked=True,
                error="THREADS_ENABLED=0 — 실발행 차단(안전). 켜려면 .env 에서 1로.")
        if config.GLOBAL_DRY_RUN:
            return PostResult(ok=False, blocked=True,
                error="GLOBAL_DRY_RUN=1 — 실발행 차단(안전). 켜려면 .env 에서 0으로.")
        if not self._rate_ok(auto=auto):
            return PostResult(ok=False, blocked=True, error=self._rate_reason(auto=auto))
        if not self._logged_in:
            return PostResult(ok=False, blocked=True,
                              error="로그인 필요 — login() 먼저 호출")

        try:
            return self._do_reply(post_url, text)
        except Exception as e:
            return PostResult(ok=False, error=f"발행 실패({type(e).__name__}): {e}")

    def _do_reply(self, post_url: str, text: str) -> PostResult:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        auto = self._automator()
        d = auto.driver
        d.get(post_url)
        time.sleep(3)

        # 캡차·차단 화면이면 즉시 멈춘다. 계속 두들기면 정지 수순이다.
        page = (d.page_source or "").lower()
        if "captcha" in page or "unusual activity" in page or "일시적으로 차단" in page:
            return PostResult(ok=False, blocked=True,
                error="캡차/차단 화면 감지 — 재시도 금지. THREADS_ENABLED=0 권장")

        boxes = d.find_elements(By.CSS_SELECTOR,
                                "div[contenteditable='true'], textarea")
        if not boxes:
            return PostResult(ok=False, error="답글 입력창 없음(셀렉터 변경 가능)")

        box = boxes[0]
        box.click()
        time.sleep(0.5)
        # 인간형 타이핑 — 한 번에 붙여넣으면 그 자체가 신호가 된다.
        for ch in text:
            box.send_keys(ch)
            time.sleep(0.02)
        time.sleep(1)
        box.send_keys(Keys.CONTROL, Keys.ENTER)
        time.sleep(4)

        # 발행됐는지 확인. 주소를 못 찾아도 발행 자체는 성공일 수 있다.
        perm = ""
        try:
            for a in d.find_elements(By.CSS_SELECTOR, "a[href*='/post/']"):
                href = a.get_attribute("href") or ""
                if self.account and f"@{self.account}" in href:
                    perm = href
                    break
        except Exception:
            pass
        return PostResult(ok=True, perm_url=perm or None,
                          error=None if perm else "발행됨(주소 확인 실패)")

    def delete_reply(self, reply_url: str, dry_run: bool = True) -> bool:
        """잘못 나간 답글 회수. 자동 발행을 켜는 이상 반드시 있어야 하는 손잡이."""
        if dry_run:
            self._log_dry("DELETE", reply_url)
            return True
        if not self._logged_in:
            return False
        from selenium.webdriver.common.by import By
        d = self._automator().driver
        d.get(reply_url)
        time.sleep(3)
        try:
            for btn in d.find_elements(By.CSS_SELECTOR, "svg[aria-label*='더'], [aria-label*='More']"):
                btn.click()
                time.sleep(1)
                for item in d.find_elements(By.XPATH, "//*[text()='삭제' or text()='Delete']"):
                    item.click()
                    time.sleep(1)
                    for ok in d.find_elements(By.XPATH, "//*[text()='삭제' or text()='Delete']"):
                        ok.click()
                        time.sleep(2)
                        return True
        except Exception:
            return False
        return False

    def quit(self):
        if self._auto is not None:
            self._auto.quit()
            self._auto = None
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_publisher.py -v
```
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
cd /d && git add "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/threads" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/tests"
```
```bash
cd /d && git commit -m "feat(threads): publisher — 발행·삭제·상한 오버라이드(자동분 별도 상한)"
```

---

## Task 6: runner — 조립과 점수 분기

**Files:**
- Create: `threads/runner.py`, `tests/test_runner.py`
- Modify: `db.py`(`_MIGRATIONS` 에 `posts.metrics_json` 은 이미 있으므로 변경 없음 — 확인만)

**Interfaces:**
- Consumes: 전 모듈
- Produces:
  - `runner.run_once(account: str = "", profile: dict = None, dry_run: bool = None) -> dict` — 반환 키: `harvested`, `passed`, `auto_published`, `queued`, `dropped`, `deferred`, `errors`(list[str])
    - `dropped` = 부적합으로 확정 폐기 · `deferred` = 판정 실패로 다음 회차 재판정 대기
  - `runner.ensure_channel(account: str) -> int` — `channels` 에 threads 행을 만들고 id 반환 (멱등)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_runner.py`:
```python
import pytest

import config
from threads.models import RawPost, Reply, Verdict


@pytest.fixture
def wired(temp_db, monkeypatch):
    """5개 모듈을 전부 목으로 갈아끼운다 — runner 의 분기만 본다."""
    from threads import runner

    posts = [RawPost(url=f"https://www.threads.net/@u{i}/post/{i}",
                     author=f"@u{i}", text="셀카 보정", posted_at="2026-08-03T10:00:00")
             for i in range(4)]
    # 점수: 95(자동) / 75(승인) / 50(폐기) / 92(자동)
    verdicts = [Verdict(True, 95, "r", "a"), Verdict(True, 75, "r", "a"),
                Verdict(False, 50, "낮음", ""), Verdict(True, 92, "r", "a")]

    monkeypatch.setattr(runner.harvester, "harvest", lambda *a, **k: posts)
    monkeypatch.setattr(runner.gate, "screen", lambda *a, **k: verdicts)
    monkeypatch.setattr(runner.reply_writer, "write",
                        lambda p, v, t, _llm=None: Reply(text="답글 https://x.test"))
    monkeypatch.setattr(config, "THREADS_AUTO_THRESHOLD", 90)
    monkeypatch.setattr(config, "THREADS_GATE_THRESHOLD", 70)
    monkeypatch.setattr(config, "THREADS_AUTO_DAILY_LIMIT", 5)
    monkeypatch.setattr(config, "THREADS_DAILY_LIMIT", 20)
    return runner


def test_routes_by_score(wired):
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["harvested"] == 4
    assert res["auto_published"] == 2      # 95, 92
    assert res["queued"] == 1              # 75
    assert res["dropped"] == 1             # 50


def test_auto_limit_spills_into_queue(wired, monkeypatch):
    """자동분 상한이 차면 고득점 건이 폐기되지 않고 승인 큐로 간다."""
    monkeypatch.setattr(config, "THREADS_AUTO_DAILY_LIMIT", 1)
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["auto_published"] == 1
    assert res["queued"] == 2              # 밀린 고득점 1건 + 원래 75점 1건


def test_author_cooldown_skips(wired, monkeypatch):
    monkeypatch.setattr("db.threads_author_replied_since",
                        lambda author, days: author == "@u0")
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["dropped"] == 2             # 원래 1건 + 쿨다운 1건


def test_empty_harvest_is_not_an_error(wired, monkeypatch):
    monkeypatch.setattr(wired.harvester, "harvest", lambda *a, **k: [])
    res = wired.run_once(account="tester", profile={"threads": {}}, dry_run=True)
    assert res["harvested"] == 0
    assert res["errors"] == []


def test_retryable_verdicts_stay_pending(wired, monkeypatch, temp_db):
    """LLM 판정 실패 건은 dropped 가 아니라 deferred 이고,
    DB 에는 pending 으로 남아 다음 회차가 다시 본다."""
    import db
    monkeypatch.setattr(wired.gate, "screen", lambda *a, **k: [
        Verdict(False, 0, "LLM 판정 실패(TimeoutError)", "", True) for _ in range(4)])
    res = wired.run_once(account="tester", profile={"threads": {
        "interest_keywords": ["보정"], "hard_block": [], "landing": "https://x.test"}},
        dry_run=True)
    assert res["deferred"] == 4
    assert res["dropped"] == 0
    assert len(db.threads_targets_pending(10)) == 4
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_runner.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'threads.runner'`

- [ ] **Step 3: `threads/runner.py` 를 쓴다**

```python
# ============================================================
#  threads/runner.py — 수집→판정→생성→분기→발행 조립
#  · 점수 분기가 이 시스템의 안전 경계다.
#    자동분 상한이 차면 고득점 건은 '폐기'가 아니라 '승인 큐'로 간다
#    (좋은 기회를 버리지 않으면서 무검수 발행량만 묶는다).
# ============================================================
from __future__ import annotations

import json
import random
import time

import config
import db
from threads import gate, harvester, reply_writer
from threads.publisher import ThreadsPublisher


def ensure_channel(account: str) -> int:
    """threads 채널 1행을 보장한다(멱등).

    채널 행을 두는 이유 — posts/creatives 가 channel_id 를 요구하고,
    대시보드 집계가 채널 단위로 돌기 때문. 코드 수정 없이 그대로 잡힌다."""
    ref = f"@{account}" if account and not account.startswith("@") else (account or "@threads")
    return db.add_channel("threads", ref, name=f"쓰레드 {ref}", audience="consumer")


def _ensure_campaign() -> int:
    """'쓰레드 답글' 상시 캠페인 1건(멱등)."""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM campaigns WHERE title=? LIMIT 1", ("쓰레드 답글",)).fetchone()
        if row:
            return row["id"]
    return db.add_campaign("쓰레드 답글", goal="유입", product=config.PROFILE_KEY)


def run_once(account: str = "", profile: dict = None, dry_run: bool = None) -> dict:
    """1회차 실행. 반환값은 대시보드·로그가 그대로 쓴다."""
    account = account or config.THREADS_ACCOUNT
    tcfg = gate.threads_config(profile if profile is not None else config.PROFILE)
    if dry_run is None:
        dry_run = not (config.THREADS_ENABLED and not config.GLOBAL_DRY_RUN)

    stats = {"harvested": 0, "passed": 0, "auto_published": 0,
             "queued": 0, "dropped": 0, "deferred": 0, "errors": []}

    posts = harvester.harvest(account, config.THREADS_HARVEST_LIMIT)
    stats["harvested"] = len(posts)
    if not posts:
        # 수집 0건은 오류가 아니다. 연속 0건 감시는 호출부(service/스케줄러)가 한다.
        return stats

    # 신선도 — 오래된 글의 답글은 아무도 보지 않는다.
    posts = [p for p in posts if _fresh_enough(p)]

    channel_id = ensure_channel(account)
    campaign_id = _ensure_campaign()
    verdicts = gate.screen(posts, tcfg)

    pub = ThreadsPublisher(account)
    if not dry_run:
        pub.login()

    try:
        for post, verdict in zip(posts, verdicts):
            target_id = db.threads_target_upsert(post, config.PROFILE_KEY)

            if not verdict.passed:
                if verdict.retryable:
                    # 판정을 못 한 것뿐이다. pending 으로 남겨 다음 회차에 다시 본다.
                    # dropped 로 찍으면 할당량이 떨어진 회차의 수집분이 영영 사라진다.
                    stats["deferred"] += 1
                else:
                    db.threads_target_verdict(target_id, verdict.score,
                                              "dropped", verdict.reason)
                    stats["dropped"] += 1
                continue

            if db.threads_author_replied_since(post.author, config.THREADS_AUTHOR_COOLDOWN_DAYS):
                db.threads_target_verdict(
                    target_id, verdict.score, "dropped",
                    f"작성자 쿨다운({config.THREADS_AUTHOR_COOLDOWN_DAYS}일)")
                stats["dropped"] += 1
                continue

            try:
                reply = reply_writer.write(post, verdict, tcfg)
            except Exception as e:
                db.threads_target_verdict(target_id, verdict.score, "dropped",
                                          f"답글 생성 실패: {e}")
                stats["dropped"] += 1
                stats["errors"].append(f"{post.url}: {e}")
                continue

            stats["passed"] += 1
            db.threads_target_verdict(target_id, verdict.score, "passed", verdict.reason)

            creative_id = db.add_creative(campaign_id, channel_id, {
                "reply": reply.text,
                "target_url": post.url,
                "target_author": post.author,
                "target_excerpt": (post.text or "")[:120],
                "score": verdict.score,
                "angle": verdict.angle,
                "profile_key": config.PROFILE_KEY,
                "brand": tcfg.get("brand", ""),
                "guard_notes": reply.guard_notes,
            }, kind="threads_reply")

            # ── 점수 분기 ──
            auto_ok = (verdict.score >= config.THREADS_AUTO_THRESHOLD
                       and pub._rate_ok(auto=True))
            if auto_ok:
                res = pub.reply(post.url, reply.text, dry_run=dry_run, auto=True)
                post_id = db.record_post(creative_id, channel_id,
                                         status="dry" if res.dry_run else
                                         ("posted" if res.ok else "failed"))
                db.update_post_status(post_id,
                                      "dry" if res.dry_run else ("posted" if res.ok else "failed"),
                                      perm_url=res.perm_url, error=res.error)
                _mark_auto(post_id)
                if res.ok:
                    db.threads_target_link_creative(target_id, creative_id)
                    stats["auto_published"] += 1
                else:
                    stats["errors"].append(f"{post.url}: {res.error}")
                if not dry_run:
                    time.sleep(random.randint(config.THREADS_REPLY_INTERVAL_MIN,
                                              config.THREADS_REPLY_INTERVAL_MAX))
            else:
                # 자동 상한이 찼거나 점수가 임계 미만 — 좋은 기회를 버리지 않고 승인 큐로.
                db.enqueue_approval(creative_id)
                stats["queued"] += 1
    finally:
        pub.quit()

    return stats


def _fresh_enough(post) -> bool:
    """THREADS_POST_MAX_AGE_MIN 이내 글만. 시각을 못 읽으면 통과시킨다
    (읽기 실패로 전부 버리는 쪽이 더 나쁘다)."""
    import datetime as dt
    if not post.posted_at:
        return True
    try:
        ts = dt.datetime.fromisoformat(post.posted_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    age_min = (dt.datetime.now(ts.tzinfo) - ts).total_seconds() / 60
    return age_min <= config.THREADS_POST_MAX_AGE_MIN


def _mark_auto(post_id: int):
    """자동 발행분 표시. db.threads_replies_today(auto_only=True) 가 이걸 센다."""
    with db.get_conn() as conn:
        conn.execute("UPDATE posts SET metrics_json=? WHERE id=?",
                     (json.dumps({"auto": True}), post_id))


if __name__ == "__main__":
    print(run_once(dry_run=True))
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/ -v
```
Expected: 전체 통과 — 누적 37건
(db 4 · gate 8 · reply_writer 8 · harvester 5 · publisher 7 · runner 5)

- [ ] **Step 5: 드라이런 종단 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m threads.runner
```
Expected: 세션이 없으므로 `{'harvested': 0, ...}` 출력 + "세션 없음/만료" 안내. **예외로 죽지 않는 것이 확인 포인트.**

- [ ] **Step 6: 커밋**

```bash
cd /d && git add "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/threads" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/tests"
```
```bash
cd /d && git commit -m "feat(threads): runner — 점수 분기(자동/승인/폐기)·쿨다운·신선도"
```

---

## Task 7: 승인 콘솔에 원글 표시

승인자가 원글을 못 보면 답글이 적절한지 판단할 수 없다. 이 화면 없이는 승인 게이트가 형식만 남는다.

**Files:**
- Modify: `approval.py`(`pending()` 반환에 답글 필드 추가), `ui/approvals.html`
- Create: `tests/test_approval_threads.py`

**Interfaces:**
- Consumes: `creatives.copy_json` 의 `threads_reply` 형식 (Task 6)
- Produces: `approval.pending()` 의 각 항목에 추가 키 — `is_reply: bool`, `reply_text: str`, `target_url: str`, `target_author: str`, `target_excerpt: str`, `score: int`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_approval_threads.py`:
```python
def test_pending_exposes_reply_fields(temp_db):
    import approval
    import db

    ch = db.add_channel("threads", "@tester", name="쓰레드 @tester")
    camp = db.add_campaign("쓰레드 답글")
    cid = db.add_creative(camp, ch, {
        "reply": "저도 그 고민 했어요 https://x.test",
        "target_url": "https://www.threads.net/@a/post/1",
        "target_author": "@a",
        "target_excerpt": "셀카 보정 앱 뭐 쓰세요?",
        "score": 78,
        "profile_key": "photomagic",
        "brand": "PhotoMagic",
    }, kind="threads_reply")
    db.enqueue_approval(cid)

    item = approval.pending()[0]
    assert item["is_reply"] is True
    assert item["target_author"] == "@a"
    assert item["score"] == 78
    assert "고민" in item["reply_text"]
    assert "셀카" in item["target_excerpt"]


def test_pending_keeps_normal_creatives_intact(temp_db):
    """기존 이미지 소재가 망가지지 않아야 한다."""
    import approval
    import db

    ch = db.add_channel("band", "https://band.us/band/1", name="테스트밴드")
    camp = db.add_campaign("일반 캠페인")
    cid = db.add_creative(camp, ch, {"headline": "제목", "body": "본문", "cta": "문의"},
                          image_path="x.png")
    db.enqueue_approval(cid)

    item = approval.pending()[0]
    assert item["is_reply"] is False
    assert item["caption"]["headline"] == "제목"
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_approval_threads.py -v
```
Expected: FAIL — `KeyError: 'is_reply'`

- [ ] **Step 3: `approval.py` 의 `pending()` 을 확장한다**

`approval.py:26-38` 의 `out.append({...})` 블록을 아래로 바꾼다. **기존 키는 하나도 빼지 않는다** (대시보드·텔레그램이 쓰고 있다):

```python
        is_reply = bool(cap.get("reply"))
        out.append({
            "approval_id": r["id"],
            "creative_id": r["creative_id"],
            "channel": ch["name"] if ch else "?",
            "platform": ch["platform"] if ch else "?",
            "caption": cap,
            "image_name": Path(img).name if img else None,
            # ⚠ 이 소재가 어느 업종 것인지. 서버는 대출 업종으로 떠 있으므로
            #   이걸 안 실어주면 타투 광고 검토 화면에 대출 상호가 붙는다.
            "profile_key": cap.get("profile_key") or "",
            "brand": cap.get("brand") or "",
            # ── 쓰레드 답글 ──
            # 승인자가 원글을 못 보면 답글이 적절한지 판단할 수 없다.
            # 이 필드들이 없으면 승인 게이트가 형식만 남는다.
            "is_reply": is_reply,
            "reply_text": cap.get("reply") or "",
            "target_url": cap.get("target_url") or "",
            "target_author": cap.get("target_author") or "",
            "target_excerpt": cap.get("target_excerpt") or "",
            "score": cap.get("score") or 0,
        })
```

- [ ] **Step 4: `ui/approvals.html` 에 원글 블록을 추가한다**

이 파일은 `el.innerHTML = \`...\`` 템플릿 문자열로 카드를 그리고(`ui/approvals.html:85-103`), 값은 이미 있는 `esc()` 헬퍼로 이스케이프한다(`:108-109` — 따옴표까지 escape). **그 패턴을 그대로 따른다.**

원글 본문은 **남이 쓴 문자열**이라 XSS 경로다. 새 함수를 만들지 말고 기존 `esc()` 를 쓴다.

`el.innerHTML` 템플릿의 `<div class="headline">` 줄 **앞**에 넣는다:

```javascript
          ${it.is_reply ? `
          <div class="orig-post">
            <div class="orig-meta">
              원글 ${esc(it.target_author)} · 관련도 ${esc(it.score)}점
              ${safeThreadHref(it.target_url)
                ? `· <a href="${esc(it.target_url)}" target="_blank" rel="noopener noreferrer">원글 보기</a>`
                : ''}
            </div>
            <div class="orig-text">${esc(it.target_excerpt)}</div>
          </div>
          <div class="reply-text">${esc(it.reply_text)}</div>` : ''}
```

그리고 `<div class="headline">`·`<div class="cap-body">`·`<div class="cta">` 세 줄은 답글일 때 비어 있으므로 감싼다:

```javascript
          ${it.is_reply ? '' : `
          <div class="headline">${esc(c.headline||'(제목 없음)')}</div>
          <div class="cap-body">${esc(c.body||'')}</div>
          <div class="cta">${esc(c.cta||'')}</div>`}
```

이미지 태그도 답글엔 없으므로 `:86` 줄을 감싼다:
```javascript
        ${it.is_reply ? '' : `<img src="/creatives/${encodeURIComponent(it.image_name||'')}" alt="전단" onerror="this.style.opacity=.15">`}
```

`esc()` 정의 **아래**에 링크 검증 함수를 추가한다. `esc()` 가 따옴표를 막아 속성 탈출은 안 되지만, `javascript:` URL 은 클릭 시 실행된다. 주소는 harvester 가 항상 `https://www.threads.net/...` 로 만들지만, 화면단에서도 한 번 더 막는다:

```javascript
// 원글 링크는 threads.net 만 허용한다. javascript: 등 다른 스킴 차단.
function safeThreadHref(u){
  return typeof u === 'string' && /^https:\/\/(www\.)?threads\.net\//.test(u);
}
```

`<style>` 블록에 최소 스타일을 추가한다:
```css
.orig-post{border-left:3px solid #bbb;background:#f7f7f7;padding:8px 12px;margin:0 0 10px}
.orig-meta{font-size:12px;color:#666}
.orig-text{margin-top:4px;white-space:pre-wrap}
.reply-text{white-space:pre-wrap;padding:2px 0 8px}
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/ -v
```
Expected: 전체 통과 (39건 — 누적 37 + 승인 2)

- [ ] **Step 6: 화면 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m uvicorn app:app --port 8010
```
브라우저에서 `http://127.0.0.1:8010/approvals` 를 열고, Task 6 드라이런으로 쌓인 항목에 원글 블록이 보이는지 확인한다. 기존 이미지 소재 항목이 깨지지 않았는지도 함께 본다.

- [ ] **Step 7: 커밋**

```bash
cd /d && git add "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/approval.py" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/ui/approvals.html" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/tests"
```
```bash
cd /d && git commit -m "feat(threads): 승인 콘솔에 원글 표시 — textContent 로 XSS 차단"
```

---

## Task 8: 골든셋 실측 — 임계값 확정

**자동 발행을 켜도 되는지 판정하는 관문.** 앞의 7개 태스크가 전부 통과해도, 이 태스크 결과가 나쁘면 `THREADS_AUTO_THRESHOLD` 를 켜지 않는다.

**Files:**
- Create: `tools/threads_goldenset.py`, `tests/test_gate_golden.py`
- Modify: `tests/fixtures/sample_posts.json`(12건 → 100건), `docs/superpowers/specs/2026-08-03-threads-reply-ad-design.md`(실측 결과 기록)

**Interfaces:**
- Consumes: `gate.screen()` (Task 2)
- Produces: `tools/threads_goldenset.py` 실행 시 콘솔 리포트 — 라벨별 점수 분포, 오탐(skip 인데 고득점) 목록, 권장 임계값

- [ ] **Step 1: 골든셋을 100건으로 늘린다**

`tests/fixtures/sample_posts.json` 에 88건을 더한다. 수집 방법:

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -c "import json;from threads import harvester;posts=harvester.harvest(limit=120);print(json.dumps([{'url':p.url,'author':p.author,'text':p.text,'posted_at':p.posted_at,'label':'','note':''} for p in posts],ensure_ascii=False,indent=2))" > data/golden_raw.json
```

`data/golden_raw.json` 을 열어 각 건에 `label` 을 손으로 채운다: `reply`(달아야 함) / `skip`(달면 안 됨) / `borderline`(애매). 채운 뒤 `tests/fixtures/sample_posts.json` 에 병합한다.

**라벨 비율 목표:** `skip` 이 최소 50건. 그중 **하드블록 계열(부고·사고·질병·정치)이 15건 이상**이어야 한다. 이 시스템이 저지르면 안 되는 사고가 정확히 거기서 나오기 때문에, 그 구간의 표본이 적으면 검증이 검증이 아니다.

- [ ] **Step 2: 리포트 도구를 쓴다**

`tools/threads_goldenset.py`:
```python
# ============================================================
#  tools/threads_goldenset.py — gate 실측 리포트
#  · 실제 LLM 을 호출한다(할당량 소모). 평소엔 돌리지 않는다.
#  · 이 리포트가 THREADS_AUTO_THRESHOLD 의 유일한 근거다.
# ============================================================
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                    # noqa: E402
from threads import gate                          # noqa: E402
from threads.models import RawPost                # noqa: E402

FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_posts.json"


def main():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    posts = [RawPost(url=d["url"], author=d["author"], text=d["text"],
                     posted_at=d.get("posted_at", "")) for d in data]
    labels = [d.get("label", "") for d in data]
    tcfg = gate.threads_config(config.PROFILE)

    print(f"[골든셋] {len(posts)}건 판정 시작 (제공자={config.COPY_PROVIDER})")
    verdicts = gate.screen(posts, tcfg)

    buckets = {}
    false_pos = []                     # skip 인데 고득점 — 가장 위험한 오류
    false_neg = []                     # reply 인데 저득점 — 기회 손실
    for d, label, v in zip(data, labels, verdicts):
        buckets.setdefault(label or "(무라벨)", []).append(v.score)
        if label == "skip" and v.score >= config.THREADS_GATE_THRESHOLD:
            false_pos.append((v.score, d["text"][:60], v.reason))
        if label == "reply" and v.score < config.THREADS_GATE_THRESHOLD:
            false_neg.append((v.score, d["text"][:60], v.reason))

    print("\n── 라벨별 점수 분포 ──")
    for label, scores in sorted(buckets.items()):
        scores.sort()
        n = len(scores)
        print(f"  {label:12s} n={n:3d}  최소={scores[0]:3d} "
              f"중앙={scores[n // 2]:3d} 최대={scores[-1]:3d}")

    print(f"\n── 오탐(skip 인데 {config.THREADS_GATE_THRESHOLD}점 이상) {len(false_pos)}건 ──")
    for score, text, reason in sorted(false_pos, reverse=True):
        print(f"  {score:3d}점 | {text} | {reason}")

    print(f"\n── 미탐(reply 인데 {config.THREADS_GATE_THRESHOLD}점 미만) {len(false_neg)}건 ──")
    for score, text, reason in sorted(false_neg):
        print(f"  {score:3d}점 | {text} | {reason}")

    skip_max = max(buckets.get("skip", [0]))
    print("\n── 판정 ──")
    print(f"  skip 최고점 = {skip_max}")
    if false_pos:
        print(f"  [NG] 자동 발행 금지 - 달면 안 되는 글이 {len(false_pos)}건 통과했습니다.")
        print("     프롬프트/하드블록을 고치고 다시 돌리세요.")
    else:
        rec = max(skip_max + 10, 85)
        print(f"  [OK] 오탐 0건. 권장 THREADS_AUTO_THRESHOLD = {rec}")
        print("     (skip 최고점보다 충분히 위. 그래도 승인 30건 검증을 먼저 하세요.)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 회귀 테스트를 쓴다**

`tests/test_gate_golden.py` — 실제 LLM 을 쓰므로 마커로 분리한다.
```python
import json
from pathlib import Path

import pytest

import config
from threads import gate
from threads.models import RawPost

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.golden
def test_hardblocked_never_scores_high():
    """이 시스템이 저지르면 안 되는 단 하나의 사고 —
    부고·사고·질병 글에 광고가 붙는 것. 여기서 막힌다."""
    data = json.loads((FIXTURES / "sample_posts.json").read_text(encoding="utf-8"))
    hard = [d for d in data if d.get("label") == "skip"
            and any(k in d["text"] for k in ("부고", "사고", "투병", "확진", "사망"))]
    assert len(hard) >= 5, "하드블록 표본이 너무 적어 검증이 성립하지 않는다"

    posts = [RawPost(url=d["url"], author=d["author"], text=d["text"]) for d in hard]
    verdicts = gate.screen(posts, gate.threads_config(config.PROFILE))
    passed = [(p.text[:40], v.score) for p, v in zip(posts, verdicts) if v.passed]
    assert passed == [], f"하드블록 글이 통과했다: {passed}"
```

`tests/conftest.py` 끝에 마커를 등록한다:
```python
# ⚠ 인자 이름을 config 로 쓰지 않는다 — 이 프로젝트의 config 모듈과 헷갈린다.
def pytest_configure(pyconfig):
    pyconfig.addinivalue_line(
        "markers", "golden: 실제 LLM 을 호출하는 골든셋 테스트 (할당량 소모)")


def pytest_collection_modifyitems(pyconfig, items):
    """평소엔 golden 을 건너뛴다. 돌리려면 `pytest -m golden`."""
    if pyconfig.getoption("-m") == "golden":
        return
    skip = pytest.mark.skip(reason="골든셋은 `pytest -m golden` 으로만")
    for item in items:
        if "golden" in item.keywords:
            item.add_marker(skip)
```

- [ ] **Step 4: 평소 테스트가 골든셋을 건너뛰는지 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/ -v
```
Expected: 39 passed, 1 skipped

- [ ] **Step 5: 실측을 돌린다**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python tools/threads_goldenset.py
```

**판정 기준:**
- 오탐 0건 → `THREADS_AUTO_THRESHOLD` 를 권장값으로 설정하고 다음으로
- 오탐 1건 이상 → **자동 발행을 켜지 않는다.** `threads/prompts/screen.txt` 의 안전 규칙과 `profiles/*.yaml` 의 `hard_block` 을 보강하고 Step 5를 다시 돌린다

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/ -m golden -v
```
Expected: 1 passed (하드블록 글 통과 0건)

- [ ] **Step 6: 결과를 설계서에 기록한다**

`docs/superpowers/specs/2026-08-03-threads-reply-ad-design.md` 의 "7. 테스트 전략" 뒤에 절을 추가한다:
```markdown
## 7-1. 골든셋 실측 결과 (YYYY-MM-DD)

- 표본: N건 (reply A / skip B / borderline C, 하드블록 계열 D건)
- 점수 분포: reply 중앙값 __ / skip 최고 __
- 오탐: __건
- 확정 `THREADS_AUTO_THRESHOLD` = __
```
빈칸은 실제 실행 결과로 채운다.

- [ ] **Step 7: 커밋**

```bash
cd /d && git add "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/tools/threads_goldenset.py" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/tests" "Antigravity 작업-2026 상반기/통합광고접수-AutoAd/docs"
```
```bash
cd /d && git commit -m "test(threads): 골든셋 100건 실측 — 자동 발행 임계값 확정"
```

---

## Task 9: 실가동 준비 — preflight·서비스 편입·런북

**Files:**
- Modify: `preflight.py`, `service.py`, `GO_LIVE.md`, `STATUS.md`
- Create: `tests/test_preflight_threads.py`

**Interfaces:**
- Consumes: 전 모듈
- Produces: `preflight.check_threads() -> dict` — 키 `ok: bool`, `items: list[tuple[str, bool, str]]`(항목명, 통과여부, 설명)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_preflight_threads.py`:
```python
import config
import preflight


def test_reports_missing_account(monkeypatch):
    monkeypatch.setattr(config, "THREADS_ACCOUNT", "")
    res = preflight.check_threads()
    assert res["ok"] is False
    names = [n for n, ok, _ in res["items"] if not ok]
    assert any("계정" in n for n in names)


def test_reports_disabled_master_switch(monkeypatch):
    monkeypatch.setattr(config, "THREADS_ACCOUNT", "tester")
    monkeypatch.setattr(config, "THREADS_ENABLED", False)
    res = preflight.check_threads()
    assert any("THREADS_ENABLED" in desc for _, _, desc in res["items"])


def test_never_raises_without_browser(monkeypatch):
    """preflight 는 읽기 전용이다. 브라우저를 띄우면 안 된다."""
    monkeypatch.setattr(config, "THREADS_ACCOUNT", "tester")
    res = preflight.check_threads()          # 예외 없이 돌아야 한다
    assert "items" in res
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/test_preflight_threads.py -v
```
Expected: FAIL — `AttributeError: module 'preflight' has no attribute 'check_threads'`

- [ ] **Step 3: `preflight.py` 에 점검을 추가한다**

기존 점검 함수들과 같은 형태로 아래를 추가한다. **브라우저를 띄우지 않는다** — preflight 는 읽기 전용이라는 것이 이 파일의 계약이다.

```python
def check_threads() -> dict:
    """쓰레드 답글 발행 준비 상태. 읽기 전용(브라우저 안 띄움)."""
    import config
    items = []

    acc = config.THREADS_ACCOUNT
    items.append(("쓰레드 계정", bool(acc),
                  acc or ".env 의 THREADS_ACCOUNT 미설정"))

    cookie = config.cookie_path("threads", acc) if acc else None
    has_cookie = bool(cookie and cookie.exists())
    items.append(("세션 쿠키", has_cookie,
                  str(cookie) if has_cookie else "python login.py threads 로 생성"))

    prof_ok = bool((config.PROFILE.get("threads") or {}).get("interest_keywords"))
    items.append(("프로필 threads 섹션", prof_ok,
                  config.PROFILE_KEY if prof_ok else
                  f"profiles/{config.PROFILE_KEY}.yaml 에 threads: 추가 필요"))

    landing = (config.PROFILE.get("threads") or {}).get("landing") or config.BRAND_SITE
    items.append(("랜딩 주소", bool(landing), landing or "미설정 — 답글에 링크가 안 붙는다"))

    # 스위치는 통과/실패가 아니라 '현재 상태' 보고다.
    items.append(("실발행 스위치", True,
                  f"THREADS_ENABLED={int(config.THREADS_ENABLED)} · "
                  f"GLOBAL_DRY_RUN={int(config.GLOBAL_DRY_RUN)} "
                  f"(둘 다 만족해야 실발행)"))
    items.append(("일일 상한", True,
                  f"총 {config.THREADS_DAILY_LIMIT}건 · "
                  f"자동 {config.THREADS_AUTO_DAILY_LIMIT}건 · "
                  f"임계 {config.THREADS_AUTO_THRESHOLD}점"))

    return {"ok": all(ok for _, ok, _ in items), "items": items}
```

`preflight.py` 의 `main()`(또는 전체 점검을 출력하는 함수)에서 `check_threads()` 를 호출해 결과를 출력하도록 한 줄 추가한다. 기존 출력 형식을 따른다.

- [ ] **Step 4: `service.py` 에 회차 실행을 편입한다**

`service.py` 의 스케줄러/감독 대상에 threads 회차를 추가한다. 기존 APScheduler 등록 패턴을 따르되, **`THREADS_ENABLED=0` 이면 등록 자체를 하지 않는다** (꺼진 기능이 로그를 더럽히지 않게).

```python
# 쓰레드 답글 회차 — 마스터 스위치가 꺼져 있으면 등록조차 하지 않는다.
if config.THREADS_ENABLED:
    from threads import runner as threads_runner

    def _threads_tick():
        try:
            stats = threads_runner.run_once()
            print(f"[threads] {stats}")
            # 수집 0건이 연속되면 셀렉터가 깨진 것이다. 조용히 도는 것보다 멈춘다.
            global _threads_empty_streak
            _threads_empty_streak = (_threads_empty_streak + 1
                                     if stats["harvested"] == 0 else 0)
            if _threads_empty_streak >= 3:
                config.THREADS_ENABLED = False
                print("[threads] [!] 3회 연속 수집 0건 - 셀렉터 변경 의심. 자동 정지.")
        except Exception as e:
            print(f"[threads] 회차 실패: {type(e).__name__}: {e}")

    _threads_empty_streak = 0
    scheduler.add_job(_threads_tick, "interval", minutes=45,
                      id="threads_reply", replace_existing=True)
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
cd "D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd" && python -m pytest tests/ -v && python preflight.py
```
Expected: 42 passed, 1 skipped · preflight 에 쓰레드 항목 출력

- [ ] **Step 6: `GO_LIVE.md` 에 런북을 추가한다**

파일 끝에 절을 추가한다:
```markdown
## 쓰레드 답글 자동광고 — 점화 순서

1. `python login.py threads --account <핸들>` — 창이 뜨면 직접 로그인(2FA·캡차 포함)
2. `python preflight.py` — 쓰레드 항목이 전부 ✅ 인지
3. `python -m threads.runner` — 드라이런. 수집·판정 건수 확인
4. `python tools/threads_goldenset.py` — 오탐 0건 확인. **1건이라도 있으면 중단**
5. `.env` 에 `THREADS_ENABLED=1` · `GLOBAL_DRY_RUN=0`
   — 단 `THREADS_AUTO_THRESHOLD=101` 로 두어 **자동 발행은 끈 채** 시작
6. 승인 콘솔(`/approvals`)에서 30건 처리 → 승인률 확인
   - 승인률 70% 미만이면 4번으로 되돌아간다
7. `THREADS_AUTO_THRESHOLD` 를 골든셋 권장값으로, `THREADS_AUTO_DAILY_LIMIT=3`
8. 1주 무사고면 상한 상향

### 비상 정지
```bash
# .env 에서 한 줄
THREADS_ENABLED=0
```
`service.py` 가 다음 회차부터 등록을 건너뛴다. 이미 나간 답글은
`/dashboard` 에서 확인 후 `ThreadsPublisher.delete_reply(url, dry_run=False)` 로 회수.
```

- [ ] **Step 7: `STATUS.md` 를 갱신한다**

"1. 진행 상태" 표에 행을 추가한다:
```markdown
| P4 | `threads/` — 쓰레드 답글 자동광고 1단계(수집→판정→생성→분기→발행) | ✅ dry-run 검증 · 실발행=골든셋 통과 후 |
```

"6. 다음 재개 지점"에 한 줄:
```markdown
- **쓰레드 답글 2단계** — 계정 풀·프록시·워밍업(하루 100건↑). 1단계 실측 후 별도 스펙.
```

- [ ] **Step 8: 커밋**

```bash
cd /d && git add "Antigravity 작업-2026 상반기/통합광고접수-AutoAd"
```
```bash
cd /d && git commit -m "feat(threads): preflight·service 편입 + 점화 런북 — 1단계 완성"
```

---

## 완료 기준

전부 만족해야 1단계가 끝난 것이다.

- [ ] `python -m pytest tests/ -v` → 전체 통과 (골든셋은 skip)
- [ ] `python -m pytest tests/ -m golden -v` → 하드블록 통과 0건
- [ ] `python tools/threads_goldenset.py` → 오탐 0건 + 권장 임계값 출력
- [ ] `python preflight.py` → 쓰레드 항목 전부 ✅
- [ ] `python -m threads.runner` → 예외 없이 통계 dict 반환
- [ ] `/approvals` 에서 원글이 보이고, 기존 이미지 소재도 안 깨짐
- [ ] `THREADS_ENABLED=0` 으로 두고 커밋 종료 (실발행은 사장님 결정)
