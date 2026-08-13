"""
backend_router.py
여러 접근 경로(백엔드)를 순서대로 시도해 '첫 번째 완전 성공'을 채택하는 라우터.

왜 필요한가 — coupang_live_collector 의 상세 수집은 경로가 하나뿐이었다.
데스크톱 Playwright 로 /vp/products/ 를 열어 보고, 막히면 그냥 실패로 기록했다.
경로를 늘리려면 try/except 를 계속 겹쳐야 하고, 어느 경로가 지금 살아 있는지
알 방법도 없었다.

설계는 Agent Reach(github.com/Panniantong/agent-reach) 의 채널 라우팅을 옮겨왔다.
핵심 규칙 세 가지:

  1) 백엔드는 코드가 아니라 '순서 있는 후보 리스트'다.
     우선순위 교체 = 리스트 재정렬 또는 override 한 줄. 함수 수정이 아니다.

  2) 첫 응답이 아니라 '첫 완전 성공'이 이긴다.
     처음 시도한 백엔드가 반쪽짜리(partial)로 응답했다고 거기서 멈추면,
     뒤에 있는 멀쩡한 백엔드가 영원히 가려진다. 그래서 partial 은 기록만 하고
     다음 후보로 넘어가며, 모든 후보가 끝난 뒤에야 partial 중 첫 번째를 쓴다.

  3) 존재 증명 ≠ 건강 증명.
     페이지가 열렸다는 사실은 데이터가 왔다는 뜻이 아니다. 쿠팡 상세는 하이드레이션이
     덜 끝나면 제목만 나오고 가격·이미지가 통째로 0 이 되는데, 예전 코드는 이걸
     'OK' 로 출력했다. 판정은 반드시 결과물의 내용으로 한다(classify 콜백).

Agent Reach 와 다른 점 — 그쪽은 후보를 전부 probe 한다(`--version` 호출이라 공짜다).
여기서는 후보 한 번이 브라우저 페이지 로드이고, 게다가 두드릴수록 차단이 길어진다.
그래서 ok 가 나오면 즉시 멈춘다(`stop_on`). 비용이 다르면 전략도 달라야 한다.
"""
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

#: 좋은 순서. pick() 이 이 순서대로 훑는다.
STATUS_PREFERENCE = ("ok", "partial")

#: 전부 실패했을 때 원인을 구분하기 위한 상태값
#   ok       — 쓸 수 있는 결과를 받았다
#   partial  — 응답은 왔지만 알맹이가 모자란다(하이드레이션 미완, 텍스트 전용 백엔드 등)
#   blocked  — 상대가 막았다(차단 페이지)
#   error    — 예외로 터졌다
#   (핸들러가 None 을 반환하면 '이 환경에서 사용 불가'로 보고 후보에서 제외한다)


@dataclass
class Attempt:
    """백엔드 한 번의 시도 결과."""
    backend: str = ""
    status: str = "error"
    data: Any = None
    message: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def __str__(self) -> str:
        return f"{self.backend}: {self.status}" + (f" — {self.message}" if self.message else "")


def ordered_backends(candidates: Sequence[str],
                     override: Optional[str] = None,
                     env_var: Optional[str] = None) -> List[str]:
    """
    후보를 시도 순서대로 반환한다. override 로 지정한 백엔드를 맨 앞으로 끌어올린다.

    모르는 override 값은 조용히 무시한다 — 오래된 설정이 살아 있는 백엔드를
    통째로 가리는 사고를 막기 위해서다(있지도 않은 이름을 넣었다고 수집이
    멈추면 안 된다).
    """
    picks = list(candidates)
    wanted = override or (os.environ.get(env_var, "").strip() if env_var else "")
    if wanted:
        for i, name in enumerate(picks):
            if name == wanted or name.startswith(wanted):
                picks.insert(0, picks.pop(i))
                break
    return picks


def run_chain(candidates: Sequence[str],
              handlers: Dict[str, Callable[[], Optional[Attempt]]],
              *,
              override: Optional[str] = None,
              env_var: Optional[str] = None,
              stop_on: Sequence[str] = ("ok",),
              on_attempt: Optional[Callable[[Attempt], None]] = None) -> List[Attempt]:
    """
    후보를 순서대로 실행하고 시도 기록 전체를 반환한다.

    handlers[name] 은 Attempt 를 반환한다. None 을 반환하면 '이 환경에서는
    쓸 수 없는 백엔드'로 보고 후보에서 제외한다(미설치 등). 예외는 잡아서
    status="error" 로 기록하고 다음 후보로 넘어간다 — 한 경로가 터졌다고
    나머지 경로를 못 써 볼 이유가 없다.

    stop_on 에 든 상태가 나오면 즉시 멈춘다. 기본값 ("ok",) — 완전 성공만
    조기 종료 사유다.
    """
    attempts: List[Attempt] = []
    for name in ordered_backends(candidates, override, env_var):
        fn = handlers.get(name)
        if fn is None:
            continue                      # 미구현 후보는 조용히 건너뛴다
        try:
            att = fn()
        except Exception as e:            # noqa: BLE001 — 어떤 예외든 다음 후보로
            att = Attempt(name, "error", message=f"{type(e).__name__}: {e}"[:200])
        if att is None:
            continue                      # 이 환경에서 사용 불가 — 후보 아님
        att.backend = att.backend or name
        attempts.append(att)
        if on_attempt:
            on_attempt(att)
        if att.status in stop_on:
            break
    return attempts


def pick(attempts: Sequence[Attempt],
         preference: Sequence[str] = STATUS_PREFERENCE) -> Optional[Attempt]:
    """시도 기록에서 채택할 결과를 고른다. ok 가 하나도 없을 때만 partial 을 쓴다."""
    for wanted in preference:
        for att in attempts:
            if att.status == wanted:
                return att
    return None


def summarize(attempts: Sequence[Attempt]) -> str:
    """실패했을 때 '무엇을 시도했고 각각 왜 안 됐는지' 한 줄로 보여준다."""
    if not attempts:
        return "시도한 백엔드 없음"
    return " | ".join(str(a) for a in attempts)
