# Ollama + Stable Diffusion 소재 생성 전환 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 광고 캡션과 카드 이미지 생성을 Gemini 에서 Ollama(gemma4) + 로컬 Stable Diffusion 으로 옮기고, 생성량을 하루 단위로 통제한다.

**Architecture:** `copy_engine` 에 `ollama` provider 를 한 갈래 더한다. 이미지는 `content/sd_backend.py` 를 새로 만들어 gemma4 가 쓴 영문 프롬프트로 SD WebUI 를 부르고, 품질 게이트를 통과한 타일만 쓴다. 한글은 전부 Pillow 가 찍는다. 소재 단위를 '발행 1건당 1장' 에서 '한 바퀴당 1장' 으로 바꾸고, 팬아웃 상한과 하루 예산으로 생성량을 묶는다. 기존 Gemini 경로는 `CARD_ENGINE`/`COPY_PROVIDER` 스위치로 남긴다.

**Tech Stack:** Python 3.14 · SQLite · Pillow · urllib(표준) · Ollama HTTP API(11434) · AUTOMATIC1111 SD WebUI API(7860) · pytest

**Spec:** `docs/superpowers/specs/2026-09-08-ollama-sd-image-pipeline-design.md`

## Global Constraints

- **Ollama·SD 호출은 반드시 Python 에서 명시적 UTF-8 로 한다.** PowerShell 로 부르면 한글이 mojibake 가 되어 브리프가 통째로 무시된다(실측). 요청은 `json.dumps(..., ensure_ascii=False).encode("utf-8")`, 헤더는 `Content-Type: application/json; charset=utf-8`, 응답은 `.decode("utf-8")`.
- **LLM 의 JSON 응답은 관대한 파서로 읽는다.** `format:"json"` 을 줘도 ` ```json ` 펜스로 감싸 오는 경우가 있다(실측).
- **인물·글자 금지 네거티브는 코드가 강제 주입한다.** LLM 출력에 맡기지 않는다.
- **흰 배경은 프롬프트가 아니라 게이트로 확인한다.** 프롬프트만 믿으면 4장 중 1장이 사진 배경으로 나온다(실측).
- **기존 Gemini 경로를 삭제하지 않는다.** 모든 신규 경로는 스위치 뒤에 둔다.
- **loan 프로필은 건드리지 않는다.**
- 확정 상수: `IMAGE_FANOUT_MAX=20` · 재고 목표는 `CREATIVE_COOLDOWN_DAYS`(=14)에서 유도 · `IMAGE_DAILY_BUDGET_SD=12` · `IMAGE_DAILY_BUDGET_GEMINI=2` · 체크포인트는 DreamShaper_8 유지.
- 테스트는 프로젝트 루트에서 `python -m pytest tests/<file> -v`. `tests/conftest.py` 가 루트를 `sys.path` 에 넣고 `temp_db` 픽스처를 제공한다. **실제 `data/autoad.db` 를 건드리는 테스트를 쓰지 않는다.**
- 새 외부 의존성 금지. `urllib.request` 로 충분하다.

## 이 계획 밖의 선행 조건 (운영자 작업)

코드가 아니다. **이것들이 안 되면 소재를 만들어도 나갈 곳이 없다.**

1. 낡은 사본(`D:\Antigravity 작업-2026 상반기\통합광고접수-AutoAd`)에서 도는 `service.py` 3종을 내리고 라이브 사본으로 갈아타기
2. PC 메모리 복구 — 가상메모리 확대, 크롬/크롬드라이버 정합, 고아 크롬 정리

---

### Task 1: 소재 경로 마이그레이션

DB 의 `creatives.image_path` 1,448건이 전부 옛 PC 경로를 가리켜 **실제 파일이 0건**이다. 발행 게이트가 "그림 파일 없으면 차단" 이라 이걸 안 고치면 대기 소재가 한 건도 못 나간다. 파일명은 1,448건 전부 현재 `data/creatives/` 에 존재한다(실측).

**Files:**
- Create: `tools/migrate_creative_paths.py`
- Test: `tests/test_migrate_creative_paths.py`

**Interfaces:**
- Consumes: 없음
- Produces: `migrate_creative_paths.remap(old_path: str, creatives_dir: Path) -> str | None` — 파일명만 떼어 새 폴더에 붙인다. 새 위치에 파일이 없으면 `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrate_creative_paths.py
# -*- coding: utf-8 -*-
"""옛 PC 경로를 현재 폴더로 옮긴다.

2026-09-08 실측: creatives.image_path 1,448건이 전부
C:\\Users\\Samsung\\OneDrive\\바탕 화면\\AutoAd_이사\\... 를 가리켜 실제 파일 0건.
파일명은 1,448건 모두 현재 data/creatives 에 있다 — 앞부분만 갈면 살아난다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import migrate_creative_paths as M


def test_remap_uses_basename(tmp_path):
    (tmp_path / "showcase_inkcraft_facebook_v0.png").write_bytes(b"x")
    old = r"C:\Users\Samsung\OneDrive\바탕 화면\AutoAd_이사\통합광고접수-AutoAd\data\creatives\showcase_inkcraft_facebook_v0.png"
    assert M.remap(old, tmp_path) == str(tmp_path / "showcase_inkcraft_facebook_v0.png")


def test_remap_returns_none_when_file_missing(tmp_path):
    old = r"C:\Users\Samsung\OneDrive\바탕 화면\없는파일.png"
    assert M.remap(old, tmp_path) is None


def test_remap_handles_posix_separators(tmp_path):
    """옛 경로가 / 로 저장돼 있어도 파일명을 뽑아야 한다."""
    (tmp_path / "doc_mirizip_band_v3.png").write_bytes(b"x")
    old = "C:/Users/Samsung/OneDrive/AutoAd_이사/data/creatives/doc_mirizip_band_v3.png"
    assert M.remap(old, tmp_path) == str(tmp_path / "doc_mirizip_band_v3.png")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_migrate_creative_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'migrate_creative_paths'`

- [ ] **Step 3: Write minimal implementation**

```python
# tools/migrate_creative_paths.py
# -*- coding: utf-8 -*-
"""creatives.image_path 를 현재 폴더로 옮긴다.

⚠ 옛 경로는 백슬래시(윈도우)로도, 슬래시로도 저장돼 있을 수 있다.
  ntpath 를 쓰지 않고 두 구분자를 모두 자른다 — 리눅스에서 돌려도 같은 결과.
⚠ 새 위치에 파일이 없으면 None 을 돌려주고 **그 행은 건드리지 않는다.**
  없는 경로로 덮어쓰면 원래 경로 정보까지 잃는다.
"""
import io
import sys
import argparse
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))


def _utf8_stdout():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                      line_buffering=True)
    except Exception:
        pass


def remap(old_path: str, creatives_dir) -> str | None:
    name = str(old_path or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        return None
    new = Path(creatives_dir) / name
    return str(new) if new.is_file() else None


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 쓴다(없으면 점검만)")
    a = ap.parse_args()

    import config
    import db

    with db.get_conn() as con:
        rows = con.execute(
            "SELECT id, image_path FROM creatives "
            "WHERE COALESCE(image_path,'') <> ''").fetchall()

    hit = miss = same = 0
    for r in rows:
        old = r["image_path"]
        if Path(old).is_file():
            same += 1
            continue
        new = remap(old, config.CREATIVES_DIR)
        if new is None:
            miss += 1
            continue
        hit += 1
        if a.apply:
            with db.get_conn() as con:
                con.execute("UPDATE creatives SET image_path=? WHERE id=?",
                            (new, r["id"]))

    print(f"이미 정상 {same}건 · 옮길 수 있음 {hit}건 · 원본 없음 {miss}건")
    if not a.apply:
        print("점검만 했습니다. 실제로 쓰려면 --apply 를 붙이세요.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_migrate_creative_paths.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 점검 실행 — 아직 쓰지 않는다**

Run: `python tools/migrate_creative_paths.py`
Expected: `이미 정상 0건 · 옮길 수 있음 1448건 · 원본 없음 0건`

**옮길 수 있음이 1,448 이 아니면 멈추고 보고한다.** 숫자가 다르면 파일이 실제로 없다는 뜻이고, 덮어쓰면 원래 경로를 잃는다.

- [ ] **Step 6: Commit**

```bash
git add tools/migrate_creative_paths.py tests/test_migrate_creative_paths.py
git commit -m "feat(autoad): add creative image path migration tool"
```

---

### Task 2: Ollama 캡션 provider

**Files:**
- Modify: `config.py:104` 부근 (COPY_PROVIDER 주석) · 새 상수 추가
- Modify: `content/copy_engine.py:883` (`_call_llm` 디스패치) · 새 함수 2개
- Test: `tests/test_copy_ollama.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `config.OLLAMA_URL: str` (기본 `http://127.0.0.1:11434`)
  - `config.OLLAMA_MODEL: str` (기본 `gemma4:31b-cloud`)
  - `copy_engine._loads_loose(txt: str) -> dict`
  - `copy_engine._call_ollama(prompt: str) -> str` — 응답 본문 문자열을 그대로 반환(기존 `_call_gemini` 와 동일 계약)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_copy_ollama.py
# -*- coding: utf-8 -*-
"""Ollama provider — 한글 왕복과 코드펜스 파싱.

2026-09-08 스파이크에서 실제로 밟은 두 함정을 고정한다.
 1) PowerShell 로 부르면 한글이 mojibake 가 되어 브리프가 통째로 무시된다.
    ("AI 광고영상" 을 넣었는데 화장품 세럼 제품샷이 나왔다)
 2) format:"json" 을 줘도 ```json 펜스로 감싸 온다.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from content import copy_engine as C


def test_loads_loose_reads_bare_json():
    assert C._loads_loose('{"a": 1}') == {"a": 1}


def test_loads_loose_reads_fenced_json():
    """```json 펜스로 감싸 와도 읽어야 한다(실측)."""
    txt = '```json\n{"prompt": "abc", "negative_prompt": "def"}\n```'
    assert C._loads_loose(txt)["prompt"] == "abc"


def test_loads_loose_raises_on_garbage():
    import pytest
    with pytest.raises(json.JSONDecodeError):
        C._loads_loose("no json here")


def test_call_ollama_sends_utf8_korean(monkeypatch):
    """요청 본문이 UTF-8 이고, 한글이 깨지지 않아야 한다."""
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"response": '{"ok": "예"}'}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        seen["body"] = req.data
        seen["ctype"] = req.headers.get("Content-type", "")
        return _Resp()

    monkeypatch.setattr(C.urllib.request, "urlopen", fake_urlopen)
    out = C._call_ollama("광고 영상 서비스 브리프")

    body = json.loads(seen["body"].decode("utf-8"))
    assert "광고 영상 서비스 브리프" in body["prompt"]   # mojibake 회귀 방지
    assert body["format"] == "json"
    assert body["stream"] is False
    assert "utf-8" in seen["ctype"].lower()
    assert out == '{"ok": "예"}'


def test_call_llm_dispatches_to_ollama(monkeypatch):
    import config
    monkeypatch.setattr(config, "COPY_PROVIDER", "ollama")
    monkeypatch.setattr(C, "_call_ollama", lambda p: "OLLAMA")
    assert C._call_llm("x") == "OLLAMA"


def test_call_llm_still_defaults_to_gemini(monkeypatch):
    """회귀 방지 — 기존 동작이 그대로여야 한다."""
    import config
    monkeypatch.setattr(config, "COPY_PROVIDER", "gemini")
    monkeypatch.setattr(C, "_call_gemini", lambda p: "GEMINI")
    assert C._call_llm("x") == "GEMINI"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_copy_ollama.py -v`
Expected: FAIL — `AttributeError: module 'content.copy_engine' has no attribute '_loads_loose'`

- [ ] **Step 3: config 에 상수 추가**

`config.py` 의 `COPY_MODEL_GEMINI` 줄(105행) 바로 아래에 넣는다.

```python
# ── Ollama (로컬 데몬 → 클라우드 모델) ──────────────────────
#  ⚠ '-cloud' 접미사 모델은 Ollama 클라우드에서 돈다. 로컬 RAM/VRAM 을 쓰지 않아
#    이 PC(16GB, 크롬 3개 병렬)의 메모리 압박에 기여하지 않는다.
OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud").strip()
```

그리고 104행 `COPY_PROVIDER` 의 주석에 `ollama` 를 값으로 추가한다.

- [ ] **Step 4: copy_engine 에 함수 2개 + 디스패치**

`content/copy_engine.py` 상단 import 에 `import json, re, urllib.request` 가 없으면 추가하고, `_call_gemini`(864행) 아래에 넣는다.

```python
def _loads_loose(txt: str) -> dict:
    """LLM 의 JSON 응답을 관대하게 읽는다.

    ⚠ format:"json" 을 줘도 ```json 펜스로 감싸 오는 경우가 있다(2026-09-08 실측).
      그대로 json.loads 하면 터진다. 첫 { 부터 마지막 } 까지만 떼어 읽는다.
    """
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _call_ollama(prompt: str) -> str:
    """Ollama 로 캡션을 만든다. 반환은 응답 본문 문자열(기존 provider 와 같은 계약).

    ⚠ 인코딩을 명시하지 않으면 한글이 깨져 프롬프트가 통째로 무시된다.
      2026-09-08 스파이크에서 실제로 밟았다 — "AI 광고영상 서비스" 브리프를 넣었는데
      화장품 세럼 제품샷 프롬프트가 나왔다. 원인은 모델이 아니라 인코딩이었다.
    """
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.7},
    }
    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        body = json.loads(r.read().decode("utf-8"))
    return body.get("response", "")
```

`_call_llm`(883행)을 바꾼다.

```python
def _call_llm(prompt: str) -> str:
    if config.COPY_PROVIDER == "ollama":
        return _call_ollama(prompt)
    return _call_gemini(prompt) if config.COPY_PROVIDER == "gemini" else _call_claude(prompt)
```

`_require_key()`(844행)에 `ollama` 분기를 더한다 — **키가 필요 없으므로 그냥 통과시킨다.** 없으면 기존 코드가 Gemini 키를 요구해 막힌다.

```python
    if config.COPY_PROVIDER == "ollama":
        return          # 로컬 데몬. API 키 없음
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_copy_ollama.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 기존 테스트가 전부 그대로 통과

- [ ] **Step 7: Commit**

```bash
git add config.py content/copy_engine.py tests/test_copy_ollama.py
git commit -m "feat(autoad): add ollama caption provider with utf-8 and loose json parsing"
```

---

### Task 3: SD 백엔드 + 품질 게이트

**Files:**
- Create: `content/sd_backend.py`
- Modify: `config.py` (CARD_ENGINE·SD_* 상수)
- Test: `tests/test_sd_backend.py`

**Interfaces:**
- Consumes: `config.OLLAMA_URL` / `OLLAMA_MODEL` (Task 2), `copy_engine._loads_loose` (Task 2)
- Produces:
  - `config.CARD_ENGINE: str` (`"gemini"` | `"sd"`, 기본 `"gemini"`)
  - `config.SD_WEBUI_URL: str` · `config.SD_STEPS: int` · `config.SD_CFG: float` · `config.SD_SAMPLER: str`
  - `sd_backend.NEG_FORCE: str`
  - `sd_backend.build_prompt(brief: str, width: int, height: int) -> dict` — `{"prompt": str, "negative_prompt": str}`
  - `sd_backend.txt2img(prompt: str, negative: str, width: int, height: int) -> PIL.Image.Image`
  - `sd_backend.is_clean_white(img: PIL.Image.Image) -> bool`
  - `sd_backend.gen_tile(brief: str, size: int = 768, retries: int = 2) -> PIL.Image.Image`
  - `sd_backend.warmup() -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sd_backend.py
# -*- coding: utf-8 -*-
"""SD 백엔드 — 강제 네거티브와 흰 배경 게이트.

2026-09-08 스파이크 실측:
 · DreamShaper_8 은 인물 편향이 강하다. "노트북 화면" 을 요구했는데 인물 사진이
   나왔다 → 인물 금지 네거티브를 코드가 강제 주입해야 한다.
 · pure white background 를 넣고 photo background 를 네거티브에 넣어도
   4장 중 1장이 사진 배경으로 나왔다 → 프롬프트가 아니라 게이트로 확인한다.
"""
import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from content import sd_backend as S


def test_neg_force_bans_people_and_text():
    for word in ("person", "woman", "face", "hands",
                 "text", "korean text", "watermark", "logo"):
        assert word in S.NEG_FORCE


def test_build_prompt_always_appends_neg_force(monkeypatch):
    """모델이 인물 금지를 빠뜨려도 코드가 붙인다."""
    monkeypatch.setattr(S, "_ask_llm",
                        lambda brief, w, h: {"prompt": "a cat",
                                             "negative_prompt": "blurry"})
    out = S.build_prompt("고양이 스티커", 768, 768)
    assert out["prompt"] == "a cat"
    assert "blurry" in out["negative_prompt"]
    assert "person" in out["negative_prompt"]      # 강제 주입 확인


def test_is_clean_white_accepts_white_border():
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    for x in range(60, 140):
        for y in range(60, 140):
            img.putpixel((x, y), (10, 20, 30))     # 가운데만 그림
    assert S.is_clean_white(img) is True


def test_is_clean_white_rejects_photo_background():
    """스파이크의 수채 타일 사례 — 종이·팔레트가 찍힌 사진 배경."""
    img = Image.new("RGB", (200, 200), (120, 130, 110))
    assert S.is_clean_white(img) is False


def test_is_clean_white_rejects_dark_corners():
    """showcase._gen_one 주석이 경고한 비네트."""
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    for x in range(0, 30):
        for y in range(0, 30):
            img.putpixel((x, y), (20, 20, 20))
    assert S.is_clean_white(img) is False


def test_gen_tile_retries_until_gate_passes(monkeypatch):
    bad = Image.new("RGB", (64, 64), (100, 100, 100))
    good = Image.new("RGB", (64, 64), (255, 255, 255))
    calls = {"n": 0}

    def fake_txt2img(prompt, negative, width, height):
        calls["n"] += 1
        return bad if calls["n"] == 1 else good

    monkeypatch.setattr(S, "_ask_llm",
                        lambda brief, w, h: {"prompt": "p", "negative_prompt": "n"})
    monkeypatch.setattr(S, "txt2img", fake_txt2img)
    out = S.gen_tile("브리프", size=64, retries=2)
    assert calls["n"] == 2
    assert S.is_clean_white(out) is True


def test_gen_tile_gives_up_after_retries(monkeypatch):
    bad = Image.new("RGB", (64, 64), (100, 100, 100))
    monkeypatch.setattr(S, "_ask_llm",
                        lambda brief, w, h: {"prompt": "p", "negative_prompt": "n"})
    monkeypatch.setattr(S, "txt2img", lambda *a, **k: bad)
    import pytest
    with pytest.raises(RuntimeError, match="흰 배경"):
        S.gen_tile("브리프", size=64, retries=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sd_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'content.sd_backend'`

- [ ] **Step 3: config 에 상수 추가**

`config.py` 의 `CARD_MODEL`(110행) 아래에 넣는다.

```python
# ── 카드 이미지 엔진 ────────────────────────────────────────
#  "gemini" = 기존 유료 경로(gemini-3-pro-image)
#  "sd"     = 로컬 Stable Diffusion (AUTOMATIC1111 WebUI API)
#  ⚠ 기존 경로를 지우지 않는다. SD 품질이 안 맞으면 이 한 줄로 되돌아간다.
CARD_ENGINE  = os.getenv("CARD_ENGINE", "gemini").strip().lower()
SD_WEBUI_URL = os.getenv("SD_WEBUI_URL", "http://127.0.0.1:7860").rstrip("/")
SD_STEPS     = int(os.getenv("SD_STEPS", "28"))
SD_CFG       = float(os.getenv("SD_CFG", "7.5"))
SD_SAMPLER   = os.getenv("SD_SAMPLER", "DPM++ 2M").strip()
```

- [ ] **Step 4: `content/sd_backend.py` 작성**

```python
# -*- coding: utf-8 -*-
"""sd_backend.py — gemma4 가 쓴 영문 프롬프트로 로컬 SD 를 돌린다

왜 이렇게 나눴는가:
  SD 는 한글 글자를 못 그린다. 그래서 SD 에게는 '배경/도안' 만 맡기고
  한글은 Pillow 가 찍는다. 그 결과 AI 가 본문에 오타를 내던 문제
  ('상황'→'상형', '전문 컨설팅'→'전룬 건설형')가 구조적으로 사라진다.

2026-09-08 스파이크에서 밟은 함정 세 가지가 이 파일에 박혀 있다:
  · 인물 편향  — DreamShaper_8 은 무엇을 요구하든 인물로 끌고 간다.
                 NEG_FORCE 를 LLM 출력 뒤에 **항상** 덧붙인다.
  · 배경 불복  — "pure white background" 를 넣어도 사진 배경이 나온다.
                 프롬프트를 믿지 않고 is_clean_white 로 검사해 재시도한다.
  · 공간 지시  — SD1.5 는 "어디를 비워라" 를 못 지킨다. 여백은 여기서
                 해결하지 않는다. 호출부(Pillow)가 불투명 패널로 확보한다.
"""
import io
import json
import time
import base64
import urllib.request

from PIL import Image

import config
from content import copy_engine

# ⚠ LLM 이 무엇을 내놓든 코드가 뒤에 붙인다. 모델은 이걸 빠뜨릴 수 있고,
#   실제로 빠뜨려서 인물 사진이 나왔다.
NEG_FORCE = (
    "person, people, woman, man, face, portrait, human, hands, body, skin, "
    "text, letters, words, korean text, watermark, signature, typography, "
    "logo, caption, ui, numbers"
)

_PERSONA = """너는 세계 최고의 Stable Diffusion 프롬프트 엔지니어다.
아래 [브리프]를 읽고 SD1.5(DreamShaper)용 영어 프롬프트를 만든다.

⚠ 프롬프트의 주제는 반드시 [브리프]에서 나와야 한다. 일반적인 광고 이미지
  (화장품 제품샷·음식 사진 등)로 대체하지 마라.

반드시 포함할 요소:
1. 주제 및 동작 — 브리프를 시각화한 상세한 묘사
2. 배경 및 환경 — 빛의 각도, 분위기
3. 스타일 및 퀄리티 — photorealistic / digital art / flat illustration 등
4. 카메라·렌더 — wide angle, 85mm lens, depth of field, studio render 등
5. Negative Prompt — 퀄리티를 떨어뜨리는 요소

★ 이 이미지 위에는 한글 문구를 따로 얹는다. 그러므로:
(a) 이미지 안에 글자가 있으면 안 된다
(b) 사람·얼굴·손이 나오면 안 된다
(c) 지정된 화면 비율({w}x{h})에 맞는 구도로 만들어라
(d) 과장 광고 표현(폭발적 성장 그래프·트로피·1등 배지)을 넣지 마라

출력은 JSON 하나만:
{"prompt": "...", "negative_prompt": "..."}"""


def _ask_llm(brief: str, width: int, height: int) -> dict:
    """gemma4 에게 프롬프트를 받는다. 테스트에서 갈아끼우는 이음매다."""
    persona = _PERSONA.replace("{w}", str(width)).replace("{h}", str(height))
    raw = copy_engine._call_ollama(f"[브리프]\n{brief}\n\n---\n\n{persona}")
    return copy_engine._loads_loose(raw)


def build_prompt(brief: str, width: int, height: int) -> dict:
    d = _ask_llm(brief, width, height)
    neg = (d.get("negative_prompt") or "").strip()
    return {
        "prompt": (d.get("prompt") or "").strip(),
        "negative_prompt": (neg + ", " + NEG_FORCE) if neg else NEG_FORCE,
    }


def txt2img(prompt: str, negative: str, width: int, height: int) -> Image.Image:
    payload = {
        "prompt": prompt, "negative_prompt": negative,
        "width": width, "height": height,
        "steps": config.SD_STEPS, "cfg_scale": config.SD_CFG,
        "sampler_name": config.SD_SAMPLER, "scheduler": "Karras",
    }
    req = urllib.request.Request(
        f"{config.SD_WEBUI_URL}/sdapi/v1/txt2img",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as r:
        body = json.loads(r.read().decode("utf-8"))
    return Image.open(io.BytesIO(base64.b64decode(body["images"][0]))).convert("RGB")


def is_clean_white(img: Image.Image, thresh: int = 235, band: float = 0.06) -> bool:
    """테두리가 흰색인가. 아니면 배경 지시를 어긴 것이다.

    ⚠ 가운데를 보면 안 된다. 도안은 가운데 있어야 정상이다. 테두리만 본다.
    ⚠ 평균만 보면 한쪽 모서리만 검은 비네트를 놓친다 — 최솟값도 같이 본다.
    """
    g = img.convert("L")
    w, h = g.size
    bw = max(1, int(min(w, h) * band))
    px = g.load()
    vals = []
    for x in range(w):
        for y in range(bw):
            vals.append(px[x, y])
            vals.append(px[x, h - 1 - y])
    for y in range(h):
        for x in range(bw):
            vals.append(px[x, y])
            vals.append(px[w - 1 - x, y])
    if not vals:
        return False
    avg = sum(vals) / len(vals)
    return avg >= thresh and min(vals) >= thresh - 60


def gen_tile(brief: str, size: int = 768, retries: int = 2) -> Image.Image:
    """게이트를 통과한 타일 1장. 실패하면 RuntimeError.

    재시도 비용은 13초뿐이라(실측) 버리고 다시 뽑는 편이 싸다.
    """
    last = None
    for attempt in range(retries + 1):
        p = build_prompt(brief, size, size)
        img = txt2img(p["prompt"], p["negative_prompt"], size, size)
        if is_clean_white(img):
            return img
        last = img
        print(f"[sd] 흰 배경 게이트 실패 — 재시도 {attempt + 1}/{retries}")
    raise RuntimeError(f"흰 배경 타일을 {retries + 1}회 시도에도 못 만들었습니다")


def warmup() -> float:
    """첫 장 지연을 없앤다. 모델이 메모리에서 밀려나 있으면 첫 요청이 느리다.

    실측(2026-09-08): 10시간 유휴 뒤에도 5.3초였다. 그래도 배치 앞에 한 번 부른다.
    """
    t0 = time.time()
    try:
        txt2img("a plain white square", NEG_FORCE, 256, 256)
    except Exception as e:
        print(f"[sd] 예열 실패(무시): {type(e).__name__}: {e}")
    return time.time() - t0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_sd_backend.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: Commit**

```bash
git add config.py content/sd_backend.py tests/test_sd_backend.py
git commit -m "feat(autoad): add stable diffusion backend with white-background quality gate"
```

---

### Task 4: showcase 엔진 분기 + 칸 수 규격 유도

**Files:**
- Modify: `content/showcase.py:170` (`_gen_one`) · `:217`, `:240` (`SHOWCASE_TILES` 사용처)
- Test: `tests/test_showcase_engine.py`

**Interfaces:**
- Consumes: `sd_backend.gen_tile` (Task 3), `config.CARD_ENGINE` (Task 3)
- Produces: `showcase.tiles_for(platform: str) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_showcase_engine.py
# -*- coding: utf-8 -*-
"""칸 수는 채널 규격이 정하고, 생성 엔진은 스위치가 정한다.

격자 코드가 cols = min(n, 2) 라서 칸 수가 곧 결과물의 비율이다.
 2장 → 2x1 가로  (facebook 1200x630)
 4장 → 2x2 정사각 (band/kakao 1080x1080)
"""
import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from content import showcase as S


def test_tiles_for_landscape_channel_is_two():
    assert S.tiles_for("facebook") == 2


def test_tiles_for_square_channel_is_four():
    assert S.tiles_for("band") == 4


def test_tiles_for_portrait_channel_is_four():
    assert S.tiles_for("kakao") == 4


def test_tiles_for_unknown_channel_defaults_to_four():
    assert S.tiles_for("nosuchplatform") == 4


def test_gen_one_uses_sd_when_engine_is_sd(monkeypatch):
    import config
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", False, raising=False)
    from content import sd_backend
    monkeypatch.setattr(sd_backend, "gen_tile",
                        lambda brief, size=768, retries=2:
                            Image.new("RGB", (8, 8), (255, 255, 255)))
    out = S._gen_one("a sticker of a cat")
    assert isinstance(out, (bytes, bytearray))
    assert out[:8] == b"\x89PNG\r\n\x1a\n"      # PNG 시그니처


def test_gen_one_still_locked_when_image_gen_locked(monkeypatch):
    """회귀 방지 — 잠금은 엔진과 무관하게 먼저 걸려야 한다."""
    import config, pytest
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_GEN_LOCKED", True, raising=False)
    with pytest.raises(RuntimeError, match="IMAGE_GEN_LOCKED"):
        S._gen_one("x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_showcase_engine.py -v`
Expected: FAIL — `AttributeError: module 'content.showcase' has no attribute 'tiles_for'`

- [ ] **Step 3: `tiles_for` 추가 + `_gen_one` 분기**

`content/showcase.py` 의 `_gen_one`(170행) **바로 위**에 넣는다.

```python
def tiles_for(platform: str) -> int:
    """칸 수는 채널 규격이 정한다.

    ⚠ 고정값(SHOWCASE_TILES) 하나로 둘 수 없다. 격자가 cols = min(n, 2) 라서
      칸 수가 곧 비율이다 — 2장이면 가로로 길고 4장이면 정사각이다.
      facebook(1200x630)에 4장을 쓰면 세로로 길어져 잘리고,
      band(1080x1080)에 2장을 쓰면 가로로 퍼져 여백이 남는다.
    """
    w, h = config.CHANNEL_SPECS.get(platform, (1080, 1080))
    return 2 if (h and w / h >= 1.5) else 4
```

`_gen_one` 의 잠금 검사 **아래**, `from google import genai` **위**에 분기를 넣는다.

```python
    if getattr(config, "CARD_ENGINE", "gemini") == "sd":
        # SD 는 글자를 못 그린다. 배경·도안만 맡기고 한글은 호출부가 찍는다.
        from content import sd_backend
        img = sd_backend.gen_tile(prompt)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
```

`styles_for`(217행)와 `make`(240행)의 `config.SHOWCASE_TILES` 를 `tiles_for(channel)` 로 바꾼다. `styles_for` 는 채널을 인자로 받지 않으므로 `tiles_n` 을 넘기는 호출부(`orchestrator.py`)가 계산해서 준다 — **두 곳의 계산식이 반드시 같아야 한다**(기존 주석의 경고와 같은 이유).

```python
# showcase.styles_for
    n = max(1, min(int(tiles_n or tiles_for("band")), len(styles)))
# showcase.make
    n = max(1, min(int(tiles_n or tiles_for(channel)), len(styles)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_showcase_engine.py tests/test_image_reuse.py -v`
Expected: PASS — 신규 6개 + 기존 재사용 테스트 전부

- [ ] **Step 5: orchestrator 호출부 정합**

`orchestrator.py` 에서 `showcase.styles_for(config.PROFILE_KEY, v)` 를 부르는 자리에 `tiles_n` 을 넘긴다.

```python
campaign["styles"] = ", ".join(
    showcase.styles_for(config.PROFILE_KEY, v,
                        tiles_n=showcase.tiles_for(ch["platform"])))
```

Run: `python -m pytest tests/ -q`
Expected: 전부 통과

- [ ] **Step 6: Commit**

```bash
git add content/showcase.py orchestrator.py tests/test_showcase_engine.py
git commit -m "feat(autoad): route showcase tiles by channel spec and add sd engine branch"
```

---

### Task 5: showcase SPECS 7종 확장

채널 수가 많은 순으로 넣는다. `printcraft`·`mirizip`·`proheadshot` 셋이 활성 채널 94개를 덮는다.

**Files:**
- Modify: `content/showcase.py:26` (`SPECS`)
- Test: `tests/test_showcase_specs.py`

**Interfaces:**
- Consumes: `showcase.SPECS` 구조 (기존)
- Produces: `SPECS` 에 `printcraft` · `mirizip` · `proheadshot` · `colorcraft` · `petportrait` · `wallpreview` · `nailpreview` 7개 키

- [ ] **Step 1: Write the failing test**

```python
# tests/test_showcase_specs.py
# -*- coding: utf-8 -*-
"""SPECS 는 프로필의 컴플라이언스와 함께 써야 한다.

⚠ stickerme 프로필은 note 가 "타 IP·캐릭터 연상 표현 금지" 다. note 를 안 보고
  모티프를 지으면 타 IP 연상 표현이 그대로 광고로 나간다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from content import showcase as S

NEW = ["printcraft", "mirizip", "proheadshot", "colorcraft",
       "petportrait", "wallpreview", "nailpreview"]


def test_new_profiles_registered():
    for k in NEW:
        assert k in S.SPECS, f"{k} SPECS 없음"


def test_each_spec_has_label_styles_motifs():
    for k in NEW:
        spec = S.SPECS[k]
        assert spec.get("label")
        assert len(spec.get("styles") or []) >= 4, f"{k}: 기법이 4개 미만"
        assert len(spec.get("motifs") or []) >= 6, f"{k}: 소재가 6개 미만"


def test_styles_are_label_prompt_pairs():
    for k in NEW:
        for item in S.SPECS[k]["styles"]:
            assert isinstance(item, tuple) and len(item) == 2
            assert "{subject}" in item[1], f"{k}: 프롬프트에 {{subject}} 없음"


def test_styles_for_is_deterministic():
    """make() 의 인덱스 계산식과 같아야 한다(기존 주석의 경고)."""
    a = S.styles_for("printcraft", 0, tiles_n=4)
    b = S.styles_for("printcraft", 0, tiles_n=4)
    assert a == b and len(a) == 4


def test_no_named_ip_in_motifs():
    """타 IP 연상 금지 — 대표적인 상표명이 모티프에 없어야 한다."""
    banned = ["mickey", "pikachu", "hello kitty", "disney", "pokemon",
              "marvel", "snoopy", "doraemon"]
    for k in NEW:
        blob = " ".join(S.SPECS[k]["motifs"]).lower()
        for b in banned:
            assert b not in blob, f"{k}: 모티프에 '{b}'"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_showcase_specs.py -v`
Expected: FAIL — `AssertionError: printcraft SPECS 없음`

- [ ] **Step 3: SPECS 7개 추가**

`content/showcase.py` 의 `SPECS` 사전에 넣는다. **각 업종의 `profiles/<key>.yaml` 의 `compliance.note` 를 먼저 읽고** 그에 어긋나지 않는 모티프를 쓴다.

```python
    "printcraft": {
        "label": "POD 디자인",
        "styles": [
            ("타이포", "minimal typographic poster design featuring {subject}, "
                      "bold geometric shapes, limited flat color palette"),
            ("라인아트", "single-line continuous line art of {subject}, "
                       "thin elegant strokes, lots of empty space"),
            ("빈티지", "vintage screen-print style illustration of {subject}, "
                     "muted retro palette, subtle paper texture in the artwork"),
            ("플랫", "flat vector illustration of {subject}, bold outlines, "
                    "cheerful saturated colors"),
        ],
        "motifs": [
            "a mountain range at sunrise", "a coffee cup with steam swirls",
            "a sailboat on calm waves", "a houseplant in a clay pot",
            "a bicycle with a basket of flowers", "a crescent moon over pine trees",
        ],
    },
    "mirizip": {
        "label": "인테리어 미리보기",
        "styles": [
            ("북유럽", "scandinavian interior of {subject}, light oak floor, "
                     "white walls, soft daylight, minimal furniture"),
            ("모던", "modern interior of {subject}, clean lines, neutral palette, "
                    "indirect lighting, uncluttered"),
            ("우드", "warm wood-toned interior of {subject}, natural textures, "
                    "cozy afternoon light"),
            ("미니멀", "minimalist interior of {subject}, muted tones, "
                     "very few objects, calm atmosphere"),
        ],
        "motifs": [
            "a small living room", "a bedroom with a low bed",
            "a kitchen with an island", "a home office nook",
            "a studio apartment", "a dining area by a window",
        ],
    },
    "proheadshot": {
        "label": "프로필 헤드샷 배경",
        # ⚠ 인물 자체는 만들지 않는다. sd_backend.NEG_FORCE 가 사람을 막고,
        #   이 업종은 '배경·조명 스타일' 을 보여준다.
        "styles": [
            ("스튜디오", "empty professional studio backdrop, {subject}, "
                       "soft key light, seamless paper background"),
            ("그라디언트", "smooth studio gradient backdrop, {subject}, "
                        "even soft lighting"),
            ("오피스", "softly blurred modern office background, {subject}, "
                     "shallow depth of field"),
            ("아웃도어", "softly blurred outdoor background, {subject}, "
                      "warm natural light, bokeh"),
        ],
        "motifs": [
            "cool grey tones", "warm beige tones", "deep navy tones",
            "soft charcoal tones", "muted sage tones", "clean white tones",
        ],
    },
    "colorcraft": {
        "label": "컬러링 도안",
        "styles": [
            ("굵은선", "coloring book page of {subject}, thick clean black outlines, "
                     "no shading, large simple areas to color"),
            ("가는선", "detailed coloring book page of {subject}, fine black line art, "
                     "intricate patterns, no shading"),
            ("만다라", "mandala-style coloring page incorporating {subject}, "
                     "symmetric radial pattern, black line art only"),
            ("장면", "coloring book scene featuring {subject}, simple background, "
                    "clear black outlines, no shading"),
        ],
        "motifs": [
            "a friendly dinosaur", "a hot air balloon over hills",
            "a cat napping on books", "a rocket and planets",
            "a garden with butterflies", "a castle on a hill",
        ],
    },
    "petportrait": {
        "label": "반려동물 초상화",
        "styles": [
            ("유화", "oil painting portrait of {subject}, visible brush strokes, "
                    "rich warm palette, classical portrait framing"),
            ("수채", "watercolor portrait of {subject}, soft washes, delicate edges"),
            ("펜화", "ink pen portrait of {subject}, fine cross-hatching, monochrome"),
            ("파스텔", "soft pastel portrait of {subject}, gentle colors, "
                     "smooth blended shading"),
        ],
        "motifs": [
            "a golden retriever", "a grey tabby cat", "a corgi in profile",
            "a beagle looking up", "a white rabbit", "a shiba inu smiling",
        ],
    },
    "wallpreview": {
        "label": "월아트 미리보기",
        "styles": [
            ("추상", "abstract wall art print of {subject}, organic shapes, "
                    "muted contemporary palette"),
            ("보태니컬", "botanical wall art print of {subject}, delicate linework, "
                       "soft natural tones"),
            ("기하", "geometric wall art print of {subject}, clean shapes, "
                    "balanced composition"),
            ("풍경", "minimal landscape wall art print of {subject}, "
                    "simplified forms, calm palette"),
        ],
        "motifs": [
            "rolling hills at dusk", "a single leaf study", "layered arches",
            "a calm sea horizon", "desert dunes", "a pale winter forest",
        ],
    },
    "nailpreview": {
        "label": "네일 디자인",
        # ⚠ 손·피부가 나오면 안 된다(NEG_FORCE). 네일 팁만 보여준다.
        "styles": [
            ("글리터", "set of press-on nail tips with {subject}, glitter finish, "
                     "arranged in a row, product photography on white"),
            ("젤", "set of press-on nail tips with {subject}, glossy gel finish, "
                  "arranged in a row, product photography on white"),
            ("무광", "set of press-on nail tips with {subject}, soft matte finish, "
                   "arranged in a row, product photography on white"),
            ("프렌치", "set of press-on nail tips with a french tip variation of "
                     "{subject}, arranged in a row, product photography on white"),
        ],
        "motifs": [
            "soft pink ombre", "milky white with tiny pearls",
            "sage green marble", "lavender with silver flecks",
            "warm nude with gold line", "sheer peach with fine glitter",
        ],
    },
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_showcase_specs.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: 실물 1장 확인 (수동)**

`.env` 에 `CARD_ENGINE=sd` · `IMAGE_GEN_LOCKED=0` 를 임시로 두고 돌린다.

Run: `python -c "from content import showcase; print(showcase.make(profile_key='printcraft', channel='band'))"`
Expected: `data/creatives/showcase_printcraft_band.png` 생성. **눈으로 본다** — 흰 배경인지, 글자가 없는지, 사람이 없는지. 확인 후 `.env` 를 원복한다.

- [ ] **Step 6: Commit**

```bash
git add content/showcase.py tests/test_showcase_specs.py
git commit -m "feat(autoad): add showcase specs for 7 profiles"
```

---

### Task 6: 쿨다운 스코프를 (이미지 × 채널) 로 + round_id

**Files:**
- Modify: `db.py:122` (`_MIGRATIONS`) · `db.py:411` (`image_cooldown_left`)
- Modify: `orchestrator.py:514` (`_claimed_images`) · `orchestrator.py:1368` (발행 게이트)
- Test: `tests/test_cooldown_scope.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `creatives.round_id TEXT` 컬럼
  - `db.image_cooldown_left(image_path: str, days: int, channel_id: int | None = None) -> int` — `channel_id` 를 주면 **그 채널의** 마지막 발행만 본다. 안 주면 기존처럼 전역(하위호환).
  - `orchestrator._claimed_images(round_id: str | None = None) -> set` — `round_id` 를 주면 그 바퀴가 잡은 것은 제외하지 않는다.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cooldown_scope.py
# -*- coding: utf-8 -*-
"""쿨다운은 '같은 방' 기준이다.

.env 주석이 그 근거를 이미 적어 뒀다 —
  "매 건 다른 문구로 나가고, 그림도 쿨다운 때문에 같은 것이 다시 쓰이지 않는다
   — '같은 방에 같은 글' 이 아니다"
목적이 같은 방에서의 반복 방지였는데 구현이 전역이라, 한 바퀴에 그림이
발행 건수만큼 필요했다. 스코프를 좁혀 '상품 1바퀴 = 그림 1장' 으로 만든다.
"""
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import db


def _seed(con, image_path, channel_id, when):
    cur = con.execute(
        "INSERT INTO creatives (campaign_id, channel_id, kind, image_path) "
        "VALUES (1, ?, 'ad', ?)", (channel_id, image_path))
    cid = cur.lastrowid
    con.execute(
        "INSERT INTO posts (creative_id, channel_id, status, posted_at, created_at) "
        "VALUES (?, ?, 'posted', ?, ?)", (cid, channel_id, when, when))
    return cid


def test_same_image_blocked_in_same_channel(temp_db):
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        _seed(con, "/img/a.png", 11, now)
    assert db.image_cooldown_left("/img/a.png", 14, channel_id=11) > 0


def test_same_image_free_in_other_channel(temp_db):
    """이게 이 변경의 핵심 — 다른 방에는 나갈 수 있어야 한다."""
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        _seed(con, "/img/a.png", 11, now)
    assert db.image_cooldown_left("/img/a.png", 14, channel_id=22) == 0


def test_global_scope_unchanged_when_channel_omitted(temp_db):
    """하위호환 — channel_id 를 안 주면 예전 그대로 전역이다."""
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        _seed(con, "/img/a.png", 11, now)
    assert db.image_cooldown_left("/img/a.png", 14) > 0


def test_round_id_column_exists(temp_db):
    with db.get_conn() as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(creatives)")]
    assert "round_id" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cooldown_scope.py -v`
Expected: FAIL — `test_same_image_free_in_other_channel` 이 실패(전역이라 0이 아님), `test_round_id_column_exists` 도 실패

- [ ] **Step 3: 마이그레이션 + 함수 시그니처 확장**

`db.py` 의 `_MIGRATIONS` 리스트 끝에 추가한다.

```python
    # 한 바퀴(= 한 상품에 대한 run_campaign 1회 실행) 식별자.
    # ⚠ '같은 캠페인' 으로만 묶으면 캠페인을 두 번 돌렸을 때 두 바퀴가 한 덩어리로
    #   보여 그림이 재사용되지 않는다. 실행마다 새 값을 찍는다.
    ("creatives", "round_id", "ALTER TABLE creatives ADD COLUMN round_id TEXT"),
```

`image_cooldown_left`(411행)를 바꾼다.

```python
def image_cooldown_left(image_path: str, days: int,
                        channel_id: int = None) -> int:
    """같은 **이미지**를 다시 쓰기까지 남은 일수(0이면 지금 써도 됨).

    ⚠ creative 행 단위로 보면 안 된다. 캠페인을 돌릴 때마다 새 creative 행이
      생기므로 last_posted_at 이 늘 비어 있어 쿨다운이 한 번도 발동하지 않는다.

    ⚠ channel_id 를 주면 **그 방에서의** 마지막 발행만 본다. 쿨다운의 목적이
      '같은 방에 같은 그림' 방지이기 때문이다(.env 주석 참고). 안 주면 예전처럼
      전역으로 본다 — 기존 호출부의 하위호환.
    """
    if days <= 0 or not image_path:
        return 0
    marks = ",".join("?" * len(COUNTS_AS_POSTED))
    sql = (f"SELECT MAX(COALESCE(p.posted_at, p.created_at)) t "
           f"FROM posts p JOIN creatives c ON p.creative_id = c.id "
           f"WHERE p.status IN ({marks}) AND c.image_path = ?")
    args = list(COUNTS_AS_POSTED) + [image_path]
    if channel_id is not None:
        sql += " AND p.channel_id = ?"
        args.append(channel_id)
    with get_conn() as c:
        row = c.execute(sql, args).fetchone()
    if not row or not row["t"]:
        return 0
    from datetime import datetime as _dt, timedelta
    try:
        last = _dt.fromisoformat(row["t"])
    except Exception:
        return 0
    left = (last + timedelta(days=days)) - _dt.now()
    return max(0, left.days + (1 if left.seconds else 0))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cooldown_scope.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 발행 게이트와 배정 로직을 채널 기준으로**

`orchestrator.py:1368` 을 바꾼다.

```python
        left = db.image_cooldown_left(row["image_path"],
                                      config.CREATIVE_COOLDOWN_DAYS,
                                      channel_id=row["channel_id"])
```

`orchestrator._claimed_images`(514행)에 `round_id` 예외를 넣는다.

```python
def _claimed_images(round_id: str = None) -> set:
    """앞으로 나갈 소재가 잡고 있는 이미지 경로.

    ⚠ 같은 바퀴(round_id)가 잡은 것은 제외하지 않는다. 한 바퀴 안에서는
      여러 채널이 **같은 그림을 공유하는 것이 정상**이기 때문이다.
    """
    sql = ("SELECT DISTINCT cr.image_path FROM creatives cr "
           "JOIN approvals a ON a.creative_id = cr.id "
           "WHERE COALESCE(cr.image_path,'') <> '' AND a.state = 'pending'")
    args = []
    if round_id:
        sql += " AND COALESCE(cr.round_id,'') <> ?"
        args.append(round_id)
    with db.get_conn() as con:
        return {r[0] for r in con.execute(sql, args)}
```

- [ ] **Step 6: Run the whole suite**

Run: `python -m pytest tests/ -q`
Expected: 전부 통과 (특히 `test_image_reuse.py` 가 깨지지 않아야 한다)

- [ ] **Step 7: Commit**

```bash
git add db.py orchestrator.py tests/test_cooldown_scope.py
git commit -m "feat(autoad): scope image cooldown per channel and add round_id"
```

---

### Task 7: 팬아웃 상한 + 재고 목표

**Files:**
- Modify: `config.py` (IMAGE_FANOUT_MAX)
- Modify: `tools/auto_loop.py:448` (`free_images` 옆)
- Test: `tests/test_fanout_stock.py`

**Interfaces:**
- Consumes: `config.CREATIVE_COOLDOWN_DAYS` (기존)
- Produces:
  - `config.IMAGE_FANOUT_MAX: int` (기본 20)
  - `auto_loop.images_per_round(profile: str) -> int`
  - `auto_loop.stock_target(profile: str) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fanout_stock.py
# -*- coding: utf-8 -*-
"""한 그림이 몇 방에 뿌려지는가를 상한으로 막는다.

시간 분산(한 바퀴를 2~3일에 걸쳐 돌기)은 이 문제를 못 고친다 — 노출 속도만
늦출 뿐 '같은 그림이 66곳에 남아 있다' 는 사실은 그대로다. 플랫폼이 보는 것은
속도가 아니라 콘텐츠 지문이다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import auto_loop as A


def _chan(monkeypatch, n):
    monkeypatch.setattr(A, "enabled_channel_count", lambda prof: n)


def test_small_profile_needs_one_image_per_round(monkeypatch):
    _chan(monkeypatch, 8)
    assert A.images_per_round("inkcraft") == 1


def test_exactly_at_cap_is_still_one(monkeypatch):
    _chan(monkeypatch, 20)
    assert A.images_per_round("x") == 1


def test_one_over_cap_needs_two(monkeypatch):
    _chan(monkeypatch, 21)
    assert A.images_per_round("x") == 2


def test_large_profile_splits(monkeypatch):
    """adstudio 74채널 → ceil(74/20) = 4장"""
    _chan(monkeypatch, 74)
    assert A.images_per_round("adstudio") == 4


def test_zero_channels_is_zero(monkeypatch):
    _chan(monkeypatch, 0)
    assert A.images_per_round("dead") == 0


def test_stock_target_is_round_images_times_cooldown(monkeypatch):
    import config
    _chan(monkeypatch, 50)
    monkeypatch.setattr(config, "CREATIVE_COOLDOWN_DAYS", 14)
    assert A.stock_target("printcraft") == 3 * 14
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fanout_stock.py -v`
Expected: FAIL — `AttributeError: module 'auto_loop' has no attribute 'images_per_round'`

- [ ] **Step 3: config 상수 추가**

`config.py` 의 `CREATIVE_COOLDOWN_DAYS`(192행) 아래에 넣는다.

```python
# 그림 1장이 덮는 채널 수 상한. 넘으면 그 바퀴에 그림을 더 쓴다.
#  ⚠ 20 은 '지금 재고로 감당되는 가장 강한 상한' 이다. 10 으로 조이면
#    adstudio 가 ceil(74/10)=8장 x 14일 = 112장 필요한데 83장뿐이라 부족해진다.
#    재고가 늘면 낮출 수 있고, 낮출수록 안전하다.
IMAGE_FANOUT_MAX = int(os.getenv("IMAGE_FANOUT_MAX", "20"))
#  ⚠ 재고 목표용 별도 상수를 두지 않는다. '라운드당 그림 수 x 쿨다운 일수' 는
#    취향이 아니라 산수다 — 한 그림이 나가면 CREATIVE_COOLDOWN_DAYS 만큼 쉬므로
#    하루 한 바퀴를 돌리려면 그만큼 있어야 한다. 같은 수에 이름을 둘 붙이면
#    언젠가 갈라진다(stock_target 참고).
```

- [ ] **Step 4: auto_loop 에 함수 3개**

`tools/auto_loop.py` 의 `free_images`(448행) **바로 위**에 넣는다.

```python
def enabled_channel_count(profile: str) -> int:
    """그 업종의 활성 채널 수(데모 제외). 테스트에서 갈아끼우는 이음매다."""
    return sum(1 for c in db.list_channels(enabled_only=True)
               if c["profile_key"] == profile and not db.is_demo_channel(c))


def images_per_round(profile: str) -> int:
    """한 바퀴에 쓸 그림 수. 채널이 많을수록 여러 장으로 나눈다."""
    n = enabled_channel_count(profile)
    if n <= 0:
        return 0
    cap = max(1, config.IMAGE_FANOUT_MAX)
    return -(-n // cap)          # ceil


def stock_target(profile: str) -> int:
    """그 업종이 무한 순환하려면 필요한 재고.

    한 그림은 한 방에 나가면 쿨다운 일수만큼 쉰다. 하루 한 바퀴를 돌리려면
    '라운드당 그림 수 x 쿨다운 일수' 만큼 있어야 돌아간다.
    """
    return images_per_round(profile) * max(1, config.CREATIVE_COOLDOWN_DAYS)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_fanout_stock.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
git add config.py tools/auto_loop.py tests/test_fanout_stock.py
git commit -m "feat(autoad): add image fan-out cap and stock target"
```

---

### Task 8: 한 바퀴 안에서 그림 공유 (`_used_paths` 교체)

스펙 §5.6 의 마지막 조각이다. Task 6 이 쿨다운을, Task 7 이 몇 장을 쓸지를 정했으니, 여기서 **한 바퀴가 실제로 그림을 나눠 쓰게** 만든다. 지금은 `_used_paths` 가 한 실행 안의 재사용을 전부 막아 채널 수만큼 그림이 필요하다.

**Files:**
- Modify: `orchestrator.py` (`run_campaign` 안의 `_used_paths` · `_existing_free` 호출부)
- Test: `tests/test_round_sharing.py`

**Interfaces:**
- Consumes: `auto_loop.images_per_round` (Task 7) — orchestrator 는 `tools/` 를 import 하지 않으므로 **같은 식을 `orchestrator.images_per_round` 로 다시 두지 않는다.** 대신 아래 `_round_pool` 이 개수를 인자로 받는다.
- Produces:
  - `orchestrator.new_round_id() -> str`
  - `orchestrator._round_pool(fmt: str, n_images: int, round_id: str) -> list[tuple[int, str]]` — 이 바퀴가 쓸 (번호, 경로) 목록
  - `orchestrator.pick_for_channel(pool: list, idx: int) -> tuple[int, str]` — 채널 순번을 풀 크기로 나눠 배정

- [ ] **Step 1: Write the failing test**

```python
# tests/test_round_sharing.py
# -*- coding: utf-8 -*-
"""한 바퀴 안에서는 여러 채널이 같은 그림을 나눠 쓴다.

지금은 _used_paths 가 한 실행 안의 재사용을 전부 막아, 채널 50곳이면 그림도
50장이 필요했다. 그래서 '발행 1건 = 그림 1장' 이 됐고 과금이 발행량에 정비례했다.
바꾼 뒤에는 '상품 1바퀴 = 그림 N장'(N = ceil(채널수 / IMAGE_FANOUT_MAX)) 이다.
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

import orchestrator as O


def test_new_round_id_is_unique():
    a, b = O.new_round_id(), O.new_round_id()
    assert a and b and a != b


def test_pick_cycles_through_pool():
    pool = [(0, "/a.png"), (1, "/b.png"), (2, "/c.png")]
    got = [O.pick_for_channel(pool, i)[1] for i in range(7)]
    assert got == ["/a.png", "/b.png", "/c.png",
                   "/a.png", "/b.png", "/c.png", "/a.png"]


def test_pick_spreads_evenly_over_many_channels():
    """adstudio 74채널 · 그림 4장 → 각 그림이 18~19곳을 덮는다(상한 20 이내)."""
    pool = [(i, f"/{i}.png") for i in range(4)]
    counts = {}
    for i in range(74):
        p = O.pick_for_channel(pool, i)[1]
        counts[p] = counts.get(p, 0) + 1
    assert max(counts.values()) <= 20
    assert len(counts) == 4


def test_pick_raises_on_empty_pool():
    import pytest
    with pytest.raises(ValueError):
        O.pick_for_channel([], 0)


def test_round_pool_returns_requested_count(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "CREATIVES_DIR", tmp_path)
    for i in range(5):
        (tmp_path / f"doc_x_band_v{i}.png").write_bytes(b"x")
    monkeypatch.setattr(O, "_claimed_images", lambda round_id=None: set())
    monkeypatch.setattr(O.db, "image_cooldown_left",
                        lambda p, d, channel_id=None: 0)
    pool = O._round_pool("doc_x_band_v{n}.png", 3, "r1")
    assert len(pool) == 3
    assert len({p for _, p in pool}) == 3          # 서로 다른 그림


def test_round_pool_shrinks_when_stock_is_short(monkeypatch, tmp_path):
    """재고가 모자라면 있는 만큼만. 없다고 터지지 않는다."""
    import config
    monkeypatch.setattr(config, "CREATIVES_DIR", tmp_path)
    (tmp_path / "doc_x_band_v0.png").write_bytes(b"x")
    monkeypatch.setattr(O, "_claimed_images", lambda round_id=None: set())
    monkeypatch.setattr(O.db, "image_cooldown_left",
                        lambda p, d, channel_id=None: 0)
    pool = O._round_pool("doc_x_band_v{n}.png", 3, "r1")
    assert len(pool) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_round_sharing.py -v`
Expected: FAIL — `AttributeError: module 'orchestrator' has no attribute 'new_round_id'`

- [ ] **Step 3: 세 함수 추가**

`orchestrator.py` 의 `_claimed_images`(514행) 아래에 넣는다.

```python
def new_round_id() -> str:
    """한 바퀴의 식별자. run_campaign 실행마다 새로 찍는다.

    ⚠ '같은 캠페인' 으로 묶으면 안 된다. 캠페인을 두 번 돌리면 두 바퀴가 한
      덩어리로 보여 그림이 재사용되지 않는다.
    """
    import uuid
    return uuid.uuid4().hex


def _round_pool(fmt: str, n_images: int, round_id: str) -> list:
    """이 바퀴가 쓸 (번호, 경로) 목록. 재고가 모자라면 있는 만큼만 돌려준다.

    조건은 기존 _existing_free 와 같다 — 파일이 있고, 쿨다운이 아니고,
    **다른 바퀴의** 미발행 소재가 잡고 있지 않을 것.
    """
    taken = _claimed_images(round_id)
    out = []
    for n in range(0, 200):
        if len(out) >= max(0, n_images):
            break
        path = str(config.CREATIVES_DIR / fmt.format(n=n))
        if path in taken or not os.path.isfile(path):
            continue
        if db.image_cooldown_left(path, config.CREATIVE_COOLDOWN_DAYS):
            continue
        out.append((n, path))
    return out


def pick_for_channel(pool: list, idx: int):
    """채널 순번 idx 에 그림을 배정한다. 풀을 순환하며 고르게 나눈다."""
    if not pool:
        raise ValueError("이 바퀴에 쓸 그림이 없습니다")
    return pool[idx % len(pool)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_round_sharing.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: `run_campaign` 을 풀 방식으로 바꾼다**

`orchestrator.run_campaign` 의 채널 루프에서 `_used_paths` 를 없애고 풀을 먼저 만든다. 루프 **앞**에:

```python
    round_id = new_round_id()
    # 한 그림이 덮는 채널 수 상한(config.IMAGE_FANOUT_MAX)에서 장수를 정한다.
    n_imgs = max(1, -(-len(channels) // max(1, config.IMAGE_FANOUT_MAX)))
```

기존 `_existing_free(fmt)` 호출을 풀에서 꺼내는 것으로 바꾼다(콘텐츠형·광고형 두 자리 모두).

```python
            pool = _round_pool(fmt, n_imgs, round_id)
            if not pool:
                raise RuntimeError(
                    "쓸 수 있는 기존 이미지가 없습니다"
                    "(전부 쿨다운이거나 다른 바퀴가 잡고 있음)")
            v, path = pick_for_channel(pool, ch_index)
            image = path
```

`ch_index` 는 `for ch in channels:` 를 `for ch_index, ch in enumerate(channels):` 로 바꿔 얻는다. `_used_paths` 선언과 `_used_paths.add(...)` 를 전부 지운다.

소재를 저장할 때 `round_id` 를 함께 넣는다(`db.add_creative` 에 인자를 더하거나, 저장 직후 `UPDATE creatives SET round_id=? WHERE id=?`).

- [ ] **Step 6: 전체 회귀**

Run: `python -m pytest tests/ -q`
Expected: 전부 통과. **`test_image_reuse.py` 가 특히 중요하다** — 기존 재사용 계약이 깨지지 않아야 한다.

- [ ] **Step 7: Commit**

```bash
git add orchestrator.py tests/test_round_sharing.py
git commit -m "feat(autoad): share one image across a round instead of per post"
```

---

### Task 9: 하루 생성 예산 (엔진별)

**Files:**
- Modify: `config.py` (예산 상수 + `image_daily_budget()`)
- Modify: `db.py` (`images_made_today`)
- Modify: `tools/auto_loop.py:503` (`do_generate`)
- Test: `tests/test_daily_budget.py`

**Interfaces:**
- Consumes: `config.CARD_ENGINE` (Task 3), `auto_loop.stock_target` (Task 7)
- Produces:
  - `config.IMAGE_DAILY_BUDGET_SD: int` (12) · `config.IMAGE_DAILY_BUDGET_GEMINI: int` (2)
  - `config.image_daily_budget() -> int`
  - `db.images_made_today() -> int` — 오늘 만들어진 creatives 수

- [ ] **Step 1: Write the failing test**

```python
# tests/test_daily_budget.py
# -*- coding: utf-8 -*-
"""예산은 '목표' 가 아니라 '천장' 이다.

실제 생성량은 재고 목표치가 정하고, 목표에 닿으면 need=0 이 되어 저절로 멈춘다.
⚠ 엔진별로 나눈 이유: 하나로 두면 CARD_ENGINE=gemini 로 되돌리는 순간
  같은 천장이 그대로 '과금' 이 된다 — 롤백 스위치가 과금 스위치가 되어 버린다.
"""
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

import db


def test_budget_follows_engine(monkeypatch):
    import config
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_SD", 12)
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_GEMINI", 2)
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    assert config.image_daily_budget() == 12
    monkeypatch.setattr(config, "CARD_ENGINE", "gemini")
    assert config.image_daily_budget() == 2


def test_images_made_today_counts_only_today(temp_db):
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        con.execute("INSERT INTO creatives (campaign_id, channel_id, kind, "
                    "image_path, created_at) VALUES (1,1,'ad','/a.png',?)", (now,))
        con.execute("INSERT INTO creatives (campaign_id, channel_id, kind, "
                    "image_path, created_at) VALUES (1,1,'ad','/b.png',"
                    "'2020-01-01T00:00:00')")
    assert db.images_made_today() == 1


def test_images_made_today_ignores_rows_without_image(temp_db):
    now = datetime.now().isoformat()
    with db.get_conn() as con:
        con.execute("INSERT INTO creatives (campaign_id, channel_id, kind, "
                    "image_path, created_at) VALUES (1,1,'ad','',?)", (now,))
    assert db.images_made_today() == 0


def test_remaining_budget_clamps_at_zero(monkeypatch, temp_db):
    import config
    import auto_loop as A
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_SD", 2)
    monkeypatch.setattr(db, "images_made_today", lambda: 5)
    assert A.remaining_image_budget() == 0


def test_remaining_budget_reports_leftover(monkeypatch, temp_db):
    import config
    import auto_loop as A
    monkeypatch.setattr(config, "CARD_ENGINE", "sd")
    monkeypatch.setattr(config, "IMAGE_DAILY_BUDGET_SD", 12)
    monkeypatch.setattr(db, "images_made_today", lambda: 5)
    assert A.remaining_image_budget() == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daily_budget.py -v`
Expected: FAIL — `AttributeError: module 'config' has no attribute 'image_daily_budget'`

- [ ] **Step 3: config 에 예산 + 헬퍼**

`config.py` 의 `IMAGE_FANOUT_MAX`(Task 7) 아래에 넣는다.

```python
# 하루에 만들 수 있는 이미지 수의 천장. 엔진별로 나눈다.
#  ⚠ 하나로 두면 CARD_ENGINE=gemini 로 되돌리는 순간 같은 천장이 그대로
#    과금이 된다 — 롤백 스위치가 과금 스위치가 되어 버린다.
IMAGE_DAILY_BUDGET_SD     = int(os.getenv("IMAGE_DAILY_BUDGET_SD", "12"))
IMAGE_DAILY_BUDGET_GEMINI = int(os.getenv("IMAGE_DAILY_BUDGET_GEMINI", "2"))


def image_daily_budget() -> int:
    return (IMAGE_DAILY_BUDGET_SD if CARD_ENGINE == "sd"
            else IMAGE_DAILY_BUDGET_GEMINI)
```

- [ ] **Step 4: db 에 오늘 집계**

`db.py` 의 `image_cooldown_left` 아래에 넣는다.

```python
def images_made_today() -> int:
    """오늘 만들어진 소재 이미지 수. 하루 생성 예산의 분모다.

    ⚠ image_path 가 빈 행은 세지 않는다. 이미지를 만들지 않은 소재라
      예산을 쓴 적이 없다.
    """
    with get_conn() as c:
        row = c.execute(
            "SELECT COUNT(*) n FROM creatives "
            "WHERE COALESCE(image_path,'') <> '' "
            "  AND DATE(COALESCE(created_at, '')) = DATE('now','localtime')"
        ).fetchone()
    return int(row["n"] if row else 0)
```

- [ ] **Step 5: auto_loop 에 잔여 예산 + do_generate 반영**

`tools/auto_loop.py` 의 `stock_target`(Task 7) 아래에 넣는다.

```python
def remaining_image_budget() -> int:
    """오늘 더 만들 수 있는 이미지 수."""
    return max(0, config.image_daily_budget() - db.images_made_today())
```

`do_generate`(503행)의 `need` 계산에 예산을 넣는다.

```python
        budget = remaining_image_budget()
        need = min(room, free_ch, plat_cap, budget) - have
        log(f"  [{platform}] 여유 {room} · 남은 채널 {free_ch} · 대기 {have}"
            f" · 주기당 {plat_cap} · 오늘 예산 {budget} → 만들 것 {max(0, need)}")
```

그리고 업종별 배분에서 **재고 목표에 닿은 업종은 건너뛴다.** `cap = free_images(...)` 줄 바로 위에 넣는다.

```python
            # 재고가 목표에 닿았으면 더 만들지 않는다. 이게 생성이 0 으로
            # 수렴하는 지점이다 — 예산은 천장이고, 멈추는 건 이 조건이다.
            tgt = stock_target(prof)
            if tgt and stock_count(prof) >= tgt:
                log(f"    {prof}: 재고 목표 {tgt}장 충족 → 건너뜀")
                continue
```

`stock_count` 를 `enabled_channel_count` 옆에 추가한다.

```python
def stock_count(profile: str) -> int:
    """그 업종이 지금 갖고 있는 쓸 수 있는 그림 수(디스크 기준)."""
    import re
    d = config.CREATIVES_DIR
    if not d.is_dir():
        return 0
    pat = re.compile(rf"^(showcase|doc)_{re.escape(profile)}_")
    return sum(1 for p in d.iterdir()
               if p.suffix.lower() == ".png" and pat.match(p.name))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_daily_budget.py -v`
Expected: PASS (5 passed)

- [ ] **Step 7: 전체 회귀 + 드라이런**

Run: `python -m pytest tests/ -q`
Expected: 전부 통과

Run: `python tools/auto_loop.py --dry-run`
Expected: 로그에 `오늘 예산 N` 이 찍히고, 재고가 충분한 업종은 `재고 목표 …장 충족 → 건너뜀` 이 나온다. **실제 발행·생성은 일어나지 않는다.**

- [ ] **Step 8: Commit**

```bash
git add config.py db.py tools/auto_loop.py tests/test_daily_budget.py
git commit -m "feat(autoad): add per-engine daily image budget and stock-target stop"
```

---

## ⛔ 전환 차단 조건 — 2026-09-08 Task 5 실측으로 추가

**아래 둘이 해결되기 전에는 `CARD_ENGINE=sd` 를 켜지 않는다.** 계획 작성 시점에는
몰랐고, Task 5 구현 중 실제 SD 를 돌려 보고 드러났다.

### 차단 ① 인물 차단이 신뢰할 수 없다 — 그런데 사람 검수가 없다

`sd_backend.NEG_FORCE` 에 `person, woman, face, hands, body, skin` 이 전부 들어간
상태에서 **부분 노출 이미지가 생성됐다**(기존 inkcraft 프롬프트, 2026-09-08 실측).
DreamShaper_8 의 인물 편향은 코드 docstring 도 이미 경고하던 것이다.

그리고 발행 경로에 사람이 없다:

```python
# tools/publish_campaign.py:199
res = O.approve_and_publish(it["aid"], reviewer="operator", dry_run=False)
```

20분 루프가 **프로그램적으로 승인하고 발행한다.** 스펙이 전제했던
"승인 콘솔 사람 확인이 최종 안전장치" 는 현재 코드에서 사실이 아니다.

→ 켜기 전에 **둘 중 하나**가 필요하다:
- 인물·피부 검출 게이트를 `gen_tile` 에 추가(흰 배경 게이트와 같은 자리), 또는
- SD 생성물에 한해 발행 전 사람 검수를 되살린다

### 차단 ③ SD 경로의 네트워크 호출에 예외 처리가 없다

`sd_backend.gen_tile` 은 두 번의 네트워크 호출(Ollama·SD WebUI)을 감싸지 않는다.
재시도 루프는 **흰 배경 게이트만** 덮으므로, `URLError`·500·JSON 아닌 응답은 타일을
즉시 중단시킨다. 그리고 그 실패는 `orchestrator.py` 의 콘텐츠형 except 로 떨어져
**광고형(Gemini 유료) 경로로 폴백**한다.

→ 차단 ② 때문에 게이트 실패가 흔한 상태라 이 폴백은 드문 길이 아니라 **흔한 길**이다.
  SD 를 켜기 전에 두 호출을 감싸고, 연결 실패도 재시도에 포함시킨다.

### 차단 ④ 예산 기본값이 그리드 한 장도 못 만든다

2026-09-08 최종 리뷰 후 예산의 단위가 **소재 행에서 실제 생성 횟수**로 바뀌었다.
그런데 `showcase.make` 는 그리드 하나에 `_gen_one` 을 **2~4회** 부른다(칸 수만큼).

→ `IMAGE_DAILY_BUDGET_GEMINI=2` 로는 그리드 **한 장도 못 만든다.**
  `IMAGE_GEN_LOCKED=0` 으로 바꾸기 전에 예산 값을 먼저 올릴 것. SD 쪽(12)도
  그리드 3~6개 분량임을 감안해 정한다.

### 차단 ② 흰 배경 게이트의 재시도 예산이 현실과 안 맞는다

| 프로필 | 결과 |
|---|---|
| printcraft | 3회(1+재시도2) **전부 실패** |
| colorcraft | **8회째 성공** |

실패는 오탐이 아니다 — 검은 선화가 테두리에 닿아 `min ≥ thresh-60` 에 정당하게
걸린다. 그런데 설계값 `retries=2` 는 3회뿐이라 `gen_tile` 이 상시 `RuntimeError` 를
던지고, `showcase.make` 가 실패해 **SD 경로가 아무것도 만들지 못한다.**

→ 켜기 전에 실측 통과율을 재고 `retries` 와 `thresh`/`band` 를 다시 잡는다.
선화 계열(colorcraft·inkcraft)은 테두리에 잉크가 닿는 것이 정상이므로,
업종별로 임계를 달리해야 할 수도 있다.

---

## 전환 순서 (코드 완료 후, 운영자 확인 아래)

코드가 다 들어가도 **`.env` 를 바꾸기 전까지 동작은 그대로다.** 한 번에 하나씩 켠다.
**3번은 위 차단 조건 둘을 해결한 뒤에만 밟는다.**

1. `python tools/migrate_creative_paths.py --apply` — 경로 1,448건 이관
2. `COPY_PROVIDER=ollama` — 캡션만 먼저. 하루 지켜본다
3. `CARD_ENGINE=sd` + `IMAGE_GEN_LOCKED=0` — 이미지 생성 재개
4. 대시보드에서 **차단(blocked) 건수와 흰 배경 게이트 재시도율**을 본다
5. 재시도율이 30% 를 지속적으로 넘으면 SDXL 재검토(스펙 §10)

되돌리기는 언제나 `.env` 한 줄이다 — `CARD_ENGINE=gemini` / `COPY_PROVIDER=gemini` / `IMAGE_GEN_LOCKED=1`.
