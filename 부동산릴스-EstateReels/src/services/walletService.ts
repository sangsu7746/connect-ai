// ════════════════════════════════════════════════════════════════
// 공용 코인 지갑 — HEADJIM 공용 wallets/{uid}
//  · subscribeBalance : 잔액 실시간 구독(읽기 전용, 본인만)
//  · spendCoins       : 코인 차감(서버 callable 'spendCoins'). 잔액 쓰기는 서버 전용이라
//                       클라이언트는 이 함수로만 차감한다(refId 멱등 — 재시도 이중차감 방지).
//  충전은 메인 홈(www.headjim.com/#points)에서만. 규약: 리포 WALLET_API.md.
// ════════════════════════════════════════════════════════════════
import { getFirebase } from './firebase'
import { doc, onSnapshot } from 'firebase/firestore'

export function subscribeBalance(uid: string, cb: (balance: number | null) => void): () => void {
  try {
    const { db } = getFirebase()
    const ref = doc(db, 'wallets', uid)
    return onSnapshot(ref, (snap) => {
      const data = snap.data()
      cb(data ? (data.balance ?? 0) : 0)
    }, () => cb(null))
  } catch {
    cb(null)
    return () => {}
  }
}

export interface SpendResult { alreadySpent: boolean; spent: number; balance: number }
export type SpendErrorCode = 'unauthenticated' | 'insufficient' | 'invalid' | 'unknown'
export interface SpendError { code: SpendErrorCode; balance?: number; required?: number; message: string }

/** 코인 차감 — 성공 시 {alreadySpent, spent, balance}. 실패 시 SpendError를 throw. */
export async function spendCoins(args: {
  coins: number; service: string; reason?: string; refId?: string
}): Promise<SpendResult> {
  const { getFunctions, httpsCallable } = await import('firebase/functions')
  const { app } = getFirebase()
  try {
    const fn = httpsCallable(getFunctions(app), 'spendCoins')
    const res = await fn(args)
    return res.data as SpendResult
  } catch (e) {
    throw classifySpendError(e)
  }
}

/** Firebase callable 에러를 앱이 다루기 쉬운 SpendError로 변환. */
export function classifySpendError(e: unknown): SpendError {
  const err = e as { code?: string; message?: string }
  const code = err?.code || ''
  const message = err?.message || String(e)
  if (code.includes('unauthenticated')) return { code: 'unauthenticated', message }
  if (code.includes('failed-precondition') || /INSUFFICIENT_BALANCE/i.test(message)) {
    const m = message.match(/balance=(\d+).*required=(\d+)/i)
    return { code: 'insufficient', balance: m ? Number(m[1]) : undefined, required: m ? Number(m[2]) : undefined, message }
  }
  if (code.includes('invalid-argument')) return { code: 'invalid', message }
  return { code: 'unknown', message }
}
