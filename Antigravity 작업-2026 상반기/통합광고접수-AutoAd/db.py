# ============================================================
#  db.py — AutoAd 공용 DB (신규 6테이블 + 접근자)
#  · 기존 대출 파이프라인(kakao_crawl.db)과 분리된 autoad.db.
#    단일 DB로 합치려면 config.AUTOAD_DB 를 kakao_crawl.db 로 지정.
#    (신규 테이블은 additive — 기존 crawled_messages/loan_records 무손상)
#  · 마이그레이션은 기존 대출앱 db.py 와 동일한 멱등 패턴
#    (CREATE TABLE IF NOT EXISTS + PRAGMA table_info → ALTER ADD COLUMN)
#  · P0-2
# ============================================================
import sqlite3
import json
from datetime import datetime
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── 스키마 ──────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    platform     TEXT NOT NULL,              -- band | cafe | facebook | kakao
    target_ref   TEXT NOT NULL,              -- 밴드/그룹 URL 또는 카톡 방 이름
    name         TEXT,
    audience     TEXT,                        -- b2b_daebu | consumer | mixed
    tone         TEXT,                        -- formal | friendly ...
    topic        TEXT,                        -- 담보 | 신용 | 사업자 ...
    active_hours TEXT,
    banned_words TEXT,                         -- JSON 배열
    profile_json TEXT,                         -- profiler 원본 태그
    enabled      INTEGER DEFAULT 0,            -- 0=미가동(안전 기본값)
    created_at   TEXT NOT NULL,
    UNIQUE(platform, target_ref)
);

CREATE TABLE IF NOT EXISTS campaigns (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    title          TEXT NOT NULL,
    goal           TEXT,                       -- 접수유도 | 인지도 ...
    product        TEXT,                        -- 광고 대상(대출상품 등)
    disclosures_id TEXT,                         -- 의무표기 세트 키
    status         TEXT DEFAULT 'draft',        -- draft | active | done
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creatives (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id INTEGER REFERENCES campaigns(id),
    channel_id  INTEGER REFERENCES channels(id),
    kind        TEXT DEFAULT 'image',          -- image | video
    copy_json   TEXT,                            -- {headline, body, cta, disclosures}
    image_path  TEXT,                            -- 생성된 팜플렛 PNG 경로
    approved    INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    creative_id  INTEGER REFERENCES creatives(id),
    channel_id   INTEGER REFERENCES channels(id),
    scheduled_at TEXT,
    posted_at    TEXT,
    status       TEXT DEFAULT 'dry',            -- dry | queued | posted | failed
    perm_url     TEXT,
    metrics_json TEXT,                            -- 댓글/좋아요/클릭 등
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consumers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT,
    phone          TEXT,                         -- 저장 시 암호화 권장(P2)
    amount         TEXT,
    collateral     TEXT,
    consent_at     TEXT,                         -- 개인정보 동의 시각(필수)
    source_channel TEXT,                          -- 유입 채널(전환추적)
    utm            TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    creative_id INTEGER REFERENCES creatives(id),
    state       TEXT DEFAULT 'pending',         -- pending | approved | edited | rejected
    reviewer    TEXT,
    decided_at  TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL
);

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

CREATE INDEX IF NOT EXISTS idx_creatives_campaign ON creatives(campaign_id);
CREATE INDEX IF NOT EXISTS idx_posts_status       ON posts(status);
CREATE INDEX IF NOT EXISTS idx_approvals_state    ON approvals(state);
CREATE INDEX IF NOT EXISTS idx_threads_targets_author  ON threads_targets(author);
CREATE INDEX IF NOT EXISTS idx_threads_targets_verdict ON threads_targets(verdict);
"""

# 향후 컬럼 추가 시 여기에 (테이블, 컬럼, DDL) 등록 → 멱등 마이그레이션
_MIGRATIONS = [
    # ("posts", "click_count", "ALTER TABLE posts ADD COLUMN click_count INTEGER DEFAULT 0"),
    # 접수 리드가 대출앱까지 실제로 등록됐는지 추적한다.
    # 이게 없으면 등록 실패한 리드가 consumers 에 조용히 남아 아무도 모르고,
    # 광고비 써서 만든 리드가 손님 전화 한 통 없이 사라진다.
    ("consumers", "registered",
     "ALTER TABLE consumers ADD COLUMN registered INTEGER DEFAULT 0"),
    ("consumers", "loan_id",
     "ALTER TABLE consumers ADD COLUMN loan_id INTEGER"),
    ("consumers", "last_error",
     "ALTER TABLE consumers ADD COLUMN last_error TEXT"),
    ("consumers", "retry_count",
     "ALTER TABLE consumers ADD COLUMN retry_count INTEGER DEFAULT 0"),
    ("consumers", "registered_at",
     "ALTER TABLE consumers ADD COLUMN registered_at TEXT"),
    # 다음 재시도 시각. 없으면 3분마다 계속 두들겨 상한이 1시간 만에 소진된다
    # (밤새 대출앱이 꺼져 있으면 아침엔 이미 포기 상태가 된다).
    ("consumers", "next_retry_at",
     "ALTER TABLE consumers ADD COLUMN next_retry_at TEXT"),
    # 등록 시도 중 표시 — 진행 중인 건을 다른 회차가 가로채 두 번 등록하는 것을 막는다.
    ("consumers", "attempt_at",
     "ALTER TABLE consumers ADD COLUMN attempt_at TEXT"),
    # 클라우드 수신함의 문서 id. 같은 리드가 두 번 배달돼도 한 건으로 알아보는 열쇠.
    # (클라우드를 '확인 응답할 때까지 재배달'로 바꾸면 중복 배달이 정상 동작이 된다)
    ("consumers", "cloud_id",
     "ALTER TABLE consumers ADD COLUMN cloud_id TEXT"),
    # 왜 못 나갔는지. 이게 없으면 대시보드가 '차단 3건'만 보여주고
    # 그게 상한 때문인지 세션 만료 때문인지 알 수 없다(=고칠 수가 없다).
    ("posts", "error", "ALTER TABLE posts ADD COLUMN error TEXT"),
    # 이 채널에 글을 올릴 때 쓸 계정. 저장된 쿠키 파일 이름을 결정한다.
    # 비어 있으면 config.BAND_ACCOUNT / FACEBOOK_ACCOUNT 를 쓴다.
    ("channels", "account", "ALTER TABLE channels ADD COLUMN account TEXT"),
    # 소재 재사용 쿨다운용. 같은 그림을 계속 우려먹으면 플랫폼 눈에 띈다.
    ("creatives", "last_posted_at", "ALTER TABLE creatives ADD COLUMN last_posted_at TEXT"),
    ("creatives", "post_count",
     "ALTER TABLE creatives ADD COLUMN post_count INTEGER DEFAULT 0"),
    # 이 채널에 어울리는 업종(profiles/*.yaml 의 key). 비면 광고 대상 아님.
    # 같은 대출 광고를 400곳에 뿌리는 대신, 모임 성격에 맞는 업종 광고를 보낸다.
    ("channels", "profile_key", "ALTER TABLE channels ADD COLUMN profile_key TEXT"),
    # 광고 링크 클릭 수. 성과 평가의 가장 빠른 신호다(접수보다 훨씬 자주 발생).
    ("creatives", "clicks", "ALTER TABLE creatives ADD COLUMN clicks INTEGER DEFAULT 0"),
    # 그 모임이 홍보 게시물을 허용하는가. allow | deny | unknown
    # ⚠ 이름만 보고 고르면 안 된다. '중고타투장터'는 이름과 달리 소개글에
    #   "홍보하는 페이지가 아닙니다"라고 적혀 있었고, 올린 글이 승인 대기에 걸렸다.
    ("channels", "ad_policy", "ALTER TABLE channels ADD COLUMN ad_policy TEXT"),
    ("channels", "rules_text", "ALTER TABLE channels ADD COLUMN rules_text TEXT"),
    ("channels", "rules_checked_at", "ALTER TABLE channels ADD COLUMN rules_checked_at TEXT"),
]


def _migrate_threads_targets_fk():
    """threads_targets.creative_id 에 FK 강제를 뒤늦게 붙인다(멱등).

    최초 배포(2026-08-03, 커밋 45459faad)는 REFERENCES 없이 나갔다. init_db() 의
    'CREATE TABLE IF NOT EXISTS' 는 이미 존재하는 테이블은 건드리지 않으므로,
    그 버전으로 한 번이라도 만들어진 실제 DB 는 SCHEMA 문자열이 FK 를 선언해도
    실제로는 강제되지 않는 채로 영원히 남는다. _MIGRATIONS(컬럼 추가 전용) 로는
    컬럼의 제약을 못 바꾸므로, 여기서 SQLite 표준 재구성 패턴(새 테이블 생성 →
    복사 → 교체)으로 직접 처리한다.

    새로 만드는 DB 는 SCHEMA 가 이미 REFERENCES 를 포함해 만들어 주므로
    이 함수는 그런 경우 아무 것도 하지 않는다(sqlite_master 검사로 판단)."""
    conn = sqlite3.connect(DB_PATH, isolation_level=None)   # autocommit — PRAGMA/DDL 즉시 적용
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='threads_targets'"
        ).fetchone()
        if row is None:
            return  # 아직 테이블이 없음 — 방금 SCHEMA 가 올바른 버전으로 만들 것이다
        if row["sql"] and "REFERENCES creatives" in row["sql"]:
            return  # 이미 최신 — 재구성 불필요

        print("[DB] threads_targets 재구성 - creative_id 에 FK 강제 추가")
        # 복사하는 동안 FK 를 꺼둔다. 켜둔 채로 하면, 옛 스키마에서 이미
        # 존재하지 않는 creatives.id 를 가리키던 행이 있을 때 복사 자체가
        # (지금 새로 추가하려는) 그 제약에 걸려 재구성이 중간에 실패한다.
        conn.execute("PRAGMA foreign_keys = OFF")

        dangling = conn.execute(
            """SELECT COUNT(*) AS n FROM threads_targets
               WHERE creative_id IS NOT NULL
                 AND creative_id NOT IN (SELECT id FROM creatives)"""
        ).fetchone()["n"]
        if dangling:
            print(f"[DB] 경고: threads_targets.creative_id 가 존재하지 않는 "
                  f"creatives.id 를 가리키는 행 {dangling}건 발견 - 데이터는 "
                  f"그대로 보존하지만, 재구성 이후로는 이런 값을 새로 넣거나 "
                  f"바꾸려는 시도가 FK 위반으로 막힌다.")

        conn.execute("BEGIN")
        try:
            conn.execute("""
                CREATE TABLE threads_targets__new (
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
                )
            """)
            # 컬럼을 명시적으로 나열한다 — SELECT * 는 나중에 컬럼이 하나 더
            # 생겼을 때 신구 테이블의 컬럼 순서가 어긋나도 조용히 통과해 버린다.
            conn.execute("""
                INSERT INTO threads_targets__new
                    (id, post_url, author, text, posted_at, likes, replies,
                     profile_key, score, verdict, reason, creative_id,
                     harvested_at, replied_at)
                SELECT id, post_url, author, text, posted_at, likes, replies,
                       profile_key, score, verdict, reason, creative_id,
                       harvested_at, replied_at
                FROM threads_targets
            """)
            conn.execute("DROP TABLE threads_targets")
            conn.execute("ALTER TABLE threads_targets__new RENAME TO threads_targets")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_threads_targets_author  "
                "ON threads_targets(author)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_threads_targets_verdict "
                "ON threads_targets(verdict)")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


def init_db():
    """테이블 생성 + 멱등 컬럼 마이그레이션."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for table, column, ddl in _MIGRATIONS:
            cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
            if cols and column not in cols:
                try:
                    conn.execute(ddl)
                    print(f"[DB] {table}.{column} 컬럼 추가")
                except Exception as e:
                    print(f"[DB] {table}.{column} 추가 실패: {e}")
    _migrate_threads_targets_fk()
    print(f"[DB] 초기화 완료 → {DB_PATH}")


def _now() -> str:
    return datetime.now().isoformat()


# ── channels ────────────────────────────────────────────────
def add_channel(platform, target_ref, name="", **kw) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO channels
               (platform, target_ref, name, audience, tone, topic,
                active_hours, banned_words, profile_json, enabled, account, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (platform, target_ref, name,
             kw.get("audience"), kw.get("tone"), kw.get("topic"),
             kw.get("active_hours"),
             json.dumps(kw.get("banned_words", []), ensure_ascii=False),
             json.dumps(kw.get("profile", {}), ensure_ascii=False),
             1 if kw.get("enabled") else 0,
             kw.get("account"),          # 이 채널에 글을 올릴 계정
             _now()))
        return cur.lastrowid


def list_channels(platform=None, enabled_only=False) -> list:
    q = "SELECT * FROM channels"
    cond, args = [], []
    if platform:
        cond.append("platform=?"); args.append(platform)
    if enabled_only:
        cond.append("enabled=1")
    if cond:
        q += " WHERE " + " AND ".join(cond)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(q, args)]


# 이미 나갔거나 지금 나가는 중인 상태. 상한 계산에 둘 다 포함해야 한다.
#  'posting' 을 빼면, 발행 중인 건이 아직 'posted' 가 아니라서
#  같은 채널의 다음 요청이 상한을 그냥 통과한다(중복 게시).
COUNTS_AS_POSTED = ("posted", "posting")


def posts_today(channel_id=None, exclude_id=None, platform=None) -> int:
    """오늘 나갔거나 나가는 중인 건수. channel_id 를 주면 그 채널만.

    exclude_id: 지금 발행 중인 그 건은 제외한다.
      ⚠ 이게 없으면 '발행 중' 표시를 한 자기 자신이 상한에 잡혀,
        상한이 N일 때 N번째 발행이 항상 스스로 막힌다(실측: 상한 1에서 첫 건부터 차단).

    platform: 그 플랫폼만 센다.
      ⚠ 계정 일일 상한은 '계정' 단위 보호 장치다. 플랫폼을 안 나누면
        밴드 발행이 페이스북 몫까지 써버려, 서로 다른 계정인데도
        한쪽이 다른 쪽을 막는다."""
    from datetime import date
    today = date.today().isoformat()
    marks = ",".join("?" * len(COUNTS_AS_POSTED))
    q = (f"SELECT COUNT(*) FROM posts WHERE status IN ({marks}) "
         f"AND substr(created_at,1,10)=?")
    args = list(COUNTS_AS_POSTED) + [today]
    if channel_id is not None:
        q += " AND channel_id=?"
        args.append(channel_id)
    if exclude_id is not None:
        q += " AND id<>?"
        args.append(exclude_id)
    if platform:
        q += " AND channel_id IN (SELECT id FROM channels WHERE platform=?)"
        args.append(platform)
    with get_conn() as c:
        return int(c.execute(q, args).fetchone()[0])


def last_post_time(platform=None):
    """마지막으로 실제 발행한 시각(datetime) 또는 None.
    발행 간격을 프로세스 메모리로만 기억하면 재시작 직후 간격이 0이 된다.

    platform: 그 플랫폼의 마지막 발행만 본다.
      발행 간격은 '한 계정이 연달아 올리는 것처럼 보이지 않게' 하는 장치다.
      플랫폼을 안 나누면 밴드에 올린 직후 페이스북 발행이 이유 없이 늦춰진다."""
    marks = ",".join("?" * len(COUNTS_AS_POSTED))
    q = (f"SELECT MAX(COALESCE(posted_at, created_at)) t FROM posts "
         f"WHERE status IN ({marks})")
    args = list(COUNTS_AS_POSTED)
    if platform:
        q += " AND channel_id IN (SELECT id FROM channels WHERE platform=?)"
        args.append(platform)
    with get_conn() as c:
        row = c.execute(q, args).fetchone()
    if not row or not row["t"]:
        return None
    from datetime import datetime as _dt
    try:
        return _dt.fromisoformat(row["t"])
    except Exception:
        return None


def mark_creative_posted(creative_id: int):
    with get_conn() as c:
        c.execute("UPDATE creatives SET last_posted_at=?, "
                  "post_count=COALESCE(post_count,0)+1 WHERE id=?",
                  (_now(), creative_id))


def image_cooldown_left(image_path: str, days: int) -> int:
    """같은 **이미지**를 다시 쓰기까지 남은 일수(0이면 지금 써도 됨).

    ⚠ creative 행 단위로 보면 안 된다. 캠페인을 돌릴 때마다 새 creative 행이
      생기므로 last_posted_at 이 늘 비어 있어 쿨다운이 한 번도 발동하지 않는다.
      플랫폼이 보는 건 '같은 그림'이지 DB 행이 아니다."""
    if days <= 0 or not image_path:
        return 0
    marks = ",".join("?" * len(COUNTS_AS_POSTED))
    with get_conn() as c:
        row = c.execute(
            f"SELECT MAX(COALESCE(p.posted_at, p.created_at)) t "
            f"FROM posts p JOIN creatives c ON p.creative_id = c.id "
            f"WHERE p.status IN ({marks}) AND c.image_path = ?",
            list(COUNTS_AS_POSTED) + [image_path]).fetchone()
    if not row or not row["t"]:
        return 0
    from datetime import datetime as _dt, timedelta
    try:
        last = _dt.fromisoformat(row["t"])
    except Exception:
        return 0
    left = (last + timedelta(days=days)) - _dt.now()
    return max(0, -(-int(left.total_seconds()) // 86400))


def add_click(track_key: str) -> bool:
    """클릭 1건 반영. track_key 는 '{campaign_id}-{channel_id}'.
    해당 크리에이티브를 찾아 clicks 를 올린다. 못 찾으면 False."""
    try:
        cid, chid = str(track_key).split("-", 1)
        cid, chid = int(cid), int(chid)
    except Exception:
        return False
    with get_conn() as c:
        cur = c.execute(
            "UPDATE creatives SET clicks=COALESCE(clicks,0)+1 "
            "WHERE campaign_id=? AND channel_id=?", (cid, chid))
        return cur.rowcount > 0


def creative_performance(limit: int = 50) -> list:
    """소재별 성과. 문구·이미지를 조정할 근거가 되는 표."""
    with get_conn() as c:
        rows = c.execute("""
            SELECT cr.id, cr.campaign_id, cr.channel_id, cr.image_path,
                   COALESCE(cr.clicks,0) clicks, cr.copy_json,
                   ch.name channel, ch.platform, ch.profile_key,
                   (SELECT COUNT(*) FROM posts p
                     WHERE p.creative_id=cr.id AND p.status='posted') posted,
                   (SELECT COUNT(*) FROM consumers s
                     WHERE s.source_channel = ch.platform || '_' || ch.id) leads
              FROM creatives cr JOIN channels ch ON cr.channel_id=ch.id
             ORDER BY clicks DESC, cr.id DESC LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]


def set_ad_policy(channel_id, policy: str, rules_text: str = ""):
    """그 채널이 홍보를 허용하는지 기록. policy: allow | deny | unknown"""
    with get_conn() as c:
        c.execute("UPDATE channels SET ad_policy=?, rules_text=?, rules_checked_at=? "
                  "WHERE id=?", (policy, (rules_text or "")[:2000], _now(), channel_id))


def set_channel_profile(channel_id, profile_key):
    """이 채널에 보낼 광고의 업종. None 이면 광고 대상에서 뺀다."""
    with get_conn() as conn:
        conn.execute("UPDATE channels SET profile_key=? WHERE id=?",
                     (profile_key or None, channel_id))


def channels_for_profile(profile_key: str, enabled_only: bool = True) -> list:
    """그 업종 광고를 보낼 채널 목록."""
    q = "SELECT * FROM channels WHERE profile_key=?"
    if enabled_only:
        q += " AND enabled=1"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(q, (profile_key,))]


def is_demo_channel(row) -> bool:
    """존재하지 않는 시연용 채널인가. 켜두면 발행이 늘 실패하는데
    원인이 '가짜 주소'라는 걸 알아채기 어렵다."""
    if not row:
        return False
    d = dict(row)
    blob = f"{d.get('name', '')} {d.get('target_ref', '')}".upper()
    return "DEMO" in blob or "데모" in blob


def set_channel_enabled(channel_id, enabled: bool, allow_demo: bool = False):
    """채널 켜기/끄기. 데모 채널을 켜는 것은 기본적으로 막는다."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
        if enabled and is_demo_channel(row) and not allow_demo:
            raise ValueError(
                f"데모 채널은 켤 수 없습니다: #{channel_id} {dict(row).get('name', '')}\n"
                f"  실제 채널을 register_channels.py 로 등록해 사용하세요.")
        conn.execute("UPDATE channels SET enabled=? WHERE id=?",
                     (1 if enabled else 0, channel_id))


# ── campaigns / creatives ───────────────────────────────────
def add_campaign(title, goal="", product="", disclosures_id="") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO campaigns (title, goal, product, disclosures_id, status, created_at)
               VALUES (?,?,?,?,'draft',?)""",
            (title, goal, product, disclosures_id, _now()))
        return cur.lastrowid


def add_creative(campaign_id, channel_id, copy: dict, image_path="", kind="image") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO creatives
               (campaign_id, channel_id, kind, copy_json, image_path, approved, created_at)
               VALUES (?,?,?,?,?,0,?)""",
            (campaign_id, channel_id, kind,
             json.dumps(copy, ensure_ascii=False), image_path, _now()))
        return cur.lastrowid


def mark_creative_approved(creative_id, approved=True):
    with get_conn() as conn:
        conn.execute("UPDATE creatives SET approved=? WHERE id=?",
                     (1 if approved else 0, creative_id))


# ── approvals (승인 큐) ─────────────────────────────────────
def enqueue_approval(creative_id) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO approvals (creative_id, state, created_at) VALUES (?,?,?)",
            (creative_id, "pending", _now()))
        return cur.lastrowid


def list_pending_approvals() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT a.*, c.copy_json, c.image_path, c.channel_id
               FROM approvals a JOIN creatives c ON a.creative_id=c.id
               WHERE a.state='pending' ORDER BY a.created_at""")]


def decide_approval(approval_id, state, reviewer="", note="") -> bool:
    """state: approved | edited | rejected — 승인 시 creative.approved 동기화.

    반환: 이번 호출이 실제로 상태를 바꿨는가(True) / 이미 처리된 건인가(False).

    ⚠ 조건 없이 UPDATE 하면 승인 버튼을 두 번 누를 때 발행이 두 번 나간다.
      발행은 되돌릴 수 없으므로 'pending 일 때만' 바꾸고 그 결과로 판단한다."""
    with get_conn() as conn:
        row = conn.execute("SELECT creative_id FROM approvals WHERE id=?",
                           (approval_id,)).fetchone()
        cur = conn.execute(
            "UPDATE approvals SET state=?, reviewer=?, note=?, decided_at=? "
            "WHERE id=? AND (state IS NULL OR state='pending')",
            (state, reviewer, note, _now(), approval_id))
        changed = cur.rowcount > 0
        if row and state == "approved" and changed:
            conn.execute("UPDATE creatives SET approved=1 WHERE id=?", (row["creative_id"],))
    return changed


# ── posts (발행 이력/성과) ──────────────────────────────────
def record_post(creative_id, channel_id, scheduled_at=None, status="dry") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO posts (creative_id, channel_id, scheduled_at, status, created_at)
               VALUES (?,?,?,?,?)""",
            (creative_id, channel_id, scheduled_at, status, _now()))
        return cur.lastrowid


def update_post_status(post_id, status, perm_url=None, error=None):
    with get_conn() as conn:
        posted = _now() if status == "posted" else None
        conn.execute(
            "UPDATE posts SET status=?, perm_url=?, error=?, "
            "posted_at=COALESCE(?, posted_at) WHERE id=?",
            (status, perm_url, (str(error)[:300] if error else None), posted, post_id))


# ── consumers (접수 PII) ────────────────────────────────────
def consumer_by_cloud_id(cloud_id: str):
    """클라우드 문서 id 로 이미 받아둔 리드를 찾는다(없으면 None).
    재배달된 리드를 새 접수로 만들지 않기 위한 관문."""
    if not cloud_id:
        return None
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM consumers WHERE cloud_id=?",
                           (cloud_id,)).fetchone()
    return dict(row) if row else None


def add_consumer(name, phone, amount="", collateral="", consent_at=None,
                 source_channel="", utm="", created_at=None, cloud_id=None) -> int:
    """created_at 은 '실제 접수 시각'. 클라우드 경유 리드는 동기화 시각이 아니라
    폼 제출 시각을 넘겨야 일자별 집계가 맞는다(미지정 시 현재 시각)."""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO consumers
               (name, phone, amount, collateral, consent_at, source_channel, utm,
                created_at, cloud_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (name, phone, amount, collateral, consent_at or created_at or _now(),
             source_channel, utm, created_at or _now(), cloud_id or None))
        return cur.lastrowid


def mark_consumer_registered(consumer_id: int, loan_id):
    """대출앱 등록 성공 기록."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE consumers SET registered=1, loan_id=?, last_error=NULL, "
            "registered_at=? WHERE id=?",
            (loan_id, _now(), consumer_id))


# 재시도 간격(분). 뒤로 갈수록 뜸해지고 마지막 값에서 고정된다.
RETRY_BACKOFF_MIN = [3, 6, 12, 30, 60]
# 이 시간이 지나도록 못 넣은 리드는 자동 재시도를 멈추고 사람을 부른다.
# ('횟수' 기준이면 대출앱을 하룻밤만 꺼둬도 아침에 이미 포기 상태가 된다)
GIVE_UP_AFTER_HOURS = 72


def _next_retry(retry_count: int) -> str:
    from datetime import timedelta
    m = RETRY_BACKOFF_MIN[min(retry_count, len(RETRY_BACKOFF_MIN) - 1)]
    return (datetime.now() + timedelta(minutes=m)).isoformat()


def mark_consumer_attempting(consumer_id: int):
    """등록 시도 시작 표시(진행 중인 건을 다른 회차가 가로채지 않도록)."""
    with get_conn() as conn:
        conn.execute("UPDATE consumers SET attempt_at=? WHERE id=?",
                     (_now(), consumer_id))


def mark_consumer_failed(consumer_id: int, error: str):
    """대출앱 등록 실패 기록(재시도 횟수 누적 + 다음 시도 시각 예약)."""
    with get_conn() as conn:
        row = conn.execute("SELECT COALESCE(retry_count,0) c FROM consumers WHERE id=?",
                           (consumer_id,)).fetchone()
        n = (row["c"] if row else 0) + 1
        conn.execute(
            "UPDATE consumers SET registered=0, last_error=?, retry_count=?, "
            "next_retry_at=?, attempt_at=NULL WHERE id=?",
            (str(error)[:500], n, _next_retry(n), consumer_id))


def _give_up_cutoff() -> str:
    from datetime import timedelta
    return (datetime.now() - timedelta(hours=GIVE_UP_AFTER_HOURS)).isoformat()


def pending_consumers(limit: int = 50) -> list:
    """지금 재시도할 차례가 된, 아직 대출앱에 못 들어간 리드.

    · next_retry_at 이 아직 안 됐으면 건너뛴다(지수 백오프)
    · 방금 시도를 시작한 건(attempt_at 이 5분 이내)은 진행 중이므로 건너뛴다
    · 접수한 지 GIVE_UP_AFTER_HOURS 를 넘긴 건은 사람이 봐야 한다(stuck)"""
    now = _now()
    from datetime import timedelta
    stale = (datetime.now() - timedelta(minutes=5)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM consumers WHERE COALESCE(registered,0)=0 "
            "AND (next_retry_at IS NULL OR next_retry_at <= ?) "
            "AND (attempt_at IS NULL OR attempt_at <= ?) "
            "AND COALESCE(created_at,'') > ? "
            "ORDER BY id LIMIT ?",
            (now, stale, _give_up_cutoff(), limit)).fetchall()
    return [dict(r) for r in rows]


def stuck_consumers() -> list:
    """자동 재시도를 포기한(너무 오래된) 리드 — 사람이 직접 확인해야 한다."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM consumers WHERE COALESCE(registered,0)=0 "
            "AND COALESCE(created_at,'') <= ? ORDER BY id",
            (_give_up_cutoff(),)).fetchall()
    return [dict(r) for r in rows]


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


if __name__ == "__main__":
    init_db()
    with get_conn() as conn:
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    print(f"[DB] 테이블: {tables}")
