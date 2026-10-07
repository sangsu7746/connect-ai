/**
 * Firebase 접속 대상을 한 곳에서 결정한다.
 *
 * 이 파일이 생기기 전에는 프로젝트 ID 가 4개 파일에 흩어져 하드코딩돼 있었다
 * (firebase.ts 의 config 7필드, adService/aiAdapters/voiceService 의 함수 URL).
 * 그래서 "랩 사본을 다른 프로젝트로 돌린다"가 불가능했다.
 *
 * ⚠️ 기본값은 전부 기존 리터럴과 동일하다. .env 파일이 하나도 없으면
 *    빌드 산출물의 동작은 이 파일 도입 전과 같다. 랩에서 다른 대상을 쓰고 싶을 때만
 *    .env.local 에 VITE_* 를 채운다.
 *
 * ⚠️ Vite 의 import.meta.env 는 런타임 조회가 아니라 **빌드타임 문자열 치환**이다.
 *    따라서 값을 바꾸려면 반드시 다시 빌드해야 하고, 여기 들어간 값은
 *    번들에 그대로 인라인된다(원래도 그랬다 — 클라이언트 Firebase config 는 공개 정보다).
 */

const env = import.meta.env

export const PROJECT_ID = env.VITE_FB_PROJECT_ID ?? 'headjim-ai'
export const FN_REGION = env.VITE_FN_REGION ?? 'us-central1'

export const firebaseConfig = {
  apiKey: env.VITE_FB_API_KEY ?? 'AIzaSyDMN5rvLPdaGR0bite5uhw5G2j_M6Au56M',
  authDomain: env.VITE_FB_AUTH_DOMAIN ?? `${PROJECT_ID}.firebaseapp.com`,
  projectId: PROJECT_ID,
  storageBucket: env.VITE_FB_STORAGE_BUCKET ?? `${PROJECT_ID}.firebasestorage.app`,
  messagingSenderId: env.VITE_FB_MSG_SENDER_ID ?? '677372885975',
  appId: env.VITE_FB_APP_ID ?? '1:677372885975:web:9ba7238cec260d68162992',
  measurementId: env.VITE_FB_MEASUREMENT_ID ?? 'G-S6FH06JP4E',
}

/**
 * App Check reCAPTCHA Enterprise 사이트 키.
 * 이 키는 프로젝트에 묶여 있으므로 다른 프로젝트로 옮기면 새로 발급해야 한다.
 * 키를 못 구한 상태에서 경고 소음만 나는 것을 막으려면 VITE_APPCHECK_ENABLED=false.
 */
export const APPCHECK_SITE_KEY =
  env.VITE_APPCHECK_SITE_KEY ?? '6LcYeFYtAAAAAC_K7jn0K8Wq5QuLro7UFxdp03Rx'
export const APPCHECK_ENABLED = (env.VITE_APPCHECK_ENABLED ?? 'true') !== 'false'

/** Auth·Firestore 에뮬레이터 연결 여부 (기본 꺼짐 — 켜야만 로컬 격리된다) */
export const USE_EMULATORS = env.VITE_USE_EMULATORS === 'true'
export const AUTH_EMULATOR_PORT = env.VITE_AUTH_EMULATOR_PORT ?? '9099'
export const FIRESTORE_EMULATOR_PORT = env.VITE_FIRESTORE_EMULATOR_PORT ?? '8080'

const FN_EMULATOR_PORT = env.VITE_FN_EMULATOR_PORT ?? '5001'

/**
 * 함수 에뮬레이터 사용 여부.
 * 명시적 env 가 없으면 기존과 같이 hostname 으로 판정한다.
 *
 * ⚠️ 의도된 미세 변경: 기존에 adService 만 'localhost' 만 보고 '127.0.0.1' 은
 *    프로덕션으로 취급했다(같은 로컬인데 aiAdapters/voiceService 와 갈렸다).
 *    여기서 127.0.0.1 포함으로 통일한다.
 */
export const USE_FN_EMULATOR = (() => {
  const flag = env.VITE_USE_FN_EMULATOR
  if (flag === 'true') return true
  if (flag === 'false') return false
  const h = window.location.hostname
  return h === 'localhost' || h === '127.0.0.1'
})()

/** 함수 베이스 URL (fnUrl 보다 먼저 초기화돼야 하므로 위에 둔다) */
export const FN_BASE = USE_FN_EMULATOR
  ? `http://localhost:${FN_EMULATOR_PORT}/${PROJECT_ID}/${FN_REGION}`
  : `https://${FN_REGION}-${PROJECT_ID}.cloudfunctions.net`

/** 함수 절대 URL — 프로덕션/에뮬레이터 양쪽을 한 곳에서 만든다. */
export function fnUrl(name: string): string {
  return `${FN_BASE}/${name}`
}
