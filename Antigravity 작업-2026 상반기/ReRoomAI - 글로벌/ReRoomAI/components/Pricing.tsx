'use client';

import { useEffect, useRef, useState } from 'react';
import { CREDIT_PACKS, FREE_GENERATIONS, SIGNUP_CREDITS } from '@/lib/constants';
import { useAuth } from '@/lib/useAuth';
import { firebaseAuth, signInWithGoogle } from '@/lib/firebase/client';
import Reveal from './Reveal';

const PAYPAL_CLIENT_ID = process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID;

// Minimal typing for the PayPal JS SDK
type PayPalButtons = {
  render: (el: HTMLElement) => Promise<void>;
  close: () => Promise<void>;
};
declare global {
  interface Window {
    paypal?: {
      Buttons: (opts: {
        style?: Record<string, string | number>;
        createOrder: () => Promise<string>;
        onApprove: (data: { orderID: string }) => Promise<void>;
        onError: (err: unknown) => void;
      }) => PayPalButtons;
    };
  }
}

let sdkPromise: Promise<void> | null = null;

function loadPayPalSdk(): Promise<void> {
  if (!PAYPAL_CLIENT_ID) return Promise.reject(new Error('PayPal is not configured.'));
  if (window.paypal) return Promise.resolve();
  if (!sdkPromise) {
    sdkPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(PAYPAL_CLIENT_ID)}&currency=USD&intent=capture`;
      script.onload = () => resolve();
      script.onerror = () => {
        sdkPromise = null;
        reject(new Error('Could not load PayPal.'));
      };
      document.head.appendChild(script);
    });
  }
  return sdkPromise;
}

export default function Pricing() {
  const { enabled: authEnabled, user, refreshCredits } = useAuth();

  const [activePack, setActivePack] = useState<string | null>(null);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const buttonHostRef = useRef<HTMLDivElement>(null);

  const paymentsConfigured = Boolean(PAYPAL_CLIENT_ID) && authEnabled;

  // Render PayPal buttons into the active pack's card
  useEffect(() => {
    if (!activePack || !buttonHostRef.current) return;
    let buttons: PayPalButtons | null = null;
    let cancelled = false;
    const host = buttonHostRef.current;

    loadPayPalSdk()
      .then(() => {
        if (cancelled || !window.paypal) return;
        host.innerHTML = '';
        buttons = window.paypal.Buttons({
          style: { layout: 'vertical', shape: 'pill', label: 'pay' },
          createOrder: async () => {
            const token = await firebaseAuth()?.currentUser?.getIdToken();
            const res = await fetch('/api/paypal/create-order', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
              },
              body: JSON.stringify({ packId: activePack }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Could not start the checkout.');
            return data.orderId;
          },
          onApprove: async ({ orderID }) => {
            const token = await firebaseAuth()?.currentUser?.getIdToken();
            const res = await fetch('/api/paypal/capture-order', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
              },
              body: JSON.stringify({ orderId: orderID }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Payment capture failed.');
            setActivePack(null);
            setErrorMsg(null);
            setStatusMsg(`Payment complete — ${data.credited} credits added to your account.`);
            void refreshCredits();
          },
          onError: (err) => {
            console.error(err);
            setErrorMsg('Something went wrong with the payment. You have not been charged twice — please try again.');
          },
        });
        return buttons.render(host);
      })
      .catch((err) => {
        if (!cancelled) setErrorMsg(err instanceof Error ? err.message : 'Could not load PayPal.');
      });

    return () => {
      cancelled = true;
      void buttons?.close().catch(() => {});
    };
  }, [activePack, refreshCredits]);

  const buy = async (packId: string) => {
    setStatusMsg(null);
    setErrorMsg(null);
    if (!paymentsConfigured) return;
    if (!user) {
      // Credits are stored on the account — sign in first.
      await signInWithGoogle();
      return;
    }
    setActivePack(packId);
  };

  return (
    <section id="pricing" className="w-full border-t border-line bg-paper-raised">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <Reveal>
          <p className="text-center text-xs font-semibold uppercase tracking-[0.24em] text-clay">
            Pricing
          </p>
          <h2 className="font-display mt-3 text-center text-3xl font-bold tracking-tight text-ink md:text-4xl">
            Traditional staging: $25+ per photo.
            <br className="hidden md:block" /> ReRoom: from $0.10.
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-center text-sm leading-relaxed text-ink-soft md:text-base">
            Try {FREE_GENERATIONS} designs free without an account, get {SIGNUP_CREDITS} more
            credits when you sign in, then pay only for what you use. Credits never expire.
          </p>
        </Reveal>

        {statusMsg && (
          <div
            role="status"
            className="mx-auto mt-8 max-w-xl rounded-xl border border-clay/30 bg-clay-soft p-4 text-center text-sm font-semibold text-clay-deep"
          >
            {statusMsg}
          </div>
        )}
        {errorMsg && (
          <div
            role="alert"
            className="mx-auto mt-8 max-w-xl rounded-xl border border-clay/30 bg-clay-soft p-4 text-center text-sm text-clay-deep"
          >
            {errorMsg}
          </div>
        )}

        <div className="mt-14 grid gap-4 md:grid-cols-3">
          {CREDIT_PACKS.map((pack, i) => (
            <Reveal key={pack.id} delay={i * 100}>
              <div
                className={`relative flex h-full flex-col rounded-2xl border p-7 ${
                  pack.highlight
                    ? 'border-clay bg-paper shadow-deep'
                    : 'border-line bg-paper'
                }`}
              >
                {pack.highlight && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-clay px-3 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-paper">
                    Most popular
                  </span>
                )}
                <h3 className="font-display text-lg font-bold text-ink">{pack.label}</h3>
                <div className="mt-4 flex items-baseline gap-2">
                  <span className="font-display text-4xl font-bold text-ink">{pack.price}</span>
                  <span className="text-xs text-ink-faint">one-time</span>
                </div>
                <p className="mt-2 text-sm font-semibold text-ink-soft">
                  {pack.credits} image credits
                </p>
                <p className="mt-1 text-xs text-ink-faint">{pack.perImage}</p>

                <ul className="mt-6 flex flex-col gap-2.5 text-sm text-ink-soft">
                  <li className="flex gap-2"><span className="text-clay">✓</span> All 8 design styles</li>
                  <li className="flex gap-2"><span className="text-clay">✓</span> All 6 tools — staging to day-to-dusk</li>
                  <li className="flex gap-2"><span className="text-clay">✓</span> Shareable before/after pages</li>
                  <li className="flex gap-2"><span className="text-clay">✓</span> Full-resolution downloads</li>
                </ul>

                {activePack === pack.id ? (
                  <div className="mt-8">
                    <div ref={buttonHostRef} className="min-h-[45px]" />
                    <button
                      onClick={() => setActivePack(null)}
                      className="mt-3 w-full cursor-pointer text-center text-xs font-semibold text-ink-faint transition-colors hover:text-ink"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => void buy(pack.id)}
                    disabled={!paymentsConfigured}
                    className={`mt-8 w-full rounded-full py-3.5 text-sm font-bold transition-all duration-200 ${
                      paymentsConfigured
                        ? pack.highlight
                          ? 'cursor-pointer bg-ink text-paper shadow-lift hover:bg-clay active:scale-95'
                          : 'cursor-pointer border border-line-strong bg-paper-raised text-ink hover:border-ink active:scale-95'
                        : 'cursor-not-allowed bg-sand text-ink-faint'
                    }`}
                  >
                    {paymentsConfigured
                      ? user
                        ? `Get ${pack.credits} credits`
                        : 'Sign in to purchase'
                      : 'Coming soon'}
                  </button>
                )}
              </div>
            </Reveal>
          ))}
        </div>

        <p className="mt-8 text-center text-xs text-ink-faint">
          {paymentsConfigured
            ? 'Secure checkout via PayPal — pay with your PayPal balance or any major card.'
            : 'Payments launching soon — meanwhile, enjoy your free credits.'}
        </p>
      </div>
    </section>
  );
}
