# -*- coding: utf-8 -*-
"""네이버 블로그 글 하나를 삭제한다.

발행기에는 삭제 기능이 없어 새로 만들었다. 로그인은 기존 흐름(저장된 쿠키)을 그대로 쓴다.

되돌릴 수 없는 동작이라 안전장치를 둔다:
  · logNo 를 인자로 명시해야 한다 (기본값 없음)
  · 지우기 전에 그 글의 제목을 읽어 보여주고, --yes 가 있어야 실제로 지운다
"""
import argparse
import json
import sys
import time

BASE = r"D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807"
sys.path.insert(0, BASE)
from naver_poster import NaverBlogPoster  # noqa: E402
from selenium.webdriver.common.by import By  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--logno", required=True, help="지울 글 번호")
    ap.add_argument("--blogid", required=True)
    ap.add_argument("--yes", action="store_true", help="실제로 삭제 (없으면 확인만)")
    a = ap.parse_args()

    out = {"logNo": a.logno, "deleted": False}
    p = NaverBlogPoster()
    try:
        p._init_driver()
        if not p._load_cookies_and_check():
            print(json.dumps({**out, "error": "쿠키 로그인 실패"}, ensure_ascii=False))
            return

        # 관리 화면에서 해당 글을 찾는다
        p.driver.get(f"https://blog.naver.com/PostView.naver?blogId={a.blogid}&logNo={a.logno}")
        time.sleep(3)
        out["title"] = (p.driver.title or "").split(" : ")[0].strip()
        if not a.yes:
            print(json.dumps({**out, "note": "확인만 함 — 지우려면 --yes"}, ensure_ascii=False))
            return

        # 글 관리 목록으로 가서 체크 후 삭제
        p.driver.get(f"https://blog.naver.com/PostThumbnailAlbumView.naver?blogId={a.blogid}")
        time.sleep(2)
        p.driver.get(f"https://admin.blog.naver.com/{a.blogid}/postmanage")
        time.sleep(4)
        for fr in p.driver.find_elements(By.TAG_NAME, "iframe"):
            try:
                p.driver.switch_to.frame(fr)
                if p.driver.find_elements(By.XPATH, f"//input[@value='{a.logno}']"):
                    break
                p.driver.switch_to.default_content()
            except Exception:
                p.driver.switch_to.default_content()

        boxes = p.driver.find_elements(By.XPATH, f"//input[@value='{a.logno}']")
        if not boxes:
            print(json.dumps({**out, "error": "글 관리 목록에서 해당 글을 찾지 못했습니다"},
                             ensure_ascii=False))
            return
        p.driver.execute_script("arguments[0].click();", boxes[0])
        time.sleep(1)

        btn = None
        for xp in ["//a[contains(.,'삭제')]", "//button[contains(.,'삭제')]",
                   "//*[@class='btn_delete']"]:
            for e in p.driver.find_elements(By.XPATH, xp):
                if e.is_displayed():
                    btn = e
                    break
            if btn:
                break
        if not btn:
            print(json.dumps({**out, "error": "삭제 버튼을 찾지 못했습니다"}, ensure_ascii=False))
            return
        p.driver.execute_script("arguments[0].click();", btn)
        time.sleep(2)
        try:
            p.driver.switch_to.alert.accept()
        except Exception:
            pass
        time.sleep(3)
        out["deleted"] = True
        print(json.dumps(out, ensure_ascii=False))
    finally:
        try:
            p.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
