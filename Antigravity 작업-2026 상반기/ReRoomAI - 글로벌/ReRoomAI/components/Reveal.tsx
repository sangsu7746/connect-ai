'use client';

import { useEffect, useRef } from 'react';

type RevealProps = {
  children: React.ReactNode;
  className?: string;
  /** 자식 요소 등장 지연 (ms) */
  delay?: number;
};

/** 뷰포트 진입 시 한 번 페이드업되는 스크롤 리빌 래퍼 */
export default function Reveal({ children, className = '', delay = 0 }: RevealProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          el.classList.add('is-visible');
          observer.disconnect();
        }
      },
      { threshold: 0.12 }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={`reveal ${className}`}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
    >
      {children}
    </div>
  );
}
