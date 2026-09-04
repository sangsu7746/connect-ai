# 블로그 리뉴얼 릴스 제작기 — M5 (TTS 나레이션 + 롱폼) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 씬별 나레이션을 Edge-TTS로 병렬 합성해 렌더에 삽입하고(BGM과 amix 믹스 — M4 이월 함정 해소), 롱폼(1~10분) 렌더까지 검증한다.

**Architecture:** tts(edge-tts 병렬·파일 캐시·실패 무음) → renderer 확장(씬 클립 나레이션 입력+apad, _mux_bgm을 나레이션 보존 amix로 전환) → render 잡에 TTS 단계 통합(total=2N+1) → 실렌더 스모크(릴스 TTS 포함 + 롱폼 60초).

**Tech Stack:** M4와 동일 + edge-tts 7.2.8(venv에 설치 확인됨, 네트워크 도달 확인됨).

**Spec:** `docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md` §9(오디오)·§10·§12 마일스톤 5

## Global Constraints

- .env 키 추가(정확히): `TTS_VOICE` 기본 `ko-KR-SunHiNeural`. settings 속성 `tts_voice`
- TTS 캐시: sha256(`text|voice`)[:32] → `server/data/tts/<hash>.mp3` (env `APP_TTS_DIR` 우선). 캐시 히트 시 재합성 없음
- 병렬 합성: asyncio, 동시 **4** 세마포어 (spec §9 "병렬 — 원본 직렬 병목 해소")
- TTS 실패(네트워크·개별 씬)는 해당 씬 무음으로 진행 — 렌더는 멈추지 않는다 (spec §10)
- 씬 클립: 나레이션 있으면 오디오 입력을 TTS 파일로, `apad`로 무음 패딩 + `-t dur` 클램프(나레이션이 씬보다 길면 잘림). 없으면 기존 anullsrc
- **_mux_bgm은 나레이션 보존 amix로 전환**(M4 이월 필수): `[1:a]volume=0.28[b];[0:a][b]amix=inputs=2:duration=first[a]`, `-map 0:v -map "[a]"` — 원본 오디오를 버리는 기존 `-map 0:v -map [b]` 제거
- 잡 total = 씬수(TTS)+씬수(클립)+1(concat), TTS는 씬별 완료 tick
- edge-tts 호출 mock 테스트(오프라인 CI). **실 TTS+실렌더 스모크는 T3에서 수행**(릴스 2씬 TTS 포함 + 롱폼 60초 10씬)
- README: M4 섹션의 celebration 무드 서술 정정(파킹 이월 — celebration은 파일만 있고 카테고리 미매핑, 폴백에서만 선택됨을 명시하거나 목록에서 제외)
- 커밋은 태스크마다, 변경 파일만 add, 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 테스트: `server/.venv/Scripts/python.exe -m pytest server/tests -v` (PYTHONUTF8=1 필요 시)

---

### Task 1: TTS 클라이언트 (tts) + README 정정

**Files:**
- Modify: `server/core/config.py` (tts_voice 1줄)
- Modify: `.env.example` (TTS_VOICE= 1줄)
- Modify: `server/requirements.txt` (edge-tts 추가 — 이미 설치돼 있어도 명시)
- Create: `server/core/tts.py`
- Modify: `README.md` (celebration 정정)
- Test: `server/tests/test_tts.py`

**Interfaces:**
- Produces: `tts.tts_dir() -> Path`(env `APP_TTS_DIR` 우선, 기본 server/data/tts) · `tts.synth_scenes(scenes: list[dict], voice: str | None = None, on_done=None) -> dict[int, pathlib.Path]` — narration 있는 씬만 병렬 합성(동시 4), idx→mp3 경로. 실패 씬은 결과에서 제외. on_done()은 씬 하나 끝날 때마다(성공·실패 무관) 호출 · 내부 `_synth_one(text, voice, out) -> bool`(edge_tts.Communicate(...).save, 예외 시 False) — Task 3이 소비

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_tts.py`:
```python
import asyncio
import pathlib
from core import tts

SCENES = [
    {"idx": 0, "role": "hook", "narration": "첫 나레이션"},
    {"idx": 1, "role": "point", "narration": "둘째 나레이션"},
    {"idx": 2, "role": "chapter", "narration": ""},          # 빈 나레이션 — 제외
]

class FakeCommunicate:
    calls: list = []
    fail_texts: set = set()

    def __init__(self, text, voice, **kw):
        self.text = text
        self.voice = voice

    async def save(self, path):
        FakeCommunicate.calls.append((self.text, self.voice))
        if self.text in FakeCommunicate.fail_texts:
            raise RuntimeError("tts down")
        pathlib.Path(path).write_bytes(b"mp3" + self.text.encode())

def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_TTS_DIR", str(tmp_path / "tts"))
    FakeCommunicate.calls = []
    FakeCommunicate.fail_texts = set()
    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)

def test_synth_scenes_parallel_and_skip_empty(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    ticks = []
    out = tts.synth_scenes(SCENES, on_done=lambda: ticks.append(1))
    assert set(out.keys()) == {0, 1}
    assert all(p.exists() for p in out.values())
    assert len(ticks) == 2                      # narration 있는 씬 수만큼
    assert all(v == "ko-KR-SunHiNeural" for _, v in FakeCommunicate.calls)

def test_cache_hit_no_recall(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    tts.synth_scenes(SCENES)
    n = len(FakeCommunicate.calls)
    tts.synth_scenes(SCENES)                    # 같은 텍스트·보이스 → 캐시
    assert len(FakeCommunicate.calls) == n

def test_failure_excluded_not_raised(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    FakeCommunicate.fail_texts = {"첫 나레이션"}
    out = tts.synth_scenes(SCENES)
    assert set(out.keys()) == {1}               # 실패 씬 제외, 예외 없음

def test_voice_override_changes_cache_key(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    a = tts.synth_scenes(SCENES[:1])
    b = tts.synth_scenes(SCENES[:1], voice="ko-KR-InJoonNeural")
    assert a[0] != b[0]                         # 보이스별 캐시 분리
```

- [ ] **Step 2: 실패 확인** — Run: `server\.venv\Scripts\python -m pytest server/tests/test_tts.py -v`, Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/config.py` Settings에 추가:
```python
    tts_voice = os.getenv("TTS_VOICE", "ko-KR-SunHiNeural")
```

`.env.example`에 추가:
```
TTS_VOICE=ko-KR-SunHiNeural
```

`server/requirements.txt`에 `edge-tts` 추가.

`server/core/tts.py`:
```python
"""Edge-TTS 나레이션 합성 (spec §9). 씬별 병렬(동시 4)·파일 캐시·실패 무음.
네트워크 실패나 개별 씬 실패는 해당 씬을 결과에서 빼는 것으로 처리한다 —
렌더는 무음으로 계속된다 (spec §10)."""
import asyncio
import hashlib
import os
import pathlib

import edge_tts

from .config import settings

_CONCURRENCY = 4


def tts_dir() -> pathlib.Path:
    p = os.environ.get("APP_TTS_DIR")
    d = pathlib.Path(p) if p else \
        pathlib.Path(__file__).resolve().parents[1] / "data" / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_path(text: str, voice: str) -> pathlib.Path:
    key = hashlib.sha256(f"{text}|{voice}".encode()).hexdigest()[:32]
    return tts_dir() / f"{key}.mp3"


async def _synth_one(text: str, voice: str, out: pathlib.Path) -> bool:
    try:
        await edge_tts.Communicate(text, voice).save(str(out))
        return out.exists() and out.stat().st_size > 0
    except Exception:
        out.unlink(missing_ok=True)
        return False


def synth_scenes(scenes: list[dict], voice: str | None = None,
                 on_done=None) -> dict:
    v = voice or settings.tts_voice
    todo = [(s["idx"], s["narration"]) for s in scenes
            if (s.get("narration") or "").strip()]
    results: dict = {}

    async def _run_all():
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def one(idx: int, text: str):
            out = _cache_path(text, v)
            try:
                if out.exists() and out.stat().st_size > 0:
                    results[idx] = out
                    return
                async with sem:
                    if await _synth_one(text, v, out):
                        results[idx] = out
            finally:
                if on_done:
                    on_done()

        await asyncio.gather(*(one(i, t) for i, t in todo))

    asyncio.run(_run_all())
    return results
```

`README.md` — M4 섹션의 BGM 규약 줄에서 celebration 서술 정정:
기존 "documentary_calm/family_warm/emotional_daily/celebration" 부분을
"documentary_calm/family_warm/emotional_daily (celebration 파일도 있으나 카테고리에
매핑되지 않아 무드 무관 폴백에서만 선택됨)"으로 교체.

- [ ] **Step 4: 테스트 통과 확인** — 4 PASS + 전체 1회(기존 167 유지)
- [ ] **Step 5: Commit**

```bash
git add server/core/config.py server/core/tts.py server/requirements.txt server/tests/test_tts.py .env.example README.md
git commit -m "feat(blog-reels): Edge-TTS 나레이션 — 병렬 합성·캐시·실패 무음 + README 정정"
```

---

### Task 2: 렌더러 나레이션 통합 (amix 전환)

**Files:**
- Modify: `server/core/renderer.py`
- Modify: `server/tests/test_renderer.py`

**Interfaces:**
- Consumes: 기존 renderer 구조
- Produces: `_scene_clip(scene, img, cap_png, fmt, workdir, narration: pathlib.Path | None = None)` — narration 있으면 오디오 입력이 TTS 파일(+`apad`), 없으면 anullsrc(기존) · `_mux_bgm`이 나레이션 보존 amix로 전환 · `render_script(..., narrations: dict | None = None)` — idx→mp3 경로, 씬별로 전달. Task 3이 소비

- [ ] **Step 1: 실패하는 테스트 작성/갱신**

`server/tests/test_renderer.py`에 추가:
```python
def test_scene_clip_with_narration_uses_apad(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    narr = tmp_path / "n0.mp3"
    narr.write_bytes(b"mp3")
    out = tmp_path / "out.mp4"
    renderer.render_script(SCENES, "reels", "부동산", None, out,
                           tmp_path / "work", narrations={0: narr})
    joined = [" ".join(map(str, c)) for c in calls]
    clip0 = [c for c in joined if "clip_000" in c][0]
    clip1 = [c for c in joined if "clip_001" in c][0]
    assert str(narr) in clip0 and "apad" in clip0        # 나레이션 씬
    assert "anullsrc" not in clip0
    assert "anullsrc" in clip1                            # 무나레이션 씬은 기존
    assert "-t 4.00" in clip0                             # 길이 클램프 유지

def test_mux_bgm_preserves_narration_via_amix(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    bgm = tmp_path / "m.mp3"
    bgm.write_bytes(b"mp3")
    renderer.render_script(SCENES, "reels", "부동산", bgm,
                           tmp_path / "out.mp4", tmp_path / "work")
    joined = [" ".join(map(str, c)) for c in calls]
    mux = [c for c in joined if "volume=0.28" in c][0]
    assert "amix=inputs=2:duration=first" in mux          # 나레이션 보존 믹스
    assert "-map [a]" in mux or '-map "[a]"' in mux
    assert "-map [b]" not in mux                          # 오디오 교체 방식 제거
```
(기존 `test_render_bgm_mux`의 어서션이 옛 `-map [b]` 방식을 전제하면 amix 기준으로 갱신.)

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/renderer.py` 변경:

`_scene_clip` 시그니처·오디오 입력 분기:
```python
def _scene_clip(scene: dict, img: pathlib.Path, cap_png: pathlib.Path,
                fmt: str, workdir: pathlib.Path,
                narration: pathlib.Path | None = None) -> pathlib.Path:
    w, h = SIZE[fmt]
    dur = max(float(scene["sec"]), 0.5)
    frames = max(round(dur * FPS), 1)
    out = workdir / f"clip_{scene['idx']:03d}.mp4"
    vf = (f"[0:v]scale={int(w * 1.25)}:{int(h * 1.25)},"
          f"zoompan=z='min(zoom+0.0011,1.16)'"
          f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":d={frames}:s={w}x{h}:fps={FPS}[bg];"
          f"[bg][1:v]overlay=0:0[v]")
    cmd = ["ffmpeg", "-y", "-loop", "1", "-i", img, "-i", cap_png]
    if narration is not None:
        cmd += ["-i", narration]
        audio = ["-af", "apad", "-map", "2:a"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
        audio = ["-map", "2:a"]
    _run(cmd + ["-filter_complex", vf, "-map", "[v]"] + audio +
         ["-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast",
          "-pix_fmt", "yuv420p", "-c:a", "aac", out])
    return out
```
(주의: apad는 `-shortest`와 함께 쓰면 패딩이 무효화되므로 나레이션 분기에서는 `-shortest`를 넣지 않는다 — `-t`가 길이를 고정한다. anullsrc 분기도 `-t` 고정이므로 기존 `-shortest`는 제거해도 동작 동일 — 제거로 통일.)

`_mux_bgm` — 나레이션 보존 amix (M4 이월 필수):
```python
def _mux_bgm(video: pathlib.Path, bgm_path: pathlib.Path, total_sec: float,
             out: pathlib.Path) -> None:
    _run(["ffmpeg", "-y", "-i", video, "-stream_loop", "-1", "-i", bgm_path,
          "-filter_complex",
          "[1:a]volume=0.28[b];[0:a][b]amix=inputs=2:duration=first[a]",
          "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
          "-t", f"{total_sec:.2f}", "-shortest", out], timeout=1800)
```

`render_script`에 `narrations: dict | None = None` 인자 추가, 씬 루프에서:
```python
        clips.append(_scene_clip(scene, img, cap, fmt, workdir,
                                 narration=(narrations or {}).get(scene["idx"])))
```

- [ ] **Step 4: 테스트 통과 확인** — 신규 2 + 기존 renderer 6(갱신 반영) + 전체 1회
- [ ] **Step 5: Commit**

```bash
git add server/core/renderer.py server/tests/test_renderer.py
git commit -m "feat(blog-reels): 렌더러 나레이션 — 씬 TTS 입력·apad·amix 전환(나레이션 보존)"
```

---

### Task 3: 렌더 잡 TTS 통합 + 실렌더 스모크 (릴스·롱폼)

**Files:**
- Modify: `server/api/render.py` (TTS 단계)
- Modify: `server/tests/test_render_api.py` (TTS 단계 반영)
- Modify: `README.md` (M5 사용법)

**Interfaces:**
- Consumes: `tts.synth_scenes`, `renderer.render_script(narrations=)`
- Produces: 렌더 잡 흐름 = TTS 병렬(씬별 tick) → 씬 클립(씬별 tick) → concat(1 tick), total=2N+1. TTS 전체 실패 시에도 무음 렌더 계속

- [ ] **Step 1: 테스트 갱신/추가**

`server/tests/test_render_api.py`:
- `_wait_job` 후 total 어서션이 있다면 2N+1 기준으로 갱신.
- 추가:
```python
def test_render_job_includes_tts_step(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.render as rd
    synth_called = {}
    def fake_synth(scenes, voice=None, on_done=None):
        synth_called["n"] = len([s for s in scenes if s.get("narration")])
        for s in scenes:
            if s.get("narration") and on_done:
                on_done()
        return {}
    monkeypatch.setattr(rd.tts, "synth_scenes", fake_synth)
    def fake_render(scenes, fmt, category, bgm_path, out_path, workdir,
                    on_scene=None, narrations=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp4")
        for _ in scenes:
            if on_scene:
                on_scene()
    monkeypatch.setattr(rd.renderer, "render_script", fake_render)
    j = _wait_job(c, c.post(f"/api/scripts/{sid}/render").json()["job_id"])
    assert j["status"] == "done"
    assert synth_called["n"] == 7                    # 나레이션 있는 씬 전부
    assert j["total"] == 7 * 2 + 1 and j["progress"] == j["total"]

def test_render_continues_when_tts_totally_fails(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.render as rd
    def boom(scenes, voice=None, on_done=None):
        raise OSError("network down")
    monkeypatch.setattr(rd.tts, "synth_scenes", boom)
    def fake_render(scenes, fmt, category, bgm_path, out_path, workdir,
                    on_scene=None, narrations=None):
        assert narrations == {}                      # 무음 폴백
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp4")
    monkeypatch.setattr(rd.renderer, "render_script", fake_render)
    j = _wait_job(c, c.post(f"/api/scripts/{sid}/render").json()["job_id"])
    assert j["status"] == "done"                     # 멈추지 않음
```
(기존 `test_render_job_creates_record`의 fake_render 시그니처에 `narrations=None` 추가 필요.)

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/api/render.py`의 work를:
```python
    def work(ctx: jobs.JobCtx) -> dict:
        conn = get_conn()
        try:
            row = conn.execute("SELECT * FROM scripts WHERE id=?",
                               (sid,)).fetchone()
            scenes = json.loads(row["scenes_json"])
            ctx.set_total(len(scenes) * 2 + 1)
            try:
                narrations = tts.synth_scenes(scenes, on_done=ctx.tick)
            except Exception:
                narrations = {}                      # TTS 전면 실패 → 무음
            # TTS 단계에서 tick이 나레이션 있는 씬 수만큼만 발생했으므로
            # 빈 나레이션 씬만큼 보정 tick
            for s in scenes:
                if not (s.get("narration") or "").strip():
                    ctx.tick()
            ...
            renderer.render_script(scenes, fmt, category, bgm_path,
                                   out, pathlib.Path(td),
                                   on_scene=ctx.tick, narrations=narrations)
            ...
```
(import에 `from core import tts` 추가. 나머지 renders 행 흐름은 기존 유지. `except Exception` 보정: tts.synth_scenes가 예외로 죽으면 tick이 하나도 안 갔으므로 보정 루프는 "전체 씬"에 대해 돌아야 함 — 구현 시 `ticked = 0`을 세는 방식이 안전:
```python
            ticked = {"n": 0}
            def tts_tick():
                ticked["n"] += 1
                ctx.tick()
            try:
                narrations = tts.synth_scenes(scenes, on_done=tts_tick)
            except Exception:
                narrations = {}
            for _ in range(len(scenes) - ticked["n"]):
                ctx.tick()
```
이 방식을 사용하라 — 위 단순 보정 대신.)

- [ ] **Step 4: 테스트 통과 확인** — 신규 2 + 기존 render API 3(시그니처 갱신) + 전체 1회

- [ ] **Step 5: 실렌더 스모크 (실 TTS + 롱폼)**

scratchpad 임시 스크립트로:
1. **릴스 TTS 스모크**: 2씬(나레이션 "보증료는 연 영점일이팔 퍼센트입니다" 등) → `tts.synth_scenes` 실호출(네트워크) → `renderer.render_script(narrations=...)` 실렌더 → ffprobe로 오디오 스트림 존재+길이 ≈5s 확인.
2. **롱폼 스모크**: storyboard.build_scenes("long", 60, ["기초","실전"]) 10씬(캡션·나레이션 채움, 그라디언트 이미지) → 실렌더 → ffprobe 길이 ≈60s 확인.
결과(파일 크기·길이·오디오 코덱)를 report에 기록. 네트워크 불가로 TTS 실패 시 무음 렌더가 성공하는지 확인하고 그 사실을 기록(스모크 실패로 취급하지 않음).

- [ ] **Step 6: README + Commit**

`README.md`에 추가:
```markdown
### M5 — TTS 나레이션

렌더 시 씬 나레이션을 Edge-TTS(무료, 네트워크 필요)로 자동 합성해 BGM과 믹스한다.
보이스는 `.env`의 `TTS_VOICE`(기본 ko-KR-SunHiNeural, 남성은 ko-KR-InJoonNeural).
네트워크가 없으면 해당 렌더는 무음으로 진행된다. 합성 결과는 `server/data/tts/`에
캐시되어 같은 문장은 재합성하지 않는다. 롱폼(1/3/5/10분)도 같은 렌더 버튼으로 동작.
```

```bash
git add server/api/render.py server/tests/test_render_api.py README.md
git commit -m "feat(blog-reels): 렌더 잡 TTS 단계 — 병렬 합성·무음 폴백·롱폼 스모크"
```

---

## M5 완료 기준 (spec §9·§12 마일스톤 5)

- [ ] 렌더 결과에 씬 나레이션이 들리고 BGM과 믹스됨(amix — 나레이션 소실 함정 해소)
- [ ] TTS 병렬(동시 4)·캐시·개별/전면 실패 시 무음 진행
- [ ] 롱폼 60초 실렌더 스모크 통과(길이 ≈60s), 릴스 TTS 스모크 통과(오디오 스트림 확인)
- [ ] 잡 진행률 total=2N+1 정확
- [ ] README celebration 정정(M4 파킹 이월)
- [ ] `pytest server/tests` 전부 통과(edge-tts 없이 오프라인), `npm run build` 영향 없음(프론트 무변경)
- [ ] 브라우저에서 나레이션 포함 릴스 확인은 사용자 수동 항목

M6(UI 마감 — 렌더 이력 삭제·컨셉 선택·폴리시)는 M5 완료 후 별도 계획서로 작성한다.
