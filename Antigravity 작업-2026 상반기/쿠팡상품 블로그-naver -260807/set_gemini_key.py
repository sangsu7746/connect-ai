"""
Gemini API 키를 바꾸고 바로 검증한다.

왜 이 스크립트가 있는가:
같은 이름의 config.json 이 이 PC 여러 폴더에 있어서, 손으로 고치면 엉뚱한 파일을
고치기 쉽다(실제로 그랬다). 이 스크립트는 자기 옆에 있는 config.json 만 건드리므로
경로를 착각할 여지가 없다. 입력한 키는 이 창에서 파일로만 가고 화면에 다시 찍히지 않는다.
"""
import io
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(BASE, "config.json")


def main() -> int:
    print("=" * 62)
    print("  Gemini API 키 변경")
    print("=" * 62)
    print(f"  대상 파일: {CFG}")

    if not os.path.exists(CFG):
        print("\n  ❌ config.json 이 없습니다. 이 스크립트를 올바른 폴더에 두세요.")
        return 1

    cfg = json.load(io.open(CFG, encoding="utf-8"))
    old = cfg.get("gemini_api_key", "")
    print(f"  현재 키  : {old[:6]}...{old[-4:]}" if len(old) > 12 else "  현재 키  : (없음)")
    print()
    print("  새 키를 붙여넣고 Enter 를 누르세요. (취소하려면 그냥 Enter)")
    print("  https://aistudio.google.com/apikey 에서 발급합니다.")
    print("  ※ 결제가 막힌 프로젝트가 아닌 '새 프로젝트'의 키여야 합니다.")
    print()

    try:
        new = input("  새 키 > ").strip().strip('"').strip("'")
    except (EOFError, KeyboardInterrupt):
        print("\n  취소했습니다.")
        return 1

    if not new:
        print("  취소했습니다. 파일을 바꾸지 않았습니다.")
        return 1
    if not new.startswith("AIza"):
        print(f"  ⚠️ 'AIza' 로 시작하지 않습니다({new[:6]}...). 키가 맞는지 확인하세요.")
        if input("  그래도 저장할까요? (y/N) > ").strip().lower() != "y":
            print("  취소했습니다.")
            return 1
    if new == old:
        print("  ⚠️ 지금 들어 있는 키와 같습니다. 새 키가 맞는지 확인하세요.")
        return 1

    # 먼저 검증하고, 통과했을 때만 저장한다. 안 되는 키로 덮어쓰면 되돌릴 게 없다.
    print("\n  키를 확인하는 중...")
    try:
        from google import genai
        # 모델명을 여기에 박아 두면 안 된다. gemini-2.5-flash 가 박혀 있었는데
        # 구글이 신규 사용자에게 막아서, 멀쩡한 키를 넣어도 404 로 거부당했다.
        # 실제로 쓰는 모델과 같은 것으로 확인해야 검증에 의미가 있다.
        import ai_writer
        r = genai.Client(api_key=new).models.generate_content(
            model=ai_writer.MODEL, contents="ok 이라고만 답하세요")
        print(f"  ✅ 응답 확인: {(r.text or '').strip()[:30]}")
    except Exception as e:
        msg = str(e)
        print(f"  ❌ 키가 동작하지 않습니다:\n     {msg[:200]}")
        if "dunning" in msg or "PERMISSION_DENIED" in msg:
            print("\n     → 결제가 정지된 프로젝트의 키입니다.")
            print("       AI Studio 에서 '새 프로젝트에서 API 키 만들기' 를 고르세요.")
        elif "prepayment" in msg or "RESOURCE_EXHAUSTED" in msg:
            print("\n     → 키는 살아 있는데 선불 잔액이 0 입니다.")
            print("       ai.studio/projects 에서 충전하거나, 결제가 걸린")
            print("       다른 프로젝트의 키를 쓰세요.")
        elif "NOT_FOUND" in msg or "404" in msg:
            print(f"\n     → 모델 '{__import__('ai_writer').MODEL}' 을 못 찾습니다.")
            print("       ai_writer.py 의 MODEL 값을 확인하세요.")
        print("\n  파일을 바꾸지 않았습니다.")
        return 1

    # 되돌릴 수 있게 백업부터
    bak = CFG + ".bak"
    io.open(bak, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))
    cfg["gemini_api_key"] = new
    io.open(CFG, "w", encoding="utf-8").write(json.dumps(cfg, ensure_ascii=False, indent=2))

    print(f"\n  ✅ 저장 완료 — {CFG}")
    print(f"     이전 설정 백업: {os.path.basename(bak)}")
    print("\n  이제 원고 생성이 가능합니다.")
    return 0


if __name__ == "__main__":
    code = main()
    print()
    try:
        input("  창을 닫으려면 Enter 를 누르세요...")
    except Exception:
        pass
    sys.exit(code)
