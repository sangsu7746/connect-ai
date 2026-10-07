import { useCallback, useRef, useState } from 'react';

/**
 * 비포/애프터 비교 슬라이더 — PrintCraft의 CompareSlider를 포팅.
 * After 레이어를 clip-path로 잘라내는 방식이라 리사이즈에도 이미지가 어긋나지 않고,
 * 포인터 드래그 + 키보드(방향키) 조작을 모두 지원한다.
 */
export default function CompareSlider({ beforeSrc, afterSrc }) {
  const [pos, setPos] = useState(50);
  const containerRef = useRef(null);
  const draggingRef = useRef(false);

  const moveTo = useCallback((clientX) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const ratio = ((clientX - rect.left) / rect.width) * 100;
    setPos(Math.max(0, Math.min(100, ratio)));
  }, []);

  const onPointerDown = (e) => {
    draggingRef.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    moveTo(e.clientX);
  };

  const onKeyDown = (e) => {
    const step = e.shiftKey ? 10 : 2;
    if (e.key === 'ArrowLeft') {
      setPos((p) => Math.max(0, p - step));
      e.preventDefault();
    } else if (e.key === 'ArrowRight') {
      setPos((p) => Math.min(100, p + step));
      e.preventDefault();
    }
  };

  return (
    <div
      ref={containerRef}
      className="cs-root"
      onPointerDown={onPointerDown}
      onPointerMove={(e) => draggingRef.current && moveTo(e.clientX)}
      onPointerUp={() => (draggingRef.current = false)}
      onPointerCancel={() => (draggingRef.current = false)}
    >
      {/* Before */}
      <img className="cs-img" src={beforeSrc} alt="before" draggable={false} />
      <span className="cs-label cs-label-before">Before</span>

      {/* After — clip-path로 좌측 pos%만 노출 */}
      <div className="cs-after" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}>
        <img className="cs-img" src={afterSrc} alt="after" draggable={false} />
        <span className="cs-label cs-label-after">After</span>
      </div>

      {/* 핸들 */}
      <div className="cs-handle" style={{ left: `${pos}%` }}>
        <button
          type="button"
          role="slider"
          aria-label="Before/After compare slider"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(pos)}
          onKeyDown={onKeyDown}
          className="cs-knob"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <path d="M4 3L1 7l3 4M10 3l3 4-3 4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}
