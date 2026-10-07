# ============================================================
#  demo.py — 시스템 체험하기 (안전: 실제 게시·실제 대출DB 변경 없음)
#
#  데모용 채널을 만들고 캠페인을 한 번 돌려서
#  "광고 자동 제작 → 승인 대기"까지 화면에서 눌러볼 수 있게 한다.
#
#  사용법
#    python demo.py            데모 채널·캠페인 생성 (승인 콘솔에서 승인해보기)
#    python demo.py --clean    데모로 만든 것 전부 삭제
#
#  ⚠ 데모 채널은 실제로 존재하지 않는 주소라 승인해도 실제 게시가 안 된다.
#    (GLOBAL_DRY_RUN=1 이면 애초에 어떤 채널이든 모의 발행만 된다)
# ============================================================
import sys
import io
import json
import argparse

import config
import db

DEMO_TAG = "[데모]"


def clean():
    with db.get_conn() as c:
        chans = [r["id"] for r in c.execute(
            "SELECT id FROM channels WHERE name LIKE ?", (DEMO_TAG + "%",))]
        camps = [r["id"] for r in c.execute(
            "SELECT id FROM campaigns WHERE title LIKE ?", (DEMO_TAG + "%",))]
        if camps:
            q = ",".join("?" * len(camps))
            crs = [r["id"] for r in c.execute(
                f"SELECT id FROM creatives WHERE campaign_id IN ({q})", camps)]
            if crs:
                qq = ",".join("?" * len(crs))
                c.execute(f"DELETE FROM approvals WHERE creative_id IN ({qq})", crs)
                c.execute(f"DELETE FROM posts WHERE creative_id IN ({qq})", crs)
                c.execute(f"DELETE FROM creatives WHERE id IN ({qq})", crs)
            c.execute(f"DELETE FROM campaigns WHERE id IN ({q})", camps)
        if chans:
            q = ",".join("?" * len(chans))
            c.execute(f"DELETE FROM posts WHERE channel_id IN ({q})", chans)
            c.execute(f"DELETE FROM channels WHERE id IN ({q})", chans)
    print(f"데모 데이터 삭제 완료 (채널 {len(chans)} · 캠페인 {len(camps)})")


def run():
    db.init_db()
    import orchestrator as orch

    print("=" * 58)
    print(" AutoAd 체험 — 광고 자동 제작해서 승인 대기까지 만들기")
    print("=" * 58)
    if config.GLOBAL_DRY_RUN:
        print(" 발행 모드: DRY-RUN — 승인해도 실제 게시는 되지 않습니다.")
    else:
        print(" ⚠ 발행 모드: 실발행 ON — 단, 데모 채널은 가짜 주소라 게시되지 않습니다.")
    print()

    # 데모 채널 (실제로 존재하지 않는 주소)
    ch = [
        db.add_channel("band", "https://band.us/band/DEMO-NOT-REAL",
                       name=f"{DEMO_TAG} 우리동네 부동산방", audience="consumer",
                       tone="친근하고 신뢰감 있게", topic="부동산 담보", enabled=True),
        db.add_channel("kakao", f"{DEMO_TAG} 사업자 단톡방",
                       name=f"{DEMO_TAG} 사업자 단톡방", audience="business",
                       tone="간결·전문", topic="사업자", enabled=True),
    ]
    print(f"1) 데모 채널 {len(ch)}개 생성 (소비자용 밴드 · 사업자용 카톡)")

    print("2) 캠페인 실행 — 채널 성향에 맞는 전단 선택 + 카피 자동 생성 중...")
    res = orch.run_campaign({
        "title": f"{DEMO_TAG} 담보대출 상담 캠페인",
        "product": "부동산·사업자 담보대출(1금융 연계)",
        "goal": "무료 상담 접수",
        "utm": "demo",
    })

    print()
    for cr in res["creatives"]:
        cap = cr["caption"]
        print(f"   ▸ {cr['channel']} ({cr['platform']}) — 전단: {cr['product']}")
        print(f"     헤드라인: {cap.get('headline')}")
        if cap.get("_fallback"):
            print("     (카피 생성 실패로 기본 문구 사용 — GEMINI_API_KEY 확인)")

    print()
    print("=" * 58)
    print(" 이제 브라우저에서 눌러보세요")
    print("=" * 58)
    print(f"  승인 콘솔 : http://127.0.0.1:8010/approvals")
    print(f"     → 전단 사진과 문구를 보고 [승인] 또는 [거절]을 눌러보세요")
    print(f"  대시보드  : http://127.0.0.1:8010/dashboard")
    print(f"     → 승인하면 '오늘 발행'과 채널별 성과에 반영됩니다")
    print(f"  접수폼    : {config.PUBLIC_BASE}/?channel=band_{ch[0]}&utm=demo")
    print(f"     → 소비자가 보는 화면 (실제 접수되니 테스트 시 주의)")
    print()
    print("  정리하려면:  python demo.py --clean")


def main():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="데모 데이터 삭제")
    a = ap.parse_args()
    clean() if a.clean else run()


if __name__ == "__main__":
    main()
