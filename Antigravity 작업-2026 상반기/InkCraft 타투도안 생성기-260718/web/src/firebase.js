// Firebase 연동 — .env에 VITE_FIREBASE_*가 채워져 있을 때만 활성화.
// 비어 있으면 앱은 로컬 프록시(server/) 모드로 동작한다.
// 코인은 HEADJIM 공용 지갑(wallets/{uid}.balance, 1코인=₩1)을 사용 —
// PrintCraft·ColorCraft·오마주앱과 같은 지갑이라 충전 코인을 어디서든 쓸 수 있다.
import { initializeApp } from 'firebase/app';
import {
  getAuth,
  GoogleAuthProvider,
  signInWithPopup,
  signOut as fbSignOut,
  onAuthStateChanged,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  sendEmailVerification,
  sendPasswordResetEmail,
} from 'firebase/auth';
import { getFunctions, httpsCallable } from 'firebase/functions';
import { getFirestore, doc, onSnapshot } from 'firebase/firestore';

const cfg = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const firebaseEnabled = Boolean(cfg.apiKey && cfg.projectId);

let auth = null;
let functions = null;
let firestore = null;

if (firebaseEnabled) {
  const app = initializeApp(cfg);
  auth = getAuth(app);
  functions = getFunctions(app);
  firestore = getFirestore(app);
}

export function watchAuth(callback) {
  if (!firebaseEnabled) return () => {};
  return onAuthStateChanged(auth, callback);
}

/** 공용 지갑 잔액 실시간 구독 */
export function watchWallet(uid, callback) {
  if (!firebaseEnabled || !uid) return () => {};
  return onSnapshot(doc(firestore, 'wallets', uid), (snap) => {
    callback(snap.data()?.balance ?? 0);
  });
}

export async function signIn() {
  await signInWithPopup(auth, new GoogleAuthProvider());
}

export async function signOut() {
  await fbSignOut(auth);
}

/** 이메일 가입 — 인증 메일 발송 (웰컴 코인은 메인 홈 트리거가 담당) */
export async function emailSignUp(email, password) {
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  await sendEmailVerification(cred.user);
  return cred.user;
}

export async function emailSignIn(email, password) {
  const cred = await signInWithEmailAndPassword(auth, email, password);
  return cred.user;
}

export async function resetPassword(email) {
  await sendPasswordResetEmail(auth, email);
}

export async function resendVerification() {
  if (auth?.currentUser) await sendEmailVerification(auth.currentUser);
}

/** 타투 도안 생성 — 기본(무료3/일→10코인) / 프리미엄(150코인) · color: 'bw'|'color' */
export async function generateDesignViaFirebase({ subject, style, engine, color }) {
  const fn = httpsCallable(functions, 'ikGenerateDesign');
  const { data } = await fn({ subject, style, engine, color });
  return data; // {image, quota, charged, translatedPrompt, engine}
}

/** AI 시착 — 내 사진에 도안을 실제 타투처럼 합성 (150코인, 실패 시 환불) */
export async function applyTattooViaFirebase({ photo, design }) {
  const fn = httpsCallable(functions, 'ikApplyTattooAI');
  const { data } = await fn({ photo, design });
  return data; // {image, charged}
}

/** 가상 모델 뷰 1프레임 (100코인, 실패 시 환불) */
export async function modelViewViaFirebase(payload) {
  // payload: {gender?, angle, refImage?, userPhoto?} — userPhoto가 있으면 내 사진 기반 정면 뷰
  const fn = httpsCallable(functions, 'ikModelView');
  const { data } = await fn(payload);
  return data; // {image, charged}
}

/** 모델 프레임에 타투 적용 1프레임 (100코인, 실패 시 환불)
 *  payload: {mode?: 'part'|'refine'|'follow', photo, design?, part?, angle?, reference?, refAngle?} */
export async function modelApplyViaFirebase(payload) {
  const fn = httpsCallable(functions, 'ikModelApply');
  const { data } = await fn(payload);
  return data; // {image, charged}
}

/** 부가 기능 과금 게이트: sheet_export (무료 1회/일 → 300코인) / manual_apply (무료 3회/일 → 30코인) */
export async function chargeFeature(feature, extra = {}) {
  const fn = httpsCallable(functions, 'ikChargeFeature');
  const { data } = await fn({ feature, ...extra });
  return data; // {ok, charged, quota?}
}

/** 잔액 부족 에러 판별 */
export function isInsufficientBalance(err) {
  return String(err?.message || err).includes('INSUFFICIENT_BALANCE');
}

// ── 코인 충전 (기존 headjimweb 결제 함수 재사용, 메인 홈과 동일 상품) ──
export const COIN_PACKAGES = [
  { code: 'basic',    paypalId: 'api-coin-basic',    coins: 5000,   krw: 5000,  usd: '3.99',  label: 'Basic',    bonus: null },
  { code: 'standard', paypalId: 'api-coin-standard', coins: 32900,  krw: 29900, usd: '19.99', label: 'Standard', bonus: '+10%' },
  { code: 'premium',  paypalId: 'api-coin-premium',  coins: 118800, krw: 99000, usd: '69.99', label: 'Premium',  bonus: '+20%' },
];

export async function creditPayPalOrder(orderId) {
  const fn = httpsCallable(functions, 'creditPayPalOrder');
  const { data } = await fn({ orderId });
  return data;
}

export async function creditTossPayment({ paymentKey, orderId, amount }) {
  const fn = httpsCallable(functions, 'creditTossPayment');
  const { data } = await fn({ paymentKey, orderId, amount });
  return data;
}

export function makeTossOrderId(uid, productCode) {
  return `${uid}_${productCode}_${Date.now().toString(36)}`;
}
