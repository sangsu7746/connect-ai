"""
이미 만들어 둔 릴스 한 건을 인스타그램에 올린다.

video_pipeline.py --upload 은 '새 상품을 골라 영상부터 만든다'. 이미 만든 영상을
올리기만 할 때 쓰는 것이 이 스크립트다. 첫 업로드처럼 셀렉터가 맞는지 확인할 때 편하다.

    python upload_one_reels.py <mp4 경로> [상품ID] [--account=headjim_03]

상품ID 를 주면 그 상품의 캡션을 만들어 붙이고, 성공 시 원장에 발행으로 기록한다.
--account 를 주면 그 계정 전용 세션 폴더를 쓴다. 계정마다 로그인을 따로 해야 하지만,
한 폴더를 여러 계정이 나눠 쓰다가 엉뚱한 곳에 올리는 사고를 막는다.
"""
import io
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    account = ""
    for a in sys.argv[1:]:
        if a.startswith("--account="):
            account = a.split("=", 1)[1].strip().lstrip("@")

    video = args[0] if args else ""
    pid = args[1] if len(args) > 1 else ""

    if not os.path.exists(video):
        print(f"영상이 없습니다: {video}")
        return 1

    import video_pipeline as V

    caption = ""
    cap_file = os.path.join(V.OUT_DIR, f"caption_{pid}.txt")
    if pid and os.path.exists(cap_file):
        caption = io.open(cap_file, encoding="utf-8").read()
    elif pid:
        import sqlite3
        conn = sqlite3.connect(V.DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM products WHERE product_id=?", (pid,)).fetchone()
        conn.close()
        if not row:
            print(f"DB에 상품 {pid} 이(가) 없습니다.")
            return 1
        prod = dict(row)
        lines = io.open(os.path.join(V.OUT_DIR, f"script_{pid}.txt"),
                        encoding="utf-8").read().strip().split("\n") \
            if os.path.exists(os.path.join(V.OUT_DIR, f"script_{pid}.txt")) else []
        if not lines:
            print("대사 파일이 없습니다. 캡션 본문 없이 고지·링크·해시태그만 올립니다.")
        caption = V.build_caption(prod, {"lines": lines})

    if not caption:
        print("캡션이 비었습니다. 상품ID를 주세요.")
        return 1

    print("=" * 58)
    print("올릴 내용")
    print("=" * 58)
    print(f"영상  : {os.path.basename(video)} ({os.path.getsize(video)//1024:,} KB)")
    print(f"계정  : @{account}" if account else "계정  : (기본 세션)")
    print("-" * 58)
    print(caption)
    print("=" * 58)

    import instagram_poster as IG
    res = IG.upload_reels([{"key": pid or "one", "video": video, "caption": caption}],
                          account=account)
    r = res.get(pid or "one", {})
    if r.get("ok"):
        if pid:
            V.mark_posted(pid, "instagram", r.get("url", ""))
        print("✅ 업로드 완료")
        return 0
    print(f"✘ 실패: {r.get('why')}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
