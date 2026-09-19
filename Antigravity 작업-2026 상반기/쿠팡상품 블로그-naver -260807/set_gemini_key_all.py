"""
Gemini API 키를 이 PC 의 모든 프로젝트에서 한 번에 바꾼다.

## 왜 필요한가
같은 키를 여러 코드베이스가 나눠 쓰고 있다(실측 19곳). 한 곳만 바꾸면 나머지가
옛 키로 계속 호출해서, 새 키의 무료 한도(하루 20회)를 옛 키 쪽이 아니라 이쪽이
금방 소진하거나, 반대로 옛 키를 쓰는 프로젝트가 조용히 죽는다.
어디를 고쳤는지 기억에 의존하지 않으려고 만든 도구다.

## 하는 일
  1. 지금 키를 쓰는 config.json 을 전부 찾는다
  2. 목록을 보여 주고 확인을 받는다
  3. 새 키가 실제로 동작하는지 먼저 확인한다
  4. 각 파일을 .bak 으로 백업하고 바꾼다

키는 이 창에서 입력받아 파일로만 간다. 화면에 다시 찍지 않고, 인자로도 받지 않는다
(명령 기록에 키가 남지 않게 하기 위함).
"""
import glob
import io
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.abspath(__file__))

#: 훑을 최상위 폴더. 여기 없는 프로젝트는 SCAN_ROOTS 에 추가하면 된다.
SCAN_ROOTS = [
    r"D:\Antigravity 작업-2026 상반기",
    r"D:\미리집-ReRoomAI",
    r"D:\카드뉴스-CardNews",
    r"D:\부동산릴스-EstateReels",
    r"D:\부동산릴스-EstateReels-v2",
    r"D:\HyperReels-260801",
    r"D:\MemoryFilm",
    r"D:\build-in-public",
    r"D:\건축스톱모션",
    r"D:\headjim_before_after",
]

KEY_FIELDS = ("gemini_api_key", "GEMINI_API_KEY", "google_api_key")


def _read(path: str):
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return None


def find_configs(old_key: str) -> list:
    """지금 키가 들어 있는 config.json 을 모두 찾는다."""
    found, seen = [], set()
    for root in SCAN_ROOTS:
        if not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, "**", "config.json"), recursive=True):
            real = os.path.normcase(os.path.abspath(path))
            if real in seen:
                continue
            seen.add(real)
            # 가상환경·캐시 안쪽은 건드리지 않는다
            if any(x in real for x in (r"\.venv", r"\node_modules", r"\__pycache__",
                                       r"\site-packages", r"\.git")):
                continue
            cfg = _read(path)
            if not isinstance(cfg, dict):
                continue
            for field in KEY_FIELDS:
                if cfg.get(field) == old_key:
                    found.append((path, field))
                    break
    return found


def verify(key: str) -> bool:
    """새 키가 실제로 응답하는지 본다. 안 되는 키로 19곳을 덮어쓰면 큰일이다."""
    try:
        sys.path.insert(0, BASE)
        import ai_writer
        model = ai_writer.MODEL
    except Exception:
        model = "gemini-flash-latest"

    import urllib.error
    import urllib.request
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    body = json.dumps({"contents": [{"parts": [{"text": "ok"}]}]}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=60)
        print(f"  ✅ 키 확인 완료 (모델 {model})")
        return True
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        print(f"  ❌ 키가 동작하지 않습니다 (HTTP {e.code})")
        if e.code == 429:
            if "prepayment" in raw:
                print("     → 선불 잔액이 0 입니다. ai.studio/projects 에서 충전하세요.")
            else:
                print("     → 할당량 초과입니다. 무료 등급은 하루 20회입니다.")
                print("       결제를 연결하면 한도가 올라갑니다.")
        elif e.code == 403:
            print("     → 결제가 정지된 프로젝트이거나 키가 막혔습니다.")
        elif e.code == 404:
            print(f"     → 모델 '{model}' 을 못 찾습니다. ai_writer.MODEL 을 확인하세요.")
        else:
            print("     ", raw[:200])
        return False
    except Exception as e:
        print(f"  ❌ 확인 실패: {str(e)[:160]}")
        return False


def main() -> int:
    print("=" * 66)
    print("  Gemini API 키 일괄 변경")
    print("=" * 66)

    here = os.path.join(BASE, "config.json")
    cfg = _read(here)
    if not isinstance(cfg, dict):
        print(f"  ❌ {here} 를 읽지 못했습니다.")
        return 1
    old = ""
    for field in KEY_FIELDS:
        if cfg.get(field):
            old = cfg[field]
            break
    if not old:
        print("  ❌ 현재 키를 찾지 못했습니다.")
        return 1

    print(f"  현재 키: ...{old[-6:]}")
    print("  같은 키를 쓰는 파일을 찾는 중입니다 (잠시 걸립니다)...")
    targets = find_configs(old)
    print(f"\n  {len(targets)}곳을 찾았습니다:")
    for path, field in targets:
        print(f"    · {path}   [{field}]")

    print()
    print("  새 키를 붙여넣고 Enter 를 누르세요. (취소하려면 그냥 Enter)")
    print("  https://aistudio.google.com/apikey")
    print()
    try:
        new = input("  새 키 > ").strip().strip('"').strip("'")
    except (EOFError, KeyboardInterrupt):
        print("\n  취소했습니다.")
        return 1

    if not new:
        print("  취소했습니다. 아무것도 바꾸지 않았습니다.")
        return 1
    if "..." in new or len(new) < 30:
        print(f"  ❌ 키가 잘린 것 같습니다({len(new)}자). 전체를 복사해 붙여넣으세요.")
        return 1
    if not new.startswith("AIza"):
        print(f"  ⚠️ 'AIza' 로 시작하지 않습니다({new[:6]}...).")
        if input("  그래도 진행할까요? (y/N) > ").strip().lower() != "y":
            return 1
    if new == old:
        print("  ⚠️ 지금 키와 같습니다.")
        return 1

    print("\n  키를 확인하는 중...")
    if not verify(new):
        print("\n  아무 파일도 바꾸지 않았습니다.")
        return 1

    print(f"\n  위 {len(targets)}곳을 모두 새 키로 바꿉니다.")
    if input("  진행할까요? (y/N) > ").strip().lower() != "y":
        print("  취소했습니다.")
        return 1

    done, failed = 0, []
    for path, field in targets:
        try:
            data = _read(path)
            if not isinstance(data, dict):
                failed.append((path, "읽기 실패"))
                continue
            io.open(path + ".bak", "w", encoding="utf-8").write(
                json.dumps(data, ensure_ascii=False, indent=2))
            data[field] = new
            io.open(path, "w", encoding="utf-8").write(
                json.dumps(data, ensure_ascii=False, indent=2))
            done += 1
            print(f"    ✔ {path}")
        except Exception as e:
            failed.append((path, str(e)[:60]))
            print(f"    ✘ {path} — {str(e)[:60]}")

    print()
    print("=" * 66)
    print(f"  {done}/{len(targets)}곳 변경 완료 (각 폴더에 config.json.bak 백업)")
    if failed:
        print(f"  실패 {len(failed)}곳 — 직접 확인하세요:")
        for path, why in failed:
            print(f"    · {path}: {why}")
    return 0 if done else 1


if __name__ == "__main__":
    code = main()
    print()
    try:
        input("  창을 닫으려면 Enter 를 누르세요...")
    except Exception:
        pass
    sys.exit(code)
