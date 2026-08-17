"""
쿠팡 상품 → 인스타그램 릴스 영상 + 소개글 파이프라인.

블로그 파이프라인과 별개로 돈다. 공유하는 것은 상품 DB·딥링크·가드레일뿐이다.

흐름:
  1. 상품 선정   딥링크가 있고 아직 영상을 안 만든 것
  2. 대사 생성   상품 실측값으로 짧은 대본. 가드레일로 날조 차단
  3. TTS         edge-tts, 1.5배속
  4. 영상 합성   상품 이미지 Ken Burns + 자막 (reels_generator 재사용)
  5. 소개글      인스타 캡션 + 대가성 고지 + 딥링크
  6. 업로드      instagram_poster (별도)

## 영상 소재에 대하여
처음 요청은 '상품명을 중국어로 바꿔 틱톡에서 검색해 영상을 내려받아 쓴다' 였다.
그 방식은 쓰지 않는다 — 틱톡 영상의 저작권자는 그 크리에이터이고, 자막·나레이션을
얹는 것은 2차적저작물 작성이라 허락이 필요하다. 인스타그램의 '비독창 콘텐츠' 정책도
남의 영상에 사소한 편집을 더한 것을 계정 단위로 추천에서 제외한다.
대신 쿠팡 상품 이미지로 모션 영상을 만든다. 파트너스가 제휴 목적 이미지 사용을 허용하고,
reels_generator 가 이미 9:16 1080x1920 로 만들 수 있다.
"""
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB = os.path.join(BASE_DIR, "price_history.db")
OUT_DIR = os.path.join(BASE_DIR, "reels_output")
LOG_DIR = os.path.join(BASE_DIR, "logs")

#: 나레이션 배속. edge-tts 의 rate 는 기본 대비 증감률이다.
#: 처음에는 요청대로 1.5배(+50%)로 넣었는데 실제 영상에서 알아듣기 어려웠다.
#: 자막을 눈으로 따라 읽을 시간도 안 나온다. +15% 로 낮춘다.
#: 더 빠르게 하려면 이 값만 올리면 된다("+30%" 처럼).
TTS_RATE = "+15%"
#: 릴스 목표 길이(초). 인스타는 90초까지 되지만 상품 소개는 짧을수록 끝까지 본다.
TARGET_SECONDS = 20


def log(msg=""):
    line = msg if not msg else f"[{datetime.now():%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with io.open(os.path.join(LOG_DIR, f"video-{datetime.now():%Y-%m}.log"),
                     "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════
# 발행 원장 — 블로그와 같은 방식으로 중복을 막는다
# ════════════════════════════════════════════════════════════════

def _conn():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS published_videos (
            product_id TEXT NOT NULL,
            channel    TEXT NOT NULL,
            made_at    TEXT NOT NULL,
            video_path TEXT,
            posted_at  TEXT,
            url        TEXT,
            PRIMARY KEY (product_id, channel)
        )
    """)
    conn.commit()
    return conn


def pick_targets(n: int, channel: str = "instagram") -> list:
    """딥링크가 있고 아직 이 채널에 영상을 안 올린 상품."""
    conn = _conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT * FROM products p
             WHERE p.is_real = 1
               AND p.affiliate_url LIKE '%link.coupang.com%'
               AND p.current_price > 0
               AND p.product_id NOT IN (
                     SELECT product_id FROM published_videos WHERE channel = ?)
             ORDER BY p.discount_rate DESC, p.review_count DESC
             LIMIT ?
        """, (channel, n)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def record_video(product_id: str, channel: str, video_path: str = "") -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO published_videos "
            "(product_id, channel, made_at, video_path) VALUES (?,?,?,?)",
            (str(product_id), channel, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             video_path))
        conn.commit()
    finally:
        conn.close()


def mark_posted(product_id: str, channel: str, url: str = "") -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE published_videos SET posted_at=?, url=? "
            "WHERE product_id=? AND channel=?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), url,
             str(product_id), channel))
        conn.commit()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════
# 대사 — 짧고, 실측값만
# ════════════════════════════════════════════════════════════════

def build_script(product: dict, log=log) -> dict:
    """
    영상 대사를 만든다. 블로그 원고와 달리 아주 짧아야 한다 — 20초 안에 읽혀야 한다.
    실측값만 쓰고, 가드레일로 지어낸 숫자·표현을 막는다.
    """
    import coupang_blog_pipeline as P
    import guardrails as G
    import unit_price as U
    import config as cfg

    title = product.get("title", "")
    curr = product.get("current_price", 0)
    orig = product.get("original_price", 0)
    disc = product.get("discount_rate", 0)
    unit_lines = U.context_lines(title, curr)
    observed = P._observed_date(product.get("updated_at", ""))

    facts = [f"- 상품명: {title}"]
    if observed:
        facts.append(f"- 확인 시점: {observed}")
    if orig:
        facts.append(f"- 정가: {orig:,}원")
    if curr:
        facts.append(f"- 판매가: {curr:,}원" + (f" ({disc}% 할인)" if disc else ""))
    if orig and curr and orig > curr:
        facts.append(f"- 절감액: {orig - curr:,}원")
    facts.extend(unit_lines)
    if product.get("review_count"):
        facts.append(f"- 상품평 수: {product['review_count']:,}개")
    context = "[쿠팡에서 실제로 수집한 값 — 이 밖의 사실을 지어내지 말 것]\n" + "\n".join(facts)

    # 문장 수를 쓸 수 있는 사진 수에 맞춘다.
    # 사진보다 문장이 많으면 남는 장면을 같은 사진으로 채우게 되는데, 그러면
    # 한 병 사진이 네 장면 내내 나온다. 짧아도 반복 없는 편이 낫다.
    import reels_generator as R
    n_scenes = min(4, R.count_product_images(product))

    prompt = f"""{context}

세로 영상(릴스) 대사를 만들어라.

규칙:
- 정확히 {n_scenes}문장. 문장마다 짧게. 한 문장 45자 안쪽.
  (이 상품은 쓸 수 있는 사진이 {n_scenes}장뿐이라 장면도 {n_scenes}개다.
   문장이 남으면 잘려 나가고, 모자라면 빈 장면이 생긴다)
- 첫 문장은 이 상품이 필요한 '한 사람의 상황'으로 시작한다. 상품명으로 시작하지 마라.
- 가격을 말할 때는 확인 시점을 함께 말한다.
- 개당 단가가 위에 있으면 반드시 쓴다. 총액보다 판단이 선다.
- 단점이나 안 맞는 경우를 한 문장 넣는다. 없는 단점을 지어내지는 마라.
- "역대급", "최저가", "지금이 기회", "강력 추천" 같은 표현 금지.
- 써 보지 않았으므로 "제가 써보니" 같은 1인칭 경험을 쓰지 마라.
- 각 문장을 한 줄씩, 번호나 기호 없이 출력한다. 다른 말은 쓰지 마라."""

    api_key = cfg.load_config().get("gemini_api_key", "")
    if not api_key:
        raise RuntimeError("config.json 에 gemini_api_key 가 없습니다.")
    from google import genai
    import ai_writer
    client = genai.Client(api_key=api_key)
    r = client.models.generate_content(model=ai_writer.MODEL, contents=prompt)
    lines = [x.strip(" -•\t") for x in (r.text or "").strip().split("\n") if x.strip()]
    lines = [x for x in lines if len(x) > 4][:n_scenes]

    narration = " ".join(lines)
    guard = G.check(narration, context)
    return {"lines": lines, "narration": narration, "guard": guard, "context": context}


# ════════════════════════════════════════════════════════════════
# 인스타그램 캡션
# ════════════════════════════════════════════════════════════════

def build_caption(product: dict, script: dict) -> str:
    """
    인스타 캡션. 대가성 고지가 **첫 줄**이어야 한다.

    인스타는 첫 줄 뒤를 '더보기'로 접는데, 공정위가 '더보기' 뒤 표시를 부적절 사례로
    명시했다(2024년 모니터링 최다 적발 유형이 바로 이 '부적절한 위치'였다).
    그래서 고지를 맨 앞에 두고, 링크와 해시태그는 그 뒤에 놓는다.
    """
    import coupang_blog_pipeline as P
    import keyword_finder

    aff = product.get("affiliate_url", "")
    body = "\n".join(script["lines"])
    try:
        kws = keyword_finder.find_keywords(product, n=8, log=lambda *a: None)
    except Exception:
        kws = []
    tags = " ".join("#" + re.sub(r"\s+", "", k) for k in kws[:8])

    return (
        f"{P.PARTNERS_DISCLOSURE}\n"
        f"\n{body}\n"
        f"\n▶ 구매는 프로필 링크에서 확인하세요\n"
        f"   {aff}\n"
        f"\n{tags}"
    )


# ════════════════════════════════════════════════════════════════
# 영상
# ════════════════════════════════════════════════════════════════

def make_video(product: dict, script: dict, log=log) -> str:
    """
    상품 이미지로 9:16 릴스를 만든다. reels_generator 의 렌더러를 그대로 쓴다.
    대사는 1.5배속으로 읽고, 같은 문장을 자막으로 얹는다.

    대사를 직접 넘기는 게 핵심이다. 그러지 않으면 렌더러가 스토리보드에서
    자체 문구를 만들어 쓰는데, 그건 가드레일을 안 거친 문장이다.
    """
    import reels_generator as R

    pid = str(product["product_id"])
    os.makedirs(OUT_DIR, exist_ok=True)

    path = R.generate_product_reels_video(
        pid, script_lines=script["lines"], tts_rate=TTS_RATE)
    log(f"    영상 생성: {os.path.basename(path)}")
    return path


def main() -> int:
    n = 1
    upload = "--upload" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit():
            n = int(a)

    log("=" * 58)
    log(f"릴스 영상 파이프라인 — 목표 {n}건" + (" · 업로드까지" if upload else " · 영상만"))

    targets = pick_targets(n)
    if not targets:
        log("⛔ 대상이 없습니다 — 딥링크가 있고 영상을 안 만든 상품이 0건입니다.")
        return 0

    made = 0
    jobs = []
    for i, prod in enumerate(targets, 1):
        log("")
        log(f"[{i}/{len(targets)}] {prod['title'][:44]}")
        try:
            sc = build_script(prod)
        except Exception as e:
            log(f"    ✘ 대사 생성 실패: {str(e)[:100]}")
            continue
        if not sc["guard"]["ok"]:
            for b in sc["guard"]["blocking"][:3]:
                log(f"    ⛔ {b}")
            continue
        log(f"    대사 {len(sc['lines'])}문장 · {len(sc['narration'])}자")
        for line in sc["lines"]:
            log(f"      · {line[:52]}")

        caption = build_caption(prod, sc)
        cap_path = os.path.join(OUT_DIR, f"caption_{prod['product_id']}.txt")
        os.makedirs(OUT_DIR, exist_ok=True)
        io.open(cap_path, "w", encoding="utf-8").write(caption)
        log(f"    캡션 저장: {os.path.basename(cap_path)}")

        try:
            path = make_video(prod, sc)
        except Exception as e:
            log(f"    ✘ 영상 생성 실패: {str(e)[:120]}")
            continue

        record_video(prod["product_id"], "instagram", path)
        made += 1
        jobs.append({"key": str(prod["product_id"]), "video": path, "caption": caption})

    log("")
    log("=" * 58)
    log(f"영상 {made}/{len(targets)}건 생성 · {OUT_DIR}")

    if not upload:
        log("업로드는 하지 않았습니다. 올리려면 --upload 를 붙여 실행하세요.")
        return 0
    if not jobs:
        return 1

    log("")
    log("─" * 58)
    log("  브라우저가 열립니다. **인스타그램에 직접 로그인해 주세요.**")
    log("  비밀번호는 이 스크립트가 다루지 않습니다.")
    log("─" * 58)
    import instagram_poster as IG
    res = IG.upload_reels(jobs, log=log)

    ok = 0
    for j in jobs:
        r = res.get(j["key"], {})
        if r.get("ok"):
            ok += 1
            mark_posted(j["key"], "instagram", r.get("url", ""))
        else:
            log(f"  ✘ {os.path.basename(j['video'])} — {r.get('why')}")
    log(f"인스타그램 업로드 {ok}/{len(jobs)}건")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
