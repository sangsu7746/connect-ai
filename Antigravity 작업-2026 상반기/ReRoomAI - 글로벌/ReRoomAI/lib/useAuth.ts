'use client';

import { useCallback, useEffect, useState } from 'react';
import { onAuthStateChanged, type User } from 'firebase/auth';
import { firebaseAuth, isFirebaseEnabled } from './firebase/client';

export type AuthState = {
  /** false when Firebase env vars are missing → anonymous demo mode only */
  enabled: boolean;
  loading: boolean;
  user: User | null;
  credits: number | null;
  /** re-fetches the credit balance from /api/me */
  refreshCredits: () => Promise<void>;
};

/** Subscribes to Firebase auth state and keeps the credit balance in sync. */
export function useAuth(): AuthState {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(isFirebaseEnabled);
  const [credits, setCredits] = useState<number | null>(null);

  const refreshCredits = useCallback(async () => {
    const auth = firebaseAuth();
    const current = auth?.currentUser;
    if (!current) {
      setCredits(null);
      return;
    }
    try {
      const token = await current.getIdToken();
      const res = await fetch('/api/me', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setCredits(typeof data.credits === 'number' ? data.credits : null);
      }
    } catch {
      // Non-fatal: badge simply shows nothing until the next refresh.
    }
  }, []);

  useEffect(() => {
    const auth = firebaseAuth();
    if (!auth) return;
    const unsub = onAuthStateChanged(auth, (u) => {
      setUser(u);
      setLoading(false);
      if (u) void refreshCredits();
      else setCredits(null);
    });
    return unsub;
  }, [refreshCredits]);

  return { enabled: isFirebaseEnabled, loading, user, credits, refreshCredits };
}
