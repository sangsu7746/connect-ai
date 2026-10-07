import { FREE_GENERATIONS, SIGNUP_CREDITS } from '@/lib/constants';
import Reveal from './Reveal';

const FAQS = [
  {
    q: 'How many designs can I create for free?',
    a: `Anyone can try ${FREE_GENERATIONS} designs without an account. Sign in with Google and you get ${SIGNUP_CREDITS} more free credits. After that, credit packs start at $9 for 50 images — and credits never expire.`,
  },
  {
    q: "Will it change my room's layout or structure?",
    a: 'No. Walls, windows, doors, ceilings and the camera perspective are preserved exactly. Only furniture, lighting, colors and decor are redesigned to match the style you choose.',
  },
  {
    q: 'What is virtual staging and who is it for?',
    a: 'Virtual staging fills an empty room with realistic, tastefully arranged furniture — the way professional stagers prepare real-estate listings. Traditional virtual staging services charge $25–40 per photo; ReRoom does it for pennies, in seconds. Perfect for realtors, landlords and Airbnb hosts.',
  },
  {
    q: 'What can it do besides staging and restyling?',
    a: 'Four more tools, all included: Remove Furniture empties an occupied room and realistically rebuilds the floors and walls behind the removed items. Day to Dusk turns a daytime exterior into a warm twilight shot with glowing windows. Renovation Preview swaps in new flooring, cabinets, countertops and finishes. Curb Appeal freshens the lawn, landscaping and facade. Every generation costs one credit.',
  },
  {
    q: 'Where are my photos stored?',
    a: 'Uploaded photos are used only to process your generation request and are not stored on our servers. If you choose to create a share link, only that before/after pair is saved so the page can be displayed.',
  },
  {
    q: 'Can I use the images commercially?',
    a: 'Yes — images you generate are yours to use in listings, portfolios and marketing. For real-estate listings, we recommend disclosing that photos are virtually staged, as most MLS rules require.',
  },
];

export default function Faq() {
  return (
    <section className="w-full border-t border-line bg-paper-raised">
      <div className="mx-auto max-w-3xl px-6 py-24">
        <Reveal>
          <p className="text-center text-xs font-semibold uppercase tracking-[0.24em] text-clay">
            FAQ
          </p>
          <h2 className="font-display mt-3 text-center text-3xl font-bold tracking-tight text-ink md:text-4xl">
            Frequently asked questions
          </h2>
        </Reveal>

        <Reveal delay={100} className="mt-12 flex flex-col gap-3">
          {FAQS.map((faq) => (
            <details
              key={faq.q}
              className="group rounded-2xl border border-line bg-paper px-6 py-5 transition-colors open:border-line-strong"
            >
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-sm font-semibold text-ink [&::-webkit-details-marker]:hidden">
                {faq.q}
                <span className="text-lg font-light text-ink-faint transition-transform duration-300 group-open:rotate-45">
                  +
                </span>
              </summary>
              <p className="mt-4 text-sm leading-relaxed text-ink-soft">{faq.a}</p>
            </details>
          ))}
        </Reveal>
      </div>
    </section>
  );
}
