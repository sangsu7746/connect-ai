import { cert, getApps, initializeApp, type App } from 'firebase-admin/app';
import { getFirestore } from 'firebase-admin/firestore';
import { getStorage } from 'firebase-admin/storage';
import { createRemoteJWKSet, jwtVerify } from 'jose';

// Server-side Firebase Admin SDK.
// Requires FIREBASE_SERVICE_ACCOUNT (raw JSON or base64-encoded JSON of the
// service account key) — when absent the app runs in anonymous demo mode.
//
// ID tokens are verified with `jose` directly against Google's JWKS instead of
// firebase-admin/auth: its jwks-rsa dependency require()s the ESM-only jose v6,
// which crashes on Vercel's serverless runtime.

let serviceAccountCache: Record<string, string> | null | undefined;

function parseServiceAccount(): Record<string, string> | null {
  if (serviceAccountCache !== undefined) return serviceAccountCache;
  const raw = process.env.FIREBASE_SERVICE_ACCOUNT;
  if (!raw) {
    serviceAccountCache = null;
    return null;
  }
  try {
    const json = raw.trim().startsWith('{')
      ? raw
      : Buffer.from(raw, 'base64').toString('utf8');
    serviceAccountCache = JSON.parse(json);
  } catch {
    console.error('FIREBASE_SERVICE_ACCOUNT is set but could not be parsed.');
    serviceAccountCache = null;
  }
  return serviceAccountCache ?? null;
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

// Google's public JWKS for Firebase Auth ID tokens (securetoken signer)
const FIREBASE_JWKS = createRemoteJWKSet(
  new URL('https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com')
);

/** Verifies a Firebase ID token from the Authorization header. Returns uid + email or null. */
export async function verifyBearer(
  authorization: string | null
): Promise<{ uid: string; email?: string } | null> {
  if (!authorization?.startsWith('Bearer ') || !isAdminEnabled()) return null;
  const projectId = parseServiceAccount()?.project_id;
  if (!projectId) return null;
  try {
    const { payload } = await jwtVerify(authorization.slice(7), FIREBASE_JWKS, {
      issuer: `https://securetoken.google.com/${projectId}`,
      audience: projectId,
    });
    if (typeof payload.sub !== 'string' || !payload.sub) return null;
    // Firebase sets auth_time/user_id claims; sub is the uid.
    return {
      uid: payload.sub,
      email: typeof payload.email === 'string' ? payload.email : undefined,
    };
  } catch {
    return null;
  }
}
