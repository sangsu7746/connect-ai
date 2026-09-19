import Reveal from './Reveal';
import StyleCards from './StyleCards';

export default function StyleGallery() {
  return (
    <section id="styles" className="w-full border-t border-line bg-paper-raised">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <Reveal>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-clay">
            Styles
          </p>
          <h2 className="font-display mt-3 text-3xl font-bold tracking-tight text-ink md:text-4xl">
            The same room, eight different ways
          </h2>
          <p className="mt-4 max-w-xl text-sm leading-relaxed text-ink-soft md:text-base">
            From refined minimalism to plush hotel luxury — pick a direction and
            see how differently your space can feel.
          </p>
        </Reveal>

        <StyleCards />
      </div>
    </section>
  );
}
