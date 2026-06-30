// ============================================================
// PayPal Configuration — @paypal/react-paypal-js 기반
// ============================================================
// 
// 설정 방법:
// 1. https://developer.paypal.com/dashboard 에서 앱 생성
// 2. Client ID를 .env 파일에 넣기:
//    VITE_PAYPAL_CLIENT_ID=실제_클라이언트_ID
// 3. 프로덕션: VITE_PAYPAL_CLIENT_ID에 Live Client ID 사용
//
// ============================================================

export const PAYPAL_CONFIG = {
  clientId: import.meta.env.VITE_PAYPAL_CLIENT_ID || 'test',
  currency: 'USD',
  intent: 'capture' as const,
};

// ── 상품 타입 정의 ──

export interface PayPalProduct {
  id: string;
  name: string;
  description: string;
  price: string; // '29.99' 형식
  currency: string;
}

// ── 구독 플랜 타입 정의 ──

export interface PayPalSubscriptionPlan {
  id: string;
  name: string;
  description: string;
  planId: string; // PayPal에서 생성한 구독 Plan ID
  price: string;
  currency: string;
  interval: 'MONTH' | 'YEAR';
}

// ── 예시 상품 목록 — 여기를 수정하세요 ──

export const PRODUCTS: PayPalProduct[] = [
  {
    id: 'connect-ai-basic',
    name: 'Connect AI Basic',
    description: 'Neural interface basic access — single user license',
    price: '29.99',
    currency: 'USD',
  },
  {
    id: 'connect-ai-pro',
    name: 'Connect AI Pro',
    description: 'Full neural-AI interface access with real-time cognitive mapping',
    price: '99.99',
    currency: 'USD',
  },
];

// ── 예시 구독 플랜 — 여기를 수정하세요 ──

export const SUBSCRIPTION_PLANS: PayPalSubscriptionPlan[] = [
  {
    id: 'connect-ai-monthly',
    name: 'Connect AI Monthly',
    description: 'Monthly access to full neural-AI suite',
    planId: 'YOUR_PAYPAL_PLAN_ID', // PayPal에서 생성한 구독 플랜 ID
    price: '49.99',
    currency: 'USD',
    interval: 'MONTH',
  },
  {
    id: 'connect-ai-yearly',
    name: 'Connect AI Yearly',
    description: 'Annual access — save 20%',
    planId: 'YOUR_PAYPAL_YEARLY_PLAN_ID',
    price: '479.99',
    currency: 'USD',
    interval: 'YEAR',
  },
];
