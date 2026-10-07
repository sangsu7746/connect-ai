'use client';

import { useAuth } from '@/lib/useAuth';
import { signInWithGoogle, signOut } from '@/lib/firebase/client';

export default function Header() {
  const { enabled, loading, user, credits } = useAuth();

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-paper/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
        <a href="#top" className="flex items-baseline gap-2.5">
          <span className="font-display text-xl font-bold tracking-tight text-ink">
            ReRoom<span className="text-clay">.</span>
          </span>
          <span className="rounded-full border border-line-strong px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.2em] text-ink-soft">
            AI Studio
          </span>
        </a>

        <nav className="flex items-center gap-5 text-sm font-medium text-ink-soft">
          <a href="#styles" className="hidden transition-colors hover:text-ink md:block">
            Styles
          </a>
          <a href="#how-it-works" className="hidden transition-colors hover:text-ink md:block">
            How it works
          </a>
          <a href="#pricing" className="hidden transition-colors hover:text-ink sm:block">
            Pricing
          </a>

          {enabled && !loading && (
            user ? (
              <div className="flex items-center gap-3">
                {credits !== null && (
                  <span
                    title="Remaining credits"
                    className="rounded-full border border-line bg-paper-raised px-3 py-1 text-xs font-bold text-ink"
                  >
                    {credits} cr
                  </span>
                )}
                <button
                  onClick={() => void signOut()}
                  className="hidden cursor-pointer text-xs transition-colors hover:text-ink sm:block"
                >
                  Sign out
                </button>
              </div>
            ) : (
              <button
                onClick={() => void signInWithGoogle()}
                className="cursor-pointer rounded-full border border-line-strong px-4 py-2 text-xs font-semibold text-ink transition-colors hover:border-ink"
              >
                Sign in
              </button>
            )
          )}

          <a
            href="#studio"
            className="rounded-full bg-ink px-5 py-2 text-sm font-semibold text-paper transition-all duration-200 hover:bg-clay"
          >
            Start designing
          </a>
        </nav>
      </div>
    </header>
  );
}
