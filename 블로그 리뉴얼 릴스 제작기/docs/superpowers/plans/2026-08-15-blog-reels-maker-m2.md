# 블로그 리뉴얼 릴스 제작기 — M2 (분석 + 대본 엔진) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 선택한 블로그 글들을 분석해 보랏빛소 지침 + GEO 규칙 + 날조 게이트가 적용된 씬 단위 대본(릴스/롱폼)과 유튜브 설명란을 생성·편집하는 엔진과 UI를 만든다.

**Architecture:** M1의 FastAPI 서버에 대본 계층을 추가한다: 금지어 단일 모듈 → 날조 게이트(guardrails 이식) → 보랏빛소 지침 생성(원칙 8종 블로그판) → Gemini 클라이언트(모델 폴백) → 씬 테이블(storyboard) → 대본 엔진(챕터 배치 생성 + 씬 단위 게이트·재생성) → GEO 설명란. 웹에는 시드 편집 배선과 스토리보드 페이지를 추가한다.

**Tech Stack:** M1과 동일 (FastAPI, httpx, sqlite3, pytest / React+TS+Vite). Gemini는 REST 직접 호출(SDK 없음).

**Spec:** `docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md` (§6 진단, §7 대본 엔진, §9 씬 테이블, §12 마일스톤 2)

## Global Constraints

- .env 키 추가(정확히): `GEMINI_API_KEY` — `core/config.py`의 `settings.gemini_api_key`
- Gemini 모델 폴백 체인(정확히 이 순서): `gemini-3.5-flash` → `gemini-2.5-flash` → `gemini-1.5-flash` (spec §7)
- 자막 제한: caption ≤ **18자**, sub ≤ **22자** (spec §7, len() 기준)
- 씬 role 문자열(정확히): `hook` | `summary` | `chapter` | `point` | `twist` | `cta`
- 씬 테이블(총 씬 수, 챕터 타이틀 포함): 릴스 30초=7·60초=13 / 롱폼 60초=10·180초=24·300초=38·600초=72 (spec §9)
- 길이 배분 가중치: hook ×1.35, cta ×1.45, summary ×1.2, chapter ×0.6, 그 외 ×1.0, 최소 컷 2.2초, 합계=목표 길이 (spec §9)
- 날조 게이트: 대본의 모든 숫자는 수집 글 본문(context)에 존재하거나 뺄셈·나눗셈 파생값이어야 함. 공백 우회 차단, 부정·유보(_HEDGE) 문맥 통과 (spec §7)
- 게이트 실패 씬은 scene_level 재생성 최대 **3회**, 최종 실패 시 숫자 없는 안전 문구 (spec §7·§10)
- 원문 복사 차단: 공백 제거 후 연속 **15자** 이상 원문과 일치하면 차단 (spec §7 n-gram 검사)
- 진단 원칙: 판정·지침은 수집 데이터에서만, LLM 추론 금지 (spec §6)
- Gemini·외부 호출 전부 mock으로 테스트 (오프라인 CI)
- web은 `verbatimModuleSyntax: true` — 타입은 `import { type X }` 필수 (M1 확정)
- 문서·README의 셸 명령은 PowerShell 5.1 기준 — `&&` 금지, `;` 사용
- 테스트: `server/.venv/Scripts/python.exe -m pytest server/tests -v` (PYTHONUTF8=1 필요 시)
- 커밋은 태스크마다, 변경 파일만 정확히 `git add`(저장소 루트가 D:\ 전체 — `git add -A` 금지), 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: 금지어 공용 모듈 (banned_words)

**Files:**
- Create: `server/core/banned_words.py`
- Test: `server/tests/test_banned_words.py`

**Interfaces:**
- Produces: `SUPERLATIVE: list[tuple[str,str]]`(정규식, 사유), `FIRST_PERSON: list[str]`, `CLICHE: list[tuple[str,str]]`, `prompt_ban_list() -> str`(프롬프트 삽입용 한 줄 목록), Task 2 guardrails가 세 목록을 소비

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_banned_words.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `server\.venv\Scripts\python -m pytest server/tests/test_banned_words.py -v`
Expected: FAIL (모듈 없음)

- [ ] **Step 3: 구현**

`server/core/banned_words.py`:
```python
"""금지어 단일 출처. 원본(쿠팡 purple_cow.py×2 + reels_generator.py)에 3중복이던
목록을 한 곳으로 모은다 (spec §7). guardrails가 런타임 검사에, script_gen이
프롬프트 지침에 같은 목록을 쓴다.

쿠팡 상품 특화 행(재고·신선도·원가·유통)은 뺐다 — 블로그 대본에서는
"신선한 재료" 같은 정상 문장을 오차단한다.
"""

#: 최상급·순위 — 표시광고법 위반 소지. 원문에 있어도 옮겨 쓰지 않는다.
SUPERLATIVE = [
    (r"역대\s*급?|역대\s*가장|사상\s*최", "검증 불가한 최상급"),
    (r"최저가|가장\s*싼|(이보다|더)\s*싼\s*(곳|데|가격)?[은는이가]?\s*없", "최저가 주장"),
    (r"국내\s*최초|세계\s*최초|업계\s*최", "최초 주장"),
    (r"NO\.?\s*1|넘버\s*원|1\s*위|일등", "순위 주장"),
    (r"최고(의|급|다|입니다|예요)|최상(의|급)|최적(의)?\s*선택", "최상급"),
    (r"유일(한|무이)", "유일 주장"),
]

#: 상투어·조작성 표현
CLICHE = [
    (r"지금이\s*기회|지금\s*(사|하)지\s*않으면|놓치면\s*후회|서두르|서둘러", "조급 유도"),
    (r"품절\s*임박|얼마\s*남지\s*않|마감\s*임박|한정\s*수량", "희소성 조작"),
    (r"강력\s*추천|무조건\s*(사|하)세요|안\s*(사|하)면\s*후회|후회하지\s*않", "근거 없는 권유"),
    (r"가성비\s*(갑|최고|끝판)", "상투어"),
    (r"만족(도|했|하고\s*있|스러웠|한다는)", "리뷰 수는 만족을 뜻하지 않는다"),
    (r"(증명|입증)(된|하는|한다|합니다)", "숫자는 무엇도 증명하지 않는다"),
    (r"(검증|보장)(된|됐|합니다|됩니다|해\s*드)", "검증·보장 주체가 없다"),
]

#: 1인칭 사용 경험 사칭 — 추천·보증 심사지침 위반. 이 대본의 화자는 아무것도
#: 직접 해보지 않았다(원문 블로거가 한 것이다).
FIRST_PERSON = [
    r"직접\s*(써|사용|테스트|해)\s*(보|봤|본|봐)",
    r"제가\s*(써|사용|구매|구입|주문|받아|해)",
    r"저도\s*(써|사용|구매|구입|주문|해)",
    r"써\s*(봤|보니|보았|\s*본\s*결과)",
    r"사용(해|하고)\s*(보니|본\s*결과|봤|봤더니)",
    r"먹어\s*(봤|보니)|발라\s*(봤|보니)|입어\s*(봤|보니)|가\s*봤(는데|더니)",
    r"내돈내산|체험기|사용기|솔직\s*후기",
]


def prompt_ban_list() -> str:
    """프롬프트에 넣을 한 줄 금지어 안내."""
    words = ("역대급, 최저가, 국내 최초, NO.1, 1위, 최고, 유일, 지금이 기회, "
             "품절 임박, 강력 추천, 무조건, 가성비 갑, 만족도, 증명, 검증, 보장, "
             "직접 써봤다, 내돈내산, 솔직 후기")
    return f"다음 표현 금지(변형 포함): {words}"
```

- [ ] **Step 4: 테스트 통과 확인** — Run 위 명령, Expected: 5 PASS
- [ ] **Step 5: Commit**

```bash
git add server/core/banned_words.py server/tests/test_banned_words.py
git commit -m "feat(blog-reels): 금지어 단일 모듈 — 최상급·상투어·1인칭 사칭"
```

---

### Task 2: 날조 게이트 (guardrails 블로그판)

**Files:**
- Create: `server/core/guardrails.py`
- Test: `server/tests/test_guardrails.py`

**Interfaces:**
- Consumes: `banned_words.SUPERLATIVE/CLICHE/FIRST_PERSON`
- Produces: `check(text: str, context: str) -> dict{ok, blocking:[str], warnings:[str]}` — context는 수집 글 본문 전체. `check_copy(text: str, sources: list[str], run: int = 15) -> list[str]` — 공백 제거 연속 run자 이상 일치 문장 반환. 내부 `_HEDGE`, `_squash`, `_sentences`, `_numbers_with_ctx`, `_known_numbers`, `_derivable` (원본 이식)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_guardrails.py`:
```python
from core import guardrails as g

CTX = ("전세 보증보험은 보증료가 연 0.128%입니다. 3억 전세면 연 38만원."
       "\n가입은 계약 기간의 절반이 지나기 전까지 가능합니다."
       "\n보증 한도는 수도권 7억원입니다.")

def test_fabricated_number_blocked():
    r = g.check("가입자의 92%가 만족했습니다", CTX)
    assert not r["ok"]
    assert any("92" in b for b in r["blocking"])

def test_known_and_derived_numbers_pass():
    # 38만원(원문 존재), 0.128%(존재), 3억-7억 차이 4억(뺄셈 파생)
    r = g.check("보증료는 연 0.128%로 3억 기준 연 38만원이다.", CTX)
    assert r["ok"], r["blocking"]

def test_superlative_blocked_but_hedge_passes():
    assert not g.check("이 방법이 최저가로 가입하는 유일한 방법입니다", CTX)["ok"]
    assert g.check("최저가인지 아닌지 이 글은 확인할 수 없다.", CTX)["ok"]

def test_space_evasion_blocked():
    assert not g.check("최 저 가 방법입니다", CTX)["ok"]

def test_first_person_blocked():
    assert not g.check("제가 직접 써 봤는데 간단했어요", CTX)["ok"]

def test_date_numbers_ignored():
    r = g.check("2026년 8월 기준으로 확인된 내용이다", CTX)
    assert r["ok"], r["blocking"]

def test_no_context_warns():
    r = g.check("좋은 방법이다", "")
    assert r["ok"] and r["warnings"]

def test_copy_detection():
    src = ["전세 보증보험은 보증료가 연 0.128%입니다. 3억 전세면 연 38만원."]
    hits = g.check_copy("놀랍게도 전세 보증보험은 보증료가 연 0.128%입니다.", src)
    assert hits                                   # 연속 15자+ 복사
    assert not g.check_copy("보증료는 연 0.128%다. 즉 3억이면 38만원 수준.", src)
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL (모듈 없음)

- [ ] **Step 3: 구현**

`server/core/guardrails.py`:
```python
"""대본 발행 전 검사. 프롬프트로 부탁하는 것과 달리 여기서 걸리면 못 나간다.

원본(쿠팡 guardrails.py)의 핵심 교훈 유지: **날조는 열거할 수 없다** —
금지어 목록만으로는 날조 44건 중 42건이 통과했다. 그래서:
  1. 숫자 대조(주력) — 대본의 모든 숫자는 수집 글(context)에 있어야 한다.
     파생값은 뺄셈·나눗셈만 허용(절감액·단가). 곱셈·덧셈은 우연 통과 위험.
  2. 어휘 검사(보조) — banned_words 목록. 부정·유보 문맥은 통과.
  3. 공백 우회 차단 — '최 저 가' 대비, 공백 제거 사본도 검사.
  4. 복사 차단 — 공백 제거 후 연속 15자 이상 원문 일치 문장 차단 (저작권).
"""
import re

from .banned_words import CLICHE, FIRST_PERSON, SUPERLATIVE

_HEDGE = re.compile(
    r"(확인할\s*수\s*없|알\s*수\s*없|판단할\s*수\s*없|답할\s*수\s*없|"
    r"아니(다|라|며|고|에요|입니다|랍니다)|아님|"
    r"모른다|모릅니다|쓰지\s*않|쓸\s*수\s*없|말할\s*수\s*없|"
    r"근거가\s*없|데이터가\s*없|기록이\s*없|검증할\s*수\s*없|"
    r"보장하지\s*않|의미하지\s*않|뜻하지\s*않)")

_NUM = re.compile(r"\d[\d,]*\.?\d*")
#: 숫자 대조에서 뺄 것 — 날짜·서수처럼 본문에서 자연스럽게 생기는 값
_DATE_CTX = re.compile(r"(년|월|일|시|분|초|번째|층|호|세기)")


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _sentences(text: str) -> list:
    return [s for s in re.split(r"(?<=[.!?。])\s+|\n+", text or "") if s.strip()]


def _numbers_with_ctx(text: str) -> list:
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0).replace(",", "").rstrip(".")
        if not raw:
            continue
        try:
            v = float(raw)
        except ValueError:
            continue
        tail = (text or "")[m.end():m.end() + 4]
        out.append((v, tail))
    return out


def _known_numbers(context: str) -> set:
    vals = set()
    for v, _ in _numbers_with_ctx(context):
        vals.add(v)
        vals.add(round(v))          # 반올림 표기 차이 흡수
    return vals


def _derivable(v: float, known: set) -> bool:
    """실측값끼리의 뺄셈·나눗셈으로 나오는 값인가? (절감액·단가만 허용)"""
    if v <= 0:
        return False
    for a in known:
        if a <= 0:
            continue
        for b in known:
            if b <= 0 or b == a:
                continue
            if abs((a - b) - v) < 0.51:
                return True
            if 2 <= b <= 1000 and float(b).is_integer():
                q = a / b
                if abs(q - v) < 0.51 or abs(round(q) - v) < 0.51:
                    return True
    return False


def check(text: str, context: str = "") -> dict:
    """대본 텍스트를 검사한다. context = 수집 글 본문 전체(숫자의 유일한 출처)."""
    blocking, warnings = [], []

    for sent in _sentences(text or ""):
        hedged = bool(_HEDGE.search(sent))
        squashed = _squash(sent)
        for pats in (SUPERLATIVE, CLICHE):
            for pat, why in pats:
                m = re.search(pat, sent) or re.search(_squash(pat), squashed)
                if m and not hedged:
                    blocking.append(f"금지 표현 '{m.group(0)}'" + (f" — {why}" if why else ""))
        for pat in FIRST_PERSON:
            m = re.search(pat, sent)
            if m:
                blocking.append(f"사용 경험 사칭 '{m.group(0)}' — 화자는 직접 해보지 않았다")

    if context:
        known = _known_numbers(context)
        seen = set()
        for v, tail in _numbers_with_ctx(text or ""):
            if v in seen:
                continue
            seen.add(v)
            if _DATE_CTX.match(tail.strip()[:1] or " ") or _DATE_CTX.search(tail[:2]):
                continue
            if v in known or round(v) in known:
                continue
            if any(abs(v - k) <= max(1.0, abs(k) * 0.005) for k in known):
                continue
            if _derivable(v, known):
                continue
            blocking.append(f"수집 글에 없는 숫자 {v:,.10g} — 지어낸 값이거나 출처가 없다")
    else:
        warnings.append("수집 글 본문이 없어 숫자 대조를 건너뛰었다 — 검사가 약해진다")

    blocking = list(dict.fromkeys(blocking))
    return {"ok": not blocking, "blocking": blocking, "warnings": warnings}


def check_copy(text: str, sources: list[str], run: int = 15) -> list[str]:
    """대본 문장이 원문을 통째로 베꼈는지 본다. 공백 제거 후 연속 run자 이상
    원문에 그대로 있으면 그 문장을 반환한다 (재구성 원칙 — spec §7)."""
    squashed_sources = [_squash(s) for s in sources if s]
    hits = []
    for sent in _sentences(text or ""):
        sq = _squash(sent)
        if len(sq) < run:
            continue
        for i in range(0, len(sq) - run + 1):
            chunk = sq[i:i + run]
            if any(chunk in src for src in squashed_sources):
                hits.append(sent)
                break
    return hits
```

- [ ] **Step 4: 테스트 통과 확인** — Expected: 8 PASS (전체 스위트도 1회)
- [ ] **Step 5: Commit**

```bash
git add server/core/guardrails.py server/tests/test_guardrails.py
git commit -m "feat(blog-reels): 날조 게이트 — 숫자 대조·공백 우회·복사 차단 이식"
```

---

### Task 3: 보랏빛소 확장 — weak[]·행정 숫자 필터·지침 생성기

**Files:**
- Modify: `server/core/purple_cow_blog.py`
- Test: `server/tests/test_purple_cow_blog.py` (테스트 추가)

**Interfaces:**
- Consumes: `banned_words.prompt_ban_list`
- Produces: `diagnose()` 반환에 `weak: [str]` 추가(실패 문항 질문 목록). `PRINCIPLES: list[dict{n,name,origin,apply}]` 8종 블로그판. `_pick_principles(diag) -> list[dict]`(원본 매핑 유지). `build_script_guide(diag: dict, scene_level: bool = False) -> str` — Task 7 script_gen이 프롬프트 상단에 주입

- [ ] **Step 1: 실패하는 테스트 추가**

`server/tests/test_purple_cow_blog.py`에 추가:
```python
def test_weak_lists_failed_questions():
    d = pc.diagnose(POOR, [])
    assert len(d["weak"]) == 4
    d2 = pc.diagnose(RICH, CORPUS)
    assert d2["weak"] == []

def test_admin_numbers_excluded_from_hooks():
    post = {"title": "보증보험 안내", "source": "naver", "summary": "",
            "content": "문의 전화 1588-1234-5678번\n사업자 등록번호 120-88-00767"}
    d = pc.diagnose(post, [])
    assert d["hooks"] == []          # 행정성 숫자는 훅이 아니다

def test_pick_principles_mapping():
    d = pc.diagnose(POOR, [])        # 전 문항 실패 → 1,2,5,6,7,8 + 3,4 → 상위 5
    ns = [p["n"] for p in pc._pick_principles(d)]
    assert ns == [1, 2, 5, 6, 7]
    d2 = pc.diagnose(RICH, CORPUS)   # 3점 이상 → 덜어내기 [3,4,6]
    assert [p["n"] for p in pc._pick_principles(d2)] == [3, 4, 6]

def test_build_script_guide_scene_level_scope():
    d = pc.diagnose(RICH, CORPUS)
    full = pc.build_script_guide(d, scene_level=False)
    one = pc.build_script_guide(d, scene_level=True)
    assert "[씬 구성]" in full and "[이번 출력 범위]" not in full
    assert "[이번 출력 범위]" in one and "[씬 구성]" not in one
    assert "금지" in full and str(d["score"]) in full
```

- [ ] **Step 2: 실패 확인** — Expected: 새 테스트 4개 FAIL

- [ ] **Step 3: 구현**

`server/core/purple_cow_blog.py` 수정 — ① import 추가, ② 행정 숫자 필터, ③ diagnose 반환에 weak, ④ 파일 끝에 PRINCIPLES·_pick_principles·build_script_guide 추가:

```python
# (파일 상단 import 아래에 추가)
from .banned_words import prompt_ban_list

#: 훅 후보에서 배제할 행정성 숫자 문맥 (원본 BORING_KEY의 블로그판)
_ADMIN_CTX = re.compile(r"(전화|문의|팩스|사업자|등록\s*번호|우편|주소|계좌|"
                        r"인가|허가|신고\s*번호|-\d{2,})")
```

diagnose()의 Q1 블록에서 hook_nums 필터를 다음으로 교체:
```python
    hook_nums = []
    for raw, val, unit in extract_numbers(text):
        if unit not in _HOOK_UNITS and not (unit == "원" and val >= 10000):
            continue
        line = _sentence_around(text, raw)
        if _ADMIN_CTX.search(line):
            continue                      # 사업자번호·전화번호는 훅이 아니다
        hook_nums.append((raw, val, unit))
```

diagnose()의 return을 다음으로 교체:
```python
    score = sum(1 for a in answers if a["yes"])
    weak = [a["q"] for a in answers if not a["yes"]]
    return {"score": score, "verdict": VERDICTS[score],
            "answers": answers, "hooks": hooks, "weak": weak}
```

파일 끝에 추가:
```python
# ════════════════════════════════════════════════════════════════
# 보랏빛소 실행 원칙 8종 — 블로그 대본판 (원본: 쿠팡 purple_cow.py PRINCIPLES)
# ════════════════════════════════════════════════════════════════

PRINCIPLES = [
    {"n": 1, "name": "각도 변화",
     "origin": "고객의 호감을 살 수 있도록 제품을 근본적으로 변화시키는 방법 10가지를 생각해 본다.",
     "apply": "주제 자체는 못 바꾸니 '보는 각도'를 바꾼다. 이 주제를 다루는 뜻밖의 상황·용도 "
              "10가지를 떠올리고 가장 의외인 1가지로 영상을 연다."},
    {"n": 2, "name": "초소형 타깃",
     "origin": "가장 작은 시장을 먼저 정의하고, 그 틈새를 완전히 뒤흔들 제품을 그린다.",
     "apply": "'누구에게나 유용한 정보'라고 말하지 않는다. 이 정보가 미치도록 필요한 단 한 사람을 "
              "직업·상황·시간대까지 좁혀 지목하고, 그 한 사람에게 말하듯 쓴다."},
    {"n": 3, "name": "아웃소싱",
     "origin": "핵심 역량에 집중하고 나머지는 아웃소싱한다.",
     "apply": "대본은 '단 하나의 주장'만 책임진다. 세부 조건·예외·출처 나열은 "
              "설명란과 원문 링크에 위임하고 대본에서 지운다."},
    {"n": 4, "name": "허락자산 구축",
     "origin": "가장 충실한 고객들과 막힘없이 직접 얘기할 소통 구조를 만든다.",
     "apply": "CTA에서 '구독해 주세요'가 아니라 '무엇을 언제 보여줄지' 약속한다. "
              "예: 다음 영상에서 실패 사례 3가지를 공개합니다."},
    {"n": 5, "name": "타 장르 모방",
     "origin": "전혀 다른 산업에서 성공한 리마커블한 아이디어를 그대로 베낀다.",
     "apply": "정보 요약 형식을 버리고 다른 장르의 형식을 빌린다. "
              "실험 보고서 / 법정 판결문 / 연애편지 / 오답 노트 / 사건 브리핑 등."},
    {"n": 6, "name": "정반대 실행",
     "origin": "다른 회사들이 표준이라 믿는 방식을 완전히 뒤집어 시도한다.",
     "apply": "모두가 '이렇게 하세요'로 시작할 때 '이런 사람은 하지 마세요'로 연다. "
              "장점 앞에 단점·부작용을 먼저, 그것도 구체적으로 놓는다."},
    {"n": 7, "name": "최초 시도",
     "origin": "속한 산업에서 '아직 행해지지 않은 것'을 찾아 누구보다 먼저 실천한다.",
     "apply": "이 주제 영상에서 아무도 하지 않은 것을 하나 한다. "
              "예: 상위 글들의 상충 지점 공개 비교, 실패 조건 공개, 직접 계산."},
    {"n": 8, "name": "근본적인 의문",
     "origin": "관행적으로 이어져 온 방식에 항상 '왜 안 되는데?'라고 묻는다.",
     "apply": "숫자를 소개하지 말고 계산한다. '월로 나누면 얼마인가?' '하루당으로 보면?' "
              "총액은 판단이 안 서지만 단위당 값은 판단이 선다. "
              "수집 글에 없는 사정은 확인할 방법이 없으니 추측하지 않는다."},
]


def _pick_principles(diag: dict) -> list:
    """진단 결과에 따라 이 콘텐츠에 필요한 원칙을 고른다 (원본 매핑 유지)."""
    yes = {a["key"] for a in diag["answers"] if a["yes"]}
    picked = []
    if "one_second" not in yes:
        picked += [1, 2]
    if "what_is_that" not in yes:
        picked += [5, 6]
    if "sneezer" not in yes:
        picked += [7]
    if "no_discount" not in yes:
        picked += [8, 2]
    picked += [3, 4]
    if diag["score"] >= 3:
        picked = [3, 4, 6]
    seen, out = set(), []
    for n in picked:
        if n not in seen:
            seen.add(n)
            out.append(next(p for p in PRINCIPLES if p["n"] == n))
    return out[:5]


def build_script_guide(diag: dict, scene_level: bool = False) -> str:
    """대본 생성 프롬프트에 주입할 보랏빛소 지침.

    scene_level=True는 씬 하나 재생성용 — 전체 구성 규칙을 넣으면 모델이
    스토리보드를 통째로 다시 만들어 파싱이 깨진다(원본에서 실증된 실패)."""
    hooks = " / ".join(diag["hooks"][:3]) or "(데이터에서 뽑을 훅 없음)"
    principles = "\n".join(
        f"  원칙 {p['n']}. {p['name']} — {p['apply']}" for p in _pick_principles(diag)[:3])
    weak = "\n".join(f"  - {w}" for w in diag["weak"]) or "  - 없음"
    common = f"""[보랏빛소 진단] 점수 {diag['score']}/4 — {diag['verdict']}
보완할 약점:
{weak}
훅 후보(수집 데이터 원문): {hooks}
적용 원칙:
{principles}
표현 규칙: 수집 글에 있는 숫자만 사용. 원문 문장을 그대로 베끼지 말고 재구성.
{prompt_ban_list()}"""
    if scene_level:
        return common + """
[이번 출력 범위] 지금은 씬 하나만 다시 쓴다. 마크다운·씬 번호·설명 금지.
요구된 JSON 오브젝트 하나만 출력한다."""
    return common + """
[씬 구성] 훅 → 결론 요약 → 본문 챕터(씬마다 주제어 재기입) → 반전/단점 고백 → 행동 유도"""
```

- [ ] **Step 4: 테스트 통과 확인** — 기존 6개 + 신규 4개 전부 PASS (전체 스위트 1회)
- [ ] **Step 5: Commit**

```bash
git add server/core/purple_cow_blog.py server/tests/test_purple_cow_blog.py
git commit -m "feat(blog-reels): 보랏빛소 원칙 8종·지침 생성기 — weak/행정숫자 필터 포함"
```

---

### Task 4: Gemini 클라이언트 (REST + 모델 폴백)

**Files:**
- Modify: `server/core/config.py` (gemini_api_key 1줄)
- Create: `server/core/gemini.py`
- Modify: `.env.example` (GEMINI_API_KEY= 1줄)
- Test: `server/tests/test_gemini.py`

**Interfaces:**
- Produces: `MODEL_CHAIN = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-1.5-flash"]`, `generate(prompt: str, temperature: float = 0.8, max_tokens: int = 4096) -> str`(모델 체인 폴백, 전부 실패 시 `GeminiError`), `parse_json(text: str) -> object`(```json 펜스 제거 후 json.loads, 실패 시 첫 `[`/`{`부터 재시도), `available() -> bool`

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_gemini.py`:
```python
import httpx
import pytest
from core import gemini

def _resp(status, text="응답"):
    body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return httpx.Response(status, json=body if status == 200 else {"error": {}},
                          request=httpx.Request("POST", "u"))

def test_generate_falls_back_on_failure(monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "k")
    calls = []
    def fake_post(url, json=None, timeout=None):
        calls.append(url)
        return _resp(500) if len(calls) == 1 else _resp(200, "폴백 성공")
    monkeypatch.setattr(httpx, "post", fake_post)
    assert gemini.generate("p") == "폴백 성공"
    assert gemini.MODEL_CHAIN[0] in calls[0] and gemini.MODEL_CHAIN[1] in calls[1]

def test_generate_raises_when_all_fail(monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "k")
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None: _resp(500))
    with pytest.raises(gemini.GeminiError):
        gemini.generate("p")

def test_generate_without_key_raises(monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "")
    with pytest.raises(gemini.GeminiError):
        gemini.generate("p")

def test_parse_json_variants():
    assert gemini.parse_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert gemini.parse_json('앞말 [1, 2] 뒷말') == [1, 2]
    assert gemini.parse_json('{"b": 2}') == {"b": 2}
    with pytest.raises(ValueError):
        gemini.parse_json("json 없음")
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/config.py`의 Settings에 추가:
```python
    gemini_api_key = os.getenv("GEMINI_API_KEY", "")
```

`.env.example`에 추가:
```
GEMINI_API_KEY=
```

`server/core/gemini.py`:
```python
"""Gemini REST 클라이언트. SDK 없이 httpx 직접 호출, 모델 체인 폴백 (spec §7)."""
import json
import re

import httpx

from .config import settings

MODEL_CHAIN = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-1.5-flash"]
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


class GeminiError(RuntimeError):
    pass


def available() -> bool:
    return bool(settings.gemini_api_key)


def generate(prompt: str, temperature: float = 0.8, max_tokens: int = 4096) -> str:
    if not available():
        raise GeminiError("GEMINI_API_KEY 미설정")
    last = None
    for model in MODEL_CHAIN:
        try:
            r = httpx.post(
                _URL.format(model=model, key=settings.gemini_api_key),
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": temperature,
                                           "maxOutputTokens": max_tokens}},
                timeout=60)
            if r.status_code != 200:
                last = f"{model}: HTTP {r.status_code}"
                continue
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                return text
            last = f"{model}: 빈 응답"
        except Exception as e:
            last = f"{model}: {type(e).__name__}"
    raise GeminiError(f"모든 모델 실패 — {last}")


def parse_json(text: str):
    """모델 출력에서 JSON을 꺼낸다. ```json 펜스·앞뒤 잡담 허용."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.M)
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start = t.find(opener)
        end = t.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(t[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                continue
    raise ValueError("JSON을 찾지 못했다")
```

- [ ] **Step 4: 테스트 통과 확인** — Expected: 4 PASS (전체 1회)
- [ ] **Step 5: Commit**

```bash
git add server/core/config.py server/core/gemini.py server/tests/test_gemini.py .env.example
git commit -m "feat(blog-reels): Gemini REST 클라이언트 — 모델 체인 폴백·JSON 파서"
```

---

### Task 5: 씬 테이블·길이 배분 (storyboard)

**Files:**
- Create: `server/core/storyboard.py`
- Test: `server/tests/test_storyboard.py`

**Interfaces:**
- Produces: `PLAN: dict[tuple[str,int], int]` — {("reels",30):7, ("reels",60):13, ("long",60):10, ("long",180):24, ("long",300):38, ("long",600):72}. `CHAPTERS: dict[tuple[str,int], int]` — 롱폼 챕터 수 {("long",60):2, ("long",180):3, ("long",300):4, ("long",600):6}, 릴스는 0. `build_scenes(fmt: str, duration: int, chapter_titles: list[str]) -> list[dict]` — dict: `{idx, role, sec, chapter, caption, sub, narration, image_prompt}`(텍스트 필드는 "" 초기화). Task 7이 소비

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_storyboard.py`:
```python
import pytest
from core import storyboard as sb

@pytest.mark.parametrize("fmt,dur", [("reels", 30), ("reels", 60),
                                     ("long", 60), ("long", 180),
                                     ("long", 300), ("long", 600)])
def test_scene_count_and_total(fmt, dur):
    scenes = sb.build_scenes(fmt, dur, ["챕터A", "챕터B", "챕터C",
                                        "챕터D", "챕터E", "챕터F"])
    assert len(scenes) == sb.PLAN[(fmt, dur)]
    assert abs(sum(s["sec"] for s in scenes) - dur) < 0.5
    assert all(s["sec"] >= 2.2 for s in scenes)

def test_structure_order_reels():
    scenes = sb.build_scenes("reels", 30, [])
    roles = [s["role"] for s in scenes]
    assert roles[0] == "hook" and roles[1] == "summary"
    assert roles[-1] == "cta" and roles[-2] == "twist"
    assert set(roles[2:-2]) == {"point"}

def test_structure_long_has_chapters():
    scenes = sb.build_scenes("long", 180, ["기초", "실전", "주의점"])
    roles = [s["role"] for s in scenes]
    assert roles.count("chapter") == 3
    ch = [s for s in scenes if s["role"] == "chapter"]
    assert [c["caption"] for c in ch] == ["기초", "실전", "주의점"]
    first = roles.index("chapter")
    assert scenes[first + 1]["role"] == "point"
    pts = [s for s in scenes if s["role"] == "point"]
    assert all(p["chapter"] in ("기초", "실전", "주의점") for p in pts)

def test_chapter_titles_padded_when_missing():
    scenes = sb.build_scenes("long", 60, ["하나뿐"])
    ch = [s["caption"] for s in scenes if s["role"] == "chapter"]
    assert len(ch) == 2 and ch[0] == "하나뿐" and ch[1]

def test_unknown_plan_raises():
    with pytest.raises(KeyError):
        sb.build_scenes("long", 999, [])
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/storyboard.py`:
```python
"""씬 테이블과 길이 배분 (spec §9). EstateReels-v2 storyboard.ts의 이식.
구조는 항상 hook → summary → (chapter → point*)* → twist → cta."""

PLAN = {("reels", 30): 7, ("reels", 60): 13,
        ("long", 60): 10, ("long", 180): 24,
        ("long", 300): 38, ("long", 600): 72}

CHAPTERS = {("long", 60): 2, ("long", 180): 3,
            ("long", 300): 4, ("long", 600): 6}

_WEIGHT = {"hook": 1.35, "cta": 1.45, "summary": 1.2, "chapter": 0.6,
           "point": 1.0, "twist": 1.0}
_MIN_SEC = 2.2


def _distribute(roles: list[str], total: int) -> list[float]:
    weights = [_WEIGHT[r] for r in roles]
    scale = total / sum(weights)
    secs = [max(_MIN_SEC, round(w * scale, 1)) for w in weights]
    secs[-1] = round(secs[-1] + (total - sum(secs)), 1)   # 오차는 cta가 흡수
    return secs


def build_scenes(fmt: str, duration: int, chapter_titles: list[str]) -> list[dict]:
    total = PLAN[(fmt, duration)]                          # 미지원 조합은 KeyError
    n_ch = CHAPTERS.get((fmt, duration), 0)
    titles = list(chapter_titles[:n_ch])
    while len(titles) < n_ch:
        titles.append(f"포인트 {len(titles) + 1}")

    roles: list[tuple[str, str]] = [("hook", ""), ("summary", "")]
    n_points = total - 4 - n_ch                            # hook+summary+twist+cta=4
    if n_ch:
        base, extra = divmod(n_points, n_ch)
        for i, t in enumerate(titles):
            roles.append(("chapter", t))
            for _ in range(base + (1 if i < extra else 0)):
                roles.append(("point", t))
    else:
        roles += [("point", "")] * n_points
    roles += [("twist", ""), ("cta", "")]

    secs = _distribute([r for r, _ in roles], duration)
    return [{"idx": i, "role": r, "sec": secs[i], "chapter": ch,
             "caption": (ch if r == "chapter" else ""), "sub": "",
             "narration": "", "image_prompt": ""}
            for i, (r, ch) in enumerate(roles)]
```

- [ ] **Step 4: 테스트 통과 확인** — Expected: 전부 PASS (전체 1회)
- [ ] **Step 5: Commit**

```bash
git add server/core/storyboard.py server/tests/test_storyboard.py
git commit -m "feat(blog-reels): 씬 테이블·길이 배분 — 릴스 2종+롱폼 4종·챕터 구조"
```

---

### Task 6: 분석 계층 (팩트 시트 + 챕터 추출)

**Files:**
- Create: `server/core/analysis.py`
- Test: `server/tests/test_analysis.py`

**Interfaces:**
- Consumes: `purple_cow_blog.extract_numbers`, `gemini.generate/parse_json/available`
- Produces: `build_fact_sheet(posts: list[dict]) -> list[dict]` — `{fact, source_title, source_url}`(숫자 포함 줄만, 중복 제거, 최대 40개). `corpus_text(posts) -> str`(본문 연결 — guardrails context용). `extract_chapters(posts, n: int) -> list[str]` — Gemini로 챕터 n개, 실패·키 없음 시 규칙 폴백(제목 상위 토큰). Task 7이 소비

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_analysis.py`:
```python
from core import analysis

POSTS = [
    {"title": "전세 보증보험 총정리", "url": "https://a/1",
     "content": "보증료는 연 0.128%다.\n숫자 없는 줄.\n한도는 7억원이다."},
    {"title": "보증보험 가입법", "url": "https://a/2",
     "content": "보증료는 연 0.128%다.\n서류는 3가지다."},
]

def test_fact_sheet_numeric_lines_only_dedup():
    facts = analysis.build_fact_sheet(POSTS)
    texts = [f["fact"] for f in facts]
    assert "보증료는 연 0.128%다." in texts
    assert "숫자 없는 줄." not in texts
    assert texts.count("보증료는 연 0.128%다.") == 1        # 중복 제거
    assert all(f["source_url"] for f in facts)

def test_corpus_text_joins_all():
    c = analysis.corpus_text(POSTS)
    assert "0.128%" in c and "서류는 3가지다" in c

def test_extract_chapters_uses_gemini(monkeypatch):
    monkeypatch.setattr(analysis.gemini, "available", lambda: True)
    monkeypatch.setattr(analysis.gemini, "generate",
                        lambda p, **kw: '["기초", "가입 절차", "주의점"]')
    assert analysis.extract_chapters(POSTS, 3) == ["기초", "가입 절차", "주의점"]

def test_extract_chapters_fallback_without_gemini(monkeypatch):
    monkeypatch.setattr(analysis.gemini, "available", lambda: False)
    ch = analysis.extract_chapters(POSTS, 2)
    assert len(ch) == 2 and all(isinstance(c, str) and c for c in ch)

def test_extract_chapters_pads_short_answer(monkeypatch):
    monkeypatch.setattr(analysis.gemini, "available", lambda: True)
    monkeypatch.setattr(analysis.gemini, "generate", lambda p, **kw: '["하나"]')
    assert len(analysis.extract_chapters(POSTS, 3)) == 3
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/analysis.py`:
```python
"""선택 글들의 분석 계층 — 팩트 시트(숫자 문장)와 챕터 후보.
팩트 시트는 대본 프롬프트의 '사용 가능한 숫자' 전부이고,
corpus_text는 guardrails 숫자 대조의 context다."""
import re
from collections import Counter

from . import gemini
from .purple_cow_blog import extract_numbers


def corpus_text(posts: list[dict]) -> str:
    return "\n".join((p.get("content") or p.get("summary") or "") for p in posts)


def build_fact_sheet(posts: list[dict], limit: int = 40) -> list[dict]:
    facts, seen = [], set()
    for p in posts:
        for line in (p.get("content") or "").splitlines():
            line = line.strip()
            if not line or line in seen or not extract_numbers(line):
                continue
            seen.add(line)
            facts.append({"fact": line, "source_title": p.get("title", ""),
                          "source_url": p.get("url", "")})
            if len(facts) >= limit:
                return facts
    return facts


def _fallback_chapters(posts: list[dict], n: int) -> list[str]:
    tokens = Counter()
    for p in posts:
        for t in re.split(r"[^\w가-힣]+", p.get("title", "")):
            if len(t) >= 2:
                tokens[t] += 1
    top = [t for t, _ in tokens.most_common(n)]
    while len(top) < n:
        top.append(f"포인트 {len(top) + 1}")
    return top[:n]


def extract_chapters(posts: list[dict], n: int) -> list[str]:
    if n <= 0:
        return []
    if not gemini.available():
        return _fallback_chapters(posts, n)
    titles = "\n".join(f"- {p.get('title', '')}" for p in posts)
    body = corpus_text(posts)[:4000]
    try:
        raw = gemini.generate(
            f"다음 블로그 글들을 종합해 영상 챕터 제목 {n}개를 만들어라.\n"
            f"[글 제목들]\n{titles}\n[본문 발췌]\n{body}\n"
            f'짧은 한국어 명사구 {n}개의 JSON 배열만 출력: ["...", ...]',
            temperature=0.4, max_tokens=512)
        ch = [str(c).strip() for c in gemini.parse_json(raw) if str(c).strip()]
    except Exception:
        return _fallback_chapters(posts, n)
    ch = ch[:n]
    while len(ch) < n:
        ch.append(f"포인트 {len(ch) + 1}")
    return ch
```

- [ ] **Step 4: 테스트 통과 확인** — Expected: 5 PASS (전체 1회)
- [ ] **Step 5: Commit**

```bash
git add server/core/analysis.py server/tests/test_analysis.py
git commit -m "feat(blog-reels): 분석 계층 — 팩트 시트·코퍼스·챕터 추출(Gemini+폴백)"
```

---

### Task 7: 대본 엔진 (script_gen) + scripts 테이블

**Files:**
- Modify: `server/core/db.py` (scripts 테이블 추가)
- Create: `server/core/script_gen.py`
- Test: `server/tests/test_script_gen.py`

**Interfaces:**
- Consumes: `analysis.*`, `storyboard.build_scenes/CHAPTERS`, `purple_cow_blog.diagnose/build_script_guide`, `guardrails.check/check_copy`, `gemini.generate/parse_json`
- Produces: DB `scripts(id, category_id, post_ids_json, fmt, duration_sec, analysis_json, scenes_json, description_md, created_at)`. `generate_script(posts: list[dict], fmt: str, duration: int) -> dict{scenes, fact_sheet, diag, chapters}` · `regen_scene(scene: dict, posts: list[dict], diag: dict) -> dict`(scene_level 단일 씬 재생성+게이트, 실패 시 원본 유지) · `SAFE_NARRATION = "자세한 조건은 설명란의 원문에서 확인하세요."` — Task 8 API가 소비

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_script_gen.py`:
```python
import json
from core import script_gen, storyboard

POSTS = [
    {"title": "전세 보증보험 총정리", "url": "https://a/1", "source": "naver",
     "summary": "",
     "content": "보증료는 연 0.128%다.\n3억이면 연 38만원이다.\n"
                "하지만 사실 집주인 동의는 필요 없다.\n1. 서류\n2. 신청\n3. 납부"},
]

def _fake_scene(caption="보증료 연 0.128%", narration="보증료는 연 0.128%입니다"):
    return {"caption": caption, "sub": "", "narration": narration,
            "image_prompt": "insurance document illustration"}

def _gen_ok(prompt, **kw):
    # 프레임/챕터 호출 모두 요청된 씬 수만큼 유효 씬 반환
    want = prompt.count('"idx"')
    return json.dumps([_fake_scene() for _ in range(max(want, 1))],
                      ensure_ascii=False)

def test_generate_script_fills_all_scenes(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(script_gen.gemini, "generate", _gen_ok)
    out = script_gen.generate_script(POSTS, "reels", 30)
    scenes = out["scenes"]
    assert len(scenes) == storyboard.PLAN[("reels", 30)]
    body = [s for s in scenes if s["role"] != "chapter"]
    assert all(s["caption"] and s["narration"] for s in body)
    assert all(len(s["caption"]) <= 18 and len(s["sub"]) <= 22 for s in scenes)

def test_gate_rejects_fabricated_then_safe_fallback(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    def bad_gen(prompt, **kw):
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene(narration="가입자의 92%가 만족했습니다")
                           for _ in range(max(want, 1))], ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", bad_gen)
    out = script_gen.generate_script(POSTS, "reels", 30)
    narrs = [s["narration"] for s in out["scenes"] if s["role"] != "chapter"]
    assert all("92" not in n for n in narrs)          # 날조 숫자는 절대 통과 못 함
    assert any(n == script_gen.SAFE_NARRATION for n in narrs)

def test_gate_rejects_copied_sentence(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    copied = "하지만 사실 집주인 동의는 필요 없다"     # 원문 15자+ 그대로
    def copy_gen(prompt, **kw):
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene(narration=copied)
                           for _ in range(max(want, 1))], ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", copy_gen)
    out = script_gen.generate_script(POSTS, "reels", 30)
    assert all(copied not in s["narration"] for s in out["scenes"])

def test_caption_over_18_truncated(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    long_cap = "가나다라마바사아자차카타파하가나다라마바"   # 20자
    monkeypatch.setattr(script_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(
                            [_fake_scene(caption=long_cap)
                             for _ in range(max(p.count('"idx"'), 1))],
                            ensure_ascii=False))
    out = script_gen.generate_script(POSTS, "reels", 30)
    assert all(len(s["caption"]) <= 18 for s in out["scenes"])

def test_regen_scene_single(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(script_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(_fake_scene(), ensure_ascii=False))
    diag = script_gen.purple_cow_blog.diagnose(POSTS[0], [])
    scene = {"idx": 2, "role": "point", "sec": 4.0, "chapter": "",
             "caption": "옛 자막", "sub": "", "narration": "옛 나레이션",
             "image_prompt": ""}
    new = script_gen.regen_scene(scene, POSTS, diag)
    assert new["caption"] == "보증료 연 0.128%" and new["idx"] == 2

def test_scripts_table_exists(db):
    names = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "scripts" in names
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/db.py`의 SCHEMA 끝에 추가:
```sql
CREATE TABLE IF NOT EXISTS scripts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  post_ids_json TEXT NOT NULL,
  fmt TEXT NOT NULL CHECK(fmt IN('reels','long')),
  duration_sec INTEGER NOT NULL,
  analysis_json TEXT NOT NULL,
  scenes_json TEXT NOT NULL,
  description_md TEXT DEFAULT '',
  created_at TEXT
);
```

`server/core/script_gen.py`:
```python
"""대본 엔진 (spec §7). 흐름:
  진단 → 팩트 시트 → 챕터 → 씬 테이블 → Gemini 배치 생성(프레임 1회 + 챕터별 1회)
  → 씬 단위 게이트(guardrails+금지어+복사+길이) → 위반 씬 scene_level 재생성 ≤3회
  → 최종 실패 시 숫자 없는 안전 문구."""
import json

from . import analysis, gemini, guardrails, purple_cow_blog, storyboard

SAFE_NARRATION = "자세한 조건은 설명란의 원문에서 확인하세요."
MAX_REGEN = 3

_SCENE_JSON = ('{"idx": %d, "caption": "≤18자 자막", "sub": "≤22자 보조(없으면 빈칸)", '
               '"narration": "나레이션(자막을 그대로 읽지 말 것)", '
               '"image_prompt": "english image prompt, no text"}')


def _merged_post(posts: list[dict]) -> dict:
    """진단은 대표 1건 형태를 받으므로 선택 글을 합쳐 하나로 만든다."""
    return {"title": posts[0].get("title", ""), "source": posts[0].get("source", ""),
            "summary": " ".join(p.get("summary", "") for p in posts),
            "content": analysis.corpus_text(posts)}


def _batch_prompt(guide: str, facts: list[dict], scenes: list[dict],
                  label: str) -> str:
    fact_lines = "\n".join(f"- {f['fact']}" for f in facts)
    scene_specs = "\n".join(
        _SCENE_JSON % s["idx"] +
        f"  ← 역할 {s['role']}" + (f", 챕터 '{s['chapter']}'" if s["chapter"] else "")
        for s in scenes)
    return f"""{guide}

[팩트 시트] — 아래 문장의 숫자만 사용할 수 있다. 여기 없는 숫자는 절대 쓰지 마라.
{fact_lines}

[GEO 규칙] 씬마다 주제어를 명시적으로 다시 쓴다. "이 방법"·"그것"·"위에서 말한" 금지.
각 씬은 앞뒤 씬 없이 단독으로 인용돼도 말이 되어야 한다.

[{label}] 아래 씬들을 채워라. 각 씬은 다음 JSON 형태이고, JSON 배열만 출력한다:
{scene_specs}"""


def _gate(scene: dict, corpus: str, sources: list[str]) -> list[str]:
    text = " ".join(x for x in (scene.get("caption"), scene.get("sub"),
                                scene.get("narration")) if x)
    problems = list(guardrails.check(text, corpus)["blocking"])
    problems += [f"원문 복사: {s}" for s in guardrails.check_copy(text, sources)]
    return problems


def _apply(scene: dict, gen: dict) -> None:
    scene["caption"] = (gen.get("caption") or "")[:18]
    scene["sub"] = (gen.get("sub") or "")[:22]
    scene["narration"] = gen.get("narration") or ""
    scene["image_prompt"] = gen.get("image_prompt") or ""


def _safe_fallback(scene: dict) -> None:
    scene["caption"] = scene["caption"][:18] or scene["chapter"][:18] or "핵심 정리"
    scene["sub"] = ""
    scene["narration"] = SAFE_NARRATION
    if not scene["image_prompt"]:
        scene["image_prompt"] = "clean minimal infographic background, no text"


def regen_scene(scene: dict, posts: list[dict], diag: dict) -> dict:
    """씬 하나를 scene_level 프롬프트로 다시 생성한다. 실패하면 원본 그대로."""
    guide = purple_cow_blog.build_script_guide(diag, scene_level=True)
    facts = analysis.build_fact_sheet(posts)
    corpus = analysis.corpus_text(posts)
    sources = [p.get("content") or "" for p in posts]
    prompt = _batch_prompt(guide, facts, [scene], "씬 재생성")
    out = dict(scene)
    try:
        gen = gemini.parse_json(gemini.generate(prompt, max_tokens=1024))
        if isinstance(gen, list):
            gen = gen[0]
        cand = dict(scene)
        _apply(cand, gen)
        if not _gate(cand, corpus, sources):
            return cand
    except Exception:
        pass
    return out


def generate_script(posts: list[dict], fmt: str, duration: int) -> dict:
    diag = purple_cow_blog.diagnose(_merged_post(posts),
                                    [{"title": p.get("title", ""),
                                      "source": p.get("source", "")} for p in posts])
    facts = analysis.build_fact_sheet(posts)
    corpus = analysis.corpus_text(posts)
    sources = [p.get("content") or "" for p in posts]
    n_ch = storyboard.CHAPTERS.get((fmt, duration), 0)
    chapters = analysis.extract_chapters(posts, n_ch) if n_ch else []
    scenes = storyboard.build_scenes(fmt, duration, chapters)
    guide = purple_cow_blog.build_script_guide(diag, scene_level=False)

    # 배치 구성: 릴스=전체 1회 / 롱폼=프레임(hook·summary·twist·cta) 1회 + 챕터별 1회
    fill = [s for s in scenes if s["role"] != "chapter"]
    if fmt == "reels":
        batches = [("릴스 대본", fill)]
    else:
        frame = [s for s in fill if s["role"] in ("hook", "summary", "twist", "cta")]
        batches = [("프레임 씬", frame)]
        for ch in chapters:
            batches.append((f"챕터 '{ch}'",
                            [s for s in fill if s["role"] == "point"
                             and s["chapter"] == ch]))

    by_idx = {s["idx"]: s for s in scenes}
    for label, batch in batches:
        if not batch:
            continue
        try:
            gens = gemini.parse_json(
                gemini.generate(_batch_prompt(guide, facts, batch, label),
                                max_tokens=4096))
        except Exception:
            gens = []
        gen_by_idx = {g.get("idx"): g for g in gens if isinstance(g, dict)}
        for pos, s in enumerate(batch):
            g = gen_by_idx.get(s["idx"]) or (gens[pos] if pos < len(gens)
                                             and isinstance(gens[pos], dict) else {})
            _apply(s, g)

    # 씬 단위 게이트 + 재생성 루프
    for s in fill:
        tries = 0
        while _gate(s, corpus, sources) and tries < MAX_REGEN:
            tries += 1
            cand = regen_scene(s, posts, diag)
            if not _gate(cand, corpus, sources):
                by_idx[s["idx"]].update(cand)
                break
        if _gate(by_idx[s["idx"]], corpus, sources) or not s["narration"]:
            _safe_fallback(by_idx[s["idx"]])

    return {"scenes": scenes, "fact_sheet": facts, "diag": diag,
            "chapters": chapters}
```

주의(구현 세부): `test_gate_rejects_fabricated_then_safe_fallback`에서 regen도 같은 날조를 반환하므로 3회 후 `_safe_fallback`이 적용되어야 한다. `regen_scene`은 게이트 실패 시 원본을 반환하므로 루프가 안전 문구로 끝난다.

- [ ] **Step 4: 테스트 통과 확인** — Expected: 새 테스트 7개 + 기존 전부 PASS
- [ ] **Step 5: Commit**

```bash
git add server/core/db.py server/core/script_gen.py server/tests/test_script_gen.py
git commit -m "feat(blog-reels): 대본 엔진 — 배치 생성·씬 게이트·재생성 루프·안전 폴백"
```

---

### Task 8: GEO 설명란 + scripts API

**Files:**
- Create: `server/core/geo.py`
- Create: `server/api/scripts.py`
- Modify: `server/main.py` (라우터 등록 1줄)
- Test: `server/tests/test_geo.py`, `server/tests/test_scripts_api.py`

**Interfaces:**
- Consumes: Task 7 전부, `core.db.get_conn`
- Produces: `geo.build_description(scenes, chapters, posts, summary_lines) -> str`(요약 박스 3줄 + 챕터 타임스탬프 + 원문 출처). REST: `POST /api/scripts {category_id, post_ids:[int], fmt, duration}` → `{id}` · `GET /api/scripts/{sid}` → 전체(scenes·fact_sheet·description_md·diag) · `GET /api/categories/{cid}/scripts` → 목록 · `POST /api/scripts/{sid}/scenes/{idx}/regen` → 갱신된 씬 · `PATCH /api/scripts/{sid}/scenes/{idx} {caption?,sub?,narration?,image_prompt?}` → 갱신된 씬

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_geo.py`:
```python
from core import geo

SCENES = [
    {"idx": 0, "role": "hook", "sec": 4.1, "chapter": "", "caption": "훅"},
    {"idx": 1, "role": "summary", "sec": 3.6, "chapter": "", "caption": "요약"},
    {"idx": 2, "role": "chapter", "sec": 1.8, "chapter": "기초", "caption": "기초"},
    {"idx": 3, "role": "point", "sec": 3.0, "chapter": "기초", "caption": "p1"},
    {"idx": 4, "role": "chapter", "sec": 1.8, "chapter": "실전", "caption": "실전"},
    {"idx": 5, "role": "cta", "sec": 4.4, "chapter": "", "caption": "cta"},
]
POSTS = [{"title": "원문A", "url": "https://a/1"}]

def test_description_structure():
    d = geo.build_description(SCENES, ["기초", "실전"], POSTS,
                              ["요약 첫 줄이다.", "둘째 줄이다.", "셋째 줄이다."])
    assert d.startswith("■ 핵심 요약")
    assert "요약 첫 줄이다." in d
    assert "0:00" in d                       # 첫 챕터 타임스탬프
    assert "챕터" in d or "타임라인" in d
    assert "https://a/1" in d                # 출처

def test_timestamps_accumulate():
    d = geo.build_description(SCENES, ["기초", "실전"], POSTS, ["a.", "b.", "c."])
    # '실전' 챕터 시작 = 4.1+3.6+1.8+3.0 = 12.5 → 0:12
    assert "0:12 실전" in d
```

`server/tests/test_scripts_api.py`:
```python
import json
from fastapi.testclient import TestClient

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def _seed_posts(c, monkeypatch):
    import api.discover as disc
    items = [{"source": "naver", "title": "전세 보증보험 총정리",
              "url": "https://blog.naver.com/a/1", "summary": "보증료 0.128%",
              "blogger": "b", "posted_at": "20260810"}]
    monkeypatch.setattr(disc.naver, "search_blog", lambda q, display=10: items)
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: [])
    monkeypatch.setattr(disc.google_search, "available", lambda: True)
    monkeypatch.setattr(disc.crawler, "fetch_content",
                        lambda url: "보증료는 연 0.128%다.\n3억이면 연 38만원이다.")
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    return [p["id"] for p in c.get("/api/categories/1/posts").json()]

def _mock_engine(monkeypatch):
    import api.scripts as sc
    def fake_generate(posts, fmt, duration):
        from core import storyboard
        scenes = storyboard.build_scenes(fmt, duration, ["기초", "실전"])
        for s in scenes:
            if s["role"] != "chapter":
                s["caption"] = "보증료 0.128%"
                s["narration"] = "보증료는 연 0.128%입니다"
        return {"scenes": scenes, "fact_sheet": [], "chapters": ["기초", "실전"],
                "diag": {"score": 2, "verdict": "회색 소", "answers": [],
                         "hooks": [], "weak": []}}
    monkeypatch.setattr(sc.script_gen, "generate_script", fake_generate)
    return sc

def test_create_get_and_list(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    r = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                     "fmt": "long", "duration": 60})
    sid = r.json()["id"]
    got = c.get(f"/api/scripts/{sid}").json()
    assert len(got["scenes"]) == 10 and got["description_md"].startswith("■")
    lst = c.get("/api/categories/1/scripts").json()
    assert [s["id"] for s in lst] == [sid]

def test_patch_scene(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    sid = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                       "fmt": "reels", "duration": 30}).json()["id"]
    r = c.patch(f"/api/scripts/{sid}/scenes/0", json={"caption": "수정 자막"})
    assert r.json()["caption"] == "수정 자막"
    assert c.get(f"/api/scripts/{sid}").json()["scenes"][0]["caption"] == "수정 자막"

def test_regen_scene_endpoint(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    sc = _mock_engine(monkeypatch)
    sid = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                       "fmt": "reels", "duration": 30}).json()["id"]
    monkeypatch.setattr(sc.script_gen, "regen_scene",
                        lambda scene, posts, diag: {**scene, "caption": "재생성됨"})
    r = c.post(f"/api/scripts/{sid}/scenes/0/regen")
    assert r.json()["caption"] == "재생성됨"

def test_create_404_on_bad_posts(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    assert c.post("/api/scripts", json={"category_id": 1, "post_ids": [999],
                                        "fmt": "reels", "duration": 30}).status_code == 404
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/geo.py`:
```python
"""GEO 산출물 — 유튜브 설명란 (spec §7 GEO 3층 중 '설명란 자동 생성').
두괄식 요약 박스(객관 단정문 3줄) + 챕터 타임스탬프(h2 대응) + 원문 출처."""


def _ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def build_description(scenes: list[dict], chapters: list[str],
                      posts: list[dict], summary_lines: list[str]) -> str:
    lines = ["■ 핵심 요약"]
    lines += [f"- {s}" for s in summary_lines[:3]]
    if chapters:
        lines.append("")
        lines.append("⏱ 챕터")
        lines.append("0:00 인트로")            # 유튜브 챕터는 0:00부터 시작해야 인식된다
        t = 0.0
        marks = {}
        for s in scenes:
            if s["role"] == "chapter" and s["chapter"] not in marks:
                marks[s["chapter"]] = t
            t += s["sec"]
        for ch in chapters:
            if ch in marks:
                lines.append(f"{_ts(marks[ch])} {ch}")
    lines.append("")
    lines.append("📚 참고한 글")
    for p in posts:
        lines.append(f"- {p.get('title', '')} {p.get('url', '')}".rstrip())
    return "\n".join(lines)
```

`server/api/scripts.py`:
```python
import datetime, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.db import get_conn
from core import geo, script_gen

router = APIRouter(prefix="/api", tags=["scripts"])


class ScriptIn(BaseModel):
    category_id: int
    post_ids: list[int]
    fmt: str
    duration: int


class SceneEdit(BaseModel):
    caption: str | None = None
    sub: str | None = None
    narration: str | None = None
    image_prompt: str | None = None


def _load_posts(conn, post_ids: list[int]) -> list[dict]:
    if not post_ids:
        raise HTTPException(404, "선택된 글이 없다")
    rows = [dict(r) for r in conn.execute(
        f"SELECT * FROM posts WHERE id IN ({','.join('?' * len(post_ids))})",
        post_ids)]
    if len(rows) != len(set(post_ids)):
        raise HTTPException(404, "존재하지 않는 글이 포함돼 있다")
    return rows


def _row_to_script(row) -> dict:
    d = dict(row)
    d["scenes"] = json.loads(d.pop("scenes_json"))
    analysis_data = json.loads(d.pop("analysis_json"))
    d["fact_sheet"] = analysis_data.get("fact_sheet", [])
    d["diag"] = analysis_data.get("diag", {})
    d["chapters"] = analysis_data.get("chapters", [])
    d["post_ids"] = json.loads(d.pop("post_ids_json"))
    return d


@router.post("/scripts")
def create_script(body: ScriptIn):
    if (body.fmt, body.duration) not in (
            ("reels", 30), ("reels", 60), ("long", 60),
            ("long", 180), ("long", 300), ("long", 600)):
        raise HTTPException(422, "지원하지 않는 형식/길이")
    conn = get_conn()
    try:
        posts = _load_posts(conn, body.post_ids)
        out = script_gen.generate_script(posts, body.fmt, body.duration)
        summary_scene = next((s for s in out["scenes"] if s["role"] == "summary"), None)
        summary_lines = [x for x in (
            summary_scene and summary_scene.get("narration"),
            out["diag"].get("hooks", [None])[0] if out["diag"].get("hooks") else None,
            f"{len(posts)}개 상위 글을 종합해 재구성한 내용이다.",
        ) if x]
        desc = geo.build_description(out["scenes"], out["chapters"], posts,
                                     summary_lines)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        cur = conn.execute(
            """INSERT INTO scripts(category_id, post_ids_json, fmt, duration_sec,
               analysis_json, scenes_json, description_md, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (body.category_id, json.dumps(body.post_ids),
             body.fmt, body.duration,
             json.dumps({"fact_sheet": out["fact_sheet"], "diag": out["diag"],
                         "chapters": out["chapters"]}, ensure_ascii=False),
             json.dumps(out["scenes"], ensure_ascii=False), desc, now))
        conn.commit()
        return {"id": cur.lastrowid}
    finally:
        conn.close()


@router.get("/scripts/{sid}")
def get_script(sid: int):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "script not found")
        return _row_to_script(row)
    finally:
        conn.close()


@router.get("/categories/{cid}/scripts")
def list_scripts(cid: int):
    conn = get_conn()
    try:
        return [{"id": r["id"], "fmt": r["fmt"], "duration_sec": r["duration_sec"],
                 "created_at": r["created_at"]}
                for r in conn.execute(
                    "SELECT * FROM scripts WHERE category_id=? ORDER BY id DESC",
                    (cid,))]
    finally:
        conn.close()


def _update_scene(sid: int, idx: int, mutate) -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "script not found")
        scenes = json.loads(row["scenes_json"])
        target = next((s for s in scenes if s["idx"] == idx), None)
        if not target:
            raise HTTPException(404, "scene not found")
        analysis_data = json.loads(row["analysis_json"])
        posts = _load_posts(conn, json.loads(row["post_ids_json"]))
        mutate(target, posts, analysis_data.get("diag", {}))
        conn.execute("UPDATE scripts SET scenes_json=? WHERE id=?",
                     (json.dumps(scenes, ensure_ascii=False), sid))
        conn.commit()
        return target
    finally:
        conn.close()


@router.post("/scripts/{sid}/scenes/{idx}/regen")
def regen_scene_ep(sid: int, idx: int):
    def mutate(target, posts, diag):
        target.update(script_gen.regen_scene(target, posts, diag))
    return _update_scene(sid, idx, mutate)


@router.patch("/scripts/{sid}/scenes/{idx}")
def edit_scene(sid: int, idx: int, body: SceneEdit):
    def mutate(target, posts, diag):
        for k, v in body.model_dump(exclude_none=True).items():
            target[k] = v
    return _update_scene(sid, idx, mutate)
```

`server/main.py`에 추가:
```python
from api.scripts import router as scripts_router
app.include_router(scripts_router)
```

- [ ] **Step 4: 테스트 통과 확인** — Expected: 새 테스트 7개 + 기존 전부 PASS
- [ ] **Step 5: Commit**

```bash
git add server/core/geo.py server/api/scripts.py server/main.py server/tests/test_geo.py server/tests/test_scripts_api.py
git commit -m "feat(blog-reels): GEO 설명란 + scripts API — 생성·조회·씬 편집·재생성"
```

---

### Task 9: 스펙 편차 정리 + 시드 키워드 편집 UI

**Files:**
- Modify: `docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md` (§5 크롤 체인 서술 1곳)
- Modify: `web/src/api.ts` (deleteKeyword 추가)
- Modify: `web/src/pages/Dashboard.tsx` (키워드 추가/삭제 UI)

**Interfaces:**
- Consumes: M1 REST `POST/DELETE /api/categories/{cid}/keywords`
- Produces: 스펙 §5가 구현(httpx 모바일 변환→trafilatura→jina)과 일치. Dashboard 카드에서 시드 키워드 추가·삭제 가능 (spec §2 "UI에서 시드 편집 가능" 충족)

- [ ] **Step 1: 스펙 문서 수정**

`docs/.../2026-08-15-blog-reels-maker-design.md` §5의
```
- 본문 크롤링은 EstateReels-v2 `blogImport.ts` 폴백 체인을 서버로 이식:
  로컬 Playwright → jina 리더 → allorigins. 네이버 블로그는 iframe 본문(PostView) 처리,
```
를 다음으로 교체 (M1 구현 확정 반영):
```
- 본문 크롤링 폴백 체인(M1 구현 확정): 네이버는 모바일 변환(m.blog) 후 httpx 직접
  추출(se-main-container/postViewArea), 일반 URL은 trafilatura, 실패·80자 미만이면
  jina 리더. 네이버 블로그 구형 PostView 쿼리 URL도 지원.
```

- [ ] **Step 2: 프론트 구현**

`web/src/api.ts`에 추가:
```ts
export const deleteKeyword = (cid: number, keyword: string) =>
  fetch(`/api/categories/${cid}/keywords/${encodeURIComponent(keyword)}`,
    { method: 'DELETE' }).then(r => j<{ ok: boolean }>(r))
```

`web/src/pages/Dashboard.tsx` — import에 `addKeyword, deleteKeyword` 추가하고, 카드의 `.chips` 블록을 다음으로 교체 (키워드 chip에 × 버튼, 카드 하단에 키워드 추가 입력):
```tsx
            <div className="chips">
              {(c.top_keywords.length ? c.top_keywords
                : c.keywords.slice(0, 5).map(k => ({ keyword: k, rise_pct: 0 })))
                .map(t => (
                  <span className="chip" key={t.keyword}>
                    {t.keyword}
                    {t.rise_pct !== 0 &&
                      <em className={t.rise_pct > 0 ? 'up' : 'down'}>
                        {t.rise_pct > 0 ? '▲' : '▼'}{Math.abs(t.rise_pct)}%
                      </em>}
                    <button className="x" title="시드에서 삭제"
                            onClick={async () => {
                              await deleteKeyword(c.id, t.keyword); load()
                            }}>×</button>
                  </span>
                ))}
            </div>
            <div className="add-row">
              <input placeholder="시드 키워드 추가"
                     value={kwDraft[c.id] ?? ''}
                     onChange={e => setKwDraft({ ...kwDraft, [c.id]: e.target.value })} />
              <button className="ghost" onClick={async () => {
                const kw = (kwDraft[c.id] ?? '').trim()
                if (!kw) return
                await addKeyword(c.id, kw)
                setKwDraft({ ...kwDraft, [c.id]: '' }); load()
              }}>+</button>
            </div>
```
컴포넌트 상단에 상태 추가:
```tsx
  const [kwDraft, setKwDraft] = useState<Record<number, string>>({})
```
`web/src/index.css`에 추가:
```css
.chip .x { background: none; border: 0; color: #9aa0ae; margin-left: 4px;
           padding: 0 2px; font-size: 12px; cursor: pointer; }
.chip .x:hover { color: #f87171; }
```

- [ ] **Step 3: 검증**

Run: `cd web; npm run build` — 통과 필수. 서버 pytest 전체 1회.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md web/src/api.ts web/src/pages/Dashboard.tsx web/src/index.css
git commit -m "feat(blog-reels): 시드 키워드 편집 UI 배선 + 스펙 크롤 체인 서술 동기화"
```

---

### Task 10: 스토리보드 UI + README

**Files:**
- Modify: `web/src/api.ts` (Script 타입·스크립트 API 헬퍼)
- Modify: `web/src/pages/PostList.tsx` (글 선택 체크박스 + 대본 만들기 바)
- Create: `web/src/pages/Storyboard.tsx`
- Modify: `web/src/App.tsx` (라우트 1줄)
- Modify: `README.md` (M2 실행법)

**Interfaces:**
- Consumes: Task 8 REST 전부
- Produces: `/script/:id` 페이지 — 씬 테이블(역할·초·자막·나레이션 인라인 편집·씬 재생성 버튼), GEO 설명란 textarea+복사 버튼, 보랏빛 진단 요약. PostList에서 글 체크 → 형식(릴스 30/60·롱폼 1/3/5/10분) 선택 → 생성 → 이동

- [ ] **Step 1: 구현**

`web/src/api.ts`에 추가:
```ts
export interface Scene {
  idx: number; role: string; sec: number; chapter: string
  caption: string; sub: string; narration: string; image_prompt: string
}
export interface Script {
  id: number; category_id: number; fmt: string; duration_sec: number
  scenes: Scene[]; description_md: string; post_ids: number[]
  chapters: string[]; diag: { score: number; verdict: string; hooks: string[] }
  fact_sheet: { fact: string; source_title: string; source_url: string }[]
}
export const createScript = (category_id: number, post_ids: number[],
                             fmt: string, duration: number) =>
  fetch('/api/scripts', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category_id, post_ids, fmt, duration }) })
    .then(r => j<{ id: number }>(r))
export const getScript = (id: number) =>
  fetch(`/api/scripts/${id}`).then(r => j<Script>(r))
export const patchScene = (sid: number, idx: number, body: Partial<Scene>) =>
  fetch(`/api/scripts/${sid}/scenes/${idx}`, { method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }).then(r => j<Scene>(r))
export const regenScene = (sid: number, idx: number) =>
  fetch(`/api/scripts/${sid}/scenes/${idx}/regen`, { method: 'POST' })
    .then(r => j<Scene>(r))
```

`web/src/pages/PostList.tsx` — 변경점만:
- import에 `useNavigate`(react-router-dom), `createScript` 추가, 상태 추가:
```tsx
  const [picked, setPicked] = useState<number[]>([])
  const [fmt, setFmt] = useState<'reels' | 'long'>('reels')
  const [dur, setDur] = useState(30)
  const [making, setMaking] = useState(false)
  const nav = useNavigate()
```
- 각 `.post` 카드 맨 앞(PurpleBadge 앞)에 체크박스:
```tsx
          <input type="checkbox" checked={picked.includes(p.id)}
                 onChange={e => setPicked(e.target.checked
                   ? [...picked, p.id] : picked.filter(x => x !== p.id))} />
```
- 목록 위(tabs 아래)에 대본 만들기 바:
```tsx
      {picked.length > 0 && (
        <div className="make-bar">
          <b>{picked.length}개 선택</b>
          <select value={`${fmt}:${dur}`} onChange={e => {
            const [f, d] = e.target.value.split(':')
            setFmt(f as 'reels' | 'long'); setDur(Number(d))
          }}>
            <option value="reels:30">릴스 30초</option>
            <option value="reels:60">릴스 60초</option>
            <option value="long:60">롱폼 1분</option>
            <option value="long:180">롱폼 3분</option>
            <option value="long:300">롱폼 5분</option>
            <option value="long:600">롱폼 10분</option>
          </select>
          <button disabled={making} onClick={async () => {
            setMaking(true)
            try {
              const { id } = await createScript(cid, picked, fmt, dur)
              nav(`/script/${id}`)
            } catch (e) { alert(`대본 생성 실패: ${e}`) }
            finally { setMaking(false) }
          }}>{making ? '생성 중… (수십 초)' : '🎬 대본 만들기'}</button>
        </div>
      )}
```

`web/src/pages/Storyboard.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Scene, type Script, getScript, patchScene, regenScene } from '../api'

const ROLE_LABEL: Record<string, string> = {
  hook: '훅', summary: '요약', chapter: '챕터', point: '포인트',
  twist: '반전', cta: 'CTA',
}

export default function Storyboard() {
  const { id } = useParams()
  const sid = Number(id)
  const [script, setScript] = useState<Script | null>(null)
  const [busy, setBusy] = useState<number | null>(null)

  useEffect(() => { getScript(sid).then(setScript).catch(e => alert(e)) }, [sid])
  if (!script) return <div className="page">불러오는 중…</div>

  const save = async (idx: number, patch: Partial<Scene>) => {
    const s = await patchScene(sid, idx, patch)
    setScript({ ...script, scenes: script.scenes.map(x => x.idx === idx ? s : x) })
  }
  const regen = async (idx: number) => {
    setBusy(idx)
    try {
      const s = await regenScene(sid, idx)
      setScript({ ...script, scenes: script.scenes.map(x => x.idx === idx ? s : x) })
    } catch (e) { alert(`재생성 실패: ${e}`) }
    finally { setBusy(null) }
  }

  return (
    <div className="page">
      <h1><Link to={`/category/${script.category_id}`}>←</Link> 스토리보드
        <span className="meta">{script.fmt === 'reels' ? '릴스' : '롱폼'} ·
          {' '}{script.duration_sec}초 · 진단 {script.diag.score}/4 {script.diag.verdict}</span>
      </h1>
      {script.scenes.map(s => (
        <div className={`scene role-${s.role}`} key={s.idx}>
          <div className="scene-head">
            <span>#{s.idx} {ROLE_LABEL[s.role] ?? s.role}
              {s.chapter && s.role !== 'chapter' ? ` · ${s.chapter}` : ''}</span>
            <span>{s.sec}s</span>
            {s.role !== 'chapter' &&
              <button className="ghost" disabled={busy !== null}
                      onClick={() => regen(s.idx)}>
                {busy === s.idx ? '재생성 중…' : '♻ AI 재생성'}
              </button>}
          </div>
          <input defaultValue={s.caption} maxLength={18} placeholder="자막(≤18자)"
                 onBlur={e => e.target.value !== s.caption &&
                   save(s.idx, { caption: e.target.value })} />
          <textarea defaultValue={s.narration} placeholder="나레이션" rows={2}
                    onBlur={e => e.target.value !== s.narration &&
                      save(s.idx, { narration: e.target.value })} />
        </div>
      ))}
      <h2>📋 유튜브 설명란 (GEO)</h2>
      <textarea className="desc" readOnly value={script.description_md} rows={10} />
      <button onClick={() => navigator.clipboard.writeText(script.description_md)}>
        복사
      </button>
    </div>
  )
}
```

`web/src/App.tsx` — import + 라우트 추가:
```tsx
import Storyboard from './pages/Storyboard'
// Routes 안에:
        <Route path="/script/:id" element={<Storyboard />} />
```

`web/src/index.css`에 추가:
```css
.meta { font-size: 13px; color: #9aa0ae; margin-left: 10px; font-weight: 400; }
.make-bar { display: flex; gap: 10px; align-items: center; background: #171a21;
            border: 1px solid #7c3aed; border-radius: 10px; padding: 10px 14px;
            margin: 12px 0; }
select { background: #171a21; color: #e6e6ea; border: 1px solid #262b36;
         border-radius: 8px; padding: 8px; }
.scene { background: #171a21; border: 1px solid #262b36; border-radius: 10px;
         padding: 10px 14px; margin-bottom: 8px; display: flex;
         flex-direction: column; gap: 6px; }
.scene.role-hook { border-left: 3px solid #f59e0b; }
.scene.role-summary { border-left: 3px solid #38bdf8; }
.scene.role-chapter { border-left: 3px solid #a78bfa; background: #1b1530; }
.scene.role-twist { border-left: 3px solid #f87171; }
.scene.role-cta { border-left: 3px solid #34d399; }
.scene-head { display: flex; gap: 10px; align-items: center; font-size: 13px;
              color: #9aa0ae; justify-content: space-between; }
.scene textarea, .desc { background: #0f1115; color: #e6e6ea;
    border: 1px solid #262b36; border-radius: 8px; padding: 8px 10px;
    font-size: 13px; font-family: inherit; resize: vertical; }
```

`README.md` 실행 섹션에 추가:
```markdown
### M2 — 대본 만들기

.env에 `GEMINI_API_KEY` 추가 필요(대본·챕터 생성). 키가 없으면 수집·진단까지만 동작.
블로그 리스트에서 글을 체크 → 형식 선택 → "대본 만들기" → 스토리보드에서
씬별 자막·나레이션 편집, AI 재생성, GEO 설명란 복사.
```

- [ ] **Step 2: 검증**

Run: `cd web; npm run build` 통과 + 서버 pytest 전체 1회 통과. 수동: 서버+웹 기동 후 curl로 5175 응답 확인, 프로세스 종료.

- [ ] **Step 3: Commit**

```bash
git add web/src/ README.md
git commit -m "feat(blog-reels): 스토리보드 UI — 글 선택·대본 생성·씬 편집·GEO 복사"
```

---

## M2 완료 기준 (spec §12 마일스톤 2)

- [ ] 리스트에서 글 3~5개 선택 → 릴스/롱폼 6가지 길이로 대본 생성
- [ ] 대본의 모든 숫자는 수집 글에 존재(파생 허용) — 날조 게이트 테스트로 보증
- [ ] 금지어·원문 복사·1인칭 사칭 차단, 실패 씬은 재생성→안전 문구
- [ ] 보랏빛소 진단(weak[] 포함)이 지침을 자동 결정, scene_level 재생성 동작
- [ ] GEO: 씬 자립성 프롬프트 규칙 + 설명란(요약 박스·챕터 타임스탬프·출처) 복사 가능
- [ ] 시드 키워드 UI 편집 가능, 스펙 §5 서술이 구현과 일치
- [ ] `pytest server/tests` 전부 통과 (Gemini 포함 외부 API 없이), `npm run build` 통과

M3(ComfyUI 이미지)는 M2 완료 후 별도 계획서로 작성한다 — ComfyUI 설치 경로·보유 체크포인트 확인 필요.
