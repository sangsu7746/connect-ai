# -*- coding: utf-8 -*-
"""업종 프로필별 홍보 카드 일괄 생성 (실제 발행은 하지 않음)

각 프로필의 홍보서 → 브리프 추출 → 카드 이미지 → data/creatives/
생성만 하고, 발행은 승인 콘솔에서 사람이 결정한다.

사용: python tools/make_cards.py [--profiles a,b,c] [--channel band] [--workers 4]
"""
import sys, io, os, argparse, importlib, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import profiles as P

SKIP = {"loan"}          # 대출은 기성 전단을 쓰므로 설명서 생성 대상 아님


def build(key: str, channel: str, promo: str = None) -> dict:
    """프로필 하나로 카드 생성. 프로세스 전역 config 오염을 피하려 서브프로세스로 실행."""
    import subprocess, json
    code = (
        "import sys,io,json;"
        "sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8');"
        "import config;"
        "from content import pamphlet;"
        f"r=pamphlet.render_from_doc(channel={channel!r}, promo={promo!r});"
        "print('@@'+json.dumps({'path':r['path'],'headline':r['brief'].get('headline',''),"
        "'product':r['brief'].get('product',''),'site':config.BRAND_SITE,"
        "'company':config.BRAND_COMPANY},ensure_ascii=False))"
    )
    env = dict(os.environ, AUTOAD_PROFILE=key, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       cwd=str(Path(__file__).parent.parent), env=env, timeout=420)
    for line in (r.stdout or "").splitlines():
        if line.startswith("@@"):
            return {"key": key, "ok": True, **json.loads(line[2:])}
    err = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()
    return {"key": key, "ok": False, "error": err[-1][:200] if err else "알 수 없는 오류"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", default="", help="쉼표 구분. 미지정 시 docs 소스 전체")
    ap.add_argument("--channel", default="band")
    ap.add_argument("--promo", default=None)
    ap.add_argument("--workers", type=int, default=4, help="동시 생성 수(과하면 rate limit)")
    a = ap.parse_args()

    if a.profiles:
        keys = [k.strip() for k in a.profiles.split(",") if k.strip()]
    else:
        keys = []
        for k in P.available():
            if k in SKIP:
                continue
            try:
                if P.load(k)["content"]["source"] == "docs":
                    keys.append(k)
            except Exception:
                pass

    print(f"카드 생성 시작 — {len(keys)}종 · 채널 {a.channel} · 동시 {a.workers}\n")
    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(build, k, a.channel, a.promo): k for k in keys}
        for f in as_completed(futs):
            k = futs[f]
            try:
                r = f.result()
            except Exception as e:
                r = {"key": k, "ok": False, "error": f"{type(e).__name__}: {e}"}
            results.append(r)
            if r["ok"]:
                print(f"  [완료] {k:12s} {r['headline'][:26]:28s} {r['site']}")
            else:
                print(f"  [실패] {k:12s} {r['error']}")

    ok = [r for r in results if r["ok"]]
    print(f"\n생성 완료: {len(ok)}/{len(keys)}종 → data/creatives/")
    if len(ok) < len(keys):
        print("실패분은 위 오류를 확인하세요(대개 rate limit — --workers 를 줄여 재시도).")
    return results


if __name__ == "__main__":
    main()
