import Reveal from './Reveal';

const STEPS = [
  {
    no: '01',
    title: 'Upload a photo',
    desc: 'Snap or upload a photo of the space — furnished or completely empty. It is optimized in your browser before upload.',
  },
  {
    no: '02',
    title: 'Pick a mode and style',
    desc: 'Restyle a furnished room, or virtually stage an empty one. Six room types, eight design styles — combine them any way you like.',
  },
  {
    no: '03',
    title: '10 seconds later: a new room',
    desc: 'Walls, windows and perspective stay exactly the same. Furniture, lighting and colors are re-imagined in photorealistic quality.',
  },
];

export default function HowItWorks() {
  return (
    <section id="how-it-works" className="w-full border-t border-line">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <Reveal>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-clay">
            How it works
          </p>
          <h2 className="font-display mt-3 text-3xl font-bold tracking-tight text-ink md:text-4xl">
            Three steps is all it takes
          </h2>
        </Reveal>

        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {STEPS.map((step, i) => (
            <Reveal key={step.no} delay={i * 100}>
              <div className="flex h-full flex-col rounded-2xl border border-line bg-paper-raised p-7">
                <span className="font-display text-sm font-bold text-clay">
                  {step.no}
                </span>
                <h3 className="font-display mt-5 text-xl font-bold text-ink">
                  {step.title}
                </h3>
                <p className="mt-3 text-sm leading-relaxed text-ink-soft">
                  {step.desc}
                </p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
