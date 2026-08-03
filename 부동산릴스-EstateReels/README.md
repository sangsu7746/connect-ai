# 부동산릴스 (EstateReels)

부동산 블로그의 **글과 사진**을 넣으면, 소비자가 궁금해하는 **니즈에 맞춰 여러 컨셉**의
**이미지 모션영상(30초·1분·3분)**을 자동으로 만들어주는 웹앱.

AdStudio(`ad-studio-app.web.app`)의 검증된 엔진·디자인 시스템·지갑 구조를 재사용하고,
부동산 광고에 특화된 **소비자 니즈 컨셉 엔진**을 새로 얹었다.

## 흐름

```
[1] 홈 → [2] 블로그 가져오기(URL 자동 / 붙여넣기+사진) → [3] 매물정보 확인·편집
      → [4] 컨셉·길이 선택 → [5] 제작(브라우저 내 합성) → [6] 결과(미리보기·다운로드)
```

## 소비자 니즈 컨셉 (8종)

| 컨셉 | 소비자 니즈 | BGM |
|---|---|---|
| 🚇 역세권·입지 | "출퇴근·이동 편한가요?" | 차분·신뢰 |
| 🏫 학군·교육환경 | "아이 키우기 좋은가요?" | 포근·가족 |
| 💰 투자가치·미래 | "오를 만한가요?" | 차분·신뢰 |
| 🏠 내부·구조 | "집 상태 어떤가요?" | 감성·따뜻 |
| 🌳 생활환경·편의 | "살기 편한가요?" | 포근·가족 |
| 🏢 단지·브랜드 | "어떤 단지인가요?" | 차분·신뢰 |
| ⚡ 급매·가격강조 | "지금 사면 이득인가요?" | 활기·경쾌 |
| 🌅 감성·라이프스타일 | "여기서 어떻게 살까?" | 감성·따뜻 |

같은 매물이라도 컨셉을 바꾸면 오프닝·강조 포인트·문구 톤·음악이 달라져 타깃별로 다른 영상이 나온다.

## 기술 스택

| 영역 | 선택 |
|---|---|
| 프론트 | React 19 + TypeScript + Vite 8 (SPA) |
| 상태 | Zustand 5 |
| 라우팅 | react-router-dom 7 |
| 영상 합성 | @ffmpeg/ffmpeg (wasm, 단일스레드) — **브라우저에서 합성, 서버 비용 0** |
| 자막 렌더 | Canvas → 프레임 크기 투명 PNG 오버레이 (한글 완벽 지원) |
| 사진 | heic2any (아이폰 HEIC 지원) |
| 백엔드(선택) | Firebase(headjim-ai) — 로그인·공용 코인 지갑 **연동 준비**(휴면) |

## 핵심 설계

- **이미지 모션영상 = 로컬·무료**: 사진마다 Ken Burns(줌인) 클립을 만들고, 컨셉이 정한 자막 카드를
  얹고, BGM을 믹스해 하나의 MP4로 합친다. AI·서버·코인이 필요 없다 → **로그인 없이 완전 무료**.
- **하이브리드 구성**: 오프라인 파서가 블로그에서 가격·평형·교통·학군 등을 추출해 컨셉별 컷에 채운다.
  원하면 "AI로 다듬기"(Gemini BYOK)로 타이틀·셀링포인트를 매끄럽게 보정한다.
- **URL 자동 가져오기**: 로컬 도우미(있으면) → allorigins(HTML) → jina 리더 순으로 본문을,
  images.weserv.nl 프록시로 사진을 가져온다. 막히면 붙여넣기+업로드로 폴백.
- **연동 준비(휴면)**: `firebase.ts`(headjim-ai)·`walletService`(잔액 구독)·선택 로그인은 넣되,
  핵심 제작이 로컬이라 로그인/코인에 의존하지 않는다. 프리미엄 AI 컨셉을 붙일 때 활성화.

## 개발

```bash
npm install
npm run dev      # http://localhost:5180
npm run build    # tsc -b && vite build
```

## 배포 (연동 준비 — 아직 배포 안 함)

HEADJIM 공용 Firebase 프로젝트(headjim-ai)를 공유하되 **호스팅 사이트는 분리**(`firebase.json`의
`"site": "estate-reels"`). 최초 1회 사이트 생성 후 배포:

```bash
npx firebase-tools hosting:sites:create estate-reels
npm run build && npx firebase-tools deploy --only hosting   # → estate-reels.web.app
```

> ⚠️ App Check가 켜진 프로젝트라 로그인/지갑을 실제로 쓰려면 새 도메인을 reCAPTCHA 키에 등록해야 한다.
> 핵심 제작(로컬 합성)은 이와 무관하게 동작한다.
> ⚠️ Cloud Functions는 프로젝트 공용이므로, 함수 추가 시 이름에 `re` 접두사(전역 유일)를 붙이고
> **한 저장소에서만** 배포할 것.

## 폴더 구조

```
src/
  pages/       Home · Import · Review · Concept · Generate · Result · Profile
  utils/       estateConcepts(니즈 컨셉 엔진) · storyboard(씬 생성)
  services/    blogImport · estateParser · ffmpegService · captionCanvas · bgmService · aiEnhance · firebase · walletService
  stores/      estateStore(위저드) · userStore(선택 로그인)
public/bgm/    무드별 무료 음원 풀 (documentary_calm · emotional_daily · celebration · family_warm)
```
