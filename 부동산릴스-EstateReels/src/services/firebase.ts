// ════════════════════════════════════════════════════════════════
// Firebase — HEADJIM 공용 프로젝트(headjim-ai) 연동 준비 (선택적 로그인)
// 핵심 기능(이미지 모션영상 합성)은 로컬·무료라 로그인이 전혀 필요 없다.
// 그래서 Firebase는 "지연 초기화" — 사용자가 로그인/지갑을 실제로 쓸 때만 켜서,
// 새 도메인의 App Check 미등록 등으로 앱 전체가 깨지지 않게 한다(연동 준비 단계).
// ════════════════════════════════════════════════════════════════
import { initializeApp, type FirebaseApp } from 'firebase/app'
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, type Auth } from 'firebase/auth'
import { getFirestore, type Firestore } from 'firebase/firestore'
import { initializeAppCheck, ReCaptchaEnterpriseProvider } from 'firebase/app-check'

const firebaseConfig = {
  apiKey: 'AIzaSyDMN5rvLPdaGR0bite5uhw5G2j_M6Au56M',
  authDomain: 'headjim-ai.firebaseapp.com',
  projectId: 'headjim-ai',
  storageBucket: 'headjim-ai.firebasestorage.app',
  messagingSenderId: '677372885975',
  appId: '1:677372885975:web:9ba7238cec260d68162992',
  measurementId: 'G-S6FH06JP4E',
}

// HEADJIM 공용 reCAPTCHA Enterprise 사이트 키(공개 키). 도메인 미등록/로컬에선 조용히 실패.
const RECAPTCHA_SITE_KEY =
  (import.meta.env.VITE_RECAPTCHA_SITE_KEY as string) || '6LcYeFYtAAAAAC_K7jn0K8Wq5QuLro7UFxdp03Rx'

let _app: FirebaseApp | null = null
let _auth: Auth | null = null
let _db: Firestore | null = null

export function getFirebase(): { app: FirebaseApp; auth: Auth; db: Firestore } {
  if (!_app) {
    _app = initializeApp(firebaseConfig)
    // App Check(reCAPTCHA Enterprise) — 최초 initializeApp 직후 1회. 등록 안 된 도메인/로컬에선
    // 토큰 발급이 실패하지만, HEADJIM은 App Check 강제(enforce)를 아직 안 켜서 요청은 그대로 통과.
    // 도메인 콘솔 등록 후에는 토큰이 붙어 이후 enforce 전환에도 대비된다.
    try {
      const host = typeof window !== 'undefined' ? window.location.hostname : ''
      if (host && host !== 'localhost' && host !== '127.0.0.1') {
        initializeAppCheck(_app, {
          provider: new ReCaptchaEnterpriseProvider(RECAPTCHA_SITE_KEY),
          isTokenAutoRefreshEnabled: true,
        })
      }
    } catch (e) {
      console.warn('App Check 초기화 생략:', e)
    }
    _auth = getAuth(_app)
    _db = getFirestore(_app)
  }
  return { app: _app, auth: _auth!, db: _db! }
}

export { GoogleAuthProvider, signInWithPopup, signOut }
