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


def _cp949_safe(s: str) -> str:
    """cp949 콘솔에 그대로 찍혀도 죽지 않도록 인코딩 불가 문자를 이스케이프한다.

    Task 1 에서 로그 문자열에 낀 em dash/이모지가 cp949 콘솔 자체를 죽여
    회차 하나를 통째로 날린 사고가 있었다. LLM 원문이 예외 메시지에 실리는
    이 지점(_extract_reply 의 JSON 파싱 실패 메시지)이 같은 사고의 재발
    지점이라 여기서 미리 막는다. repr() 은 출력 가능한 비-ASCII 문자를
    이스케이프하지 않으므로 repr 을 적용하기 전에 이걸 거쳐야 한다."""
    return s.encode("cp949", errors="backslashreplace").decode("cp949")


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
    """문제 목록을 돌려준다. 빈 리스트면 통과. 절대 예외를 던지지 않는다.

    tcfg=None 은 아직 프로필을 못 읽은 호출자에게서 실제로 들어올 수 있다.
    빈 dict 로 취급하면 own 이 빈 문자열이 되어 '모든 링크가 우리 것이
    아님'으로 처리되므로(landing 없음 → 전부 거부), 예외 대신 문제 목록으로
    자연스럽게 이어진다."""
    tcfg = tcfg or {}
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
        # 부분 문자열 비교(구 버전)는 'evilphotomagic.test',
        # 'photomagic.test.evil.com', 'app.test'(own 이 'my-photomagic-app.test'
        # 일 때) 를 전부 우리 것으로 오인했다 — 우리 도메인이 상대방 호스트의
        # 부분 문자열이거나 그 반대이기만 하면 통과되는 구조였기 때문이다.
        # 이건 표준적인 피싱 룩어라이크 모양이다. copy_engine._find_leaks() 는
        # 같은 부분 문자열 방식을 그대로 쓰지만 그쪽은 우리가 쓴 캠페인
        # 카피를 검사하는 것이고, 여기는 남이 쓴 글에 반응해 만든 답글이
        # 그 사람 타임라인에 자동 게시되는 것이라 노출 성격이 다르다 — 여기만
        # 정확 일치/도메인 경계(.) 일치로 좁힌다.
        if not own or not (h == own or h.endswith("." + own)):
            problems.append(f"우리 것이 아닌 주소: {h}")
    if len(hosts) > 1:
        problems.append(f"링크 과다({len(hosts)}개, 최대 1개)")

    for b in config.BANNED_PHRASES:
        if b and b in body:
            problems.append(f"금칙어 '{b}'")

    # 상투구 - 같은 계정이 매번 같은 말로 답글을 달면 그 자체가 광고 티다.
    # ⚠ 프롬프트에 "쓰지 마라" 로 나열하는 것만으로는 안 막힌다(실측
    #   2026-08-04): "미리 시뮬레이션 돌려보고" 를 금지했더니 "미리
    #   시뮬레이션해보면" · "가볍게 시뮬레이션 돌려보기" 로 변형해 나왔다.
    #   그래서 정규식으로 어간만 잡아 가드에서 재생성시킨다.
    for pat, label in _CLICHE_PATTERNS:
        if pat.search(body):
            problems.append(f"상투구 '{label}'")

    # 답글에 상대 핸들을 다시 붙이지 않는다. 이미 그 사람 글 밑이라
    # 불필요하고, 사람이 쓴 답글에서는 잘 안 나오는 모양이다.
    if re.search(r"@[A-Za-z0-9._]{2,}", body):
        problems.append("답글에 멘션(@아이디) 포함")

    # "미리집( https://... )" 처럼 괄호 안에 공백이 뜬 형태.
    if re.search(r"\(\s+https?://|https?://[^\s)]*\s+\)", body):
        problems.append("괄호 안 링크 공백")

    return problems


# 어간만 잡는다. 조사·활용이 붙어도 걸리도록.
_CLICHE_PATTERNS = [
    (re.compile(r"미리\s*시뮬레이션"), "미리 시뮬레이션"),
    (re.compile(r"시뮬레이션\s*(?:을\s*)?돌려"), "시뮬레이션 돌려"),
    (re.compile(r"미리\s*배치해"), "미리 배치해"),
    (re.compile(r"감\s*잡기\s*(?:편|좋)"), "감 잡기 편"),
    (re.compile(r"실패\s*(?:가\s*)?없[어었]"), "실패 없어"),
    (re.compile(r"훨씬\s*수월"), "훨씬 수월"),
    (re.compile(r"미리\s*보고\s*시작"), "미리 보고 시작"),
]


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
        raise ValueError(f"JSON 없음: {_cp949_safe(raw[:120])!r}")
    reply = json.loads(text[start:end + 1]).get("reply", "")
    if not isinstance(reply, str):
        # {"reply": null}/숫자/리스트를 str() 로 뭉개면 'None'/'12345' 같은
        # 문자열이 검증을 통과해 그대로 게시된다 — validate() 는 타입을 안
        # 보므로 아무 가드도 안 걸린다. LLM 이 null 로 "할 말 없음"을
        # 표현하는 건 충분히 있을 수 있는 일이라, 이건 파싱 실패와 동일하게
        # 다뤄 재시도로 흘려보낸다(빈 문자열/공백은 이미 길이 가드가 잡으므로
        # 여기서 막지 않는다).
        raise ValueError(
            f"reply 필드가 문자열이 아님(type={type(reply).__name__}): "
            f"{_cp949_safe(repr(reply))[:120]}")
    return reply.strip()


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
        try:
            text = _extract_reply(llm(prompt))
        except ValueError as e:
            # LLM 이 JSON 형식을 안 지킨 응답(설명 텍스트만, 네트워크 오류
            # 메시지 등)도 '위반'과 동일하게 다룬다. 여기서 안 잡으면
            # _extract_reply 의 ValueError 가 루프 밖으로 그대로 새어나가
            # 첫 호출이 쓰레기를 뱉는 순간 재시도 없이 바로 죽어 '1회
            # 재생성' 계약이 깨진다(copy_engine.generate_copy() 는 이
            # 파싱 실패를 잡아 재시도하는데, 이 모듈의 초판은 그 처리가
            # 빠져 있었다 — 리뷰에서 재현된 회귀).
            notes.append(f"{attempt}차 위반: 응답 파싱 실패({e})")
            prompt = (base + "\n\n[재작성] 이전 응답이 JSON 형식이 아니었다. "
                      '아래 형식만 정확히 출력하라: {"reply": "답글 전문"}')
            continue
        problems = validate(text, tcfg)
        if not problems:
            return Reply(text=text, guard_notes=notes)
        notes.append(f"{attempt}차 위반: {', '.join(problems)}")
        prompt = (base + "\n\n[재작성] 다음 문제를 고쳐라: "
                  + ", ".join(problems)
                  + f". 링크는 반드시 {landing} 하나만 쓰고 "
                    "다른 서비스 이름·주소는 절대 쓰지 마라.")

    raise ValueError(f"답글 가드 통과 실패: {' / '.join(notes)}")
