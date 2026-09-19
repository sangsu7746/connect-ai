# ============================================================
#  preflight.py — 실가동 준비 상태 점검 (읽기 전용, 발행/로그인 안 함)
#  실행: python preflight.py
#  능력별로 무엇이 준비됐고 무엇이 막혔는지 진단.
#
#  ⚠ 이 파일은 전체가 "읽기 전용"이라는 계약을 진다 — 브라우저를 띄우지
#    않고, 세션을 시작하지 않는다(단, 기존 섹션 일부는 PrintCraft/대출앱
#    HTTP 헬스체크로 네트워크를 짧게 두드린다 — 이건 이 태스크 이전부터
#    있던 동작이라 범위 밖으로 두고 손대지 않는다).
#  ⚠ import 자체도 부작용이 없어야 한다 — 그래야 테스트가
#    `import preflight` 만으로 `check_threads()` 를 안전하게 불러 쓸 수
#    있다. 예전엔 이 파일 전체가 모듈 최상위에서 바로 실행돼(stdout을
#    UTF-8 TextIOWrapper 로 바꿔치기하는 것까지 포함) `import preflight`
#    가 pytest 의 stdout 캡처를 깨뜨렸다(실측: capture teardown 단계에서
#    `ValueError: I/O operation on closed file`, 테스트가 0개 수집됨) —
#    그래서 전체 점검 로직을 main() 으로 감싸고 `if __name__=="__main__"`
#    가드를 추가했다. 이 리팩터를 빼면 이번 태스크의 브리프가 지정한
#    테스트 파일(`import config; import preflight`) 자체가 못 돈다.
# ============================================================
import sys
import io
import importlib
from pathlib import Path

import config

OK, WARN, NO = "✅", "⚠️ ", "❌"


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


def check_threads() -> dict:
    """쓰레드 답글 발행 준비 상태. 읽기 전용(브라우저 안 띄움, 네트워크도 안 만짐).

    ⚠ 이 함수만은 위 모듈 docstring 의 예외(HTTP 헬스체크)도 적용받지
    않는다 — 계정·쿠키·프로필·랜딩·스위치·상한, 전부 로컬 상태만 본다.
    쿠키는 '세션을 열어 유효한지'가 아니라 '파일이 디스크에 있는지'만
    확인한다(설계 원칙 1 — preflight 는 읽기 전용)."""
    import config
    items = []

    acc = config.THREADS_ACCOUNT
    items.append(("쓰레드 계정", bool(acc),
                  acc or ".env 의 THREADS_ACCOUNT 미설정"))

    cookie = config.cookie_path("threads", acc) if acc else None
    has_cookie = bool(cookie and cookie.exists())
    items.append(("세션 쿠키", has_cookie,
                  str(cookie) if has_cookie else "python login.py threads 로 생성"))

    # ⚠ 활성 프로필(AUTOAD_PROFILE)이 아니라 쓰레드 전용 프로필을 본다.
    #   서버는 대출 업종으로 떠 있어도 쓰레드는 THREADS_PROFILE 로 돈다.
    #   실측(2026-08-04): 이걸 config.PROFILE 로 보다가 mirizip 에 threads:
    #   섹션이 멀쩡히 있는데도 "loan.yaml 에 추가 필요" 로 잘못 떴다.
    try:
        tprof = config.threads_profile()
    except Exception as e:
        tprof = {}
        items.append(("프로필 로드", False, f"{type(e).__name__}: {e}"))
    tkey = tprof.get("key") or config.PROFILE_KEY

    prof_ok = bool((tprof.get("threads") or {}).get("interest_keywords"))
    items.append(("프로필 threads 섹션", prof_ok,
                  (f"{tkey}"
                   + (f" (활성 프로필은 {config.PROFILE_KEY})"
                      if tkey != config.PROFILE_KEY else ""))
                  if prof_ok else f"profiles/{tkey}.yaml 에 threads: 추가 필요"))

    landing = (tprof.get("threads") or {}).get("landing") or config.BRAND_SITE
    items.append(("랜딩 주소", bool(landing), landing or "미설정 - 답글에 링크가 안 붙는다"))

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


def _print_threads_section():
    """check_threads() 결과를 콘솔에 출력한다.

    ⚠ 이 함수는 위 OK/WARN/NO(✅/⚠️ /❌) 를 일부러 안 쓴다 — 그 세
    글자는 이 파일이 cp949 제약 이전부터 쓰던 기존 코드고, 이번 태스크
    (Task 9) 지시는 "기존 위반은 범위 밖(손대지 않는다), 새로 추가하는
    코드에는 새 위반을 넣지 않는다"이다. 그래서 이 절만 [OK]/[NG]/[!]
    로 찍는다."""
    res = check_threads()
    print("\n[8] 쓰레드 답글 자동광고 (threads)")
    for name, ok, detail in res["items"]:
        mark = "[OK]" if ok else "[NG]"
        print(f"  {mark} {name}" + (f" - {detail}" if detail else ""))
    if not res["ok"]:
        print("  [!] 계정/쿠키/프로필/랜딩 중 [NG] 가 있으면 실발행 전 반드시 해소하세요.")


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    results = {}

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

    # 8) 쓰레드 답글 자동광고 (Task 9)
    _print_threads_section()

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


if __name__ == "__main__":
    main()
