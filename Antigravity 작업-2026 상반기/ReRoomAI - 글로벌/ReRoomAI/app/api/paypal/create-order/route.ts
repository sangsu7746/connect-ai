import { NextRequest, NextResponse } from 'next/server';
import { CREDIT_PACKS } from '@/lib/constants';
import { isAdminEnabled, verifyBearer } from '@/lib/firebase/admin';
import { createPayPalOrder, isPayPalEnabled } from '@/lib/paypal';

export const runtime = 'nodejs';

// Creates a PayPal order for a credit pack. The price comes from CREDIT_PACKS
// on the server, so the client can only choose *which* pack — never the amount.

export async function POST(req: NextRequest) {
  if (!isPayPalEnabled() || !isAdminEnabled()) {
    return NextResponse.json({ error: 'Payments are not configured.' }, { status: 501 });
  }

  const identity = await verifyBearer(req.headers.get('authorization'));
  if (!identity) {
    return NextResponse.json({ error: 'Please sign in before purchasing.' }, { status: 401 });
  }

  const { packId } = await req.json();
  const pack = CREDIT_PACKS.find((p) => p.id === packId);
  if (!pack) {
    return NextResponse.json({ error: 'Unknown credit pack.' }, { status: 400 });
  }

  try {
    const orderId = await createPayPalOrder({
      uid: identity.uid,
      packId: pack.id,
      usd: pack.usd,
      description: `ReRoom AI — ${pack.label} pack (${pack.credits} image credits)`,
    });
    return NextResponse.json({ orderId });
  } catch (err) {
    console.error('create-order error:', err);
    return NextResponse.json({ error: 'Could not start the checkout.' }, { status: 502 });
  }
}
