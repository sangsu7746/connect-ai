# 블로그 리뉴얼 릴스 제작기 — M4 (릴스 렌더) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 씬 이미지+자막을 Pillow·네이티브 ffmpeg로 합성해 첫 영상 파일(릴스 1080×1920)을 산출하고, 스토리보드에서 렌더 잡 진행·미리보기·다운로드까지 연결한다. M3에서 파킹한 scenes_json 경합 창도 공용 락으로 마감한다.

**Architecture:** scenes_lock(파킹 마감) → captions(Pillow 자막 PNG: 중앙/로어서드+스크림, 맑은고딕) → bgm(무드별 로컬 mp3 결정론 선택) → renderer(EstateReels 검증 구조 이식: 씬 클립(zoompan Ken Burns+자막 overlay+무음)→concat -c copy→BGM 먹싱, 폴백·길이 클램프) → renders 테이블+render API(jobs 재사용, ref 잠금) → Storyboard UI(렌더 버튼·진행·video 미리보기).

**Tech Stack:** M3와 동일 + 시스템 ffmpeg 8.1.2(확인됨, PATH), 맑은고딕(C:\Windows\Fonts\malgun*.ttf 확인됨). BGM은 `D:\부동산릴스-EstateReels-v2\public\bgm`(무드 4종×6곡)을 `server/data/bgm/`으로 복사(사용자 소유 자산, data는 git 미추적).

**Spec:** `docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md` §9(렌더링)·§10

## Global Constraints

- 해상도: 릴스 **1080×1920**, 롱폼 **1920×1080** (spec §9 — 렌더러는 fmt 불문 동작, M4 완료 기준은 릴스)
- ffmpeg 파라미터(정확히): fps **25**, zoompan `z='min(zoom+0.0011,1.16)'`(EstateReels 이식), `libx264 -preset veryfast -pix_fmt yuv420p`, 소스는 1.25배 스케일 후 zoompan (spec §9)
- concat은 `-c copy` 우선, 실패 시 재인코딩 폴백 — **양쪽 모두 길이 클램프 적용**(M1 최종 리뷰의 EstateReels 버그 교훈)
- BGM 볼륨 **0.28**, 루프(`-stream_loop -1`)+`-shortest`. BGM 파일 없으면 무음 진행(멈추지 않음)
- 자막(spec §9): hook/cta = 중앙 대형(볼드), 그 외 = 하단 로어서드, 하단 스크림 그라디언트. 폰트 폴백: malgunbd → malgun → Pillow 기본
- image_file 없는 씬은 스타일 그라디언트 카드를 즉석 생성해 렌더 계속 (spec §10)
- 렌더는 잡(kind `render`, ref `str(sid)` — 이미지 잡과 별개 kind지만 **렌더 중 이미지 잡·이미지 잡 중 렌더 모두 409**: scenes_json·GPU 공유)
- 산출물: `server/data/videos/<sid>_<render_id>.mp4`, 정적 서빙 `/videos`
- **scenes_lock**: `core/locks.py`의 프로세스 공용 `threading.Lock`을 images.py·scripts.py의 fresh-read→병합→쓰기 구간에 적용 (M3 파킹 마감 — mutate/Gemini/SD 호출은 락 밖)
- ffmpeg 호출은 mock 테스트(오프라인 CI) + **로컬 실렌더 스모크 1회는 구현 태스크가 수행**(ffmpeg 존재 확인됨 — 2씬 5초, ffprobe로 길이 검증)
- web은 verbatimModuleSyntax. 커밋은 태스크마다, 변경 파일만 add, 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 테스트: `server/.venv/Scripts/python.exe -m pytest server/tests -v` (PYTHONUTF8=1 필요 시)

---

### Task 1: scenes_lock — M3 파킹 경합 마감

**Files:**
- Create: `server/core/locks.py`
- Modify: `server/api/images.py` (병합 쓰기 구간 락)
- Modify: `server/api/scripts.py` (_update_scene 병합 쓰기 구간 락)
- Test: `server/tests/test_scenes_lock.py`

**Interfaces:**
- Produces: `locks.scenes_lock: threading.Lock` — scenes_json에 쓰는 모든 코드(이후 renderer 포함)가 fresh-read→병합→UPDATE→commit 구간을 `with locks.scenes_lock:`으로 감싼다. 느린 작업(SD·Gemini 호출)은 락 밖

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_scenes_lock.py`:
```python
import threading
from core import locks

def test_scenes_lock_exists_and_is_lock():
    assert isinstance(locks.scenes_lock, type(threading.Lock()))

def test_images_and_scripts_use_lock(monkeypatch):
    # 소스 검사: 병합-쓰기 구간이 락을 잡는지 (정적 확인 — 동작 경합은 M3 회귀 테스트가 커버)
    import inspect
    import api.images as im
    import api.scripts as sc
    assert "scenes_lock" in inspect.getsource(im)
    assert "scenes_lock" in inspect.getsource(sc._update_scene)
```

- [ ] **Step 2: 실패 확인** — Run: `server\.venv\Scripts\python -m pytest server/tests/test_scenes_lock.py -v`, Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/locks.py`:
```python
"""프로세스 공용 락. scenes_json은 이미지 잡·텍스트 편집·렌더가 함께 쓰므로
fresh-read→병합→쓰기 구간을 직렬화한다 (M3 최종 리뷰 파킹 항목 마감).
단일 프로세스(uvicorn 1 워커 + 스레드 잡) 전제 — 느린 I/O(SD·Gemini·ffmpeg)는
락 밖에서 수행하고, ms 단위의 병합 구간만 락 안에 둔다."""
import threading

scenes_lock = threading.Lock()
```

`server/api/images.py` — `work()` 루프의 병합 쓰기 구간을 락으로 감싼다 (SD 호출 `_gen_for_scene`은 락 **밖**, 그 결과를 병합하는 fresh read+UPDATE만 안):
```python
# import 추가
from core.locks import scenes_lock
```
`work()` 루프 본문을 다음 구조로 조정 — `_gen_for_scene`이 씬 dict를 직접 갱신하므로, 생성은 스테일 사본으로 하고 결과 필드만 락 안에서 병합:
```python
            for idx in todo:
                row = _load_script(conn, sid)
                scenes = json.loads(row["scenes_json"])
                scene = next((s for s in scenes if s["idx"] == idx), None)
                if scene is None:
                    continue
                _gen_for_scene(conn, scene, category, fmt,
                               salt=secrets.token_hex(3) if force else "")
                with scenes_lock:
                    fresh_row = conn.execute(
                        "SELECT scenes_json FROM scripts WHERE id=?",
                        (sid,)).fetchone()
                    fresh = json.loads(fresh_row["scenes_json"])
                    ft = next((s for s in fresh if s["idx"] == idx), None)
                    if ft is not None:
                        ft["image_file"] = scene["image_file"]
                        ft["image_fallback"] = scene["image_fallback"]
                        conn.execute("UPDATE scripts SET scenes_json=? WHERE id=?",
                                     (json.dumps(fresh, ensure_ascii=False), sid))
                        conn.commit()
                done += 1
                ctx.tick()
```
(현재 코드가 이미 fresh-merge 구조라면 그 구간에 `with scenes_lock:`만 씌우는 최소 변경으로 충분 — 구조가 위와 다르면 실코드에 맞춰 적용하고 report에 명시.)

`server/api/scripts.py` — `_update_scene`의 fresh read→병합→UPDATE→commit 구간을 `with scenes_lock:`으로 감싼다 (mutate 호출은 락 밖 유지).

- [ ] **Step 4: 테스트 통과 확인** — 신규 2개 + **기존 전체 146개**(특히 test_job_preserves_concurrent_text_edit) PASS. 경합 테스트 5회 반복 실행도 통과 확인
- [ ] **Step 5: Commit**

```bash
git add server/core/locks.py server/api/images.py server/api/scripts.py server/tests/test_scenes_lock.py
git commit -m "fix(blog-reels): scenes_lock — scenes_json 병합 쓰기 직렬화 (M3 파킹 마감)"
```

---

### Task 2: 자막 PNG 렌더 (captions)

**Files:**
- Create: `server/core/captions.py`
- Test: `server/tests/test_captions.py`

**Interfaces:**
- Consumes: Pillow(설치됨)
- Produces: `captions.render_caption(caption: str, sub: str, role: str, width: int, height: int) -> bytes` — 프레임 크기 투명 RGBA PNG. hook/cta=중앙 대형, 그 외=하단 로어서드+스크림. `captions.load_font(size) -> ImageFont`(malgunbd→malgun→기본 폴백). Task 4 renderer가 소비

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_captions.py`:
```python
import io
from PIL import Image
from core import captions

def _img(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))

def test_png_rgba_frame_size():
    data = captions.render_caption("자막 테스트", "보조 자막", "point", 540, 960)
    img = _img(data)
    assert img.mode == "RGBA" and img.size == (540, 960)

def test_point_text_in_lower_third_with_scrim():
    data = captions.render_caption("하단 자막", "", "point", 540, 960)
    img = _img(data)
    alpha = img.split()[3]
    # 상단 1/3에는 불투명 픽셀이 없어야, 하단 1/3에는 있어야 한다
    top = alpha.crop((0, 0, 540, 320))
    bottom = alpha.crop((0, 640, 540, 960))
    assert max(top.getextrema()) == (0, 0) or top.getextrema()[1] == 0
    assert bottom.getextrema()[1] > 0

def test_hook_text_centered():
    data = captions.render_caption("중앙 훅", "", "hook", 540, 960)
    alpha = _img(data).split()[3]
    middle = alpha.crop((0, 320, 540, 640))
    assert middle.getextrema()[1] > 0

def test_empty_caption_returns_fully_transparent():
    data = captions.render_caption("", "", "point", 540, 960)
    alpha = _img(data).split()[3]
    assert alpha.getextrema() == (0, 0)

def test_font_fallback(monkeypatch):
    monkeypatch.setattr(captions, "FONT_CANDIDATES", ["Z:/no/such/font.ttf"])
    data = captions.render_caption("폴백", "", "cta", 540, 960)
    assert _img(data).size == (540, 960)          # 기본 폰트로도 동작
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/captions.py`:
```python
"""자막 PNG 렌더 (spec §9 — EstateReels captionCanvas 이식).
hook/cta는 중앙 대형, 나머지는 하단 로어서드 + 스크림 그라디언트.
프레임 크기 투명 PNG로 만들어 ffmpeg overlay 0:0 한 번으로 얹는다."""
import io

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"]

_CENTER_ROLES = ("hook", "cta")


def load_font(size: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw_outlined(draw, xy, text, font, fill):
    x, y = xy
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 220))
    draw.text((x, y), text, font=font, fill=fill)


def render_caption(caption: str, sub: str, role: str,
                   width: int, height: int) -> bytes:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if not (caption or sub):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    if role in _CENTER_ROLES:
        font = load_font(max(int(height * 0.048), 20))
        sub_font = load_font(max(int(height * 0.030), 14))
        lines = _wrap(draw, caption, font, int(width * 0.86))
        line_h = int(height * 0.062)
        total = len(lines) * line_h + (line_h if sub else 0)
        y = (height - total) // 2
        for line in lines:
            w = draw.textlength(line, font=font)
            _draw_outlined(draw, ((width - w) // 2, y), line, font,
                           (255, 255, 255, 255))
            y += line_h
        if sub:
            w = draw.textlength(sub, font=sub_font)
            _draw_outlined(draw, ((width - w) // 2, y), sub, sub_font,
                           (255, 224, 130, 255))
    else:
        # 하단 스크림 그라디언트 (하단 28% 영역)
        scrim_h = int(height * 0.28)
        for i in range(scrim_h):
            a = int(160 * (i / scrim_h))
            draw.line([(0, height - scrim_h + i), (width, height - scrim_h + i)],
                      fill=(0, 0, 0, a))
        font = load_font(max(int(height * 0.036), 16))
        sub_font = load_font(max(int(height * 0.026), 12))
        lines = _wrap(draw, caption, font, int(width * 0.9))
        line_h = int(height * 0.048)
        y = height - int(height * 0.06) - len(lines) * line_h - \
            (int(height * 0.036) if sub else 0)
        for line in lines:
            w = draw.textlength(line, font=font)
            _draw_outlined(draw, ((width - w) // 2, y), line, font,
                           (255, 255, 255, 255))
            y += line_h
        if sub:
            w = draw.textlength(sub, font=sub_font)
            _draw_outlined(draw, ((width - w) // 2, y), sub, sub_font,
                           (200, 200, 210, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 4: 테스트 통과 확인** — 5 PASS + 전체 1회
- [ ] **Step 5: Commit**

```bash
git add server/core/captions.py server/tests/test_captions.py
git commit -m "feat(blog-reels): 자막 PNG — 중앙/로어서드·스크림·맑은고딕 폴백"
```

---

### Task 3: BGM 선택기 + 자산 복사

**Files:**
- Create: `server/core/bgm.py`
- Test: `server/tests/test_bgm.py`
- (자산: `D:\부동산릴스-EstateReels-v2\public\bgm\*.mp3` 24개 → `server/data/bgm/`로 복사 — git 미추적)

**Interfaces:**
- Produces: `bgm.bgm_dir() -> Path`(env `APP_BGM_DIR` 우선, 기본 server/data/bgm) · `bgm.pick(category: str, seed: int) -> pathlib.Path | None` — 카테고리→무드(부동산·재테크·IT=documentary_calm, 요리·건강=family_warm, 여행=emotional_daily, 그 외=documentary_calm), 무드 파일들(`<mood>-*.mp3`) 중 seed 결정론 선택, 없으면 무드 불문 아무 mp3, 그것도 없으면 None

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_bgm.py`:
```python
from core import bgm

def _setup(monkeypatch, tmp_path):
    d = tmp_path / "bgm"
    d.mkdir()
    for name in ("documentary_calm-01.mp3", "documentary_calm-02.mp3",
                 "family_warm-01.mp3"):
        (d / name).write_bytes(b"mp3")
    monkeypatch.setenv("APP_BGM_DIR", str(d))
    return d

def test_pick_mood_and_deterministic(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    a = bgm.pick("부동산", seed=1)
    b = bgm.pick("부동산", seed=1)
    assert a == b and a.name.startswith("documentary_calm")
    c = bgm.pick("부동산", seed=2)
    assert c.name.startswith("documentary_calm")
    assert bgm.pick("요리", seed=1).name.startswith("family_warm")

def test_pick_falls_back_to_any_then_none(monkeypatch, tmp_path):
    d = _setup(monkeypatch, tmp_path)
    # 여행 무드(emotional_daily) 없음 → 아무 mp3
    assert bgm.pick("여행", seed=1) is not None
    for f in d.iterdir():
        f.unlink()
    assert bgm.pick("부동산", seed=1) is None
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현 + 자산 복사**

`server/core/bgm.py`:
```python
"""BGM 결정론 선택 (spec §9 — EstateReels bgmService 무드 구조 이식).
파일은 server/data/bgm/(git 미추적)에 두고, 없으면 무음 진행."""
import os
import pathlib

_MOOD = {"부동산": "documentary_calm", "재테크": "documentary_calm",
         "IT": "documentary_calm", "요리": "family_warm",
         "건강": "family_warm", "여행": "emotional_daily"}
_DEFAULT_MOOD = "documentary_calm"


def bgm_dir() -> pathlib.Path:
    p = os.environ.get("APP_BGM_DIR")
    d = pathlib.Path(p) if p else \
        pathlib.Path(__file__).resolve().parents[1] / "data" / "bgm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pick(category: str, seed: int) -> pathlib.Path | None:
    mood = _MOOD.get(category, _DEFAULT_MOOD)
    files = sorted(bgm_dir().glob(f"{mood}-*.mp3"))
    if not files:
        files = sorted(bgm_dir().glob("*.mp3"))
    if not files:
        return None
    return files[seed % len(files)]
```

자산 복사(구현 중 1회 실행):
```bash
mkdir -p "server/data/bgm"
cp "D:/부동산릴스-EstateReels-v2/public/bgm/"*.mp3 "server/data/bgm/"
```

- [ ] **Step 4: 테스트 통과 확인** — 2 PASS + 전체 1회. `ls server/data/bgm | wc -l` = 24 확인
- [ ] **Step 5: Commit** (mp3는 data라 미추적 — 코드·테스트만)

```bash
git add server/core/bgm.py server/tests/test_bgm.py
git commit -m "feat(blog-reels): BGM 선택기 — 무드 매핑·결정론·무음 폴백"
```

---

### Task 4: ffmpeg 렌더러 (renderer)

**Files:**
- Create: `server/core/renderer.py`
- Test: `server/tests/test_renderer.py`

**Interfaces:**
- Consumes: `captions.render_caption`, `image_gen.images_dir/gradient_card`, `style_packs.load/pick`, ffmpeg(PATH)
- Produces: `renderer.SIZE = {"reels": (1080, 1920), "long": (1920, 1080)}` · `renderer.render_script(scenes: list[dict], fmt: str, category: str, bgm_path: Path | None, out_path: Path, workdir: Path, on_scene=None) -> None`(씬별 클립 생성→concat→BGM 먹싱, `on_scene()` 콜백은 씬 클립 하나 완료마다 호출 — 잡 tick용. 실패 시 `RenderError`) · 내부: `_scene_clip(...)`, `_concat(...)`, `_mux_bgm(...)`, `_run(cmd)`(subprocess, 실패 시 stderr 꼬리 포함 RenderError)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_renderer.py`:
```python
import pathlib
import subprocess
from core import renderer

SCENES = [
    {"idx": 0, "role": "hook", "sec": 4.0, "chapter": "", "caption": "훅",
     "sub": "", "narration": "", "image_prompt": "", "image_file": "a.png"},
    {"idx": 1, "role": "cta", "sec": 3.0, "chapter": "", "caption": "구독",
     "sub": "", "narration": "", "image_prompt": "", "image_file": "b.png"},
]

def _setup(monkeypatch, tmp_path):
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    from core import image_gen
    (imgs / "a.png").write_bytes(image_gen.gradient_card("#7c3aed", 64, 114))
    (imgs / "b.png").write_bytes(image_gen.gradient_card("#34d399", 64, 114))
    monkeypatch.setenv("APP_IMAGES_DIR", str(imgs))
    calls = []
    def fake_run(cmd, capture_output=None, text=None, timeout=None, encoding=None):
        calls.append(cmd)
        # concat·클립 출력 파일을 흉내 낸다
        out = pathlib.Path(cmd[-1])
        out.write_bytes(b"fake")
        class R:
            returncode = 0
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls

def test_render_builds_expected_commands(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    out = tmp_path / "out.mp4"
    ticks = []
    renderer.render_script(SCENES, "reels", "부동산", None, out,
                           tmp_path / "work", on_scene=lambda: ticks.append(1))
    assert len(ticks) == 2                                # 씬 2개 tick
    joined = [" ".join(map(str, c)) for c in calls]
    clip_cmds = [c for c in joined if "zoompan" in c]
    assert len(clip_cmds) == 2
    assert "min(zoom+0.0011,1.16)" in clip_cmds[0]
    assert "libx264" in clip_cmds[0] and "veryfast" in clip_cmds[0]
    assert "1080x1920" in clip_cmds[0]                    # zoompan s=
    concat_cmds = [c for c in joined if "-f concat" in c]
    assert concat_cmds and "-c copy" in concat_cmds[0]
    assert out.exists()

def test_render_bgm_mux(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    bgm = tmp_path / "m.mp3"
    bgm.write_bytes(b"mp3")
    out = tmp_path / "out.mp4"
    renderer.render_script(SCENES, "reels", "부동산", bgm, out, tmp_path / "work")
    joined = [" ".join(map(str, c)) for c in calls]
    mux = [c for c in joined if "volume=0.28" in c]
    assert mux and "-stream_loop -1" in mux[0] and "-shortest" in mux[0]

def test_concat_falls_back_to_reencode(monkeypatch, tmp_path):
    calls = []
    from core import image_gen
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    (imgs / "a.png").write_bytes(image_gen.gradient_card("#7c3aed", 64, 114))
    (imgs / "b.png").write_bytes(image_gen.gradient_card("#34d399", 64, 114))
    monkeypatch.setenv("APP_IMAGES_DIR", str(imgs))
    import subprocess as sp
    def fake_run(cmd, capture_output=None, text=None, timeout=None, encoding=None):
        calls.append(cmd)
        joined = " ".join(map(str, cmd))
        class R:
            returncode = 1 if ("-f concat" in joined and "-c copy" in joined) else 0
            stderr = "copy failed"
        if R.returncode == 0:
            pathlib.Path(cmd[-1]).write_bytes(b"fake")
        return R()
    monkeypatch.setattr(sp, "run", fake_run)
    out = tmp_path / "out.mp4"
    renderer.render_script(SCENES, "reels", "부동산", None, out, tmp_path / "work")
    joined = [" ".join(map(str, c)) for c in calls]
    reenc = [c for c in joined if "-f concat" in c and "-c copy" not in c]
    assert reenc and "libx264" in reenc[0]                # 재인코딩 폴백

def test_missing_image_uses_gradient(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    scenes = [dict(SCENES[0], image_file="")]              # 이미지 없음
    renderer.render_script(scenes, "reels", "부동산", None,
                           tmp_path / "o.mp4", tmp_path / "work")
    # 그라디언트 카드가 workdir에 생성돼 클립 입력으로 쓰였는지
    assert any(p.name.startswith("grad_") for p in (tmp_path / "work").iterdir())

def test_run_raises_render_error_with_stderr(monkeypatch):
    import subprocess as sp
    def boom(cmd, capture_output=None, text=None, timeout=None, encoding=None):
        class R:
            returncode = 1
            stderr = "x" * 500
        return R()
    monkeypatch.setattr(sp, "run", boom)
    import pytest
    with pytest.raises(renderer.RenderError):
        renderer._run(["ffmpeg", "-i", "nope"])
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/renderer.py`:
```python
"""ffmpeg 렌더러 (spec §9 — EstateReels ffmpegService 2단계 구조 이식).
① 씬 클립: 이미지 1.25배 스케일→zoompan(줌인)→자막 PNG overlay→무음 트랙
② concat -c copy(자막이 구워져 재인코딩 불필요) → 실패 시 재인코딩 폴백
③ BGM 먹싱(volume 0.28, 루프, -shortest). 양쪽 모두 길이 클램프."""
import pathlib
import subprocess

from . import bgm as _bgm  # noqa: F401  (호출부 참조용 — 직접 사용은 API 층)
from . import captions, image_gen, style_packs

SIZE = {"reels": (1080, 1920), "long": (1920, 1080)}
FPS = 25


class RenderError(RuntimeError):
    pass


def _run(cmd: list) -> None:
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       timeout=600, encoding="utf-8")
    if r.returncode != 0:
        tail = (r.stderr or "").strip()[-300:]
        raise RenderError(f"ffmpeg 실패 (exit {r.returncode}) — {tail}")


def _scene_image(scene: dict, category: str, fmt: str,
                 workdir: pathlib.Path) -> pathlib.Path:
    f = scene.get("image_file") or ""
    p = image_gen.images_dir() / f if f else None
    if p and p.exists():
        return p
    style = style_packs.load().get(
        style_packs.pick(scene["role"], category), {"color": "#4b5563"})
    w, h = image_gen.SIZE[fmt]
    out = workdir / f"grad_{scene['idx']}.png"
    out.write_bytes(image_gen.gradient_card(style["color"], w, h))
    return out


def _scene_clip(scene: dict, img: pathlib.Path, cap_png: pathlib.Path,
                fmt: str, workdir: pathlib.Path) -> pathlib.Path:
    w, h = SIZE[fmt]
    dur = max(float(scene["sec"]), 0.5)
    frames = max(int(dur * FPS), 1)
    out = workdir / f"clip_{scene['idx']:03d}.mp4"
    vf = (f"[0:v]scale={int(w * 1.25)}:{int(h * 1.25)},"
          f"zoompan=z='min(zoom+0.0011,1.16)':d={frames}:s={w}x{h}:fps={FPS}[bg];"
          f"[bg][1:v]overlay=0:0[v]")
    _run(["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", cap_png,
          "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
          "-filter_complex", vf, "-map", "[v]", "-map", "2:a",
          "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out])
    return out


def _concat(clips: list[pathlib.Path], total_sec: float, out: pathlib.Path,
            workdir: pathlib.Path) -> None:
    lst = workdir / "concat.txt"
    lst.write_text("\n".join(f"file '{c.as_posix()}'" for c in clips),
                   encoding="utf-8")
    base = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
            "-t", f"{total_sec:.2f}"]
    try:
        _run(base + ["-c", "copy", out])
    except RenderError:
        _run(base + ["-c:v", "libx264", "-preset", "veryfast",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", out])


def _mux_bgm(video: pathlib.Path, bgm_path: pathlib.Path, total_sec: float,
             out: pathlib.Path) -> None:
    _run(["ffmpeg", "-y", "-i", video, "-stream_loop", "-1", "-i", bgm_path,
          "-filter_complex", "[1:a]volume=0.28[b]",
          "-map", "0:v", "-map", "[b]", "-c:v", "copy", "-c:a", "aac",
          "-t", f"{total_sec:.2f}", "-shortest", out])


def render_script(scenes: list[dict], fmt: str, category: str,
                  bgm_path: pathlib.Path | None, out_path: pathlib.Path,
                  workdir: pathlib.Path, on_scene=None) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w, h = SIZE[fmt]
    total = sum(float(s["sec"]) for s in scenes)
    clips = []
    for scene in scenes:
        img = _scene_image(scene, category, fmt, workdir)
        cap = workdir / f"cap_{scene['idx']:03d}.png"
        cap.write_bytes(captions.render_caption(
            scene.get("caption") or "", scene.get("sub") or "",
            scene["role"], w, h))
        clips.append(_scene_clip(scene, img, cap, fmt, workdir))
        if on_scene:
            on_scene()
    if bgm_path:
        tmp = workdir / "noaudio.mp4"
        _concat(clips, total, tmp, workdir)
        try:
            _mux_bgm(tmp, bgm_path, total, out_path)
        except RenderError:
            tmp.replace(out_path)                          # BGM 실패 → 무음 진행
    else:
        _concat(clips, total, out_path, workdir)
```

- [ ] **Step 4: 테스트 통과 확인** — 6 PASS + 전체 1회

- [ ] **Step 5: 로컬 실렌더 스모크 (ffmpeg 실사용 — 이 태스크에서 수행)**

임시 파이썬 스크립트로 2씬(그라디언트 이미지) 릴스를 실제 렌더:
```bash
server\.venv\Scripts\python -c "import sys; sys.path.insert(0,'server'); import pathlib, tempfile; from core import renderer, image_gen; import os; td=pathlib.Path(tempfile.mkdtemp()); os.environ['APP_IMAGES_DIR']=str(td/'i'); (td/'i').mkdir(); (td/'i'/'a.png').write_bytes(image_gen.gradient_card('#7c3aed',540,960)); scenes=[{'idx':0,'role':'hook','sec':2.5,'chapter':'','caption':'실렌더 스모크','sub':'','image_file':'a.png'},{'idx':1,'role':'point','sec':2.5,'chapter':'','caption':'둘째 씬','sub':'부제','image_file':'a.png'}]; renderer.render_script(scenes,'reels','부동산',None,td/'out.mp4',td/'w'); print('OK', (td/'out.mp4').stat().st_size)"
```
이후 `ffprobe -v error -show_entries format=duration -of csv=p=0 <out.mp4>` 로 길이 ≈5.0 확인. 결과(파일 크기·길이)를 report에 기록.

- [ ] **Step 6: Commit**

```bash
git add server/core/renderer.py server/tests/test_renderer.py
git commit -m "feat(blog-reels): ffmpeg 렌더러 — 씬 클립·concat 폴백·BGM 먹싱 (실렌더 스모크 통과)"
```

---

### Task 5: renders 테이블 + render API

**Files:**
- Modify: `server/core/db.py` (renders 테이블)
- Create: `server/api/render.py`
- Modify: `server/main.py` (라우터 + /videos 정적 서빙)
- Test: `server/tests/test_render_api.py`

**Interfaces:**
- Consumes: `renderer.render_script/RenderError/SIZE`, `bgm.pick`, `jobs.start/get/has_running`, scripts 테이블
- Produces: DB `renders(id, script_id, file, duration_sec, created_at)` · REST `POST /api/scripts/{sid}/render` → `{job_id}`(렌더·이미지 잡 어느 쪽이든 실행 중이면 409 — kind 불문 ref=str(sid) 검사) · `GET /api/scripts/{sid}/renders` → `[{id, file, duration_sec, created_at}]` 최신순 · 잡 total=씬수+1(concat), result_json에 `{render_id, file}` · `videos_dir()`(env `APP_VIDEOS_DIR` 우선, 기본 server/data/videos) · main.py `/videos` 정적 서빙

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_render_api.py`:
```python
import time
from fastapi.testclient import TestClient

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("APP_IMAGES_DIR", str(tmp_path / "imgs"))
    monkeypatch.setenv("APP_VIDEOS_DIR", str(tmp_path / "vids"))
    monkeypatch.setenv("APP_BGM_DIR", str(tmp_path / "bgm"))
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

def test_render_job_creates_record(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.render as rd
    def fake_render(scenes, fmt, category, bgm_path, out_path, workdir,
                    on_scene=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp4")
        for _ in scenes:
            if on_scene:
                on_scene()
    monkeypatch.setattr(rd.renderer, "render_script", fake_render)
    jid = c.post(f"/api/scripts/{sid}/render").json()["job_id"]
    j = _wait_job(c, jid)
    assert j["status"] == "done"
    renders = c.get(f"/api/scripts/{sid}/renders").json()
    assert len(renders) == 1 and renders[0]["file"].endswith(".mp4")
    assert renders[0]["duration_sec"] == 30

def test_render_conflicts_with_image_job(monkeypatch, tmp_path):
    import threading
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    gate = threading.Event()
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img",
                        lambda p, n, w, h: (gate.wait(timeout=5), b"\x89PNG")[1])
    ijid = c.post(f"/api/scripts/{sid}/images").json()["job_id"]
    try:
        assert c.post(f"/api/scripts/{sid}/render").status_code == 409
    finally:
        gate.set()
    _wait_job(c, ijid)

def test_render_error_marks_job(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.render as rd
    from core.renderer import RenderError
    def boom(*a, **kw):
        raise RenderError("ffmpeg 실패")
    monkeypatch.setattr(rd.renderer, "render_script", boom)
    j = _wait_job(c, c.post(f"/api/scripts/{sid}/render").json()["job_id"])
    assert j["status"] == "error" and "ffmpeg" in j["error"]
    assert c.get(f"/api/scripts/{sid}/renders").json() == []
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/db.py` SCHEMA 끝에 추가:
```sql
CREATE TABLE IF NOT EXISTS renders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
  file TEXT NOT NULL,
  duration_sec INTEGER NOT NULL,
  created_at TEXT
);
```

`server/api/render.py`:
```python
import datetime
import json
import os
import pathlib
import tempfile

from fastapi import APIRouter, HTTPException

from core.db import get_conn
from core import bgm, jobs, renderer

router = APIRouter(prefix="/api", tags=["render"])


def videos_dir() -> pathlib.Path:
    p = os.environ.get("APP_VIDEOS_DIR")
    d = pathlib.Path(p) if p else \
        pathlib.Path(__file__).resolve().parents[1] / "data" / "videos"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/scripts/{sid}/render")
def start_render(sid: int):
    if jobs.has_running("images", str(sid)) or jobs.has_running("render", str(sid)):
        raise HTTPException(409, "이 스크립트의 잡이 이미 실행 중입니다 — 완료 후 다시 시도하세요")
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM scripts WHERE id=?", (sid,)).fetchone()
        if not row:
            raise HTTPException(404, "script not found")
        cat = conn.execute("SELECT name FROM categories WHERE id=?",
                           (row["category_id"],)).fetchone()
        category = cat["name"] if cat else ""
        fmt, duration = row["fmt"], row["duration_sec"]
    finally:
        conn.close()

    def work(ctx: jobs.JobCtx) -> dict:
        conn = get_conn()
        try:
            row = conn.execute("SELECT * FROM scripts WHERE id=?",
                               (sid,)).fetchone()
            scenes = json.loads(row["scenes_json"])
            ctx.set_total(len(scenes) + 1)
            bgm_path = bgm.pick(category, seed=sid)
            with tempfile.TemporaryDirectory(prefix=f"render_{sid}_") as td:
                now = datetime.datetime.now().isoformat(timespec="seconds")
                cur = conn.execute(
                    """INSERT INTO renders(script_id, file, duration_sec,
                       created_at) VALUES(?,?,?,?)""",
                    (sid, "", duration, now))
                conn.commit()
                rid = cur.lastrowid
                fname = f"{sid}_{rid}.mp4"
                out = videos_dir() / fname
                try:
                    renderer.render_script(scenes, fmt, category, bgm_path,
                                           out, pathlib.Path(td),
                                           on_scene=ctx.tick)
                except Exception:
                    conn.execute("DELETE FROM renders WHERE id=?", (rid,))
                    conn.commit()
                    raise
                conn.execute("UPDATE renders SET file=? WHERE id=?",
                             (fname, rid))
                conn.commit()
                ctx.tick()
                return {"render_id": rid, "file": fname}
        finally:
            conn.close()

    return {"job_id": jobs.start("render", 0, work, ref=str(sid))}


@router.get("/scripts/{sid}/renders")
def list_renders(sid: int):
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT id, file, duration_sec, created_at FROM renders
               WHERE script_id=? AND file != '' ORDER BY id DESC""", (sid,))]
    finally:
        conn.close()
```

`server/main.py`에 추가:
```python
from api.render import router as render_router, videos_dir
app.include_router(render_router)
app.mount("/videos", StaticFiles(directory=str(videos_dir())), name="videos")
```

추가로 `server/api/images.py`의 `generate_images` 409 검사도 렌더 잡을 포함하도록 갱신:
```python
    if jobs.has_running("images", str(sid)) or jobs.has_running("render", str(sid)):
        raise HTTPException(409, "이 스크립트의 잡이 이미 실행 중입니다 — 완료 후 다시 시도하세요")
```
(단일 씬 이미지 재생성의 검사도 동일하게.)

- [ ] **Step 4: 테스트 통과 확인** — 3 PASS + 전체 1회
- [ ] **Step 5: Commit**

```bash
git add server/core/db.py server/api/render.py server/api/images.py server/main.py server/tests/test_render_api.py
git commit -m "feat(blog-reels): 렌더 잡·renders 기록·/videos 서빙 — 이미지 잡과 상호 409"
```

---

### Task 6: 렌더 UI + README

**Files:**
- Modify: `web/src/api.ts` (Render 타입·헬퍼)
- Modify: `web/src/pages/Storyboard.tsx` (렌더 버튼·진행·미리보기·이력)
- Modify: `web/src/index.css`
- Modify: `README.md` (M4 사용법)

**Interfaces:**
- Consumes: Task 5 REST
- Produces: Storyboard 상단에 `🎬 렌더` 버튼(잡 진행률 공유 표시), 완료 시 `<video controls>` 미리보기(`/videos/<file>`)+다운로드 링크+렌더 이력 목록

- [ ] **Step 1: 구현**

`web/src/api.ts`에 추가:
```ts
export interface RenderInfo {
  id: number; file: string; duration_sec: number; created_at: string
}
export const startRender = (sid: number) =>
  fetch(`/api/scripts/${sid}/render`, { method: 'POST' })
    .then(r => j<{ job_id: number }>(r))
export const getRenders = (sid: number) =>
  fetch(`/api/scripts/${sid}/renders`).then(r => j<RenderInfo[]>(r))
```

`web/src/pages/Storyboard.tsx` — 변경점:
- import에 `type RenderInfo, getRenders, startRender` 추가, 상태:
```tsx
  const [renders, setRenders] = useState<RenderInfo[]>([])
  const [renderJob, setRenderJob] = useState<Job | null>(null)
```
- 마운트 시 이력 로드(기존 useEffect에 `getRenders(sid).then(setRenders)` 추가).
- 렌더 실행(이미지 폴링과 같은 패턴 — try/catch·mounted 가드·1초 폴링):
```tsx
  const runRender = async () => {
    try {
      const { job_id } = await startRender(sid)
      const poll = async () => {
        try {
          const jb = await getJob(job_id)
          if (!mounted.current) return
          setRenderJob(jb)
          if (jb.status === 'running') {
            imgTimer.current = setTimeout(poll, 1000)
            return
          }
          if (jb.status === 'error') alert(`렌더 실패: ${jb.error}`)
          setRenders(await getRenders(sid))
        } catch (e) {
          if (!mounted.current) return
          setRenderJob(null)
          alert(`렌더 잡 확인 실패: ${e}`)
        }
      }
      poll()
    } catch (e) { alert(`렌더 시작 실패: ${e}`) }
  }
```
- 기존 이미지 버튼 3종("🎨 이미지 생성"·"전부 재생성"·씬별 "🖼 재생성")의 disabled 조건에도 `|| renderJob?.status === 'running'`을 추가한다(서버 409가 있지만 UI에서도 잠금 — M3 교훈).
- make-bar에 버튼 추가(이미지 잡·렌더 잡 중 비활성):
```tsx
        <button disabled={imgJob?.status === 'running' || renderJob?.status === 'running'}
                onClick={runRender}>
          {renderJob?.status === 'running'
            ? `🎬 렌더 중… ${renderJob.progress}/${renderJob.total}`
            : '🎬 렌더'}
        </button>
```
- GEO 설명란 위에 렌더 결과 섹션:
```tsx
      {renders.length > 0 && (
        <>
          <h2>🎬 렌더 결과</h2>
          <video className="preview" controls
                 src={`/videos/${renders[0].file}`} />
          <div className="renders">
            {renders.map(r => (
              <a key={r.id} href={`/videos/${r.file}`} download>
                ⬇ {r.file} ({r.duration_sec}초 · {r.created_at})
              </a>
            ))}
          </div>
        </>
      )}
```

`web/vite.config.ts` proxy에 `'/videos': 'http://127.0.0.1:8792'` 추가 (M3의 /images 교훈).

`web/src/index.css`에 추가:
```css
.preview { width: 100%; max-width: 320px; border-radius: 10px;
           border: 1px solid #262b36; }
.renders { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.renders a { color: #a78bfa; }
```

`README.md` M3 섹션 뒤에 추가:
```markdown
### M4 — 릴스 렌더

스토리보드에서 "🎬 렌더" → 씬 이미지+자막(맑은고딕)+Ken Burns를 ffmpeg로 합성해
`server/data/videos/`에 mp4 저장, 완료 시 페이지에서 미리보기·다운로드.
BGM은 `server/data/bgm/`의 mp3를 카테고리 무드로 자동 선택(없으면 무음).
이미지가 없는 씬은 스타일 색 카드로 대체됨 — 먼저 "🎨 이미지 생성" 권장.
ffmpeg가 PATH에 있어야 한다(확인: `ffmpeg -version`).
```

- [ ] **Step 2: 검증** — `cd web; npm run build` 통과 + 서버 pytest 전체 1회.

- [ ] **Step 3: Commit**

```bash
git add web/src/ web/vite.config.ts README.md
git commit -m "feat(blog-reels): 렌더 UI — 잡 진행·미리보기·다운로드·이력"
```

---

## M4 완료 기준 (spec §9·§12 마일스톤 4)

- [ ] 릴스 30/60초 스크립트가 1080×1920 mp4로 렌더(실렌더 스모크 — T4에서 수행·기록)
- [ ] 자막이 역할별 스타일(중앙/로어서드+스크림)로 영상에 구워짐, 한글 정상
- [ ] concat copy 실패 시 재인코딩 폴백, BGM 없거나 실패 시 무음 진행, 이미지 없는 씬은 색 카드
- [ ] 렌더·이미지 잡 상호 409, 진행률 폴링, 완료 시 미리보기·다운로드
- [ ] scenes_lock으로 M3 파킹 경합 마감(기존 회귀 테스트 유지)
- [ ] `pytest server/tests` 전부 통과(ffmpeg 없이 오프라인), `npm run build` 통과
- [ ] 실제 UI에서 릴스 1건 브라우저 렌더 확인은 사용자 수동 항목(README 기재)

M5(롱폼 + Edge-TTS 나레이션)는 M4 완료 후 별도 계획서로 작성한다.
