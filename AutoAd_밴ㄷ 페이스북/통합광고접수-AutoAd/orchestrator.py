# ============================================================
#  orchestrator.py — 지휘부  (P1-8)
#  캠페인 → 채널성향으로 상품 자동선택 → 전단 크리에이티브 + 캡션
#         → DB 크리에이티브·승인큐 → (승인) → dry-run/실발행 → posts 기록
#  * 얇게 유지: 실제 일은 각 모듈에 위임, 여기선 조율만.
#  * 카피 생성 실패(크레딧/네트워크) 시 브랜드 기반 폴백 캡션으로 자동 대체.
# ============================================================
import os
import re
import sys
import json
import zlib          # 재활용 문구 선택 씨앗 — hash() 는 프로세스마다 값이 달라진다
import time
import atexit
import random
import threading
import contextlib
from datetime import datetime

import config
import db
import crosslock          # 밴드·페북 파이프라인이 클립보드를 두고 부딪히지 않게
from content import registry, pamphlet, copy_engine


def _cp949_safe_orch(s: str) -> str:
    """cp949 콘솔에 그대로 찍혀도 죽지 않도록 인코딩 불가 문자를 이스케이프한다.

    ⚠ 실측(2026-08-05): _space_out() 의 print() 에 낀 em dash 하나가
      cp949 콘솔에서 UnicodeEncodeError 를 던졌다. _PUBLISH_LOCK 은
      with 블록이라 예외가 나도 정상적으로 풀리지만, 그 앞에서 이미
      db.update_post_status(post_id,"posting") 이 실행된 뒤였다 - 그
      결과 발행 job 5개가 전부 '조용히 실패해 종료'됐는데 DB 상태만
      'posting' 에 영구히 남아 겉보기엔 진행 중처럼 보였다(승인 콘솔
      에서 수십 분을 기다려도 안 끝나는 것처럼 보인 원인). threads
      패키지에 이미 같은 함수(reply_writer._cp949_safe)가 있지만,
      orchestrator.py 는 band/facebook/kakao 도 다루는 범용 모듈이라
      threads 패키지를 끌어오지 않고 여기 그대로 둔다."""
    return s.encode("cp949", errors="backslashreplace").decode("cp949")
from channels.base import PostResult
from channels.band import BandAdapter
from channels.facebook import FacebookAdapter
from channels.kakao import KakaoAdapter
from channels.threads import ThreadsAdapter

# 플랫폼 → 어댑터 (P0-3 인터페이스로 통일)
ADAPTERS = {
    "band": BandAdapter,
    "facebook": FacebookAdapter,
    "kakao": KakaoAdapter,
    "threads": ThreadsAdapter,
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
            "facebook": config.FACEBOOK_ACCOUNT,
            "threads": config.THREADS_ACCOUNT}.get(platform, "")


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

# next_free_slot() 이 방금 내준 슬롯을 플랫폼별로 기억한다.
#
# ⚠ 실측(2026-08-05): 최근 실제 발행이 오래전(1시간 이상)이면 첫 슬롯은
#   '거의 지금'으로 계산된다 - 정상이다. 문제는 그 다음이다. '거의 지금'
#   으로 잡힌 job 은 APScheduler 가 즉시 실행하고, "date" 트리거는 1회성
#   이라 실행되는 순간 스토어에서 사라진다(직접 확인: 예약 0.57초 뒤
#   get_jobs() 가 이미 빈 목록). 반면 db.last_post_time() 은 그 job 이
#   '실제로 posted 상태에 도달'해야만 갱신되는데, 그건 브라우저 발행이
#   끝나는 60~90초 뒤다. 그 사이(예약 직후 ~ 실제 posted 기록까지)
#   next_free_slot() 은 그 job 을 스토어에서도, last_post_time 에서도
#   못 본다 - 두 데이터 소스 모두에게 '존재하지 않는' 셈이 되어, 뒤이은
#   승인 5건이 전부 같은 '거의 지금' 슬롯을 받았다(재현: 6건을 10초
#   간격으로 승인 → job 1개가 _PUBLISH_LOCK 을 잡고 나머지 5개는 전부
#   같은 시각에 예약돼 락 하나를 놓고 줄줄이 대기).
#
#   그래서 세 번째 정보원을 더한다 - '슬롯을 내준 시각' 그 자체를 여기
#   즉시 기록한다. 실제 발행 완료를 기다리지 않으므로 이 틈을 못 놓친다.
#   in-process 메모리라 서버 재시작 시 초기화되지만, 한 번의 승인 폭주
#   (연달아 승인 누르는 상황) 안에서는 같은 프로세스로 처리되므로 충분하다.
_LAST_RESERVED_AT = {}


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


def _space_key(platform: str = None, account: str = None) -> str:
    """간격을 세는 단위. 플랫폼+계정.

    ⚠ 계정을 빼면 같은 플랫폼의 두 번째 계정이 첫 번째 계정 때문에 기다린다.
      밖에서 보면 서로 다른 사람이라 늦출 이유가 없다."""
    return f"{platform or ''}|{account or ''}"


def _seconds_since_last_post(platform: str = None, account: str = None) -> float:
    """그 플랫폼·계정의 마지막 발행 이후 경과 초. 프로세스 메모리와 DB 중 더 최근 것.

    메모리만 믿으면 프로세스를 재시작한 직후 첫 발행이 간격 없이 즉시 나간다
    (감독기가 서버를 되살리는 일이 잦으므로 실제로 일어난다).
    DB 도 함께 보므로 파이프라인을 따로 띄워도 간격이 지켜진다."""
    mem = _LAST_POST_AT.get(_space_key(platform, account), 0.0)
    mem_elapsed = (time.time() - mem) if mem else None
    db_elapsed = None
    try:
        last = db.last_post_time(platform=platform, account=account)
        if last:
            db_elapsed = max(0.0, (datetime.now() - last).total_seconds())
    except Exception:
        pass
    cands = [x for x in (mem_elapsed, db_elapsed) if x is not None]
    return min(cands) if cands else None


def publish_interval(platform: str = None) -> tuple:
    """그 플랫폼의 발행 간격(초) 범위.

    쓰레드 답글은 남의 글에 붙으므로 내 담벼락 게시물보다 촘촘하면 안 된다.
    그래서 별도 설정을 둔다(THREADS_REPLY_INTERVAL_*). 예전엔 _space_out 이
    공용값(90~300)만 봐서 이 설정이 아무 데도 안 쓰이고 있었다.

    ⚠ POST_INTERVAL_MAX <= 0 은 '간격을 두지 마라'는 전역 신호로 취급한다.
      플랫폼별 값이 이걸 무시하면, 그 신호를 믿고 있던 쪽이 조용히 몇 분씩
      자게 된다 — 실측(2026-08-04): 이 함수가 쓰레드 전용 값을 읽도록 바꾸자
      POST_INTERVAL 을 0 으로 막아 둔 기존 테스트가 267초를 자기 시작했다
      (전체 스위트 35초 → 8분). 운영에서 이 값을 0 으로 두는 것은 '지금은
      간격 없이 내보낸다'는 뜻이므로 플랫폼을 가릴 이유도 없다."""
    if config.POST_INTERVAL_MAX <= 0:
        return 0, 0
    if platform == "threads":
        return config.THREADS_REPLY_INTERVAL_MIN, config.THREADS_REPLY_INTERVAL_MAX
    return config.POST_INTERVAL_MIN, config.POST_INTERVAL_MAX


def next_free_slot(platform: str = None):
    """이 플랫폼에서 다음으로 발행해도 되는 가장 이른 시각(datetime).

    두 가지를 함께 본다.
      · 마지막 **실제** 발행 시각 (db.last_post_time — posting 은 제외)
      · 이미 **예약**돼 있는 같은 플랫폼 발행 중 가장 늦은 것

    예약분을 안 보면, 승인을 연달아 누를 때 전부 '지금'으로 예약돼
    한꺼번에 나간다(간격 장치가 무력화된다)."""
    import datetime as _dt
    lo, hi = publish_interval(platform)
    gap = _dt.timedelta(seconds=random.randint(min(lo, hi), max(lo, hi)))
    now = _dt.datetime.now()

    earliest = now
    last = db.last_post_time(platform)
    if last:
        earliest = max(earliest, last + gap)

    try:
        import scheduler
        for j in scheduler.get_scheduler().get_jobs():
            run_at = getattr(j, "next_run_time", None)
            # ⚠ 실측(2026-08-05): scheduler.schedule_publish() 는 job id 를
            #   f"pub-{creative_id}" 로 만드는데(scheduler.py:79), 여기서는
            #   "publish:" 접두사(콜론)를 찾고 있었다 — 하이픈/콜론이 달라
            #   기존 예약을 단 하나도 못 찾았다. 그 결과 next_free_slot() 이
            #   매번 '지금'에 가까운 시각을 돌려줬고, 승인을 30초 간격으로
            #   6번 하자 예약도 30초 간격으로 잡혔다(의도는 180~600초).
            #   실제 발행은 _PUBLISH_LOCK 을 쥔 채 진행되므로, 겹친 예약들이
            #   락 하나를 놓고 줄줄이 대기하며 앞 건의 스페이싱 대기(최대
            #   600초)+실제 게시 시간만큼씩 뒤로 밀렸다 — '멈춘 것'이 아니라
            #   '한 시간 넘게 순서를 기다리는 중'이었다.
            if not run_at or not str(j.id).startswith("pub-"):
                continue
            run_at = run_at.replace(tzinfo=None)
            # 이 플랫폼 건인지 확인 — creative_id 로 채널을 되짚는다.
            args = getattr(j, "args", ()) or ()
            if args and platform:
                row = _load_creative_channel(args[0])
                if not row or row["platform"] != platform:
                    continue
            earliest = max(earliest, run_at + gap)
    except Exception:
        # 스케줄러가 안 떠 있으면(스크립트 실행 등) 예약분은 없는 것으로 본다.
        pass

    # 세 번째 정보원 - 방금 내준 슬롯(아직 완료·심지어 시작도 안 됐을 수
    # 있다). db.last_post_time() 도 스케줄러 스캔도 못 보는 '예약 직후 ~
    # 실제 발행 완료 전' 구간을 이걸로 메운다.
    reserved = _LAST_RESERVED_AT.get(platform or "")
    if reserved:
        earliest = max(earliest, reserved + gap)

    _LAST_RESERVED_AT[platform or ""] = earliest
    return earliest


def _space_out(platform: str = None, account: str = None):
    """직전 발행과 최소 간격을 둔다. 연달아 나가면 기계임이 드러난다.

    간격은 **계정별로** 센다. 계정 A 가 방금 올렸다고 계정 B 를 기다리게 하면
    계정을 늘린 만큼 발행이 느려질 뿐, 위장 효과는 늘지 않는다."""
    key = _space_key(platform, account)
    lo, hi = publish_interval(platform)
    if hi <= 0:
        _LAST_POST_AT[key] = time.time()
        return
    wait = random.randint(min(lo, hi), max(lo, hi))
    elapsed = _seconds_since_last_post(platform, account)
    if elapsed is not None and elapsed < wait:
        left = int(wait - elapsed)
        # 실측(2026-08-05): 이 줄의 em dash 가 cp949 콘솔에서 발행 job
        # 5개를 통째로 죽인 적이 있다(_cp949_safe_orch 독스트링 참고).
        # 문구를 고치는 것만으론 다음에 또 같은 실수를 못 막으므로,
        # 여기서 인코딩 가능 여부와 무관하게 항상 필터를 거친다.
        who = (platform or "전체") + (f"/{account}" if account else "")
        print(_cp949_safe_orch(f"[orchestrator] 발행 간격 유지({who}) - {left}초 대기"))
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


# 창 없는 모드(headless)로는 로그인이 되지 않는 플랫폼.
#   밴드는 아이디·비밀번호를 **클립보드에 복사해 Ctrl+V 로 붙여넣는다**
#   (band_automator.login). 창이 없으면 붙여넣기가 먹지 않아 빈 값으로 제출되고,
#   "로그인 최종 실패"로 끝난다. 게다가 밴드는 band_session 이 세션 전용 쿠키라
#   저장된 쿠키로 복원되지 않으므로 **매번 이 경로를 탄다**.
#   실측(2026-08-10): 사람이 직접 돌리면(창 있음) 성공, 자동 루프에서는
#   (창 없음) 100% 실패했다. 세 계정 모두 같은 증상.
_NEEDS_WINDOW_TO_LOGIN = {"band"}


def _allow_window_for_login(adapter):
    """로그인에 창이 필요한 플랫폼이면 창을 쓰도록 바꾼다.

    이미 만들어진 드라이버가 창 없이 떠 있으면 그것부터 버려야 한다.
    (headless 는 드라이버를 만들 때 정해지므로 나중에 바꿔도 소용없다)
    """
    if getattr(adapter, "platform", "") not in _NEEDS_WINDOW_TO_LOGIN:
        return
    if not getattr(adapter, "headless", False):
        return
    adapter.headless = False
    auto = getattr(adapter, "_auto", None)
    if auto is not None:
        try:
            auto._safe_quit_driver()
        except Exception:
            pass
        adapter._auto = None


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
    print(f"[login] 세션 만료 - 저장된 계정으로 자동 로그인 "
          f"({cred.get('name') or acc} / {cred['login_type']})")
    # ⚠ 여기서부터는 실제 로그인 폼을 조작한다. 밴드는 창이 없으면 붙여넣기가
    #   먹지 않아 반드시 실패하므로, 창 없는 모드였다면 창을 띄워 다시 만든다.
    _allow_window_for_login(adapter)
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
    print(f"[login] 자동 로그인 성공 - {adapter.platform}/{acc}")
    return True, ""


# ── 상품 선택 (성향 라우팅) ─────────────────────────────────
# 한 장에 완결된 광고 여러 개가 타일로 붙어 있는 시트.
# ⚠ 규제 업종(대출)에서는 쓸 수 없다 - 시트 하단에 의무표기 띠를 하나
#   붙여도, 타일 하나하나가 그 자체로 독립된 광고라 개별 타일은 필수기재를
#   갖추지 못한다(각 타일에 헤드라인·전화번호·상호가 따로 인쇄돼 있다).
#   타일 단위 슬라이싱(P2) 전까지는 아예 고르지 않는다.
_TILED_SHEET_CATEGORIES = ("배너",)


def _tiled_sheet_blocked(product: dict) -> bool:
    if not config.is_regulated(config.PROFILE_KEY):
        return False
    return str((product or {}).get("category") or "") in _TILED_SHEET_CATEGORIES


def pick_product(channel: dict, campaign: dict, used=None) -> str:
    """캠페인이 상품을 지정하면 그것, 아니면 채널 성향에 맞는 상품 중 하나.

    ⚠ 예전엔 늘 cands[0] 만 골라, 소비자 채널 140곳에 전부 같은 전단이 나갔다.
      같은 계정이 같은 그림·같은 문구를 여러 방에 뿌리는 것이 가장 빨리 걸리는 패턴이다.
      채널 id 로 돌려가며 고른다(무작위가 아니라 채널마다 고정 — 재현 가능해야 한다)."""
    if campaign.get("product_key"):
        return campaign["product_key"]
    cands = [p for p in registry.by_audience(channel.get("audience", "mixed"))
             if p.get("flyer") and not _tiled_sheet_blocked(p)]
    if not cands:
        return "general"
    # ⚠ 쿨다운 중인 전단을 고르면 소재를 만들어놓고 발행 단계에서 막힌다.
    #   (실측: 9건 중 6건이 '만들자마자 차단'이었다)
    #   여기서 미리 빼야 만든 소재가 실제로 나간다.
    plat = channel.get("platform", "band")
    free = [p for p in cands
            if not db.image_cooldown_left(
                str(config.CREATIVES_DIR / f"tpl_{p['key']}_{plat}.png"),
                config.CREATIVE_COOLDOWN_DAYS)]
    if free:
        cands = free          # 전부 쿨다운이면 어쩔 수 없이 원래 후보로(발행이 막아준다)
    # 같은 캠페인 안에서 두 채널이 같은 전단을 고르면, 렌더 경로가 같아져
    # 뒤엣것이 발행 단계에서 '같은 이미지'로 막힌다.
    # ⚠ 남은 전단이 없으면 **소재를 만들지 않는다**(None 반환).
    #   억지로 같은 전단을 배정해봐야 발행에서 막히고, 그때까지 카피 생성
    #   비용만 나간다. 실측: 소비자용 전단 4종에 채널 9곳을 배정해 4건이 중복.
    fresh = [p for p in cands if p["key"] not in (used or ())]
    if not fresh:
        return None
    idx = int(channel.get("id") or 0) % len(fresh)
    return fresh[idx]["key"]


# 문구 안에 박힌 '그 소재 전용' 추적 경로. track_path() 가 만든 형태
#   예: headjim-ink.web.app/t/16-193   ('/t/{캠페인}-{채널}')
_TRACK_IN_TEXT = re.compile(r"[\w.-]+/t/[\w-]+")


def _claimed_images(round_id: str = None) -> set:
    """**앞으로 나갈 소재가 잡고 있는** 이미지 경로.

    같은 그림에 소재가 둘 붙으면 첫 건이 나가는 순간 나머지가 쿨다운에 막힌다.
    그래서 이미 배정된 그림은 새 소재에 다시 주지 않는다.

    ⚠ 기준은 '아직 발행 안 됨'이 아니라 **'아직 발행될 수 있음'**이다.
      승인이 이미 소모된 소재(approved/rejected)는 발행이 blocked·failed 로
      끝났어도 다시 시도되지 않는다 — 그런데도 그림을 영구히 붙들고 있었다.
      실측(2026-08-14): 잡힌 소재 540건 중 **533건이 이 죽은 소재**였고,
      그 탓에 이미지 292장 중 쓸 수 있는 것이 2장까지 줄었다.
      pending 만 세도록 바꾸니 재고가 되살아난다.

    ⚠ 같은 바퀴(round_id)가 잡은 것은 제외하지 않는다. 한 바퀴 안에서는
      여러 채널이 **같은 그림을 공유하는 것이 정상**이기 때문이다.
    """
    sql = ("SELECT DISTINCT cr.image_path FROM creatives cr "
           "JOIN approvals a ON a.creative_id = cr.id "
           "WHERE COALESCE(cr.image_path,'') <> '' AND a.state = 'pending'")
    args = []
    if round_id:
        sql += " AND COALESCE(cr.round_id,'') <> ?"
        args.append(round_id)
    with db.get_conn() as con:
        return {r[0] for r in con.execute(sql, args) if r[0]}


def new_round_id() -> str:
    """한 바퀴의 식별자. run_campaign 실행마다 새로 찍는다.

    ⚠ '같은 캠페인' 으로 묶으면 안 된다. 캠페인을 두 번 돌리면 두 바퀴가 한
      덩어리로 보여 그림이 재사용되지 않는다.
    """
    import uuid
    return uuid.uuid4().hex


def _round_pool(fmt: str, n_images: int, round_id: str) -> list:
    """이 바퀴가 쓸 (번호, 경로) 목록. 재고가 모자라면 있는 만큼만 돌려준다.

    조건은 기존 _existing_free 와 같다 — 파일이 있고, 쿨다운이 아니고,
    **다른 바퀴의** 미발행 소재가 잡고 있지 않을 것.
    """
    taken = _claimed_images(round_id)
    out = []
    for n in range(0, 200):
        if len(out) >= max(0, n_images):
            break
        path = str(config.CREATIVES_DIR / fmt.format(n=n))
        if path in taken or not os.path.isfile(path):
            continue
        if db.image_cooldown_left(path, config.CREATIVE_COOLDOWN_DAYS):
            continue
        out.append((n, path))
    return out


def pick_for_channel(pool: list, idx: int):
    """채널 순번 idx 에 그림을 배정한다. 풀을 순환하며 고르게 나눈다."""
    if not pool:
        raise ValueError("이 바퀴에 쓸 그림이 없습니다")
    return pool[idx % len(pool)]


def _recycled_caption(campaign: dict, channel: dict, new_track: str) -> dict:
    """예전에 LLM 이 만들어 검증까지 통과한 문구를 **돌려 쓴다**.

    왜 필요한가 — 카피 API 가 죽으면 폴백은 업종마다 문장이 하나뿐이라, 같은
    방에 몇 번을 올려도 글이 똑같아진다. 그게 위험한 것이지 '생성 실패' 자체가
    위험한 게 아니다. DB 에는 예전에 만들어 검증을 통과한 문구가 수백 개 남아
    있으니(2026-08-13 실측: adstudio 166·printcraft 131·loan 113·inkcraft 89),
    그걸 쓰면 API 없이도 문구가 갈린다.

    ⚠ 본문에 박힌 추적 경로는 **반드시 새 것으로 바꾼다**. 그대로 두면 클릭이
      예전 캠페인·채널의 추적키로 잡혀 성과가 뒤섞이고, 그 소재가 사라졌으면
      죽은 링크가 나간다. 재활용 대상 517개 중 363개에 이게 박혀 있었다.

    ⚠ 같은 채널에 이미 나간 문구는 고르지 않는다. 재활용의 목적이 '문구를
      가르는 것'인데 같은 방에 같은 글을 다시 내면 아무 의미가 없다.

    ⚠ **같은 그림에 붙었던 문구만** 고른다. 업종만 맞추면 임야담보 전단에
      토지담보 문구가 붙는다(2026-08-13 실측 3건 전부 불일치). 대부업 광고에서
      전단과 본문이 다른 상품을 말하면 오인 소지가 있다. 같은 그림 문구가
      없으면 재활용하지 않는다 — 어설프게 맞추느니 안 내보내는 게 낫다.

    못 고르면 None — 호출부가 기존 폴백으로 간다(그 폴백은 발행에서 막힌다).
    """
    pk = config.PROFILE_KEY or ""
    img = (campaign or {}).get("_image_path") or ""
    if not pk or not img:
        return None
    try:
        with db.get_conn() as con:
            rows = con.execute(
                "SELECT cr.copy_json FROM creatives cr "
                "JOIN channels ch ON ch.id = cr.channel_id "
                "WHERE ch.profile_key = ? AND ch.platform = ? "
                "  AND COALESCE(cr.copy_json,'') <> '' "
                # 같은 그림이어야 문구와 전단이 같은 상품을 말한다
                "  AND cr.image_path = ? "
                # ⚠ 여기서 채널로 거르지 않는다. 전단 파일명이 (상품×플랫폼)별로
                #   고정이라 한 그림의 소재가 한 채널에 몰려 있다(실측: tpl_toji_band
                #   43건이 전부 ch52). 채널로 빼면 후보가 0이 되어 폴백으로 떨어진다.
                #   중복은 아래 _recent_texts_for_channel 이 **실제 발행된 것**만
                #   기준으로 막는다 — 초안까지 버릴 이유는 없다.
                "ORDER BY cr.id DESC LIMIT 400",
                (pk, channel.get("platform"), img)).fetchall()
    except Exception:
        return None

    used = _recent_texts_for_channel(channel.get("id"))
    pool = []
    for r in rows:
        try:
            d = json.loads(r["copy_json"]) or {}
        except Exception:
            continue
        if d.get("_fallback"):
            continue          # 폴백을 재활용하면 폴백이다
        h, b, cta = (str(d.get(k) or "") for k in ("headline", "body", "cta"))
        if len(f"{h}{b}".strip()) < 30:
            continue
        if _TRACK_IN_TEXT.sub("", f"{h} {b} {cta}") in used:
            continue
        pool.append((h, b, cta))
    if not pool:
        return None

    # 어느 것을 고를지는 채널마다 갈라야 한다. track_key 를 씨앗으로 쓰면
    # 같은 채널은 늘 같은 선택이라 재현 가능하고, 채널이 다르면 서로 갈린다.
    seed = zlib.crc32(str(new_track or channel.get("id") or "").encode("utf-8"))
    h, b, cta = pool[seed % len(pool)]

    def fix(t):
        # 옛 추적 경로 → 새 추적 경로. 새 경로가 없으면 문장에서 걷어낸다.
        return _TRACK_IN_TEXT.sub(new_track, t) if new_track else _TRACK_IN_TEXT.sub("", t)

    return {"headline": fix(h), "body": fix(b), "cta": fix(cta), "_recycled": True}


def _recent_texts_for_channel(channel_id) -> set:
    """이 채널에 이미 나간 문구들(추적 경로는 뺀 상태로 비교)."""
    if not channel_id:
        return set()
    try:
        with db.get_conn() as con:
            rows = con.execute(
                "SELECT cr.copy_json FROM posts p "
                "JOIN creatives cr ON cr.id = p.creative_id "
                "WHERE p.channel_id = ? AND p.status = 'posted'",
                (channel_id,)).fetchall()
    except Exception:
        return set()
    out = set()
    for r in rows:
        try:
            d = json.loads(r["copy_json"]) or {}
        except Exception:
            continue
        t = " ".join(str(d.get(k) or "") for k in ("headline", "body", "cta"))
        out.add(_TRACK_IN_TEXT.sub("", t))
    return out


# ── 캡션 생성 (실패 시 폴백) ────────────────────────────────
def _fallback_caption(campaign: dict, channel: dict, product_title: str) -> dict:
    """카피 생성 실패 시 쓰는 안전 문구. 본문은 업종 프로필에서 온다.

    ⚠ 여기까지 오면 문장이 **하나뿐**이다. 같은 방에 반복되면 안 되므로
      db.not_fallback_sql 이 발행 단계에서 막는다. 먼저 _recycled_caption 을
      시도하고, 그것도 없을 때만 여기로 온다."""
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

    # 짧은 추적 경로가 가능하면 업종을 가리지 않고 그걸 쓴다.
    # ⚠ 긴 리다이렉트 주소(…adClick?c=…&u=https%3A%2F%2F목적지)를 프롬프트에 주면
    #   LLM 이 u= 안의 목적지를 풀어 '깨끗한' 주소를 본문에 적어버린다(실측).
    #   그러면 사람은 추적되지 않는 링크를 누르고, _caption_text 가 추적 링크를
    #   하나 더 붙여 한 글에 링크가 둘 생긴다. 짧은 경로엔 풀어낼 u= 가 없다.
    tp = track_path(campaign)
    if "/" in tp:
        return "https://" + tp

    if config.INTAKE_TARGET == "loan_app":
        dest = f"{config.PUBLIC_BASE}/intake?{q}"
    else:
        site = (config.BRAND_SITE or "").strip()
        if not site:
            return ""      # 보낼 곳이 없으면 링크를 넣지 않는다(가짜 주소보다 낫다)
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
    # 사람을 실제로 보내는 사이트를 기준으로 삼는다.
    # ⚠ 대출 업종은 BRAND_SITE 가 비어 있고(접수폼으로 보내므로) 목적지가
    #   PUBLIC_BASE 다. 그걸 안 보면 대출 광고만 긴 adClick 주소가 나간다.
    site = (config.BRAND_SITE or "").strip()
    if not site and config.INTAKE_TARGET == "loan_app":
        site = config.PUBLIC_BASE or ""
    site = re.sub(r"^https?://", "", site.strip()).rstrip("/")
    key = str(campaign.get("track_key") or "").strip()
    if not site:
        return ""
    if not re.fullmatch(r"[0-9]+-[0-9]+", key):
        return site          # 추적 키가 없으면 추적 없이 사이트 주소만
    # rewrite 를 올리지 않은 사이트에는 짧은 경로를 쓰지 않는다.
    # 클릭을 못 세는 정도가 아니라, Vercel 처럼 404 를 주는 곳에서는
    # 광고를 누른 사람이 오류 페이지를 보게 된다(실측: mirizip.com).
    if site.lower() not in config.TRACK_SITES:
        return site
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
    # ⚠ 채널의 topic/tone 은 그 채널을 '처음 분류했을 때'의 값이다.
    #   업종(profile_key)만 바꾸고 이 값을 그대로 두면, 예를 들어 대출 채널이던
    #   밴드가 adstudio 로 바뀌어도 topic 은 '부동산 담보대출' 로 남아 있어
    #   AI 광고영상 광고에 대출 문구가 실린다(실측: 4건 전부 대출 카피).
    #   광고할 상품은 캠페인·업종이 정한다. 채널은 '누구에게·어떤 말투로'만 준다.
    subject = (campaign.get("product") or product_title
               or config.PROFILE_NAME or channel.get("topic") or "")
    profile = {
        "platform": channel["platform"],
        "audience": channel.get("audience"),
        "tone": channel.get("tone"),
        "topic": subject,
        "form_url": form_url,            # 프롬프트 {form_url} 치환용
        "form": form,
        # 콘텐츠형 프롬프트가 쓰는 값들.
        # ⚠ 콘텐츠형은 본문에 링크를 나열하지 않으므로, 이 주소가 유일한 유입구다.
        #   맨 도메인을 쓰면 클릭을 셀 수 없어 성과 비교가 불가능해진다 → 추적 경로.
        "brand_site": (track_path(campaign) if form == "content" else "")
                      or config.BRAND_SITE or config.BRAND_COMPANY,
        "styles": campaign.get("styles", ""),
    }
    # 상품명이 비면 프롬프트의 '상품:' 칸이 빈칸으로 들어가고, LLM 은 남은 단서인
    # 채널 topic 에만 의존하게 된다. 업종 이름이라도 반드시 채운다.
    camp = dict(campaign)
    camp["product"] = subject
    try:
        cap = copy_engine.generate_copy(camp, profile, _llm=copy_fn)
    except Exception as e:
        # ⚠ 예외 **메시지**까지 남긴다. 타입만 찍으면 'ValueError' 뿐이라 원인을
        #   알 수 없다. copy_engine 은 어떤 검사에 걸렸는지를 메시지에 담아 던지는데
        #   (예: "카피 검증 실패(재시도 3회): 도구 표기 누락(...)"), 그걸 버리고 있었다.
        #   그 바람에 폴백이 조용히 쌓였다 — 2026-08-13 실측: 최근 소재의 23%가
        #   폴백이었고 weddingstudio·lifealbum 은 100% 였는데 로그로는 알 수 없었다.
        #   폴백은 업종마다 문장이 고정이라, 같은 방에 같은 글이 반복해서 나간다.
        # 폴백보다 먼저 **예전 문구 재활용**을 시도한다. 폴백은 문장이 하나뿐이라
        # 같은 방에 반복되지만, 재활용은 서로 다른 글이 나간다.
        cap = _recycled_caption(camp, channel, profile.get("brand_site") or "")
        if cap:
            print(f"[orchestrator] 카피 생성 실패({type(e).__name__}: {e}) "
                  f"→ 예전 문구 재활용")
        else:
            print(f"[orchestrator] 카피 생성 실패({type(e).__name__}: {e}) "
                  f"→ 재활용할 문구도 없어 폴백 캡션 사용")
            cap = _fallback_caption(campaign, channel, product_title)
    cap["form_url"] = form_url
    # ⚠ 소재를 만든 업종을 함께 저장한다.
    #   발행은 서버 프로세스(업종=loan)에서 일어나므로, 여기서 안 박아두면
    #   타투 광고에 대출 면책문구가 붙어 나간다(실제로 발생했다).
    cap["profile_key"] = config.PROFILE_KEY
    cap["disclaimer"] = config.DISCLAIMER or ""
    # ★ 법정 필수기재사항(대부업법 제9조 등). 선언한 업종에만 값이 있다.
    #   ⚠ LLM 출력 **바깥**에서 붙인다. copy_engine 은 이 키를 만들지도,
    #     읽지도 않는다 - 카피 재생성이 문구를 고쳐 쓸 수 없어야 한다.
    cap["mandatory"] = config.MANDATORY_DISCLOSURE or ""
    cap["brand"] = config.BRAND_COMPANY or ""
    return cap


def _mandatory_for(cap: dict, prof: str = None) -> str:
    """이 소재에 붙일 법정 필수기재 문구.

    ★ 저장된 값보다 **업종 프로필의 현재 값**을 우선한다.
      copy_engine.regenerate() 는 {headline, body, cta} 만 돌려주고
      approval._update_caption() 이 copy_json 을 갈아끼우므로, 운영자가
      승인 콘솔에서 '수정'을 한 번 누르면 저장된 의무표기가 날아간다.
      발행 시점에 업종에서 다시 읽으면 그 구멍으로 빠져나갈 수 없다.
      업종을 모를 때만(레거시 소재) 저장된 값을 쓴다.

    ⚠ 업종이 확정됐으면 그 업종의 값을 **빈 문자열이라도 그대로 믿는다**.
      예전엔 빈 문자열일 때 저장된 cap['mandatory'] 로 폴백했는데, 그건
      '이 업종은 의무표기를 선언하지 않았다(= 절대 붙이면 안 된다)' 는
      뜻이라 폴백 방향이 거꾸로였다. mirizip 소재에 대출 문구가 남아
      있으면 그대로 인테리어 광고에 붙는다."""
    key = str(prof or cap.get("profile_key") or "").strip()
    if key:
        return (config.mandatory_disclosure(key) or "").strip()
    return str(cap.get("mandatory") or "").strip()


# 문장 끝 마침표 — **앞 글자가 한글일 때만** 문장 끝으로 본다.
# ⚠ 단순히 `\.\s+` 로 나누면 '연 20.0% (연 환산 기준)' 의 소수점과
#   'headjim-loan.web.app/t/98-52' 의 점까지 문장 끝으로 오인해 링크가
#   두 동강 난다. 한글 뒤의 마침표만 본다(…중요합니다. / …보세요.).
_SENTENCE_END = re.compile(r"(?<=[가-힣])\.[ \t]+")


def _paragraphize(body: str) -> str:
    """본문을 문장마다 문단으로 나눈다.

    카피 모델은 서너 문장을 한 덩어리로 내놓는다. 밴드·페북 본문에서는
    그게 벽처럼 보여서 읽히지 않는다(운영자 지적, 2026-08-11).

    ⚠ **본문에만** 쓴다. 면책문구와 법정 필수기재에는 절대 쓰지 말 것.
      그쪽은 시행령 [별표1] 지정문구라 '한 글자도 바꾸지 말 것' 이 원칙이고,
      disclosure._squash() 비교와 fingerprint() 지문이 공백에 물려 있다.
      줄바꿈을 끼워 넣으면 지문이 달라져 발행이 막힌다.
    """
    b = str(body or "").strip()
    if not b:
        return b
    return _SENTENCE_END.sub(".\n\n", b)


def _caption_text(cap: dict, prof: str = None) -> str:
    parts = [cap.get("headline", ""),
             _paragraphize(cap.get("body", "")),
             cap.get("cta", "")]
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
    # ★ 법정 필수기재사항 - 면책문구와 별개다. 선언한 업종(대출)에만 붙는다.
    m = _mandatory_for(cap, prof)
    if m and m not in text and not _mandatory_baked_in(cap, prof):
        text = f"{text}\n\n{m}"
    return text


def _post_needs_crosslock(adapter) -> bool:
    """발행(본문 입력) 구간에 프로세스 간 잠금이 필요한가.

    필요하다 = 그 엔진이 본문을 **클립보드로** 붙여넣는다는 뜻이다. 클립보드는
    머신에 하나뿐이라 두 파이프라인이 동시에 쓰면 서로의 글을 붙여넣는다.

    ⚠ 판단이 안 서면 **True**(잠근다). 잘못 False 를 주면 엉뚱한 방에 엉뚱한
      글이 올라가고 되돌릴 수 없다 - 느린 것보다 훨씬 나쁘다.

    False 는 아래 둘을 **모두** 만족할 때만 준다:
      1) 엔진 모듈이 CLIPBOARD_FREE_POST = True 를 스스로 선언한다.
         선언을 엔진 파일에 두었기 때문에, 그 파일을 예전 판으로 되돌리면
         선언이 사라져 잠금이 자동으로 복구된다.
      2) 그 드라이버에서 CDP 가 실제로 동작한다. 엔진은 CDP 가 실패하면
         클립보드로 되돌아가므로, 여기서 확인하지 않으면 '잠금 없이
         클립보드를 쓰는' 최악의 구간이 생긴다.
    """
    try:
        auto = adapter._automator()
    except Exception:
        return True
    mod = sys.modules.get(type(auto).__module__)
    if not getattr(mod, "CLIPBOARD_FREE_POST", False):
        return True                      # 선언이 없다 = 클립보드를 쓴다고 본다
    drv = getattr(auto, "driver", None)
    if drv is None:
        return True
    ok = getattr(auto, "_cdp_ok", None)
    if ok is None:
        try:
            drv.execute_cdp_cmd("Browser.getVersion", {})
            ok = True
        except Exception as e:
            print(f"[publish] CDP 사용 불가({type(e).__name__}) - 크로스 잠금 유지")
            ok = False
        try:
            auto._cdp_ok = ok
        except Exception:
            pass
    return not ok


def _mandatory_baked_in(cap: dict, prof: str = None) -> bool:
    """이 소재의 **이미지**에 현재 값 그대로 의무표기 띠가 구워져 있는가.

    왜 보는가 — pamphlet.stamp_mandatory_band() 는 전단 위아래로 캔버스를 늘려
    헤더 띠(상호·등록번호)와 하단 띠(13항목)를 굽는다. 실측(2026-08-11):
    발행 이미지 1024x2940 중 띠가 1346px, **이미지의 45.8%**다. 그런데 본문에도
    같은 14줄을 또 붙이고 있었다. 같은 내용이 두 번 나가면서 게시글이 전단보다
    고지글로 보인다(운영자 지적).

    ⚠ 판정 근거는 **지문 일치 하나뿐**이다. _profile_gate C(아래 942행 부근)가
      발행 직전에 같은 값을 대조해 불일치면 발행 자체를 막는다. 그러니
      '지문이 맞다' = '이 이미지에 지금 값 그대로 띠가 있다' 가 성립한다.
    ⚠ 지문이 없거나 다르면 **반드시 본문에 넣는다**(이 함수가 False 를 준다).
      띠가 없는 소재까지 빼면 의무표기가 아예 없는 광고가 나간다 - 미표기는
      중복보다 훨씬 나쁘다. 쓰레드 답글·레거시 소재가 여기에 해당한다.
    ⚠ 승인 콘솔 프리뷰(approval._caption_text)는 **일부러 그대로 둔다**.
      그 화면은 광고가 아니라 사람이 법정 문구를 눈으로 확인하는 게이트다.
    """
    key = str(prof or cap.get("profile_key") or "").strip()
    if not key:
        return False
    want = str(config.mandatory_fingerprint(key) or "").strip()
    got = str(cap.get("mandatory_img") or "").strip()
    return bool(want) and got == want


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
    # ★ 의무표기가 미완성이면 **소재를 아예 만들지 않는다**.
    #   왜 발행 게이트만으로는 부족한가 - disclosure.lines() 는 값이 빈 항목의
    #   줄을 조용히 뺀다. 그 상태로 소재를 구우면 '항목이 빠진 띠'가 이미지에
    #   영구히 박히고, 나중에 프로필을 채워 게이트가 열려도 그 이미지는 옛날
    #   그대로 나간다. 만들지 않는 것이 유일하게 안전한 선택이다.
    #   ⚠ 선언하지 않은 업종 14개는 항상 빈 목록 → 무영향.
    _cgaps = config.compliance_gaps(config.PROFILE_KEY)
    if _cgaps:
        print(f"[orchestrator] {config.PROFILE_KEY} 업종 법정 필수기재사항 미완성 "
              f"- 소재를 만들지 않습니다: {', '.join(_cgaps)}")
        return {"campaign_id": cid, "creatives": []}
    # ★ 업종 x 플랫폼 화이트리스트를 **소재를 만들기 전에** 적용한다.
    #   아래 루프는 채널마다 Gemini 이미지를 새로 만든다 - 발행 직전에만
    #   막으면 나가지도 못할 소재의 생성 비용을 그대로 지불하게 된다.
    _allowed = [ch for ch in channels
                if config.platform_allowed(config.PROFILE_KEY, ch.get("platform"))]
    _dropped = len(channels) - len(_allowed)
    if _dropped:
        # 조용히 사라지면 '왜 소재가 안 만들어지지'가 된다. 반드시 알린다.
        allow = ", ".join(config.profile_allow_platforms(config.PROFILE_KEY))
        print(f"[orchestrator] {config.PROFILE_KEY} 업종 허용 플랫폼이 아니라 "
              f"채널 {_dropped}개 제외 (allow_platforms: {allow or '제한없음'})")
    channels = _allowed
    docs_mode = (config.CONTENT_SOURCE == "docs")
    # ⚠ 채널마다 다른 이미지를 만든다. 예전엔 업종당 1장을 만들어 돌려 썼는데,
    #   발행 직전 게이트(image_cooldown_left)가 '같은 이미지 14일 금지'를 채널 무관
    #   전역으로 걸기 때문에 첫 건만 나가고 나머지가 전부 차단됐다.
    #   게이트를 푸는 게 아니라 소재를 다양화하는 것이 맞다 — 동일 이미지를 여러
    #   그룹에 뿌리는 것이 플랫폼이 가장 빨리 잡는 패턴이기 때문이다.
    # ⚠ 0 부터 다시 시작하면 지난 캠페인이 만든 파일을 덮어쓴다. 경로가 같으니
    #   쿨다운에 그대로 걸려, 만들자마자 발행이 막히는 소재가 된다(실측 4건).
    def _free_from(fmt, start=0, limit=200):
        """아직 안 쓴 일련번호. 쿨다운뿐 아니라 **미발행 소재가 이미 잡은 번호**도 건너뛴다.

        ⚠ 예전에는 쿨다운만 봤다. 쿨다운은 '발행된' 이미지에만 걸리므로, 만들어
          두고 아직 안 나간 소재의 번호는 늘 '비어 있음'으로 나왔다. 그래서 주기마다
          같은 번호를 골라 **같은 파일을 덮어썼다**.
          실측(2026-08-12): 미발행 inkcraft 소재 19건 중 **15건**이
          showcase_inkcraft_facebook_v17.png 하나를 공유하고 있었다. 그 상태에서는
          첫 건이 나가는 순간 나머지 14건이 전부 이미지 쿨다운에 걸려 막힌다 -
          이미지 생성비만 쓰고 광고는 안 나간다.
        """
        taken = _claimed_images()
        for n in range(start, limit):
            path = str(config.CREATIVES_DIR / fmt.format(n=n))
            if path in taken:
                continue            # 아직 안 나간 소재가 이 파일을 쓰고 있다
            if not db.image_cooldown_left(path, config.CREATIVE_COOLDOWN_DAYS):
                return n
        return start

    # _existing_free 는 '한 바퀴는 이미지를 나눠 쓴다'로 바뀌며 _round_pool 로
    # 대체됐다(재고 재사용 후보를 찾는 역할은 같지만, 이번 실행에서 쓴 경로를
    # 전부 배제하는 대신 이 바퀴의 풀에서 순환 배정한다).

    show_n = 0                  # 콘텐츠형 격자 일련번호(모티프 조합이 달라진다)
    doc_n = 0                   # 광고형 카드 일련번호
    used_products = set()       # 이번 캠페인에서 이미 쓴 전단

    round_id = new_round_id()   # 이번 run_campaign 실행 전체가 공유하는 바퀴 식별자
    # 한 그림이 덮는 채널 수 상한(config.IMAGE_FANOUT_MAX)에서 이 바퀴가 쓸 장수를 정한다.
    # ⚠ tools/auto_loop.py 의 images_per_round() 와 같은 식이다. orchestrator 는
    #   tools/ 를 import 하지 않고(auto_loop 가 orchestrator 를 import 하므로
    #   반대 방향은 순환 import) _round_pool 이 장수를 인자로만 받으므로 여기서
    #   다시 계산한다 — 상한(IMAGE_FANOUT_MAX) 계산식을 고치면 두 곳을 같이 봐야 한다.
    n_imgs = max(1, -(-len(channels) // max(1, config.IMAGE_FANOUT_MAX)))

    out = []
    for ch_index, ch in enumerate(channels):
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
                fmt = f"showcase_{config.PROFILE_KEY}_{ch['platform']}_v{{n}}.png"
                try:
                    if getattr(config, "IMAGE_GEN_LOCKED", False):
                        # 생성이 잠겨 있으면 **만들어둔 재고**로 돈다.
                        # 그림에 무엇이 있는지는 variant 로 되살린다(styles_for).
                        # ⚠ 이 바퀴의 풀에서 채널 순번대로 나눠 배정한다 — 옛날
                        #   _used_paths 는 이번 실행 안의 재사용을 전부 막았지만,
                        #   지금은 한 바퀴 안에서 여러 채널이 같은 그림을 공유하는
                        #   것이 정상이다(스펙 §5.6).
                        pool = _round_pool(fmt, n_imgs, round_id)
                        if not pool:
                            raise RuntimeError(
                                "이미지 생성이 잠겨 있고, 쓸 수 있는 기존 이미지도 "
                                "없습니다(전부 쿨다운이거나 다른 바퀴가 잡고 있음)")
                        v, path = pick_for_channel(pool, ch_index)
                        image = path
                        # ⚠ tiles_n 은 채널 규격(showcase.tiles_for)이 아니라
                        #   재사용하는 그 이미지 자신의 치수(tiles_in_image)로
                        #   준다 — 재고와 채널 규격이 어긋나는 파일이 있어서다
                        #   (실측: 75장 중 26장). 이 한 줄을 나중에 리팩터링
                        #   하더라도 tiles_n=showcase.tiles_in_image(path) 는
                        #   반드시 남아야 한다. 지우면 캡션이 그림에 없는
                        #   스타일을 말하거나 있는 스타일을 빠뜨리게 된다.
                        campaign["styles"] = ", ".join(
                            showcase.styles_for(
                                config.PROFILE_KEY, v,
                                tiles_n=showcase.tiles_in_image(path)))
                        campaign["form"] = "content"
                        print(f"[orchestrator] 콘텐츠형 소재 **재사용** v{v} → {image}")
                    else:
                        # 쿨다운에 안 걸린 첫 번호부터 쓴다(지난 캠페인 파일을 덮지 않는다).
                        show_n = _free_from(fmt, show_n)
                        out_img = config.CREATIVES_DIR / fmt.format(n=show_n)
                        s = showcase.make(profile_key=config.PROFILE_KEY,
                                          channel=ch["platform"], variant=show_n,
                                          out_path=str(out_img))
                        image = s["path"]
                        campaign["styles"] = ", ".join(s["styles"])
                        campaign["form"] = "content"
                        show_n += 1
                        print(f"[orchestrator] 콘텐츠형 소재 #{show_n} → {image}")
                except Exception as e:
                    # ⚠ 여기도 메시지를 남긴다. 'ClientError' 만 찍히면 할당량 초과인지
                    #   키 문제인지 프롬프트 거부인지 구분할 수 없다(같은 이유로
                    #   make_caption 쪽도 고쳤다). 길면 잘라서라도 남긴다.
                    print(f"[orchestrator] 콘텐츠형 소재 실패"
                          f"({type(e).__name__}: {str(e)[:300]}) "
                          f"→ 이 채널은 광고형으로 대체")

            if image is None:
                dfmt = f"doc_{config.PROFILE_KEY}_{ch['platform']}_v{{n}}.png"
                if getattr(config, "IMAGE_GEN_LOCKED", False):
                    # ⚠ 콘텐츠형과 같은 이유로 풀에서 나눠 배정한다(위 주석 참고).
                    pool = _round_pool(dfmt, n_imgs, round_id)
                    if not pool:
                        print(f"[orchestrator] {ch['name'][:26]}: 이미지 생성 잠금 + "
                              f"쓸 수 있는 기존 카드 없음 → 건너뜀")
                        continue
                    v, path = pick_for_channel(pool, ch_index)
                    image = path
                    print(f"[orchestrator] 설명서 카드 **재사용** v{v} → {image}")
                else:
                    doc_n = _free_from(dfmt, doc_n)
                    out_img = config.CREATIVES_DIR / dfmt.format(n=doc_n)
                    r = pamphlet.render_from_doc(channel=ch["platform"],
                                                 promo=campaign.get("promo"),
                                                 out_path=str(out_img))
                    image = r["path"] if isinstance(r, dict) else r
                    doc_n += 1
                    print(f"[orchestrator] 설명서 카드 #{doc_n} → {image}")
        else:
            product_key = pick_product(ch, campaign, used_products)
            if not product_key:
                # 이 채널 성향에 맞는 전단이 동났다(쿨다운 또는 이미 사용).
                # 소재를 만들어도 발행에서 막히므로 여기서 멈춘다.
                print(f"[orchestrator] {ch['name'][:26]}: 쓸 수 있는 전단 없음 → 건너뜀 "
                      f"(전단을 늘리거나 쿨다운이 풀릴 때까지 대기)")
                continue
            used_products.add(product_key)
            tpl = registry.get(product_key)
            if not tpl.get("flyer"):
                print(f"[orchestrator] {product_key}: 전단 JPG 없음 → 스킵(PSD 편집 P2)")
                continue
            title = tpl["title"]
            image = pamphlet.render_from_template(product_key, ch["platform"],
                                                  promo=campaign.get("promo"),
                                                  profile_key=config.PROFILE_KEY)

        # 클릭 추적 키 — 캠페인+채널 조합은 크리에이티브 1건과 정확히 대응한다.
        # (크리에이티브 id 는 캡션을 만든 뒤에야 생기므로 여기서는 쓸 수 없다)
        campaign["track_key"] = f"{cid}-{ch['id']}"
        # ⚠ 문구 재활용이 **같은 그림의** 문구만 고르도록 이미지를 넘긴다.
        #   안 넘기면 임야담보 전단에 토지담보 문구가 붙는다(2026-08-13 실측).
        #   대부업 광고에서 전단과 본문이 다른 상품을 말하면 오인 소지가 있다.
        campaign["_image_path"] = image
        caption = make_caption(campaign, ch, title, copy_fn)
        # ★ 이 이미지에 실제로 구워진 의무표기의 지문. 발행 직전에 현재 값과
        #   대조해, 값이 바뀐 뒤에 옛 이미지가 나가는 것을 막는다(_profile_gate C).
        caption["mandatory_img"] = config.mandatory_fingerprint(config.PROFILE_KEY)
        # 이 실행(바퀴)에서 만든 소재라는 표식 — _claimed_images(round_id) 가
        # 같은 바퀴의 다른 채널이 잡은 그림은 막지 않도록 이걸로 구분한다.
        creative_id = db.add_creative(cid, ch["id"], caption, image, round_id=round_id)
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
                      ch.active_hours, ch.profile_key
               FROM creatives c JOIN channels ch ON c.channel_id = ch.id
               WHERE c.id = ?""", (creative_id,)).fetchone()
    return dict(row) if row else None


# 업종 표식(profile_key)을 잃어버린 loan 소재를 잡아내는 마지막 단서.
# ⚠ 여기 없는 문자열은 게이트를 그냥 통과한다. loan 프로필의 상호가 바뀌면
#   반드시 같이 고칠 것.
# ⚠ 상호 하나만으로는 상호를 안 싣는 소재를 못 잡는다. 대출 소재라면 거의
#   반드시 들어가는 문자열을 함께 본다(등록번호·업종어). 타 업종 14개의
#   카피에는 나올 수 없는 문자열만 고른다 - 여기에 흔한 단어를 넣으면
#   인테리어 광고가 대출로 오판돼 발행이 막힌다.
_LOAN_TOKENS = ("더스틴홀딩스", "대부중개업", "2026-대구중구-0002")


def _creative_profile(row, caption: dict = None) -> str:
    """이 소재가 어느 업종인지. 모르면 None(= 제한 없음으로 취급).

    다중 신호로 본다:
      1) copy_json.profile_key  — 정상 경로(make_caption 이 박아 준다)
      2) channels.profile_key   — 채널에 업종이 지정돼 있으면 그것
      3) 본문에 loan 브랜드 토큰 — 표식을 잃은 레거시 대출 소재 구멍 막기
    'None = loan 이 아님'이다. 업종 불명이라고 전부 막으면 profile_key 가
    없는 레거시 소재(승인 대기 중인 것 포함)가 통째로 죽는다."""
    cap = caption or {}
    prof = str(cap.get("profile_key") or "").strip()
    if prof:
        return prof
    prof = str((dict(row) if row else {}).get("profile_key") or "").strip()
    if prof:
        return prof
    blob = " ".join(v for v in cap.values() if isinstance(v, str))
    if any(t in blob for t in _LOAN_TOKENS):
        return "loan"
    return None


def _profile_gate(prof: str, platform: str, caption: dict = None) -> str:
    """발행을 막아야 하면 사유 문자열, 괜찮으면 None.

    ⚠ 사유 문자열은 콘솔(cp949)에 찍힌다. em dash·이모지 금지 - ASCII
      하이픈만 쓴다(_cp949_safe_orch 독스트링 참고)."""
    # A) 업종 x 플랫폼
    # ★ 판정 대상은 **소재의 업종(prof)** 이다. config.PROFILE_KEY(발행
    #   프로세스의 업종)로 보면, 쓰레드용으로 AUTOAD_PROFILE 을 바꾸는 순간
    #   loan 소재가 threads 로 샌다. config.py 의 platform_allowed 주석이
    #   요구하는 동작이기도 하다. prof 가 None 이면 제한 없음으로 취급된다
    #   (표식 없는 레거시 소재를 통째로 죽이지 않기 위함).
    if not config.platform_allowed(prof, platform):
        return (f"{prof} 업종은 {platform} 발행 대상이 아닙니다"
                f"(프로필 allow_platforms)")

    # B) 법정 필수기재사항 - 값이 비어 있으면 발행하지 않는다.
    #   ⚠ 없는 값을 '그럴듯하게 지어내 채우는' 것이 최악이다. 막는 쪽이 맞다.
    #   ⚠ 선언하지 않은 업종(loan 외 전부)은 항상 빈 목록 → 무영향.
    if prof:
        if config.compliance_expired(prof):
            return (f"대부중개업 등록 유효기간 만료"
                    f"({config.compliance_valid_to(prof)}) - "
                    f"갱신 전에는 발행하지 않습니다")
        missing = config.compliance_missing(prof)
        if missing:
            return ("법정 필수기재사항 미설정: " + ", ".join(missing) +
                    " - 대부업법 제9조 위반 상태라 발행하지 않습니다"
                    " (프로필을 고쳤다면 서비스를 재시작해야 반영됩니다)")

    # C) 소재 **이미지**에 구워진 의무표기가 지금 값과 같은가.
    #   ⚠ A/B 는 프로필 값만 본다. 그런데 이미지는 소재를 만든 시점의 값으로
    #     띠를 굽고, 발행은 row["image_path"] 를 그대로 쓴다. 즉 '이자율이
    #     비었을 때 만든 이미지'(그 줄이 빠진 띠)를 나중에 값만 채워 발행하면
    #     A/B 는 통과하고 이미지에는 그 항목이 없다. 여기서 막는다.
    #   ⚠ 선언 안 한 업종은 want == "" → 검사 자체가 없다(무회귀).
    if prof and caption is not None:
        want = config.mandatory_fingerprint(prof)
        if want:
            got = str(caption.get("mandatory_img") or "").strip()
            if got != want:
                return ("소재 이미지에 구워진 법정 필수기재 표기가 현재 값과 "
                        f"다릅니다(소재 {got or '없음'} / 현재 {want}) - "
                        "소재를 다시 만들어야 합니다")
    return None


def _link_threads_target(post_url: str, creative_id: int):
    """실발행 성공 시 threads_targets 를 이 크리에이티브에 연결해 작성자
    쿨다운(replied_at)을 시작한다(디스패치 항목 4).

    threads/runner.py(Task 6)는 자동발행이 실제로 성공했을 때만
    db.threads_target_link_creative() 를 부른다. 승인 큐를 거쳐 나가는
    답글도 같은 규칙 — '실발행 성공 시에만' — 을 지켜야 쿨다운 시계가
    dry-run 이나 승인 대기 상태만으로 앞서 나가지 않는다.

    orchestrator 는 threads_targets 를 몰랐으므로(디스패치 원문), 여기서
    필요한 최소한만 안다 — post_url 로 그 원글의 id 를 찾아 넘겨준다는
    사실 하나뿐이다. 점수·검수 사유 같은 나머지 지식은 threads/ 쪽
    책임으로 남겨 둔다. db.py 에는 'post_url 로 조회'만 하는 전용
    함수가 없고 db.py 는 이 태스크의 수정 대상이 아니므로, 이미 이
    파일의 다른 곳(_load_creative_channel 등)에서 쓰는 것과 같은
    방식으로 db.get_conn() 을 직접 사용한다."""
    if not post_url:
        return
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM threads_targets WHERE post_url=?", (post_url,)).fetchone()
    if row:
        db.threads_target_link_creative(row["id"], creative_id)


def publish_creative(creative_id: int, dry_run: bool = None):
    """크리에이티브 발행 — 어댑터.post() 호출 후 posts 기록. (dry_run 기본=config)"""
    dry = config.GLOBAL_DRY_RUN if dry_run is None else dry_run
    row = _load_creative_channel(creative_id)
    if not row:
        raise ValueError(f"크리에이티브 없음: {creative_id}")

    caption = json.loads(row["copy_json"]) if row["copy_json"] else {}
    platform = row["platform"]
    # ⚠ 쓰레드 답글은 나머지 세 채널과 본문·대상을 만드는 방식 자체가
    #   다르다. copy_json 에는 headline/body/cta 가 없고 reply 하나뿐이라
    #   _caption_text() 로 만들면 빈 문자열이 나가고(디스패치 항목 2),
    #   대상도 channels.target_ref(=계정 @핸들)가 아니라 답글을 달 원글
    #   URL(copy_json.target_url)이어야 한다(디스패치 항목 3). 이 두 줄
    #   이외에는 band/facebook/kakao 경로를 절대 건드리지 않는다.
    # 이 소재의 업종. 게이트와 의무표기 주입이 같은 값을 봐야 한다
    # (게이트는 통과시켰는데 다른 업종의 문구가 붙는 상황을 만들지 않는다).
    prof = _creative_profile(row, caption)
    if platform == "threads":
        text = caption.get("reply") or ""
        target = caption.get("target_url") or ""
    else:
        text = _caption_text(caption, prof)
        target = row["target_ref"]
    account = (dict(row).get("account") or "").strip() or None

    post_id = db.record_post(creative_id, row["channel_id"],
                             status="dry" if dry else "queued")

    if dry:
        # 모의 발행은 브라우저를 쓰지 않으므로 직렬화·로그인이 필요 없다.
        adapter = get_adapter(platform, account)
        res = adapter.post(target, text,
                           image_path=row["image_path"], dry_run=True)
        # ⚠ 모의 발행은 업종 게이트로 '막지 않는다'. 아무 것도 안 나가는데
        #   막으면 사전 점검 자체가 불가능해진다. 대신 실발행 때 막힐
        #   것이라는 사실을 경고로 남긴다(조용히 통과시키면 운영자는
        #   dry 성공을 보고 실발행도 될 거라 믿는다).
        warn = _profile_gate(prof, platform, caption)
        db.update_post_status(post_id, "dry", getattr(res, "perm_url", None),
                              getattr(res, "error", None)
                              or (f"[실발행 시 차단됨] {warn}" if warn else None))
        print(f"[orchestrator] 발행 post#{post_id} [dry] {row['name']}({platform})"
              + (f" - [실발행 시 차단됨] {_cp949_safe_orch(warn)}" if warn else ""))
        return res

    # 데모 채널은 실제로 존재하지 않는 주소다. 켜는 것은 set_channel_enabled 가 막지만,
    # 이미 켜져 있던 채널(과거에 켠 것)은 그 관문을 지나오지 않는다.
    # 발행 직전인 여기가 우회할 수 없는 마지막 지점이다.
    if db.is_demo_channel(row):
        why = "데모 채널 - 실제로 존재하지 않는 주소라 실발행하지 않습니다"
        db.update_post_status(post_id, "blocked", None, why)
        print(f"[orchestrator] 발행 post#{post_id} [blocked] {row['name']}({platform}) - {why}")
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
            # ⚠ why 는 아래 여러 호출부에서 오는데, cp949 로 인코딩 안 되는
            # 문자(em dash 등)가 섞여 있으면 이 print() 자체가 죽는다 -
            # 실측(2026-08-05)으로 같은 유형 사고를 여러 번 겪었다.
            safe_why = _cp949_safe_orch(why)
            print(f"[orchestrator] 발행 post#{post_id} [blocked] {row['name']}"
                  f"({platform}) - {safe_why}")
            return PostResult(ok=False, blocked=True, error=why)

        # 아래 검사들은 '광고가 안 나가는' 쪽으로 실패해야 한다. 계정을 잃는 것보다 낫다.

        # ★ 업종 게이트 — 두 가지를 본다(_profile_gate 참고).
        #   A) 업종 x 플랫폼: loan 은 band/facebook 에만 나간다.
        #   B) 법정 필수기재사항: 등록번호·광고용전화·이자율·부대비용·경고문구·
        #      중개수수료 고지가 하나라도 비면 loan 소재는 발행하지 않는다.
        #      등록 유효기간 만료도 여기서 막는다.
        #   ⚠ 반드시 이 잠금 안에서 판정한다. 밖에서 보면 판정과 발행 사이에
        #     설정(프로필·등록번호·이자율)이 바뀔 틈이 생긴다.
        why_p = _profile_gate(prof, platform, caption)
        if why_p:
            return _block(why_p)

        ok_h, why_h = hours_ok(row)
        if not ok_h:
            return _block(why_h)

        # ★ 그림이 있어야 할 소재인데 파일이 없으면 발행하지 않는다.
        #   ⚠ 실측(2026-08-10): 이사 뒤 creatives.image_path 가 옛 PC 의
        #     D:\Antigravity... 를 가리켜 132건 **전부** 파일이 없었다. 그런데도
        #     광고 20건이 그대로 나갔다 — 밴드는 '파일 없음(건너뜀)' 만 찍고 게시
        #     버튼을 눌렀고(band_automator._attach_images), 페북은 send_keys 실패를
        #     except 로 삼킨 뒤 게시했다. 둘 다 DB 에는 posted 로 남아서, 반나절
        #     동안 아무도 몰랐다.
        #   그림 없는 광고는 본문만 남아 사실상 스팸 글이다. 201개 방에 그게
        #   반복되면 신고가 가장 빨리 붙는다. 안 나가는 쪽이 낫다.
        img = row["image_path"]
        if img and not os.path.isfile(img):
            # 메시지에 em dash 를 쓰지 않는다 - _cp949_safe_orch 가 — 로
            # 이스케이프해서 콘솔 로그가 읽기 나빠진다(위 _block 주석 참고).
            return _block(f"소재 이미지 파일이 없습니다 - 발행하지 않습니다: {img}")

        left = db.image_cooldown_left(row["image_path"], config.CREATIVE_COOLDOWN_DAYS,
                                      channel_id=row["channel_id"])
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
        _space_out(platform, account)

        # 자는 사이에 허용 시간대를 벗어났을 수 있다. 실제 게시 직전에 다시 본다.
        ok_h, why_h = hours_ok(row)
        if not ok_h:
            return _block(why_h)

        # 발행 구간의 크로스 잠금 — **클립보드를 쓰는 엔진일 때만** 잡는다.
        #   밴드는 2026-08-11 부터 CDP Input.insertText 로 본문을 넣어 클립보드를
        #   쓰지 않는다(band_automator.CLIPBOARD_FREE_POST). 그런 엔진까지 묶어
        #   두면 밴드가 글을 쓰는 동안 페북이 통째로 놀게 된다.
        #   ⚠ 로그인 구간(위)의 잠금은 그대로다 - 거기서는 **비밀번호**가
        #     클립보드로 간다.
        need_lock = _post_needs_crosslock(adapter)
        try:
            with (crosslock.hold("publish") if need_lock
                  else contextlib.nullcontext()):
                res = adapter.post(target, text,
                                   image_path=row["image_path"], dry_run=False)
        except crosslock.LockTimeout as e:
            return _block(str(e))

        # blocked(안전장치가 막음)와 failed(실제 발행 실패)를 구분해야
        # 운영자가 상한 도달을 계정 차단으로 오인해 재시도를 반복하지 않는다.
        if res.ok:
            status = "posted"
            db.mark_creative_posted(creative_id)     # 소재 쿨다운 시작
            if platform == "threads":
                # 승인 경로로 나간 답글도 자동발행(threads/runner.py)과
                # 같은 규칙을 지킨다 — '실발행 성공' 시점에만 threads_targets
                # 를 이 크리에이티브에 잇는다(디스패치 항목 4). dry-run
                # 이었다면 여기까지 오지 않는다(위 `if dry:` 에서 이미
                # return 했다) — 그러니 dry-run 이 작성자 쿨다운을
                # 오염시키는 일(threads/runner.py 가 막아 놓은 바로 그
                # 사고)은 이 위치에서 조건 없이도 이미 일어날 수 없다.
                _link_threads_target(target, creative_id)
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
    # res.error 는 어댑터가 만든 값이다 - threads 답글이면 LLM 생성 실패
    # 사유가 그대로 실릴 수 있어 cp949 필터를 반드시 거친다.
    err = getattr(res, "error", None)
    print(f"[orchestrator] 발행 post#{post_id} [{status}] {row['name']}({platform})"
          + (f" - {_cp949_safe_orch(err)}" if err else ""))
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
        why = "이미 처리된 승인입니다 - 중복 발행을 막았습니다"
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
