# 블로그 리뉴얼 릴스 제작기 — M6 (마감: 나레이션 예산·견고화·이력 관리) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** M5 최종 리뷰의 필수 이월(나레이션 길이 예산)과 견고화 목록(리미터·캐시 원자화·렌더 직렬화·이력 삭제·문서 동기화)을 닫아 프로젝트를 마감한다.

**Architecture:** script_gen에 씬별 나레이션 자수 예산(프롬프트+게이트 — 기존 재생성 루프 재사용) → 오디오/TTS/잡 견고화(alimiter·원자적 캐시 쓰기·전역 렌더 직렬화) → 렌더 이력 삭제 API+UI + 스펙·README 문구 동기화.

**Tech Stack:** 기존과 동일. 신규 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md` §7·§9·§12 마일스톤 6

## Global Constraints

- 나레이션 예산: 씬당 `int(sec * 5)`자(edge-tts ≈6자/초 대비 여유) — 프롬프트에 씬별 명시 + `_gate`가 초과를 위반으로 보고(기존 재생성 예산·안전 폴백 루프가 자동 처리). 안전 문구(SAFE_NARRATION)는 예산 검사 면제(짧아서 무관하나 명시)
- amix 뒤 `alimiter=limit=0.98` 보험 (M5 실측: 평시 클리핑 LOW — 보험 목적)
- TTS 캐시 쓰기 원자화: `.tmp`에 저장 후 `os.replace` — 부분 파일이 캐시 히트가 되지 않게
- 렌더 잡은 **전역 1개**(스크립트 불문 — spec §9 "동시 렌더 1개", GPU/CPU 공유): kind='render'의 running이 있으면 409. 이미지 잡은 기존 per-sid 유지
- 렌더 이력 삭제: `DELETE /api/renders/{rid}` — 파일+행 삭제, 실행 중 렌더 잡 있으면 409. UI 이력에 🗑 버튼
- 문서: 스펙 §9 오디오 문구를 구현(씬별 TTS 트랙+concat+마스터 amix)에 동기화, README celebration 문장 정리(이중 괄호 제거)
- 커밋은 태스크마다, 변경 파일만 add, 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- 테스트: `server/.venv/Scripts/python.exe -m pytest server/tests -v` (PYTHONUTF8=1 필요 시), web은 `cd web; npm run build`

---

### Task 1: 나레이션 길이 예산 (M5 필수 이월)

**Files:**
- Modify: `server/core/script_gen.py`
- Test: `server/tests/test_script_gen.py` (추가)

**Interfaces:**
- Produces: `narration_budget(sec: float) -> int` = `max(int(sec * 5), 10)` · `_SCENE_JSON`/배치 프롬프트가 씬별 예산 명시("나레이션 N자 이내 — 이 씬은 M초") · `_gate`가 예산 초과를 위반 목록에 추가(`"나레이션 길이 초과: {len}자 > {budget}자"`) — scene dict의 `sec` 사용, SAFE_NARRATION은 면제

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_script_gen.py`에 추가:
```python
def test_narration_budget_formula():
    assert script_gen.narration_budget(4.0) == 20
    assert script_gen.narration_budget(8.3) == 41
    assert script_gen.narration_budget(1.0) == 10          # 하한

def test_gate_flags_over_budget_narration():
    scene = {"idx": 0, "role": "point", "sec": 4.0, "chapter": "",
             "caption": "자막", "sub": "",
             "narration": "가" * 40, "image_prompt": ""}
    problems = script_gen._gate(scene, "본문", ["본문"])
    assert any("길이 초과" in p for p in problems)

def test_gate_allows_within_budget_and_safe():
    scene = {"idx": 0, "role": "point", "sec": 4.0, "chapter": "",
             "caption": "자막", "sub": "",
             "narration": "가" * 15, "image_prompt": ""}
    assert not any("길이 초과" in p
                   for p in script_gen._gate(scene, "본문", ["본문"]))
    safe = dict(scene, narration=script_gen.SAFE_NARRATION, sec=2.2)
    assert not any("길이 초과" in p
                   for p in script_gen._gate(safe, "본문", ["본문"]))

def test_over_budget_triggers_regen_then_fallback(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    def long_gen(prompt, **kw):
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene(narration="보증료는 " + "가" * 60)
                           for _ in range(max(want, 1))], ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", long_gen)
    out = script_gen.generate_script(POSTS, "reels", 30)
    for s in out["scenes"]:
        if s["role"] == "chapter":
            continue
        budget = script_gen.narration_budget(s["sec"])
        assert len(s["narration"]) <= max(budget,
                                          len(script_gen.SAFE_NARRATION))

def test_prompt_includes_budget(monkeypatch):
    monkeypatch.setattr(script_gen.gemini, "available", lambda: True)
    seen = {}
    def spy(prompt, **kw):
        seen["p"] = prompt
        want = prompt.count('"idx"')
        return json.dumps([_fake_scene() for _ in range(max(want, 1))],
                          ensure_ascii=False)
    monkeypatch.setattr(script_gen.gemini, "generate", spy)
    script_gen.generate_script(POSTS, "reels", 30)
    assert "자 이내" in seen["p"]                    # 씬별 예산 문구
```

- [ ] **Step 2: 실패 확인** — Run: `server\.venv\Scripts\python -m pytest server/tests/test_script_gen.py -v`, Expected: 신규 FAIL

- [ ] **Step 3: 구현**

`server/core/script_gen.py`:
- 추가:
```python
def narration_budget(sec: float) -> int:
    """씬 길이에 맞는 나레이션 자수 예산. edge-tts ≈6자/초 — 5자/초로 여유."""
    return max(int(float(sec) * 5), 10)
```
- `_batch_prompt`의 씬 스펙 라인에 예산 명시 — `_SCENE_JSON % s["idx"]` 뒤 주석부를:
```python
    scene_specs = "\n".join(
        _SCENE_JSON % s["idx"] +
        f"  ← 역할 {s['role']}, {s['sec']}초, 나레이션 {narration_budget(s['sec'])}자 이내"
        + (f", 챕터 '{s['chapter']}'" if s["chapter"] else "")
        for s in scenes)
```
- `_gate`에 예산 검사 추가(기존 problems 계산 뒤):
```python
    narr = scene.get("narration") or ""
    if narr and narr != SAFE_NARRATION and "sec" in scene:
        budget = narration_budget(scene["sec"])
        if len(narr) > budget:
            problems.append(f"나레이션 길이 초과: {len(narr)}자 > {budget}자")
    return problems
```
(주의: `_gate`는 `_safe_fallback` 내부의 caption 단독 검사에서 `{"caption":..., "sub":"", "narration":""}` 형태로도 불린다 — narration 빈 문자열·sec 부재 시 검사 스킵이 위 조건으로 보장됨.)

- [ ] **Step 4: 테스트 통과 확인** — 신규 5 + 기존 script_gen 8 + 전체 1회(175 유지·갱신)
- [ ] **Step 5: Commit**

```bash
git add server/core/script_gen.py server/tests/test_script_gen.py
git commit -m "feat(blog-reels): 나레이션 길이 예산 — 씬 초당 5자·게이트·프롬프트 명시"
```

---

### Task 2: 오디오·TTS·렌더 견고화

**Files:**
- Modify: `server/core/renderer.py` (alimiter)
- Modify: `server/core/tts.py` (원자적 캐시 쓰기)
- Modify: `server/api/render.py` (전역 렌더 직렬화)
- Test: `server/tests/test_renderer.py`, `server/tests/test_tts.py`, `server/tests/test_render_api.py` (추가·갱신)

**Interfaces:**
- Produces: `_mux_bgm` 필터가 `...amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.98[a]` · `tts._synth_one`이 `.tmp` 경로에 저장 후 `os.replace(out)` · `start_render`가 `jobs.has_running_kind("render")`(신규 헬퍼 — ref 불문 kind 검사)로 전역 1개 강제, 이미지 잡 검사(per-sid)는 유지

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_renderer.py`에 추가:
```python
def test_mux_has_limiter(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    bgm = tmp_path / "m.mp3"
    bgm.write_bytes(b"mp3")
    renderer.render_script(SCENES, "reels", "부동산", bgm,
                           tmp_path / "out.mp4", tmp_path / "work")
    joined = [" ".join(map(str, c)) for c in calls]
    mux = [c for c in joined if "volume=0.28" in c][0]
    assert "alimiter=limit=0.98" in mux
```

`server/tests/test_tts.py`에 추가:
```python
def test_atomic_cache_write(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    out = tts.synth_scenes(SCENES[:1])
    assert 0 in out
    leftovers = list(out[0].parent.glob("*.tmp*"))
    assert leftovers == []                        # 임시 파일 잔재 없음

def test_partial_tmp_not_cached(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    FakeCommunicate.fail_texts = {"첫 나레이션"}
    tts.synth_scenes(SCENES[:1])
    d = pathlib.Path(str(tmp_path / "tts"))
    assert list(d.glob("*.mp3")) == []            # 실패는 최종 경로에 안 남음
```

`server/tests/test_render_api.py`에 추가:
```python
def test_render_serialized_globally(monkeypatch, tmp_path):
    import threading
    c = make_client(monkeypatch, tmp_path)
    sid1 = _make_script(c, monkeypatch)
    sid2 = _make_script2(c, monkeypatch)          # 두 번째 스크립트 헬퍼
    import api.render as rd
    gate = threading.Event()
    def slow_render(scenes, fmt, category, bgm_path, out_path, workdir,
                    on_scene=None, narrations=None):
        gate.wait(timeout=5)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp4")
    monkeypatch.setattr(rd.renderer, "render_script", slow_render)
    jid = c.post(f"/api/scripts/{sid1}/render").json()["job_id"]
    try:
        assert c.post(f"/api/scripts/{sid2}/render").status_code == 409
    finally:
        gate.set()
    _wait_job(c, jid)
```
(`_make_script2`: `_make_script`와 동일하되 카테고리 2에 discover(키워드 "재테크")·스크립트 생성 — 기존 헬퍼를 인자화하거나 복제해 구현. URL 충돌 피하려고 mock 검색 결과의 url을 다르게.)

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/core/renderer.py` `_mux_bgm` 필터:
```python
          "[1:a]volume=0.28[b];[0:a][b]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.98[a]",
```

`server/core/tts.py` `_synth_one`:
```python
async def _synth_one(text: str, voice: str, out: pathlib.Path) -> bool:
    tmp = out.parent / (out.name + ".tmp")
    try:
        await edge_tts.Communicate(text, voice).save(str(tmp))
        if tmp.exists() and tmp.stat().st_size > 0:
            os.replace(tmp, out)
            return True
        tmp.unlink(missing_ok=True)
        return False
    except Exception:
        tmp.unlink(missing_ok=True)
        return False
```

`server/core/jobs.py`에 헬퍼 추가:
```python
def has_running_kind(kind: str) -> bool:
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT 1 FROM jobs WHERE kind=? AND status='running'",
            (kind,)).fetchone() is not None
    finally:
        conn.close()
```

`server/api/render.py` `start_render` 검사:
```python
    if jobs.has_running_kind("render"):
        raise HTTPException(409, "다른 렌더가 진행 중입니다 — 완료 후 다시 시도하세요 (동시 렌더 1개)")
    if jobs.has_running("images", str(sid)):
        raise HTTPException(409, "이 스크립트의 잡이 이미 실행 중입니다 — 완료 후 다시 시도하세요")
```
(images.py의 기존 검사는 그대로 — 이미지 잡은 per-sid, 단 렌더 실행 중 이미지 잡 409는 기존 `has_running("render", str(sid))`가 sid 일치 때만 걸리므로 **`has_running_kind("render")`로 교체**해 전역 렌더 중 이미지 잡도 대기시킨다 — GPU/CPU 공유 취지 동일. generate_images·regen_scene_image 두 곳.)

- [ ] **Step 4: 테스트 통과 확인** — 신규 4 + 기존 전체 1회(기존 409 테스트들 호환 확인 — test_render_conflicts_with_image_job은 per-sid images 검사라 유지됨)
- [ ] **Step 5: Commit**

```bash
git add server/core/renderer.py server/core/tts.py server/core/jobs.py server/api/render.py server/api/images.py server/tests/test_renderer.py server/tests/test_tts.py server/tests/test_render_api.py
git commit -m "feat(blog-reels): 견고화 — alimiter·TTS 원자 캐시·전역 렌더 직렬화"
```

---

### Task 3: 렌더 이력 삭제 + 문서 동기화

**Files:**
- Modify: `server/api/render.py` (DELETE 엔드포인트)
- Modify: `web/src/api.ts`, `web/src/pages/Storyboard.tsx` (삭제 버튼)
- Modify: `docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md` (§9 오디오 문구)
- Modify: `README.md` (celebration 문장 정리)
- Test: `server/tests/test_render_api.py` (추가)

**Interfaces:**
- Produces: `DELETE /api/renders/{rid}` → 파일 삭제(missing 무시)+행 삭제, 렌더 잡 실행 중이면 409, 없는 rid 404 · UI 이력 항목에 🗑 버튼(확인 confirm 후 삭제·목록 갱신)

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/test_render_api.py`에 추가:
```python
def test_delete_render(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.render as rd
    def fake_render(scenes, fmt, category, bgm_path, out_path, workdir,
                    on_scene=None, narrations=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp4")
    monkeypatch.setattr(rd.renderer, "render_script", fake_render)
    _wait_job(c, c.post(f"/api/scripts/{sid}/render").json()["job_id"])
    r = c.get(f"/api/scripts/{sid}/renders").json()[0]
    fpath = rd.videos_dir() / r["file"]
    assert fpath.exists()
    assert c.delete(f"/api/renders/{r['id']}").status_code == 200
    assert not fpath.exists()
    assert c.get(f"/api/scripts/{sid}/renders").json() == []
    assert c.delete(f"/api/renders/{r['id']}").status_code == 404
```

- [ ] **Step 2: 실패 확인** — Expected: FAIL

- [ ] **Step 3: 구현**

`server/api/render.py`에 추가:
```python
@router.delete("/renders/{rid}")
def delete_render(rid: int):
    if jobs.has_running_kind("render"):
        raise HTTPException(409, "렌더 진행 중에는 삭제할 수 없습니다")
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM renders WHERE id=?", (rid,)).fetchone()
        if not row:
            raise HTTPException(404, "render not found")
        if row["file"]:
            (videos_dir() / row["file"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM renders WHERE id=?", (rid,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
```

`web/src/api.ts`에 추가:
```ts
export const deleteRender = (id: number) =>
  fetch(`/api/renders/${id}`, { method: 'DELETE' }).then(r => j<{ ok: boolean }>(r))
```

`web/src/pages/Storyboard.tsx` — 이력 항목에 삭제 버튼(import에 `deleteRender` 추가):
```tsx
            {renders.map(r => (
              <div key={r.id} className="render-row">
                <a href={`/videos/${r.file}`} download>
                  ⬇ {r.file} ({r.duration_sec}초 · {r.created_at})
                </a>
                <button className="ghost" onClick={async () => {
                  if (!confirm('이 렌더를 삭제할까요?')) return
                  try {
                    await deleteRender(r.id)
                    setRenders(await getRenders(sid))
                  } catch (e) { alert(`삭제 실패: ${e}`) }
                }}>🗑</button>
              </div>
            ))}
```
`web/src/index.css`: `.render-row { display: flex; gap: 8px; align-items: center; }`

스펙 §9 오디오 항목 교체:
```
- 오디오(M5 구현 확정): 씬 클립에 Edge-TTS 나레이션 트랙(44100 스테레오 통일·apad·-t)
  → concat → 마스터에서 BGM amix(volume 0.28, normalize=0, alimiter 0.98).
  TTS는 씬별 병렬 4·문장 캐시·실패 무음.
```
(기존 "Edge-TTS 씬별 병렬 생성... adelay + amix, BGM 볼륨 0.28" 줄과 그 폴백 서술을 위 내용으로 갱신 — 실제 줄을 읽고 정확히 교체.)

README celebration 문장을 자연스럽게 정리(이중 괄호 제거):
```
BGM 파일명은 `<무드>-NN.mp3` 규약을 따른다(documentary_calm·family_warm·emotional_daily).
celebration 파일도 들어 있으나 카테고리에 매핑되지 않아 무드 폴백에서만 선택된다.
```

- [ ] **Step 4: 검증** — 신규 1 + 전체 pytest + `cd web; npm run build`
- [ ] **Step 5: Commit**

```bash
git add server/api/render.py web/src/ README.md docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md server/tests/test_render_api.py
git commit -m "feat(blog-reels): 렌더 이력 삭제·스펙 §9 동기화·README 정리 — M6 마감"
```

---

## M6 완료 기준 (spec §12 마일스톤 6 + M5 이월)

- [ ] 나레이션이 씬 예산(초당 5자) 안으로 생성·게이트되어 잘림이 예외 케이스가 됨
- [ ] amix 뒤 리미터, TTS 캐시 원자적 쓰기, 렌더 전역 1개 직렬화(이미지 잡도 렌더 중 대기)
- [ ] 렌더 이력 삭제(파일+행) 동작, 진행 중 409
- [ ] 스펙 §9가 구현과 일치, README 문장 정리
- [ ] `pytest server/tests` 전부 통과(오프라인), `npm run build` 통과

이로써 스펙 §12의 전 마일스톤이 완료된다.
