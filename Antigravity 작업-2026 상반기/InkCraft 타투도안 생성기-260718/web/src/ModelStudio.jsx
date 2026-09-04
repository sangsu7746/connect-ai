import { useEffect, useRef, useState } from 'react';
import { MODEL_ANGLES, MODEL_GENDERS } from './presets.js';
import CompareSlider from './CompareSlider.jsx';
import { loadImage, removeWhiteBg, fileToDataUrl } from './ink.js';

const N = MODEL_ANGLES.length; // 8방향
const VIEW_COST = 100;  // 프레임당 (functions와 일치)
const APPLY_COST = 100;

// 수동 배치 좌표(앵커 각도 + x)로 "기하학적으로 100% 확실히" 가려지는 각도만 스킵한다.
// 오직 앵커가 정면(0)·후면(4) 정샷일 때만 x좌표가 좌우 위치와 신뢰성 있게 대응하므로,
// 그 경우의 반대쪽 완전 측면(2/6)만 스킵 — 몸의 반대쪽 측면에서는 절대 보이지 않기 때문.
// 나머지는 전부 AI가 각도별로 직접 판단(안 보이면 원본 그대로 반환하도록 프롬프트에 명시됨).
//
// (과거엔 "몸통 중앙(x 0.45~0.55) 배치 → 반대편 3개 각도 통째 스킵" 규칙이 있었으나,
//  대부분의 중앙 배치 도안이 이 조건에 걸려 AI에게 그려볼 기회조차 주지 않고 스킵해버리는
//  오탐이 심각했다. 45°/315° 같은 비스듬한 앵커에서는 x좌표가 실제 좌우 위치와도 잘 안 맞았다.)
function occludedForPlacement(anchorAngle, x) {
  const skip = new Set();
  if (anchorAngle === 0) { // 정면
    if (x > 0.55) skip.add(2);       // 모델 왼쪽 부위 → 우측면에서 가려짐
    else if (x < 0.45) skip.add(6);  // 모델 오른쪽 부위 → 좌측면에서 가려짐
  } else if (anchorAngle === 4) { // 후면
    if (x < 0.45) skip.add(2);
    else if (x > 0.55) skip.add(6);
  }
  skip.delete(anchorAngle);
  return [...skip];
}

/**
 * AI 가상 모델 스튜디오 — 속옷(스포츠웨어) 차림의 실사 모델을 8방향으로 생성해
 * 드래그로 360° 회전시키고, 수동 배치(위치·크기) 기준으로 도안을 전 각도에 적용한 뒤
 * Before/After 슬라이더로 비교한다.
 * model 상태는 App이 보관(디자인을 바꿔도 모델 유지, 재생성 비용 절약).
 */
export default function ModelStudio({ design, model, setModel, onError, aiView, aiApply, beforeManual, showCosts, onZoom }) {
  const { gender, frames, applied } = model;
  const [angleIdx, setAngleIdx] = useState(0);
  const [busy, setBusy] = useState(null); // null | {label, done, total}
  const [compare, setCompare] = useState(false);
  const dragRef = useRef(null); // {startX, startIdx}

  // ── 수동 배치: 배경 제거된 도안을 클릭 위치 + 크기로 현재 각도 프레임에 얹는다 ──
  const [manual, setManual] = useState(false);
  const [mPos, setMPos] = useState({ x: 0.5, y: 0.4 });
  const [mScale, setMScale] = useState(22); // 프레임 너비 대비 %
  const manualCanvasRef = useRef(null);
  const manualImgsRef = useRef({ frame: null, ink: null });

  // 도안 → 흰 배경 투명 PNG (도안이 바뀔 때마다 1회 변환, 캔버스 연산이라 무료)
  const [designNoBg, setDesignNoBg] = useState(null);
  useEffect(() => {
    let alive = true;
    removeWhiteBg(design)
      .then((d) => { if (alive) setDesignNoBg(d); })
      .catch(() => { if (alive) setDesignNoBg(null); });
    return () => { alive = false; };
  }, [design]);

  // 수동 모드 캔버스 그리기 (프레임 + 배경 제거 도안 오버레이)
  useEffect(() => {
    if (!manual) return;
    let alive = true;
    (async () => {
      try {
        const base = frames?.[angleIdx];
        if (!base || !designNoBg) return;
        manualImgsRef.current.frame = await loadImage(base);
        manualImgsRef.current.ink = await loadImage(designNoBg);
        if (alive) drawManual();
      } catch (e) {
        onError?.(e.message);
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manual, angleIdx, designNoBg, frames]);

  useEffect(() => { if (manual) drawManual(); }, [mPos, mScale]); // eslint-disable-line react-hooks/exhaustive-deps

  function drawManual() {
    const { frame, ink } = manualImgsRef.current;
    const canvas = manualCanvasRef.current;
    if (!canvas || !frame) return;
    canvas.width = frame.width;
    canvas.height = frame.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(frame, 0, 0);
    if (ink) {
      const w = canvas.width * (mScale / 100);
      const h = w * (ink.height / ink.width);
      // multiply: 잉크가 피부톤 위에 스며든 것처럼 어둡게 섞임 (스티커 느낌 방지)
      ctx.globalCompositeOperation = 'multiply';
      ctx.globalAlpha = 0.95;
      ctx.drawImage(ink, mPos.x * canvas.width - w / 2, mPos.y * canvas.height - h / 2, w, h);
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = 'source-over';
    }
  }

  const onManualClick = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setMPos({
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    });
  };

  // 수동 배치 기준으로 8방향 AI 적용: 기준 각도는 정제(refine), 나머지는 전파(follow)
  const applyManualAI360 = async () => {
    const canvas = manualCanvasRef.current;
    if (!canvas || busy) return;
    const anchor = angleIdx;
    const composite = canvas.toDataURL('image/jpeg', 0.92);
    setManual(false);
    setBusy({ label: 'Inking 360°', done: 0, total: N });
    try {
      const skip = occludedForPlacement(anchor, mPos.x);
      const next = new Array(N).fill(null);
      const r0 = await aiApply({ mode: 'refine', photo: composite, angle: anchor });
      next[anchor] = r0.image;
      setModel((m) => ({ ...m, applied: [...next] }));

      // 전 프레임이 항상 '앵커 적용본(위치·크기) + 원본 도안(디자인)'을 직접 참조 —
      // 체인 전파는 한 프레임의 오류가 증폭되므로(도안 변형·확대·소실) 사용하지 않는다.
      let done = 1;
      for (let i = 0; i < N; i++) {
        if (i === anchor) continue;
        setBusy({ label: 'Inking 360°', done, total: N });
        if (skip.includes(i)) {
          next[i] = frames[i]; // 가려지는 뷰는 원본 재사용 (무과금)
        } else {
          const r = await aiApply({
            mode: 'follow', photo: frames[i], reference: next[anchor], design, angle: i, refAngle: anchor,
          });
          next[i] = r.image;
        }
        done += 1;
        setModel((m) => ({ ...m, applied: [...next] }));
      }
      setCompare(true);
      setAngleIdx(anchor);
    } catch (e) {
      onError?.(e);
    } finally {
      setBusy(null);
    }
  };

  // AI가 잘못 넣은 각도를 원본으로 되돌리는 보정 버튼용
  const clearThisView = () => {
    if (!applied) return;
    setModel((m) => {
      const next = m.applied.slice();
      next[angleIdx] = m.frames[angleIdx];
      return { ...m, applied: next };
    });
  };

  const applyManualPlace = async () => {
    const canvas = manualCanvasRef.current;
    if (!canvas) return;
    try {
      // Firebase 모드: 무료 3회/일 → 초과 30코인 (내 사진 수동 시착과 같은 게이트)
      if (beforeManual) await beforeManual();
      const image = canvas.toDataURL('image/jpeg', 0.92);
      setModel((m) => {
        const nextApplied = (m.applied || m.frames).slice();
        nextApplied[angleIdx] = image;
        return { ...m, applied: nextApplied };
      });
      setManual(false);
      setCompare(true);
    } catch (e) {
      onError?.(e);
    }
  };

  const setGender = (g) => setModel((m) => ({ ...m, gender: g }));

  // 내 전신사진 기반 모델 (선택) — 사진은 정면 뷰 생성에만 쓰이고 저장되지 않음
  const [userPhoto, setUserPhoto] = useState(null);
  const onUserPhotoUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setUserPhoto(await fileToDataUrl(file));
    } catch (err) {
      onError?.(err.message);
    }
    e.target.value = '';
  };

  // ── 모델 8방향 생성: 정면 → 나머지 7방향(정면 참조) ──
  // 중간 실패 시 이미 만든 뷰는 보존되므로, 다시 누르면 남은 뷰만 이어서 생성한다 (재과금 방지)
  const createModel = async () => {
    if (busy) return;
    const next = frames && frames.length === N ? frames.slice() : new Array(N).fill(null);
    const doneCount = () => next.filter(Boolean).length;
    setBusy({ label: 'Creating model', done: doneCount(), total: N });
    try {
      if (!next[0]) {
        const front = await aiView({ gender, angle: 0, refImage: null, userPhoto });
        next[0] = front.image;
        setModel((m) => ({ ...m, frames: [...next], applied: null }));
        setAngleIdx(0);
      }
      for (let i = 1; i < N; i++) {
        if (next[i]) continue;
        setBusy({ label: 'Creating model', done: doneCount(), total: N });
        const r = await aiView({ gender, angle: i, refImage: next[0] });
        next[i] = r.image;
        setModel((m) => ({ ...m, frames: [...next] }));
      }
    } catch (e) {
      onError?.(e);
    } finally {
      setBusy(null);
    }
  };

  // ── 드래그 회전 (비교 모드에서는 슬라이더와 충돌하므로 버튼만) ──
  const onPointerDown = (e) => {
    if (compare) return;
    dragRef.current = { startX: e.clientX, startIdx: angleIdx };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!dragRef.current) return;
    const steps = Math.round((e.clientX - dragRef.current.startX) / 45);
    setAngleIdx(((dragRef.current.startIdx - steps) % N + N) % N);
  };
  const onPointerUp = () => { dragRef.current = null; };

  const rotate = (dir) => setAngleIdx((i) => (i + dir + N) % N);

  const downloadCurrent = () => {
    const src = (compare && applied?.[angleIdx]) || applied?.[angleIdx] || frames?.[angleIdx];
    if (!src) return;
    const a = document.createElement('a');
    a.href = src;
    a.download = `inkcraft-model-${MODEL_ANGLES[angleIdx].label.toLowerCase()}.jpg`;
    a.click();
  };

  const modelReady = frames && frames.every(Boolean);
  const appliedReady = applied && applied.every(Boolean);
  const shownFrame = (applied && applied[angleIdx]) || frames?.[angleIdx];

  return (
    <div className="model-studio">
      {/* 모델이 없을 때: 생성 화면 — 가상 모델 또는 내 전신사진 기반 */}
      {!frames && (
        <>
          <div className="seg">
            {MODEL_GENDERS.map((g) => (
              <button key={g.id} className={gender === g.id ? 'active' : ''} onClick={() => setGender(g.id)}>
                {g.emoji} {g.label}
              </button>
            ))}
          </div>

          {userPhoto ? (
            <div className="user-photo-row">
              <img src={userPhoto} alt="my photo" />
              <div className="upr-text">
                <b>📷 Using your photo</b>
                <small>Face &amp; build preserved · never stored</small>
                <button className="link-btn" onClick={() => setUserPhoto(null)}>✕ Remove photo</button>
              </div>
            </div>
          ) : (
            <label className="upload-box">
              <input type="file" accept="image/*" onChange={onUserPhotoUpload} hidden />
              📷 (Optional) Use my full-body photo
              <small>같은 얼굴·체형으로 생성 · 본인 사진만</small>
            </label>
          )}

          <button className="cta" onClick={createModel} disabled={!!busy}>
            {busy
              ? `${busy.label}… ${busy.done + 1}/${busy.total}`
              : `🧍 Create ${userPhoto ? 'My ' : ''}360° Model${showCosts ? ` · ${VIEW_COST * N}🪙` : ''}`}
          </button>
          <p className="hint">{N} views · drag to spin · try tattoos from every angle</p>
        </>
      )}

      {/* 모델 뷰어 */}
      {frames && (
        <>
          <div className="model-viewer">
            {/* 현재 각도 확대 보기 (수동 배치 중엔 숨김) */}
            {!manual && shownFrame && onZoom && (
              <button
                className="zoom-btn"
                onClick={() => onZoom(shownFrame)}
                title="크게 보기"
                aria-label="Zoom"
              >
                ⛶
              </button>
            )}
            {manual ? (
              <canvas
                ref={manualCanvasRef}
                className="ms-canvas model-manual-canvas"
                onClick={onManualClick}
                title="Click where the tattoo should go"
              />
            ) : compare && applied?.[angleIdx] && frames?.[angleIdx] ? (
              <CompareSlider beforeSrc={frames[angleIdx]} afterSrc={applied[angleIdx]} />
            ) : shownFrame ? (
              <img
                className="model-frame"
                src={shownFrame}
                alt={`model ${MODEL_ANGLES[angleIdx].label}`}
                draggable={false}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={onPointerUp}
                title="Drag left/right to rotate"
              />
            ) : (
              <div className="model-frame model-loading"><div className="spinner" /></div>
            )}
            <div className="model-rotate">
              <button className="ghost" onClick={() => rotate(-1)} title="Rotate left">◀</button>
              <span className="angle-label">
                {MODEL_ANGLES[angleIdx].label} · {angleIdx * 45}°
                {frames && !modelReady && ` (${frames.filter(Boolean).length}/${N} views)`}
              </span>
              <button className="ghost" onClick={() => rotate(1)} title="Rotate right">▶</button>
            </div>

            {/* 생성이 중간에 끊긴 모델: 남은 뷰만 이어서 생성 (이미 만든 뷰는 재과금 없음) */}
            {!modelReady && !busy && (
              <button className="cta" onClick={createModel}>
                ▶️ Resume model — {N - frames.filter(Boolean).length} views left
                {showCosts ? ` · ${VIEW_COST * (N - frames.filter(Boolean).length)}🪙` : ''}
              </button>
            )}
          </div>

          {/* 수동 배치 컨트롤 (배경 제거된 도안 · 클릭 위치 + 크기) */}
          {manual && (
            <div className="ms-controls">
              <div className="size-row">
                <input
                  type="range" min="6" max="60" step="1"
                  value={mScale}
                  onChange={(e) => setMScale(Number(e.target.value))}
                />
                <span className="size-value">{mScale}%</span>
              </div>
              <div className="btn-row">
                <button
                  className="cta"
                  onClick={applyManualAI360}
                  disabled={!!busy || !modelReady}
                  title={!modelReady ? '8방향 뷰가 모두 생성된 후 사용 가능 — Resume으로 남은 뷰를 완성해주세요' : undefined}
                >
                  ✨ AI Apply 360°
                  {showCosts ? ` · ${APPLY_COST * (N - occludedForPlacement(angleIdx, mPos.x).length)}🪙` : ''}
                </button>
                <button className="cta secondary" onClick={applyManualPlace}>
                  ✅ This view only{showCosts ? ' · free 3/day' : ''}
                </button>
                <button className="cta secondary" onClick={() => setManual(false)}>✖ Cancel</button>
              </div>
              <p className="hint">Click to position · ✨ AI Apply spreads it to all {N} angles</p>
            </div>
          )}

          {/* 적용은 🎯 Manual place → ✨ AI Apply 360° 흐름으로 일원화 */}
          {!manual && (
          <div className="btn-row">
            {busy && (
              <button className="cta" disabled>
                {`${busy.label}… ${busy.done + 1}/${busy.total}`}
              </button>
            )}
            <button
              className="cta"
              onClick={() => { setManual(true); setCompare(false); }}
              disabled={!!busy || !frames?.[angleIdx] || !designNoBg}
              title="배경 제거된 도안을 원하는 위치·크기로 직접 배치 — 현재 각도 프레임만 있으면 사용 가능"
            >
              🎯 Manual place
            </button>
            {applied?.[angleIdx] && (
              <button className={`cta secondary ${compare ? 'on' : ''}`} onClick={() => setCompare((c) => !c)}>
                {compare ? '🔄 Rotate mode' : '🆚 Compare'}
              </button>
            )}
            {applied?.[angleIdx] && applied[angleIdx] !== frames[angleIdx] && (
              <button className="cta secondary" onClick={clearThisView} title="이 각도의 타투를 지우고 원본으로 되돌림">
                🧹 Clear view
              </button>
            )}
            <button className="cta secondary" onClick={downloadCurrent} disabled={!shownFrame}>
              ⬇️ This view
            </button>
            <button
              className="cta secondary"
              onClick={() => { setModel((m) => ({ ...m, frames: null, applied: null })); setCompare(false); }}
              disabled={!!busy}
            >
              🗑️ New model
            </button>
          </div>
          )}
          {!manual && (
            <p className="hint">
              {compare ? 'Drag to compare · ◀ ▶ angle' : 'Drag or ◀ ▶ to spin 360°'}
            </p>
          )}
        </>
      )}
    </div>
  );
}
