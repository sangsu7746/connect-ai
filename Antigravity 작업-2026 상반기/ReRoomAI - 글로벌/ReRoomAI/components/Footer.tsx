export default function Footer() {
  return (
    <footer className="w-full border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 py-10 text-xs text-ink-faint md:flex-row">
        <div className="flex items-baseline gap-2">
          <span className="font-display text-sm font-bold text-ink">
            ReRoom<span className="text-clay">.</span>
          </span>
          <span>© 2026 ReRoom AI. All rights reserved.</span>
        </div>
        <div className="flex items-center gap-4">
          <a href="#pricing" className="font-semibold text-ink-soft transition-colors hover:text-clay">
            Pricing
          </a>
          <a href="#studio" className="font-semibold text-ink-soft transition-colors hover:text-clay">
            Start designing
          </a>
        </div>
      </div>
    </footer>
  );
}
