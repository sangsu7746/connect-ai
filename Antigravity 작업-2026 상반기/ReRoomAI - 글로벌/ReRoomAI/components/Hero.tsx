import CompareSlider from './CompareSlider';
import Reveal from './Reveal';

const STATS = [
  { value: '~10 sec', label: 'per design' },
  { value: '8 styles', label: 'to choose from' },
  { value: 'From $0.10', label: 'per staged photo' },
];

export default function Hero() {
  return (
    <section id="top" className="relative w-full overflow-hidden">
      {/* Soft background glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[840px] -translate-x-1/2 rounded-full bg-clay-soft opacity-60 blur-3xl"
      />

      <div className="relative mx-auto flex max-w-6xl flex-col items-center px-6 pb-24 pt-20 text-center md:pt-28">
        <Reveal className="flex flex-col items-center">
          <p className="mb-6 flex items-center gap-2 rounded-full border border-line bg-paper-raised px-4 py-1.5 text-xs font-medium tracking-wide text-ink-soft">
            <span className="h-1.5 w-1.5 rounded-full bg-clay" />
            AI Interior Design &amp; Virtual Staging
          </p>

          <h1 className="font-display max-w-3xl text-4xl font-bold leading-[1.3] tracking-tight text-ink md:text-6xl md:leading-[1.25]">
            Restyle any room.
            <br />
            Stage any listing. <em className="not-italic text-clay">In seconds.</em>
          </h1>

          <p className="mt-7 max-w-xl text-base leading-relaxed text-ink-soft md:text-lg">
            Upload a photo and AI transforms it in about 10 seconds — restyle,
            stage, remove furniture, preview a renovation, boost curb appeal,
            or turn day into dusk. Every photo a listing needs, for a fraction
            of the cost of traditional photo services.
          </p>

          <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
            <a
              href="#studio"
              className="rounded-full bg-ink px-8 py-4 text-sm font-semibold text-paper shadow-lift transition-all duration-300 hover:-translate-y-0.5 hover:bg-clay"
            >
              Try it free — no signup
            </a>
            <a
              href="#pricing"
              className="rounded-full border border-line-strong bg-paper-raised px-8 py-4 text-sm font-semibold text-ink transition-all duration-300 hover:border-ink"
            >
              See pricing
            </a>
          </div>

          <dl className="mt-12 flex items-center divide-x divide-line">
            {STATS.map((stat) => (
              <div key={stat.label} className="px-6 sm:px-9">
                <dt className="sr-only">{stat.label}</dt>
                <dd className="font-display text-xl font-bold text-ink md:text-2xl">
                  {stat.value}
                </dd>
                <dd className="mt-1 text-[11px] tracking-wide text-ink-faint">
                  {stat.label}
                </dd>
              </div>
            ))}
          </dl>
        </Reveal>

        {/* Showcase slider */}
        <Reveal delay={150} className="mt-16 w-full max-w-4xl">
          <CompareSlider
            beforeSrc="/living_room_before.png"
            afterSrc="/living_room_after.png"
            beforeAlt="Living room before redesign"
            afterAlt="Living room redesigned in Japandi style"
            priority
          />
          <p className="mt-4 text-xs text-ink-faint">
            Drag the handle to see the Japandi-style transformation.
          </p>
        </Reveal>
      </div>
    </section>
  );
}
