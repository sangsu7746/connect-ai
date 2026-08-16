import { NextRequest, NextResponse } from 'next/server';
import { CREDIT_PACKS } from '@/lib/constants';
import { adminDb, isAdminEnabled, verifyBearer } from '@/lib/firebase/admin';
import { addCredits } from '@/lib/firebase/credits';
import { capturePayPalOrder, isPayPalEnabled } from '@/lib/paypal';

export const runtime = 'nodejs';

// Captures an approved PayPal order and credits the buyer's balance.
// Verifies: capture status, buyer identity (custom_id), exact amount, idempotency.

export async function POST(req: NextRequest) {
  if (!isPayPalEnabled() || !isAdminEnabled()) {
    return NextResponse.json({ error: 'Payments are not configured.' }, { status: 501 });
  }

  const identity = await verifyBearer(req.headers.get('authorization'));
  if (!identity) {
    return NextResponse.json({ error: 'Please sign in.' }, { status: 401 });
  }

  const { orderId } = await req.json();
  if (typeof orderId !== 'string' || !orderId) {
    return NextResponse.json({ error: 'Missing orderId.' }, { status: 400 });
  }

  try {
    const capture = await capturePayPalOrder(orderId);

    if (capture.status !== 'COMPLETED') {
      return NextResponse.json(
        { error: `Payment not completed (status: ${capture.status}).` },
        { status: 402 }
      );
    }

    const [uid, packId] = capture.customId.split(':');
    const pack = CREDIT_PACKS.find((p) => p.id === packId);

    if (uid !== identity.uid || !pack) {
      console.error('capture mismatch:', capture.customId, 'caller:', identity.uid);
      return NextResponse.json({ error: 'Order verification failed.' }, { status: 403 });
    }

    if (capture.currency !== 'USD' || Number(capture.amountValue) !== pack.usd) {
      console.error('amount mismatch:', capture.amountValue, capture.currency, 'expected:', pack.usd);
      return NextResponse.json({ error: 'Order verification failed.' }, { status: 403 });
    }

    // Idempotency: one credit grant per capture
    const orderRef = adminDb().collection('orders').doc(capture.captureId);
    const seen = await orderRef.get();
    if (seen.exists) {
      return NextResponse.json({ ok: true, credited: 0, duplicate: true });
    }

    await addCredits(identity.uid, pack.credits);
    await orderRef.set({
      uid: identity.uid,
      packId: pack.id,
      credits: pack.credits,
      usd: pack.usd,
      paypalOrderId: orderId,
      processedAt: new Date(),
    });

    return NextResponse.json({ ok: true, credited: pack.credits });
  } catch (err) {
    console.error('capture-order error:', err);
    return NextResponse.json({ error: 'Payment capture failed.' }, { status: 502 });
  }
}
