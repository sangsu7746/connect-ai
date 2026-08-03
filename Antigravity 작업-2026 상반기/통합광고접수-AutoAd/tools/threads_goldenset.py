# -*- coding: utf-8 -*-
# ============================================================
#  tools/threads_goldenset.py -- gate 실측 리포트 (Task 8)
#  · 실제 LLM 을 호출한다(할당량 소모). 평소엔 돌리지 않는다.
#  · 이 리포트가 THREADS_AUTO_THRESHOLD 의 유일한 근거다 -- 단,
#    tests/fixtures/sample_posts.json 이 synthetic(합성) 데이터인 동안은 아니다.
#    아래 main() 은 픽스처의 "synthetic" 플래그를 읽어, synthetic 데이터로
#    돌아간 실행이면 결과 맨 앞과 맨 끝에 경고를 못 보고 지나칠 수 없게 찍는다.
#
#  사용법 (실측 - 실제 LLM 호출, 할당량 소모):
#    python tools/threads_goldenset.py
#
#  실행 전 확인할 것: tests/fixtures/sample_posts.json 의 각 항목이
#  "synthetic": true 를 달고 있는 동안은 이 스크립트가 무엇을 출력하든
#  THREADS_AUTO_THRESHOLD 를 켤 근거가 되지 않는다. 실제 라벨링된 골든셋으로
#  교체하는 절차는 이 파일 하단 및 task-8-report.md 를 참고.
# ============================================================
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config                                      # noqa: E402
import profiles as _profiles                        # noqa: E402
from threads import gate                            # noqa: E402
from threads.models import RawPost                  # noqa: E402
from threads.reply_writer import _cp949_safe        # noqa: E402

FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "sample_posts.json"

# 이 골든셋의 문구는 PhotoMagic 프로필의 관심 키워드/하드블록을 가정하고
# 작성돼 있다(threads.gate 자체는 업종을 모르지만, 픽스처 텍스트는 특정
# 업종을 가정한다 - tests/test_gate.py 의 tcfg 픽스처도 photomagic.yaml 과
# 동일한 키워드 목록을 그대로 하드코딩해서 쓴다).
#
# 브리프의 원안은 여기서 config.PROFILE(활성 프로필, .env 의 AUTOAD_PROFILE)을
# 그대로 썼다. 이 저장소의 현재 AUTOAD_PROFILE 은 loan 이고 loan.yaml 에는
# threads: 섹션이 아예 없다 - 그대로 쓰면 관심 키워드가 빈 리스트가 되어
# 전건이 키워드 단계에서 탈락하고, 리포트는 "활성 프로필이 우연히 무엇인가"에
# 따라 조용히 의미를 잃는다. 그래서 이 리포트는 픽스처가 가정하는 프로필을
# 명시적으로 고정한다. 다른 업종의 골든셋을 돌리려면 THREADS_GOLDEN_PROFILE
# 인자로 넘기거나 아래 상수를 바꾼다.
GOLDEN_PROFILE_KEY = "photomagic"

_BANNER = "=" * 60


def _load_fixture(path: Path = FIXTURE) -> tuple:
    """(disclaimer_lines, entries) 를 돌려준다.

    Task 8 이전의 배열 최상위 형식도 허용해서, 픽스처를 실제 데이터로
    교체할 때 형식을 굳이 object 로 유지하지 않아도 되게 한다."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [], payload
    return list(payload.get("_disclaimer") or []), list(payload.get("posts") or [])


def _synthetic_split(entries: list) -> tuple:
    """(synthetic 로 표시된 건수, 전체 건수).

    entries 중 단 한 건이라도 synthetic 이면 전체 실행을 '오염된' 것으로
    본다 - 실제 데이터와 합성 데이터가 섞인 골든셋의 임계값은 실제 데이터만의
    임계값보다 신뢰도가 낮다. entries 가 전부 synthetic 이 아니면(=미래에
    실제 라벨링된 골든셋으로 완전히 교체된 뒤) 경고 없이 정상 리포트만 낸다."""
    synthetic_n = sum(1 for d in entries if d.get("synthetic") is True)
    return synthetic_n, len(entries)


def _print_synthetic_banner(synthetic_n: int, total_n: int, disclaimer: list) -> None:
    print(_BANNER)
    print("[!] SYNTHETIC DATA WARNING")
    print(f"[!] 이 픽스처의 {synthetic_n}/{total_n}건이 \"synthetic\": true 로 표시돼 있다.")
    for line in disclaimer:
        print(f"[!] {_cp949_safe(line)}")
    print("[!] 이 실행에서 나온 점수/임계값 후보는 THREADS_AUTO_THRESHOLD 를")
    print("[!] 켜는 근거가 될 수 없다. 실제로 라벨링된 골든셋으로 교체한 뒤")
    print("[!] 다시 돌려야 한다 (아래 '실제 골든셋 만드는 법' 참고).")
    print(_BANNER)


def main(_llm=None, profile_key: str = None) -> dict:
    """리포트를 찍고, 결과 요약 dict 를 돌려준다(테스트/재사용을 위해).

    _llm 을 넘기면 gate.screen() 에 그대로 전달돼 실제 LLM 을 호출하지
    않는다 - 하네스 자체를 검증할 때 쓴다. 평소 사용(python
    tools/threads_goldenset.py)에서는 None 이라 실제 LLM 을 부른다."""
    disclaimer, data = _load_fixture()
    if not data:
        print("[NG] 픽스처에 글이 하나도 없습니다. tests/fixtures/sample_posts.json 확인.")
        return {"false_pos": [], "false_neg": [], "buckets": {}, "is_synthetic_run": False}

    posts = [RawPost(url=d["url"], author=d["author"], text=d.get("text", ""),
                     posted_at=d.get("posted_at", "")) for d in data]
    labels = [d.get("label", "") for d in data]
    synthetic_n, total_n = _synthetic_split(data)
    is_synthetic_run = synthetic_n > 0

    key = profile_key or GOLDEN_PROFILE_KEY
    profile = _profiles.load(key)
    tcfg = gate.threads_config(profile)

    if is_synthetic_run:
        _print_synthetic_banner(synthetic_n, total_n, disclaimer)

    print(f"\n[골든셋] {len(posts)}건 판정 시작 (프로필={key}, 제공자={config.COPY_PROVIDER})")
    verdicts = gate.screen(posts, tcfg, _llm=_llm)

    buckets = {}
    false_pos = []                     # skip 인데 고득점 -- 가장 위험한 오류
    false_neg = []                     # reply 인데 저득점 -- 기회 손실
    for d, label, v in zip(data, labels, verdicts):
        buckets.setdefault(label or "(무라벨)", []).append(v.score)
        # 글 본문과 LLM reason 은 낯선 사람이 쓴 원문/모델의 자유 출력이라
        # cp949 콘솔에서 못 그리는 문자가 섞여 있을 수 있다. 여기서 안 막으면
        # 리포트 출력 도중 콘솔 자체가 죽어 나머지 결과를 통째로 잃는다
        # (threads/reply_writer.py 의 _cp949_safe 도입 배경과 같은 사고 유형).
        text_snip = _cp949_safe((d.get("text") or "")[:60])
        reason = _cp949_safe(v.reason or "")
        if label == "skip" and v.score >= config.THREADS_GATE_THRESHOLD:
            false_pos.append((v.score, text_snip, reason))
        if label == "reply" and v.score < config.THREADS_GATE_THRESHOLD:
            false_neg.append((v.score, text_snip, reason))

    print("\n── 라벨별 점수 분포 ──")
    for label, scores in sorted(buckets.items()):
        scores.sort()
        n = len(scores)
        print(f"  {label:12s} n={n:3d}  최소={scores[0]:3d} "
              f"중앙={scores[n // 2]:3d} 최대={scores[-1]:3d}")

    print(f"\n── 오탐(skip 인데 {config.THREADS_GATE_THRESHOLD}점 이상) {len(false_pos)}건 ──")
    for score, text, reason in sorted(false_pos, reverse=True):
        print(f"  {score:3d}점 | {text} | {reason}")

    print(f"\n── 미탐(reply 인데 {config.THREADS_GATE_THRESHOLD}점 미만) {len(false_neg)}건 ──")
    for score, text, reason in sorted(false_neg):
        print(f"  {score:3d}점 | {text} | {reason}")

    skip_max = max(buckets.get("skip", [0]))
    print("\n── 판정 ──")
    print(f"  skip 최고점 = {skip_max}")
    if false_pos:
        print(f"  [NG] 자동 발행 금지 - 달면 안 되는 글이 {len(false_pos)}건 통과했습니다.")
        print("     프롬프트/하드블록을 고치고 다시 돌리세요.")
    else:
        rec = max(skip_max + 10, 85)
        if is_synthetic_run:
            print("  [OK] 오탐 0건 (synthetic 픽스처 기준 - 하네스 동작 확인용).")
            print(f"     참고용 후보값 = {rec} -- 단, synthetic 데이터 기준이라")
            print("     THREADS_AUTO_THRESHOLD 로 실제 채택할 수 없습니다.")
        else:
            print(f"  [OK] 오탐 0건. 권장 THREADS_AUTO_THRESHOLD = {rec}")
            print("     (skip 최고점보다 충분히 위. 그래도 승인 30건 검증을 먼저 하세요.)")

    if is_synthetic_run:
        print()
        _print_synthetic_banner(synthetic_n, total_n, disclaimer)
        print("[!] 위 모든 숫자는 사람이 손으로 지어낸 데이터에서 나왔다.")
        print("[!] THREADS_AUTO_THRESHOLD 를 켜는 근거로 쓰지 마라.")

    return {
        "false_pos": false_pos,
        "false_neg": false_neg,
        "buckets": buckets,
        "is_synthetic_run": is_synthetic_run,
    }


if __name__ == "__main__":
    main()
