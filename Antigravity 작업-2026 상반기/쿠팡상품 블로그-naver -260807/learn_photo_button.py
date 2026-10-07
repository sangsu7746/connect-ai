"""
learn_photo_button.py
────────────────────────────────────────────────────────────────────────────
네이버 블로그 글쓰기 에디터에서 사진 추가 버튼의 정확한 경로를 학습합니다.

사용법:
    python learn_photo_button.py

실행 흐름:
    1. 네이버 로그인 (쿠키 세션 또는 아이디/비밀번호)
    2. 블로그 글쓰기 페이지 오픈
    3. 화면에 '지금 사진 추가 버튼을 직접 눌러주세요' 안내 표시
    4. 사용자가 툴바에서 사진 버튼을 클릭
    5. 시스템이 클릭된 버튼 정보(XPath, class, title 등) 자동 캡처
    6. naver_selectors.json 에 저장
    7. 이후 포스터가 저장된 경로를 최우선으로 사용
────────────────────────────────────────────────────────────────────────────
"""
import os
import sys
import json
import time

# Windows CP949 환경에서 이모지 출력 오류 방지
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ── JS: 버튼 클릭 이벤트 캡처 스크립트 ────────────────────────────────────
_CAPTURE_JS = """
(function() {
    if (window.__photoCapturing) return;
    window.__photoCapturing = true;
    window.__photoBtnInfo = null;

    function getXPath(el) {
        if (!el) return '';
        if (el.id) return '//*[@id="' + el.id + '"]';
        var parts = [];
        while (el && el.nodeType === 1) {
            var idx = 1;
            var sib = el.previousSibling;
            while (sib) {
                if (sib.nodeType === 1 && sib.nodeName === el.nodeName) idx++;
                sib = sib.previousSibling;
            }
            parts.unshift(el.nodeName.toLowerCase() + '[' + idx + ']');
            el = el.parentNode;
        }
        return '/' + parts.join('/');
    }

    // 모든 클릭 이벤트를 캡처 (캡처 단계)
    document.addEventListener('click', function(e) {
        var el = e.target;
        // 버튼 요소까지 올라가며 탐색
        for (var i = 0; i < 5 && el && el.tagName !== 'BODY'; i++) {
            if (el.tagName === 'BUTTON' || el.getAttribute('role') === 'button') {
                window.__photoBtnInfo = {
                    tagName:    el.tagName.toLowerCase(),
                    id:         el.id || '',
                    title:      el.getAttribute('title') || '',
                    ariaLabel:  el.getAttribute('aria-label') || '',
                    className:  el.className || '',
                    dataName:   el.getAttribute('data-name') || '',
                    textContent: el.textContent.trim().substring(0, 30),
                    xpath:      getXPath(el)
                };
                console.log('[학습] 버튼 캡처됨:', JSON.stringify(window.__photoBtnInfo));
                break;
            }
            el = el.parentElement;
        }
    }, true);
})();
"""

_SELECTOR_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "naver_selectors.json"
)


def load_selectors() -> dict:
    """저장된 선택자 파일 로드."""
    if os.path.exists(_SELECTOR_FILE):
        try:
            with open(_SELECTOR_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_selectors(data: dict) -> None:
    """선택자 파일 저장."""
    abs_path = os.path.abspath(_SELECTOR_FILE)
    with open(abs_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[저장 완료] {abs_path}")
    print(f"[파일 크기] {os.path.getsize(abs_path)} bytes")


def run_learning():
    """사진 버튼 학습 실행."""
    try:
        import config as cfg
        from naver_poster import NaverBlogPoster
    except ImportError as e:
        print(f"❌ 임포트 실패: {e}")
        return

    conf = cfg.load_config()
    naver_id = conf.get("naver_id", "")
    naver_pw = conf.get("naver_pw", "")

    if not naver_id or not naver_pw:
        print("❌ config에 naver_id / naver_pw 가 설정되어 있지 않습니다.")
        return

    print("=" * 60)
    print("📚 네이버 사진 버튼 경로 학습 모드")
    print("=" * 60)

    poster = NaverBlogPoster(headless=False, log_callback=print)

    try:
        # 로그인
        if not poster.login(naver_id, naver_pw):
            print("❌ 로그인 실패.")
            return

        # 글쓰기 페이지 이동
        print("\n📝 글쓰기 페이지로 이동 중...")
        write_url = f"https://blog.naver.com/PostWriteForm.naver?blogId={naver_id}"
        poster.driver.get(write_url)
        time.sleep(3)

        # iframe 진입 시도
        try:
            from selenium.webdriver.common.by import By
            frame = poster.driver.find_element(By.ID, "mainFrame")
            poster.driver.switch_to.frame(frame)
            print("  → mainFrame 진입")
        except Exception:
            pass

        time.sleep(2)

        # JS 캡처 스크립트 주입 (default_content + iframe 모두)
        poster.driver.switch_to.default_content()
        poster.driver.execute_script(_CAPTURE_JS)
        try:
            frame = poster.driver.find_element(By.ID, "mainFrame")
            poster.driver.switch_to.frame(frame)
            poster.driver.execute_script(_CAPTURE_JS)
            print("  → mainFrame + default 양쪽에 캡처 스크립트 주입 완료")
        except Exception:
            print("  → default_content 에만 캡처 스크립트 주입")
        poster.driver.switch_to.default_content()

        print("\n" + "=" * 60)
        print("지금 네이버 에디터 툴바에서 [사진 추가] 버튼을 직접 눌러주세요!")
        print("(카메라 아이콘 또는 '사진' 텍스트가 있는 버튼)")
        print("=" * 60)

        # 사용자 클릭 대기 (최대 90초, default + iframe 양쪽 폴링)
        btn_info = None
        for i in range(90):
            time.sleep(1)
            try:
                # default_content 에서 먼저 확인
                poster.driver.switch_to.default_content()
                result = poster.driver.execute_script("return window.__photoBtnInfo;")
                if not result:
                    # iframe 안도 확인
                    try:
                        frame = poster.driver.find_element(By.ID, "mainFrame")
                        poster.driver.switch_to.frame(frame)
                        result = poster.driver.execute_script("return window.__photoBtnInfo;")
                        poster.driver.switch_to.default_content()
                    except Exception:
                        pass
                if result:
                    btn_info = result
                    break
            except Exception:
                pass
            print(f"  대기 중... ({i+1}/90초)", end="\r")

        if not btn_info:
            print("\n⚠️ 60초 내에 버튼이 감지되지 않았습니다.")
            return

        print(f"\n✅ 버튼 캡처 성공!")
        print(f"   title      : {btn_info.get('title', '없음')}")
        print(f"   ariaLabel  : {btn_info.get('ariaLabel', '없음')}")
        print(f"   className  : {btn_info.get('className', '없음')[:60]}")
        print(f"   dataName   : {btn_info.get('dataName', '없음')}")
        print(f"   textContent: {btn_info.get('textContent', '없음')}")
        print(f"   xpath      : {btn_info.get('xpath', '없음')}")

        # XPath 후보 생성 (가장 안정적인 것부터)
        xpath_candidates = []
        if btn_info.get("title"):
            xpath_candidates.append(
                f"//button[@title='{btn_info['title']}']"
            )
        if btn_info.get("ariaLabel"):
            xpath_candidates.append(
                f"//button[@aria-label='{btn_info['ariaLabel']}']"
            )
        if btn_info.get("dataName"):
            xpath_candidates.append(
                f"//button[@data-name='{btn_info['dataName']}']"
            )
        # className의 첫 번째 고유 클래스 추출
        classes = [c for c in btn_info.get("className", "").split()
                   if len(c) > 5 and "se-" in c]
        if classes:
            xpath_candidates.append(
                f"//button[contains(@class,'{classes[0]}')]"
            )
        # 절대 XPath는 마지막 폴백으로
        if btn_info.get("xpath"):
            xpath_candidates.append(btn_info["xpath"])

        # 저장
        from datetime import datetime
        selectors = load_selectors()
        selectors["photo_button"] = {
            "raw_info": btn_info,
            "xpath_candidates": xpath_candidates,
            "learned_at": datetime.now().isoformat()
        }
        save_selectors(selectors)

        print("\n📋 저장된 XPath 후보 (우선순위 순):")
        for i, xp in enumerate(xpath_candidates, 1):
            print(f"  {i}. {xp}")

        print("\n🎉 학습 완료! 다음 포스팅부터 이 경로를 자동으로 사용합니다.")

    finally:
        input("\n엔터를 누르면 브라우저를 닫습니다...")
        poster.close()


if __name__ == "__main__":
    run_learning()
