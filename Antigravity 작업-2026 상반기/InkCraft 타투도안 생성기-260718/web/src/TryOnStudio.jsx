import { useEffect, useRef, useState } from 'react';
import { BODY_PARTS } from './presets.js';

const MAX_PHOTO = 1280; // 업로드 사진 최대 변 (비용·용량 절약)

/** 파일 → 리사이즈된 dataURL */
function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const ratio = Math.min(1, MAX_PHOTO / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * ratio);
      c.height = Math.round(img.height * ratio);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      resolve(c.toDataURL('image/jpeg', 0.92));
    };
    img.onerror = () => reject(new Error('Failed to read the photo.'));
    img.src = url;
  });
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load image.'));
    img.src = src;
  });
}

/**
 * 타투 시착 스튜디오 — 내 사진(팔/다리/상체/온몸)에 도안을 얹어본다.
 * ① 수동 배치: 클릭 위치 + 크기 + 잉크 블렌딩(멀티플라이), 무료 게이트는 App에서 주입
 * ② AI 적용: Gemini가 피부 굴곡·조명에 맞춰 실제 타투처럼 합성 (프리미엄)
 * 결과는 original=원본 사진과 함께 App으로 전달된다.
 */
export default function TryOnStudio({ design, onResult, onError, beforeManual, aiApply, showCosts }) {
  const [bodyPart, setBodyPart] = useState('arm');
  const [photo, setPhoto] = useState(null);
  const [pos, setPos] = useState({ x: 0.5, y: 0.45 });
  const [scale, setScale] = useState(30); // 사진 너비 대비 %
  // 블렌딩: ink(multiply — 피부 위 잉크처럼 자연스럽게) / vivid(원색 그대로)
  const [blend, setBlend] = useState('ink');
  const [aiBusy, setAiBusy] = useState(false);
  const canvasRef = useRef(null);
  const imgsRef = useRef({ photo: null, design: null });

  // 사진/디자인 로드
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        imgsRef.current.photo = photo ? await loadImage(photo) : null;
        imgsRef.current.design = design ? await loadImage(design) : null;
        if (alive) draw();
      } catch (e) {
        onError?.(e.message);
      }
    })();
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photo, design]);

  useEffect(() => { draw(); }, [pos, scale, blend]); // eslint-disable-line react-hooks/exhaustive-deps

  function draw() {
    const { photo: p, design: d } = imgsRef.current;
    const canvas = canvasRef.current;
    if (!canvas || !p) return;
    canvas.width = p.width;
    canvas.height = p.height;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(p, 0, 0);
    if (d) {
      const w = canvas.width * (scale / 100);
      const h = w * (d.height / d.width);
      ctx.globalCompositeOperation = blend === 'ink' ? 'multiply' : 'source-over';
      ctx.drawImage(d, pos.x * canvas.width - w / 2, pos.y * canvas.height - h / 2, w, h);
      ctx.globalCompositeOperation = 'source-over';
    }
  }

  const onCanvasClick = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setPos({
      x: (e.clientX - rect.left) / rect.width,
      y: (e.clientY - rect.top) / rect.height,
    });
  };

  const onUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setPhoto(await fileToDataUrl(file));
    } catch (err) {
      onError?.(err.message);
    }
    e.target.value = '';
  };

  const applyManual = async () => {
    const canvas = canvasRef.current;
    if (!canvas || !photo) return;
    try {
      // Firebase 모드: 무료 3회/일 → 초과 30코인 (게이트는 App에서 주입)
      if (beforeManual) await beforeManual();
      onResult({ image: canvas.toDataURL('image/jpeg', 0.92), original: photo, method: 'manual', bodyPart });
      setPhoto(null); // 적용 후 스튜디오 초기화 (결과물을 도안으로 재사용하는 재귀 방지)
    } catch (e) {
      onError?.(e);
    }
  };

  const applyAI = async () => {
    if (!photo || !design || aiBusy) return;
    setAiBusy(true);
    try {
      // Firebase 모드면 ikApplyTattooAI(150코인), 로컬 모드면 로컬 프록시 — App에서 주입
      const data = await aiApply({ photo, design, bodyPart });
      onResult({ image: data.image, original: photo, method: 'ai', bodyPart });
      setPhoto(null); // 적용 후 스튜디오 초기화
    } catch (e) {
      onError?.(e);
    } finally {
      setAiBusy(false);
    }
  };

  const part = BODY_PARTS.find((p) => p.id === bodyPart);

  return (
    <div className="mockup-studio">
      <h2>Try it on your skin</h2>
      <div className="seg part-seg">
        {BODY_PARTS.map((p) => (
          <button
            key={p.id}
            className={bodyPart === p.id ? 'active' : ''}
            onClick={() => setBodyPart(p.id)}
            title={p.ko}
          >
            {p.emoji} {p.label}
          </button>
        ))}
      </div>
      {!photo ? (
        <label className="upload-box">
          <input type="file" accept="image/*" onChange={onUpload} hidden />
          📷 Upload a photo of your {part.label.toLowerCase()} ({part.ko})
          <small>Photo is never stored</small>
        </label>
      ) : (
        <>
          <canvas
            ref={canvasRef}
            className="ms-canvas"
            onClick={onCanvasClick}
            title="Click where the tattoo should go"
          />
          <div className="ms-controls">
            <div className="size-row">
              <input
                type="range" min="8" max="70" step="1"
                value={scale}
                onChange={(e) => setScale(Number(e.target.value))}
              />
              <span className="size-value">{scale}%</span>
            </div>
            <div className="seg">
              <button
                className={blend === 'ink' ? 'active' : ''}
                onClick={() => setBlend('ink')}
                title="Blends the black ink into your skin tone"
              >
                🖋️ Ink on skin
              </button>
              <button className={blend === 'vivid' ? 'active' : ''} onClick={() => setBlend('vivid')}>
                Vivid
              </button>
            </div>
            <div className="btn-row">
              <button className="cta" onClick={applyManual}>✅ Apply (manual)</button>
              <button className="cta secondary" onClick={applyAI} disabled={aiBusy}>
                {aiBusy ? 'AI inking…' : `✨ AI Apply${showCosts ? ' · 150🪙' : ''}`}
              </button>
              <button className="cta secondary" onClick={() => setPhoto(null)}>🗑️ Change photo</button>
            </div>
            <p className="hint">Click to position · ✨ AI Apply renders it realistically</p>
          </div>
        </>
      )}
    </div>
  );
}
