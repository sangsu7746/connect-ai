"""블로그 리뉴얼 릴스 제작기용 범용 발행 CLI.
쿠팡 파이프라인(제휴·고지·위젯)을 태우지 않고 세션·에디터 자산만 재사용한다.
입력: --file handoff.json {platform, title, body_md, category}
출력: stdout 마지막 줄에 {"ok": bool, "url": str, "error": str}

주의: 티스토리는 비공개로 올라가지만 **네이버는 즉시 공개 발행**된다(naver_poster에 비공개 기능이 없음).
호출 측이 사용자에게 이 차이를 알려야 한다.

정독 결과(2026-08-16, tistory_poster.py 1070줄 / naver_poster.py 1725줄 전체 확인):

  · tistory_poster.text_to_html()/build_html() 은 affiliate_url 값과 무관하게
    "이 포스팅은 쿠팡 파트너스 활동의 일환으로..." 고지를 맨 위·맨 아래에 무조건
    삽입한다(affiliate_url="" 로 넘겨도 고지 자체는 안 사라진다 — 브리프가 적은
    "affiliate_url="" 이면 제휴 없음"이라는 가정과 실제 동작이 다르다). 그래서 이
    두 함수는 호출하지 않고, 헤딩(##)·목록(-)·문단만 살리는 자체 경량 마크다운→HTML
    변환기(_md_to_tistory_html)로 본문을 만들어 write_post(..., prebuilt_html=True)
    로 넘긴다. write_post() 는 ensure_login/_ctx/_page 를 전부 포함해 로그인부터
    발행까지 처리하는 최상위 함수라 그것 하나만 부르면 된다. 발행 URL은 반환
    dict 의 "url" 키(발행 후 page.url, `/manage/newpost` 를 벗어났는지로 성공 판정)
    로 온다. mode="private" 로 넘기면 라디오 #open0(비공개)을 선택해 발행한다.

  · naver_poster.NaverBlogPoster.write_post(title, content, _category, ...) 는
    성공 여부(bool)만 돌려주고 URL을 돌려주지 않는다(브리프는 "반환값"에서 URL을
    구할 수 있다고 가정했으나 실제로는 아니다). coupang_blog_pipeline.py 도 네이버
    발행 성공 시 record_published(product_id, "naver") 를 url 인자 없이 호출하는
    것으로 이미 그렇게 쓰고 있었다(정독으로 확인 — 이 프로젝트 자체가 원래도 네이버
    글 URL을 남기지 않는다). 그래서 발행 직후 페이지에 남은 blogId/logNo 를 긁어
    PostView 주소를 최선을 다해 구성한다(fix_published_naver.py 가 쓰는 것과 같은
    logNo 정규식) — 못 찾으면 url="" 로 둔다(그래도 ok=True 는 유지한다, 발행 자체는
    성공했으므로).
    로그인은 NaverBlogPoster._init_driver() + _load_cookies_and_check() 로 저장된
    쿠키(~/.naver_poster_cookies.pkl)만 재사용한다. login(id, pw) 은 쿠키가 없을 때
    아이디/비밀번호 입력·2차 인증 대기까지 들어가는 흐름이라 크리덴셜을 새로 다루게
    되므로 쓰지 않는다 — 쿠키가 없거나 만료됐으면 발행하지 않고 바로 실패로 보고한다.
    content 는 segments 없이 넘기면 write_post 가 사람처럼 한 글자씩 타이핑만 한다
    (HTML 해석이 없다) — 마크다운 기호를 그대로 두면 '##'·'**' 가 글자 그대로 찍히므로
    _md_to_naver_plain 으로 기호만 제거한 평문을 만들어 넘긴다.
"""
import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def _result(ok: bool, url: str = "", error: str = "") -> None:
    print(json.dumps({"ok": ok, "url": url, "error": error}, ensure_ascii=False))


def _md_to_tistory_html(md: str) -> str:
    """마크다운을 티스토리 에디터가 받는 간단한 HTML로 바꾼다.

    tistory_poster.text_to_html()/build_html() 은 affiliate_url 값과 무관하게
    쿠팡 파트너스 대가성 고지 문단을 무조건 넣는다(정독으로 확인) — 그래서
    재사용하지 않고 헤딩(##)·목록(-)·문단만 살리는 자체 변환을 쓴다.

    article_gen._paragraphs() 는 헤딩 단독 블록을 다음 문단에 단일 개행(\n)으로
    붙여서 저장한다 — 그래서 저장된 body_md 블록은 "## 제목\n본문…" 처럼 여러
    줄이다. 블록 단위(len(lines)==1)로만 헤딩을 판정하면 이 블록이 그냥 <p>로
    떨어진다 — 그래서 블록이 아니라 **줄 단위**로 판정한다.
    """
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    out = []
    para_buf = []
    list_buf = []

    def flush_para():
        if para_buf:
            out.append(f'<p data-ke-size="size16">{esc(" ".join(para_buf))}</p>')
            para_buf.clear()

    def flush_list():
        if list_buf:
            items = "".join(f"<li>{esc(b)}</li>" for b in list_buf)
            out.append(f'<ul data-ke-list-type="disc">{items}</ul>')
            list_buf.clear()

    for block in re.split(r"\n\s*\n", (md or "").strip()):
        b = block.strip()
        if not b:
            continue
        for raw in b.split("\n"):
            ln = raw.strip()
            if not ln:
                continue
            m_img = re.match(r"^\[\[IMG(\d+)\]\]$", ln)
            if m_img:
                # 업로드된 이미지 자리. tistory_poster._apply_uploaded 가
                # {{IMGn|폴백}} 을 실제 주소로 바꿔준다(폴백은 비워 둔다).
                flush_para()
                flush_list()
                out.append(
                    f'<p data-ke-size="size16"><img src="{{{{IMG{m_img.group(1)}|}}}}" '
                    f'style="max-width:100%;height:auto;"></p>'
                )
                continue
            if re.match(r"^#{1,3}\s+", ln):
                flush_para()
                flush_list()
                heading = re.sub(r"^#{1,3}\s+", "", ln)
                out.append(f'<h2 data-ke-size="size26">{esc(heading)}</h2>')
                continue
            if re.match(r"^[-*•]\s+", ln):
                flush_para()
                list_buf.append(re.sub(r"^[-*•]\s+", "", ln))
                continue
            flush_list()
            if ln.startswith("■"):
                flush_para()
                out.append(f'<p data-ke-size="size16">{esc(ln)}</p>')
                continue
            para_buf.append(ln)
        flush_para()
        flush_list()
    flush_para()
    flush_list()
    return "\n".join(out)


def publish_tistory(title: str, body_md: str, category: str, mode: str = "private",
                    images: list = None, wait_minutes: float = 6, tags: str = "") -> str:
    """tistory_poster 의 기존 발행 흐름 재사용. 반환: 글 URL.

    mode 는 draft/private/public. 기본은 private 이라 이 인자를 안 주던 기존
    호출부(블로그 리뉴얼 릴스 제작기)는 동작이 바뀌지 않는다.

    write_post() 하나가 ensure_login/_ctx/_page 를 전부 포함해서 처리하는
    최상위 함수라 그것만 부른다. prebuilt_html=True 로 넘겨 text_to_html/
    build_html(쿠팡 고지·제휴 링크 삽입 로직)을 아예 타지 않는다.
    """
    import tistory_poster as tp

    html = _md_to_tistory_html(body_md)
    res = tp.write_post(
        title, html, tags=tags or "", affiliate_url="", mode=mode,
        headless=False, prebuilt_html=True, category=category or "",
        upload_paths=images or None, wait_minutes=wait_minutes,
    )
    if not res.get("ok"):
        raise RuntimeError(res.get("why") or "티스토리 발행 실패(원인 미상)")
    return res.get("url", "")


def _md_to_naver_plain(md: str) -> str:
    """마크다운을 네이버 SmartEditor 타이핑용 평문으로 바꾼다.

    naver_poster.write_post 는 segments 를 안 주면 content 를 사람처럼 한 글자씩
    타이핑만 한다(HTML 해석 없음) — 마크다운 기호를 그대로 두면 화면에 '##', '**'
    가 글자 그대로 찍힌다. 그래서 기호만 제거하고 줄바꿈(문단 구분)은 그대로 둔다.
    """
    out = []
    for raw in (md or "").split("\n"):
        s = raw.strip()
        s = re.sub(r"^#{1,6}\s+", "", s)
        s = re.sub(r"^[-*•]\s+", "· ", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"\1", s)
        out.append(s)
    return "\n".join(out)


def _extract_naver_url(poster) -> str:
    """발행 직후 페이지에서 current_url 기반으로 blogId/logNo 를 긁어 PostView 주소를 만든다(최선 노력).

    naver_poster.write_post 는 성공 여부만 돌려주고 URL을 돌려주지 않는다
    (coupang_blog_pipeline.py 도 naver 발행 성공 시 record_published 를 url 없이
    부른다 — 이 프로젝트가 원래도 naver 글 URL을 남겨 오지 않았다). fix_published_
    naver.py 가 쓰는 것과 같은 logNo 정규식으로 최대한 복원한다. 못 찾으면 빈 문자열.
    page_source 전체를 보면 추천글·공유 위젯에서 다른 logNo를 잘못 매칭할 수 있어,
    current_url 기반 매칭만 사용한다(정확도 우선).
    """
    try:
        d = poster.driver
        cur = d.current_url or ""
    except Exception:
        return ""
    m = re.search(r"blogId=([\w-]+)&(?:amp;)?logNo=(\d{6,})", cur)
    if m:
        return f"https://blog.naver.com/PostView.naver?blogId={m.group(1)}&logNo={m.group(2)}"
    if "logNo=" in cur:
        return cur
    return ""


def _naver_id() -> str:
    """config.json 의 naver_id. 없으면 빈 문자열(호출부가 기존대로 동작)."""
    try:
        import json
        import pathlib
        cfg = pathlib.Path(__file__).with_name("config.json")
        return str(json.loads(cfg.read_text(encoding="utf-8")).get("naver_id", "")).strip()
    except Exception:
        return ""


def publish_naver(title: str, body_md: str, category: str, mode: str = "public",
                  images: list = None, wait_minutes: float = 6,
                  tags: str = "") -> str:  # mode·wait_minutes 는 무시 (네이버는 즉시 공개, 쿠키 재사용)
    """네이버 즉시 공개 발행 — 되돌리려면 블로그에서 직접 삭제해야 한다. 반환: 글 URL(확보 실패 시 빈 문자열).

    login(id, pw) 대신 _init_driver()+_load_cookies_and_check() 만 써서 저장된
    쿠키(~/.naver_poster_cookies.pkl) 세션만 재사용한다 — 아이디/비밀번호를
    다루는 로그인 흐름에는 들어가지 않는다. 쿠키가 없거나 만료됐으면 발행하지
    않고 실패로 보고한다(사용자가 naver_poster.py 로 먼저 로그인해야 한다).
    """
    from naver_poster import NaverBlogPoster

    poster = NaverBlogPoster(headless=False)
    try:
        poster._init_driver()
        if not poster._load_cookies_and_check():
            raise RuntimeError(
                "네이버 로그인 세션이 없거나 만료됐습니다 — "
                "naver_poster.py 로 먼저 로그인해 쿠키를 만들어 두세요."
            )
        text = _md_to_naver_plain(body_md)
        # naver_id 를 빼면 글쓰기 URL 에 ?blogId= 가 붙지 않아 에디터 iframe 이
        # 아예 뜨지 않는다("에디터를 찾지 못했습니다" 로 실패) — 실측 확인.
        # 동작하는 coupang_blog_pipeline 과 같은 출처(config.json)에서 읽는다.
        # 이미지·태그는 write_post 가 원래 받는 인자인데 그동안 넘기지 않고 있었다.
        # 이미지는 pyautogui 로 윈도우 파일 선택 창을 조작해 붙는다 — 그동안 PC 를 건드리면 안 된다.
        ok = poster.write_post(title, text, category or "",
                               naver_id=_naver_id(),
                               tags=tags or "",
                               image_paths=images or None)
        if not ok:
            raise RuntimeError("네이버 발행 실패(자세한 원인은 콘솔 로그 참고)")
        return _extract_naver_url(poster)
    finally:
        poster.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    args = ap.parse_args()
    try:
        with open(args.file, encoding="utf-8") as f:
            h = json.load(f)
        fn = {"tistory": publish_tistory, "naver": publish_naver}.get(h["platform"])
        if not fn:
            _result(False, error=f"지원하지 않는 platform: {h['platform']}")
            return
        url = fn(h["title"], h["body_md"], h.get("category", ""), h.get("mode", "private"),
                 h.get("images") or None, float(h.get("wait_minutes", 6)),
                 ",".join(h.get("tags") or []) if isinstance(h.get("tags"), list) else (h.get("tags") or ""))
        _result(True, url=url or "")
    except Exception as e:
        _result(False, error=f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
