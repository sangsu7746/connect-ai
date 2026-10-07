import { create } from 'zustand'
import { auth, db } from '../services/firebase'
import { onAuthStateChanged, signOut as firebaseSignOut } from 'firebase/auth'
import { doc, setDoc, onSnapshot } from 'firebase/firestore'
import type { User, Entitlement, AppLocale, Plan } from '../types'
import { SUPPORTED_LOCALES } from '../services/localizationService'

const DEFAULT_ENTITLEMENT: Entitlement = { plan: 'free' }

/** 비로그인(guest) 상태로 생성 액션을 시도할 때 던진다 — 생성은 로그인 계정 기준으로만 집계·과금된다 */
export class LoginRequiredError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'LoginRequiredError'
  }
}

// 개발자 본인 계정은 결제 없이 항상 Pro로 취급한다 — 이 앱의 다른 모든 플랜 게이트와 마찬가지로
// 클라이언트에서 판정하는 값이라 완전한 서버측 보안 경계는 아니지만, 기존 entitlement 게이트들도
// 전부 같은 신뢰 모델(클라이언트가 Firestore/로컬 상태를 그대로 믿음)이라 일관성 있는 예외 처리다.
const DEVELOPER_EMAILS = ['headjimkss@gmail.com']

// 실제 화면 게이트에 쓰는 접근 등급 — "무료 영구 + 포인트" 모델.
// guest: 비로그인(생성 불가 — 사용량 집계·지갑이 계정 기준이라 로그인 필수)
// free: 로그인 일반 사용자 — 무빙포토 일일 무료 + 포인트로 프리미엄 제작
// pro: 무과금 특권 계정(개발자 오버라이드 등) — 포인트 차감 없음
export type AccessTier = 'guest' | 'free' | 'pro'

interface UserState {
  user: User | null
  entitlement: Entitlement
  isLoading: boolean
  language: AppLocale

  // actions
  setUser: (user: User | null) => void
  setEntitlement: (e: Entitlement) => void
  setLoading: (v: boolean) => void
  setLanguage: (lang: AppLocale) => void
  logout: () => Promise<void>
  // 만료된 구독은 서버 웹훅이 아직 강등을 반영하기 전이라도 즉시 무료로 취급한 "실효 등급"
  effectivePlan: () => Plan
  isPro: () => boolean
  hasBasicOrAbove: () => boolean
  accessTier: () => AccessTier
  // 로그인만 하면 생성 가능 — 무료 한도·포인트 차감은 walletService.ensureRenderAuthorization이 담당
  canGenerate: () => boolean
}

// 브라우저 언어가 지원 10개 언어 중 하나면 그걸, 아니면 영어로 시작
function detectInitialLocale(): AppLocale {
  const browserLang = navigator.language.slice(0, 2) as AppLocale
  return SUPPORTED_LOCALES.includes(browserLang) ? browserLang : 'en'
}

function effectivePlanOf(entitlement: Entitlement, email?: string | null): Plan {
  if (email && DEVELOPER_EMAILS.includes(email)) return 'pro'
  if (entitlement.expiresAt && entitlement.expiresAt.getTime() < Date.now()) return 'free'
  return entitlement.plan
}

export const useUserStore = create<UserState>()((set, get) => ({
  user: null,
  entitlement: DEFAULT_ENTITLEMENT,
  isLoading: true,
  language: detectInitialLocale(),

  setUser: (user) => set({ user }),
  setEntitlement: (entitlement) => set({ entitlement }),
  setLoading: (isLoading) => set({ isLoading }),
  setLanguage: (language) => {
    set({ language })
    import('../i18n').then(m => m.default.changeLanguage(language))
  },
  logout: async () => {
    await firebaseSignOut(auth)
    set({ user: null, entitlement: DEFAULT_ENTITLEMENT })
  },
  effectivePlan: () => effectivePlanOf(get().entitlement, get().user?.email),
  isPro: () => get().effectivePlan() === 'pro',
  hasBasicOrAbove: () => get().effectivePlan() !== 'free',

  accessTier: () => {
    const { user, effectivePlan } = get()
    if (!user) return 'guest'
    // basic 구독은 UI에서 숨겨져 신규 발생하지 않는다 — 남아있더라도 free와 동일하게 취급
    return effectivePlan() === 'pro' ? 'pro' : 'free'
  },

  canGenerate: () => get().accessTier() !== 'guest',
}))

// ── Firebase Auth & Firestore Entitlements 실시간 동기화 ──
let unsubscribeEntitlement: (() => void) | null = null
let unsubscribeUserDoc: (() => void) | null = null

onAuthStateChanged(auth, async (firebaseUser) => {
  const store = useUserStore.getState()

  if (unsubscribeEntitlement) {
    unsubscribeEntitlement()
    unsubscribeEntitlement = null
  }
  if (unsubscribeUserDoc) {
    unsubscribeUserDoc()
    unsubscribeUserDoc = null
  }

  if (firebaseUser) {
    const userDocRef = doc(db, 'users', firebaseUser.uid)
    const entitlementDocRef = doc(db, 'entitlements', firebaseUser.uid)

    // 1. 사용자 프로필 우선 반영 — createdAt은 아직 모르니 잠정적으로 지금 시각을 넣어두고,
    // 곧이어 구독하는 Firestore 문서에서 서버가 기록한 실제 값이 오면 덮어쓴다
    const provisionalProfile: User = {
      uid: firebaseUser.uid,
      email: firebaseUser.email ?? '',
      displayName: firebaseUser.displayName ?? '사용자',
      photoURL: firebaseUser.photoURL ?? undefined,
      locale: store.language,
      createdAt: new Date(),
    }
    store.setUser(provisionalProfile)

    try {
      await setDoc(userDocRef, {
        email: provisionalProfile.email,
        displayName: provisionalProfile.displayName,
        photoURL: provisionalProfile.photoURL,
        lastActiveAt: new Date(),
      }, { merge: true })
    } catch (e) {
      console.error('Failed to sync user profile:', e)
    }

    // 2. 사용자 문서 실시간 구독 — Cloud Functions(onUserCreate)가 기록한 진짜 createdAt이
    // 도착하면 트라이얼 기산일을 정확한 값으로 갱신한다
    unsubscribeUserDoc = onSnapshot(userDocRef, (snap) => {
      const data = snap.data()
      const createdAt = data?.createdAt?.toDate?.()
      if (createdAt) {
        const current = useUserStore.getState().user
        if (current) useUserStore.getState().setUser({ ...current, createdAt })
      }
    }, (err) => {
      console.error('Subscription error for user profile:', err)
    })

    // 3. 결제 권한 정보 실시간 구독 — 결제 이력이 없는 사용자는 문서 자체가 없으므로(무료) 기본값 사용
    unsubscribeEntitlement = onSnapshot(entitlementDocRef, (snap) => {
      const data = snap.data()
      store.setEntitlement(data ? {
        plan: (data.plan as Plan) ?? 'free',
        source: data.source,
        paypalId: data.paypalId,
        status: data.status,
        renewedAt: data.renewedAt?.toDate?.(),
        expiresAt: data.expiresAt?.toDate?.(),
      } : DEFAULT_ENTITLEMENT)
      store.setLoading(false)
    }, (err) => {
      console.error('Subscription error for entitlements:', err)
      store.setEntitlement(DEFAULT_ENTITLEMENT)
      store.setLoading(false)
    })

  } else {
    store.setUser(null)
    store.setEntitlement(DEFAULT_ENTITLEMENT)
    store.setLoading(false)
  }
})
