# ============================================================
#  threads/reply_writer.py — 1단 통합 답글 생성 + 가드
#  · 브라우저를 모른다. 목 LLM 으로 전부 테스트된다.
#  · 가드는 copy_engine 의 실측 교훈을 그대로 가져온다
#    (자리표시자 미치환 → LLM 이 남의 서비스를 지어내 홍보한 사고).
# ============================================================
from __future__ import annotations

import json
import re
from pathlib import Path

import config
from threads.models import RawPost, Reply, Verdict

PROMPT_DIR = Path(__file__).parent / "prompts"

MAX_EMOJI = 2
_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_URL_RE = re.compile(
    r"\b(?:https?://)?([a-z0-9][a-z0-9.-]*\.(?:com|net|org|io|ai|app|kr|co\.kr|test))",
    re.I)
# 이모지 대략 범위 (정확한 유니코드 분류 대신 실용적 근사)
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")


def _own_host(landing: str) -> str:
    return re.sub(r"^https?://", "", (landing or "").strip().lower()).split("/")[0]


def _with_scheme(landing: str) -> str:
    """랜딩 값에 스킴이 없으면 https:// 를 붙인다.

    profiles/*.yaml 은 brand.site 를 스킴 없이 저장한다(예: 'photomagic.test').
    gate.threads_config() 의 폴백 경로(Task 2)를 타면 tcfg['landing'] 이 이
    맨 도메인 그대로 들어올 수 있다. 그 값을 프롬프트에 그대로 박으면 LLM 이
    스킴 없는 주소를 그대로 써서 쓰레드에서 링크로 인식되지 않을 수 있다 —
    프롬프트에 넣기 직전에만 정규화한다. validate() 의 호스트 비교(_own_host)는
    이미 스킴을 벗겨내고 비교하므로 스킴 유무와 무관하게 그대로 동작한다."""
    u = (landing or "").strip()
    if not u or re.match(r"^https?://", u, re.I):
        return u
    return "https://" + u


def validate(text: str, tcfg: dict) -> list:
    """문제 목록을 돌려준다. 빈 리스트면 통과."""
    problems = []
    body = text or ""

    if _PLACEHOLDER_RE.search(body):
        problems.append("치환되지 않은 자리표시자")

    max_chars = config.THREADS_REPLY_MAX_CHARS
    if len(body) > max_chars:
        problems.append(f"길이 초과({len(body)}/{max_chars}자)")
    if not body.strip():
        problems.append("길이 부족(빈 답글)")

    emoji_n = len(_EMOJI_RE.findall(body))
    if emoji_n > MAX_EMOJI:
        problems.append(f"이모지 과다({emoji_n}개, 최대 {MAX_EMOJI})")

    own = _own_host(tcfg.get("landing", ""))
    hosts = [h.lower() for h in _URL_RE.findall(body)]
    for h in hosts:
        if not own or (h not in own and own not in h):
            problems.append(f"우리 것이 아닌 주소: {h}")
    if len(hosts) > 1:
        problems.append(f"링크 과다({len(hosts)}개, 최대 1개)")

    for b in config.BANNED_PHRASES:
        if b and b in body:
            problems.append(f"금칙어 '{b}'")

    return problems


def _load_prompt() -> str:
    return (PROMPT_DIR / "reply.txt").read_text(encoding="utf-8")


def _build_prompt(post: RawPost, verdict: Verdict, tcfg: dict) -> str:
    banned = ", ".join(f'"{b}"' for b in config.BANNED_PHRASES) or "(없음)"
    landing = _with_scheme(tcfg.get("landing", ""))
    return (_load_prompt()
            .replace("{author}", post.author or "")
            .replace("{post_text}", (post.text or "").replace("\n", " ")[:600])
            .replace("{angle}", verdict.angle or "")
            .replace("{brand}", str(tcfg.get("brand", "")))
            .replace("{brand_desc}", str(tcfg.get("brand_desc", "")))
            .replace("{landing}", landing)
            .replace("{max_chars}", str(config.THREADS_REPLY_MAX_CHARS))
            .replace("{banned}", banned))


def _extract_reply(raw: str) -> str:
    if not raw:
        raise ValueError("빈 응답")
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"JSON 없음: {raw[:120]!r}")
    return str(json.loads(text[start:end + 1]).get("reply", "")).strip()


def _call_llm(prompt: str) -> str:
    from content import copy_engine
    return copy_engine._call_llm(prompt)


def write(post: RawPost, verdict: Verdict, tcfg: dict, _llm=None) -> Reply:
    """답글 1건 생성. 가드 위반이면 문제를 알려 1회 재생성하고,
    그래도 위반이면 예외를 던진다.

    잘라내기로 넘어가지 않는 이유 — 남의 서비스 이름을 지어낸 경우
    잘라내면 문장이 깨지고, 무엇보다 '왜 그랬는지'가 로그에 안 남는다."""
    llm = _llm or _call_llm
    base = _build_prompt(post, verdict, tcfg)
    landing = _with_scheme(tcfg.get("landing", ""))

    prompt = base
    notes = []
    for attempt in (1, 2):
        text = _extract_reply(llm(prompt))
        problems = validate(text, tcfg)
        if not problems:
            return Reply(text=text, guard_notes=notes)
        notes.append(f"{attempt}차 위반: {', '.join(problems)}")
        prompt = (base + "\n\n[재작성] 다음 문제를 고쳐라: "
                  + ", ".join(problems)
                  + f". 링크는 반드시 {landing} 하나만 쓰고 "
                    "다른 서비스 이름·주소는 절대 쓰지 마라.")

    raise ValueError(f"답글 가드 통과 실패: {' / '.join(notes)}")
