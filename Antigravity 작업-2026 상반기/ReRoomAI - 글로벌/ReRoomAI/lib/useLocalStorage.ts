'use client';

import { useCallback, useSyncExternalStore } from 'react';

const STORAGE_EVENT = 'reroom:storage';

/**
 * localStorage와 동기화되는 상태 훅.
 * useSyncExternalStore를 사용해 SSR 하이드레이션 불일치 없이
 * 마운트 직후 저장된 값으로 자동 갱신된다.
 */
export function useLocalStorage(key: string, fallback: string) {
  const subscribe = useCallback((onChange: () => void) => {
    window.addEventListener(STORAGE_EVENT, onChange);
    window.addEventListener('storage', onChange);
    return () => {
      window.removeEventListener(STORAGE_EVENT, onChange);
      window.removeEventListener('storage', onChange);
    };
  }, []);

  const value = useSyncExternalStore(
    subscribe,
    () => localStorage.getItem(key) ?? fallback,
    () => fallback
  );

  const setValue = useCallback(
    (next: string) => {
      localStorage.setItem(key, next);
      window.dispatchEvent(new Event(STORAGE_EVENT));
    },
    [key]
  );

  return [value, setValue] as const;
}
