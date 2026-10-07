# AdStudio-Lab — 워크플로우 개발용 사본

> `D:\광고영상-AdStudio` (운영본) 을 2026-08-04 에 복제한 **개발 전용 사본**이다.
> 워크플로우를 깊게 손보는 실험은 여기서 하고, 검증이 끝난 변경만 운영본에 옮긴다.
>
> dev 서버 포트는 5200 으로 분리돼 있어 운영본과 동시에 띄울 수 있다.

## 운영본과 다른 점 (되돌리지 말 것)

| 항목 | 운영본 | 이 사본 | 이유 |
|---|---|---|---|
| `firebase.json` → `hosting.site` | `ad-studio-app` | `adstudio-lab` | 존재하지 않는 사이트라 hosting 오배포가 "site not found" 로 실패한다 |
| `.firebaserc` | `default: headjim-ai` | `default` **없음**, `prod`/`demo` 별칭만 | 활성 프로젝트가 없으므로 `firebase deploy` 가 `--project` 없이는 아예 안 나간다 |
| `firebase.json` → `predeploy` | 없음 | 3곳 모두 `deploy-guard.cjs` | `headjim-ai` 로 나가는 배포를 물리적으로 차단 (fail-closed) |
| Firebase 접속 설정 | 소스 4곳에 하드코딩 | `src/services/firebaseTarget.ts` 한 곳 | 랩을 다른 프로젝트·에뮬레이터로 돌릴 수 있게 |

### ⚠️ functions 오배포가 가장 위험하다

이 저장소는 `firebase.json` 에 `codebase` 를 지정하지 않아 `headjim-ai` 의 공용
**`default` 코드베이스를 점유**한다. 여기서 `firebase deploy --only functions` 가
나가면 라이브 5개 함수(`onUserCreate`·`corsProxy`·`edgeTTS`·`analyzeProduct`·`generateAd`)가
즉시 덮어써지고, 빈 `GEMINI_API_KEY` 반영·웰컴 코인 값 변경·오마주/MemoryFilm
프론트의 401 을 동시에 일으킨다. `scripts/deploy-guard.cjs` 가 이걸 막는다.

**운영 배포는 `D:\광고영상-AdStudio` 에서만 한다.**

## 로컬 격리 개발 (권장)

```
npm run dev:emu    # Auth(9099)·Firestore(8080)·Functions(5001)·UI(4000) 에뮬레이터
npm run dev        # 별도 터미널, 5200
```

`.env.example` 을 `.env.local` 로 복사하고 `VITE_USE_EMULATORS=true` 를 켜야
로그인·지갑·프로젝트 문서가 운영 Firestore 로 새지 않는다. 끄면 기존과 동일하게
운영 `headjim-ai` 에 붙는다(기본값).

### 에뮬레이터로 덮을 수 없는 것

- **Gemini·edgeTTS·영상 어댑터** — 에뮬레이터 안에서도 실제 외부 API 를 그대로 호출한다(과금 발생).
- **지갑·결제 콜러블 5종** (`spendCoins`·`refundSpentCoins`·`bankTransferCreate`·`creditTossPayment`·`creditPayPalOrder`) — 이 저장소에 소스가 없다. `headjim-ai` 의 `headjimweb` 코드베이스 소속이라 에뮬레이터가 서빙하지 못한다.
- **`/t/**` → `adClick` rewrite** — 이 함수도 이 저장소에 없다. 랩 전용 프로젝트에 hosting 을 배포하면 이 경로만 동작하지 않는다.

---

# AdStudio — 제품 자료로 만드는 AI 광고 영상

제품·기업 사이트(URL)나 제품 설명서를 첨부하면 AI가 분석해 광고 컨셉을 만들고,
**가상 배우(LTX) 또는 내 사진 속 모델(무빙포토)**로 광고 영상을 제작하는 웹앱.
오마주 영상앱(MemoryFrame)의 파이프라인을 이어받아 광고 제작 용도로 재편한 프로젝트다.

## 공통 엔진

```
자료 업로드 (텍스트 / URL / 파일)
  → Gemini 분석 (서버에서 호출 — analyzeProduct)
  → 광고 컨셉 (나레이션 편집 + 길이·음악·음성 설정)
  → 배우 설정 (AI 가상 배우 100코인 | 사진 배우 50코인)
  → 광고 출력 (생성 → 미리보기 → 다운로드)
```

화면 흐름: `A1_Home → A2_Source → A3_Concept → A4_Actor → A5_Progress → A6_Result`

## 과금 모델 — "무료 영구 + 코인" (오마주 기본 구성)

- **웰컴 코인**: 가입 시 3,000코인 (functions/onUserCreate, 멱등 지급)
- **AI 배우 광고**: 100코인 (LTX — GPU 비용)
- **사진 배우 광고**: 50코인 (extraction 로컬 CV + 합성)
- 코인은 HEADJIM 공용 지갑(`wallets/{uid}`) 공유 — 원장 app 필드는 `adstudio`

## 오마주에서 이어받은 것 / 삭제한 것

| 이어받음 (연계) | 삭제됨 |
|---|---|
| AppShell·코인 잔액 칩·충전 모달(Toss/PayPal) | 오마주 기념영상 마법사(S1~S6) |
| 지갑·일일 무료 한도(walletService, dailyUsage) | GuidePage(오마주 안내) |
| extraction (얼굴감지·배경제거·무빙포토) | — |
| aiAdapters의 Kaggle(LTX) 어댑터, corsProxy | — |
| edgeTTS 무료 나레이션, bgmService, ffmpegService | — |

## 개발

```bash
npm install    # (이 복사본에는 node_modules 포함돼 있어 생략 가능)
npm run dev    # 개발 서버
npm run build  # tsc + vite build
```

## 배포 (⚠️ 반드시 읽을 것)

오마주앱과 **같은 Firebase 프로젝트(headjim-ai)**를 공유한다(공용 지갑·계정 때문에 의도된 설계).
호스팅은 별도 사이트로 분리 — `firebase.json`에 `"site": "adstudio"`를 넣어뒀으므로
그냥 배포해도 기존 오마주앱(headjim-ai.web.app)을 덮어쓰지 않는다.

최초 1회, 사이트를 만들어야 배포가 된다:

```bash
npx firebase-tools hosting:sites:create adstudio
npm run build && npx firebase-tools deploy --only hosting   # → adstudio.web.app
```

**⚠️ Functions는 프로젝트 공용이므로 여기서 배포하면 오마주앱 것을 덮어쓴다.**
이 저장소 functions/index.js에 추가된 `analyzeProduct`·`generateAd`는
배포 전에 오마주 원본 저장소(D:\오마주 동영상-260706) functions와 병합한 뒤
**한 곳에서만 배포할 것.** 서버 환경변수 `GEMINI_API_KEY` 설정 필요.

## 남은 연동 작업 (TODO)

1. **렌더 워커**: `adJobs/{jobId}` 큐 문서를 읽어 실제 영상 생성
   - AI 배우: `services/aiAdapters.ts`의 Kaggle(LTX) 어댑터 재사용
   - 사진 배우: `src/extraction/` 파이프라인 + `sceneRenderer`/`ffmpegService`
2. **A5_Progress**: adJobs onSnapshot 구독으로 실제 진행률 표시 (현재 데모 진행바)
3. **나레이션 합성**: `voiceService`(edgeTTS) → 영상에 오디오 트랙 합성
4. PDF·이미지 자료 분석 (현재 텍스트/URL만)

## 참고 문서

- [ARCHITECTURE.md](ARCHITECTURE.md) — 스택·지갑·보안 규칙·재사용 패턴 (오마주 기준, 구조 동일)
