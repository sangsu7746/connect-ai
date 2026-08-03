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
    걸러지는가"다. `content.copy_engine._call_llm` 을 호출 시 예외를 던지게
    바꿔치기해도(모의 LLM 없이) 이 테스트는 그대로 통과한다 -- Task 8
    리뷰 1라운드에서 확인."""
    data = _load_posts()
    hard = [d for d in data if d.get("label") == "skip"
            and any(k in d["text"] for k in ("부고", "사고", "투병", "확진", "사망"))]
    assert len(hard) >= 5, "하드블록 표본이 너무 적어 검증이 성립하지 않는다"

    posts = [RawPost(url=d["url"], author=d["author"], text=d["text"]) for d in hard]
    tcfg = gate.threads_config(_profiles.load(GOLDEN_PROFILE_KEY))
    verdicts = gate.screen(posts, tcfg)
    passed = [(p.text[:40], v.score) for p, v in zip(posts, verdicts) if v.passed]
    assert passed == [], f"하드블록 글이 통과했다: {passed}"
