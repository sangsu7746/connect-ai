"""
이미 발행된 네이버 블로그 글을 쿠팡 파트너스 승인 기준에 맞게 고친다.

고치는 것 두 가지 (딥링크는 이 3건에 이미 들어 있다):
  1. 제목 앞에 [광고]
  2. 대가성 고지를 본문 **맨 앞** 문단으로 (지금은 본문 3만 자 뒤에 있다)

방식: SmartEditor 를 직접 조작한다. 관찰 결과 이 URL 에는 iframe 이 없어서
최상위에서 .se-title-text / .se-text-paragraph 에 접근할 수 있다.
  수정 URL: PostWriteForm.naver?blogId=..&logNo=..&redirect=Update
  발행 버튼: button.publish_btn__*

주의: 제목·본문에 '타이핑'으로 넣는다. JS 로 innerText 를 바꾸면 에디터 내부 모델이
갱신되지 않아 저장 시 원래 내용으로 되돌아간다(SmartEditor 는 DOM 이 아니라 자체 모델을 쓴다).
"""
import io
import json
import re
import sys
import time
import urllib.request

sys.path.insert(0, r"D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

from naver_poster import NaverBlogPoster
import coupang_blog_pipeline as P
import guardrails as G

CFG = r"D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807\config.json"
cfg = json.load(io.open(CFG, encoding="utf-8"))
BID = cfg["naver_id"]
DISCLOSURE = P.PARTNERS_DISCLOSURE
EDIT_URL = ("https://blog.naver.com/PostWriteForm.naver"
            "?blogId={bid}&logNo={log}&redirect=Update&widgetTypeCall=true")

#: 이 글들만 건드린다. 부동산 글 등 다른 글을 잘못 고치면 안 된다.
KEYWORDS = ("면봉", "아메리카노", "드라이버")

HDR = {"User-Agent": "Mozilla/5.0 (compatible; KakaoTalk-Scrap/1.0)"}


def public_state(log_no: str) -> dict:
    """공개 페이지에서 현재 상태를 읽는다. 저장했다는 말이 아니라 결과를 본다."""
    url = f"https://blog.naver.com/PostView.naver?blogId={BID}&logNo={log_no}"
    try:
        h = urllib.request.urlopen(
            urllib.request.Request(url, headers=HDR), timeout=20).read().decode("utf-8", "ignore")
    except Exception as e:
        return {"error": str(e)[:50]}
    t = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)', h)
    title = t.group(1) if t else ""
    # 본문 영역만 본다 — 블로그 스킨의 헤더·사이드바를 고지 앞 요소로 오인하면 안 된다
    m = re.search(r'<div[^>]*class="[^"]*se-main-container[^"]*"[^>]*>(.*)', h, re.S)
    art = m.group(1)[:40000] if m else h
    plain = re.sub(r"<[^>]+>", " ", art)
    return {
        "title": title,
        "problems": G.check_disclosure(plain, title),
        "deeplink": "link.coupang.com" in h,
    }


def edit_one(p: NaverBlogPoster, log_no: str) -> dict:
    d = p.driver
    d.get(EDIT_URL.format(bid=BID, log=log_no))
    time.sleep(7)
    d.switch_to.default_content()

    # 도움말·이어쓰기 팝업 정리
    try:
        d.execute_script(
            "document.querySelectorAll('.se-popup-button-cancel,"
            " .se-help-popup-close-button, .btn_close').forEach(el => el.click());")
    except Exception:
        pass
    time.sleep(1.2)

    cur = d.execute_script("""
        const t = document.querySelector('.se-title-text');
        const paras = [...document.querySelectorAll('.se-text-paragraph')];
        return {
          title: t ? (t.innerText||'').trim() : null,
          firstPara: paras.length > 1 ? (paras[1].innerText||'').trim().slice(0,60) : null,
          paraCount: paras.length
        };""")
    if not cur or not cur["title"]:
        return {"ok": False, "why": "제목 요소를 찾지 못했습니다"}

    p.log(f"  현재 제목: {cur['title'][:50]}")
    p.log(f"  본문 문단: {cur['paraCount']}개")

    # 제목이 '[광고]로 시작' 하지 않으면 고쳐야 한다.
    # 중간에 [광고] 가 박힌 경우도 여기 걸린다(커서가 중앙에 놓여 실제로 그렇게 됐다).
    need_title = not cur["title"].startswith("[광고]")
    need_disc = DISCLOSURE not in (cur["firstPara"] or "")

    if not need_title and not need_disc:
        return {"ok": True, "note": "이미 기준을 만족합니다 — 저장하지 않았습니다"}

    # ── 제목을 통째로 다시 쓴다 ──
    # 커서를 '맨 앞'으로 보내는 방법이 통하지 않았다.
    #   element.click() 은 요소 '중앙'을 클릭하고, SmartEditor 제목에서는 Home 이 안 먹는다.
    #   그래서 "…3,390[광고]원" 처럼 제목 한가운데에 박혔다.
    # 선택 영역을 JS Range 로 잡아 전체를 선택한 뒤, 실제 타이핑으로 덮어쓴다.
    # (JS 로 innerText 를 직접 바꾸면 에디터 모델이 갱신되지 않아 저장 시 되돌아간다.
    #  선택만 JS 로 잡고 입력은 키보드로 하는 것이 요점이다)
    if need_title:
        clean = re.sub(r"\[\s*(광고|AD)\s*\]", "", cur["title"]).strip()
        new_title = f"[광고]{clean}"
        el = d.find_element(By.CSS_SELECTOR, ".se-title-text")
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.5)
        el.click()
        time.sleep(0.8)

        # JS Range 로 선택을 잡아 봤지만 첫 키 입력에서 풀려 뒤에 덧붙었다.
        # 키보드 Ctrl+A 로 잡되, **무엇이 선택됐는지 먼저 읽어 본다.**
        # 본문까지 선택된 상태에서 타이핑하면 글 전체가 날아간다 — 확인 없이는 절대 치지 않는다.
        # 여기까지 실패한 방법들(같은 실수를 반복하지 않도록 남긴다):
        #   click + Home        → Home 무반응, click 은 요소 '중앙'을 눌러 제목 한가운데 삽입
        #   JS Range 전체 선택   → 첫 키 입력에서 선택이 풀려 뒤에 덧붙음
        #   el.send_keys        → element not interactable (input 이 아니라 contenteditable)
        #   ActionChains Ctrl+A → 0자 선택. SmartEditor 가 가로채는 것으로 보인다
        #
        # execCommand 는 beforeinput/input 이벤트를 정상적으로 발생시켜
        # contenteditable 에디터의 내부 모델까지 갱신한다. 캐럿도 Range 로 직접 놓는다.
        res = d.execute_script("""
            const want = arguments[0];
            const t = document.querySelector('.se-title-text');
            if (!t) return {ok:false, why:'제목 요소 없음'};
            t.focus();
            const sel = window.getSelection();

            // 1) 기존에 잘못 박힌 [광고] 를 모두 지운다
            for (let guard = 0; guard < 5; guard++) {
              const walker = document.createTreeWalker(t, NodeFilter.SHOW_TEXT);
              let hit = null;
              while (walker.nextNode()) {
                const i = walker.currentNode.data.indexOf('[광고]');
                if (i >= 0) { hit = {node: walker.currentNode, i}; break; }
              }
              if (!hit) break;
              const r = document.createRange();
              r.setStart(hit.node, hit.i);
              r.setEnd(hit.node, hit.i + 4);
              sel.removeAllRanges(); sel.addRange(r);
              document.execCommand('delete');
            }

            // 2) 맨 앞에 캐럿을 놓고 [광고] 를 넣는다
            const first = document.createTreeWalker(t, NodeFilter.SHOW_TEXT).nextNode() || t;
            const r2 = document.createRange();
            r2.setStart(first, 0);
            r2.collapse(true);
            sel.removeAllRanges(); sel.addRange(r2);
            const okIns = document.execCommand('insertText', false, '[광고]');

            return {ok: okIns, title: (t.innerText||'').trim()};
        """, new_title)
        time.sleep(1.2)
        if not res.get("ok"):
            return {"ok": False, "why": f"제목 삽입 실패: {res.get('why') or 'execCommand 거부'}"}
        after = d.execute_script(
            "const t=document.querySelector('.se-title-text');return t?(t.innerText||'').trim():'';")
        p.log(f"  제목 재입력: {after[:52]}")
        if not after.startswith("[광고]"):
            return {"ok": False, "why": f"제목이 의도대로 안 됨: {after[:60]} — 저장하지 않았습니다"}

    # ── 본문 맨 앞에 고지 문단 ──
    if need_disc:
        paras = d.find_elements(By.CSS_SELECTOR, ".se-text-paragraph")
        # paras[0] 은 제목 영역이다. 본문 첫 문단은 paras[1].
        target = paras[1] if len(paras) > 1 else paras[0]
        d.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
        time.sleep(0.5)
        target.click()
        time.sleep(0.8)
        # Ctrl+Home 을 쓰면 '문서 맨 앞' = 제목으로 튈 수 있다. 고지가 제목에 박히면 낭패다.
        # 클릭한 문단의 줄 맨 앞으로만 이동한다.
        ActionChains(d).send_keys(Keys.HOME).perform()
        time.sleep(0.6)
        # 고지를 치고 Enter — 문단이 갈라져 고지가 1번, 원래 글이 2번이 된다
        p._human_type(DISCLOSURE)
        time.sleep(0.6)
        ActionChains(d).send_keys(Keys.ENTER).perform()
        time.sleep(1.2)
        p.log("  본문 맨 앞에 대가성 고지 삽입")

    # ── 발행 ──
    p.log("  발행 버튼 클릭...")
    try:
        btns = d.find_elements(
            By.XPATH, "//button[contains(.,'발행')] | //a[contains(.,'발행')]")
        for b in btns:
            if b.is_displayed():
                d.execute_script("arguments[0].click();", b)
                break
        time.sleep(3.5)
        # 발행 패널의 최종 버튼
        confirm = d.find_elements(
            By.XPATH, "//*[contains(@class,'btn_confirm')] | //button[contains(.,'발행')]")
        for b in reversed(confirm):
            if b.is_displayed():
                d.execute_script("arguments[0].click();", b)
                break
        time.sleep(6)
    except Exception as e:
        return {"ok": False, "why": f"발행 실패: {str(e)[:70]}"}

    left = "PostWriteForm" not in d.current_url
    return {"ok": left, "note": "저장 완료" if left else "편집기에 남아 있음 — 확인 필요"}


def main() -> int:
    only = [a for a in sys.argv[1:] if a.isdigit() and len(a) > 8]

    p = NaverBlogPoster(headless=False)
    if not p.login(cfg["naver_id"], cfg["naver_pw"]):
        print("네이버 로그인 실패")
        return 1
    d = p.driver
    try:
        # 대상 글 찾기
        d.get(f"https://blog.naver.com/PostList.naver?blogId={BID}")
        time.sleep(4)
        ids = []
        for fr in [None] + d.find_elements(By.TAG_NAME, "iframe"):
            try:
                d.switch_to.default_content()
                if fr is not None:
                    d.switch_to.frame(fr)
                for x in re.findall(r"logNo=(\d{10,})", d.page_source):
                    if x not in ids:
                        ids.append(x)
            except Exception:
                continue
        d.switch_to.default_content()

        targets = []
        for ln in (only or ids):
            st = public_state(ln)
            if st.get("error"):
                continue
            if not any(k in st["title"] for k in KEYWORDS):
                continue          # 쿠팡 글이 아니면 건드리지 않는다
            targets.append((ln, st))

        print("=" * 66)
        print(f"  대상 {len(targets)}건")
        for ln, st in targets:
            print(f"   {ln}  {st['title'][:44]}")
            for x in st["problems"]:
                print(f"      ⛔ {x}")
        print("=" * 66)

        for ln, _ in targets:
            print(f"\n[{ln}]")
            try:
                r = edit_one(p, ln)
            except Exception as e:
                r = {"ok": False, "why": str(e)[:100]}
            print(f"  {'✅ ' + r.get('note', '') if r.get('ok') else '❌ ' + str(r.get('why'))}")
            time.sleep(2)
    finally:
        p.close()

    print("\n" + "=" * 66)
    print("  공개 페이지 재확인")
    for ln, _ in targets:
        st = public_state(ln)
        print(f"\n  {ln}  {st.get('title','')[:46]}")
        print(f"     파트너스 기준: {'통과 ✅' if not st.get('problems') else '위반'}")
        for x in st.get("problems", []):
            print(f"       ⛔ {x}")
        print(f"     딥링크: {'있음' if st.get('deeplink') else '없음 ⛔'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
