import { doc, getDoc, setDoc, increment } from 'firebase/firestore'
import { db } from './firebase'

/** 하루 단위 생성 한도(무빙포토·AI영상 등)를 넘었을 때 던지는 전용 에러 */
export class DailyLimitError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'DailyLimitError'
  }
}

function todayId(): string {
  return new Date().toISOString().slice(0, 10) // "2026-07-12" — 사용자 로컬 자정이 아니라 UTC 기준 하루 단위
}

/**
 * usage/{uid}/{bucket}/{yyyy-mm-dd} 문서의 값을 확인해 한도를 넘으면 DailyLimitError를 던지고,
 * 아니면 amount만큼 늘린다. 무빙포토·AI영상은 TTS(Cloud Functions 비용 발생)와 달리 로컬 처리나
 * 사용자 본인 API 키(BYOK)로 동작해 앱에 직접 비용이 들지 않으므로, 서버(Admin SDK) 대신
 * 클라이언트에서 직접 집계한다 — 조작해도 본인 무료 한도만 늘어날 뿐 앱 비용에는 영향이 없다.
 */
export async function checkAndIncrementDaily(
  uid: string,
  bucket: 'movingPhoto' | 'aiVideoSeconds' | 'keyframeDownload',
  field: string,
  limit: number,
  amount: number,
  exceededMessage: string
): Promise<void> {
  const ref = doc(db, 'usage', uid, bucket, todayId())
  const snap = await getDoc(ref)
  const current = snap.exists() ? ((snap.data()[field] as number) ?? 0) : 0

  if (current + amount > limit) {
    throw new DailyLimitError(exceededMessage)
  }

  await setDoc(ref, { [field]: increment(amount), updatedAt: new Date() }, { merge: true })
}

/**
 * 오늘 소비한 일일 카운트를 amount만큼 되돌린다 — 제작이 하나도 완성되지 못하고 전체 실패했을 때
 * 무료 슬롯을 되살리는 용도. 0 아래로는 내려가지 않는다.
 */
export async function decrementDaily(
  uid: string,
  bucket: 'movingPhoto' | 'aiVideoSeconds' | 'keyframeDownload',
  field: string,
  amount: number
): Promise<void> {
  const ref = doc(db, 'usage', uid, bucket, todayId())
  const snap = await getDoc(ref)
  const current = snap.exists() ? ((snap.data()[field] as number) ?? 0) : 0
  const rollback = Math.min(current, amount)
  if (rollback <= 0) return
  await setDoc(ref, { [field]: increment(-rollback), updatedAt: new Date() }, { merge: true })
}
