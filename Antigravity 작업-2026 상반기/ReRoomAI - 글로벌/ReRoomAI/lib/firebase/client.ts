'use client';

import { getApps, initializeApp, type FirebaseApp } from 'firebase/app';
import {
  GoogleAuthProvider,
  getAuth,
  signInWithPopup,
  signOut as fbSignOut,
  type Auth,
} from 'firebase/auth';

// Client-side Firebase. All NEXT_PUBLIC_FIREBASE_* vars must be set for
// sign-in to be available; otherwise the app runs in anonymous demo mode.

const config = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

export const isFirebaseEnabled = Boolean(config.apiKey && config.projectId && config.appId);

let app: FirebaseApp | null = null;

export function firebaseAuth(): Auth | null {
  if (!isFirebaseEnabled) return null;
  if (!app) {
    app = getApps()[0] ?? initializeApp(config);
  }
  return getAuth(app);
}

export async function signInWithGoogle() {
  const auth = firebaseAuth();
  if (!auth) return;
  await signInWithPopup(auth, new GoogleAuthProvider());
}

export async function signOut() {
  const auth = firebaseAuth();
  if (!auth) return;
  await fbSignOut(auth);
}
