# -*- coding: utf-8 -*-
"""_find_foreign — 한국어 문구에 섞인 낯선 문자체계 차단

실측 사고(2026-08-07, 캠페인 #45 cr#287):
  "질감이 살짝 들어가 있는 게 눈이  ఎక్కువగా 가는 편입니다"
  텔루구 문자가 한국어 문장 한가운데 섞여 나왔다. 금칙어 목록으로는 못 막는다
  — 어떤 문자가 섞일지 미리 알 수 없다.

⚠ 거짓 차단이 더 비싸다. 정상 한국어 광고에 흔히 쓰는 것(영문 브랜드명·이모지·
  한자·통화기호·낱자모)은 반드시 통과해야 한다. 통과 케이스를 먼저 본다.
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ⚠ 콘솔 기본 인코딩(cp949)으로는 여기서 다루는 문자를 못 찍는다.
#   출력하다 죽으면 '검사기가 틀렸다'로 오해하게 된다.
# ⚠ sys.stdout 을 **새 TextIOWrapper 로 갈아끼우면 안 된다**.
#   pytest 아래에서는 그 래퍼가 GC 될 때 캡처용 임시파일을 닫아버려
#   세션이 통째로 죽는다("ValueError: I/O operation on closed file",
#   수집 0건). reconfigure 는 같은 객체의 인코딩만 바꾸므로 안전하고,
#   pytest 캡처 객체처럼 지원하지 않는 대상에서는 조용히 넘어간다.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from content.copy_engine import _find_foreign


# (설명, 문구) — 차단되면 안 되는 것
PASS = [
    ("정상 한국어", "선이 굵직한 올드스쿨 느낌에 점묘로 음영을 채우는 도트워크를 써봤습니다."),
    ("영문 브랜드·주소", "AI 도안 생성기 headjim-ink.web.app 에서 확인하세요 (InkCraft)."),
    ("이모지", "굿즈 제작 \U0001F3A8 지금 확인 ▶ 100% 무료!"),
    ("한자·통화·기호", "㈜더스틴홀딩스 · 大邱 — 연 20.0% ~ ₩1,000만"),
    ("낱자모", "ㄱㄴㄷ ㅏㅑㅓ 표기 테스트"),
    ("일본어", "タトゥー デザイン 참고"),
    ("전각 괄호", "（공지） 오늘 마감"),
    ("줄바꿈·탭", "첫 줄\n둘째 줄\t끝"),
]

# (설명, 문구) — 반드시 차단해야 하는 것
BLOCK = [
    ("실제 사고(텔루구)", "질감이 들어가 있는 게 눈이 ఎక్కువగా 가는 편입니다."),
    ("키릴", "우리 서비스 Привет 확인"),
    ("아랍", "지금 مرحبا 확인"),
    ("태국", "도안 สวัสดี 보기"),
    ("데바나가리", "타투 नमस्ते 도안"),
    ("히브리", "굿즈 שלום 제작"),
]


def main():
    fails = []
    print("── 통과해야 하는 것 ─────────────────────────")
    for name, text in PASS:
        hits = _find_foreign(text)
        ok = not hits
        print(f"  {'OK ' if ok else 'NG '} {name:<16} {hits}")
        if not ok:
            fails.append(f"거짓 차단: {name} -> {hits}")

    print("\n── 차단해야 하는 것 ─────────────────────────")
    for name, text in BLOCK:
        hits = _find_foreign(text)
        ok = bool(hits)
        print(f"  {'OK ' if ok else 'NG '} {name:<16} {hits}")
        if not ok:
            fails.append(f"놓침: {name}")

    print("\n" + "-" * 46)
    if fails:
        for f in fails:
            print("  X", f)
        print(f" {len(fails)}건 실패")
        return 1
    print(f" {len(PASS) + len(BLOCK)}건 전부 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
