import { cert, getApps, initializeApp, type App } from 'firebase-admin/app';
import { getAuth } from 'firebase-admin/auth';
import { getFirestore } from 'firebase-admin/firestore';
import { getStorage } from 'firebase-admin/storage';

// Server-side Firebase Admin SDK.
// Requires FIREBASE_SERVICE_ACCOUNT (raw JSON or base64-encoded JSON of the
// service account key) — when absent the app runs in anonymous demo mode.

function parseServiceAccount(): Record<string, string> | null {
  const raw = process.env.FIREBASE_SERVICE_ACCOUNT;
  if (!raw) return null;
  try {
    const json = raw.trim().startsWith('{')
      ? raw
      : Buffer.from(raw, 'base64').toString('utf8');
    return JSON.parse(json);
  } catch {
    console.error('FIREBASE_SERVICE_ACCOUNT is set but could not be parsed.');
    return null;
  }
}

let app: App | null = null;

function getAdminApp(): App | null {
  if (app) return app;
  const existing = getApps();
  if (existing.length > 0) {
    app = existing[0];
    return app;
  }
  const serviceAccount = parseServiceAccount();
  if (!serviceAccount) return null;
  app = initializeApp({
    credential: cert(serviceAccount),
    storageBucket:
      process.env.FIREBASE_STORAGE_BUCKET ||
      `${serviceAccount.project_id}.firebasestorage.app`,
  });
  return app;
}

export const isAdminEnabled = () => getAdminApp() !== null;

export function adminAuth() {
  const a = getAdminApp();
  if (!a) throw new Error('Firebase Admin is not configured.');
  return getAuth(a);
}

export function adminDb() {
  const a = getAdminApp();
  if (!a) throw new Error('Firebase Admin is not configured.');
  return getFirestore(a);
}

export function adminBucket() {
  const a = getAdminApp();
  if (!a) throw new Error('Firebase Admin is not configured.');
  return getStorage(a).bucket();
}

/** Verifies a Bearer token from the Authorization header. Returns uid + email or null. */
export async function verifyBearer(
  authorization: string | null
): Promise<{ uid: string; email?: string } | null> {
  if (!authorization?.startsWith('Bearer ') || !isAdminEnabled()) return null;
  try {
    const decoded = await adminAuth().verifyIdToken(authorization.slice(7));
    return { uid: decoded.uid, email: decoded.email };
  } catch {
    return null;
  }
}
