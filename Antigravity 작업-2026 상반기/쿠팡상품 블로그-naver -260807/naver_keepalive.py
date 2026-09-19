# -*- coding: utf-8 -*-
"""네이버 블로그 세션을 살려 두고, 죽었는지 알려 준다.

왜 필요한가 — 세션이 끊기면 무인 발행이 그날부터 조용히 실패한다.
쿠키는 쓸 때마다 갱신되므로 가끔 글쓰기 화면에 들르는 것만으로 만료를 미룰 수 있다.
비밀번호는 다루지 않는다. 끊겼으면 사람이 직접 로그인해야 한다고 알릴 뿐이다.

블로그별 프로필 규칙:
  .naver_profile_<blogId>  가 있으면 그것을 쓴다 (블로그마다 다른 네이버 계정일 때)
  없으면 .naver_profile    을 쓴다 (지금처럼 계정이 하나일 때)

사용:
  python naver_keepalive.py                 config.json 의 naver_id 하나만
  python naver_keepalive.py apahand headjim ctm10000
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
WRITE_URL = "https://blog.naver.com/{blog_id}/postwrite"


def profile_dir(blog_id: str) -> str:
    special = os.path.join(BASE, f".naver_profile_{blog_id}")
    return special if os.path.isdir(special) else os.path.join(BASE, ".naver_profile")


def default_blogs() -> list:
    try:
        with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
            bid = (json.load(f) or {}).get("naver_id", "")
        return [bid] if bid else []
    except Exception:
        return []


def check_one(pw, blog_id: str) -> dict:
    """글쓰기 화면에 도달하는지 본다. 도달하면 그 방문 자체가 쿠키를 갱신한다."""
    out = {"blog": blog_id, "profile": os.path.basename(profile_dir(blog_id)), "ok": False}
    ctx = None
    try:
        ctx = pw.chromium.launch_persistent_context(profile_dir(blog_id), headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(WRITE_URL.format(blog_id=blog_id), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        # 편집기가 떴는지'만' 보면 안 된다. 네이버는 권한 없는 블로그의 글쓰기 주소로 가면
        # 조용히 내 블로그로 되돌린다 — 그러면 편집기는 떠 있는데 대상이 다르다.
        # 실측(2026-08-27): headjim/postwrite 요청이 apahand 로 돌아왔다.
        target = page.url
        for fr in page.frames:
            if "postwrite" in (fr.url or ""):
                target = fr.url
                break
        out["finalUrl"] = target
        on_write = "postwrite" in target
        right_blog = f"/{blog_id}/" in target or f"blogId={blog_id}" in target
        out["ok"] = bool(on_write and right_blog)
        if not on_write:
            out["why"] = "로그인이 필요합니다"
        elif not right_blog:
            out["why"] = f"다른 블로그로 연결됩니다 — {blog_id} 계정으로 따로 로그인해야 합니다"
        else:
            out["why"] = "정상"
    except Exception as e:
        out["why"] = f"확인 실패: {str(e)[:100]}"
    finally:
        if ctx:
            try:
                ctx.close()
            except Exception:
                pass
    return out


def main():
    blogs = sys.argv[1:] or default_blogs()
    if not blogs:
        print(json.dumps({"error": "확인할 블로그가 없습니다"}, ensure_ascii=False))
        return

    from playwright.sync_api import sync_playwright

    results = []
    with sync_playwright() as pw:
        for b in blogs:
            results.append(check_one(pw, b))

    dead = [r for r in results if not r["ok"]]
    if dead:
        try:
            import notify
            lines = "\n".join(f"· {r['blog']}: {r.get('why', '')}" for r in dead)
            notify.send(f"⚠️ 네이버 블로그 로그인이 필요합니다\n{lines}")
        except Exception:
            pass

    print(json.dumps({"results": results, "allOk": not dead}, ensure_ascii=False))


if __name__ == "__main__":
    main()
