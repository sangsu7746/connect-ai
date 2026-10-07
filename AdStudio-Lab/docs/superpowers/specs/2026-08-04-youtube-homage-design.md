# 유튜브 레퍼런스 오마주 모드 — 설계

작성일: 2026-08-04
대상: `D:\AdStudio-Lab`
상태: 승인됨 (구현 계획 대기)

## 1. 배경과 목적

현재 AdStudio는 자료를 분석한 뒤 **앱이 미리 정해둔 8종 템플릿**(`AD_STRUCTURES` → `AD_CONCEPT_TEMPLATES`)
중 하나를 골라 고정 6씬 스토리보드를 만든다. 어떤 제품을 넣어도 씬 구성의 골격이 같다는 뜻이다.
이것이 기존 기업·제품 광고 앱과 차별화되지 않는 지점이다.

이 설계는 **레퍼런스 기반 오마주 모드**를 추가한다. 사용자가 참고하고 싶은 광고의 리듬과
샷 문법을 가져와 씬 구성의 골격으로 삼는다. 기존 템플릿 모드는 그대로 남고, 새 모드가 나란히 추가된다.

### 벗어나려는 것을 정확히 하기

벗어나려는 대상은 **"앱이 정해준 고정 템플릿"**이지 "유튜브가 아닌 것"이 아니다.
이 구분이 §4의 세 번째 입구(글로 설명하기)를 정당화한다 — 유튜브에 없는 느낌을
사용자가 서술해도 그것 역시 템플릿 탈출이다.

## 2. 결정 사항 요약

| 항목 | 결정 | 근거 |
|---|---|---|
| 오마주가 덮어쓰는 범위 | **구성(`structureId`)만**. 대분류·강조점·톤·비주얼스타일은 사용자 선택 유지 | 광고는 결국 내 제품의 강조점을 팔아야 한다. 레퍼런스에 끌려가면 안 된다 |
| 검색어 구성 | **소분류 + 제품군 + 광고 키워드** (예: `"수분크림 광고 CF"`) | 대분류(`제품광고`)만으로는 무관한 결과가 나온다 |
| 제품군 추출 | `AdAnalysis`에 필드가 없으므로 **`productName`에서 일반명사만 추출** (§6-1) | 브랜드명이 들어가면 경쟁사 광고만 나오거나 결과가 0건이 된다 |
| 검색 API 키 | **앱 소유 공용 키** (Cloud Function) | 사용자 BYOK는 GCP 프로젝트·키 발급 장벽이 커서 대부분 이탈한다 |
| 쿼터 대응 | 25개 일괄 수신 + Firestore 캐시 + 대체 입구 2개 | 검색 한도가 하루 약 100회로 낮다 |
| 레퍼런스 입구 | **검색 / URL 직접 / 글로 설명** 3갈래 | 유튜브에 원하는 광고가 없는 경우가 실제로 흔하다 |
| 코인 과금 | **없음** (당분간) | Gemini 영상 분석이 현재 프리뷰 무료라 원가 0 |

## 3. 확인된 외부 제약

구현 가능성이 여기에 달려 있어 실제 문서로 확인했다.

**Gemini — YouTube URL 직접 분석 (핵심 의존성)**
- YouTube URL을 영상 입력으로 직접 받는다. 다운로드·재업로드 불필요.
- **공개 영상만** 가능 (비공개·미등록 불가).
- 무료 티어 **하루 8시간 분량** — 30초 광고 기준 약 960편이므로 실질 제약이 아니다.
- **현재 프리뷰라 무료. 향후 과금·한도 변경이 문서에 명시돼 있다.** → §8 위험 참조.
- 출처: https://ai.google.dev/gemini-api/docs/video-understanding

**YouTube Data API v3 — 검색**
- `search.list`는 **하루 약 100회**로 제한된다 (프로젝트 단위).
- 한 번 호출로 **최대 50개** 결과를 받을 수 있고 **비용은 개수와 무관하게 동일**하다.
  → 25개를 한 번에 받아두면 "다른 후보 보기"가 추가 비용 0이 된다. 이 설계의 핵심 절약 지점.
- `videos.list` 등 조회는 1유닛으로 저렴하다.
- 캐시한 API 데이터는 30일 내 갱신·삭제해야 한다 (약관). → TTL 7일 채택.
- 출처: https://developers.google.com/youtube/v3/determine_quota_cost

## 4. 사용자 흐름

분기 지점은 **A5_Concept의 "스토리 구성" 선택**이다.
(A3는 길이·음악·음성·자막 설정 페이지이며 이 설계와 무관하다.)

```
A5 컨셉
 ├ 대분류 · 소분류 · 강조점 · 톤 · 비주얼스타일   ← 변경 없음
 └ 스토리 구성
     ├ [템플릿]      AD_STRUCTURES 8종 중 선택    ← 기존 경로, 코드 변경 없음
     └ [유튜브 오마주] → A5b 레퍼런스 화면
```

### A5b 레퍼런스 화면 — 입구 3개가 하나로 수렴

```
① 검색으로 찾기
     소분류 + 제품군 → 검색어 자동생성 (수정 가능)
     → youtubeSearch (공용 키 + 캐시, 25개 수신)
     → 5개씩 카드 표시 · "다른 후보 보기"는 쿼터 0
     → 선택
② URL 직접 넣기        (검색창과 나란히, 폴백이 아닌 대등한 입구)
③ 글로 설명하기        (유튜브에 없는 느낌을 서술)

        ↓ 세 갈래 모두

   HomageStructure  →  A6 스토리보드
```

어느 단계에서든 **"그냥 템플릿에서 고르기"로 복귀**할 수 있다.
이 기능 때문에 광고를 못 만드는 상황은 존재해선 안 된다.

## 5. 데이터 모델

`AdConceptSelection`에 두 필드를 추가한다.

```ts
structureSource: 'template' | 'homage'   // 기본 'template' — 기존 동작 보존
homage?: HomageReference
```

### `structureId`는 비워두지 않는다 — 예약 id `ad_homage`

오마주 모드에서도 `structureId`에 반드시 **`'ad_homage'`**를 넣는다. 비워두면 두 곳이 조용히 깨진다.

- `A5_Concept.tsx:63` — `canProceed`가 `structureId !== ''`를 요구한다. 비면 진행 버튼이 죽는다.
- `storyboardGenerator.ts:1852` — `isAdProject`를 `conceptId.startsWith('ad_')`로 판정한다.
  비거나 `ad_` 접두사가 없으면 **광고 각본 생성 분기 자체가 안 돈다.** 제품 분석 결과가
  통째로 무시되고 일반 오마주앱 템플릿이 나온다.

`'ad_homage'`는 `AD_STRUCTURES`에 **등록하지 않는다** (템플릿 탭 목록에 뜨면 안 된다).
`AD_CONCEPT_TEMPLATES['ad_homage']`도 만들지 않는다 — §6의 `:1824` 분기가 그 앞에서
가로채기 때문이다. 다만 가로채기에 실패했을 때 `DEFAULT_CONCEPT_TEMPLATE`으로
조용히 흘러가지 않도록, homage인데 `structure`가 없으면 **명시적으로 실패**시킨다.

```ts
interface HomageReference {
  source: 'search' | 'url' | 'description'
  videoId?: string          // description 입구에서는 없다
  title?: string
  channelTitle?: string
  thumbnailUrl?: string
  durationSec?: number
  userDescription?: string  // description 입구의 원문
  structure: HomageStructure
  analyzedAt: number
}
```

```ts
// ⚠️ 저작권 가드레일: 구조만 담고 표현은 담지 않는다.
//    "베끼지 마라"라고 프롬프트로 부탁하는 대신, 담을 그릇을 만들지 않는다.
interface HomageStructure {
  scenes: {
    seq: number
    durationSec: number
    shotType: 'wide' | 'medium' | 'close' | 'extreme_close' | 'insert' | 'text_card'
    cameraMove: 'static' | 'pan' | 'tilt' | 'push_in' | 'pull_out' | 'handheld' | 'orbit'
    subjectRole: 'product' | 'person' | 'environment' | 'text' | 'abstract'
    emotionBeat: string     // "긴장 고조" 같은 감정 단계. 원본 대사가 아니다. 40자 제한
    transition: 'cut' | 'dissolve' | 'wipe' | 'match_cut'
  }[]
  pacing: 'slow' | 'medium' | 'fast' | 'accelerating'
  overallArc: string        // 서사 곡선 한 줄 요약. 80자 제한
}
```

**대사·자막 문구·브랜드명·로고 묘사를 담을 필드가 없다.**
씬의 실제 대사와 화면 설명은 **항상 `AdAnalysis`(내 제품 분석 결과)에서 생성**되며,
레퍼런스는 리듬과 샷 순서만 제공한다.

## 6. 컴포넌트

| 파일 | 역할 | 신규/수정 |
|---|---|---|
| `functions/index.js` → `youtubeSearch` | 공용 키로 검색. Bearer 토큰 검증(corsProxy와 동일 패턴). `maxResults=25`. Firestore 캐시 | 신규 export |
| `src/services/youtubeService.ts` | 검색어 조립(§6-1), 결과 파싱, URL→videoId 추출 | 신규 |
| `src/services/homageAnalyzer.ts` | 입구 3개가 수렴하는 지점 | 신규 |
| `src/pages/A5b_Reference.tsx` | 레퍼런스 선택 화면 | 신규 |
| `src/pages/A5_Concept.tsx` | 구성 선택에 탭 추가 | 수정 |
| `src/stores/adStore.ts` | 두 필드 추가 | 수정 |
| `src/utils/storyboardGenerator.ts` | 분기 2곳 + `buildSceneDurations`에 선택적 `weights` 인자 | 수정 |
| `src/App.tsx` | `/reference` 라우트 | 수정 |

### 6-1. 검색어 조립 — 브랜드명을 반드시 뺀다

`AdAnalysis`에는 제품군 필드가 없다(`productName`·`description`·`keyFeatures`·
`targetAudience`·`mainBenefit`뿐). 그래서 `productName`에서 **일반명사만 뽑아** 쓴다.

```
"미리집 수분크림 50ml"  →  "수분크림"
```

브랜드명을 그대로 넣으면 두 가지로 망가진다 — 그 브랜드의 기존 광고만 나오거나
(신규 브랜드면) 결과가 0건이 된다. 어느 쪽도 "같은 결의 광고 참고"라는 목적에 맞지 않는다.

추출은 Gemini에 맡긴다(분석 단계에서 이미 호출하므로 추가 왕복이 없다).
실패하면 `categorySub` 라벨만으로 폴백한다.

최종 형태: `` `${제품군} ${categorySub 라벨} 광고` `` + 선택적 `CF` 키워드.
**조립 결과는 항상 입력창에 노출**해 사용자가 고쳐 재검색할 수 있어야 한다(§7).

### homageAnalyzer — 이 설계의 중심

```ts
analyzeFromVideo(videoId: string): Promise<HomageStructure>
analyzeFromDescription(text: string): Promise<HomageStructure>
```

둘 다 같은 스키마를 반환한다. 호출부는 어느 입구였는지 몰라도 된다.
세 번째 입구(글로 설명)가 코드를 거의 늘리지 않는 이유가 이것이다 —
입력만 다르고 출력 계약과 후처리가 동일하다.

### storyboardGenerator 통합 — 정확히 두 지점

- **`storyboardGenerator.ts:1824`** — `AD_CONCEPT_TEMPLATES[conceptId]`로 6씬 풀을 가져오는 자리.
  homage면 `structure.scenes`를 뼈대로 사용한다. **씬 수 정합은 아래 규칙을 따른다.**
- **`storyboardGenerator.ts:1871-1872`** — Gemini에 넘기는 `structureLabel`/`structureFlow` 자리.
  homage면 샷 순서 + 페이싱 + 감정 곡선 요약으로 대체한다.

`structureSource === 'template'`이면 두 분기 모두 기존 경로를 그대로 탄다.

### 씬 수 정합 — 레퍼런스 길이 ≠ 내 영상 길이

레퍼런스가 30초 12씬인데 내 광고가 15초일 수 있다. 기존 생성기는
`desiredCount = durationSec / 3`으로 씬 수를 역산하므로 그대로 두면 어긋난다.

**비율 보존 리샘플링**을 쓴다. 씬을 앞에서 자르지 않는다 — 그러면 광고의 마무리(CTA)가
통째로 날아간다.

1. 목표 씬 수 `n = max(3, round(durationSec / 3))`을 구한다.
2. 레퍼런스 씬이 `n`개보다 **많으면**: `durationSec` 비중이 낮은 씬부터 병합한다.
   인접한 같은 `subjectRole` 씬을 우선 합쳐 서사 단계를 보존한다.
3. `n`개보다 **적으면**: 가장 긴 씬을 둘로 나눈다. 나뉜 씬은 `shotType`을 한 단계
   좁혀(`wide`→`medium`) 같은 비트 안에서 시선이 좁혀지게 한다.
4. 최종 씬 길이는 **레퍼런스의 상대 길이 비율을 가중치로** 재배분한다.
   페이싱(빠름/느림)이 이 비율에 담겨 있어, 균등 분배하면 오마주의 핵심인 리듬이 사라진다.

첫 씬(훅)과 마지막 씬(마무리)은 병합·분할 대상에서 **항상 제외**한다.

**기존 함수는 가중치를 받지 않는다.** `buildSceneDurations(durationSec, sceneCount)`
(`:1797`)에는 가중치 인자가 없으므로 **선택적 3번째 인자 `weights?: number[]`를 추가**한다.
인자를 안 넘기면 지금과 완전히 동일하게 동작해야 한다(§9 회귀).

**재현 한계를 인정한다.** 같은 함수가 씬 길이를 `SCENE_SEC_MIN=2` ~ `SCENE_SEC_SOFT_MAX=4`초로
클램프한다(`:1798`, `:1803-1804`). 즉 레퍼런스의 0.5초 퀵컷이나 8초 롱테이크는
**그대로 재현되지 않고 2~4초로 눌린다.** 이것은 영상 생성 어댑터가 짧은 클립을
안정적으로 못 만들기 때문에 생긴 기존 제약이며, 이 설계에서 풀지 않는다.

따라서 오마주가 실제로 전달하는 것은 **컷의 절대 길이가 아니라 상대적 완급과 샷 순서**다.
사용자 기대를 왜곡하지 않도록 UI에 이 점을 한 줄로 알린다 —
"참고 영상의 컷 순서와 완급을 가져옵니다(컷 길이는 영상 생성 한계에 맞춰 조정됩니다)".

## 7. 오류 처리

**이 기능에서만 "조용한 폴백"을 쓰지 않는다.**
앱의 기존 원칙은 AI 실패 시 조용히 템플릿으로 되돌아가는 것이지만, 오마주는 사용자가
명시적으로 고른 것이라 조용히 바꿔치기하면 "왜 내가 고른 영상 느낌이 안 나지?"가 된다.
항상 알리고 선택지를 준다.

| 상황 | 처리 |
|---|---|
| 검색 쿼터 소진 | 에러 아님 — "오늘 자동검색 한도 소진. URL 붙여넣기나 직접 설명으로 진행하세요" |
| 검색 결과 0건 | 검색어 수정 유도 + 나머지 두 입구 안내 |
| 5개가 마음에 안 듦 | "다른 후보 보기" (쿼터 0, 25개 중에서) → 소진 시 검색어 수정 |
| 비공개·연령제한·삭제 영상 | "이 영상은 분석할 수 없습니다" + 다른 후보로 복귀 |
| 너무 긴 영상 (직접 URL) | `videos.list`(1유닛)로 길이 확인, 10분 초과면 경고 |
| Gemini 분석 실패 | 1회 재시도 → 실패 시 "레퍼런스 없이 진행 / 다시 고르기" 선택 |
| 스키마 불일치 응답 | whitelist 후처리로 정리 시도 → 필수 필드 없으면 실패 처리 |

## 8. 저작권 가드레일

세 겹으로 막는다.

1. **스키마에 표현 필드 없음** — 대사·자막·브랜드명을 담을 자리가 애초에 없다.
2. **whitelist 후처리** — 응답에서 스키마 밖 필드는 버린다. 자유 텍스트(`emotionBeat`,
   `overallArc`)는 길이를 제한해 원본 대사가 통째로 새어드는 것을 막는다.
3. **생성 단계 분리** — 씬의 실제 대사·화면 설명은 `AdAnalysis`에서만 생성한다.
   레퍼런스는 뼈대만 제공하고 살은 내 제품 자료에서 붙는다.

완성된 프로젝트에 참고 영상 링크를 기록해 사후 추적이 가능하게 한다.

## 9. 검증

**회귀가 가장 중요하다.** 오마주를 쓰지 않는 사용자에게 영향이 0이어야 한다.

| 종류 | 내용 |
|---|---|
| 회귀 | `structureSource='template'`일 때 스토리보드 출력이 도입 전과 **완전히 동일**. `buildSceneDurations`를 `weights` 없이 호출했을 때 반환값이 도입 전과 동일 |
| 유닛 | 검색어 조립 / URL 파싱(youtu.be·shorts·embed·타임스탬프 포함 등 다양한 형태) / 스키마 검증 / whitelist 후처리 |
| 통합 | 캐시 히트·미스, 쿼터 소진 경로, 입구 3개가 동일 스키마로 수렴하는지 |
| E2E | 실제 광고 영상 하나로 검색→선택→분석→스토리보드 전 구간 |

## 10. 위험과 미결

| 항목 | 내용 |
|---|---|
| **Gemini 영상분석 과금 전환** | 현재 프리뷰 무료지만 문서에 변경 예고가 있다. 과금 시작 시 코인 과금(§2) 재검토 필요 |
| 검색 쿼터 확장 | 사용자가 늘면 하루 100검색이 병목이 된다. 그때 BYOK 유튜브 키를 선택지로 추가 |
| 유튜브 약관 | 검색 결과 표시 시 채널명·썸네일 출처 표기 규칙 확인 필요 |
| 여러 영상 혼합 | Gemini 2.5는 요청당 최대 10개 영상을 받는다. 여러 레퍼런스를 섞는 것은 후속 과제 |
| 배포 | 이 저장소는 배포 가드가 걸려 있어 `youtubeSearch` 함수는 운영 저장소에서 배포해야 한다 |
