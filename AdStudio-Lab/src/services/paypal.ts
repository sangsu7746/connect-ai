// ── PayPal 결제 설정 ──────────────────────────────────────────
// 아래 값은 "사장님 소유" PayPal 비즈니스 계정에서 직접 발급/생성해야 하는 값입니다.
// 이 앱이 대신 만들어줄 수 없어요 — PayPal 개발자 대시보드(developer.paypal.com)에서 발급받은
// 실제 값으로 바꿔주세요.
//
// 1. PAYPAL_CLIENT_ID: developer.paypal.com > Apps & Credentials 에서 발급받는 공개 식별자입니다.
//    (Client Secret과 다릅니다 — Secret은 절대 프론트엔드에 넣으면 안 되지만, Client ID는
//    PayPal 공식 문서 기준으로 공개돼도 안전한 값이라 여기 프론트엔드 코드에 둡니다.)
// 2. PAYPAL_PLAN_IDS: PayPal 대시보드 > Products & Plans 에서 "일반"/"프로" 월간 구독 상품을
//    각각 만든 뒤 발급되는 Plan ID(P-로 시작)를 넣어주세요.
export const PAYPAL_CLIENT_ID = 'YOUR_PAYPAL_CLIENT_ID'
export const PAYPAL_PLAN_IDS = {
  basic: 'YOUR_BASIC_PLAN_ID', // 일반 $3.99/월 구독 Plan ID
  pro: 'YOUR_PRO_PLAN_ID',     // 프로 $9.99/월 구독 Plan ID
}

// PayPal JS SDK는 <script> 태그로 동적 로드한다 — 결제 화면(ProfilePage)에 진입한 사용자만
// 로드하도록 전역 index.html에는 넣지 않는다. 같은 세션에서 여러 번 불러도 한 번만 로드되게 캐싱.
let sdkPromise: Promise<void> | null = null

export function loadPayPalSdk(): Promise<void> {
  if (sdkPromise) return sdkPromise

  sdkPromise = new Promise((resolve, reject) => {
    if ((window as any).paypal) return resolve()

    const script = document.createElement('script')
    script.src = `https://www.paypal.com/sdk/js?client-id=${PAYPAL_CLIENT_ID}&vault=true&intent=subscription`
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('PayPal 결제 모듈을 불러오지 못했어요. 잠시 후 다시 시도해주세요.'))
    document.body.appendChild(script)
  })

  return sdkPromise
}

// window.paypal은 SDK 스크립트가 로드된 뒤에만 존재하는 전역 객체라 타입을 직접 선언해 쓴다
export function getPayPalSdk(): any {
  return (window as any).paypal
}
