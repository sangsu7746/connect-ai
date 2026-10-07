// ════════════════════════════════════════════════════════════════
// 사용자 스토어 — 개별 로그인/회원가입(이메일·비밀번호) + Google.
// 계정은 HEADJIM 공용 프로젝트(headjim-ai)에 만들어져 코인 지갑이 전 서비스에서 공유된다.
// 핵심 제작은 로그인 후 이용(무료 2회) — 로그인은 코인·내 작업 동기화용.
// ════════════════════════════════════════════════════════════════
import { create } from 'zustand'
import type { User } from '../types'

const DEVELOPER_EMAILS = ['headjimkss@gmail.com']

/** Firebase Auth 에러 코드를 한국어 안내로. */
function authErrorMessage(e: unknown): string {
  const code = (e as { code?: string })?.code || ''
  if (code.includes('email-already-in-use')) return '이미 가입된 이메일이에요. 로그인해 주세요.'
  if (code.includes('invalid-email')) return '이메일 형식이 올바르지 않아요.'
  if (code.includes('weak-password')) return '비밀번호는 6자 이상이어야 해요.'
  if (code.includes('wrong-password') || code.includes('invalid-credential')) return '이메일 또는 비밀번호가 올바르지 않아요.'
  if (code.includes('user-not-found')) return '가입되지 않은 이메일이에요. 회원가입해 주세요.'
  if (code.includes('too-many-requests')) return '시도가 너무 많아요. 잠시 후 다시 시도해 주세요.'
  if (code.includes('popup-closed-by-user') || code.includes('cancelled-popup')) return '로그인 창이 닫혔어요.'
  if (code.includes('operation-not-allowed')) return '이메일 로그인이 비활성화되어 있어요. 관리자에게 문의해 주세요.'
  if (code.includes('network')) return '네트워크 오류예요. 연결을 확인해 주세요.'
  return '처리 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요.'
}

interface UserState {
  user: User | null
  authReady: boolean
  authBusy: boolean
  loginError: string
  authNotice: string
  isDeveloper: () => boolean
  loginWithGoogle: () => Promise<void>
  loginWithEmail: (email: string, password: string) => Promise<void>
  signupWithEmail: (email: string, password: string) => Promise<void>
  resendVerification: () => Promise<void>
  logout: () => Promise<void>
}

export const useUserStore = create<UserState>()((set, get) => ({
  user: null,
  authReady: false,
  authBusy: false,
  loginError: '',
  authNotice: '',
  isDeveloper: () => !!get().user && DEVELOPER_EMAILS.includes(get().user!.email),

  loginWithGoogle: async () => {
    set({ loginError: '', authNotice: '', authBusy: true })
    try {
      const { getFirebase, GoogleAuthProvider, signInWithPopup } = await import('../services/firebase')
      await signInWithPopup(getFirebase().auth, new GoogleAuthProvider())
    } catch (e) {
      set({ loginError: authErrorMessage(e) })
      console.warn('google login failed:', e)
    } finally { set({ authBusy: false }) }
  },

  loginWithEmail: async (email, password) => {
    set({ loginError: '', authNotice: '', authBusy: true })
    try {
      const { getFirebase } = await import('../services/firebase')
      const { signInWithEmailAndPassword } = await import('firebase/auth')
      await signInWithEmailAndPassword(getFirebase().auth, email.trim(), password)
    } catch (e) {
      set({ loginError: authErrorMessage(e) })
    } finally { set({ authBusy: false }) }
  },

  signupWithEmail: async (email, password) => {
    set({ loginError: '', authNotice: '', authBusy: true })
    try {
      const { getFirebase } = await import('../services/firebase')
      const { createUserWithEmailAndPassword, sendEmailVerification } = await import('firebase/auth')
      const cred = await createUserWithEmailAndPassword(getFirebase().auth, email.trim(), password)
      try { await sendEmailVerification(cred.user) } catch { /* 인증메일 실패는 치명 아님 */ }
      set({ authNotice: '가입이 완료됐어요! 인증 메일을 보냈으니 메일함에서 확인해 주세요.' })
    } catch (e) {
      set({ loginError: authErrorMessage(e) })
    } finally { set({ authBusy: false }) }
  },

  resendVerification: async () => {
    set({ loginError: '', authNotice: '' })
    try {
      const { getFirebase } = await import('../services/firebase')
      const { sendEmailVerification } = await import('firebase/auth')
      const u = getFirebase().auth.currentUser
      if (u) { await sendEmailVerification(u); set({ authNotice: '인증 메일을 다시 보냈어요.' }) }
    } catch (e) { set({ loginError: authErrorMessage(e) }) }
  },

  logout: async () => {
    try {
      const { getFirebase, signOut } = await import('../services/firebase')
      await signOut(getFirebase().auth)
    } catch { /* ignore */ }
    set({ user: null, loginError: '', authNotice: '' })
  },
}))

// Auth 세션 복원 — 지연 초기화가 안전한 시점에 1회 구독(SDK 초기화는 오프라인 안전).
let inited = false
export async function initAuth() {
  if (inited) return
  inited = true
  try {
    const { getFirebase } = await import('../services/firebase')
    const { onAuthStateChanged } = await import('firebase/auth')
    const { auth } = getFirebase()
    onAuthStateChanged(auth, (fb) => {
      if (fb) {
        useUserStore.setState({
          user: {
            uid: fb.uid,
            email: fb.email ?? '',
            displayName: fb.displayName ?? (fb.email ? fb.email.split('@')[0] : '사용자'),
            photoURL: fb.photoURL ?? undefined,
            emailVerified: fb.emailVerified,
            createdAt: new Date(),
          },
          authReady: true,
        })
      } else {
        useUserStore.setState({ user: null, authReady: true })
      }
    })
  } catch (e) {
    console.warn('auth init skipped:', e)
    useUserStore.setState({ authReady: true })
  }
}
