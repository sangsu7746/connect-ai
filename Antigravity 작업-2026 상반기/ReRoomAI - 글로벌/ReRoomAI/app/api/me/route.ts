import { NextRequest, NextResponse } from 'next/server';
import { isAdminEnabled, verifyBearer } from '@/lib/firebase/admin';
import { ensureUser } from '@/lib/firebase/credits';

export const runtime = 'nodejs';

/** Returns (and lazily creates) the signed-in user's credit balance. */
export async function GET(req: NextRequest) {
  if (!isAdminEnabled()) {
    return NextResponse.json({ error: 'Accounts are not enabled on this deployment.' }, { status: 501 });
  }

  const identity = await verifyBearer(req.headers.get('authorization'));
  if (!identity) {
    return NextResponse.json({ error: 'Please sign in.' }, { status: 401 });
  }

  const user = await ensureUser(identity.uid, identity.email);
  return NextResponse.json({ credits: user.credits });
}
