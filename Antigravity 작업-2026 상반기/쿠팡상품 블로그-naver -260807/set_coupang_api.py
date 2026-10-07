"""
쿠팡 파트너스 API 키를 config.json 에 넣고 바로 검증한다.

키는 이 창에서만 입력되고 파일로만 간다. 검증에 실패하면 저장하지 않는다 —
안 되는 키로 덮어쓰면 되돌릴 게 없다(Gemini 키 교체 때 같은 이유로 백업을 남겼다).
"""
import io
import json
import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CFG = os.path.join(BASE_DIR, "config.json")


def main() -> int:
    print("=" * 62)
    print("  쿠팡 파트너스 API 키 등록")
    print("=" * 62)
    print(f"  대상 파일: {CFG}")
    print()
    print("  쿠팡 파트너스 > 기타 > 오픈 API 에서 발급한 두 값을 넣습니다.")
    print("  비밀번호가 아니라 API 키입니다. 화면에 다시 출력되지 않습니다.")
    print()

    if not os.path.exists(CFG):
        print("  ✘ config.json 이 없습니다.")
        return 1
    cfg = json.load(io.open(CFG, encoding="utf-8"))

    cur_a = cfg.get("coupang_access_key", "")
    if cur_a:
        print(f"  현재 등록된 access key: {cur_a[:8]}...")
        print()

    try:
        access = input("  ACCESS KEY > ").strip()
        secret = input("  SECRET KEY > ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  취소했습니다.")
        return 1

    if not access or not secret:
        print("  두 값이 모두 필요합니다. 취소했습니다.")
        return 1

    # 먼저 검증하고 통과했을 때만 저장한다
    print()
    print("  키를 확인하는 중...")
    cfg_bak = dict(cfg)
    cfg["coupang_access_key"] = access
    cfg["coupang_secret_key"] = secret
    io.open(CFG, "w", encoding="utf-8").write(
        json.dumps(cfg, ensure_ascii=False, indent=2))

    try:
        import importlib
        import coupang_api
        importlib.reload(coupang_api)
        ok = coupang_api.selftest() == 0
    except Exception as e:
        print(f"  ✘ 검증 중 오류: {str(e)[:200]}")
        ok = False

    if not ok:
        # 되돌린다
        io.open(CFG, "w", encoding="utf-8").write(
            json.dumps(cfg_bak, ensure_ascii=False, indent=2))
        print()
        print("  ✘ 검증에 실패해 이전 설정으로 되돌렸습니다.")
        return 1

    shutil.copy2(CFG, CFG + ".bak")
    print()
    print("  ✅ 저장 완료. 이제 딥링크를 로그인 없이 만들 수 있습니다.")
    print("     python daily_links.py   (API 를 우선 사용합니다)")
    return 0


if __name__ == "__main__":
    code = main()
    print()
    try:
        input("  창을 닫으려면 Enter > ")
    except Exception:
        pass
    sys.exit(code)
