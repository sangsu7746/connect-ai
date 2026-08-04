import { initializeApp } from 'firebase/app'
import { initializeAppCheck, ReCaptchaEnterpriseProvider } from 'firebase/app-check'
import { getAuth, GoogleAuthProvider, signInWithPopup, signOut, connectAuthEmulator } from 'firebase/auth'
import { getFirestore, connectFirestoreEmulator, doc, setDoc, getDoc, collection, query, where, getDocs, onSnapshot } from 'firebase/firestore'
import {
  firebaseConfig,
  APPCHECK_SITE_KEY,
  APPCHECK_ENABLED,
  USE_EMULATORS,
  AUTH_EMULATOR_PORT,
  FIRESTORE_EMULATOR_PORT,
} from './firebaseTarget'

// Initialize Firebase
const app = initializeApp(firebaseConfig)

// App Check — 매크로/봇 가입 및 API 남용 방어 (reCAPTCHA Enterprise).
// 메인 홈과 같은 웹 앱ID를 공유하므로 같은 사이트 키를 쓴다.
//
// ⚠️ localhost 개발: reCAPTCHA 사이트 키에 배포 도메인(headjim-ai.web.app)만 등록돼 있어
// 로컬에서는 토큰 발급이 실패한다. App Check 시행(enforce)이 켜진 뒤로는 이게 경고가 아니라
// "Firestore 접근 전면 차단(Missing or insufficient permissions)"으로 이어져 지갑·프로젝트를
// 읽지 못하고 제작이 시작되지 않는다. 그래서 개발 빌드에서는 디버그 토큰 모드를 켠다 —
// 콘솔에 찍히는 토큰을 Firebase Console(App Check → 앱 → 디버그 토큰 관리)에 1회 등록하면
// 로컬에서도 정상 통과한다. 프로덕션 빌드에는 이 플래그가 포함되지 않는다.
if (import.meta.env.DEV) {
  // @ts-expect-error Firebase SDK가 전역에서 읽는 비공개 디버그 플래그
  self.FIREBASE_APPCHECK_DEBUG_TOKEN = true
}

// App Check 키는 프로젝트에 묶여 있다. 다른 프로젝트로 옮기면 새 키를 발급하거나
// VITE_APPCHECK_ENABLED=false 로 초기화 자체를 끈다.
if (APPCHECK_ENABLED) {
  initializeAppCheck(app, {
    provider: new ReCaptchaEnterpriseProvider(APPCHECK_SITE_KEY),
    isTokenAutoRefreshEnabled: true,
  })
}

export const auth = getAuth(app)
export const db = getFirestore(app)
export const googleProvider = new GoogleAuthProvider()

// 로컬 에뮬레이터 격리 — VITE_USE_EMULATORS=true 일 때만 붙는다.
// 이걸 켜야 로그인·지갑·프로젝트 문서가 운영 Firestore 로 새지 않는다.
if (USE_EMULATORS) {
  connectAuthEmulator(auth, `http://localhost:${AUTH_EMULATOR_PORT}`, { disableWarnings: true })
  connectFirestoreEmulator(db, 'localhost', Number(FIRESTORE_EMULATOR_PORT))
  console.info(
    `[firebase] 에뮬레이터 연결됨 — auth:${AUTH_EMULATOR_PORT} firestore:${FIRESTORE_EMULATOR_PORT} (운영 데이터 미접속)`,
  )
}

export { signInWithPopup, signOut, GoogleAuthProvider }
export { doc, setDoc, getDoc, collection, query, where, getDocs, onSnapshot }
