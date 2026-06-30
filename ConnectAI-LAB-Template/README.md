# Connect AI LAB — 웹사이트 템플릿 사용 설명서

> 🧠 프리미엄 랜딩 페이지 + Firebase 인증 + PayPal/토스 결제 — 올인원 템플릿

---

## 📌 이 템플릿으로 무엇을 할 수 있나요?

이 템플릿은 **디지털 상품, SaaS, AI 서비스, 온라인 강의** 등을 판매하는 
웹사이트를 빠르게 만들 수 있도록 설계되었습니다.

| 기능 | 설명 |
|------|------|
| 🎬 **풀스크린 비디오 랜딩** | 영상 배경 + 스크롤 애니메이션으로 고급스러운 첫인상 |
| 🔐 **회원 인증 (Firebase)** | Google, Apple, 이메일 로그인/회원가입 |
| 💳 **해외 결제 (PayPal)** | 일회성 구매 + 구독 결제 — 전 세계 대응 |
| 🇰🇷 **국내 결제 (토스페이먼츠)** | 카드, 계좌이체, 가상계좌 — 한국 고객 대응 |
| 📊 **데이터베이스 (Firestore)** | 회원 정보, 주문 기록, 구독 상태 자동 저장 |
| ✨ **프리미엄 애니메이션** | Framer Motion 텍스트 스크램블, 3D 스크롤, 페이드인 |

### 활용 예시

- AI 서비스 랜딩 + 유료 플랜 결제
- 온라인 강의 판매 페이지
- 디지털 상품 (이북, 소프트웨어) 판매
- SaaS 제품 소개 + 구독 결제
- 포트폴리오 사이트 + 유료 컨설팅 예약

---

## 🚀 시작하기 (5분 안에 실행)

### Step 1. 파일 다운로드 후 설치

```bash
# 프로젝트 폴더에서 터미널 열기
npm install
```

### Step 2. 환경 변수 설정

```bash
# .env.example 파일을 복사
cp .env.example .env
```

`.env` 파일을 열고 자신의 정보를 입력:

```env
# Firebase (필수)
VITE_FIREBASE_API_KEY=여기에_입력
VITE_FIREBASE_PROJECT_ID=여기에_입력
...

# PayPal (해외결제 사용 시)
VITE_PAYPAL_CLIENT_ID=여기에_입력

# 토스페이먼츠 (국내결제 사용 시)
VITE_TOSS_CLIENT_KEY=여기에_입력
```

### Step 3. 개발 서버 실행

```bash
npm run dev
```

브라우저에서 `http://localhost:5173` 열기 — 끝! 🎉

---

## 🎨 커스터마이징 가이드

### ① 사이트 텍스트 변경

📄 파일: `src/config/content.ts`

이 파일 하나에 사이트의 **모든 텍스트**가 들어있습니다:

```typescript
export const SITE_CONFIG = {
  brandName: '내 브랜드 이름',        // 브랜드명
  copyright: '© 2026 내 회사명',      // 저작권
  
  hero: {
    titleLeft: ['첫줄', '둘째줄'],     // 히어로 왼쪽 타이틀
    titleRight: ['세째줄', '넷째줄'],   // 히어로 오른쪽 타이틀
    watermark: 'BRANDNAME',            // 배경 워터마크
    description: '설명문...',           // 소개글
  },
  
  metrics: {
    items: [
      { value: '99.9%', label: '정확도' },  // 성능 지표
      // ...
    ],
  },
  // ... 나머지도 같은 방식
};
```

### ② 배경 영상 변경

📄 파일: `src/config/videos.ts`

```typescript
export const VIDEO_URLS = {
  hero: '/my-video.mp4',        // public/ 폴더에 넣은 파일
  section2: 'https://...',      // 또는 외부 URL
  metrics: '',                   // 빈 문자열 = 검정 배경
  technology: '/tech-bg.mp4',
  footer: '/footer-bg.mp4',
};
```

**영상 넣는 방법:**
1. MP4 파일을 `public/` 폴더에 복사
2. `videos.ts`에서 `/파일명.mp4`으로 경로 지정

### ③ 로고 변경

📄 파일: `src/components/ConnectAILabLogo.tsx`

SVG 경로를 수정하거나, 이미지 로고로 교체

### ④ 색상/폰트 변경

📄 파일: `tailwind.config.js` + `src/index.css`

기본 설정은 검정 배경 + 흰색 텍스트 + Space Mono 폰트

---

## 🔥 Firebase 설정 방법

### 1단계: 프로젝트 생성

1. [Firebase Console](https://console.firebase.google.com/) 접속
2. **프로젝트 추가** 클릭 → 이름 입력 → 생성
3. **웹 앱 추가** (</> 아이콘) → 앱 이름 입력

### 2단계: 설정값 복사

프로젝트 설정에서 나오는 값을 `.env` 파일에 입력:

```env
VITE_FIREBASE_API_KEY=AIzaSyB...
VITE_FIREBASE_AUTH_DOMAIN=my-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=my-project
VITE_FIREBASE_STORAGE_BUCKET=my-project.firebasestorage.app
VITE_FIREBASE_MESSAGING_SENDER_ID=123456789
VITE_FIREBASE_APP_ID=1:123456789:web:abc123
```

### 3단계: 인증 활성화

Firebase Console → Authentication → Sign-in method에서 활성화:
- ✅ Google
- ✅ Apple (선택)
- ✅ 이메일/비밀번호 (선택)

### 코드에서 사용하기

```tsx
import { useAuth } from './contexts/AuthContext';

function MyPage() {
  const { user, signInWithGoogle, signOut } = useAuth();

  if (!user) {
    return <button onClick={signInWithGoogle}>Google 로그인</button>;
  }

  return (
    <div>
      <p>안녕하세요, {user.displayName}님!</p>
      <button onClick={signOut}>로그아웃</button>
    </div>
  );
}
```

---

## 💳 PayPal 결제 설정 (해외 결제)

### 1단계: PayPal 앱 생성

1. [PayPal Developer](https://developer.paypal.com/dashboard) 접속
2. **Apps & Credentials** → **Create App**
3. **Client ID** 복사 → `.env`에 입력

```env
VITE_PAYPAL_CLIENT_ID=AdUXefM8jcKwu20P...
```

### 2단계: 상품 정보 수정

📄 파일: `src/lib/paypal.ts`

```typescript
export const PRODUCTS: PayPalProduct[] = [
  {
    id: 'my-product',
    name: '내 상품',
    description: '상품 설명',
    price: '29.99',        // USD
    currency: 'USD',
  },
];
```

### 3단계: 결제 버튼 넣기

```tsx
import PayPalCheckoutButton from './components/payment/PayPalCheckoutButton';
import { PRODUCTS } from './lib/paypal';

function PricingSection() {
  return (
    <PayPalCheckoutButton
      product={PRODUCTS[0]}
      onSuccess={(details) => {
        alert(`결제 완료! Order ID: ${details.id}`);
        // Firestore에 주문 기록 저장 등
      }}
      onError={(err) => alert('결제 실패')}
    />
  );
}
```

### 테스트

- Sandbox 모드에서는 **PayPal 테스트 계정**으로 결제 테스트 가능
- Developer Dashboard → Sandbox → Accounts에서 테스트 계정 확인

---

## 🇰🇷 토스페이먼츠 설정 (국내 결제)

### 1단계: 상점 등록

1. [토스페이먼츠 개발자](https://developers.tosspayments.com) 가입
2. **내 개발정보** → **클라이언트 키** 복사

```env
VITE_TOSS_CLIENT_KEY=test_ck_D5GePWvyJnrK0W0k6q8gLzN97Eoq
```

> 💡 `test_ck_`로 시작하면 테스트 모드, `live_ck_`로 시작하면 실서비스

### 2단계: 상품 정보 수정

📄 파일: `src/lib/toss.ts`

```typescript
export const TOSS_PRODUCTS: TossProduct[] = [
  {
    id: 'my-product-kr',
    name: '내 상품 이름',     // 결제창에 표시
    price: 29900,             // 원 단위
    currency: 'KRW',
  },
];
```

### 3단계: 결제 버튼 넣기

```tsx
import TossCheckoutButton from './components/payment/TossCheckoutButton';
import { TOSS_PRODUCTS } from './lib/toss';

function PricingSection() {
  return (
    <TossCheckoutButton
      product={TOSS_PRODUCTS[0]}
      customerName="홍길동"
      customerEmail="user@example.com"
      onError={(err) => alert('결제 실패')}
    />
  );
}
```

### 결제 완료 처리

토스페이먼츠는 결제 성공 시 `successUrl`로 리다이렉트합니다.
서버에서 **결제 승인 API**를 호출해야 최종 완료됩니다.

> ⚠️ 실서비스에서는 반드시 백엔드 서버에서 결제 승인 처리를 해야 합니다.

---

## 📁 전체 파일 구조

```
프로젝트/
├── .env.example              ← 📋 환경변수 템플릿 (복사해서 .env로)
├── index.html                ← HTML 진입점
├── package.json              ← 의존성 목록
├── tailwind.config.js        ← Tailwind 설정
├── public/                   ← 📂 여기에 영상/이미지 넣기
│
└── src/
    ├── config/               ← ⭐ 설정 파일 (여기만 수정!)
    │   ├── videos.ts         ←   🎬 영상 URL
    │   └── content.ts        ←   ✏️ 모든 텍스트
    │
    ├── lib/                  ← 외부 서비스 연동
    │   ├── firebase.ts       ←   🔥 Firebase 초기화
    │   ├── firestore.ts      ←   📊 DB 모델 + CRUD
    │   ├── paypal.ts         ←   💳 PayPal 상품 정의
    │   └── toss.ts           ←   🇰🇷 토스 상품 정의
    │
    ├── contexts/
    │   └── AuthContext.tsx    ←   🔐 로그인 상태 관리
    │
    ├── components/
    │   ├── payment/          ←   💰 결제 버튼 컴포넌트
    │   │   ├── PayPalCheckoutButton.tsx
    │   │   └── TossCheckoutButton.tsx
    │   ├── Navbar.tsx
    │   ├── ConnectAILabLogo.tsx
    │   ├── ScrambleText.tsx
    │   └── SquashHamburger.tsx
    │
    ├── App.tsx               ← 메인 페이지 (5개 섹션)
    ├── main.tsx              ← 앱 진입점
    └── index.css             ← 글로벌 스타일
```

---

## 🌐 배포 방법

### Firebase Hosting (추천)

```bash
# Firebase 로그인
npx -y firebase-tools@latest login

# 호스팅 초기화
npx -y firebase-tools@latest init hosting
# → public 디렉토리: dist
# → SPA: Yes

# 빌드 후 배포
npm run build
npx -y firebase-tools@latest deploy --only hosting
```

### Vercel

```bash
npx -y vercel --prod
```

### Netlify

`dist/` 폴더를 Netlify에 드래그 앤 드롭

---

## ❓ FAQ

**Q: Firebase 없이도 사이트가 보이나요?**  
A: 네! 랜딩 페이지는 Firebase 없이도 정상 작동합니다. 로그인/결제 기능만 비활성됩니다.

**Q: PayPal과 토스 둘 다 꼭 써야 하나요?**  
A: 아닙니다. 필요한 것만 쓰세요. 안 쓰는 건 `.env`에 키를 안 넣으면 됩니다.

**Q: 영상은 어디서 구하나요?**  
A: [Pexels](https://pexels.com), [Pixabay](https://pixabay.com) 에서 무료 MP4를 다운받거나, 
직접 촬영한 영상을 `public/` 폴더에 넣으세요.

**Q: 모바일에서도 잘 보이나요?**  
A: 네, 반응형으로 제작되어 모바일/태블릿/데스크톱 모두 대응합니다.

---

## 🛠 기술 스택

| 기술 | 용도 |
|------|------|
| React 18 + TypeScript | UI 프레임워크 |
| Vite 5 | 빌드 도구 (초고속) |
| Tailwind CSS 3 | 스타일링 |
| Framer Motion 12 | 애니메이션 |
| Firebase Auth | 회원 인증 |
| Cloud Firestore | 데이터베이스 |
| @paypal/react-paypal-js | 해외 결제 |
| 토스페이먼츠 SDK | 국내 결제 |

---

**© 2026 AI CITY BUILDERS. All rights reserved.**
