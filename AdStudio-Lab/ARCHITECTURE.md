# MemoryFrame (오마주 영상앱) — 재사용 설계도

> 목적: 다음 웹앱을 만들 때 이 앱의 구성(스택·수익화·지갑·배포)을 그대로 복제하기 위한 참조 문서.
> 마지막 갱신: 2026-07-19 ("무료 영구 + 코인" 모델 개편 직후)

---

## 1. 기술 스택

| 영역 | 선택 | 비고 |
|---|---|---|
| 프론트엔드 | React 19 + TypeScript + Vite 8 | SPA, `tsc -b && vite build` |
| 상태 관리 | Zustand 5 | 스토어 3개(user/project/keys), Redux 불필요 |
| 라우팅 | react-router-dom 7 | |
| UI | 인라인 스타일 + CSS 변수 + clsx | 별도 UI 프레임워크 없음 |
| 애니메이션 | framer-motion | |
| 아이콘 | lucide-react | |
| 다국어 | i18next + react-i18next | 10개 언어 리소스 (⚠️ UI 하드코딩 한국어 잔존) |
| 미디어 처리 | @ffmpeg/ffmpeg (wasm) | 브라우저에서 영상 합성 — 서버 비용 0 |
| 비전 AI | @mediapipe/tasks-vision | 얼굴/자세 감지, 브라우저 로컬 |
| 린트 | oxlint | eslint보다 빠름 |
| 백엔드 | Firebase (Auth·Firestore·Hosting·Functions) | 프로젝트: `headjim-ai` (HEADJIM 앱들이 공유) |
| 지갑 서버 | Cloudflare Workers (무료 플랜) | `D:\headjim-platform\wallet-worker` — 별도 배포 |

## 2. 폴더 구조

```
src/
  pages/        # 위저드 화면 흐름: S1_Home → S2_Upload → S3_Concept
                #   → S4_Storyboard → S5_Progress → S6_Result
                # + ProfilePage(계정·코인), KeysPage(BYOK 키 관리)
  stores/       # zustand: userStore(인증·티어), projectStore(제작 상태·인가 기록),
                #   keysStore(BYOK 키 메타 + KeyVault)
  services/     # firebase, walletService(지갑), dailyUsage(일일 무료 한도),
                #   ffmpegService(합성·워터마크), sceneRenderer(레인별 렌더 파이프라인),
                #   aiAdapters(제공자별 API), voiceService(TTS), localizationService,
                #   projectService(Firestore CRUD), paypal(구독 — 현재 휴면)
  extraction/   # 브라우저 로컬 CV 파이프라인 (얼굴 감지·세그먼트·매팅) — 서버 비용 0
  i18n/         # 언어 리소스
  utils/        # storyboardGenerator, personResolver, qualityGates
functions/      # Cloud Functions: onUserCreate(웰컴 코인), corsProxy, edgeTTS
firestore.rules # 보안 규칙 (아래 §5)
```

## 3. 수익화 모델 — "무료 영구 + 코인" (핵심 재사용 패턴)

**원칙: 무료는 기간제(트라이얼)가 아니라 영구 무료 레인. 코인은 무료의 반대말이 아니라 "더 좋은 것의 연료".**

| 등급 | 정의 | 권한 |
|---|---|---|
| `guest` | 비로그인 | 둘러보기만 — 생성 불가(사용량·지갑이 계정 기준) |
| `free` | 로그인 | 일일 무료 한도 + 코인 결제, 편집 기능 전면 개방 |
| `pro` | 무과금 특권(개발자 이메일 오버라이드) | 차감 없음 |

- **무료 레인**: 한계비용 ~0원인 기능(로컬 처리)만 무료로. 무빙포토 일 5개, 워터마크+720p 마감.
- **코인 결제분**: 워터마크 없음 + 원본 화질 → 무료/유료 차별선이 "품질 마감".
- **웰컴 코인 3,000** (1,500코인=$1): 트라이얼 대신 온보딩. 소진 시점 = 자연스러운 결제 순간.
- **구독은 숨김**: 멘탈 모델을 "무료+코인" 하나로. 재도입 시 "월간 코인 번들"로 정의할 것.

### 제작 인가 단일 경로 (walletService.ensureRenderAuthorization)
모든 유료성 액션은 이 함수 하나를 통과한다:
1. guest → `LoginRequiredError`
2. pro → 통과(무과금)
3. 이미 인가 있음(재시도) → 그대로 반환 (이중 차감 방지)
4. 무료 슬롯 시도(해당 레인만) → 성공 시 `{refId, cost: 0}`
5. 코인 차감(멱등 refId) → `{refId, cost: N}`, 잔액 부족 시 `InsufficientPointsError`

전체 실패 시 `releaseRenderAuthorization` — cost>0은 서버 환급, cost 0은 일일 카운트 복원.
**cost === 0 ⇒ 무료 마감(워터마크), cost > 0 또는 pro ⇒ 프리미엄 마감** — 이 규칙 하나로 통일.

## 4. 공용 코인 지갑 (HEADJIM 전 앱 공유 — 그대로 복제 가능)

위치: `D:\headjim-platform\wallet-worker` (Cloudflare Worker, `wrangler deploy`)

```
데이터 모델 (Firestore, 프로젝트 headjim-ai):
  wallets/{uid}                : { balance: int, updatedAt }
  wallets/{uid}/ledger/{refId} : { delta: int, app, reason, createdAt }
  config/pricing               : 단가표 (없으면 Worker의 DEFAULT_PRICING)

API:
  GET  /wallet/balance            (Firebase ID 토큰)
  POST /wallet/spend              { cost, app, reason, refId } — refId 멱등
  POST /wallet/refund             { refId } — 금액은 서버가 원장에서 읽음(조작 불가)
  POST /admin/grant               X-Admin-Key — 수동 지급
  POST /payments/paypal/credit    { orderId } — PayPal 주문을 서버가 직접 조회·검증 후 적립
  GET  /config/pricing
```

설계 불변식 (완화 금지):
- 지갑 쓰기는 **오직 서버**(Worker 서비스 계정 + Cloud Functions Admin SDK)만. 클라이언트는 읽기만.
- 모든 차감/환급/지급은 **refId 멱등** — 재시도로 이중 처리되지 않음.
- 차감(원장 생성)과 잔액 갱신은 **단일 commit**(원자성) + 낙관적 동시성(updateTime precondition).
- 새 앱 추가 시: `app` 필드에 앱 이름 넣고 spend 호출 + Worker `ALLOWED_ORIGINS`에 도메인 추가만 하면 끝.

### 웰컴 코인 (functions/onUserCreate)
Auth 계정 생성 트리거에서 Admin SDK로 `wallets/{uid}` + `ledger/welcome-{uid}` 트랜잭션 지급.
ledger 문서 존재 여부로 멱등 — 트리거 재시도에도 이중 지급 없음. (같은 Firebase 프로젝트라서 가능;
다른 프로젝트면 Worker `/admin/grant`를 호출할 것.)

## 5. Firestore 보안 규칙 패턴

```
users/{uid}            본인 읽기/쓰기
projects/{id}(+photos) userId 필드 = 본인일 때만
entitlements/{uid}     본인 읽기만, 쓰기 금지 (서버 전용)
wallets/{uid}(+ledger) 본인 읽기만, 쓰기 금지 (지갑 Worker·Admin SDK 전용) ← 절대 완화 금지
config/*               공개 읽기, 쓰기 금지 (단가표 등)
usage/{uid}/tts/*      본인 읽기만 (서버 비용 발생 → 서버 집계)
usage/{uid}/**         본인 읽기/쓰기 (앱 비용 0인 무료 한도 → 클라이언트 집계 허용)
```

**신뢰 모델**: 앱 비용이 발생하는 것(TTS, 코인)은 서버가 강제, 앱 비용이 0인 것(무료 한도)은
클라이언트 집계 허용 — 조작해도 본인 한도만 늘 뿐 손해 없음. 이 구분이 서버리스 비용을 지킨다.

## 6. 재사용 가치가 높은 컴포넌트/패턴

- **일일 무료 한도** `services/dailyUsage.ts` — `usage/{uid}/{bucket}/{yyyy-mm-dd}` 문서,
  `checkAndIncrementDaily` / `decrementDaily`(실패 시 복원). UTC 자정 리셋.
- **BYOK KeyVault** `stores/keysStore.ts` — API 키를 IndexedDB + WebCrypto(AES-GCM)로 기기에만 저장,
  계정에는 "등록했었다" 플래그만. 서버 전송 없음.
- **corsProxy** `functions/index.js` — CORS 막힌 외부 API를 Functions로 중계, 제공자별 인증 헤더 매핑.
- **무료 TTS** `functions/edgeTTS` — edge-tts-universal(키 불필요) + 월간 한도 서버 집계.
- **워터마크** `services/ffmpegService.ts` — ffmpeg.wasm은 drawtext 폰트가 없으므로
  **Canvas로 텍스트 PNG를 그려 overlay 필터로 합성**. + `scale='min(720,iw)':-2` 다운스케일.
  병합은 단계적 폴백(자막+음성+BGM → … → 무음 영상만)으로 최대한 결과물을 살린다.
- **코인 잔액 칩** `AppShell.tsx` — `onSnapshot(wallets/{uid})` 실시간 구독, 클릭 시 충전 페이지.
- **에러 종류별 배너** S5 — InsufficientPoints/QuotaExhausted/LoginRequired/DailyLimit 각각
  전용 배너 + 원인에 맞는 CTA(충전/키설정/로그인) — 전환율에 직결되는 패턴.

## 7. 배포 절차

```bash
# 프론트엔드
npm run build && npx firebase-tools deploy --only hosting     # → headjim-ai.web.app

# Cloud Functions
npx firebase-tools deploy --only functions                    # 서버에만 남은 함수 있으면 --force

# 지갑 Worker (별도, headjim-platform/wallet-worker에서)
npx wrangler deploy
```

## 8. 알려진 주의사항 / 새 앱에서 피할 것

1. **웹훅에는 반드시 서명 검증** — 서명 검증 없는 PayPal 웹훅은 아무나 POST로 권한 탈취 가능
   (이 앱에서 실제로 발견·제거함). 결제 검증은 Worker처럼 "서버가 PG에 직접 조회" 방식이 안전.
2. **Node.js 20 런타임 2026-10-30 지원 종료** — 새 Functions는 22로 시작할 것.
3. **i18n은 처음부터** — 리소스만 만들고 UI에 한국어를 하드코딩하면 글로벌 출시 때 전면 재작업.
4. **키 차감 전에 사전 조건 검사** — 코인 차감 → 키 없음 실패 순서가 되면 환급 절차가 필요해짐.
   반드시 "필수 조건 검사 → 차감" 순서로.
5. **클라이언트 플랜 게이트는 보안 경계가 아님** — 진짜 돈이 걸린 것은 지갑 Worker/Functions가 강제.
6. **BYOK는 프로슈머용** — 글로벌 일반 소비자는 API 키를 발급받지 않는다. 소비자 제품은
   앱 공급 키 + 코인에 실비를 녹이는 구조가 정석 (이 앱의 향후 전환 과제).
