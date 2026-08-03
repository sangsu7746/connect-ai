# ============================================================
#  threads/gate.py — 답글 달 글 선별 (키워드 1차 → LLM 2차)
#  · 브라우저를 모른다. 계정 없이 골든셋으로 반복 검증 가능.
#  · 자동 발행 임계값은 이 모듈의 점수 분포에서 나온다.
# ============================================================
from __future__ import annotations

import json
import re
from pathlib import Path

import config
from threads.models import RawPost, Verdict

PROMPT_DIR = Path(__file__).parent / "prompts"
# LLM 한 번에 넘기는 글 수. 너무 크면 index 대응이 어긋나고, 너무 작으면 호출이 잦다.
BATCH_SIZE = 12


def threads_config(profile: dict) -> dict:
    """프로필에서 threads: 섹션을 꺼내고 빠진 값을 채운다."""
    t = dict((profile or {}).get("threads") or {})
    t.setdefault("interest_keywords", [])
    t.setdefault("hard_block", [])
    t.setdefault("landing", config.BRAND_SITE or "")
    t.setdefault("brand", config.BRAND_COMPANY or "")
    t.setdefault("brand_desc", config.PROFILE_NAME or "")
    return t


def keyword_pass(text: str, tcfg: dict) -> tuple:
    """1차 필터. 반환 (통과여부, 사유).

    하드블록이 관심 키워드를 이긴다. 순서가 뒤집히면
    '사고 사진 보정' 같은 글이 통과해 부고·사고 글에 광고가 붙는다."""
    body = text or ""
    for bad in tcfg.get("hard_block") or []:
        if bad and bad in body:
            return False, f"하드블록 '{bad}'"
    hits = [k for k in (tcfg.get("interest_keywords") or []) if k and k in body]
    if not hits:
        return False, "관심 키워드 없음"
    return True, f"키워드 {', '.join(hits[:3])}"


def _load_prompt() -> str:
    return (PROMPT_DIR / "screen.txt").read_text(encoding="utf-8")


def _posts_block(items: list) -> str:
    """LLM 에 넘길 글 목록. index 는 배치 안에서의 위치다."""
    lines = []
    for i, (_, post) in enumerate(items):
        body = (post.text or "").replace("\n", " ").strip()
        lines.append(f"[{i}] {body[:400]}")
    return "\n".join(lines)


def _extract_json(raw: str) -> dict:
    """copy_engine._extract_json 과 같은 규칙 (코드펜스·앞뒤 잡텍스트 허용)."""
    if not raw:
        raise ValueError("빈 응답")
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"JSON 없음: {raw[:120]!r}")
    return json.loads(text[start:end + 1])


def _call_llm(prompt: str) -> str:
    """copy_engine 의 제공자 전환을 그대로 재사용한다."""
    from content import copy_engine
    return copy_engine._call_llm(prompt)


def screen(posts: list, tcfg: dict, _llm=None) -> list:
    """입력과 같은 길이·같은 순서로 Verdict 를 돌려준다.

    1차에서 떨어진 글은 LLM 을 아예 보지 않는다. 비용도 있지만,
    하드블록 글에 LLM 이 높은 점수를 줄 여지를 없애는 것이 더 큰 이유다."""
    llm = _llm or _call_llm
    verdicts = [None] * len(posts)
    survivors = []                      # [(원래 index, post)]

    for idx, post in enumerate(posts):
        ok, reason = keyword_pass(post.text, tcfg)
        if ok:
            survivors.append((idx, post))
        else:
            verdicts[idx] = Verdict(passed=False, score=0, reason=reason)

    template = _load_prompt()
    for start in range(0, len(survivors), BATCH_SIZE):
        batch = survivors[start:start + BATCH_SIZE]
        prompt = (template
                  .replace("{brand}", str(tcfg.get("brand", "")))
                  .replace("{brand_desc}", str(tcfg.get("brand_desc", "")))
                  .replace("{posts_block}", _posts_block(batch)))
        try:
            data = _extract_json(llm(prompt))
            results = {int(r["index"]): r for r in data.get("results", [])}
        except Exception as e:
            # 배치 하나가 망가져도 나머지 배치는 계속 간다.
            # 판정 못 한 것은 '부적합'이 아니라 '아직 모름' → retryable.
            # (할당량이 떨어진 회차의 수집분을 통째로 버리지 않기 위해)
            for orig_idx, _ in batch:
                verdicts[orig_idx] = Verdict(
                    passed=False, score=0, retryable=True,
                    reason=f"LLM 판정 실패({type(e).__name__})")
            continue

        for local_i, (orig_idx, _) in enumerate(batch):
            r = results.get(local_i)
            if not r:
                verdicts[orig_idx] = Verdict(passed=False, score=0, retryable=True,
                                             reason="LLM 응답에 이 글이 없음")
                continue
            score = int(r.get("score") or 0)
            safe = bool(r.get("safe", False))
            # safe=False 면 점수가 아무리 높아도 떨어뜨린다.
            passed = safe and score >= config.THREADS_GATE_THRESHOLD
            verdicts[orig_idx] = Verdict(
                passed=passed, score=score,
                reason=str(r.get("reason") or ("" if safe else "LLM 안전판정 실패")),
                angle=str(r.get("angle") or ""))

    # 방어 — 어떤 경로로도 None 이 남지 않게
    return [v or Verdict(passed=False, score=0, retryable=True, reason="미판정")
            for v in verdicts]
