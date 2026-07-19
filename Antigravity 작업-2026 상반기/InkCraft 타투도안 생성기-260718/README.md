# 🖋️ InkCraft — AI 타투 도안 생성기

스타일(올드스쿨/파인라인/미니멀/기하학/트라이벌/이레즈미) + 소재를 입력하면
스텐실용 흑백 타투 도안이 여러 장 생성되는 웹앱.
"tattoo design" 글로벌 검색 수요 타깃 — 경쟁 앱들의 구독 강요 대신 **무료 미끼 + 건당 코인**.
흑백 도안이라 FLUX schnell 품질로 충분. ColorCraft Kids(headjim-color)를 모체로 제작 —
HEADJIM 공용 지갑·회원·결제 시스템을 공유한다.

## 구조

```
InkCraft 타투도안 생성기-260718/
├── web/         Vite + React (다크 타투 스튜디오 테마) — Firebase/로컬 모드 자동 전환
├── server/      로컬 개발 프록시 (포트 8789) — FLUX 생성 + 한국어 번역, 과금 없음
├── functions/   프로덕션 (codebase inkcraft) — ikGenerateDesign / ikChargeFeature
└── start.bat    로컬 원클릭 실행 (프록시 + 웹앱, http://localhost:5175)
```

## 핵심 기능

- **잉크 대구분**: ⬛ Black & Grey / 🎨 Color — 스타일마다 컬러 전용 프롬프트
  (올드스쿨=적·황·녹 원색, 이레즈미=전통 일본 채색, 파인라인=수채 워시 등)
- **스타일 6종**: ⚓ Old School / 🪶 Fine Line / ◦ Minimal / ◇ Geometric / 🌀 Tribal / 🐉 Irezumi
  — 스타일별 전용 프롬프트 (순백 배경·피부 없음·글자 없음 공통 원칙)
- **변형 배치 생성**: 한 소재로 1·2·4장 연속 생성 후 나란히 비교 (진행 표시)
- **한국어 자동 번역**: 한글 소재 → Llama 3.1 영역 후 생성
- **✨ 프리미엄**: Gemini 2.5 Flash Image (선 품질·구도 향상, 한국어 원어 이해)
- **도안 보관함**: 생성한 도안 체크 선택 → 미리보기·개별 PNG 다운로드
- **🧴 타투 시착**: 부위 선택(💪팔/🦵다리/🫸상체/🧍온몸) + 내 사진 업로드 →
  수동 배치(클릭 위치·크기·잉크 블렌딩) 또는 ✨AI 적용(Gemini가 피부 굴곡·조명에 맞춰 합성)
- **📷 내 전신사진 모델**: 전신사진을 업로드하면 같은 얼굴·헤어·체형의 모델로 변환해
  8방향 생성 (사진은 정면 뷰 생성에만 사용, 저장 안 함 — 본인/동의 사진만 업로드 안내)
- **🧍 AI 가상 모델 360°**: 속옷(스포츠웨어) 차림의 실사 모델을 8방향 생성 → 드래그 회전 →
  부위(왼팔/오른팔/가슴/등/왼다리/오른다리) 선택 → 전 각도 타투 적용 → Before/After 슬라이더 비교.
  모델 프레임은 앱이 보관해 도안을 바꿔도 재생성 비용 없음
- **🎯 수동 배치 (모델)**: 도안의 흰 배경을 클라이언트에서 자동 제거(무료) → 원하는 각도 프레임에
  클릭 위치·크기 슬라이더로 직접 배치 (무료 3회/일 → 30코인, 내 사진 수동 시착과 같은 게이트)
- **✨ 배치 기준 AI 360°**: 수동 배치를 기준점 삼아 기준 각도는 refine(그 자리·그 크기로 실제 타투화),
  나머지 7각도는 follow(같은 위치·크기로 전파) — 완료 후 자동으로 Before/After 비교 모드 진입 (800코인)
- **⬇️ PNG (no bg)**: 배경 투명 도안 PNG 다운로드 (클라이언트 연산, 무료)
- **📄 플래시 시트**: 선택 도안들을 A4 세로 PDF로 조립 — 빈티지 이중 잉크 테두리 표지
  (한글 제목 지원, 캔버스 렌더링) + 페이지 번호. 클라이언트(jsPDF) 생성이라 서버 비용 0원
- 회원(Google + 이메일 인증) / 앱 내 충전(토스·PayPal) — ColorCraft와 동일 모듈

## 수익화 (1코인=₩1, HEADJIM 공용 지갑)

| 기능 | 과금 |
|---|---|
| 기본 도안 생성 | 무료 3장/일 → 10코인 |
| ✨ 프리미엄 도안 | 150코인 |
| 🧴 수동 시착 | 무료 3회/일 → 30코인 |
| ✨ AI 시착 (Gemini) | 150코인 (실패 시 환불) |
| 🧍 가상 모델 생성 (8방향) | 프레임당 100코인 = 800코인 |
| 🖋️ 모델 타투 360° 적용 | 프레임당 100코인 = 800코인 |
| 📄 플래시 시트 내보내기 | 무료 1시트/일 → 300코인 |

- 차감/환불: `walletTransactions` 원장(refId 멱등), 실패 시 자동 환불 — WALLET_API.md 규약
- 충전 패키지·웰컴 코인: 메인 홈과 동일 (headjimweb 함수 재사용)

## 로컬 실행

`server/.env`(CF·Gemini 키)와 `web/.env`(Firebase·결제 키)는 ColorCraft에서 복사됨.
`start.bat` 더블클릭 → http://localhost:5175
(로컬 모드로 쓰려면 `web/.env`를 잠시 다른 이름으로 변경 — 과금 없이 IP 한도만)

## 배포 (headjim-ai 프로젝트 합류 — ⚠️ 대상 지정 필수)

```powershell
# 최초 1회: Firebase 콘솔 또는 CLI로 호스팅 사이트 생성
firebase hosting:sites:create headjim-ink --project headjim-ai
firebase target:apply hosting inkcraft headjim-ink

firebase deploy --only functions:inkcraft   # ik* 함수만 — colorcraft/printcraft/지갑 함수 보호
cd web; npm run build; cd ..
firebase deploy --only hosting:inkcraft     # headjim-ink 사이트만
```

- 시크릿(CF_API_TOKEN/CF_ACCOUNT_ID/GEMINI_API_KEY)은 프로젝트에 이미 등록됨 (PrintCraft와 공유)
- Auth 승인된 도메인에 `headjim-ink.web.app` 추가 필요 (로그인 조건)

## 로드맵

- [ ] 배포 + 도메인 (예: ink.headjim.com)
- [ ] 부위 미리보기 (팔뚝/손목/등 목업 위에 도안 합성)
- [ ] 스타일 추가 (치카노 레터링, 네오트래디셔널, 블래스트오버)
- [ ] 도안 시드 고정 + 미세 수정 (같은 구도로 디테일만 변경)
- [ ] SEO 랜딩 (스타일별 갤러리 페이지 — "snake tattoo design" 등 롱테일)
