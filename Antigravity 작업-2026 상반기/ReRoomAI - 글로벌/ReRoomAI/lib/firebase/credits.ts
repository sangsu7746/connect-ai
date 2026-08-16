import { FieldValue } from 'firebase-admin/firestore';
import { adminDb } from './admin';
import { SIGNUP_CREDITS } from '@/lib/constants';

// Firestore schema: users/{uid} → { email, credits, totalGenerated, createdAt }

export type UserRecord = {
  credits: number;
  email?: string;
};

/** Ensures the user document exists (granting signup credits once) and returns it. */
export async function ensureUser(uid: string, email?: string): Promise<UserRecord> {
  const ref = adminDb().collection('users').doc(uid);
  const snap = await ref.get();
  if (!snap.exists) {
    const fresh = {
      email: email ?? null,
      credits: SIGNUP_CREDITS,
      totalGenerated: 0,
      createdAt: FieldValue.serverTimestamp(),
    };
    await ref.set(fresh);
    return { credits: SIGNUP_CREDITS, email };
  }
  const data = snap.data()!;
  return { credits: data.credits ?? 0, email: data.email ?? email };
}

/** Atomically consumes one credit. Returns false when the balance is empty. */
export async function consumeCredit(uid: string): Promise<boolean> {
  const ref = adminDb().collection('users').doc(uid);
  return adminDb().runTransaction(async (tx) => {
    const snap = await tx.get(ref);
    const credits = snap.exists ? (snap.data()!.credits ?? 0) : 0;
    if (credits < 1) return false;
    tx.update(ref, {
      credits: FieldValue.increment(-1),
      totalGenerated: FieldValue.increment(1),
    });
    return true;
  });
}

/** Refunds one credit (used when generation fails after consumption). */
export async function refundCredit(uid: string): Promise<void> {
  await adminDb()
    .collection('users')
    .doc(uid)
    .update({
      credits: FieldValue.increment(1),
      totalGenerated: FieldValue.increment(-1),
    });
}

/** Adds purchased credits (called from the payment webhook). */
export async function addCredits(uid: string, amount: number): Promise<void> {
  await adminDb()
    .collection('users')
    .doc(uid)
    .set(
      {
        credits: FieldValue.increment(amount),
        lastPurchaseAt: FieldValue.serverTimestamp(),
      },
      { merge: true }
    );
}
