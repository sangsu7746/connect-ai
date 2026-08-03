# ============================================================
#  config.py — AutoAd 통합 광고·접수 시스템 설정
#  · 모든 시크릿은 .env 에서만 읽는다 (소스 하드코딩 금지)
#  · P0-1
# ============================================================
import os
from pathlib import Path

# .env 로드 (python-dotenv 없으면 조용히 넘어감 — OS 환경변수만 사용)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── 경로 ────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
DATA_DIR      = BASE_DIR / "data"
CREATIVES_DIR = DATA_DIR / "creatives"          # 생성된 팜플렛 PNG
DOWNLOAD_DIR  = DATA_DIR / "downloads"
for _d in (DATA_DIR, CREATIVES_DIR, DOWNLOAD_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# AutoAd 자체 DB(신규 6테이블). 대출 파이프라인의 kakao_crawl.db 와는 분리.
# 하나의 DB로 합치려면 AUTOAD_DB 를 kakao_crawl.db 경로로 지정 (신규 테이블은 additive).
DB_PATH = Path(os.getenv("AUTOAD_DB", str(DATA_DIR / "autoad.db")))

# ── 외부 시스템 연동 ────────────────────────────────────────
# 대출위젯-카카오 app.py (FastAPI). 접수 브릿지가 여기로 POST /api/intake/register
LOAN_API_BASE   = os.getenv("LOAN_API_BASE",   "http://127.0.0.1:8000")
# PrintCraft 로컬 이미지 서버 (server/index.js). POST /api/generate
PRINTCRAFT_BASE = os.getenv("PRINTCRAFT_BASE", "http://127.0.0.1:8787")
# 밴드/페북 발행 엔진(페이스북-광고글/app) 위치 — band_automator.py·facebook_automator.py
# ⚠ 발행 엔진은 '자동포스팅' 프로그램 것을 쓴다.
#   페이스북-광고글/app 사본은 오래된 버전이라 게시 버튼을 못 찾는다(실측).
#   자동포스팅 쪽에는 익명 팝업·나가기 확인창 처리와 세션 관리가 들어 있다.
FB_PROJECT_APP_DIR = os.getenv(
    "FB_PROJECT_APP_DIR",
    str(BASE_DIR.parent / "페이스북-회원자동포스팅 _260706" / "app"))
# 밴드는 별도 프로그램에 있다.
BAND_PROJECT_APP_DIR = os.getenv(
    "BAND_PROJECT_APP_DIR",
    str(BASE_DIR.parent / "네이버밴드-자동포스팅" / "app"))
# 카카오 발행 엔진(대출위젯-카카오) 위치 — kakao_send.ahk (AutoHotkey)
KAKAO_PROJECT_DIR = os.getenv("KAKAO_PROJECT_DIR",
                              str(BASE_DIR.parent / "대출위젯-카카오-260628"))
# 소비자 접수폼의 공개 주소. 광고 카피 CTA 링크로 삽입된다(전환추적 파라미터 포함).
# ⚠ 실발행 전 반드시 외부에서 접근 가능한 주소로 교체(터널/호스팅). 로컬 주소면 소비자가 못 연다.
PUBLIC_BASE = os.getenv("PUBLIC_BASE", "http://127.0.0.1:8010").rstrip("/")
# 클라우드 수신함(Firestore) → 사무실 PC 회수용. cloud_sync.py 가 사용.
# (토큰은 아래 시크릿 섹션에서 _secret 으로 로드)
LEAD_PULL_URL = os.getenv("LEAD_PULL_URL", "").strip()
# 회수한 리드를 '받았다'고 확인해 주는 주소. 비워두면 확인 없이 즉시 확정하는
# 구버전 클라우드로 간주한다(그 경우 전송 중 끊기면 리드가 사라질 수 있다).
LEAD_ACK_URL = os.getenv("LEAD_ACK_URL", "").strip()
# 광고 링크 클릭 추적용 리다이렉트. 광고 본문의 링크를 이 주소로 감싸면
# 클릭이 기록된 뒤 목적지로 넘어간다. 비우면 추적 없이 목적지로 직행한다.
AD_CLICK_URL = os.getenv("AD_CLICK_URL", "").strip()
AD_CLICK_PULL_URL = os.getenv("AD_CLICK_PULL_URL", "").strip()
# 콘텐츠형 글에 쓰는 채널별 추적 경로의 앞부분 — '{BRAND_SITE}/{TRACK_PREFIX}/{키}'.
# ⚠ 이 값을 바꾸면 호스팅 rewrite 의 source 도 같이 바꿔야 한다
#   (InkCraft firebase.json 의 "/t/**"). 안 맞추면 링크가 SPA 로 흡수돼
#   클릭이 한 건도 안 잡히고, 사용자에겐 정상 페이지로 보여 눈치채기 어렵다.
TRACK_PREFIX = os.getenv("AD_TRACK_PREFIX", "t").strip().strip("/") or "t"

if not LEAD_ACK_URL and LEAD_PULL_URL.endswith("loanIntakePull"):
    # 같은 프로젝트의 짝 함수라 주소가 한 글자만 다르다. 손으로 넣다가 빠뜨리면
    # 확인이 안 가 리드가 10분마다 계속 재배달되므로 자동으로 유도한다.
    LEAD_ACK_URL = LEAD_PULL_URL[:-len("loanIntakePull")] + "loanIntakeAck"
# 같은 프로젝트의 짝 함수라 주소가 접미사만 다르다. 수기 설정 누락을 막는다.
if LEAD_PULL_URL.endswith("loanIntakePull"):
    _root = LEAD_PULL_URL[:-len("loanIntakePull")]
    AD_CLICK_URL = AD_CLICK_URL or (_root + "adClick")
    AD_CLICK_PULL_URL = AD_CLICK_PULL_URL or (_root + "adClickPull")

# ── 시크릿 (하드코딩 금지 — 없으면 빈 문자열) ───────────────
# 붙여넣기 시 끼는 앞뒤 공백/개행 방어를 위해 항상 .strip()
def _secret(name: str) -> str:
    return os.getenv(name, "").strip()

ANTHROPIC_API_KEY = _secret("ANTHROPIC_API_KEY")   # 카피 생성
GROQ_API_KEY      = _secret("GROQ_API_KEY")         # 서류 파싱(재발급본)
CF_API_TOKEN      = _secret("CF_API_TOKEN")         # PrintCraft FLUX
CF_ACCOUNT_ID     = _secret("CF_ACCOUNT_ID")
GEMINI_API_KEY    = _secret("GEMINI_API_KEY")       # PrintCraft 프리미엄
TELEGRAM_TOKEN    = _secret("TELEGRAM_TOKEN")       # 승인 콘솔
TELEGRAM_CHAT_ID  = _secret("TELEGRAM_CHAT_ID")
LEAD_PULL_TOKEN   = _secret("LEAD_PULL_TOKEN")      # 클라우드 수신함 회수용

# ── 모델 ────────────────────────────────────────────────────
# 최신 Sonnet. (기존 프로젝트의 claude-sonnet-4-6 은 현재 유효 ID 아님)
COPY_MODEL = os.getenv("COPY_MODEL", "claude-sonnet-5").strip()
# 카피 생성 제공자: gemini(무료티어·저비용) | claude(품질). 주입식이라 전환 자유.
COPY_PROVIDER     = os.getenv("COPY_PROVIDER", "gemini").strip().lower()
COPY_MODEL_GEMINI = os.getenv("COPY_MODEL_GEMINI", "gemini-flash-lite-latest").strip()
# 기존 전단 → 카드형 재편집용 이미지 모델.
# 실측(2026-07): gemini-3-pro-image = 오타 0·레이아웃 우수(권장)
#                gemini-3.1-flash-image = 저렴하나 오타 발생('가치'→'가처')
#                gemini-2.5-flash-image = 텍스트 대량 붕괴, 사용 금지
CARD_MODEL = os.getenv("CARD_MODEL", "gemini-3-pro-image").strip()

# ── 발행 계정 ───────────────────────────────────────────────
# ⚠ 이 값이 저장된 쿠키 파일 이름을 결정한다.
#   밴드  : 페이스북-광고글/data/cookies/{BAND_ACCOUNT}.json
#   페이스북: 페이스북-광고글/data/cookies/facebook_{FACEBOOK_ACCOUNT}.json
#   비워두면 어댑터 기본값('naver_default')을 쓰는데, 그런 쿠키 파일은 없으므로
#   로그인이 100% 실패한다. login.py --account 에 쓴 값과 반드시 같아야 한다.
#   채널별로 다른 계정을 쓰려면 channels.account 에 넣는다(이 값은 그때의 기본값).
BAND_ACCOUNT     = _secret("BAND_ACCOUNT")
FACEBOOK_ACCOUNT = _secret("FACEBOOK_ACCOUNT")
# 발행용 브라우저를 창 없이 띄울지. 예약 발행이 창을 띄우면 카카오 AHK 전송 중
# 포커스를 뺏어 엉뚱한 창에 글이 들어갈 수 있다.
PUBLISH_HEADLESS = os.getenv("PUBLISH_HEADLESS", "1") == "1"
# 로그인 세션을 이 시간마다 실제로 다시 확인한다(분). 0이면 확인 안 함.
SESSION_RECHECK_MIN = int(os.getenv("SESSION_RECHECK_MIN", "30"))


def cookie_path(platform: str, account: str = None):
    """그 계정의 쿠키 파일 경로(존재 여부와 무관). 진단 메시지·점검에 쓴다."""
    from pathlib import Path as _P
    if platform == "threads":
        acc = account or THREADS_ACCOUNT
        if not acc:
            return None
        return _P(FB_PROJECT_APP_DIR).parent / "data" / "cookies" / f"threads_{acc}.json"
    acc = account or (BAND_ACCOUNT if platform == "band" else FACEBOOK_ACCOUNT)
    if not acc:
        return None
    # 밴드와 페북은 서로 다른 프로그램의 data/cookies 를 쓰고, 파일명 규칙도 다르다.
    #   밴드 : {계정}.json          (band_automator._cookie_path)
    #   페북 : fb_{계정}.json       (facebook_automator._cookie_path)
    root = _P(BAND_PROJECT_APP_DIR if platform == "band" else FB_PROJECT_APP_DIR).parent
    d = root / "data" / "cookies"
    return d / (f"fb_{acc}.json" if platform == "facebook" else f"{acc}.json")


# ── 운영 안전장치 (기본값 = 안전) ───────────────────────────
GLOBAL_DRY_RUN     = os.getenv("GLOBAL_DRY_RUN", "1") == "1"   # 1이면 실채널 발행 금지
DAILY_POST_LIMIT   = int(os.getenv("DAILY_POST_LIMIT", "10"))  # 계정 전체 일일 발행 상한
TIMEZONE           = "Asia/Seoul"

# ── 계정 정지 방어 ──────────────────────────────────────────
# 플랫폼이 실제로 보는 것은 브라우저 위장이 아니라 '행동 패턴'이다.
# 짧은 시간에 여러 방에 비슷한 글이 올라가는 것 자체가 신호가 된다.
#
# 같은 채널에 하루 몇 번까지. 같은 밴드에 반복 게시가 가장 빨리 걸린다.
CHANNEL_DAILY_LIMIT = int(os.getenv("CHANNEL_DAILY_LIMIT", "1"))
# 발행과 발행 사이 최소 간격(초). 이 범위에서 무작위로 쉰다.
POST_INTERVAL_MIN = int(os.getenv("POST_INTERVAL_MIN", "90"))
POST_INTERVAL_MAX = int(os.getenv("POST_INTERVAL_MAX", "300"))
# 같은 소재(이미지)를 다시 쓰기까지의 최소 일수. 같은 그림 반복은 눈에 띈다.
CREATIVE_COOLDOWN_DAYS = int(os.getenv("CREATIVE_COOLDOWN_DAYS", "14"))
# 발행 허용 시간대(24h). 새벽에 광고가 나가면 그 자체가 신호다.
# 채널에 active_hours 가 있으면 그쪽이 우선한다.
POST_HOURS_START = int(os.getenv("POST_HOURS_START", "9"))
POST_HOURS_END   = int(os.getenv("POST_HOURS_END", "21"))

# 채널 규격 프리셋 (px) — P1-2 팜플렛 생성기가 사용
CHANNEL_SPECS = {
    "band":     (1080, 1080),   # 정사각
    "cafe":     (1080, 1080),
    "facebook": (1200, 630),    # 링크 카드
    "kakao":    (1080, 1350),   # 세로형
}

# ── 업종 프로필 ─────────────────────────────────────────────
# 브랜드·의무표기·금칙어·소재출처는 profiles/{key}.yaml 에서 온다.
# 엔진 코드는 업종을 몰라도 되게 하기 위함. 전환: .env 의 AUTOAD_PROFILE
import profiles as _profiles

PROFILE       = _profiles.load()
PROFILE_KEY   = PROFILE["key"]
PROFILE_NAME  = PROFILE["name"]

_b = PROFILE["brand"]
BRAND_COMPANY    = _b["company"]
BRAND_ROMAN      = _b["roman"]
BRAND_PHONE      = _b["phone"]
BRAND_REGION     = _b["region"]
BRAND_CHANNELS   = _b["channels"]
BRAND_REGISTERED = _b["registered"]
BRAND_SITE       = _b.get("site", "")     # 웹/앱 서비스는 전화 대신 사이트 주소로 유도
BRAND_REG_NO     = os.getenv("BRAND_REG_NO", "").strip() or _b["reg_no"]

_c = PROFILE["compliance"]
DISCLAIMER      = _c["disclaimer"]        # 모든 소재 하단 고정 문구
BANNED_PHRASES  = list(_c["banned_phrases"])
COMPLIANCE_NOTE = _c["note"]
LOAN_DISCLAIMER = DISCLAIMER              # 이전 이름 호환

_ct = PROFILE["content"]
CONTENT_SOURCE = _ct["source"]            # flyers | docs
FLYERS_DIR = _profiles.resolve_dir(_ct["flyers_dir"])
DOCS_DIR   = _profiles.resolve_dir(_ct["docs_dir"])
# 이 업종의 기본 설명서(파일명). render_from_doc 을 인자 없이 부를 때 쓴다.
DEFAULT_DOC = (str(DOCS_DIR / _ct["doc"]) if (DOCS_DIR and _ct.get("doc")) else "")
FALLBACK_BODY = (PROFILE.get("fallback_copy") or {}).get("body", "")
INTAKE_TITLE  = (PROFILE.get("intake") or {}).get("title", "상담 접수")
INTAKE_TARGET = (PROFILE.get("intake") or {}).get("target", "none")

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

REQUIRED_SECRETS = ["ANTHROPIC_API_KEY"]  # P1 진입 시 최소 필요


def missing_secrets(names=None) -> list:
    """비어 있는 시크릿 이름 목록 반환 (배포/실행 전 점검용)."""
    names = names or REQUIRED_SECRETS
    return [n for n in names if not globals().get(n)]


if __name__ == "__main__":
    print(f"[config] DB_PATH        = {DB_PATH}")
    print(f"[config] LOAN_API_BASE  = {LOAN_API_BASE}")
    print(f"[config] PRINTCRAFT_BASE= {PRINTCRAFT_BASE}")
    print(f"[config] GLOBAL_DRY_RUN = {GLOBAL_DRY_RUN}")
    miss = missing_secrets(list(REQUIRED_SECRETS) + [
        "GROQ_API_KEY", "GEMINI_API_KEY", "TELEGRAM_TOKEN"])
    print(f"[config] 미설정 시크릿  = {miss or '없음'}")
