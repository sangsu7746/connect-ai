import re
from core import banned_words as bw

def test_superlative_patterns_match():
    samples = ["역대급 할인", "최저가 보장", "국내 최초 공개", "NO.1 브랜드",
               "무조건 사세요", "1위 제품", "유일한 방법"]
    for s in samples:
        assert any(re.search(p, s) for p, _ in bw.SUPERLATIVE), s

def test_cliche_patterns_match():
    samples = ["지금이 기회입니다", "품절 임박이에요", "안 사면 후회합니다",
               "가성비 갑이죠", "만족도가 높습니다", "효과가 증명된 방법"]
    for s in samples:
        assert any(re.search(p, s) for p, _ in bw.CLICHE), s

def test_first_person_patterns_match():
    samples = ["제가 직접 써 봤는데요", "내돈내산 솔직 후기", "사용해 보니 좋았어요"]
    for s in samples:
        assert any(re.search(p, s) for p in bw.FIRST_PERSON), s

def test_normal_text_not_matched():
    ok = ["전세 보증보험은 보증료가 연 0.128%다", "체크리스트를 확인하세요",
          "이 방법이 맞지 않는 사람도 있다"]
    for s in ok:
        assert not any(re.search(p, s) for p, _ in bw.SUPERLATIVE + bw.CLICHE), s
        assert not any(re.search(p, s) for p in bw.FIRST_PERSON), s

def test_prompt_ban_list_is_single_line():
    line = bw.prompt_ban_list()
    assert "\n" not in line and "역대급" in line and "최저가" in line
