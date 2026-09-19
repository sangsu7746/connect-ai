# -*- coding: utf-8 -*-
"""check_group_rules.py — 그룹 소개·규칙을 읽어 '홍보 허용' 여부를 판단

왜 필요한가:
  '중고타투장터'는 이름만 보면 광고를 받아줄 것 같지만, 소개글에
  "타투용품점 및 용품 홍보하는 페이지가 아닙니다" 라고 적혀 있었다.
  실제로 올린 글이 관리자 승인 대기에 걸렸다.
  이름만으로 고르면 같은 실수가 반복되고, 계정 평판이 상한다.

무엇을 하는가:
  각 그룹의 소개/규칙 문구를 읽어와 LLM 에게 '홍보 게시물 허용 여부'를 묻고,
  channels.ad_policy 에 allow | deny | unknown 으로 저장한다.
  판단 근거(원문)도 함께 남겨 사람이 확인할 수 있게 한다.

⚠ 읽기 전용이다. 글을 쓰지 않는다.
⚠ 그룹 페이지를 연속 방문하므로 --limit 로 나눠 돌리는 것을 권한다.

사용:
  python tools/check_group_rules.py --profile inkcraft
  python tools/check_group_rules.py --profile inkcraft --apply
  python tools/check_group_rules.py --platform facebook --limit 30 --apply
"""
import sys
import io
import json
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _utf8_stdout():
    """콘솔 한글 깨짐 방지 — 스크립트로 실행될 때만.
    ⚠ 모듈 최상단에서 바꾸면 이 파일을 import 한 쪽의 출력이 닫혀버린다
      (cloud_sync·register_channels 에서 이미 같은 사고를 겪었다)."""
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      line_buffering=True)
    except Exception:
        pass


import config
import db
import orchestrator as O

# 소개글에서 이 말이 보이면 거의 확실히 홍보 금지다(LLM 앞단 빠른 판정).
DENY_HINTS = ("홍보 금지", "광고 금지", "홍보하는 페이지가 아", "홍보하는 페이지 아",
              "광고성 게시물", "홍보글 금지", "무단 광고", "상업적 게시물 금지",
              "판매 글 금지", "자기 홍보", "자기홍보", "상업적인내용", "상업적인 내용",
              "상업적 글", "홍보 및 광고", "광고글", "차단시키겠",
              "no promotion", "no advertising", "no ads", "no self-promotion")
ALLOW_HINTS = ("홍보 가능", "광고 가능", "홍보 허용", "자유 홍보", "무제한 홍보",
               "홍보 자유", "광고 환영", "홍보환영")
# '주제에서 벗어난 글 금지'는 홍보 금지가 아니다. 주제에 맞으면 올릴 수 있다.
TOPIC_HINTS = ("이외에 모든내용", "이외 모든 내용", "관련이외", "관련 이외",
               "주제와 무관", "관련 없는 글")


def fetch_about(auto, url: str) -> str:
    """그룹 소개·규칙 문구를 긁어온다. 못 읽으면 빈 문자열."""
    texts = []
    base = url.rstrip("/")
    for path in ("/about", ""):
        try:
            auto.driver.get(base + path + "/")
            time.sleep(3)
            t = auto.driver.execute_script("""
                const out = [];
                const og = document.querySelector("meta[property='og:description']");
                if (og && og.content) out.push(og.content);
                // 소개/규칙이 들어가는 영역을 넓게 훑는다
                document.querySelectorAll("div[role='main'] span, div[role='main'] div")
                  .forEach(e => {
                     const s = (e.innerText || '').trim();
                     if (s.length > 25 && s.length < 1200) out.push(s);
                  });
                return out.slice(0, 60).join('\\n');
            """) or ""
            if t.strip():
                texts.append(t)
            if len(" ".join(texts)) > 400:
                break
        except Exception:
            continue
    # 중복 줄 제거
    seen, lines = set(), []
    for ln in "\n".join(texts).splitlines():
        s = ln.strip()
        if s and s not in seen:
            seen.add(s)
            lines.append(s)
    return "\n".join(lines)[:4000]


def _hard_deny(text: str) -> str:
    """원문에 홍보 금지 문구가 있으면 그 대목을 돌려준다(없으면 빈 문자열).
    이 판정은 LLM 결과보다 우선한다 — 사람이 적어둔 규칙이 가장 확실한 근거다."""
    low = (text or "").lower()
    for h in DENY_HINTS:
        i = low.find(h.lower())
        if i >= 0:
            return (text[max(0, i - 25):i + 55]).replace("\n", " ").strip()
    return ""


def quick_verdict(text: str):
    low = (text or "").lower()
    if any(h.lower() in low for h in DENY_HINTS):
        return "deny"
    if any(h.lower() in low for h in ALLOW_HINTS):
        return "allow"
    if any(h.lower() in low for h in TOPIC_HINTS):
        return "topic_only"
    return None


def ask_llm(name: str, text: str) -> tuple:
    """LLM 판정. 반환 (policy, 근거)"""
    from content import copy_engine as CE
    prompt = f"""아래는 온라인 커뮤니티(페이스북 그룹)의 소개·규칙 문구입니다.
이 모임의 규칙이 무엇을 금지하는지 정확히 구분해 주세요.

[모임 이름] {name}
[소개·규칙]
{text[:2500]}

[분류 — 넷 중 하나]
- allow      : 홍보·광고·판매를 허용/환영한다고 적혀 있음
- deny       : **상업적 홍보 자체를 금지**한다고 적혀 있음
               (예: "자기 홍보 금지", "상업적인 글 삭제/차단", "홍보하는 페이지 아님")
- topic_only : 홍보 금지는 없고, **주제에서 벗어난 글만** 금지함
               (예: "○○ 관련 이외 모든 내용은 삭제", "주제와 무관한 글 금지")
               → 주제에 맞는 내용이면 올려도 되는 곳
- unknown    : 근거가 없거나 애매함 (억지로 allow 하지 마세요)

[중요]
'주제 관련성 규칙'과 '홍보 금지 규칙'은 다릅니다. 혼동하지 마세요.
"타투 관련 이외 삭제"는 topic_only 이지 deny 가 아닙니다.

[출력] JSON 만: {{"policy":"allow|deny|topic_only|unknown","why":"근거 한 줄(원문 인용)"}}"""
    try:
        raw = CE._call_llm(prompt)
        d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        p = str(d.get("policy", "unknown")).strip()
        return (p if p in ("allow", "deny", "topic_only", "unknown") else "unknown",
                str(d.get("why", ""))[:160])
    except Exception as e:
        return "unknown", f"판정 실패({type(e).__name__})"


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", help="업종 key 로 대상 한정 (예: inkcraft)")
    ap.add_argument("--platform", default="facebook", choices=["facebook", "band"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--apply", action="store_true", help="DB 에 기록")
    ap.add_argument("--recheck", action="store_true", help="이미 확인한 것도 다시")
    a = ap.parse_args()

    db.init_db()
    chans = [c for c in db.list_channels(platform=a.platform)
             if not db.is_demo_channel(c)]
    if a.profile:
        chans = [c for c in chans if c["profile_key"] == a.profile]
    if not a.recheck:
        chans = [c for c in chans if not c["ad_policy"]]
    if a.limit:
        chans = chans[:a.limit]
    if not chans:
        print("확인할 채널이 없습니다(이미 확인했거나 대상 없음).")
        return 0

    acc = O.default_account(a.platform)
    adapter = O.get_adapter(a.platform, acc)
    adapter.headless = False
    ok, why = O.ensure_login(adapter)
    if not ok:
        print(f"로그인 실패: {why[:150]}")
        return 1
    auto = adapter._automator()

    print(f"\n{len(chans)}개 그룹의 소개·규칙 확인 (약 {len(chans)*6//60+1}분)\n")
    res = []
    for i, c in enumerate(chans, 1):
        text = fetch_about(auto, c["target_ref"])
        pol = quick_verdict(text)
        why_s = "규칙 문구에서 직접 확인" if pol else ""
        if not pol:
            pol, why_s = ask_llm(c["name"], text) if text else ("unknown", "소개글을 못 읽음")
        # ⚠ 원문에 금지 문구가 있으면 LLM 판단보다 **원문이 우선**한다.
        #   실측: "자기 홍보 … 허용되지 않습니다"가 적힌 그룹을 LLM 이 allow 로 뒤집었다.
        #   판정이 실행마다 흔들리는데, 틀린 쪽이 '허용'이면 계정이 위험하다.
        hard = _hard_deny(text)
        if hard and pol != "deny":
            pol, why_s = "deny", f"원문 금지 문구 우선: …{hard}…"
        res.append((c, pol, why_s, text))
        mark = {"allow": "허용", "deny": "금지",
                "topic_only": "주제만", "unknown": "불명"}.get(pol, "불명")
        print(f"  {i:3d}. [{mark}] {c['name'][:40]:42s} {why_s[:52]}")
        if a.apply:
            db.set_ad_policy(c["id"], pol, text)

    from collections import Counter
    cnt = Counter(p for _, p, _, _ in res)
    print(f"\n{'-'*62}")
    print(f" 허용 {cnt.get('allow',0)} · 주제만 {cnt.get('topic_only',0)}"
          f" · 금지 {cnt.get('deny',0)} · 불명 {cnt.get('unknown',0)}")
    print(" (주제만 = 홍보 금지는 없고 주제 무관한 글만 금지 → 주제에 맞으면 게시 가능)")
    if not a.apply:
        print(" 기록하려면 --apply 를 붙여 다시 실행하세요.")
    else:
        print(" DB 에 기록했습니다.")
        deny = [c for c, p, _, _ in res if p == "deny" and c["enabled"]]
        if deny:
            for c in deny:
                db.set_channel_enabled(c["id"], False)
            print(f" ⚠ 홍보 금지 그룹 {len(deny)}개를 자동으로 껐습니다.")
    print(" (브라우저는 열어 둡니다 — 닫으면 세션이 사라집니다)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
