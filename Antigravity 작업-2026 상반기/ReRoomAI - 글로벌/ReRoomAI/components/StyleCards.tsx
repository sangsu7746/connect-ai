'use client';

import { STYLES } from '@/lib/constants';
import Reveal from './Reveal';

/** Style gallery cards. Clicking scrolls to the studio with that style pre-selected. */
export default function StyleCards() {
  const pickStyle = (styleId: string) => {
    window.dispatchEvent(new CustomEvent('reroom:style', { detail: styleId }));
    document.getElementById('studio')?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div className="mt-12 grid grid-cols-2 gap-4 md:grid-cols-4">
      {STYLES.map((style, i) => (
        <Reveal key={style.id} delay={i * 60}>
          <button
            type="button"
            onClick={() => pickStyle(style.id)}
            className="group flex h-full w-full cursor-pointer flex-col justify-between rounded-2xl border border-line bg-paper p-5 text-left transition-all duration-300 hover:-translate-y-1 hover:border-line-strong hover:shadow-lift"
          >
            <div className="flex items-center gap-1.5">
              {style.swatch.map((color) => (
                <span
                  key={color}
                  className="h-5 w-5 rounded-full border border-ink/10"
                  style={{ backgroundColor: color }}
                />
              ))}
            </div>
            <div className="mt-8">
              <h3 className="font-display text-lg font-bold text-ink">
                {style.label}
              </h3>
              <p className="mt-1.5 text-xs leading-relaxed text-ink-soft">
                {style.desc}
              </p>
              <p className="mt-4 text-xs font-semibold text-clay opacity-0 transition-opacity duration-300 group-hover:opacity-100">
                Design with this style →
              </p>
            </div>
          </button>
        </Reveal>
      ))}
    </div>
  );
}
