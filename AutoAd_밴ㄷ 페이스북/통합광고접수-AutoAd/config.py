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
# '/t/…' 짧은 추적 경로가 **실제로 배포된** 사이트 목록.
# ⚠ 여기 없는 사이트에 그 경로를 쓰면 안 된다.
#   · Firebase 호스팅이라도 rewrite 를 안 올렸으면 SPA 가 흡수해 클릭이 0 이 되고,
#   · Next.js/Vercel 처럼 미지정 경로에 404 를 주는 곳은 **광고를 누른 사람이
#     오류 페이지를 본다**(mirizip.com 에서 실제로 404 확인).
#   사이트에 rewrite 를 올린 뒤에 여기에 추가한다.
TRACK_SITES = {h.strip().lower() for h in os.getenv(
    "AD_TRACK_SITES",
    "headjim-ink.web.app,ad-studio-app.web.app,headjim-loan.web.app").split(",")
    if h.strip()}

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
# 카피 생성 제공자: gemini(무료티어·저비용) | claude(품질) | ollama(로컬·무과금). 주입식이라 전환 자유.
COPY_PROVIDER     = os.getenv("COPY_PROVIDER", "gemini").strip().lower()
COPY_MODEL_GEMINI = os.getenv("COPY_MODEL_GEMINI", "gemini-flash-lite-latest").strip()
# ── Ollama (로컬 데몬 → 클라우드 모델) ──────────────────────
#  ⚠ '-cloud' 접미사 모델은 Ollama 클라우드에서 돈다. 로컬 RAM/VRAM 을 쓰지 않아
#    이 PC(16GB, 크롬 3개 병렬)의 메모리 압박에 기여하지 않는다.
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud").strip()
# 기존 전단 → 카드형 재편집용 이미지 모델.
# 실측(2026-07): gemini-3-pro-image = 오타 0·레이아웃 우수(권장)
#                gemini-3.1-flash-image = 저렴하나 오타 발생('가치'→'가처')
#                gemini-2.5-flash-image = 텍스트 대량 붕괴, 사용 금지
CARD_MODEL = os.getenv("CARD_MODEL", "gemini-3-pro-image").strip()

# ── 카드 이미지 엔진 ────────────────────────────────────────
#  "gemini" = 기존 유료 경로(gemini-3-pro-image)
#  "sd"     = 로컬 Stable Diffusion (AUTOMATIC1111 WebUI API)
#  ⚠ 기존 경로를 지우지 않는다. SD 품질이 안 맞으면 이 한 줄로 되돌아간다.
CARD_ENGINE  = os.getenv("CARD_ENGINE", "gemini").strip().lower()
SD_WEBUI_URL = os.getenv("SD_WEBUI_URL", "http://127.0.0.1:7860").rstrip("/")
SD_STEPS     = int(os.getenv("SD_STEPS", "28"))
SD_CFG       = float(os.getenv("SD_CFG", "7.5"))
SD_SAMPLER   = os.getenv("SD_SAMPLER", "DPM++ 2M").strip()

# 콘텐츠형 격자에 넣을 결과물 칸 수. 이미지 생성 비용이 이 수에 정비례한다
# (칸 1개 = 이미지 1회 생성). 4장 격자를 2장으로 줄이면 비용이 절반이다.
# ⚠ 1로 두면 '결과물을 여럿 보여준다'는 콘텐츠형의 성격이 사라진다.
SHOWCASE_TILES = max(1, int(os.getenv("SHOWCASE_TILES", "2")))

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


# ── 플랫폼별 일일 상한 (계정 단위) ──────────────────────────
# 상한은 '계정 하나가 하루에 몇 건 뿌리는가'다. 플랫폼마다 감시 강도가 달라서
# 한 값으로 묶으면 한쪽에 맞춘 값이 다른 쪽에서 과하거나 모자란다.
#   · 밴드   : 방마다 알림이 가서 사람 눈에 더 잘 띈다
#   · 페이스북: 그룹 피드에 묻히지만 계정 제한이 걸리면 회복이 느리다
# 값이 없으면 DAILY_POST_LIMIT 로 떨어진다(기존 동작 유지).
#
# ⚠ 여기 숫자를 올려도 실제 발행량은 그만큼 늘지 않는다. 진짜 천장은 셋이다.
#   1) 채널 수  — 한 방에 하루 CHANNEL_DAILY_LIMIT 건까지다(.env, 현재 2).
#                 천장은 '켜진 채널 수 × 그 값' 과 이 상한 중 작은 쪽이다.
#   2) 소재 수  — 같은 이미지는 CREATIVE_COOLDOWN_DAYS 동안 재사용 못 한다.
#                 건수만큼 새 이미지를 만들어야 하고, 그게 비용의 전부다.
#   3) 시간     — 발행은 한 번에 하나씩, 사이에 POST_INTERVAL 만큼 쉰다.
#                 건당 평균 3~4분이라 100건이면 6시간 넘게 걸린다.
_PLATFORM_DAILY = {
    "band":     int(os.getenv("DAILY_POST_LIMIT_BAND", "0")),
    "facebook": int(os.getenv("DAILY_POST_LIMIT_FACEBOOK", "0")),
    "kakao":    int(os.getenv("DAILY_POST_LIMIT_KAKAO", "0")),
}


def daily_limit(platform: str = None) -> int:
    """그 플랫폼의 계정당 일일 발행 상한."""
    return _PLATFORM_DAILY.get(platform or "", 0) or DAILY_POST_LIMIT
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

# 그림 1장이 덮는 채널 수 상한. 넘으면 그 바퀴에 그림을 더 쓴다.
#  ⚠ 20 은 '지금 재고로 감당되는 가장 강한 상한' 이다. 10 으로 조이면
#    adstudio 가 ceil(74/10)=8장 x 14일 = 112장 필요한데 83장뿐이라 부족해진다.
#    재고가 늘면 낮출 수 있고, 낮출수록 안전하다.
IMAGE_FANOUT_MAX = int(os.getenv("IMAGE_FANOUT_MAX", "20"))
#  ⚠ 재고 목표용 별도 상수를 두지 않는다. '라운드당 그림 수 x 쿨다운 일수' 는
#    취향이 아니라 산수다 — 한 그림이 나가면 CREATIVE_COOLDOWN_DAYS 만큼 쉬므로
#    하루 한 바퀴를 돌리려면 그만큼 있어야 한다. 같은 수에 이름을 둘 붙이면
#    언젠가 갈라진다(stock_target 참고).

# AI 이미지 생성을 통째로 잠근다(1=잠금). 기본은 풀림.
#   잠기는 것 : showcase.make(결과물 격자) · pamphlet.render_from_doc(설명서 카드)
#               — 둘 다 제미나이를 부르고, 부르는 만큼 과금된다.
#   안 잠기는 것: render_from_template(기성 전단 → Pillow 로컬 합성, 무료)
#
# ⚠ 왜 '생성 실패'로 두지 않고 별도 스위치를 두는가 — 키가 살아 있는 동안에도
#   운영자가 이미지 비용을 통제할 수 있어야 한다. 2026-08-14 운영자 지시로 켬:
#   새 제미나이 키를 넣되 이미지는 지시가 있을 때까지 만들지 않는다.
IMAGE_GEN_LOCKED = os.getenv("IMAGE_GEN_LOCKED", "0").strip() == "1"
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
# 이 업종을 내보낼 수 있는 플랫폼(빈 리스트 = 제한 없음).
PROFILE_ALLOW_PLATFORMS = list(PROFILE.get("allow_platforms") or [])

_b = PROFILE["brand"]
BRAND_COMPANY    = _b["company"]
BRAND_ROMAN      = _b["roman"]
BRAND_PHONE      = _b["phone"]
BRAND_REGION     = _b["region"]
BRAND_CHANNELS   = _b["channels"]
BRAND_REGISTERED = _b["registered"]
BRAND_SITE       = _b.get("site", "")     # 웹/앱 서비스는 전화 대신 사이트 주소로 유도
BRAND_REG_NO     = os.getenv("BRAND_REG_NO", "").strip() or _b["reg_no"]

# ── 확인된 사실 (광고에 쓸 수 있는 수치의 유일한 출처) ──────────────
# 카피에 나오는 시간·횟수·배수·퍼센트는 **여기 적힌 것만** 통과한다
# (content/copy_engine._find_unverified_numbers).
#
# 왜 필요한가: '구체적으로 써라'라고 시키면 LLM 은 구체성을 흉내내려고 숫자를
#   지어낸다(실측: 근거 없이 "40초 만에", "1분 만에"). 실증할 수 없는 성능
#   표시는 표시광고법 위반이라 잘라낼 수 없고 폴백으로 보내야 한다.
#
# ⚠ 여기 적는 값은 **실제로 측정한 값**이어야 한다. 범위로 적는 것은 괜찮고
#   오히려 정직하지만, 범위라고 해서 실증 의무가 사라지지는 않는다.
#   "40~60초" 도 그렇게 걸린다는 근거가 있어야 쓸 수 있다.
PROFILE_FACTS = str(PROFILE.get("facts") or "").strip()

# ── 이 업종에서 쓰면 안 되는 '글의 각도' ─────────────────────
# content/copy_engine.ANGLES 의 인덱스 목록. 카피 생성은 매번 각도 하나를
# 골라 "이렇게 써라"라고 지시하는데, 그중 몇 개는 규제 업종에서 그대로
# 위법 유도축이 된다.
#   0 "직접 써 본 사람의 후기처럼"   → 광고주는 쓴 당사자가 아니다(거짓 후기)
#   2 "쓰기 전과 쓴 뒤가 어떻게 달라졌는지 대비해서" → 승인 암시
#   5 "실패했던 시도를 먼저 이야기하며"             → 거절 이력 + 1인칭 체험담
# 2026-08-10 실측 사고("다른 데서 안 되던 게 여기선 풀렸는지…")가 정확히 이 축이다.
#
# ⚠ ANGLES 자체에서 항목을 지우지 마라. 선택이 crc32(track_key) % len(ANGLES)
#   이므로 길이가 바뀌면 진행 중인 모든 소재의 각도가 재배정된다.
#   여기서 '후보에서 빼는' 방식이어야 인덱스가 보존된다.
# ⚠ 이 키를 선언하지 않은 프로필은 예전과 완전히 같게 동작한다(무회귀).
PROFILE_DENY_ANGLES = sorted({
    int(i) for i in ((PROFILE.get("copy") or {}).get("deny_angles") or [])
})


# ── 업종 x 플랫폼 화이트리스트 ──────────────────────────────
# 소재는 만들어진 업종을 copy_json 에 달고 다니지만, 발행은 서버 프로세스의
# 업종(보통 loan)에서 일어난다. 그래서 '이 소재를 이 플랫폼에 내보내도 되는가'는
# 활성 프로필이 아니라 **소재의 업종**으로 판단해야 한다.
_ALLOW_CACHE = {}


def profile_allow_platforms(profile_key: str) -> list:
    """그 업종의 허용 플랫폼 목록. 빈 리스트 = 제한 없음.

    ⚠ 발행 경로(publish_creative)에서 불린다. 프로필 파일이 없거나 깨져도
      예외를 밖으로 던지지 않는다 — 여기서 터지면 발행 job 이 통째로 죽고,
      DB 상태만 'posting' 으로 남아 겉보기엔 진행 중처럼 보인다.
      대신 '제한 없음'으로 처리하고 그 사실을 로그로 남긴다."""
    key = (profile_key or "").strip()
    if not key:
        return []
    if key == PROFILE_KEY:
        # 이미 로드된 프로필을 다시 디스크에서 읽지 않는다.
        return list(PROFILE_ALLOW_PLATFORMS)
    if key in _ALLOW_CACHE:
        return list(_ALLOW_CACHE[key])
    try:
        allow = list(_profiles.load(key).get("allow_platforms") or [])
    except Exception as e:
        # cp949 콘솔에서도 안전하도록 ASCII 만 쓴다.
        print(f"[config] profile '{key}' load failed ({type(e).__name__})"
              f" - allow_platforms unknown, treating as no restriction")
        allow = []
    _ALLOW_CACHE[key] = allow
    return list(allow)


# ── 규제 업종 ───────────────────────────────────────────────
# 이 키의 소재는 '프로필을 못 읽으면 통과'가 아니라 '못 읽으면 차단'이다.
# ⚠ 왜 필요한가 — _profile_for() 는 프로필 **파일이 없으면** (None, False) 를
#   돌려주고, 그러면 platform_allowed 도 compliance_missing 도 '제한 없음'이
#   된다(fail-open). 즉 profiles/loan.yaml 의 이름을 바꾸거나 배포물에
#   profiles/ 를 안 실으면 대출광고가 **아무 검사 없이 아무 플랫폼으로** 나간다.
#   깨진 yaml 은 막히는데 없는 yaml 은 통과하는 비대칭이 사고의 형태다.
#   여기 이름이 든 업종만 fail-closed 로 뒤집는다(나머지 14개 업종 무영향).
REGULATED_PROFILE_KEYS = ("loan",)


def is_regulated(profile_key: str) -> bool:
    """대부업 등 광고 규제를 받는 업종인가(fail-closed 대상)."""
    return (profile_key or "").strip() in REGULATED_PROFILE_KEYS


_is_regulated = is_regulated        # 내부 호출용 별칭


def platform_allowed(profile_key: str, platform: str) -> bool:
    """그 업종 소재를 이 플랫폼에 내보내도 되는가.

    · profile_key 가 비었으면(업종 불명) True — 레거시 소재를 죽이지 않는다.
    · 그 업종에 allow_platforms 가 없으면 True — 기존 업종 전부 무영향.
    · 있으면 목록에 든 플랫폼만 True.
    · ★ 규제 업종(REGULATED_PROFILE_KEYS)인데 프로필을 못 읽으면 False.
    """
    if _is_regulated(profile_key):
        prof, _ = _profile_for(profile_key)
        if prof is None:
            # cp949 콘솔에서도 안전하도록 ASCII 만 쓴다.
            print(f"[config] regulated profile '{profile_key}' unavailable"
                  f" - blocking all platforms (fail-closed)")
            return False
    allow = profile_allow_platforms(profile_key)
    if not allow:
        return True
    return (platform or "").strip().lower() in allow


def loan_reg_no_missing() -> bool:
    """대부중개업 등록번호가 비어 있는가.

    대부업법 제9조상 대출광고에는 등록번호 등 필수기재사항이 들어가야 한다.
    번호가 없으면 '만들어 넣는' 것이 아니라 **발행을 막는다**.
    (소재가 loan 업종인지의 판단은 호출부 책임이다)

    ⚠ 등록번호 하나만 본다. 이자율·부대비용까지 포함한 전체 점검은
      compliance_gaps() 를 쓸 것."""
    return not (BRAND_REG_NO or "").strip()


# ── 법정 필수기재사항(의무표기) ─────────────────────────────
# 어느 업종에 적용되는지는 프로필의 compliance.mandatory_required 가 정한다.
# 선언하지 않은 프로필(loan 외 14개)은 전부 빈 값 → 동작 변화 없음.
from content import disclosure as _disclosure   # noqa: E402  (config 를 import 하지 않는 순수 모듈)

_PROFILE_CACHE = {}


def _profile_for(profile_key: str):
    """업종 키로 프로필 dict. 활성 프로필은 디스크를 다시 읽지 않는다.

    반환 (profile|None, load_failed).
      · load_failed=True 는 '파일은 있는데 읽지 못했다' 는 뜻이다. 이때는
        의무표기 선언 여부조차 알 수 없으므로 호출부가 **막는 쪽**으로
        처리해야 한다.
      · 파일 자체가 없으면 (None, False) - 삭제된 업종의 레거시 소재를
        새로 죽이지 않는다(platform_allowed 와 같은 태도)."""
    key = (profile_key or "").strip()
    if not key:
        return None, False
    if key == PROFILE_KEY:
        return PROFILE, False
    if key in _PROFILE_CACHE:
        return _PROFILE_CACHE[key]
    exists = (_profiles.DIR / f"{key}.yaml").exists()
    try:
        got = (_profiles.load(key), False)
    except Exception as e:
        # cp949 콘솔에서도 안전하도록 ASCII 만 쓴다.
        print(f"[config] profile '{key}' load failed ({type(e).__name__})"
              f" - mandatory disclosure state unknown")
        got = (None, bool(exists))
    _PROFILE_CACHE[key] = got
    return got


def mandatory_disclosure(profile_key: str) -> str:
    """그 업종의 법정 필수기재 문구 블록. 선언 안 한 업종은 ""."""
    prof, _ = _profile_for(profile_key)
    return _disclosure.build(prof) if prof else ""


def mandatory_lines(profile_key: str) -> list:
    """그 업종의 필수기재 문구를 줄 단위로(이미지 합성용). 없으면 []."""
    prof, _ = _profile_for(profile_key)
    return _disclosure.lines(prof) if prof else []


def mandatory_header_lines(profile_key: str) -> list:
    """[별표1] 1.가 - 광고 왼쪽상단에 놓을 상호·등록번호. 없으면 []."""
    prof, _ = _profile_for(profile_key)
    return _disclosure.header_lines(prof) if prof else []


def mandatory_fingerprint(profile_key: str) -> str:
    """그 업종 의무표기의 현재 지문. 선언 안 한 업종은 "".

    소재(이미지)를 구울 때 저장해 두고 발행 직전에 다시 계산해 대조한다.
    다르면 '이미지에 찍힌 의무표기가 지금 값과 다르다'는 뜻이라 막는다."""
    return _disclosure.fingerprint(mandatory_lines(profile_key))


def compliance_missing(profile_key: str) -> list:
    """그 업종에서 값이 비어 있는 필수기재 항목(사람이 읽는 이름) 목록.

    빈 리스트 = 항목은 다 찼다는 뜻(등록 유효기간은 별도 검사).
    ⚠ 사유 문자열은 cp949 콘솔에 찍힌다. em dash·이모지 금지."""
    prof, failed = _profile_for(profile_key)
    if failed:
        # 파일은 있는데 못 읽었다. 의무표기 선언 여부를 알 수 없으므로 막는다.
        return [f"업종 프로필 '{profile_key}' 을(를) 읽지 못함(의무표기 확인 불가)"]
    if not prof:
        # ★ 규제 업종은 '파일이 없다'도 막는다(fail-closed). 나머지는 종전대로
        #   통과 - 삭제된 업종의 레거시 소재를 새로 죽이지 않기 위함.
        if _is_regulated(profile_key):
            return [f"규제 업종 프로필 '{profile_key}' 을(를) 찾지 못함"
                    f"(의무표기 확인 불가)"]
        return []
    out = list(_disclosure.gaps(prof))
    if _disclosure.flyer_phone_unverified(prof):
        out.append("전단에 인쇄된 전화번호가 등록 광고용 번호인지 미확인"
                   "(compliance.mandatory.flyer_phone_verified)")
    return out


def compliance_expired(profile_key: str, today=None) -> bool:
    """등록 유효기간이 지났는가. 선언 안 한 업종은 항상 False."""
    prof, _ = _profile_for(profile_key)
    return _disclosure.registration_expired(prof, today) if prof else False


def compliance_valid_to(profile_key: str):
    """등록 유효기간 만료일(date) 또는 None."""
    prof, _ = _profile_for(profile_key)
    return _disclosure.valid_to(prof) if prof else None


def compliance_gaps(profile_key: str, today=None) -> list:
    """그 업종에서 채워지지 않은 필수기재 항목 + 등록 유효기간 문제.

    빈 리스트 = 발행해도 되는 상태. 비어 있지 않으면 **발행을 막는다**."""
    out = compliance_missing(profile_key)
    if compliance_expired(profile_key, today):
        out = out + [f"등록 유효기간 만료({compliance_valid_to(profile_key)})"]
    return out


def compliance_renewal_due(profile_key: str, today=None) -> bool:
    """등록 갱신 창구(만료 3개월 전 ~ 1개월 전)에 들어왔는가. 경고용."""
    prof, _ = _profile_for(profile_key)
    return _disclosure.renewal_due(prof, today) if prof else False


def loan_compliance_gaps(today=None) -> list:
    """활성 프로필 기준 필수기재 점검(운영자 확인용 창구).

    등록번호까지 포함해 검사하므로 loan_reg_no_missing() 의 상위 집합이다."""
    return compliance_gaps(PROFILE_KEY, today)


# 이 프로세스의 업종에 대한 의무표기(소재 생성 시 캡션에 박아 둔다).
MANDATORY_DISCLOSURE = _disclosure.build(PROFILE)


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
# 쓰레드 답글이 쓸 업종 프로필. 비우면 활성 프로필(AUTOAD_PROFILE)을 따른다.
# ⚠ AUTOAD_PROFILE 을 바꾸면 밴드·페북·카카오 캠페인까지 전부 그 업종으로 바뀐다.
#   쓰레드만 다른 업종으로 돌리려고 그걸 건드리면 돌고 있던 광고가 갈아엎힌다.
#   그래서 쓰레드 전용 창구를 따로 둔다. (예: 대출 캠페인은 그대로, 쓰레드만 mirizip)
THREADS_PROFILE = _secret("THREADS_PROFILE")
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
# ⚠ 실측(2026-08-04 첫 실수집)에서 90분은 너무 좁았다 - 13건 중 10건이
#   이 필터에서 버려졌다. 추천 피드는 최신순이 아니라 반응순이라 하루 지난
#   글도 상위에 계속 노출된다(실제 피드에 1일·20시간·18시간짜리가 나란히
#   떠 있었다). '오래된 글은 아무도 안 본다'는 전제가 이 피드에는 안 맞는다.
#   24시간으로 넓힌다.
THREADS_POST_MAX_AGE_MIN = int(os.getenv("THREADS_POST_MAX_AGE_MIN", "1440"))
THREADS_REPLY_MAX_CHARS = int(os.getenv("THREADS_REPLY_MAX_CHARS", "280"))


def threads_profile() -> dict:
    """쓰레드 파이프라인이 쓸 업종 프로필 dict.

    THREADS_PROFILE 이 비었거나 활성 프로필과 같으면 이미 로드된 PROFILE 을
    그대로 준다(파일을 두 번 읽지 않는다). 로드에 실패하면 예외를 그대로
    올린다 — 조용히 대출 프로필로 떨어지면 인테리어 글에 대부중개 상호가
    붙은 답글이 나간다."""
    if THREADS_PROFILE and THREADS_PROFILE != PROFILE_KEY:
        return _profiles.load(THREADS_PROFILE)
    return PROFILE
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
