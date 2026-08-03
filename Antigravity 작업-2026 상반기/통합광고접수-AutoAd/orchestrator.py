# ============================================================
#  orchestrator.py — 지휘부  (P1-8)
#  캠페인 → 채널성향으로 상품 자동선택 → 전단 크리에이티브 + 캡션
#         → DB 크리에이티브·승인큐 → (승인) → dry-run/실발행 → posts 기록
#  * 얇게 유지: 실제 일은 각 모듈에 위임, 여기선 조율만.
#  * 카피 생성 실패(크레딧/네트워크) 시 브랜드 기반 폴백 캡션으로 자동 대체.
# ============================================================
import re
import sys
import json
import time
import atexit
import random
import threading
from datetime import datetime

import config
import db
import crosslock          # 밴드·페북 파이프라인이 클립보드를 두고 부딪히지 않게
from content import registry, pamphlet, copy_engine
from channels.base import PostResult
from channels.band import BandAdapter
from channels.facebook import FacebookAdapter
from channels.kakao import KakaoAdapter

# 플랫폼 → 어댑터 (P0-3 인터페이스로 통일)
ADAPTERS = {
    "band": BandAdapter,
    "facebook": FacebookAdapter,
    "kakao": KakaoAdapter,
}


# 계정별로 어댑터를 재사용한다.
# 매번 새로 만들면 브라우저·로그인 세션이 매번 초기화돼(_logged_in=False)
# 실발행이 100% '로그인 필요'로 막힌다. 실제로 그 상태였다.
#
# ⚠ 캐시 키에 계정이 반드시 들어가야 한다. 플랫폼만으로 잡으면 채널마다 다른
#   계정을 쓸 수 없고, 첫 채널의 로그인 세션으로 다른 계정 채널에 글이 나간다.
_ADAPTER_CACHE = {}

# 실발행은 한 번에 하나만. 클립보드·브라우저 포커스가 머신 전역 자원이라,
# 두 발행이 겹치면 A 밴드 작성창에 B 광고문이 붙어 나갈 수 있다(되돌릴 수 없음).
# 승인 콘솔(FastAPI 스레드풀)과 예약 발행(APScheduler 스레드풀)이 같은 프로세스에 있다.
_PUBLISH_LOCK = threading.RLock()


def default_account(platform: str) -> str:
    return {"band": config.BAND_ACCOUNT,
            "facebook": config.FACEBOOK_ACCOUNT}.get(platform, "")


def get_adapter(platform: str, account: str = None, fresh: bool = False):
    if platform not in ADAPTERS:
        raise ValueError(f"미지원 채널: {platform}")
    account = (account or default_account(platform) or "").strip()
    key = (platform, account)
    with _PUBLISH_LOCK:
        if fresh:
            drop_adapter(platform, account)
        if key not in _ADAPTER_CACHE:
            kw = {}
            if account:
                kw["account_id"] = account
            # 예약 발행이 창을 띄우면 카카오 AHK 전송 중 포커스를 뺏는다.
            if platform in ("band", "facebook"):
                kw["headless"] = config.PUBLISH_HEADLESS
            _ADAPTER_CACHE[key] = ADAPTERS[platform](**kw)
        return _ADAPTER_CACHE[key]


def drop_adapter(platform: str, account: str = None):
    """캐시에서 빼고 브라우저를 닫는다. 안 닫으면 chrome 이 프로세스마다 쌓인다."""
    account = (account or default_account(platform) or "").strip()
    ad = _ADAPTER_CACHE.pop((platform, account), None)
    _close(ad)


def _close(ad):
    if ad is None:
        return
    try:
        auto = getattr(ad, "_auto", None)
        drv = getattr(auto, "driver", None) if auto else None
        if drv is not None:
            drv.quit()
    except Exception:
        pass


def close_all_adapters():
    """프로세스 종료 시 남은 브라우저 정리."""
    with _PUBLISH_LOCK:
        for ad in list(_ADAPTER_CACHE.values()):
            _close(ad)
        _ADAPTER_CACHE.clear()


atexit.register(close_all_adapters)


def stored_credential(platform: str, account: str) -> dict:
    """발행 엔진의 암호화 저장소(storage.py, Fernet)에서 이 계정의 자격증명을 읽는다.

    ⚠ 비밀번호는 여기서 읽어 그대로 엔진에 넘길 뿐, 로그·DB·화면 어디에도 남기지 않는다.
      (사람이 페이스북-광고글 프로그램에서 한 번 등록해 둔 값을 재사용한다)
    없으면 None."""
    # 계정은 해당 플랫폼 프로그램의 저장소에 있다(밴드/페북이 서로 다른 프로그램).
    # ⚠ 두 프로그램 모두 `from app...` 을 쓰므로 AutoAd 의 app.py 와 부딪힌다.
    #   channels.engine 이 임포트 동안만 격리해 준다.
    app_dir = (config.BAND_PROJECT_APP_DIR if platform == "band"
               else config.FB_PROJECT_APP_DIR)
    try:
        from channels import engine
        storage = engine.load(app_dir, "storage")
        accounts = storage.load_accounts()
    except Exception as e:
        print(f"[login] 자격증명 저장소를 열 수 없습니다: {type(e).__name__}: {e}")
        return None

    want = (account or "").strip().lower()
    # 저장소마다 id 표기가 다르다. 실제로 쓰이는 형태를 모두 받아준다.
    #   페북 자동포스팅 : 'fb:headjimkss@gmail.com'
    #   구버전 사본     : 'facebook_headjimkss@gmail.com'
    keys = ({want, f"fb:{want}", f"facebook_{want}"} if platform == "facebook"
            else {want})
    # ⚠ 같은 아이디가 밴드용·페북용으로 각각 저장돼 있다. platform 을 안 보면
    #   페북 로그인에 밴드 계정 설정(login_type)을 써서 실패한다.
    want_plat = {"facebook"} if platform == "facebook" else {"naver", "band"}

    def _hit(a):
        ids = {str(a.get("id", "")).lower(), str(a.get("raw_id", "")).lower()}
        return bool(ids & keys) and bool(a.get("password"))

    for a in accounts:                       # 1차: 플랫폼까지 맞는 것
        if _hit(a) and str(a.get("platform", "")).lower() in want_plat:
            return {"password": a["password"],
                    "login_type": a.get("login_type") or "naver",
                    "name": a.get("name", "")}
    for a in accounts:                       # 2차: 아이디만 맞는 것(차선)
        if _hit(a):
            return {"password": a["password"],
                    "login_type": a.get("login_type") or "naver",
                    "name": a.get("name", "")}
    return None


# ── 계정 정지 방어 ──────────────────────────────────────────
# 플랫폼이 실제로 보는 건 브라우저 위장이 아니라 행동 패턴이다.
# 짧은 시간에 여러 방에 비슷한 글이 올라가면 위장을 아무리 해도 걸린다.
# 플랫폼별로 따로 기억한다. 하나로 묶으면 밴드에 올린 직후
# 페이스북 발행이 이유 없이 늦춰진다(서로 다른 계정인데도).
_LAST_POST_AT = {}


def _parse_hours(spec: str):
    """'9-21' 또는 '09:00-21:00' → (9, 21). 못 읽으면 None."""
    if not spec:
        return None
    m = re.match(r"\s*(\d{1,2})(?::\d{2})?\s*-\s*(\d{1,2})(?::\d{2})?\s*$", str(spec))
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (a, b) if 0 <= a <= 24 and 0 <= b <= 24 else None


def hours_ok(channel: dict) -> tuple:
    """지금이 이 채널의 발행 허용 시간대인가. 반환 (가능여부, 사유)."""
    rng = _parse_hours((channel or {}).get("active_hours")) or \
        (config.POST_HOURS_START, config.POST_HOURS_END)
    start, end = rng
    if start == end:                       # 종일 허용
        return True, ""
    h = datetime.now().hour
    inside = (start <= h < end) if start < end else (h >= start or h < end)
    if inside:
        return True, ""
    return False, (f"발행 허용 시간대가 아닙니다(지금 {h}시, 허용 {start}~{end}시) — "
                   f"새벽 광고는 그 자체가 신고 사유가 됩니다")


def _seconds_since_last_post(platform: str = None) -> float:
    """그 플랫폼의 마지막 발행 이후 경과 초. 프로세스 메모리와 DB 중 더 최근 것.

    메모리만 믿으면 프로세스를 재시작한 직후 첫 발행이 간격 없이 즉시 나간다
    (감독기가 서버를 되살리는 일이 잦으므로 실제로 일어난다).
    DB 도 함께 보므로 파이프라인을 따로 띄워도 간격이 지켜진다."""
    mem = _LAST_POST_AT.get(platform or "", 0.0)
    mem_elapsed = (time.time() - mem) if mem else None
    db_elapsed = None
    try:
        last = db.last_post_time(platform=platform)
        if last:
            db_elapsed = max(0.0, (datetime.now() - last).total_seconds())
    except Exception:
        pass
    cands = [x for x in (mem_elapsed, db_elapsed) if x is not None]
    return min(cands) if cands else None


def _space_out(platform: str = None):
    """직전 발행과 최소 간격을 둔다. 연달아 나가면 기계임이 드러난다."""
    key = platform or ""
    lo, hi = config.POST_INTERVAL_MIN, config.POST_INTERVAL_MAX
    if hi <= 0:
        _LAST_POST_AT[key] = time.time()
        return
    wait = random.randint(min(lo, hi), max(lo, hi))
    elapsed = _seconds_since_last_post(platform)
    if elapsed is not None and elapsed < wait:
        left = int(wait - elapsed)
        print(f"[orchestrator] 발행 간격 유지({platform or '전체'}) — {left}초 대기")
        time.sleep(left)
    _LAST_POST_AT[key] = time.time()


def _session_still_valid(adapter) -> bool:
    """살아있다고 표시된 세션을 실제로 한 번 물어본다.
    이 확인이 없으면 _logged_in 이 True 로 굳어, 만료된 뒤에도 로그인 단계를
    그냥 통과하고 발행이 '셀렉터 오류'로 오진된다."""
    try:
        auto = getattr(adapter, "_auto", None)
        if auto is None or getattr(auto, "driver", None) is None:
            return False           # 브라우저가 죽었으면 다시 로그인해야 한다
        return bool(auto._is_logged_in())
    except Exception:
        return False


def ensure_login(adapter) -> tuple:
    """실발행 직전 로그인 보장. 반환 (성공여부, 사유).

    저장된 쿠키로만 복원한다 — 비밀번호는 시스템 어디에도 두지 않는다.
    만료됐으면 사람이 `python login.py band --account ...` 로 한 번 다시 열어야 한다.
    """
    if not hasattr(adapter, "login"):
        return True, ""            # 로그인 개념이 없는 채널(카카오=UI 자동화)

    if getattr(adapter, "_logged_in", False):
        # 오래 켜둔 프로세스에서는 세션이 도중에 만료된다. 주기적으로 실제 확인.
        last = getattr(adapter, "_login_at", 0)
        recheck = config.SESSION_RECHECK_MIN * 60
        if recheck and (time.time() - last) > recheck:
            if _session_still_valid(adapter):
                adapter._login_at = time.time()
                return True, ""
            adapter._logged_in = False        # 만료 확인 → 재로그인 경로로
        else:
            return True, ""

    acc = getattr(adapter, "account_id", "") or ""

    # 1차: 저장된 세션(쿠키·크롬 프로필)으로 복원 — 비밀번호가 필요 없다.
    try:
        ok = adapter.login()
    except Exception as e:
        ok = False
        print(f"[login] 세션 복원 오류({type(e).__name__}: {e})")
    if ok:
        adapter._login_at = time.time()
        return True, ""

    # 2차: 등록해 둔 계정으로 프로그램이 스스로 로그인.
    #   밴드가 주는 세션은 '브라우저 닫으면 만료'라 쿠키 복원이 자주 실패한다.
    #   사람이 매번 로그인 창을 붙잡고 있을 수 없으므로 여기서 자동으로 들어간다.
    #   비밀번호는 암호화 저장소에서 엔진으로 곧장 전달되며 로그·DB에 남기지 않는다.
    cred = stored_credential(adapter.platform, acc)
    if not cred:
        return False, (f"세션 만료 + 저장된 계정 없음({acc or '기본계정'}) — "
                       f"`python login.py {adapter.platform} --account {acc or '<계정>'}` "
                       f"로 한 번 로그인하거나, 발행 프로그램에 계정을 등록하세요")
    print(f"[login] 세션 만료 — 저장된 계정으로 자동 로그인 "
          f"({cred.get('name') or acc} / {cred['login_type']})")
    try:
        ok = adapter.login(cred={"password": cred["password"],
                                 "login_type": cred["login_type"]})
    except Exception as e:
        return False, (f"자동 로그인 실패({type(e).__name__}: {e}) — "
                       f"2단계 인증·캡차일 수 있습니다")
    if not ok:
        return False, (f"자동 로그인 실패({acc}) — 비밀번호가 바뀌었거나 "
                       f"2단계 인증·캡차가 걸렸을 수 있습니다. "
                       f"`python login.py {adapter.platform} --account {acc}` 로 "
                       f"한 번 직접 로그인해 주세요")
    adapter._login_at = time.time()
    print(f"[login] 자동 로그인 성공 — {adapter.platform}/{acc}")
    return True, ""


# ── 상품 선택 (성향 라우팅) ─────────────────────────────────
def pick_product(channel: dict, campaign: dict) -> str:
    """캠페인이 상품을 지정하면 그것, 아니면 채널 성향에 맞는 상품 중 하나.

    ⚠ 예전엔 늘 cands[0] 만 골라, 소비자 채널 140곳에 전부 같은 전단이 나갔다.
      같은 계정이 같은 그림·같은 문구를 여러 방에 뿌리는 것이 가장 빨리 걸리는 패턴이다.
      채널 id 로 돌려가며 고른다(무작위가 아니라 채널마다 고정 — 재현 가능해야 한다)."""
    if campaign.get("product_key"):
        return campaign["product_key"]
    cands = [p for p in registry.by_audience(channel.get("audience", "mixed"))
             if p.get("flyer")]
    if not cands:
        return "general"
    idx = int(channel.get("id") or 0) % len(cands)
    return cands[idx]["key"]


# ── 캡션 생성 (실패 시 폴백) ────────────────────────────────
def _fallback_caption(campaign: dict, channel: dict, product_title: str) -> dict:
    """카피 생성 실패 시 쓰는 안전 문구. 본문은 업종 프로필에서 온다."""
    body = (config.FALLBACK_BODY or "").replace("{region}", config.BRAND_REGION)
    cta = " · ".join(x for x in (
        f"☎ {config.BRAND_PHONE}" if config.BRAND_PHONE else "",
        config.BRAND_CHANNELS) if x)
    return {
        "headline": f"{product_title} 안내",
        "body": body,
        "cta": cta or "자세히 보기",
        "_fallback": True,
    }



def intake_url(channel: dict, campaign: dict) -> str:
    """광고에 실을 링크. 업종에 따라 목적지가 다르다.

    ⚠ 업종을 안 보면 타투 광고에도 대출 접수폼 주소가 실린다(실제로 발생).
      · intake.target = loan_app  → 대출 접수폼(PUBLIC_BASE/intake)
      · 그 외(none 등)            → 그 업종의 서비스 사이트(brand.site)
    """
    from urllib.parse import urlencode
    utm = campaign.get("utm") or campaign.get("title", "")
    q = urlencode({"channel": f"{channel['platform']}_{channel['id']}", "utm": utm})

    if config.INTAKE_TARGET == "loan_app":
        dest = f"{config.PUBLIC_BASE}/intake?{q}"
    else:
        site = (config.BRAND_SITE or "").strip()
        if not site:
            return ""      # 보낼 곳이 없으면 링크를 넣지 않는다(가짜 주소보다 낫다)
        # 우리 사이트로 보내는 경우엔 짧은 추적 경로를 쓴다.
        # ⚠ 긴 리다이렉트 주소(…adClick?c=…&u=https%3A%2F%2F목적지)를 프롬프트에 주면
        #   LLM 이 u= 안의 목적지를 풀어 '깨끗한' 주소를 본문에 적어버린다(실측).
        #   그러면 사람은 추적되지 않는 링크를 누르고, _caption_text 가 추적 링크를
        #   하나 더 붙여 한 글에 링크가 둘 생긴다. 짧은 경로엔 풀어낼 u= 가 없다.
        tp = track_path(campaign)
        if "/" in tp:
            return "https://" + tp
        if not site.startswith("http"):
            site = "https://" + site
        dest = f"{site}?{q}"

    # 클릭 추적: 목적지로 직행시키면 몇 명이 눌렀는지 알 수 없다.
    # 공개 리다이렉트를 거쳐 기록한 뒤 목적지로 보낸다(로컬 서버는 외부에서 안 보인다).
    track = (config.AD_CLICK_URL or "").strip()
    key = campaign.get("track_key") or ""
    if not (track and key):
        return dest

    from urllib.parse import quote
    ch_key = f"{channel['platform']}_{channel['id']}"
    return (f"{track}?c={quote(key)}&ch={quote(ch_key)}"
            f"&u={quote(dest, safe='')}")


def track_path(campaign: dict) -> str:
    """콘텐츠형 글에 넣을 채널별 추적 경로 (예: headjim-ink.web.app/t/13-195).

    광고형은 adClick 리다이렉트 주소를 그대로 써도 되지만, 콘텐츠형 글에
    cloudfunctions.net 주소가 보이면 그 순간 광고로 읽힌다.
    대신 우리 사이트의 짧은 경로를 적고, 호스팅 rewrite 가 같은 adClick 함수로
    넘긴다. 경로의 코드가 곧 track_key('{campaign_id}-{channel_id}') 라서
    db.add_click() 이 그대로 받는다 — 매핑 테이블이 필요 없다.

    BRAND_SITE 가 없으면 빈 문자열(호출부가 폴백을 쓴다)."""
    site = re.sub(r"^https?://", "", (config.BRAND_SITE or "").strip()).rstrip("/")
    key = str(campaign.get("track_key") or "").strip()
    if not site:
        return ""
    if not re.fullmatch(r"[0-9]+-[0-9]+", key):
        return site          # 추적 키가 없으면 추적 없이 사이트 주소만
    return f"{site}/{config.TRACK_PREFIX}/{key}"


def creative_form(channel: dict) -> str:
    """그 모임에 맞는 소재 형태. 'ad'(광고형) | 'content'(콘텐츠형)

    · allow      홍보를 허용한 곳      → 광고형 배너로 괜찮다
    · topic_only 주제만 지키면 되는 곳  → 콘텐츠형(결과물 공유)
    · unknown    규정이 없는 곳        → 콘텐츠형(더 안전한 쪽)
    · deny       홍보 금지            → 애초에 발행 대상이 아니다
    """
    return "ad" if (channel or {}).get("ad_policy") == "allow" else "content"


def make_caption(campaign: dict, channel: dict, product_title: str, copy_fn=None) -> dict:
    form_url = intake_url(channel, campaign)
    form = creative_form(channel)
    profile = {
        "platform": channel["platform"],
        "audience": channel.get("audience"),
        "tone": channel.get("tone"),
        "topic": channel.get("topic"),
        "form_url": form_url,            # 프롬프트 {form_url} 치환용
        "form": form,
        # 콘텐츠형 프롬프트가 쓰는 값들.
        # ⚠ 콘텐츠형은 본문에 링크를 나열하지 않으므로, 이 주소가 유일한 유입구다.
        #   맨 도메인을 쓰면 클릭을 셀 수 없어 성과 비교가 불가능해진다 → 추적 경로.
        "brand_site": (track_path(campaign) if form == "content" else "")
                      or config.BRAND_SITE or config.BRAND_COMPANY,
        "styles": campaign.get("styles", ""),
    }
    try:
        cap = copy_engine.generate_copy(campaign, profile, _llm=copy_fn)
    except Exception as e:
        print(f"[orchestrator] 카피 생성 실패({type(e).__name__}) → 폴백 캡션 사용")
        cap = _fallback_caption(campaign, channel, product_title)
    cap["form_url"] = form_url
    # ⚠ 소재를 만든 업종을 함께 저장한다.
    #   발행은 서버 프로세스(업종=loan)에서 일어나므로, 여기서 안 박아두면
    #   타투 광고에 대출 면책문구가 붙어 나간다(실제로 발생했다).
    cap["profile_key"] = config.PROFILE_KEY
    cap["disclaimer"] = config.DISCLAIMER or ""
    cap["brand"] = config.BRAND_COMPANY or ""
    return cap


def _caption_text(cap: dict) -> str:
    parts = [cap.get("headline", ""), cap.get("body", ""), cap.get("cta", "")]
    text = "\n\n".join(p for p in parts if p)
    # 접수 링크 보증: 모델이 빠뜨리거나 가짜 자리표시자를 쓴 경우 실제 URL을 덧붙인다.
    url = cap.get("form_url")
    if url and url not in text:
        text = f"{text}\n\n▶ 상담 접수: {url}"
    # 의무 표기 보증: 법으로 요구되는 문구를 LLM 이 넣어주기를 기대하면 안 된다
    #   (실측: 모델이 빠뜨렸고 리허설에서 드러났다).
    #   전단 이미지에 인쇄돼 있더라도, 본문에도 붙여 확실히 남긴다.
    #
    # ★ 소재를 만든 업종의 문구를 쓴다. 발행 프로세스의 업종(보통 loan)을 쓰면
    #   타투 광고에 대출 면책문구가 붙는다.
    d = (cap.get("disclaimer") if "disclaimer" in cap else config.DISCLAIMER) or ""
    d = d.strip()
    if d and d not in text:
        text = f"{text}\n\n{d}"
    return text


# ── 캠페인 실행 ─────────────────────────────────────────────
def run_campaign(campaign: dict, copy_fn=None, channels=None) -> dict:
    """
    campaign: {title, product, goal, product_key?, promo?}
    channels: None 이면 DB의 enabled 채널 사용
    반환: {campaign_id, creatives:[...]}
    """
    cid = db.add_campaign(campaign["title"], goal=campaign.get("goal", ""),
                          product=campaign.get("product", ""))
    channels = channels if channels is not None else db.list_channels(enabled_only=True)
    docs_mode = (config.CONTENT_SOURCE == "docs")
    # ⚠ 채널마다 다른 이미지를 만든다. 예전엔 업종당 1장을 만들어 돌려 썼는데,
    #   발행 직전 게이트(image_cooldown_left)가 '같은 이미지 14일 금지'를 채널 무관
    #   전역으로 걸기 때문에 첫 건만 나가고 나머지가 전부 차단됐다.
    #   게이트를 푸는 게 아니라 소재를 다양화하는 것이 맞다 — 동일 이미지를 여러
    #   그룹에 뿌리는 것이 플랫폼이 가장 빨리 잡는 패턴이기 때문이다.
    show_n = 0                  # 콘텐츠형 격자 일련번호(모티프 조합이 달라진다)
    doc_n = 0                   # 광고형 카드 일련번호

    out = []
    for ch in channels:
        # 업종에 따라 소재 만드는 방식이 다르다.
        #  · flyers : 기성 전단 JPG 를 채널 규격으로 리사이즈(대출 등)
        #  · docs   : 제품 설명서 PDF → AI 카드 생성(InkCraft·미리집 등)
        if docs_mode:
            product_key = config.PROFILE_KEY
            title = config.PROFILE_NAME
            # 지난 채널의 설정이 남아 넘어가지 않게 매번 지운다.
            # (콘텐츠형 소재가 실패해 배너로 넘어갔는데 form 이 남아 있으면
            #  광고 배너에 콘텐츠형 문구가 붙는다)
            campaign.pop("form", None)
            campaign.pop("styles", None)
            image = None

            if creative_form(ch) == "content":
                # 콘텐츠형: 브랜드 배너가 아니라 '결과물 격자'를 쓴다.
                # 주제 중심 모임에서는 배너가 광고로 읽혀 승인 대기·삭제 대상이 된다.
                from content import showcase
                try:
                    out_img = config.CREATIVES_DIR / (
                        f"showcase_{config.PROFILE_KEY}_{ch['platform']}_v{show_n}.png")
                    s = showcase.make(profile_key=config.PROFILE_KEY,
                                      channel=ch["platform"], variant=show_n,
                                      out_path=str(out_img))
                    image = s["path"]
                    campaign["styles"] = ", ".join(s["styles"])
                    campaign["form"] = "content"
                    show_n += 1
                    print(f"[orchestrator] 콘텐츠형 소재 #{show_n} → {image}")
                except Exception as e:
                    print(f"[orchestrator] 콘텐츠형 소재 실패({type(e).__name__}) "
                          f"→ 이 채널은 광고형으로 대체")

            if image is None:
                out_img = config.CREATIVES_DIR / (
                    f"doc_{config.PROFILE_KEY}_{ch['platform']}_v{doc_n}.png")
                r = pamphlet.render_from_doc(channel=ch["platform"],
                                             promo=campaign.get("promo"),
                                             out_path=str(out_img))
                image = r["path"] if isinstance(r, dict) else r
                doc_n += 1
                print(f"[orchestrator] 설명서 카드 #{doc_n} → {image}")
        else:
            product_key = pick_product(ch, campaign)
            tpl = registry.get(product_key)
            if not tpl.get("flyer"):
                print(f"[orchestrator] {product_key}: 전단 JPG 없음 → 스킵(PSD 편집 P2)")
                continue
            title = tpl["title"]
            image = pamphlet.render_from_template(product_key, ch["platform"],
                                                  promo=campaign.get("promo"))

        # 클릭 추적 키 — 캠페인+채널 조합은 크리에이티브 1건과 정확히 대응한다.
        # (크리에이티브 id 는 캡션을 만든 뒤에야 생기므로 여기서는 쓸 수 없다)
        campaign["track_key"] = f"{cid}-{ch['id']}"
        caption = make_caption(campaign, ch, title, copy_fn)
        creative_id = db.add_creative(cid, ch["id"], caption, image)
        approval_id = db.enqueue_approval(creative_id)
        out.append({
            "channel": ch["name"], "platform": ch["platform"],
            "product": product_key, "creative_id": creative_id,
            "approval_id": approval_id, "image": image, "caption": caption,
        })
        print(f"[orchestrator] 크리에이티브 #{creative_id} 준비 "
              f"→ {ch['name']}({ch['platform']}) / {product_key} / 승인#{approval_id}")
    return {"campaign_id": cid, "creatives": out}


# ── 승인 → 발행 ─────────────────────────────────────────────
def _load_creative_channel(creative_id: int) -> dict:
    with db.get_conn() as conn:
        row = conn.execute(
            """SELECT c.id, c.copy_json, c.image_path, c.channel_id,
                      ch.platform, ch.target_ref, ch.name, ch.account,
                      ch.active_hours
               FROM creatives c JOIN channels ch ON c.channel_id = ch.id
               WHERE c.id = ?""", (creative_id,)).fetchone()
    return dict(row) if row else None


def publish_creative(creative_id: int, dry_run: bool = None):
    """크리에이티브 발행 — 어댑터.post() 호출 후 posts 기록. (dry_run 기본=config)"""
    dry = config.GLOBAL_DRY_RUN if dry_run is None else dry_run
    row = _load_creative_channel(creative_id)
    if not row:
        raise ValueError(f"크리에이티브 없음: {creative_id}")

    caption = json.loads(row["copy_json"]) if row["copy_json"] else {}
    text = _caption_text(caption)
    platform = row["platform"]
    account = (dict(row).get("account") or "").strip() or None

    post_id = db.record_post(creative_id, row["channel_id"],
                             status="dry" if dry else "queued")

    if dry:
        # 모의 발행은 브라우저를 쓰지 않으므로 직렬화·로그인이 필요 없다.
        adapter = get_adapter(platform, account)
        res = adapter.post(row["target_ref"], text,
                           image_path=row["image_path"], dry_run=True)
        db.update_post_status(post_id, "dry", getattr(res, "perm_url", None),
                              getattr(res, "error", None))
        print(f"[orchestrator] 발행 post#{post_id} [dry] {row['name']}({platform})")
        return res

    # 데모 채널은 실제로 존재하지 않는 주소다. 켜는 것은 set_channel_enabled 가 막지만,
    # 이미 켜져 있던 채널(과거에 켠 것)은 그 관문을 지나오지 않는다.
    # 발행 직전인 여기가 우회할 수 없는 마지막 지점이다.
    if db.is_demo_channel(row):
        why = "데모 채널 — 실제로 존재하지 않는 주소라 실발행하지 않습니다"
        db.update_post_status(post_id, "blocked", None, why)
        print(f"[orchestrator] 발행 post#{post_id} [blocked] {row['name']}({platform}) — {why}")
        return PostResult(ok=False, blocked=True, error=why)

    # ── 실발행 ── 한 번에 하나만. 클립보드·창 포커스가 머신 전역 자원이라
    #    동시에 두 건이 나가면 엉뚱한 밴드에 엉뚱한 글이 올라간다(되돌릴 수 없음).
    #
    # ⚠ 안전장치 검사는 **반드시 이 잠금 안에서** 한다.
    #   밖에서 검사하면, 앞선 건이 아직 'posted' 로 기록되기 전에 뒤 건이 전부
    #   통과해 같은 밴드에 중복 게시된다(검사와 실행 사이의 틈).
    with _PUBLISH_LOCK:
        def _block(why):
            db.update_post_status(post_id, "blocked", None, why)
            print(f"[orchestrator] 발행 post#{post_id} [blocked] {row['name']}"
                  f"({platform}) — {why}")
            return PostResult(ok=False, blocked=True, error=why)

        # 아래 검사들은 '광고가 안 나가는' 쪽으로 실패해야 한다. 계정을 잃는 것보다 낫다.
        ok_h, why_h = hours_ok(row)
        if not ok_h:
            return _block(why_h)

        left = db.image_cooldown_left(row["image_path"], config.CREATIVE_COOLDOWN_DAYS)
        if left:
            return _block(f"같은 소재를 {config.CREATIVE_COOLDOWN_DAYS}일 안에 다시 쓰지 "
                          f"않습니다(앞으로 {left}일) — 동일 이미지 반복은 가장 빨리 걸립니다")

        adapter = get_adapter(platform, account)
        # 상한 계산에서 지금 이 건은 빼야 한다(안 빼면 N번째가 늘 스스로 막힌다).
        adapter._current_post_id = post_id
        if not adapter._rate_ok(row["channel_id"]):
            return _block(adapter._rate_reason(row["channel_id"]) or "발행 상한 도달")

        # 로그인부터 보장한다.
        # (예전엔 이 단계가 없어서 새 어댑터가 늘 미로그인 상태로 post 를 불렀고
        #  밴드·페북은 100% 차단됐다. 즉 스위치를 켜도 광고가 한 건도 안 나갔다.)
        #
        # ⚠ 로그인도 크로스 잠금 안에서 한다. 밴드 로그인은 **비밀번호를
        #   클립보드에 복사**하기 때문에(band_automator.py:302), 그 순간
        #   다른 파이프라인이 붙여넣으면 공개 글에 비밀번호가 실린다.
        try:
            with crosslock.hold("publish"):
                ok, why = ensure_login(adapter)
                if not ok:
                    return _block(why)
        except crosslock.LockTimeout as e:
            return _block(str(e))

        # ★ 이 자리를 '점유'한다. 이제부터 이 건은 상한 계산에 포함되므로,
        #   대기 중인 다른 요청이 같은 채널로 통과하지 못한다.
        db.update_post_status(post_id, "posting")

        # 직전 발행과 간격을 둔다(무작위). 프로세스 안 잠금(_PUBLISH_LOCK)은 쥔 채
        # 쉬어야 이 프로세스의 다른 건도 함께 늦춰진다.
        # ⚠ 크로스 잠금은 여기서 쥐지 않는다. 90~300초를 잡고 있으면 다른
        #   플랫폼 파이프라인이 그 시간 내내 놀게 된다(분리한 의미가 없어진다).
        _space_out(platform)

        # 자는 사이에 허용 시간대를 벗어났을 수 있다. 실제 게시 직전에 다시 본다.
        ok_h, why_h = hours_ok(row)
        if not ok_h:
            return _block(why_h)

        # 본문 붙여넣기가 클립보드를 쓴다 → 여기가 진짜 배타 구간이다.
        try:
            with crosslock.hold("publish"):
                res = adapter.post(row["target_ref"], text,
                                   image_path=row["image_path"], dry_run=False)
        except crosslock.LockTimeout as e:
            return _block(str(e))

        # blocked(안전장치가 막음)와 failed(실제 발행 실패)를 구분해야
        # 운영자가 상한 도달을 계정 차단으로 오인해 재시도를 반복하지 않는다.
        if res.ok:
            status = "posted"
            db.mark_creative_posted(creative_id)     # 소재 쿨다운 시작
        elif getattr(res, "blocked", False):
            status = "blocked"
        else:
            status = "failed"
            # 발행이 진짜로 실패했으면 세션이 도중에 끊겼을 수 있다.
            # 캐시를 비워 다음 시도가 로그인부터 다시 하게 한다.
            # (안 그러면 _logged_in=True 가 굳어 영원히 같은 실패를 반복한다)
            drop_adapter(platform, account)

    db.update_post_status(post_id, status, getattr(res, "perm_url", None),
                          getattr(res, "error", None))
    print(f"[orchestrator] 발행 post#{post_id} [{status}] {row['name']}({platform})"
          + (f" — {res.error}" if getattr(res, "error", None) else ""))
    return res


def approve_and_publish(approval_id: int, reviewer: str = "operator",
                        dry_run: bool = None):
    """승인 처리 후 즉시 발행(기본 dry-run)."""
    with db.get_conn() as conn:
        row = conn.execute("SELECT creative_id FROM approvals WHERE id=?",
                           (approval_id,)).fetchone()
    if not row:
        raise ValueError(f"승인 항목 없음: {approval_id}")
    # ⚠ 이미 처리된 승인이면 다시 발행하지 않는다.
    #   승인 버튼을 두 번 누르는 것만으로 같은 밴드에 같은 글이 두 번 올라간다.
    #   발행은 되돌릴 수 없으므로 여기서 확실히 끊는다.
    if not db.decide_approval(approval_id, "approved", reviewer):
        why = "이미 처리된 승인입니다 — 중복 발행을 막았습니다"
        print(f"[orchestrator] 승인#{approval_id} {why}")
        return PostResult(ok=False, blocked=True, error=why)
    return publish_creative(row["creative_id"], dry_run=dry_run)


def approve_and_schedule(approval_id: int, run_at, reviewer: str = "operator"):
    """승인 처리 후 지정 시각에 발행 예약(즉시 발행 대신). 재시작 복구됨."""
    import scheduler   # 지연 import (순환 회피)
    with db.get_conn() as conn:
        row = conn.execute("SELECT creative_id FROM approvals WHERE id=?",
                           (approval_id,)).fetchone()
    if not row:
        raise ValueError(f"승인 항목 없음: {approval_id}")
    db.decide_approval(approval_id, "approved", reviewer)   # creatives.approved=1
    job = scheduler.schedule_publish(row["creative_id"], run_at)
    return {"scheduled": True, "job_id": job.id, "creative_id": row["creative_id"],
            "run_at": str(run_at)}


# ── 데모용 채널 시드 ────────────────────────────────────────
def seed_demo_channels():
    """드라이런 데모용 채널 2개(밴드 소비자 / 카카오 사업자) 등록·활성화."""
    ids = []
    ids.append(db.add_channel("band", "https://band.us/band/DEMO", name="부동산 정보방(데모)",
                              audience="consumer", tone="친근", topic="부동산담보", enabled=True))
    ids.append(db.add_channel("kakao", "사업자 대출 단톡(데모)", name="사업자 대출 단톡(데모)",
                              audience="business", tone="간결", topic="사업자", enabled=True))
    return ids
