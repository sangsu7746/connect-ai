import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { onAuthStateChanged } from 'firebase/auth'
import { doc, setDoc, getDoc, arrayUnion, arrayRemove } from 'firebase/firestore'
import { auth, db } from '../services/firebase'
import type { ProviderKey, KeyStatus, QuotaInfo } from '../types'

// 알리바바 신규 가입 무료 쿼터(초) — KeysPage 안내 문구·쿼터 대시보드·영상 생성 파이프라인이 공유하는 기준값
export const ALIBABA_FREE_QUOTA_SECONDS = 1650

// 알리바바 무료 쿼터 유효 기간(일) — 키 등록 시점부터 계산하는 추정 기본값. 정확한 만료일은
// 알리바바 콘솔에서 계정별로 확인해야 하며, 여기 값은 "기한이 지나면 사용자 모르게 유료 과금으로
// 넘어가는 사고"를 막기 위한 보수적 안전장치다.
export const ALIBABA_FREE_QUOTA_DAYS = 90

// Gemini 무료 티어는 "초"가 아니라 "하루 요청 수"로 태평양 시간 자정에 리셋된다. 공개된 수치가
// 출처마다 들쭉날쭉하고(같은 모델을 두고 250~1,500회로 갈림) 계정/등급에 따라서도 달라서, 과신하지
// 않도록 보수적인 하한값을 경고용 기준치로만 쓴다 — 실제 한도는 Google AI Studio에서 계정별로 확인해야 한다.
export const GEMINI_FREE_IMAGE_RPD = 500 // gemini-2.5-flash-image (키프레임 이미지 생성)
export const GEMINI_FREE_TEXT_RPD = 250  // gemini-2.5-flash (닮음새 검증·정밀검수·인물 캡션·번역)

/** 구글 Gemini 무료 쿼터가 리셋되는 태평양 시간 기준 오늘 날짜(YYYY-MM-DD). */
function getPacificDateString(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Los_Angeles' })
}

// ── KeyVault: IndexedDB + WebCrypto 래퍼 ──────────────────────
const DB_NAME = 'memoryframe-vault'
const STORE_NAME = 'keys'

async function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => req.result.createObjectStore(STORE_NAME)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

async function getEncryptionKey(): Promise<CryptoKey> {
  // 브라우저 세션마다 동일한 키를 파생 (deviceId 기반)
  let deviceId = localStorage.getItem('mf_did')
  if (!deviceId) {
    deviceId = crypto.randomUUID()
    localStorage.setItem('mf_did', deviceId)
  }
  const raw = new TextEncoder().encode(deviceId.padEnd(32, '0').slice(0, 32))
  return crypto.subtle.importKey('raw', raw, 'AES-GCM', false, ['encrypt', 'decrypt'])
}

async function encryptValue(value: string): Promise<string> {
  const key = await getEncryptionKey()
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const encoded = new TextEncoder().encode(value)
  const cipher = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, encoded)
  const combined = new Uint8Array([...iv, ...new Uint8Array(cipher)])
  return btoa(String.fromCharCode(...combined))
}

async function decryptValue(encrypted: string): Promise<string> {
  const key = await getEncryptionKey()
  const combined = new Uint8Array(atob(encrypted).split('').map(c => c.charCodeAt(0)))
  const iv = combined.slice(0, 12)
  const cipher = combined.slice(12)
  const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, key, cipher)
  return new TextDecoder().decode(plain)
}

export const KeyVault = {
  async setKey(provider: ProviderKey, apiKey: string): Promise<void> {
    const encrypted = await encryptValue(apiKey)
    const db = await openDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      tx.objectStore(STORE_NAME).put(encrypted, provider)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
  },

  async getKey(provider: ProviderKey): Promise<string | null> {
    const db = await openDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readonly')
      const req = tx.objectStore(STORE_NAME).get(provider)
      req.onsuccess = async () => {
        if (!req.result) return resolve(null)
        try { resolve(await decryptValue(req.result)) }
        catch { resolve(null) }
      }
      req.onerror = () => reject(req.error)
    })
  },

  async removeKey(provider: ProviderKey): Promise<void> {
    const db = await openDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite')
      tx.objectStore(STORE_NAME).delete(provider)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
    })
  },

  async hasKey(provider: ProviderKey): Promise<boolean> {
    const key = await KeyVault.getKey(provider)
    return key !== null && key.length > 0
  }
}

// ── Zustand 스토어 ────────────────────────────────────────────

interface KeysState {
  keyStatuses: Record<ProviderKey, KeyStatus>
  quotas: Record<string, QuotaInfo>
  isValidating: Record<string, boolean>
  // 알리바바 무료 쿼터 만료일(ISO) — 키 등록 시점 + ALIBABA_FREE_QUOTA_DAYS로 자동 설정.
  // 만료가 지나면 알리바바 API 사용이 전면 자동 중단되고, 사용자가 갱신을 확인해야 재개된다.
  alibabaFreeExpiresAt: string | null
  // 사용자가 "유료 전환했음(기한 없이 사용)"을 명시적으로 확인한 상태 — true면 만료 검사를 건너뛴다
  alibabaPaidMode: boolean
  // 로그인한 계정에 "이 기기든 저 기기든 한 번은 등록했었다"고 기록된 제공자 목록(값 자체는 없음) —
  // 실제 키 값은 계속 기기 로컬(IndexedDB)에만 있고, 이건 "다른 기기에서 등록됨" 안내용 표시일 뿐이라
  // KeyVault.hasKey() 같은 실제 사용 가능 여부 판단에는 절대 쓰지 않는다
  accountRegisteredProviders: ProviderKey[]

  // actions
  setKeyStatus: (provider: ProviderKey, status: Partial<KeyStatus>) => void
  setQuota: (provider: ProviderKey, quota: QuotaInfo) => void
  setValidating: (provider: ProviderKey, val: boolean) => void
  saveKey: (provider: ProviderKey, key: string) => Promise<void>
  removeKey: (provider: ProviderKey) => Promise<void>
  updateUsage: (provider: ProviderKey, secondsUsed: number) => void
  // 만료 후 사용자가 갱신을 확인했을 때 — 새 무료 쿼터(+90일) 또는 유료 전환(기한 없음)으로 재개
  renewAlibabaFree: () => void
  confirmAlibabaPaid: () => void
  updateGeminiUsage: (kind: 'image' | 'text') => void
  getGeminiUsageToday: () => { image: number; text: number }
  loadAccountProviders: (uid: string) => Promise<void>
  clearAccountProviders: () => void
}

const makeDefaultStatus = (provider: ProviderKey): KeyStatus => ({
  provider, isSet: false, isValid: null
})

const DEFAULT_PROVIDERS: ProviderKey[] = ['alibaba', 'seedance', 'hailuo', 'kling', 'veo', 'runway', 'gemini', 'kaggle']

/**
 * 로그인한 계정 문서에 "이 제공자는 (어느 기기에서든) 한 번 등록됐었다"는 표시만 남긴다.
 * 키 값 자체는 절대 보내지 않는다 — 로그인 안 한 상태면 그냥 조용히 넘어간다(게스트 이용은 계속 가능).
 */
async function syncAccountProviderFlag(provider: ProviderKey, isSet: boolean) {
  const uid = auth.currentUser?.uid
  if (!uid) return
  try {
    await setDoc(
      doc(db, 'users', uid),
      { registeredProviders: isSet ? arrayUnion(provider) : arrayRemove(provider) },
      { merge: true }
    )
  } catch (e) {
    console.error('계정 API 키 등록 상태 동기화 실패(로컬 저장에는 영향 없음):', e)
  }
}

export const useKeysStore = create<KeysState>()(
  persist(
    (set, get) => ({
      keyStatuses: Object.fromEntries(
        DEFAULT_PROVIDERS.map(p => [p, makeDefaultStatus(p)])
      ) as Record<ProviderKey, KeyStatus>,
      quotas: {},
      isValidating: {},
      alibabaFreeExpiresAt: null,
      alibabaPaidMode: false,
      accountRegisteredProviders: [],

      setKeyStatus: (provider, status) => set(state => ({
        keyStatuses: {
          ...state.keyStatuses,
          [provider]: { ...state.keyStatuses[provider], ...status }
        }
      })),

      setQuota: (provider, quota) => set(state => ({
        quotas: { ...state.quotas, [provider]: quota }
      })),

      setValidating: (provider, val) => set(state => ({
        isValidating: { ...state.isValidating, [provider]: val }
      })),

      saveKey: async (provider, key) => {
        let normalized = key.trim()
        // Kaggle은 kaggle.json 파일 내용을 통째로 붙여넣어도 되게 지원한다 — username을 따로
        // 몰라도 파일 안의 두 값을 자동 추출해 내부 저장 형식("username:key")으로 변환한다.
        if (provider === 'kaggle' && normalized.startsWith('{')) {
          try {
            const parsed = JSON.parse(normalized)
            if (parsed.username && parsed.key) normalized = `${parsed.username}:${parsed.key}`
          } catch {
            // JSON이 아니면 입력 원문 그대로 저장 (유저명:토큰 직접 입력 케이스)
          }
        }
        await KeyVault.setKey(provider, normalized)
        set(state => ({
          keyStatuses: {
            ...state.keyStatuses,
            [provider]: { ...state.keyStatuses[provider], isSet: true, isValid: null }
          },
          // 알리바바 키를 (재)등록하면 무료 쿼터 시계가 시작된다 — 이미 추적 중이면 유지
          ...(provider === 'alibaba' && !get().alibabaFreeExpiresAt && !get().alibabaPaidMode
            ? { alibabaFreeExpiresAt: new Date(Date.now() + ALIBABA_FREE_QUOTA_DAYS * 86400_000).toISOString() }
            : {}),
        }))
        syncAccountProviderFlag(provider, true)
      },

      removeKey: async (provider) => {
        await KeyVault.removeKey(provider)
        set(state => ({
          keyStatuses: {
            ...state.keyStatuses,
            [provider]: makeDefaultStatus(provider)
          },
          // 키를 지우면 만료 추적도 초기화 — 새 키 등록 시 새 시계로 시작
          ...(provider === 'alibaba' ? { alibabaFreeExpiresAt: null, alibabaPaidMode: false } : {}),
        }))
        syncAccountProviderFlag(provider, false)
      },

      renewAlibabaFree: () => set({
        alibabaFreeExpiresAt: new Date(Date.now() + ALIBABA_FREE_QUOTA_DAYS * 86400_000).toISOString(),
        alibabaPaidMode: false,
      }),

      confirmAlibabaPaid: () => set({ alibabaPaidMode: true }),

      updateUsage: (provider, secondsUsed) => set(state => {
        const prev = state.quotas[provider] ?? {
          provider, estimatedSecondsUsed: 0,
          totalFreeSeconds: provider === 'alibaba' ? ALIBABA_FREE_QUOTA_SECONDS : undefined,
        }
        return {
          quotas: {
            ...state.quotas,
            [provider]: { ...prev, estimatedSecondsUsed: prev.estimatedSecondsUsed + secondsUsed }
          }
        }
      }),

      updateGeminiUsage: (kind) => set(state => {
        const today = getPacificDateString()
        const prev = state.quotas['gemini']
        const base: QuotaInfo = prev?.geminiQuotaDate === today
          ? prev
          : { provider: 'gemini', estimatedSecondsUsed: 0, geminiImageRequestsToday: 0, geminiTextRequestsToday: 0, geminiQuotaDate: today }
        return {
          quotas: {
            ...state.quotas,
            gemini: {
              ...base,
              geminiImageRequestsToday: (base.geminiImageRequestsToday ?? 0) + (kind === 'image' ? 1 : 0),
              geminiTextRequestsToday: (base.geminiTextRequestsToday ?? 0) + (kind === 'text' ? 1 : 0),
            }
          }
        }
      }),

      // 저장된 카운터를 그대로 읽지 않고 오늘 날짜와 비교해서 돌려준다 — 자정이 지난 뒤 새 API
      // 호출이 아직 한 번도 없었어도(즉 updateGeminiUsage가 안 불려도) 화면엔 0으로 보이게 하기 위함
      getGeminiUsageToday: () => {
        const q = get().quotas['gemini']
        if (!q || q.geminiQuotaDate !== getPacificDateString()) return { image: 0, text: 0 }
        return { image: q.geminiImageRequestsToday ?? 0, text: q.geminiTextRequestsToday ?? 0 }
      },

      loadAccountProviders: async (uid) => {
        try {
          const snap = await getDoc(doc(db, 'users', uid))
          const list = (snap.data()?.registeredProviders ?? []) as ProviderKey[]
          set({ accountRegisteredProviders: list })
        } catch (e) {
          console.error('계정 API 키 등록 상태 불러오기 실패:', e)
        }
      },

      clearAccountProviders: () => set({ accountRegisteredProviders: [] }),
    }),
    {
      name: 'memoryframe-keys-meta',
      // 키 자체는 IndexedDB에, 메타 상태만 localStorage에
      partialize: (s) => ({
        keyStatuses: s.keyStatuses,
        quotas: s.quotas,
        alibabaFreeExpiresAt: s.alibabaFreeExpiresAt,
        alibabaPaidMode: s.alibabaPaidMode,
      })
    }
  )
)

// 로그인 시 계정에 기록된 "등록했던 제공자" 표시를 불러오고, 로그아웃 시(또는 다른 계정 전환 시)
// 이전 계정의 표시가 남아있지 않도록 비운다 — userStore.ts와 동일한 onAuthStateChanged 패턴
onAuthStateChanged(auth, (firebaseUser) => {
  if (firebaseUser) {
    useKeysStore.getState().loadAccountProviders(firebaseUser.uid)
  } else {
    useKeysStore.getState().clearAccountProviders()
  }
})

// ── 알리바바 무료 기한 검사 (비 React 코드 공용) ──────────────

/** 무료 기한까지 남은 일수. 추적 안 됨(null)·유료 모드면 null, 만료면 음수/0 이하. */
export function alibabaFreeDaysLeft(): number | null {
  const { alibabaFreeExpiresAt, alibabaPaidMode } = useKeysStore.getState()
  if (alibabaPaidMode || !alibabaFreeExpiresAt) return null
  return Math.ceil((new Date(alibabaFreeExpiresAt).getTime() - Date.now()) / 86400_000)
}

/** 만료로 인해 알리바바 사용이 차단된 상태인지. */
export function isAlibabaBlocked(): boolean {
  const days = alibabaFreeDaysLeft()
  return days !== null && days <= 0
}

/**
 * 알리바바 API 호출 직전에 부르는 안전장치 — 무료 기한이 지났으면 호출 자체를 막는다.
 * (기한이 지난 뒤에도 콘솔에서 "무료 쿼터만 사용"을 해제해둔 계정은 호출마다 실요금이 청구될 수
 * 있으므로, 사용자가 키 설정에서 갱신을 확인하기 전까지는 어떤 알리바바 호출도 나가면 안 된다.)
 */
export function assertAlibabaUsable(): void {
  if (isAlibabaBlocked()) {
    throw new Error(
      '알리바바 무료 사용 기한(등록 후 90일 추정)이 지나 자동으로 사용을 중단했어요 — 기한이 지난 호출은 실제 요금이 청구될 수 있어요. ' +
      '알리바바 콘솔에서 쿼터 상태를 확인한 뒤, 키 설정 화면에서 [무료 쿼터 갱신] 또는 [유료 전환 확인]을 눌러 다시 사용할 수 있어요.'
    )
  }
}

// 기존 사용자 보정 — 만료 추적 도입 전에 알리바바 키를 등록해둔 경우, 지금부터 90일 시계를 시작한다
// (persist는 localStorage라 create 시점에 동기 복원됨)
{
  const s = useKeysStore.getState()
  if (s.keyStatuses['alibaba']?.isSet && !s.alibabaFreeExpiresAt && !s.alibabaPaidMode) {
    useKeysStore.setState({
      alibabaFreeExpiresAt: new Date(Date.now() + ALIBABA_FREE_QUOTA_DAYS * 86400_000).toISOString(),
    })
  }
}
