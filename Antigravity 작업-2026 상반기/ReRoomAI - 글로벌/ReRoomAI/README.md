# ReRoom AI — AI 공간 인테리어 디자인 리디자인 서비스

**ReRoom AI**는 방 사진 한 장을 업로드하고 공간 유형과 인테리어 스타일을 골라 단 10초 만에 새로운 방 분위기로 바꿔주는 AI 인테리어 리디자인 웹 서비스입니다. 

기존 방의 건축학적 뼈대(벽, 창문, 문, 천장 및 카메라 시야 구도)는 완벽히 유지하면서 가구, 조명, 색감, 장식 등을 인테리어 테마에 맞춰 고화질 실사 합성 형태로 렌더링합니다.

---

## 주요 기능

1. **인테리어 인페인팅 리디자인:**
   - 거실, 침실, 주방, 욕실, 서재, 원룸 등 6가지 공간 유형을 선택할 수 있습니다.
   - 모던, 미니멀, 북유럽, 인더스트리얼, 재팬디, 미드센추리, 한옥, 호텔 라운지 등 8가지 인테리어 콘셉트를 제공합니다.
2. **이중 API 작동 모드:**
   - **데모 모드:** 서비스 제공자의 서버 환경변수 키(`process.env.GEMINI_API_KEY`)를 사용하여 기본 구동됩니다.
     - 브라우저 로컬 스토리지 기준 **무료 2회 제한**
     - 서버 인메모리 맵 기준 **IP당 하루 최대 10회 제한**
   - **BYOK 모드:** "내 API 키로 무제한 사용" 토글을 켜고 개인 API 키를 등록하여 무제한 이용할 수 있습니다. (사용자의 브라우저 로컬 스토리지에만 저장되며 서버 로그에는 일체 남지 않습니다.)
3. **비포 / 애프터 드래그 비교 슬라이더:**
   - 렌더링 완료 후 사용자가 마우스나 모바일 터치 드래그를 통해 원본 방 사진(Before)과 리디자인된 방 사진(After)을 한눈에 비교할 수 있는 실시간 비교 슬라이더를 장착했습니다.
   - 결과물 다운로드(PNG) 및 "다른 스타일로 다시 디자인하기"를 통해 원본 사진 업로드 없이 여러 인테리어 테마를 연속 실험할 수 있습니다.
4. **전처리 최적화:**
   - 업로드된 이미지는 클라이언트 브라우저 단에서 Canvas API를 이용해 최대 긴 쪽 1024px로 자동 다운스케일링되어 안전하게 전송됩니다 (업로드 제한 10MB, 서버 수신 제한 8MB).

---

## 로컬 실행 방법

### 1. 패키지 설치
```bash
npm install
```

### 2. 환경 변수 파일 생성
프로젝트 루트 디렉토리에 `.env.local` 파일을 생성한 뒤 발급받은 데모용 API 키를 입력합니다:
```env
GEMINI_API_KEY=발급받은_Gemini_API_Key_입력
```
*API 키가 없는 경우 [Google AI Studio](https://aistudio.google.com/apikey)에서 무료로 신속하게 발급받을 수 있습니다.*

### 3. 개발 서버 구동
```bash
npm run dev
```
브라우저에서 [http://localhost:3000](http://localhost:3000)으로 접속하여 즉시 테스트를 진행합니다.

---

## Vercel에 배포하기
이 프로젝트는 Next.js App Router 기반의 서버리스 단일 리포지토리로 바로 Vercel 배포가 가능합니다:
1. 코드를 GitHub 개인 저장소에 푸시합니다.
2. [Vercel](https://vercel.com) 대시보드에서 해당 저장소를 연동(Import)합니다.
3. 배포 설정 페이지의 **Environment Variables** 항목에 `GEMINI_API_KEY` 환경변수를 추가하고 본인의 API 키를 입력합니다.
4. **Deploy** 버튼을 클릭하면 약 1분 이내에 글로벌 라이브 서버로 배포 완료됩니다.

---

## 기술 스택
- **Core:** Next.js 16+ (App Router, Node runtime API)
- **Language:** TypeScript
- **Styling:** Tailwind CSS v4 (커스텀 디자인 토큰), Pretendard + Noto Serif KR (`next/font`)
- **AI SDK:** `@google/genai` (공식 SDK)
- **Model:** `gemini-3.1-flash-image-preview` (Nano Banana 2)

---

## 프로젝트 구조
```
app/
  layout.tsx          # 폰트·메타데이터·OG 설정
  page.tsx            # 섹션 조립 (서버 컴포넌트)
  globals.css         # 디자인 토큰 (@theme) · 그레인/리빌 스타일
  api/generate/       # Gemini 이미지 생성 라우트 (IP 레이트리밋 포함)
components/
  Header · Hero · StyleGallery · HowItWorks · Studio · Faq · Footer
  CompareSlider.tsx   # 접근성 지원 비포/애프터 슬라이더 (clip-path + 포인터 캡처)
  Reveal.tsx          # 스크롤 리빌 래퍼
lib/
  constants.ts        # 공간 유형·스타일 정의 (UI와 서버 프롬프트가 공유)
  useLocalStorage.ts  # SSR 안전 localStorage 상태 훅
```
