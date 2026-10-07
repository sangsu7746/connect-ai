# 블로그 리뉴얼 릴스 제작기 — M3 (SD 이미지 파이프라인) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대본의 씬별 이미지 프롬프트를 스타일팩과 결합해 로컬 SD WebUI(DreamShaper 8)로 이미지를 생성·캐시하고, 스토리보드 UI에서 잡 진행률과 씬 썸네일로 확인·재생성한다.

**Architecture:** style_packs(JSON 정의+롤/카테고리 매핑) → sd_webui 클라이언트(txt2img) → image_gen(캐시 조회→생성→저장→그라디언트 폴백) → jobs(스레드 기반 최소 잡 러너+진행률) → scripts images API(씬 일괄 잡·단일 씬 동기 재생성·정적 서빙) → Storyboard UI(썸네일·진행 폴링).

**Tech Stack:** M2.5와 동일 + Pillow(그라디언트 폴백·requirements 추가). SD WebUI API `/sdapi/v1/txt2img`(이미 API 모드로 운용 중, 포트 7860).

**Spec:** `docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md` §8(2026-08-16 개정판)

## Global Constraints

- .env 키 추가(정확히): `SD_WEBUI_URL` — 기본값 `http://127.0.0.1:7860`. settings 속성 `sd_webui_url`
- 해상도(SD1.5): 릴스(fmt `reels`) **576×1024**, 롱폼(fmt `long`) **1024×576** (spec §8)
- txt2img 파라미터: steps **25**, sampler `DPM++ 2M Karras`, cfg_scale **7**, seed -1
- 공통 네거티브에 `text, watermark, letters, typography, logo` 포함(자막 오버레이 충돌 방지)
- 씬 롤 매핑(정확히): hook=cinematic, summary=neon_abstract, cta=neon_abstract, twist=papercut, point·chapter=카테고리 기본(부동산=isometric, 재테크=flat_vector, IT=flat_vector, 건강=pastel_anime, 요리=pastel_anime, 여행=pastel_anime, 그 외=flat_vector) (spec §8)
- 캐시 키: sha256(`prompt|negative|style_id|WxH`) — 같은 키는 재생성하지 않고 파일 재사용
- 이미지 파일: `server/data/images/<hash>.png`, 정적 서빙 `/images/<hash>.png`
- SD 다운·실패 시 스타일 색 그라디언트 카드 폴백(Pillow) — 잡은 멈추지 않고 해당 씬만 폴백, scenes에 기록 (spec §8·§10)
- jobs.status 값: `running` | `done` | `error` 세 가지뿐
- SD·외부 호출 전부 mock 테스트(오프라인 CI). 실생성 스모크는 사용자 수동 항목
- web은 `verbatimModuleSyntax: true` — 타입은 `import { type X }`
- 커밋은 태스크마다, 변경 파일만 `git add`(루트 D:\ — `git add -A` 금지), 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 테스트: `server/.venv/Scripts/python.exe -m pytest server/tests -v` (PYTHONUTF8=1 필요 시)

---

### Task 1: 스타일팩 정의 + 로더

**Files:**
- Create: `server/core/style_packs.json`
- Create: `server/core/style_packs.py`
- Test: `server/tests/test_style_packs.py`

**Interfaces:**
- Produces: `style_packs.load() -> dict[str, dict]`(id→{name, prefix, negative, color}) · `style_packs.pick(role: str, category_name: str) -> str`(스타일 id — Global Constraints의 롤 매핑) · `style_packs.COMMON_NEGATIVE: str` · Task 3이 소비

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_style_packs.py`:
```python
from core import style_packs as sp

def test_load_six_packs_with_required_fields():
    packs = sp.load()
    assert set(packs.keys()) == {"flat_vector", "pastel_anime", "isometric",
                                 "cinematic", "papercut", "neon_abstract"}
    for p in packs.values():
        assert p["prefix"] and p["negative"] is not None and p["color"].startswith("#")

def test_pick_role_mapping():
    assert sp.pick("hook", "재테크") == "cinematic"
    assert sp.pick("summary", "부동산") == "neon_abstract"
    assert sp.pick("cta", "여행") == "neon_abstract"
    assert sp.pick("twist", "IT") == "papercut"

def test_pick_category_defaults():
    assert sp.pick("point", "부동산") == "isometric"
    assert sp.pick("point", "재테크") == "flat_vector"
    assert sp.pick("chapter", "요리") == "pastel_anime"
    assert sp.pick("point", "육아") == "flat_vector"      # 미정의 카테고리 기본

def test_common_negative_has_text_ban():
    for word in ("text", "watermark", "letters"):
        assert word in sp.COMMON_NEGATIVE
```

- [ ] **Step 2: 실패 확인** — Run: `server\.venv\Scripts\python -m pytest server/tests/test_style_packs.py -v`, Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/style_packs.json`:
```json
{
  "flat_vector": {
    "name": "플랫 벡터 인포그래픽",
    "prefix": "flat vector illustration, minimal infographic style, clean geometric shapes, soft gradient background, pastel accent colors, 2D design",
    "negative": "photo, photorealistic, 3d render, cluttered",
    "color": "#7c3aed"
  },
  "pastel_anime": {
    "name": "파스텔 애니 일러스트",
    "prefix": "beautiful anime background art, pastel colors, soft lighting, ghibli inspired scenery, detailed illustration, warm atmosphere",
    "negative": "photo, photorealistic, dark, gloomy",
    "color": "#f59e0b"
  },
  "isometric": {
    "name": "아이소메트릭 3D",
    "prefix": "isometric 3d illustration, clean architectural miniature, soft studio lighting, pastel palette, high detail diorama",
    "negative": "photo, flat 2d, sketch, messy",
    "color": "#38bdf8"
  },
  "cinematic": {
    "name": "시네마틱 실사",
    "prefix": "cinematic photography, dramatic lighting, shallow depth of field, high contrast, professional photo, 8k detail",
    "negative": "illustration, cartoon, anime, painting",
    "color": "#f87171"
  },
  "papercut": {
    "name": "페이퍼컷 콜라주",
    "prefix": "layered paper cut art, papercraft collage, depth layers, soft shadows, handcrafted texture, vivid colors",
    "negative": "photo, photorealistic, flat, digital gradient",
    "color": "#a78bfa"
  },
  "neon_abstract": {
    "name": "네온 그라디언트 추상",
    "prefix": "abstract neon gradient background, glowing shapes, dark backdrop, vibrant purple and blue light, smooth flowing forms",
    "negative": "photo, people, faces, cluttered detail",
    "color": "#34d399"
  }
}
```

`server/core/style_packs.py`:
```python
"""이미지 스타일팩 6종 로더 + 씬 롤/카테고리 매핑 (spec §8)."""
import json
import pathlib
from functools import lru_cache

COMMON_NEGATIVE = ("text, watermark, letters, typography, logo, signature, "
                   "low quality, blurry, deformed")

_ROLE_FIXED = {"hook": "cinematic", "summary": "neon_abstract",
               "cta": "neon_abstract", "twist": "papercut"}
_CATEGORY_DEFAULT = {"부동산": "isometric", "재테크": "flat_vector",
                     "IT": "flat_vector", "건강": "pastel_anime",
                     "요리": "pastel_anime", "여행": "pastel_anime"}
_FALLBACK = "flat_vector"


@lru_cache(maxsize=1)
def load() -> dict:
    p = pathlib.Path(__file__).with_name("style_packs.json")
    return json.loads(p.read_text(encoding="utf-8"))


def pick(role: str, category_name: str) -> str:
    if role in _ROLE_FIXED:
        return _ROLE_FIXED[role]
    return _CATEGORY_DEFAULT.get(category_name, _FALLBACK)
```

- [ ] **Step 4: 테스트 통과 확인** — 4 PASS + 전체 1회
- [ ] **Step 5: Commit**

```bash
git add server/core/style_packs.json server/core/style_packs.py server/tests/test_style_packs.py
git commit -m "feat(blog-reels): 스타일팩 6종 — 프리픽스·네거티브·롤/카테고리 매핑"
```

---

### Task 2: SD WebUI 클라이언트

**Files:**
- Modify: `server/core/config.py` (sd_webui_url 1줄)
- Modify: `.env.example` (SD_WEBUI_URL= 1줄)
- Create: `server/core/sd_webui.py`
- Test: `server/tests/test_sd_webui.py`

**Interfaces:**
- Consumes: `settings.sd_webui_url`
- Produces: `sd_webui.available() -> bool`(GET `/sdapi/v1/sd-models` 2s 타임아웃) · `sd_webui.txt2img(prompt: str, negative: str, width: int, height: int) -> bytes`(PNG 바이트 — base64 디코드, 실패 시 `SDError`) · `class SDError(RuntimeError)` — Task 3이 소비

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_sd_webui.py`:
```python
import base64
import httpx
import pytest
from core import sd_webui

PNG_STUB = b"\x89PNG\r\n\x1a\n_stub"

def test_txt2img_decodes_base64(monkeypatch):
    monkeypatch.setattr(sd_webui.settings, "sd_webui_url", "http://x:7860")
    captured = {}
    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        assert url.endswith("/sdapi/v1/txt2img")
        body = {"images": [base64.b64encode(PNG_STUB).decode()]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    out = sd_webui.txt2img("a cat", "bad", 576, 1024)
    assert out == PNG_STUB
    assert captured["steps"] == 25 and captured["cfg_scale"] == 7
    assert captured["sampler_name"] == "DPM++ 2M Karras"
    assert captured["width"] == 576 and captured["height"] == 1024

def test_txt2img_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(sd_webui.settings, "sd_webui_url", "http://x:7860")
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None:
                        httpx.Response(500, json={}, request=httpx.Request("POST", url)))
    with pytest.raises(sd_webui.SDError):
        sd_webui.txt2img("a", "b", 576, 1024)

def test_txt2img_raises_on_empty_images(monkeypatch):
    monkeypatch.setattr(sd_webui.settings, "sd_webui_url", "http://x:7860")
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None:
                        httpx.Response(200, json={"images": []},
                                       request=httpx.Request("POST", url)))
    with pytest.raises(sd_webui.SDError):
        sd_webui.txt2img("a", "b", 576, 1024)

def test_available(monkeypatch):
    monkeypatch.setattr(sd_webui.settings, "sd_webui_url", "http://x:7860")
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None:
                        httpx.Response(200, json=[], request=httpx.Request("GET", url)))
    assert sd_webui.available() is True
    def boom(url, timeout=None):
        raise OSError("down")
    monkeypatch.setattr(httpx, "get", boom)
    assert sd_webui.available() is False
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/config.py` Settings에 추가:
```python
    sd_webui_url = os.getenv("SD_WEBUI_URL", "http://127.0.0.1:7860")
```

`.env.example`에 추가:
```
SD_WEBUI_URL=http://127.0.0.1:7860
```

`server/core/sd_webui.py`:
```python
"""SD WebUI(A1111) API 클라이언트 (spec §8). DreamShaper 8 로드 상태를 전제로
현재 모델을 그대로 사용한다(모델 전환 API는 쓰지 않는다 — 단일 체크포인트 환경)."""
import base64

import httpx

from .config import settings


class SDError(RuntimeError):
    pass


def available() -> bool:
    try:
        r = httpx.get(f"{settings.sd_webui_url}/sdapi/v1/sd-models", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def txt2img(prompt: str, negative: str, width: int, height: int) -> bytes:
    try:
        r = httpx.post(f"{settings.sd_webui_url}/sdapi/v1/txt2img",
                       json={"prompt": prompt, "negative_prompt": negative,
                             "width": width, "height": height,
                             "steps": 25, "cfg_scale": 7,
                             "sampler_name": "DPM++ 2M Karras", "seed": -1},
                       timeout=180)
    except Exception as e:
        raise SDError(f"SD WebUI 호출 실패: {type(e).__name__}")
    if r.status_code != 200:
        raise SDError(f"SD WebUI HTTP {r.status_code}")
    images = r.json().get("images") or []
    if not images:
        raise SDError("SD WebUI가 이미지를 반환하지 않음")
    return base64.b64decode(images[0])
```

- [ ] **Step 4: 테스트 통과 확인** — 4 PASS + 전체 1회
- [ ] **Step 5: Commit**

```bash
git add server/core/config.py server/core/sd_webui.py server/tests/test_sd_webui.py .env.example
git commit -m "feat(blog-reels): SD WebUI 클라이언트 — txt2img·available·SDError"
```

---

### Task 3: 이미지 생성·캐시·폴백 (image_gen)

**Files:**
- Modify: `server/requirements.txt` (Pillow 추가)
- Modify: `server/core/db.py` (images 캐시 테이블)
- Create: `server/core/image_gen.py`
- Test: `server/tests/test_image_gen.py`

**Interfaces:**
- Consumes: `sd_webui.txt2img/SDError`, `style_packs.load/pick/COMMON_NEGATIVE`, `core.db.get_conn`
- Produces: DB `images(hash TEXT PRIMARY KEY, style_id, prompt, width, height, file, created_at)` · `image_gen.SIZE = {"reels": (576,1024), "long": (1024,576)}` · `image_gen.images_dir() -> Path`(env `APP_IMAGES_DIR` 우선, 기본 server/data/images, mkdir) · `image_gen.generate(conn, image_prompt: str, style_id: str, fmt: str) -> dict{file: str, cached: bool, fallback: bool}`(캐시 조회→txt2img→저장→INSERT; SDError 시 그라디언트 폴백 파일 생성, 폴백은 캐시 테이블에 넣지 않는다 — SD 복구 후 재생성 가능해야 하므로) · `image_gen.gradient_card(color_hex: str, width: int, height: int) -> bytes`(Pillow 세로 그라디언트 PNG)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_image_gen.py`:
```python
from core import image_gen, sd_webui

PNG = b"\x89PNG_fake"

def _setup_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_IMAGES_DIR", str(tmp_path / "imgs"))

def test_generate_saves_and_caches(db, monkeypatch, tmp_path):
    _setup_dir(monkeypatch, tmp_path)
    calls = []
    def fake(prompt, negative, width, height):
        calls.append(prompt)
        return PNG
    monkeypatch.setattr(image_gen.sd_webui, "txt2img", fake)
    r1 = image_gen.generate(db, "a cozy room", "isometric", "reels")
    assert not r1["cached"] and not r1["fallback"]
    assert (tmp_path / "imgs").joinpath(r1["file"]).read_bytes() == PNG
    r2 = image_gen.generate(db, "a cozy room", "isometric", "reels")
    assert r2["cached"] and r2["file"] == r1["file"]
    assert len(calls) == 1                          # 캐시 재사용 — 재호출 없음

def test_generate_style_prefix_and_negative(db, monkeypatch, tmp_path):
    _setup_dir(monkeypatch, tmp_path)
    seen = {}
    def fake(prompt, negative, width, height):
        seen.update(prompt=prompt, negative=negative, width=width, height=height)
        return PNG
    monkeypatch.setattr(image_gen.sd_webui, "txt2img", fake)
    image_gen.generate(db, "busy street", "cinematic", "long")
    assert "cinematic photography" in seen["prompt"] and "busy street" in seen["prompt"]
    assert "text" in seen["negative"]               # 공통 네거티브
    assert (seen["width"], seen["height"]) == (1024, 576)

def test_generate_fallback_on_sd_error(db, monkeypatch, tmp_path):
    _setup_dir(monkeypatch, tmp_path)
    def boom(prompt, negative, width, height):
        raise sd_webui.SDError("down")
    monkeypatch.setattr(image_gen.sd_webui, "txt2img", boom)
    r = image_gen.generate(db, "anything", "flat_vector", "reels")
    assert r["fallback"] and r["file"]
    data = (tmp_path / "imgs").joinpath(r["file"]).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"          # 실제 PNG 그라디언트
    # 폴백은 캐시 미등록 → SD 복구 후 재생성 가능
    assert db.execute("SELECT COUNT(*) c FROM images").fetchone()["c"] == 0

def test_gradient_card_is_png():
    data = image_gen.gradient_card("#7c3aed", 64, 128)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/requirements.txt`에 `Pillow` 추가 후 `server\.venv\Scripts\pip install Pillow`.

`server/core/db.py` SCHEMA 끝에 추가:
```sql
CREATE TABLE IF NOT EXISTS images(
  hash TEXT PRIMARY KEY,
  style_id TEXT NOT NULL,
  prompt TEXT NOT NULL,
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  file TEXT NOT NULL,
  created_at TEXT
);
```

`server/core/image_gen.py`:
```python
"""이미지 생성·캐시·폴백 (spec §8). 캐시 키 = sha256(prompt|negative|style|WxH).
폴백(그라디언트 카드)은 캐시에 넣지 않는다 — SD 복구 후 같은 키로 재생성돼야 한다."""
import datetime
import hashlib
import io
import os
import pathlib

from PIL import Image

from . import sd_webui, style_packs

SIZE = {"reels": (576, 1024), "long": (1024, 576)}


def images_dir() -> pathlib.Path:
    p = os.environ.get("APP_IMAGES_DIR")
    d = pathlib.Path(p) if p else \
        pathlib.Path(__file__).resolve().parents[1] / "data" / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gradient_card(color_hex: str, width: int, height: int) -> bytes:
    r, g, b = _hex_rgb(color_hex)
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        row = (int(r * (0.35 + 0.5 * t)), int(g * (0.35 + 0.5 * t)),
               int(b * (0.35 + 0.5 * t)))
        for x in range(width):
            px[x, y] = row
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate(conn, image_prompt: str, style_id: str, fmt: str) -> dict:
    packs = style_packs.load()
    pack = packs.get(style_id) or packs["flat_vector"]
    width, height = SIZE[fmt]
    prompt = f"{pack['prefix']}, {image_prompt}" if image_prompt else pack["prefix"]
    negative = f"{style_packs.COMMON_NEGATIVE}, {pack['negative']}".strip(", ")
    key = hashlib.sha256(
        f"{prompt}|{negative}|{style_id}|{width}x{height}".encode()).hexdigest()[:32]

    row = conn.execute("SELECT file FROM images WHERE hash=?", (key,)).fetchone()
    if row and (images_dir() / row["file"]).exists():
        return {"file": row["file"], "cached": True, "fallback": False}

    fname = f"{key}.png"
    try:
        data = sd_webui.txt2img(prompt, negative, width, height)
    except sd_webui.SDError:
        data = gradient_card(pack["color"], width, height)
        fb = f"fb_{key}.png"
        (images_dir() / fb).write_bytes(data)
        return {"file": fb, "cached": False, "fallback": True}

    (images_dir() / fname).write_bytes(data)
    conn.execute("""INSERT OR REPLACE INTO images(hash, style_id, prompt, width,
                    height, file, created_at) VALUES(?,?,?,?,?,?,?)""",
                 (key, style_id, prompt, width, height, fname,
                  datetime.datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return {"file": fname, "cached": False, "fallback": False}
```

- [ ] **Step 4: 테스트 통과 확인** — 4 PASS + 전체 1회
- [ ] **Step 5: Commit**

```bash
git add server/requirements.txt server/core/db.py server/core/image_gen.py server/tests/test_image_gen.py
git commit -m "feat(blog-reels): 이미지 생성·캐시·그라디언트 폴백 — 폴백 미캐시"
```

---

### Task 4: 잡 러너 + 이미지 API + 정적 서빙

**Files:**
- Modify: `server/core/db.py` (jobs 테이블)
- Create: `server/core/jobs.py`
- Create: `server/api/images.py`
- Modify: `server/main.py` (라우터 등록 + StaticFiles 마운트)
- Test: `server/tests/test_images_api.py`

**Interfaces:**
- Consumes: `image_gen.generate/images_dir/SIZE`, `style_packs.pick`, `core.db.get_conn`, scripts 테이블(M2)
- Produces: DB `jobs(id, kind, status CHECK('running','done','error'), progress, total, result_json, error, created_at)` · `jobs.start(kind: str, total: int, work: Callable[[JobCtx], dict]) -> int`(스레드 실행; JobCtx.tick()으로 progress+1; work 반환 dict→result_json; 예외→status error) · `jobs.get(jid) -> dict` · REST: `POST /api/scripts/{sid}/images` → `{job_id}`(씬별 스타일 매핑→generate→scenes_json의 각 씬에 `image_file`·`image_fallback` 기록; 이미 image_file 있는 씬은 건너뜀, `{force:true}`면 전부 재생성) · `GET /api/jobs/{jid}` · `POST /api/scripts/{sid}/scenes/{idx}/image` → 단일 씬 동기 재생성(캐시 우회 위해 항상 새로 생성 — 프롬프트가 같아도 seed -1이므로 캐시 키에 `|r{n}` 리트라이 솔트 추가) · main.py에 `/images` StaticFiles 마운트
- 주의: 잡 스레드는 자체 `get_conn()`을 열고 닫는다(SQLite 커넥션은 스레드 간 공유 금지). scripts 조회·갱신도 잡 안에서 수행

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_images_api.py`:
```python
import json
import time
from fastapi.testclient import TestClient

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("APP_IMAGES_DIR", str(tmp_path / "imgs"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def _make_script(c, monkeypatch):
    import api.discover as disc
    monkeypatch.setattr(disc.naver, "search_blog", lambda q, display=10: [
        {"source": "naver", "title": "전세 보증보험 총정리",
         "url": "https://blog.naver.com/a/1", "summary": "",
         "blogger": "b", "posted_at": "20260810"}])
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: [])
    monkeypatch.setattr(disc.google_search, "available", lambda: True)
    monkeypatch.setattr(disc.crawler, "fetch_content",
                        lambda url: "보증료는 연 0.128%다.")
    c.post("/api/categories/1/discover", json={"keyword": "전세"})
    ids = [p["id"] for p in c.get("/api/categories/1/posts").json()]
    import api.scripts as sc
    from core import storyboard
    monkeypatch.setattr(sc.gemini, "available", lambda: True)
    def fake_generate(posts, fmt, duration):
        scenes = storyboard.build_scenes(fmt, duration, [])
        for s in scenes:
            s["caption"] = "자막"
            s["narration"] = "나레이션"
            s["image_prompt"] = "cozy room"
        return {"scenes": scenes, "fact_sheet": [], "chapters": [],
                "diag": {"score": 2, "verdict": "회색 소", "answers": [],
                         "hooks": [], "weak": []}}
    monkeypatch.setattr(sc.script_gen, "generate_script", fake_generate)
    return c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                        "fmt": "reels", "duration": 30}).json()["id"]

def _wait_job(c, jid, timeout=10):
    for _ in range(timeout * 20):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise TimeoutError

def test_images_job_fills_scenes(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img",
                        lambda p, n, w, h: b"\x89PNG_x")
    jid = c.post(f"/api/scripts/{sid}/images").json()["job_id"]
    j = _wait_job(c, jid)
    assert j["status"] == "done" and j["progress"] == j["total"] == 7
    scenes = c.get(f"/api/scripts/{sid}").json()["scenes"]
    assert all(s["image_file"] for s in scenes)
    assert not any(s["image_fallback"] for s in scenes)

def test_images_job_skips_existing_unless_force(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    calls = []
    def fake(p, n, w, h):
        calls.append(p)
        return b"\x89PNG_x"
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img", fake)
    _wait_job(c, c.post(f"/api/scripts/{sid}/images").json()["job_id"])
    n1 = len(calls)
    _wait_job(c, c.post(f"/api/scripts/{sid}/images").json()["job_id"])
    assert len(calls) == n1                    # 전부 채워져 있어 스킵
    _wait_job(c, c.post(f"/api/scripts/{sid}/images",
                        json={"force": True}).json()["job_id"])
    assert len(calls) > n1                     # force는 재생성

def test_images_job_fallback_marks_scene(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    from core import sd_webui
    def boom(p, n, w, h):
        raise sd_webui.SDError("down")
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img", boom)
    j = _wait_job(c, c.post(f"/api/scripts/{sid}/images").json()["job_id"])
    assert j["status"] == "done"               # 폴백이라 잡은 성공
    scenes = c.get(f"/api/scripts/{sid}").json()["scenes"]
    assert all(s["image_fallback"] for s in scenes)

def test_single_scene_regen(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img",
                        lambda p, n, w, h: b"\x89PNG_y")
    r = c.post(f"/api/scripts/{sid}/scenes/0/image").json()
    assert r["image_file"]
    scenes = c.get(f"/api/scripts/{sid}").json()["scenes"]
    assert scenes[0]["image_file"] == r["image_file"]

def test_job_404(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    assert c.get("/api/jobs/999").status_code == 404
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/db.py` SCHEMA 끝에 추가:
```sql
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running' CHECK(status IN('running','done','error')),
  progress INTEGER DEFAULT 0,
  total INTEGER DEFAULT 0,
  result_json TEXT DEFAULT '{}',
  error TEXT DEFAULT '',
  created_at TEXT
);
```

`server/core/jobs.py`:
```python
"""최소 잡 러너 (spec §8 — §3 잡 큐의 M3 최소형). 스레드 1개/잡.
SQLite 커넥션은 스레드 간 공유 금지 — 잡 스레드가 자체 커넥션을 연다."""
import datetime
import json
import threading

from .db import get_conn


class JobCtx:
    def __init__(self, jid: int):
        self.jid = jid

    def tick(self) -> None:
        conn = get_conn()
        try:
            conn.execute("UPDATE jobs SET progress = progress + 1 WHERE id=?",
                         (self.jid,))
            conn.commit()
        finally:
            conn.close()


def start(kind: str, total: int, work) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO jobs(kind, total, created_at) VALUES(?,?,?)",
            (kind, total, datetime.datetime.now().isoformat(timespec="seconds")))
        conn.commit()
        jid = cur.lastrowid
    finally:
        conn.close()

    def _run():
        ctx = JobCtx(jid)
        conn = get_conn()
        try:
            result = work(ctx)
            conn.execute("UPDATE jobs SET status='done', result_json=? WHERE id=?",
                         (json.dumps(result or {}, ensure_ascii=False), jid))
            conn.commit()
        except Exception as e:
            conn.execute("UPDATE jobs SET status='error', error=? WHERE id=?",
                         (f"{type(e).__name__}: {e}", jid))
            conn.commit()
        finally:
            conn.close()

    threading.Thread(target=_run, daemon=True).start()
    return jid


def get(jid: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
```

`server/api/images.py`:
```python
import json
import secrets
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.db import get_conn
from core import image_gen, jobs, style_packs

router = APIRouter(prefix="/api", tags=["images"])


class ImagesIn(BaseModel):
    force: bool = False


def _load_script(conn, sid: int):
    row = conn.execute("SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
    if not row:
        raise HTTPException(404, "script not found")
    return row


def _category_name(conn, cid: int) -> str:
    row = conn.execute("SELECT name FROM categories WHERE id=?", (cid,)).fetchone()
    return row["name"] if row else ""


def _gen_for_scene(conn, scene: dict, category: str, fmt: str,
                   salt: str = "") -> None:
    style = style_packs.pick(scene["role"], category)
    prompt = (scene.get("image_prompt") or "") + (f" |r{salt}" if salt else "")
    r = image_gen.generate(conn, prompt, style, fmt)
    scene["image_file"] = r["file"]
    scene["image_fallback"] = r["fallback"]


@router.post("/scripts/{sid}/images")
def generate_images(sid: int, body: ImagesIn | None = None):
    force = bool(body and body.force)
    conn = get_conn()
    try:
        row = _load_script(conn, sid)
        scenes = json.loads(row["scenes_json"])
        todo = [s for s in scenes
                if force or not s.get("image_file")]
        fmt, cid = row["fmt"], row["category_id"]
    finally:
        conn.close()

    def work(ctx: jobs.JobCtx) -> dict:
        conn = get_conn()
        try:
            row = _load_script(conn, sid)
            scenes = json.loads(row["scenes_json"])
            category = _category_name(conn, cid)
            done = 0
            for scene in scenes:
                if not force and scene.get("image_file"):
                    continue
                # force는 캐시를 우회해 새 이미지를 뽑아야 하므로 리트라이 솔트 부여
                _gen_for_scene(conn, scene, category, fmt,
                               salt=secrets.token_hex(3) if force else "")
                done += 1
                ctx.tick()
                conn.execute("UPDATE scripts SET scenes_json=? WHERE id=?",
                             (json.dumps(scenes, ensure_ascii=False), sid))
                conn.commit()
            return {"generated": done}
        finally:
            conn.close()

    return {"job_id": jobs.start("images", len(todo), work)}


@router.get("/jobs/{jid}")
def get_job(jid: int):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404, "job not found")
    return j


@router.post("/scripts/{sid}/scenes/{idx}/image")
def regen_scene_image(sid: int, idx: int):
    conn = get_conn()
    try:
        row = _load_script(conn, sid)
        scenes = json.loads(row["scenes_json"])
        target = next((s for s in scenes if s["idx"] == idx), None)
        if not target:
            raise HTTPException(404, "scene not found")
        _gen_for_scene(conn, target, _category_name(conn, row["category_id"]),
                       row["fmt"], salt=secrets.token_hex(3))
        conn.execute("UPDATE scripts SET scenes_json=? WHERE id=?",
                     (json.dumps(scenes, ensure_ascii=False), sid))
        conn.commit()
        return target
    finally:
        conn.close()
```

`server/main.py`에 추가:
```python
from fastapi.staticfiles import StaticFiles
from api.images import router as images_router
from core.image_gen import images_dir
app.include_router(images_router)
app.mount("/images", StaticFiles(directory=str(images_dir())), name="images")
```
(주의: `images_dir()`는 env를 읽으므로 마운트는 app 생성 시점 env 기준 — 테스트의 reload(main) 전 `APP_IMAGES_DIR` setenv가 선행돼야 한다. make_client가 이미 그렇게 한다.)

- [ ] **Step 4: 테스트 통과 확인** — 5 PASS + 전체 1회
- [ ] **Step 5: Commit**

```bash
git add server/core/db.py server/core/jobs.py server/api/images.py server/main.py server/tests/test_images_api.py
git commit -m "feat(blog-reels): 이미지 잡 러너·씬 일괄/단일 생성 API·정적 서빙"
```

---

### Task 5: 스토리보드 이미지 UI + README

**Files:**
- Modify: `web/src/api.ts` (Scene에 image 필드·이미지 API 헬퍼·Job 타입)
- Modify: `web/src/pages/Storyboard.tsx` (썸네일·생성 버튼·진행 폴링·씬 재생성)
- Modify: `web/src/index.css` (썸네일·진행 바)
- Modify: `README.md` (M3 사용법)

**Interfaces:**
- Consumes: Task 4 REST
- Produces: Storyboard에 씬 썸네일(`/images/<file>`), "🎨 이미지 생성" 버튼(잡 시작→1초 폴링→완료 시 리로드), 씬별 "🖼 재생성", 폴백 씬 표시(⚠)

- [ ] **Step 1: 구현**

`web/src/api.ts` — Scene에 필드 추가 + 헬퍼:
```ts
// Scene 인터페이스에 추가:
  image_file?: string; image_fallback?: boolean
// 파일 하단에 추가:
export interface Job {
  id: number; kind: string; status: 'running' | 'done' | 'error'
  progress: number; total: number; error: string
}
export const startImages = (sid: number, force = false) =>
  fetch(`/api/scripts/${sid}/images`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force }) }).then(r => j<{ job_id: number }>(r))
export const getJob = (id: number) =>
  fetch(`/api/jobs/${id}`).then(r => j<Job>(r))
export const regenSceneImage = (sid: number, idx: number) =>
  fetch(`/api/scripts/${sid}/scenes/${idx}/image`, { method: 'POST' })
    .then(r => j<Scene>(r))
```

`web/src/pages/Storyboard.tsx` — 변경점:
- import에 `type Job, getJob, regenSceneImage, startImages` 추가, 상태 추가:
```tsx
  const [imgJob, setImgJob] = useState<Job | null>(null)
```
- 잡 폴링 함수 (컴포넌트 안):
```tsx
  const runImages = async (force = false) => {
    try {
      const { job_id } = await startImages(sid, force)
      const poll = async () => {
        const jb = await getJob(job_id)
        setImgJob(jb)
        if (jb.status === 'running') { setTimeout(poll, 1000); return }
        if (jb.status === 'error') alert(`이미지 생성 실패: ${jb.error}`)
        setScript(await getScript(sid))
      }
      poll()
    } catch (e) { alert(`이미지 생성 시작 실패: ${e}`) }
  }
```
- h1 아래에 버튼·진행 바:
```tsx
      <div className="make-bar">
        <button disabled={imgJob?.status === 'running'}
                onClick={() => runImages(false)}>
          {imgJob?.status === 'running'
            ? `🎨 생성 중… ${imgJob.progress}/${imgJob.total}`
            : '🎨 이미지 생성'}
        </button>
        <button className="ghost" disabled={imgJob?.status === 'running'}
                onClick={() => runImages(true)}>전부 재생성</button>
      </div>
```
- 씬 카드(.scene) 안, scene-head 아래에 썸네일 블록:
```tsx
          {s.image_file && (
            <div className="scene-img">
              <img src={`/images/${s.image_file}`} alt="" loading="lazy" />
              {s.image_fallback && <span className="fb-badge">⚠ 폴백</span>}
              <button className="ghost" disabled={busy !== null}
                      onClick={async () => {
                        try {
                          const ns = await regenSceneImage(sid, s.idx)
                          setScript(prev => prev && { ...prev,
                            scenes: prev.scenes.map(x => x.idx === s.idx ? ns : x) })
                        } catch (e) { alert(`재생성 실패: ${e}`) }
                      }}>🖼 재생성</button>
            </div>
          )}
```

`web/src/index.css`에 추가:
```css
.scene-img { display: flex; gap: 10px; align-items: flex-start; }
.scene-img img { width: 96px; border-radius: 8px; border: 1px solid #262b36; }
.fb-badge { font-size: 11px; color: #f59e0b; }
```

`README.md` M2.5 섹션 뒤에 추가:
```markdown
### M3 — 씬 이미지 생성

`.env`의 `SD_WEBUI_URL`(기본 http://127.0.0.1:7860)로 로컬 SD WebUI에 연결
(D:\sd-webui\start-api.bat 로 API 모드 실행). 스토리보드에서 "🎨 이미지 생성"
→ 씬별 스타일팩 자동 매핑 → 진행률 표시. SD가 꺼져 있으면 그라디언트 카드로
대체되고(⚠ 폴백), SD를 켠 뒤 "전부 재생성"으로 채울 수 있다.
```

- [ ] **Step 2: 검증** — `cd web; npm run build` 통과 + 서버 pytest 전체 1회.

- [ ] **Step 3: Commit**

```bash
git add web/src/ README.md
git commit -m "feat(blog-reels): 스토리보드 이미지 UI — 잡 진행률·썸네일·씬 재생성"
```

---

## M3 완료 기준 (spec §8·§12 마일스톤 3)

- [ ] 스타일팩 6종이 JSON 정의로 존재, 씬 롤·카테고리 자동 매핑 동작
- [ ] "이미지 생성" 잡이 씬 전체를 채우고 진행률 폴링, 캐시 재사용(동일 프롬프트 재호출 없음)
- [ ] SD 다운 시 그라디언트 폴백으로 진행(잡 성공·⚠ 표시), 폴백은 캐시 미등록
- [ ] 단일 씬 이미지 재생성 동작
- [ ] `pytest server/tests` 전부 통과(SD 없이 오프라인), `npm run build` 통과
- [ ] 실생성 스모크(SD WebUI 켜고 릴스 1건)는 사용자 수동 확인 항목

M4(릴스 렌더 — 자막 PNG·ffmpeg 합성)는 M3 완료 후 별도 계획서로 작성한다.
