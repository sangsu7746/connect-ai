# 유튜브 오마주 모드 — 인수인계

구현 완료일: 2026-08-05 · 브랜치 `feat/adstudio-youtube-homage`
설계: [2026-08-04-youtube-homage-design.md](./2026-08-04-youtube-homage-design.md)
계획: [../plans/2026-08-04-youtube-homage.md](../plans/2026-08-04-youtube-homage.md)

## 상태

12개 태스크 구현 완료, 테스트 115개 통과, `tsc`/`build`/`lint` 클린.
**아직 배포하지 않았고, 실제 API 키로 검증되지 않았다.**

## 1. 실호출 검증이 남았다 (키가 필요하다)

키·JDK 부재로 8항목이 미검증이다. **위험도 순서대로** 정리한다.

### 1순위 — Gemini `fileData.fileUri` 페이로드 형태 ⚠️ 가장 위험

`src/services/homageAnalyzer.ts` 가 Gemini 에 유튜브 URL 을 넘기는 형태다.
문서에서 두 가지 형태가 보여 하나를 골랐고 **실호출로 확인하지 못했다.**
틀렸다면 레퍼런스 입구 3개 중 2개(검색·URL)가 통째로 동작하지 않는다. 폴백도 없다.

**UI 를 거치지 말고 먼저 격리 검증할 것:**

1. `/keys` 에서 Gemini 키 등록
2. 브라우저 콘솔에서:
   ```js
   const m = await import('/src/services/homageAnalyzer.ts')
   await m.analyzeFromVideo('<짧은 공개 광고 videoId>')
   ```
3. `{scenes:[...], pacing, overallArc}` 가 나오면 성공. 실패하면 응답 본문의 오류 메시지를 보고 페이로드 형태를 조정한다.

### 2순위 — Gemini 스키마 준수율

1회 재시도로 충분한지가 여기서 갈린다. 1순위와 같은 세션에서 실제 광고 5~10편을 분석해
`sanitizeHomageStructure` 출력을 확인한다.

### 3순위 — A6 스토리보드까지 도달해 실제 씬 확인

최종 리뷰가 잡은 C1(제품 컷에 인물이 강제되던 문제)의 회귀 확인 지점이다.
제품 컷에 사람이 안 들어가고 포즈 경고가 안 뜨면 정상이다.

### 4순위 — 저작권 가드레일 실검증

슬로건이 뚜렷한 한국 광고를 분석한 뒤 `emotionBeat`·`overallArc` 에 원본 슬로건이
들어갔는지 확인한다. 2순위 직후에 하면 추가 비용이 없다.

### 5순위 — `youtubeSearch` 실호출 (아래 2번 배포가 선행)

### 6~8순위 (낮음)

Firestore 에뮬레이터 캐시 / 전체 E2E / `/concept` 요약 카드.

## 2. 배포 순서 — 이 순서를 지켜야 한다

`youtubeSearch` 함수는 **이 저장소에서 배포할 수 없다**(`scripts/deploy-guard.cjs` 가 차단).
프론트가 먼저 나가면 검색 탭이 404 로 조용히 죽는다.

1. Google Cloud Console 에서 **YouTube Data API v3** 활성화 후 API 키 발급
2. `AdStudio-Lab/functions/index.js` 의 `youtubeSearch` 를 운영 저장소
   `D:\광고영상-AdStudio\functions\index.js` 로 이식
3. 운영 저장소 `functions/.env` 에 `YOUTUBE_API_KEY=...`
4. 운영 저장소에서 **함수 하나만** 배포:
   ```
   firebase deploy --only functions:youtubeSearch
   ```
   ⚠️ `--only functions` (전체)는 절대 쓰지 마라 — default 코드베이스의 라이브 5개 함수를 덮어쓴다.
5. **Firebase 콘솔에서 `youtubeSearchCache` 컬렉션에 `expireAt` TTL 정책 설정**
   → 이게 없으면 유튜브 약관의 "캐시 30일 내 삭제"가 전혀 이행되지 않는다. 코드는 필드만 남긴다.
6. 그 다음에 프론트 배포

## 3. 남은 Minor (병합 차단 아님)

| 항목 | 내용 |
|---|---|
| `homageVideoId` 잔존 | 오마주→템플릿으로 되돌려 저장하면 Firestore 의 기존 `homageVideoId` 가 안 지워진다(`projectService` 가 undefined 키를 제거한 뒤 `merge:true` 로 쓰기 때문). 실제 정리하려면 `deleteField()` 필요 |
| 2인·그룹 모델 미사용 | 오마주 모드는 `person` 컷에 항상 `['person_1']` 만 넣는다. 사진 2장을 올려도 person_2 가 어떤 씬에서도 안 쓰인다 |
| `emotionBeat` 과잉 폐기 | 문장부호 가드가 `"설렘, 기대감."` 같은 정상 구절도 버린다. `HOMAGE_JSON_SCHEMA_HINT` 에 "no punctuation, phrase only" 를 넣어 애초에 안 뱉게 하는 게 비용 0의 보완책 |
| 검색어 단위 누락 | `CAPACITY_QUANTITY_TOKEN_RE` 에 `mg`·`oz`·`ea`·`캡슐` 이 빠져 `"비타민C 1000mg"` 은 여전히 `"1000mg"` 을 집는다 |
| `youtubeSearch` 레이트리밋 없음 | `q` 길이 상한도 uid별 제한도 없어, 로그인한 사용자 한 명이 공용 일일 100검색을 소진 가능 |

## 4. 구현 중 잡힌 결함 (참고)

계획 자체의 결함 12건이 리뷰에서 잡혔다. 특히 실사용 영향이 컸던 것:

- **API 키 로그 유출** — `node-fetch@3` 의 `FetchError.message` 에 요청 URL(=키)이 포함된다
- **오마주 폴백이 로맨틱 대사** — Gemini 실패 시 "기억해줘, 우리의 시간."이 최종 결과로 확정됐다
- **`subjectRefs` 계약 단절** — 제품 컷에 인물이 강제되고 유료 이미지가 씬마다 재생성됐다
- **StrictMode 취소 플래그** — 개발 모드에서 레퍼런스 화면 전체가 먹통이 됐다
