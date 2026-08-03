# ============================================================
#  preflight.py — 실가동 준비 상태 점검 (읽기 전용, 발행/로그인 안 함)
#  실행: python preflight.py
#  능력별로 무엇이 준비됐고 무엇이 막혔는지 진단.
# ============================================================
import sys
import io
import importlib
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import config

OK, WARN, NO = "✅", "⚠️ ", "❌"
results = {}


def line(sym, label, detail=""):
    print(f"  {sym} {label}" + (f"  — {detail}" if detail else ""))


def dep(mod):
    try:
        importlib.import_module(mod)
        return True
    except Exception:
        return False


def reachable(url):
    try:
        import requests
        requests.get(url, timeout=1.5)
        return True
    except Exception:
        return False


print("=" * 60)
print(" AutoAd 실가동 준비 점검 (preflight)")
print("=" * 60)

# 1) 시크릿 / 모드
print("\n[1] 시크릿 · 모드")
has_anthropic = bool(config.ANTHROPIC_API_KEY)
line(OK if has_anthropic else NO, "ANTHROPIC_API_KEY",
     "설정됨(크레딧은 live 카피 테스트로 확인)" if has_anthropic else "미설정 → 카피 생성 불가")
line(OK if config.GROQ_API_KEY else WARN, "GROQ_API_KEY", "서류분석용" if config.GROQ_API_KEY else "미설정(접수 서류 AI분석만 영향)")
line(OK if config.TELEGRAM_TOKEN else WARN, "TELEGRAM_TOKEN", "모바일 승인 알림" if config.TELEGRAM_TOKEN else "미설정(웹 승인은 됨)")
line(WARN if not config.GLOBAL_DRY_RUN else OK, "GLOBAL_DRY_RUN",
     ("0 = 실발행 무장!" if not config.GLOBAL_DRY_RUN else "1 = 안전(발행 모의)"))
line(OK, "일일 발행 상한", f"{config.DAILY_POST_LIMIT}건/일")
_copy_model = config.COPY_MODEL_GEMINI if config.COPY_PROVIDER == "gemini" else config.COPY_MODEL
line(OK, "카피 제공자", f"{config.COPY_PROVIDER} ({_copy_model})")
results["카피"] = bool(config.GEMINI_API_KEY if config.COPY_PROVIDER == "gemini" else config.ANTHROPIC_API_KEY)

# 2) 파이썬 의존성
print("\n[2] 파이썬 의존성")
deps = {
    "anthropic": "카피", "PIL": "팜플렛", "fastapi": "웹", "uvicorn": "웹",
    "apscheduler": "스케줄", "sqlalchemy": "스케줄",
    "selenium": "밴드/페북", "webdriver_manager": "밴드/페북", "pyperclip": "밴드/페북",
    "requests": "공용",
}
missing = [m for m in deps if not dep(m)]
for m, use in deps.items():
    line(OK if dep(m) else NO, m, use)
if missing:
    line(WARN, "설치 필요", f"pip install {' '.join('Pillow' if m=='PIL' else m for m in missing)}")

# 3) 발행 엔진 · 도구
print("\n[3] 발행 엔진 · 도구")
band_eng = Path(config.FB_PROJECT_APP_DIR) / "band_automator.py"
fb_eng = Path(config.FB_PROJECT_APP_DIR) / "facebook_automator.py"
ahk_script = Path(config.KAKAO_PROJECT_DIR) / "kakao_send.ahk"
line(OK if band_eng.exists() else NO, "밴드 엔진", str(band_eng))
line(OK if fb_eng.exists() else NO, "페북 엔진", str(fb_eng))
line(OK if ahk_script.exists() else NO, "카카오 AHK 스크립트", str(ahk_script))
try:
    from channels.kakao import KakaoAdapter
    ahk_exe = KakaoAdapter()._ahk_exe()
except Exception:
    ahk_exe = None
line(OK if ahk_exe else WARN, "AutoHotkey", ahk_exe or "미설치 → 카카오 실전송 불가(autohotkey.com)")
results["밴드"] = band_eng.exists() and dep("selenium")
results["페북"] = fb_eng.exists() and dep("selenium")
results["카카오"] = ahk_script.exists() and bool(ahk_exe)

# 4) 콘텐츠 자산
print("\n[4] 콘텐츠 자산")
try:
    from content import registry
    prods = registry.products()
    with_flyer = [p for p in prods if p.get("flyer")]
    line(OK if with_flyer else NO, "전단 템플릿", f"{len(with_flyer)}/{len(prods)}종 (즉시사용)")
    results["팜플렛"] = bool(with_flyer)
except Exception as e:
    line(NO, "전단 템플릿", f"로드 실패: {e}")
    results["팜플렛"] = False
line(OK if reachable(config.PRINTCRAFT_BASE) else WARN, "PrintCraft 서버",
     config.PRINTCRAFT_BASE + (" 응답" if reachable(config.PRINTCRAFT_BASE) else " 미응답(전단 재사용은 무관)"))

# 5) 외부 연동
print("\n[5] 외부 연동")
loan_ok = reachable(config.LOAN_API_BASE)
line(OK if loan_ok else WARN, "대출앱(접수 종착)", config.LOAN_API_BASE + (" 응답" if loan_ok else " 미응답 → 접수 등록 불가(대출앱 uvicorn 구동 필요)"))
results["접수"] = loan_ok

# 광고 CTA에 실리는 접수폼 주소 — 로컬이면 소비자가 열 수 없다
_local = any(h in config.PUBLIC_BASE for h in ("127.0.0.1", "localhost"))
line(WARN if _local else OK, "접수폼 공개주소(PUBLIC_BASE)",
     config.PUBLIC_BASE + (" — 로컬 주소! 실발행 시 소비자가 못 엶(터널/호스팅 필요)" if _local else ""))
results["접수링크"] = not _local

# 6) DB · 채널
print("\n[6] DB · 채널")
try:
    import db
    db.init_db()
    chans = db.list_channels()
    enabled = [c for c in chans if c.get("enabled")]
    by_plat = {}
    for c in enabled:
        by_plat[c["platform"]] = by_plat.get(c["platform"], 0) + 1
    line(OK if enabled else WARN, "활성 채널",
         (", ".join(f"{k}:{v}" for k, v in by_plat.items()) if enabled else "0개 → register_channels 로 등록 필요"))

    # 켜져 있는 채널이 실제로 존재하는 곳인가.
    # 데모만 켜둔 채로 '준비됨' 이라고 하면, 스위치를 켜도 광고가 한 건도 안 나간다.
    demos = [c for c in enabled if db.is_demo_channel(c)]
    real = [c for c in enabled if not db.is_demo_channel(c)]
    if demos:
        line(NO, "데모 채널 활성", f"{len(demos)}개 — " +
             ", ".join(f"#{c['id']} {c['name']}" for c in demos[:3]) +
             "  → 실제 채널을 등록하고 데모는 끄세요")
    line(OK if real else NO, "실제 발행 대상", f"{len(real)}개")
    results["실채널"] = bool(real)
except Exception as e:
    line(NO, "DB", f"오류: {e}")
    results["실채널"] = False

# 7) 로그인 세션 (밴드·페북 실발행의 전제)
#    ⚠ '쿠키 파일이 아무거나 있다'로 판정하면 안 된다. 발행 때 실제로 열리는 파일은
#      계정 이름으로 정해지므로, 다른 계정 쿠키가 있어도 발행은 전건 실패한다.
print("\n[7] 로그인 세션 (실제 발행 계정 기준)")
import time as _time

def _session_check(platform: str, label: str, account: str):
    if not account:
        line(NO, f"{label} 계정", f"미설정 → .env 에 {platform.upper()}_ACCOUNT= 를 넣으세요"
                                  " (login.py --account 에 쓴 값과 동일하게)")
        return False
    p = config.cookie_path(platform, account)
    if p is None or not p.exists():
        line(NO, f"{label} 세션", f"{account} → 파일 없음 ({p.name if p else '?'}) · "
                                  f"python login.py {platform} --account {account}")
        return False
    age_d = (_time.time() - p.stat().st_mtime) / 86400
    fresh = age_d <= 14
    line(OK if fresh else WARN, f"{label} 세션",
         f"{account} · {age_d:.0f}일 전" + ("" if fresh else " — 만료 가능성 높음"))
    return fresh

try:
    band_sess = _session_check("band", "밴드", config.BAND_ACCOUNT)
    fb_sess = _session_check("facebook", "페북", config.FACEBOOK_ACCOUNT)
    results["밴드세션"], results["페북세션"] = band_sess, fb_sess
    # 참고용: 실제로 저장돼 있는 쿠키들(계정 이름이 어긋나면 여기서 눈치챌 수 있다)
    cdir = Path(config.FB_PROJECT_APP_DIR).parent / "data" / "cookies"
    have = sorted(f.stem for f in cdir.glob("*.json")) if cdir.exists() else []
    line(OK if have else WARN, "보유 세션 파일", ", ".join(have) if have else "없음")
except Exception as e:
    line(NO, "저장된 세션", f"확인 실패: {e}")
    results["밴드세션"] = results["페북세션"] = False

# ── 능력별 준비 요약 ──
print("\n" + "=" * 60)
print(" 능력별 준비 상태")
print("=" * 60)
# 밴드·페북은 엔진만 있어서는 못 나간다. 로그인 세션이 살아 있어야 실제로 발행된다.
cap = {
    "카피 생성": results.get("카피"),
    "팜플렛 생성": results.get("팜플렛"),
    "밴드 발행": results.get("밴드") and results.get("밴드세션"),
    "페북 발행": results.get("페북") and results.get("페북세션"),
    "카카오 발행": results.get("카카오"),
    "접수→대출": results.get("접수"),
    "접수 링크 공개": results.get("접수링크"),
    "실제 발행 대상 채널": results.get("실채널"),
}
for name, ready in cap.items():
    line(OK if ready else WARN, name, "" if ready else "준비 필요(위 항목 참조)")

blockers = [k for k, v in cap.items() if not v]
print("\n" + "-" * 60)
if not blockers:
    print(" 판정: 모든 능력 준비됨. GLOBAL_DRY_RUN=0 + 로그인 후 실가동 가능.")
else:
    print(f" 판정: 아래 능력에 준비 필요 → {', '.join(blockers)}")
    print(f"  · 카피: {config.COPY_PROVIDER} 키(무료티어 가능)  · 접수: 대출앱 uvicorn 구동")
    print("  · 접수 링크 공개: PUBLIC_BASE 를 외부 주소로(터널/호스팅)")
    print("  · 밴드/페북: python login.py band --account <계정> 으로 세션 갱신")
    print("  · 실제 발행 대상 채널: register_channels.py 로 진짜 밴드/그룹/방 등록 후 데모 끄기")
    print("  · 카카오: AHK + 데스크톱 카톡 실행")
print(" ⚠️  실발행은 GLOBAL_DRY_RUN=0 + 로그인 필요. 첫 발행은 반드시 버너/테스트 채널로.")
print("-" * 60)
