import json
from pathlib import Path

import pytest

import profiles as _profiles
from threads import gate
from threads.models import RawPost

FIXTURES = Path(__file__).parent / "fixtures"

# tests/fixtures/sample_posts.json 의 문구는 PhotoMagic 프로필의 관심
# 키워드/하드블록을 가정하고 쓰였다(tools/threads_goldenset.py 의
# GOLDEN_PROFILE_KEY 와 반드시 맞춰야 한다). config.PROFILE(활성 프로필,
# .env 의 AUTOAD_PROFILE)을 그대로 쓰면, 활성 프로필이 threads: 섹션이 없는
# 업종(예: loan)일 때 관심 키워드가 텅 비어 전건이 키워드 단계에서 탈락하고,
# 이 테스트는 '판정 통과한 글이 하나도 없으니' 그냥 통과해버린다 -- 하드블록이
# 실제로 걸러서가 아니라 애초에 아무것도 안 걸러서 생기는 거짓 안전이다.
GOLDEN_PROFILE_KEY = "photomagic"


def _load_posts() -> list:
    """sample_posts.json 은 {"_disclaimer": [...], "posts": [...]} 형태다.
    이전(배열 최상위) 형식도 허용한다."""
    payload = json.loads((FIXTURES / "sample_posts.json").read_text(encoding="utf-8"))
    return payload["posts"] if isinstance(payload, dict) else payload


def _llm_call_guard():
    """`_llm` 자리에 꽂을 스파이 + "한 번도 안 불렸다"를 나중에 확인할 수
    있는 호출 기록을 같이 돌려준다.

    단순히 예외를 던지는 함수만으로는 부족하다 -- `gate.screen()` 은 배치
    하나가 깨져도 나머지를 살리려고 `llm(prompt)` 호출을 통째로
    `except Exception:` 으로 감싼다(gate.py). `AssertionError` 도
    `Exception` 의 하위 클래스라 그 안에서 조용히 삼켜져 `retryable=True`
    로만 남고, 바깥의 `assert passed == []` 는 (호출된 적이 있어도) 그대로
    통과해버린다 -- "시끄럽게 실패"가 아니라 "더 조용히 실패"가 되는
    역효과. 그래서 호출 여부를 리스트에 먼저 기록해 두고, `gate.screen()`
    호출이 끝난 뒤 테스트 본문에서 그 기록을 명시적으로 assert 한다 --
    이 assert 는 gate.screen() 의 try/except 바깥에 있어서 절대 안
    삼켜진다."""
    calls = []

    def _llm(prompt: str) -> str:
        calls.append(prompt)
        raise AssertionError(
            "test_hardblocked_never_scores_high 이 LLM 을 호출하려 했다 -- "
            "hard 표본이 키워드 단계를 통과했다는 뜻이다.")

    return _llm, calls


@pytest.mark.golden
def test_hardblocked_never_scores_high():
    """이 시스템이 저지르면 안 되는 단 하나의 사고 --
    부고·사고·질병 글에 광고가 붙는 것. 여기서 막힌다.

    이 테스트는 `@pytest.mark.golden` 이 붙어 있어 평소 `pytest tests/`
    실행에서는 conftest.py 의 pytest_collection_modifyitems 가 스킵한다.
    `pytest -m golden` 으로만 선택된다.

    실제 LLM 을 호출하지 않는다(할당량 소모 없음) -- `hard` 로 뽑히는 글은
    전부 `label == "skip"` 이고 부고/사고/투병/확진/사망 중 하나를 문자
    그대로 담고 있는데, `gate.screen()` 은 `gate.keyword_pass()` 에서
    하드블록에 걸린 글을 LLM 에 아예 넘기지 않는다(gate.py 의
    "하드블록이 관심 키워드를 이긴다" 설계). 즉 이 테스트가 실제로 검증하는
    건 "LLM 이 이 글들을 낮게 채점하는가"가 아니라 "LLM 을 보기도 전에
    걸러지는가"다.

    이걸 "지금은 우연히 참"이 아니라 "깨지면 바로 드러나는 보장"으로
    만들기 위해 `_llm=_llm_call_guard()` 를 명시적으로 꽂는다 --
    `gate.screen(posts, tcfg)` 처럼 `_llm` 을 생략해서
    `content.copy_engine._call_llm`(실제 LLM, 할당량 소모)로 암묵적으로
    폴백하게 두지 않는다. `hard` 표본이 전부 키워드 단계에서 걸린다는
    전제가 미래에(픽스처 수정 등으로) 깨지면, 실제 LLM 을 조용히 부르는
    대신 아래 `assert llm_calls == []` 에서 즉시 시끄럽게 실패한다(Task 8
    리뷰 2라운드 -- 리뷰어가 이 테스트의 초기 버전으로 실제 소액 할당량을
    태운 사고 이후 추가)."""
    data = _load_posts()
    hard = [d for d in data if d.get("label") == "skip"
            and any(k in d["text"] for k in ("부고", "사고", "투병", "확진", "사망"))]
    assert len(hard) >= 5, "하드블록 표본이 너무 적어 검증이 성립하지 않는다"

    posts = [RawPost(url=d["url"], author=d["author"], text=d["text"]) for d in hard]
    tcfg = gate.threads_config(_profiles.load(GOLDEN_PROFILE_KEY))
    llm_guard, llm_calls = _llm_call_guard()
    verdicts = gate.screen(posts, tcfg, _llm=llm_guard)
    assert llm_calls == [], (
        f"LLM 이 {len(llm_calls)}번 호출됐다 -- 하드블록 표본이 키워드 "
        f"단계를 안 통과하고 LLM 까지 갔다는 뜻이다(실사용이었다면 할당량이 "
        f"소모됐다). sample_posts.json 에서 어떤 글이 label=skip 인데 "
        f"gate.keyword_pass() 를 통과하는지 확인하라.")
    passed = [(p.text[:40], v.score) for p, v in zip(posts, verdicts) if v.passed]
    assert passed == [], f"하드블록 글이 통과했다: {passed}"
