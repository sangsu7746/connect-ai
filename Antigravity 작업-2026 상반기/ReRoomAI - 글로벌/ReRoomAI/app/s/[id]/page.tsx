import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import CompareSlider from '@/components/CompareSlider';
import { adminDb, isAdminEnabled } from '@/lib/firebase/admin';

// Public before/after share page — the free marketing loop:
// a realtor sends this link to a client, the client sees the product.

type ShareDoc = {
  beforeUrl: string;
  afterUrl: string;
  styleLabel: string | null;
  roomLabel: string | null;
  modeLabel: string;
};

/** "Living Room · Modern style" / "Kitchen" / "Day to Dusk" depending on the mode. */
function shareHeading(share: ShareDoc): string {
  const parts = [share.roomLabel, share.styleLabel && `${share.styleLabel} style`].filter(
    Boolean
  ) as string[];
  return parts.length > 0 ? parts.join(' · ') : share.modeLabel;
}

async function getShare(id: string): Promise<ShareDoc | null> {
  if (!isAdminEnabled()) return null;
  if (!/^[a-f0-9]{16}$/.test(id)) return null;
  const snap = await adminDb().collection('shares').doc(id).get();
  if (!snap.exists) return null;
  return snap.data() as ShareDoc;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const share = await getShare(id);
  if (!share) return { title: 'ReRoom AI' };
  const title = `${shareHeading(share)} — before & after | ReRoom AI`;
  const description = `See this ${(share.roomLabel ?? 'property').toLowerCase()} transformed with AI (${share.modeLabel}). Drag the slider to compare.`;
  return {
    title,
    description,
    openGraph: {
      title,
      description,
      images: [{ url: share.afterUrl, width: 1024, height: 768 }],
      type: 'website',
    },
  };
}

export default async function SharePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const share = await getShare(id);
  if (!share) notFound();

  return (
    <div className="flex min-h-screen flex-col bg-paper">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <Link href="/" className="flex items-baseline gap-2.5">
            <span className="font-display text-xl font-bold tracking-tight text-ink">
              ReRoom<span className="text-clay">.</span>
            </span>
          </Link>
          <Link
            href="/#studio"
            className="rounded-full bg-ink px-5 py-2 text-sm font-semibold text-paper transition-colors hover:bg-clay"
          >
            Try it free
          </Link>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col items-center px-6 py-14 text-center">
        <span className="rounded-full bg-clay px-4 py-1.5 text-[11px] font-bold uppercase tracking-[0.18em] text-paper">
          {share.modeLabel}
        </span>
        <h1 className="font-display mt-5 text-3xl font-bold tracking-tight text-ink md:text-4xl">
          {shareHeading(share)}
        </h1>
        <p className="mt-3 text-sm text-ink-soft">
          Drag the handle to compare the before and after.
        </p>

        <div className="mt-10 w-full">
          <CompareSlider
            beforeSrc={share.beforeUrl}
            afterSrc={share.afterUrl}
            beforeAlt={`${share.roomLabel ?? 'Property'} before`}
            afterAlt={`${share.roomLabel ?? 'Property'} after — ${share.modeLabel}`}
            priority
          />
        </div>

        <div className="mt-12 flex flex-col items-center gap-4">
          <p className="text-sm text-ink-soft">
            Made with <span className="font-bold text-ink">ReRoom AI</span> — restyle any room
            or stage an empty listing in about 10 seconds.
          </p>
          <Link
            href="/#studio"
            className="rounded-full bg-ink px-8 py-4 text-sm font-semibold text-paper shadow-lift transition-all duration-300 hover:-translate-y-0.5 hover:bg-clay"
          >
            Design your own room — free
          </Link>
        </div>
      </main>

      <footer className="border-t border-line py-8 text-center text-xs text-ink-faint">
        © 2026 ReRoom AI. All rights reserved.
      </footer>
    </div>
  );
}
