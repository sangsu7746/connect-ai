# -*- coding: utf-8 -*-
"""classify_channels.py — 채널마다 어울리는 업종 광고를 배정

같은 대출 광고를 400곳에 뿌리는 대신, 그룹 성격에 맞는 업종 광고를 보낸다.
(타투 그룹엔 타투 도안, 부동산 그룹엔 담보대출, 반려동물 그룹엔 펫 초상화 …)

이름만 보고 규칙으로 나누면 놓치는 게 많아 LLM 에게 분류를 맡긴다.
사람이 확인할 수 있게 **결과를 먼저 보여주고**, --apply 를 줘야 DB 에 쓴다.

사용:
  python tools/classify_channels.py                # 분류만 보기
  python tools/classify_channels.py --apply        # DB 에 배정
  python tools/classify_channels.py --platform facebook
"""
import sys
import io
import json
import argparse
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

import config
import db
import profiles as P

# 업종별로 '이런 모임에 맞다'를 한 줄로. LLM 에게 주는 설명.
HINT = {
    "loan":        "부동산·담보대출·경매·재테크·자금·사업자금·창업자금 — 돈 빌릴 일이 있는 모임",
    "inkcraft":    "타투·문신 관련 모임",
    "petportrait": "반려동물·강아지·고양이 모임",
    "nailpreview": "네일·뷰티·미용 모임",
    "wallpreview": "인테리어 소품·그림·액자·집꾸미기 모임",
    "mirizip":     "인테리어·리모델링·집수리·이사 모임",
    "proheadshot": "취업·이직·구인구직·비즈니스 프로필이 필요한 모임",
    "printcraft":  "굿즈·상품 제작·판매·쇼핑몰·창업 모임",
    "stickerme":   "캐릭터·이모티콘·굿즈 좋아하는 모임",
    "photomagic":  "사진·이미지 편집에 관심 있는 일반 모임",
    "memoryfilm":  "가족·기념일·결혼·돌잔치 모임",
    "homage":      "영상 제작·추억·가족 영상 모임",
    "colorcraft":  "육아·아이·교육 모임",
    "adstudio":    "광고·마케팅·홍보·자영업 모임",
}
NONE = "none"      # 어느 업종도 맞지 않음(광고 보내지 않음)


def build_prompt(items) -> str:
    lines = "\n".join(f"{i+1}. {n}" for i, (_, n) in enumerate(items))
    kinds = "\n".join(f"- {k}: {v}" for k, v in HINT.items())
    return f"""아래는 온라인 커뮤니티(밴드/페이스북 그룹) 이름 목록입니다.
각 모임에 광고를 낸다면 어느 업종이 가장 어울릴지 하나만 고르세요.

[업종]
{kinds}
- {NONE}: 위 어느 것도 어울리지 않음(무관한 주제, 판단 불가, 또는 광고하면 안 될 곳)

[중요]
- 불법·위험 신호가 있는 모임(내구제, 가개통, 선불유심, 토토, 사채, 카드깡 등)은
  반드시 {NONE} 으로 분류하세요.
- 애매하면 억지로 끼워맞추지 말고 {NONE} 을 고르세요.
- 홍보·광고 허용 모임은 그 모임이 다루는 주제로 판단하세요. 주제가 없으면 adstudio.

[모임 목록]
{lines}

[출력]
JSON 배열만 출력하세요. 설명·주석 금지.
[{{"n":1,"k":"업종키"}}, {{"n":2,"k":"업종키"}}, ...]
목록의 모든 번호가 정확히 한 번씩 나와야 합니다."""


def classify(items, chunk=60) -> dict:
    """{channel_id: profile_key}"""
    from content import copy_engine as CE
    out = {}
    valid = set(HINT) | {NONE}
    for s in range(0, len(items), chunk):
        part = items[s:s + chunk]
        print(f"  분류 중 {s+1}~{s+len(part)} / {len(items)}")
        try:
            raw = CE._call_llm(build_prompt(part))
            data = json.loads(raw[raw.find("["):raw.rfind("]") + 1])
        except Exception as e:
            print(f"    실패({type(e).__name__}) — 이 묶음은 {NONE} 처리")
            data = []
        got = {}
        for d in data:
            try:
                i = int(d["n"]) - 1
                k = str(d["k"]).strip()
                if 0 <= i < len(part) and k in valid:
                    got[i] = k
            except Exception:
                continue
        for i, (cid, _) in enumerate(part):
            out[cid] = got.get(i, NONE)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", default="all", choices=["all", "band", "facebook", "kakao"])
    ap.add_argument("--apply", action="store_true", help="DB 에 실제로 배정")
    ap.add_argument("--chunk", type=int, default=60)
    a = ap.parse_args()

    db.init_db()
    chans = db.list_channels() if a.platform == "all" else db.list_channels(platform=a.platform)
    chans = [c for c in chans if not db.is_demo_channel(c)]
    # 카카오 방은 전부 대부업체 접수·답변방(거래처)이라 소비자 광고 대상이 아니다.
    # 분류에 넣으면 '대출 주제'라는 이유로 loan 이 배정돼 거래처에 광고가 나간다.
    if a.platform == "all":
        skipped = [c for c in chans if c["platform"] == "kakao"]
        chans = [c for c in chans if c["platform"] != "kakao"]
        if skipped:
            print(f"카카오 {len(skipped)}개는 제외(거래처 방 — 소비자 광고 대상 아님)")
    items = [(c["id"], c["name"] or c["target_ref"]) for c in chans]
    if not items:
        print("분류할 채널이 없습니다.")
        return 1

    print(f"채널 {len(items)}개 · 업종 {len(HINT)}종 + {NONE}")
    print(f"카피 제공자: {config.COPY_PROVIDER} ({config.COPY_MODEL_GEMINI})\n")

    res = classify(items, a.chunk)

    by = defaultdict(list)
    for cid, name in items:
        by[res.get(cid, NONE)].append(name)

    print("\n" + "=" * 62)
    print(" 분류 결과")
    print("=" * 62)
    order = sorted(by, key=lambda k: (-len(by[k]), k))
    for k in order:
        label = P.load(k)["name"] if k in HINT else "광고 안 함"
        print(f"\n■ {k:12s} {label:28s} {len(by[k]):3d}개")
        for n in by[k][:8]:
            print(f"    · {n[:56]}")
        if len(by[k]) > 8:
            print(f"      ... 외 {len(by[k]) - 8}개")

    print("\n" + "-" * 62)
    print(" 요약: " + " · ".join(f"{k} {len(v)}" for k, v in
                                 sorted(by.items(), key=lambda x: -len(x[1]))))

    if not a.apply:
        print("\n실제로 배정하려면 --apply 를 붙여 다시 실행하세요.")
        return 0

    n = 0
    for cid, key in res.items():
        db.set_channel_profile(cid, None if key == NONE else key)
        n += 1
    print(f"\n{n}개 채널에 업종 배정 완료.")
    print("업종별 캠페인은 tools/run_by_profile.py 로 돌립니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
