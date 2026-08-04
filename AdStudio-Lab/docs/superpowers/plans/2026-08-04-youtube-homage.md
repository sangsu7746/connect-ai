# 유튜브 레퍼런스 오마주 모드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자료 분석 결과로 유튜브 광고를 검색·선택하고, 그 영상의 씬 구조를 오마주해 스토리보드를 만드는 모드를 기존 템플릿 모드와 나란히 추가한다.

**Architecture:** 레퍼런스 입구 3개(검색·URL·글로 설명)가 모두 `HomageStructure` 하나로 수렴한다. 유튜브 검색만 새 Cloud Function(공용 키 + Firestore 캐시)을 쓰고, 영상 분석은 기존 BYOK Gemini 경로(`callProxy`)를 재사용한다. `storyboardGenerator`는 두 지점에서만 분기하며, `structureSource === 'template'`이면 기존 코드 경로를 그대로 탄다.

**Tech Stack:** React 19 · TypeScript · Vite 8 · Zustand 5 · Firebase Functions v1(nodejs20) · Gemini API(YouTube URL 영상 입력) · YouTube Data API v3 · Vitest(이번에 신규 도입)

## Global Constraints

이 절의 요구사항은 **모든 태스크에 암묵적으로 포함**된다.

- **회귀 불변**: `structureSource === 'template'`일 때 스토리보드 출력이 도입 전과 완전히 동일해야 한다. `buildSceneDurations`를 `weights` 없이 호출한 결과도 동일해야 한다.
- **저작권 경계**: `HomageStructure`에 대사·자막 문구·브랜드명·로고 묘사를 담는 필드를 **만들지 않는다**. 자유 텍스트는 `emotionBeat` 40자, `overallArc` 80자로 제한한다. 씬의 실제 대사·화면 설명은 항상 `AdAnalysis`에서 생성한다.
- **배포 금지**: 이 저장소는 `scripts/deploy-guard.cjs`가 `headjim-ai` 배포를 차단한다. 어떤 태스크에서도 `firebase deploy`를 실행하지 않는다.
- **예약 id**: 오마주 모드의 `structureId`는 항상 `'ad_homage'`. `AD_STRUCTURES`·`AD_CONCEPT_TEMPLATES`에는 **등록하지 않는다**.
- **검색 파라미터**: `maxResults=25`, 캐시 TTL **7일**(유튜브 약관 30일 이내 요구).
- **씬 길이 클램프**: `SCENE_SEC_MIN=2`, `SCENE_SEC_SOFT_MAX=4`는 변경하지 않는다.
- **커밋**: 각 태스크 끝에서 커밋한다. 브랜치는 `feat/adstudio-youtube-homage`.
- **작업 디렉터리**: 모든 명령은 `D:\AdStudio-Lab` 기준.

---

## File Structure

| 파일 | 책임 | 태스크 |
|---|---|---|
| `vitest.config.ts` | 테스트 러너 설정 | 1 |
| `src/types/homage.ts` | `HomageStructure` · `HomageReference` · `HOMAGE_STRUCTURE_ID` | 2 |
| `src/stores/adStore.ts` | `structureSource` · `homage` 상태 | 2 |
| `src/services/homageSchema.ts` | 스키마 검증 · whitelist 후처리 (순수) | 3 |
| `src/services/youtubeService.ts` | 검색어 조립 · URL 파싱 (순수) + 검색 호출 | 4, 7 |
| `src/utils/homageResampler.ts` | 씬 수 정합 리샘플링 (순수) | 5 |
| `src/utils/storyboardGenerator.ts` | `buildSceneDurations` 가중치 · 분기 2곳 | 5, 9 |
| `functions/index.js` | `youtubeSearch` 함수 | 6 |
| `src/services/homageAnalyzer.ts` | 영상/글 → `HomageStructure` | 8 |
| `src/pages/A5b_Reference.tsx` | 레퍼런스 선택 화면 | 10 |
| `src/pages/A5_Concept.tsx` · `src/App.tsx` | 모드 분기 · 라우트 | 11 |

---

## Task 1: 테스트 인프라 도입

이 저장소에는 **테스트 러너가 전혀 없다**(`package.json`에 vitest·jest 없음, 테스트 파일 0개). 이후 모든 태스크가 TDD로 진행되므로 먼저 깐다.

**Files:**
- Create: `vitest.config.ts`
- Create: `src/services/__smoke__/setup.test.ts`
- Modify: `package.json` (devDependencies, scripts)

**Interfaces:**
- Consumes: 없음
- Produces: `npm test` 명령. 이후 모든 태스크가 이 명령으로 테스트를 돌린다.

- [ ] **Step 1: vitest 설치**

```bash
npm install -D vitest@^3
```

- [ ] **Step 2: vitest.config.ts 작성**

```ts
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    // 순수 함수 위주라 node 환경이면 충분하다. DOM 이 필요한 테스트가 생기면
    // 해당 파일 상단에 `// @vitest-environment jsdom` 을 붙인다.
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // 브라우저 전용 모듈(ffmpeg.wasm, mediapipe)을 끌어오는 파일은 테스트하지 않는다
    exclude: ['**/node_modules/**', '**/dist/**'],
  },
})
```

- [ ] **Step 3: package.json 에 스크립트 추가**

`"guard": "node scripts/deploy-guard.cjs manual"` 아래에 추가한다.

```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 4: 러너가 실제로 도는지 확인하는 스모크 테스트**

> ⚠️ 이 파일은 **임시**다. `vitest run` 은 테스트 파일이 0개면 실패하므로 러너 도입을
> 검증할 최소 파일이 필요하다. Task 2 에서 진짜 테스트가 생기면 **삭제한다**
> (Task 2 Step 7). 항구적으로 두면 아무것도 검증하지 않는 테스트가 남는다.

`src/services/__smoke__/setup.test.ts`:

```ts
import { describe, it, expect } from 'vitest'

describe('테스트 인프라', () => {
  it('vitest 가 동작한다', () => {
    expect(1 + 1).toBe(2)
  })
})
```

- [ ] **Step 5: 테스트 실행**

Run: `npm test`
Expected: PASS 1개.

- [ ] **Step 6: 기존 빌드가 깨지지 않았는지 확인**

Run: `npx tsc -b && npm run build`
Expected: 에러 0.

- [ ] **Step 7: 커밋**

```bash
git add vitest.config.ts package.json package-lock.json src/services/__smoke__/setup.test.ts
git commit -m "test: vitest 도입 — 오마주 모드 TDD 기반"
```

---

## Task 2: 타입 정의와 스토어 확장

**Files:**
- Create: `src/types/homage.ts`
- Modify: `src/stores/adStore.ts:31-43` (`AdConceptSelection`, `DEFAULT_AD_CONCEPT`)
- Test: `src/types/homage.test.ts`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `HOMAGE_STRUCTURE_ID = 'ad_homage'` (const)
  - `interface HomageScene`, `HomageStructure`, `HomageReference`
  - `AdConceptSelection.structureSource: 'template' | 'homage'`
  - `AdConceptSelection.homage?: HomageReference`

- [ ] **Step 1: 실패하는 테스트 작성**

`src/types/homage.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { HOMAGE_STRUCTURE_ID, SHOT_TYPES, CAMERA_MOVES } from './homage'

describe('오마주 타입 상수', () => {
  it('예약 structureId 는 ad_ 접두사를 가진다', () => {
    // storyboardGenerator 의 isAdProject 판정이 conceptId.startsWith('ad_') 이므로
    // 이 접두사가 빠지면 광고 각본 생성 분기가 통째로 안 돈다
    expect(HOMAGE_STRUCTURE_ID).toBe('ad_homage')
    expect(HOMAGE_STRUCTURE_ID.startsWith('ad_')).toBe(true)
  })

  it('샷 타입과 카메라 무브가 정의돼 있다', () => {
    expect(SHOT_TYPES).toContain('close')
    expect(CAMERA_MOVES).toContain('push_in')
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `npm test -- homage`
Expected: FAIL — `Cannot find module './homage'`

- [ ] **Step 3: 타입 파일 작성**

`src/types/homage.ts`:

```ts
/**
 * 유튜브 레퍼런스 오마주 — 구조 전용 타입.
 *
 * ⚠️ 저작권 경계: 이 파일의 어떤 타입에도 원본 대사·자막 문구·브랜드명·로고 묘사를
 *    담는 필드를 추가하지 않는다. "베끼지 마라"라고 프롬프트로 부탁하는 대신
 *    담을 그릇 자체를 만들지 않는 방식이다. 씬의 실제 대사와 화면 설명은
 *    항상 AdAnalysis(내 제품 분석 결과)에서 생성된다.
 */

/**
 * 오마주 모드의 예약 structureId.
 *
 * ⚠️ 비워두면 두 곳이 조용히 깨진다:
 *  - A5_Concept.tsx 의 canProceed 가 structureId !== '' 를 요구한다
 *  - storyboardGenerator 의 isAdProject 가 conceptId.startsWith('ad_') 로 판정한다
 *    → 접두사가 없으면 광고 각본 생성 분기가 안 돌고 제품 분석 결과가 무시된다
 *
 * AD_STRUCTURES / AD_CONCEPT_TEMPLATES 에는 등록하지 않는다(템플릿 목록에 뜨면 안 된다).
 */
export const HOMAGE_STRUCTURE_ID = 'ad_homage'

export const SHOT_TYPES = ['wide', 'medium', 'close', 'extreme_close', 'insert', 'text_card'] as const
export const CAMERA_MOVES = ['static', 'pan', 'tilt', 'push_in', 'pull_out', 'handheld', 'orbit'] as const
export const SUBJECT_ROLES = ['product', 'person', 'environment', 'text', 'abstract'] as const
export const TRANSITIONS = ['cut', 'dissolve', 'wipe', 'match_cut'] as const
export const PACINGS = ['slow', 'medium', 'fast', 'accelerating'] as const

export type ShotType = (typeof SHOT_TYPES)[number]
export type CameraMove = (typeof CAMERA_MOVES)[number]
export type SubjectRole = (typeof SUBJECT_ROLES)[number]
export type Transition = (typeof TRANSITIONS)[number]
export type Pacing = (typeof PACINGS)[number]

/** 자유 텍스트 상한 — 원본 대사가 통째로 새어드는 것을 막는다 */
export const EMOTION_BEAT_MAX = 40
export const OVERALL_ARC_MAX = 80

export interface HomageScene {
  seq: number
  durationSec: number
  shotType: ShotType
  cameraMove: CameraMove
  subjectRole: SubjectRole
  /** "긴장 고조" 같은 감정 단계. 원본 대사가 아니다. EMOTION_BEAT_MAX 자 제한 */
  emotionBeat: string
  transition: Transition
}

export interface HomageStructure {
  scenes: HomageScene[]
  pacing: Pacing
  /** 서사 곡선 한 줄 요약. OVERALL_ARC_MAX 자 제한 */
  overallArc: string
}

export interface HomageReference {
  source: 'search' | 'url' | 'description'
  videoId?: string           // description 입구에서는 없다
  title?: string
  channelTitle?: string
  thumbnailUrl?: string
  durationSec?: number
  userDescription?: string   // description 입구의 원문
  structure: HomageStructure
  analyzedAt: number
}

/** 검색 결과 카드 1장 — 아직 분석하지 않은 후보 */
export interface HomageCandidate {
  videoId: string
  title: string
  channelTitle: string
  thumbnailUrl: string
  publishedAt: string
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `npm test -- homage`
Expected: PASS 2개.

- [ ] **Step 5: 스토어에 두 필드 추가**

`src/stores/adStore.ts` 상단 import 에 추가:

```ts
import type { HomageReference } from '../types/homage'
```

`AdConceptSelection`(`:31-38`)에 두 줄 추가:

```ts
export interface AdConceptSelection {
  categoryMain: string   // 대분류 id (예: 'food')
  categorySub: string    // 소분류 id (예: 'fresh')
  emphasis: string[]     // 강조 포인트 id, 최대 2개
  structureId: string    // 스토리 구성 id (ad_*) — project.conceptId로 저장된다
  tone: string           // 톤&무드 id
  visualStyle: string    // 비주얼 스타일(룩) id — 조명·질감의 방향을 정한다
  /** 구성의 출처. 'template' 이면 기존 경로를 그대로 탄다(회귀 불변) */
  structureSource: 'template' | 'homage'
  /** structureSource === 'homage' 일 때만 존재 */
  homage?: HomageReference
}
```

`DEFAULT_AD_CONCEPT`(`:40-43`)에 기본값 추가 — **`'template'` 이어야 기존 동작이 보존된다**:

```ts
const DEFAULT_AD_CONCEPT: AdConceptSelection = {
  categoryMain: '', categorySub: '', emphasis: [], structureId: '', tone: 'energetic',
  visualStyle: 'clean_bright', structureSource: 'template',
}
```

- [ ] **Step 6: 타입 검사**

Run: `npx tsc -b`
Expected: 에러 0.

> `adStore` 는 zustand `persist` 를 쓴다. 기존 사용자의 localStorage 에는 `structureSource` 가 없어 `undefined` 로 복원된다. Task 9 의 분기는 `=== 'homage'` 로 판정하므로 `undefined` 는 자동으로 템플릿 경로가 된다 — 마이그레이션이 불필요하다. 이 점은 Task 12 에서 실제로 검증한다.

- [ ] **Step 7: Task 1 의 임시 스모크 테스트를 삭제하고 커밋**

`homage.test.ts` 가 러너 동작을 증명하므로 임시 파일은 역할이 끝났다. 남겨두면
아무것도 검증하지 않는 테스트가 영구히 남는다.

```bash
rm -rf src/services/__smoke__
npm test
```

Expected: `homage.test.ts` 2개 PASS, 스모크 테스트는 목록에서 사라진다.

```bash
git add -A src/types/homage.ts src/types/homage.test.ts src/stores/adStore.ts src/services/__smoke__
git commit -m "feat(homage): 구조 전용 타입과 스토어 필드 추가"
```

---

## Task 3: 스키마 검증과 whitelist 후처리

LLM 응답을 신뢰하지 않는다. 스키마 밖 필드를 버리고, 자유 텍스트를 자르고, enum 을 강제한다. 저작권 가드레일의 두 번째 겹이다.

**Files:**
- Create: `src/services/homageSchema.ts`
- Test: `src/services/homageSchema.test.ts`

**Interfaces:**
- Consumes: `src/types/homage.ts` 전체
- Produces:
  - `sanitizeHomageStructure(raw: unknown): HomageStructure` — 실패 시 `throw new Error`
  - `HOMAGE_JSON_SCHEMA_HINT: string` — Gemini 프롬프트에 넣을 스키마 설명

- [ ] **Step 1: 실패하는 테스트 작성**

`src/services/homageSchema.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { sanitizeHomageStructure } from './homageSchema'

const validRaw = {
  scenes: [
    { seq: 1, durationSec: 3, shotType: 'wide', cameraMove: 'static',
      subjectRole: 'environment', emotionBeat: '평온한 일상', transition: 'cut' },
    { seq: 2, durationSec: 2, shotType: 'close', cameraMove: 'push_in',
      subjectRole: 'product', emotionBeat: '문제 인식', transition: 'match_cut' },
    { seq: 3, durationSec: 4, shotType: 'medium', cameraMove: 'pan',
      subjectRole: 'person', emotionBeat: '해소', transition: 'dissolve' },
  ],
  pacing: 'medium',
  overallArc: '일상 → 문제 → 해소',
}

describe('sanitizeHomageStructure', () => {
  it('정상 구조를 그대로 통과시킨다', () => {
    const out = sanitizeHomageStructure(validRaw)
    expect(out.scenes).toHaveLength(3)
    expect(out.pacing).toBe('medium')
    expect(out.scenes[1].shotType).toBe('close')
  })

  it('스키마에 없는 필드를 버린다 — 대사 유출 차단', () => {
    const withDialogue = {
      ...validRaw,
      scenes: validRaw.scenes.map(s => ({
        ...s,
        dialogue: '지금 바로 만나보세요',   // 원본 대사
        brandName: '경쟁사브랜드',
        subtitleText: '한정 특가',
      })),
    }
    const out = sanitizeHomageStructure(withDialogue)
    for (const scene of out.scenes) {
      expect(scene).not.toHaveProperty('dialogue')
      expect(scene).not.toHaveProperty('brandName')
      expect(scene).not.toHaveProperty('subtitleText')
    }
    // 통째로 직렬화해도 원본 문구가 남아 있으면 안 된다
    expect(JSON.stringify(out)).not.toContain('지금 바로')
    expect(JSON.stringify(out)).not.toContain('경쟁사브랜드')
  })

  it('emotionBeat 이 40자를 넘으면 자른다', () => {
    const long = '가'.repeat(100)
    const out = sanitizeHomageStructure({
      ...validRaw,
      scenes: [{ ...validRaw.scenes[0], emotionBeat: long }, validRaw.scenes[1], validRaw.scenes[2]],
    })
    expect(out.scenes[0].emotionBeat).toHaveLength(40)
  })

  it('overallArc 이 80자를 넘으면 자른다', () => {
    const out = sanitizeHomageStructure({ ...validRaw, overallArc: '나'.repeat(200) })
    expect(out.overallArc).toHaveLength(80)
  })

  it('알 수 없는 enum 값은 안전한 기본값으로 바꾼다', () => {
    const out = sanitizeHomageStructure({
      ...validRaw,
      pacing: 'ludicrous',
      scenes: [{ ...validRaw.scenes[0], shotType: 'drone_shot', transition: 'star_wipe' },
               validRaw.scenes[1], validRaw.scenes[2]],
    })
    expect(out.pacing).toBe('medium')
    expect(out.scenes[0].shotType).toBe('medium')
    expect(out.scenes[0].transition).toBe('cut')
  })

  it('seq 를 1부터 다시 매긴다', () => {
    const out = sanitizeHomageStructure({
      ...validRaw,
      scenes: validRaw.scenes.map(s => ({ ...s, seq: 99 })),
    })
    expect(out.scenes.map(s => s.seq)).toEqual([1, 2, 3])
  })

  it('씬이 3개 미만이면 실패시킨다', () => {
    expect(() => sanitizeHomageStructure({ ...validRaw, scenes: [validRaw.scenes[0]] }))
      .toThrow(/씬이 너무 적/)
  })

  it('scenes 가 배열이 아니면 실패시킨다', () => {
    expect(() => sanitizeHomageStructure({ scenes: 'nope', pacing: 'fast', overallArc: 'x' }))
      .toThrow(/구조를 읽지 못/)
  })

  it('durationSec 이 숫자가 아니면 3초로 채운다', () => {
    const out = sanitizeHomageStructure({
      ...validRaw,
      scenes: [{ ...validRaw.scenes[0], durationSec: 'long' }, validRaw.scenes[1], validRaw.scenes[2]],
    })
    expect(out.scenes[0].durationSec).toBe(3)
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `npm test -- homageSchema`
Expected: FAIL — `Cannot find module './homageSchema'`

- [ ] **Step 3: 구현**

`src/services/homageSchema.ts`:

```ts
import {
  SHOT_TYPES, CAMERA_MOVES, SUBJECT_ROLES, TRANSITIONS, PACINGS,
  EMOTION_BEAT_MAX, OVERALL_ARC_MAX,
} from '../types/homage'
import type { HomageScene, HomageStructure } from '../types/homage'

/** 최소 씬 수 — 이보다 적으면 광고 서사가 성립하지 않는다 */
const MIN_SCENES = 3
/** 최대 씬 수 — LLM 이 폭주했을 때의 상한 */
const MAX_SCENES = 24
const DEFAULT_SCENE_SEC = 3

function pickEnum<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback
}

function clampText(value: unknown, max: number): string {
  if (typeof value !== 'string') return ''
  return value.trim().slice(0, max)
}

/**
 * LLM 이 돌려준 원시 응답을 신뢰할 수 있는 HomageStructure 로 정제한다.
 *
 * ⚠️ 저작권 가드레일 2단계: 여기서 **스키마에 없는 필드를 전부 버린다**.
 *    타입 정의만으로는 런타임에 아무것도 막지 못한다 — LLM 이 dialogue·brandName 같은
 *    필드를 끼워 넣으면 그대로 저장되고 프롬프트로 흘러간다. 화이트리스트 방식으로
 *    필요한 키만 새 객체에 옮겨 담아 원본 표현이 새어나갈 경로를 끊는다.
 */
export function sanitizeHomageStructure(raw: unknown): HomageStructure {
  if (!raw || typeof raw !== 'object') {
    throw new Error('오마주 구조를 읽지 못했어요. 다시 시도해주세요.')
  }
  const obj = raw as Record<string, unknown>

  if (!Array.isArray(obj.scenes)) {
    throw new Error('오마주 구조를 읽지 못했어요 (씬 목록 없음).')
  }

  const scenes: HomageScene[] = obj.scenes
    .slice(0, MAX_SCENES)
    .filter(s => s && typeof s === 'object')
    .map((s, i) => {
      const src = s as Record<string, unknown>
      const dur = Number(src.durationSec)
      // 화이트리스트 — 여기 없는 키는 전부 버려진다
      return {
        seq: i + 1,
        durationSec: Number.isFinite(dur) && dur > 0 ? Math.round(dur * 10) / 10 : DEFAULT_SCENE_SEC,
        shotType: pickEnum(src.shotType, SHOT_TYPES, 'medium'),
        cameraMove: pickEnum(src.cameraMove, CAMERA_MOVES, 'static'),
        subjectRole: pickEnum(src.subjectRole, SUBJECT_ROLES, 'product'),
        emotionBeat: clampText(src.emotionBeat, EMOTION_BEAT_MAX),
        transition: pickEnum(src.transition, TRANSITIONS, 'cut'),
      }
    })

  if (scenes.length < MIN_SCENES) {
    throw new Error(`오마주 구조의 씬이 너무 적어요 (${scenes.length}개). 다른 영상을 골라주세요.`)
  }

  return {
    scenes,
    pacing: pickEnum(obj.pacing, PACINGS, 'medium'),
    overallArc: clampText(obj.overallArc, OVERALL_ARC_MAX),
  }
}

/**
 * Gemini 에 넘길 스키마 설명. 응답 형식을 고정해 파싱 실패를 줄인다.
 * 마지막 문장이 저작권 가드레일 1단계(프롬프트 수준)다 — 실제 차단은
 * sanitizeHomageStructure 가 하지만, 애초에 안 뱉게 하는 편이 낫다.
 */
export const HOMAGE_JSON_SCHEMA_HINT = `
Return ONLY valid JSON with this exact shape:
{
  "scenes": [
    {
      "seq": 1,
      "durationSec": 2.5,
      "shotType": "wide|medium|close|extreme_close|insert|text_card",
      "cameraMove": "static|pan|tilt|push_in|pull_out|handheld|orbit",
      "subjectRole": "product|person|environment|text|abstract",
      "emotionBeat": "short Korean phrase describing the emotional beat, max 40 chars",
      "transition": "cut|dissolve|wipe|match_cut"
    }
  ],
  "pacing": "slow|medium|fast|accelerating",
  "overallArc": "one-line Korean summary of the narrative arc, max 80 chars"
}

CRITICAL: Describe STRUCTURE ONLY — shot grammar, pacing, emotional progression.
Do NOT transcribe or paraphrase any spoken dialogue, on-screen text, subtitles,
brand names, product names, slogans, or logos. Those fields do not exist in the
schema and any such content will be discarded.
`.trim()
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `npm test -- homageSchema`
Expected: PASS 9개.

- [ ] **Step 5: 커밋**

```bash
git add src/services/homageSchema.ts src/services/homageSchema.test.ts
git commit -m "feat(homage): 스키마 검증·whitelist 후처리 — 원본 표현 유출 차단"
```

---

## Task 4: 검색어 조립과 URL 파싱 (순수 함수)

**Files:**
- Create: `src/services/youtubeService.ts` (순수 함수부만)
- Test: `src/services/youtubeService.test.ts`

**Interfaces:**
- Consumes: `AdAnalysis`(`src/stores/adStore.ts`), `AD_CATEGORIES`(`src/utils/adConcepts.ts`)
- Produces:
  - `buildSearchQuery(productTypeKo: string, categorySubLabel: string): string`
  - `parseYoutubeVideoId(input: string): string | null`

- [ ] **Step 1: 실패하는 테스트 작성**

`src/services/youtubeService.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { buildSearchQuery, parseYoutubeVideoId } from './youtubeService'

describe('buildSearchQuery', () => {
  it('제품군과 소분류를 합쳐 광고 검색어를 만든다', () => {
    expect(buildSearchQuery('수분크림', '화장품')).toBe('수분크림 화장품 광고')
  })

  it('제품군이 비면 소분류만으로 만든다', () => {
    expect(buildSearchQuery('', '화장품')).toBe('화장품 광고')
  })

  it('소분류가 비면 제품군만으로 만든다', () => {
    expect(buildSearchQuery('수분크림', '')).toBe('수분크림 광고')
  })

  it('둘 다 비면 빈 문자열을 준다 — 호출부가 검색을 막을 수 있게', () => {
    expect(buildSearchQuery('', '')).toBe('')
  })

  it('중복 단어를 접지 않고 공백을 정리한다', () => {
    expect(buildSearchQuery('  수분크림  ', ' 화장품 ')).toBe('수분크림 화장품 광고')
  })

  it('제품군과 소분류가 같으면 한 번만 넣는다', () => {
    expect(buildSearchQuery('화장품', '화장품')).toBe('화장품 광고')
  })
})

describe('parseYoutubeVideoId', () => {
  it.each([
    ['https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'dQw4w9WgXcQ'],
    ['https://youtube.com/watch?v=dQw4w9WgXcQ&t=30s', 'dQw4w9WgXcQ'],
    ['https://youtu.be/dQw4w9WgXcQ', 'dQw4w9WgXcQ'],
    ['https://youtu.be/dQw4w9WgXcQ?t=42', 'dQw4w9WgXcQ'],
    ['https://www.youtube.com/shorts/dQw4w9WgXcQ', 'dQw4w9WgXcQ'],
    ['https://www.youtube.com/embed/dQw4w9WgXcQ', 'dQw4w9WgXcQ'],
    ['https://m.youtube.com/watch?v=dQw4w9WgXcQ', 'dQw4w9WgXcQ'],
    ['  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ', 'dQw4w9WgXcQ'],
    ['dQw4w9WgXcQ', 'dQw4w9WgXcQ'],           // 순수 id 직접 입력
  ])('%s → %s', (input, expected) => {
    expect(parseYoutubeVideoId(input)).toBe(expected)
  })

  it.each([
    ['https://vimeo.com/12345'],
    ['https://www.youtube.com/watch?v=too_short'],
    ['그냥 한글 문장'],
    [''],
  ])('잘못된 입력은 null: %s', (input) => {
    expect(parseYoutubeVideoId(input)).toBeNull()
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `npm test -- youtubeService`
Expected: FAIL — 모듈 없음.

- [ ] **Step 3: 구현**

`src/services/youtubeService.ts`:

```ts
import type { HomageCandidate } from '../types/homage'

/** 유튜브 videoId 는 11자 [A-Za-z0-9_-] 로 고정돼 있다 */
const VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/

/**
 * 검색어를 조립한다 — `{제품군} {소분류} 광고`.
 *
 * ⚠️ 브랜드명은 절대 넣지 않는다. 넣으면 그 브랜드의 기존 광고만 나오거나
 *    (신규 브랜드면) 결과가 0건이 된다. 어느 쪽도 "같은 결의 광고 참고"에 맞지 않다.
 *    브랜드 제거는 호출부(extractProductType)가 책임진다.
 */
export function buildSearchQuery(productTypeKo: string, categorySubLabel: string): string {
  const a = productTypeKo.trim()
  const b = categorySubLabel.trim()
  const words = a && b && a !== b ? [a, b] : [a || b].filter(Boolean)
  if (words.length === 0) return ''
  return `${words.join(' ')} 광고`
}

/**
 * 다양한 유튜브 URL 형태에서 videoId 를 뽑는다.
 * watch?v= / youtu.be / shorts / embed / m.youtube 를 모두 받는다.
 * 순수 11자 id 를 그대로 넣는 것도 허용한다.
 */
export function parseYoutubeVideoId(input: string): string | null {
  const s = (input || '').trim()
  if (!s) return null

  if (VIDEO_ID_RE.test(s)) return s

  let url: URL
  try {
    url = new URL(s)
  } catch {
    return null
  }

  const host = url.hostname.replace(/^www\./, '').replace(/^m\./, '')

  let candidate: string | null = null
  if (host === 'youtu.be') {
    candidate = url.pathname.slice(1).split('/')[0]
  } else if (host === 'youtube.com' || host === 'youtube-nocookie.com') {
    if (url.pathname === '/watch') {
      candidate = url.searchParams.get('v')
    } else {
      const m = url.pathname.match(/^\/(?:shorts|embed|v)\/([^/?]+)/)
      candidate = m ? m[1] : null
    }
  }

  return candidate && VIDEO_ID_RE.test(candidate) ? candidate : null
}

export type { HomageCandidate }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `npm test -- youtubeService`
Expected: PASS 19개.

- [ ] **Step 5: 커밋**

```bash
git add src/services/youtubeService.ts src/services/youtubeService.test.ts
git commit -m "feat(homage): 검색어 조립·유튜브 URL 파싱"
```

---

## Task 5: 씬 리샘플링과 buildSceneDurations 가중치

레퍼런스가 30초 12씬인데 내 광고가 15초일 수 있다. 앞에서 자르면 CTA 가 날아가므로 비율 보존 리샘플링을 쓴다.

**Files:**
- Create: `src/utils/homageResampler.ts`
- Modify: `src/utils/storyboardGenerator.ts:1797` (`buildSceneDurations` 시그니처)
- Test: `src/utils/homageResampler.test.ts`

**Interfaces:**
- Consumes: `HomageScene`, `HomageStructure` (`src/types/homage.ts`)
- Produces:
  - `resampleHomageScenes(scenes: HomageScene[], targetCount: number): HomageScene[]`
  - `buildSceneDurations(durationSec: number, sceneCount: number, weights?: number[]): number[]` (기존 함수 확장)

- [ ] **Step 1: 실패하는 테스트 작성**

`src/utils/homageResampler.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { resampleHomageScenes } from './homageResampler'
import type { HomageScene } from '../types/homage'

const scene = (seq: number, durationSec: number, subjectRole: HomageScene['subjectRole'] = 'product'): HomageScene => ({
  seq, durationSec, shotType: 'medium', cameraMove: 'static',
  subjectRole, emotionBeat: `beat${seq}`, transition: 'cut',
})

describe('resampleHomageScenes', () => {
  it('개수가 이미 맞으면 그대로 돌려준다', () => {
    const input = [scene(1, 3), scene(2, 3), scene(3, 3)]
    expect(resampleHomageScenes(input, 3)).toEqual(input)
  })

  it('줄일 때 첫 씬(훅)과 마지막 씬(마무리)을 보존한다', () => {
    const input = [scene(1, 5, 'environment'), scene(2, 1), scene(3, 1), scene(4, 1), scene(5, 4, 'text')]
    const out = resampleHomageScenes(input, 3)
    expect(out).toHaveLength(3)
    expect(out[0].emotionBeat).toBe('beat1')
    expect(out[out.length - 1].emotionBeat).toBe('beat5')
  })

  it('줄일 때 가장 짧은 중간 씬부터 병합한다', () => {
    const input = [scene(1, 5), scene(2, 0.5), scene(3, 4), scene(4, 4)]
    const out = resampleHomageScenes(input, 3)
    expect(out).toHaveLength(3)
    // 0.5초 씬이 이웃과 합쳐져 사라진다
    expect(out.map(s => s.emotionBeat)).not.toContain('beat2')
  })

  it('늘릴 때 가장 긴 씬을 나눈다', () => {
    const input = [scene(1, 2), scene(2, 10), scene(3, 2)]
    const out = resampleHomageScenes(input, 4)
    expect(out).toHaveLength(4)
    // 10초 씬이 둘로 갈려 총 길이는 보존된다
    expect(out.reduce((a, s) => a + s.durationSec, 0)).toBeCloseTo(14, 1)
  })

  it('나뉜 씬은 샷 타입이 한 단계 좁아진다', () => {
    const input = [scene(1, 2), { ...scene(2, 10), shotType: 'wide' as const }, scene(3, 2)]
    const out = resampleHomageScenes(input, 4)
    const widened = out.filter(s => s.emotionBeat === 'beat2')
    expect(widened).toHaveLength(2)
    expect(widened[1].shotType).toBe('medium')
  })

  it('seq 를 1부터 다시 매긴다', () => {
    const out = resampleHomageScenes([scene(1, 5), scene(2, 1), scene(3, 1), scene(4, 5)], 3)
    expect(out.map(s => s.seq)).toEqual([1, 2, 3])
  })

  it('목표가 3 미만이면 3으로 올린다', () => {
    expect(resampleHomageScenes([scene(1, 3), scene(2, 3), scene(3, 3), scene(4, 3)], 1)).toHaveLength(3)
  })

  it('입력이 3개 미만이어도 목표 개수를 채운다', () => {
    expect(resampleHomageScenes([scene(1, 6), scene(2, 6)], 4)).toHaveLength(4)
  })
})
```

`src/utils/storyboardGenerator.test.ts` (신규 — 회귀 보호가 핵심):

```ts
import { describe, it, expect } from 'vitest'
import { buildSceneDurations } from './storyboardGenerator'

describe('buildSceneDurations 회귀', () => {
  it.each([
    [15, 5, 15],
    [30, 10, 30],
    [60, 20, 60],
    [15, 3, 12],   // 씬당 최대 4초 클램프 때문에 총합이 줄어드는 기존 동작
  ])('weights 없이 호출하면 기존 동작을 유지한다 (%i초 %i씬)', (dur, count, expectedTotal) => {
    const out = buildSceneDurations(dur, count)
    expect(out).toHaveLength(count)
    expect(out.reduce((a, b) => a + b, 0)).toBe(expectedTotal)
    for (const d of out) {
      expect(d).toBeGreaterThanOrEqual(2)
      expect(d).toBeLessThanOrEqual(4)
    }
  })
})

describe('buildSceneDurations 가중치', () => {
  it('가중치가 큰 씬에 더 긴 시간을 준다', () => {
    const out = buildSceneDurations(9, 3, [1, 4, 1])
    expect(out).toHaveLength(3)
    expect(out[1]).toBeGreaterThan(out[0])
    expect(out[1]).toBeGreaterThan(out[2])
  })

  it('가중치를 써도 2~4초 클램프를 지킨다', () => {
    const out = buildSceneDurations(9, 3, [1, 100, 1])
    for (const d of out) {
      expect(d).toBeGreaterThanOrEqual(2)
      expect(d).toBeLessThanOrEqual(4)
    }
  })

  it('가중치 길이가 씬 수와 다르면 무시하고 균등 분배한다', () => {
    expect(buildSceneDurations(9, 3, [1, 2])).toEqual(buildSceneDurations(9, 3))
  })

  it('가중치가 전부 0이면 균등 분배로 폴백한다', () => {
    expect(buildSceneDurations(9, 3, [0, 0, 0])).toEqual(buildSceneDurations(9, 3))
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `npm test -- homageResampler storyboardGenerator`
Expected: FAIL — `resampleHomageScenes` 모듈 없음, `buildSceneDurations` 가 export 되지 않음.

- [ ] **Step 3: buildSceneDurations 확장 및 export**

`src/utils/storyboardGenerator.ts:1797` 의 함수를 다음으로 교체한다. **`weights` 를 안 넘기면 기존 코드와 완전히 동일한 경로를 탄다.**

```ts
/**
 * 씬별 길이를 배분한다.
 *
 * @param weights 선택적 상대 가중치(오마주 모드에서 레퍼런스의 컷 비율을 전달).
 *                길이가 sceneCount 와 다르거나 합이 0이면 무시하고 균등 분배한다.
 *
 * ⚠️ 씬 길이는 SCENE_SEC_MIN~SCENE_SEC_SOFT_MAX(2~4초)로 클램프된다. 영상 생성
 *    어댑터가 짧은 클립을 안정적으로 못 만들기 때문에 생긴 기존 제약이며,
 *    레퍼런스의 0.5초 퀵컷이나 8초 롱테이크는 그대로 재현되지 않는다.
 */
export function buildSceneDurations(durationSec: number, sceneCount: number, weights?: number[]): number[] {
  const usable = weights && weights.length === sceneCount && weights.some(w => w > 0)
    ? weights.map(w => (Number.isFinite(w) && w > 0 ? w : 0))
    : null

  let durations: number[]
  if (usable) {
    const total = usable.reduce((a, b) => a + b, 0)
    durations = usable.map(w =>
      Math.max(SCENE_SEC_MIN, Math.min(SCENE_SEC_SOFT_MAX, Math.round((durationSec * w) / total))))
  } else {
    const base = Math.max(SCENE_SEC_MIN, Math.min(SCENE_SEC_SOFT_MAX, Math.floor(durationSec / sceneCount)))
    durations = new Array(sceneCount).fill(base)
  }

  let remainder = durationSec - durations.reduce((a, b) => a + b, 0)

  for (let i = 0; i < durations.length && remainder !== 0; i++) {
    while (remainder > 0 && durations[i] < SCENE_SEC_SOFT_MAX) { durations[i]++; remainder-- }
    while (remainder < 0 && durations[i] > SCENE_SEC_MIN) { durations[i]--; remainder++ }
  }
  return durations
}
```

> 함수 본문 이후 `remainder` 재배분 루프는 원본 `:1800-1805` 와 동일하다. `weights` 없이 호출하면 `base` 계산 → 균등 배열 → 동일 루프로 원본과 바이트 단위로 같은 결과가 나온다.

- [ ] **Step 4: 리샘플러 구현**

`src/utils/homageResampler.ts`:

```ts
import type { HomageScene, ShotType } from '../types/homage'

const MIN_SCENES = 3

/** 넓은 → 좁은 순서. 씬을 나눌 때 뒤쪽 조각의 시선을 한 단계 좁힌다 */
const SHOT_NARROWING: Record<ShotType, ShotType> = {
  wide: 'medium',
  medium: 'close',
  close: 'extreme_close',
  extreme_close: 'extreme_close',
  insert: 'insert',
  text_card: 'text_card',
}

/**
 * 레퍼런스 씬 수를 내 영상 길이에 맞춘다.
 *
 * ⚠️ 앞에서 잘라내지 않는다 — 그러면 광고의 마무리(CTA)가 통째로 날아간다.
 *    첫 씬(훅)과 마지막 씬(마무리)은 병합·분할 대상에서 항상 제외한다.
 */
export function resampleHomageScenes(scenes: HomageScene[], targetCount: number): HomageScene[] {
  const target = Math.max(MIN_SCENES, targetCount)
  let work = scenes.map(s => ({ ...s }))

  // 입력이 목표보다 적으면 분할, 많으면 병합
  while (work.length > target && work.length > 1) {
    work = mergeShortestMiddle(work)
  }
  while (work.length < target) {
    work = splitLongest(work)
  }

  return work.map((s, i) => ({ ...s, seq: i + 1 }))
}

/** 가장 짧은 중간 씬을 이웃과 합친다. 같은 subjectRole 이웃을 우선한다 */
function mergeShortestMiddle(scenes: HomageScene[]): HomageScene[] {
  // 첫·마지막은 보호. 보호 대상만 남으면 어쩔 수 없이 마지막 직전을 쓴다
  const first = 1
  const last = scenes.length - 2
  let idx = first <= last ? first : Math.max(0, scenes.length - 2)
  for (let i = first; i <= last; i++) {
    if (scenes[i].durationSec < scenes[idx].durationSec) idx = i
  }

  const prev = scenes[idx - 1]
  const next = scenes[idx + 1]
  // 같은 역할의 이웃과 합치면 서사 단계가 덜 뭉개진다
  const mergeIntoPrev = !next || (prev && prev.subjectRole === scenes[idx].subjectRole)
  const targetIdx = mergeIntoPrev ? idx - 1 : idx + 1

  const out = scenes.map(s => ({ ...s }))
  out[targetIdx] = {
    ...out[targetIdx],
    durationSec: Math.round((out[targetIdx].durationSec + scenes[idx].durationSec) * 10) / 10,
  }
  out.splice(idx, 1)
  return out
}

/** 가장 긴 씬을 둘로 나눈다. 뒤 조각은 샷을 한 단계 좁힌다 */
function splitLongest(scenes: HomageScene[]): HomageScene[] {
  if (scenes.length === 0) {
    return [{
      seq: 1, durationSec: 3, shotType: 'medium', cameraMove: 'static',
      subjectRole: 'product', emotionBeat: '', transition: 'cut',
    }]
  }

  let idx = 0
  for (let i = 1; i < scenes.length; i++) {
    if (scenes[i].durationSec > scenes[idx].durationSec) idx = i
  }

  const src = scenes[idx]
  const half = Math.round((src.durationSec / 2) * 10) / 10
  const front: HomageScene = { ...src, durationSec: half }
  const back: HomageScene = {
    ...src,
    durationSec: Math.round((src.durationSec - half) * 10) / 10,
    shotType: SHOT_NARROWING[src.shotType],
    transition: 'cut',
  }

  const out = scenes.map(s => ({ ...s }))
  out.splice(idx, 1, front, back)
  return out
}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `npm test -- homageResampler storyboardGenerator`
Expected: PASS 16개. **회귀 테스트 4개가 반드시 통과해야 한다.**

- [ ] **Step 6: 전체 테스트와 빌드**

Run: `npm test && npx tsc -b`
Expected: 전부 PASS, 타입 에러 0.

- [ ] **Step 7: 커밋**

```bash
git add src/utils/homageResampler.ts src/utils/homageResampler.test.ts src/utils/storyboardGenerator.ts src/utils/storyboardGenerator.test.ts
git commit -m "feat(homage): 씬 수 정합 리샘플링 + buildSceneDurations 가중치"
```

---

## Task 6: youtubeSearch Cloud Function

**Files:**
- Modify: `functions/index.js` (파일 끝에 추가)
- Modify: `functions/.env` (`YOUTUBE_API_KEY` 자리 확보 — 값은 사용자가 채운다)

**Interfaces:**
- Consumes: 기존 `verifyBearer(req)`(`functions/index.js:292`), `cors`, `admin`
- Produces: `POST /youtubeSearch` — 두 가지 모드
  - `{ q: string }` → `200 { items: HomageCandidate[], cached: boolean }` (검색, 100유닛)
  - `{ videoId: string }` → `200 { videoId, title, channelTitle, thumbnailUrl, durationSec }` (단일 조회, 1유닛)
  - `401` 미로그인 · `400` 입력 없음/형식 오류 · `404` 영상 없음 · `429` 쿼터 소진 · `503` 키 미설정

- [ ] **Step 1: 함수 추가**

`functions/index.js` 끝에 추가한다. `corsProxy`(`:102`)와 동일한 `cors → method → verifyBearer` 순서를 지킨다.

```js
// ════════════════════════════════════════════════════════════════
// AdStudio 오마주: 유튜브 광고 검색
// ════════════════════════════════════════════════════════════════

/** 캐시 수명 7일 — 유튜브 약관이 캐시 데이터를 30일 내 갱신·삭제하도록 요구한다 */
const YT_CACHE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
/**
 * 한 번에 25개를 받아둔다. search.list 는 결과 개수와 무관하게 비용이 같으므로
 * (하루 약 100회 한도), 25개를 받아 5개씩 보여주면 "다른 후보 보기"가 공짜가 된다.
 */
const YT_MAX_RESULTS = 25;

/** 검색어 → 캐시 문서 id (Firestore 문서 id 제약을 피해 해시로 만든다) */
function ytCacheKey(q) {
  return require('crypto').createHash('sha1').update(q).digest('hex');
}

/** ISO8601 duration(PT1M30S) → 초. videos.list 가 이 형식으로 준다 */
function ytParseDuration(iso) {
  const m = /^P(?:\d+D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$/.exec(iso || '');
  if (!m) return 0;
  return (+(m[1] || 0)) * 3600 + (+(m[2] || 0)) * 60 + (+(m[3] || 0));
}

exports.youtubeSearch = functions.https.onRequest((req, res) => {
  return cors(req, res, async () => {
    if (req.method !== 'POST') return res.status(405).send('Method Not Allowed');

    const uid = await verifyBearer(req);
    if (!uid) return res.status(401).send('검색은 로그인 후 이용할 수 있어요.');

    const apiKey = process.env.YOUTUBE_API_KEY;
    if (!apiKey) return res.status(503).send('서버에 YouTube API 키가 설정되지 않았어요.');

    const fetchFn = (...args) => import('node-fetch').then(({ default: f }) => f(...args));

    // ── 모드 2: 단일 영상 정보 조회 (직접 URL 입력 검증용) ──
    // videos.list 는 1유닛이라 search.list(100유닛)와 달리 부담이 없다.
    // 사용자가 2시간짜리 영상을 붙여넣으면 Gemini 무료 한도(하루 8시간 분량)를
    // 한 번에 태우므로, 분석 전에 길이를 먼저 확인한다.
    const videoId = String((req.body || {}).videoId || '').trim();
    if (videoId) {
      if (!/^[A-Za-z0-9_-]{11}$/.test(videoId)) return res.status(400).send('영상 id 형식이 올바르지 않아요.');
      try {
        const r = await fetchFn('https://www.googleapis.com/youtube/v3/videos'
          + `?part=snippet,contentDetails&id=${videoId}&key=${apiKey}`);
        if (!r.ok) return res.status(502).send('영상 정보를 가져오지 못했어요.');
        const d = await r.json();
        const item = (d.items || [])[0];
        if (!item) return res.status(404).send('영상을 찾을 수 없어요. 공개 영상인지 확인해주세요.');
        return res.json({
          videoId,
          title: item.snippet.title,
          channelTitle: item.snippet.channelTitle,
          thumbnailUrl: (item.snippet.thumbnails.medium || item.snippet.thumbnails.default || {}).url || '',
          durationSec: ytParseDuration(item.contentDetails.duration),
        });
      } catch (e) {
        console.error('youtubeSearch(videoId) 실패:', e);
        return res.status(502).send('영상 정보를 가져오지 못했어요.');
      }
    }

    // ── 모드 1: 검색 ──
    const q = String((req.body || {}).q || '').trim();
    if (!q) return res.status(400).send('검색어가 필요해요.');

    const db = admin.firestore();
    const ref = db.collection('youtubeSearchCache').doc(ytCacheKey(q));

    try {
      const snap = await ref.get();
      if (snap.exists) {
        const data = snap.data();
        if (data.fetchedAt && Date.now() - data.fetchedAt < YT_CACHE_TTL_MS) {
          return res.json({ items: data.items || [], cached: true });
        }
      }
    } catch (e) {
      console.warn('youtubeSearch: 캐시 조회 실패, 원본 호출로 진행', e);
    }

    const url = 'https://www.googleapis.com/youtube/v3/search'
      + `?part=snippet&type=video&videoEmbeddable=true&maxResults=${YT_MAX_RESULTS}`
      + `&q=${encodeURIComponent(q)}&key=${apiKey}`;

    try {
      const r = await fetchFn(url);
      if (r.status === 403) {
        // 쿼터 소진과 키 문제가 둘 다 403 으로 온다. 본문으로 구분한다.
        const body = await r.text();
        if (/quota/i.test(body)) {
          return res.status(429).send('오늘 자동검색 한도를 다 썼어요.');
        }
        console.error('youtubeSearch: 403', body.slice(0, 300));
        return res.status(503).send('유튜브 검색을 사용할 수 없어요.');
      }
      if (!r.ok) {
        console.error('youtubeSearch: HTTP', r.status);
        return res.status(502).send('유튜브 검색에 실패했어요.');
      }

      const data = await r.json();
      const items = (data.items || [])
        .filter(it => it.id && it.id.videoId)
        .map(it => ({
          videoId: it.id.videoId,
          title: it.snippet.title,
          channelTitle: it.snippet.channelTitle,
          thumbnailUrl: (it.snippet.thumbnails.medium || it.snippet.thumbnails.default || {}).url || '',
          publishedAt: it.snippet.publishedAt,
        }));

      try {
        await ref.set({ q, items, fetchedAt: Date.now() });
      } catch (e) {
        console.warn('youtubeSearch: 캐시 저장 실패 (응답은 정상 반환)', e);
      }

      return res.json({ items, cached: false });
    } catch (e) {
      console.error('youtubeSearch 실패:', e);
      return res.status(502).send('유튜브 검색에 실패했어요.');
    }
  });
});
```

- [ ] **Step 2: functions/.env 에 키 자리 추가**

기존 내용은 지우지 말고 한 줄만 덧붙인다. 값은 사용자가 직접 채운다(§배포 노트 참조).

```
YOUTUBE_API_KEY=
```

- [ ] **Step 3: 문법 검사**

Run: `node --check functions/index.js`
Expected: 출력 없음(통과).

- [ ] **Step 4: 함수가 정상 로드되는지 확인**

Run: `npm run dev:emu`
Expected: 로그에 `youtubeSearch` 가 로드된 함수 목록에 나타난다. 확인 후 `Ctrl+C`.

> 에뮬레이터가 안 뜨면 Firestore 에뮬레이터에 JDK 가 필요하다. `--only functions` 로 좁혀 확인해도 된다: `npx firebase-tools emulators:start --project demo --only functions`

- [ ] **Step 5: 커밋**

`.env` 는 gitignore 대상이므로 스테이징되지 않는다. 정상이다.

```bash
git add functions/index.js
git commit -m "feat(homage): youtubeSearch 함수 — 공용 키 검색 + 7일 캐시"
```

---

## Task 7: 검색 호출 클라이언트

**Files:**
- Modify: `src/services/youtubeService.ts` (네트워크부 추가)
- Test: `src/services/youtubeService.test.ts` (테스트 추가)

**Interfaces:**
- Consumes: `fnUrl`(`src/services/firebaseTarget.ts`), `auth`(`src/services/firebase.ts`), Task 6 의 `POST /youtubeSearch`
- Produces:
  - `searchAdVideos(q: string): Promise<HomageCandidate[]>`
  - `class YoutubeQuotaError extends Error` — 호출부가 대체 입구로 유도할 때 구분용

- [ ] **Step 1: 실패하는 테스트 작성**

`src/services/youtubeService.test.ts` 에 추가한다.

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { searchAdVideos, YoutubeQuotaError } from './youtubeService'

vi.mock('./firebase', () => ({ auth: { currentUser: { getIdToken: async () => 'tok' } } }))
vi.mock('./firebaseTarget', () => ({ fnUrl: (n: string) => `https://fake/${n}` }))

describe('searchAdVideos', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
  afterEach(() => { vi.unstubAllGlobals() })

  it('결과 배열을 돌려준다', async () => {
    const items = [{ videoId: 'a'.repeat(11), title: 'T', channelTitle: 'C', thumbnailUrl: 'u', publishedAt: 'p' }]
    ;(fetch as any).mockResolvedValue({ ok: true, status: 200, json: async () => ({ items, cached: false }) })
    await expect(searchAdVideos('수분크림 광고')).resolves.toEqual(items)
  })

  it('Authorization 헤더에 ID 토큰을 싣는다', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, status: 200, json: async () => ({ items: [] }) })
    await searchAdVideos('x')
    const init = (fetch as any).mock.calls[0][1]
    expect(init.headers.Authorization).toBe('Bearer tok')
  })

  it('429 는 YoutubeQuotaError 로 구분한다', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 429, text: async () => '한도' })
    await expect(searchAdVideos('x')).rejects.toBeInstanceOf(YoutubeQuotaError)
  })

  it('빈 검색어는 호출 없이 빈 배열', async () => {
    await expect(searchAdVideos('  ')).resolves.toEqual([])
    expect(fetch).not.toHaveBeenCalled()
  })

  it('기타 오류는 일반 Error', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 502, text: async () => 'fail' })
    await expect(searchAdVideos('x')).rejects.toThrow(/검색/)
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `npm test -- youtubeService`
Expected: FAIL — `searchAdVideos` 없음.

- [ ] **Step 3: 구현**

`src/services/youtubeService.ts` 에 추가한다.

```ts
import { auth } from './firebase'
import { fnUrl } from './firebaseTarget'

/** 검색 쿼터 소진 — 호출부가 URL·글 입구로 유도하기 위해 따로 구분한다 */
export class YoutubeQuotaError extends Error {
  constructor(message = '오늘 자동검색 한도를 다 썼어요.') {
    super(message)
    this.name = 'YoutubeQuotaError'
  }
}

/** youtubeSearch 함수를 호출해 광고 후보를 받아온다 */
export async function searchAdVideos(q: string): Promise<HomageCandidate[]> {
  const query = (q || '').trim()
  if (!query) return []

  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  try {
    const token = await auth.currentUser?.getIdToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch { /* 토큰 발급 실패가 호출 자체를 막지는 않는다 — 서버가 401로 답한다 */ }

  const res = await fetch(fnUrl('youtubeSearch'), {
    method: 'POST',
    headers,
    body: JSON.stringify({ q: query }),
  })

  if (res.status === 429) throw new YoutubeQuotaError()
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(detail || '유튜브 검색에 실패했어요.')
  }

  const data = await res.json()
  return (data.items || []) as HomageCandidate[]
}

export interface YoutubeVideoInfo {
  videoId: string
  title: string
  channelTitle: string
  thumbnailUrl: string
  durationSec: number
}

/**
 * 단일 영상 정보(제목·길이)를 조회한다. 직접 URL 입력 시 분석 전에 부른다.
 * videos.list 는 1유닛이라 검색(100유닛)과 달리 자주 불러도 부담이 없다.
 */
export async function getVideoInfo(videoId: string): Promise<YoutubeVideoInfo> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  try {
    const token = await auth.currentUser?.getIdToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch { /* 서버가 401로 답한다 */ }

  const res = await fetch(fnUrl('youtubeSearch'), {
    method: 'POST',
    headers,
    body: JSON.stringify({ videoId }),
  })

  if (res.status === 404) throw new Error('영상을 찾을 수 없어요. 공개 영상인지 확인해주세요.')
  if (!res.ok) {
    const detail = await res.text().catch(() => '')
    throw new Error(detail || '영상 정보를 가져오지 못했어요.')
  }
  return (await res.json()) as YoutubeVideoInfo
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `npm test -- youtubeService`
Expected: PASS 24개 (기존 19 + 신규 5).

- [ ] **Step 5: 커밋**

```bash
git add src/services/youtubeService.ts src/services/youtubeService.test.ts
git commit -m "feat(homage): 검색 호출 클라이언트 + 쿼터 오류 구분"
```

---

## Task 8: homageAnalyzer — 영상·글 → 구조

**Files:**
- Create: `src/services/homageAnalyzer.ts`
- Test: `src/services/homageAnalyzer.test.ts`

**Interfaces:**
- Consumes: `callProxy` 패턴(`src/services/aiAdapters.ts:1272`), `geminiTextEndpoint`, `geminiText`, `KeyVault`(`src/stores/keysStore.ts`), `sanitizeHomageStructure`·`HOMAGE_JSON_SCHEMA_HINT`(Task 3)
- Produces:
  - `analyzeFromVideo(videoId: string): Promise<HomageStructure>`
  - `analyzeFromDescription(text: string): Promise<HomageStructure>`

> **선행 확인 필요.** Gemini 의 YouTube URL 입력 페이로드 형태가 문서상 두 가지로 보인다 — 클래식 `generateContent` 의 `fileData: { fileUri }` 와 신형 Interactions API 의 `{ type: 'video', uri }`. 이 앱은 `v1beta/models/*:generateContent` 를 쓰므로 **`fileData.fileUri` 로 구현**하고, Step 6 의 실호출 스모크로 확인한다. 실패하면 그 응답 본문을 보고 형태를 맞춘다.

- [ ] **Step 1: 실패하는 테스트 작성**

`src/services/homageAnalyzer.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'

const callProxy = vi.fn()
vi.mock('./aiAdapters', () => ({
  callProxy: (...a: unknown[]) => callProxy(...a),
  geminiTextEndpoint: async () => 'https://fake/gen',
  geminiText: (d: any) => d.text,
}))
vi.mock('../stores/keysStore', () => ({
  KeyVault: { getKey: async () => 'FAKE_KEY' },
  useKeysStore: { getState: () => ({ updateGeminiUsage: () => {} }) },
}))

import { analyzeFromVideo, analyzeFromDescription } from './homageAnalyzer'

const goodJson = JSON.stringify({
  scenes: [
    { seq: 1, durationSec: 3, shotType: 'wide', cameraMove: 'static', subjectRole: 'environment', emotionBeat: '평온', transition: 'cut' },
    { seq: 2, durationSec: 2, shotType: 'close', cameraMove: 'push_in', subjectRole: 'product', emotionBeat: '주목', transition: 'cut' },
    { seq: 3, durationSec: 3, shotType: 'medium', cameraMove: 'pan', subjectRole: 'person', emotionBeat: '해소', transition: 'dissolve' },
  ],
  pacing: 'fast',
  overallArc: '일상 → 주목 → 해소',
})

describe('analyzeFromVideo', () => {
  beforeEach(() => callProxy.mockReset())

  it('YouTube URL 을 fileData 로 실어 보낸다', async () => {
    callProxy.mockResolvedValue({ text: goodJson })
    await analyzeFromVideo('dQw4w9WgXcQ')
    const arg = callProxy.mock.calls[0][0]
    const parts = arg.body.contents[0].parts
    const filePart = parts.find((p: any) => p.fileData)
    expect(filePart.fileData.fileUri).toBe('https://www.youtube.com/watch?v=dQw4w9WgXcQ')
  })

  it('구조를 정제해 돌려준다', async () => {
    callProxy.mockResolvedValue({ text: goodJson })
    const out = await analyzeFromVideo('dQw4w9WgXcQ')
    expect(out.scenes).toHaveLength(3)
    expect(out.pacing).toBe('fast')
  })

  it('코드펜스로 감싼 JSON 도 파싱한다', async () => {
    callProxy.mockResolvedValue({ text: '```json\n' + goodJson + '\n```' })
    const out = await analyzeFromVideo('dQw4w9WgXcQ')
    expect(out.scenes).toHaveLength(3)
  })

  it('JSON 이 아니면 사용자용 오류를 던진다', async () => {
    callProxy.mockResolvedValue({ text: '분석할 수 없습니다' })
    await expect(analyzeFromVideo('dQw4w9WgXcQ')).rejects.toThrow(/분석하지 못했어요/)
  })

  it('videoId 형식이 틀리면 호출 전에 막는다', async () => {
    await expect(analyzeFromVideo('bad')).rejects.toThrow(/영상 주소/)
    expect(callProxy).not.toHaveBeenCalled()
  })

  it('첫 응답이 깨져도 1회 재시도해서 성공한다', async () => {
    callProxy.mockResolvedValueOnce({ text: '깨진 응답' })
             .mockResolvedValueOnce({ text: goodJson })
    const out = await analyzeFromVideo('dQw4w9WgXcQ')
    expect(out.scenes).toHaveLength(3)
    expect(callProxy).toHaveBeenCalledTimes(2)
  })

  it('두 번 다 실패하면 오류를 던진다 (3회째는 없다)', async () => {
    callProxy.mockResolvedValue({ text: '계속 깨짐' })
    await expect(analyzeFromVideo('dQw4w9WgXcQ')).rejects.toThrow()
    expect(callProxy).toHaveBeenCalledTimes(2)
  })
})

describe('analyzeFromDescription', () => {
  beforeEach(() => callProxy.mockReset())

  it('영상 파트 없이 텍스트만 보낸다', async () => {
    callProxy.mockResolvedValue({ text: goodJson })
    await analyzeFromDescription('훅으로 시작해서 조용히 끝난다')
    const parts = callProxy.mock.calls[0][0].body.contents[0].parts
    expect(parts.some((p: any) => p.fileData)).toBe(false)
    expect(parts[0].text).toContain('훅으로 시작해서')
  })

  it('영상 입구와 같은 스키마를 돌려준다', async () => {
    callProxy.mockResolvedValue({ text: goodJson })
    const out = await analyzeFromDescription('아무 설명')
    expect(out.scenes).toHaveLength(3)
    expect(out.overallArc).toBe('일상 → 주목 → 해소')
  })

  it('설명이 너무 짧으면 막는다', async () => {
    await expect(analyzeFromDescription('짧')).rejects.toThrow(/조금 더 자세히/)
    expect(callProxy).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `npm test -- homageAnalyzer`
Expected: FAIL — 모듈 없음.

- [ ] **Step 2-1: aiAdapters 의 세 헬퍼를 export 한다 (확인됨 — 현재 전부 비공개)**

`src/services/aiAdapters.ts` 의 세 줄에 `export` 키워드만 붙인다. 본문은 건드리지 않는다.

- `:72` `async function callProxy(` → `export async function callProxy(`
- `:244` `async function geminiTextEndpoint(` → `export async function geminiTextEndpoint(`
- `:260` `function geminiText(` → `export function geminiText(`

기존 호출부는 같은 파일 안에 있어 영향이 없다. `npx tsc -b` 로 확인한다.

- [ ] **Step 3: 구현**

`src/services/homageAnalyzer.ts`:

```ts
import { callProxy, geminiTextEndpoint, geminiText } from './aiAdapters'
import { KeyVault, useKeysStore } from '../stores/keysStore'
import { sanitizeHomageStructure, HOMAGE_JSON_SCHEMA_HINT } from './homageSchema'
import { parseYoutubeVideoId } from './youtubeService'
import type { HomageStructure } from '../types/homage'

const MIN_DESCRIPTION_LEN = 10

/** ```json 펜스나 앞뒤 잡소리를 걷어내고 JSON 본문만 남긴다 */
function extractJson(text: string): string {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/)
  const body = fenced ? fenced[1] : text
  const start = body.indexOf('{')
  const end = body.lastIndexOf('}')
  return start >= 0 && end > start ? body.slice(start, end + 1) : body
}

async function runGeminiOnce(parts: unknown[]): Promise<HomageStructure> {
  const apiKey = await KeyVault.getKey('gemini')
  if (!apiKey) throw new Error('Gemini 키가 필요해요. 키 페이지에서 등록해주세요.')

  const data = await callProxy({
    provider: 'gemini',
    apiKey,
    method: 'POST',
    endpoint: await geminiTextEndpoint(apiKey),
    body: {
      contents: [{ parts }],
      generationConfig: { responseMimeType: 'application/json' },
    },
  })
  useKeysStore.getState().updateGeminiUsage('text')

  const text = geminiText(data)
  if (!text) throw new Error(data?.error?.message || '오마주 구조를 분석하지 못했어요.')

  let parsed: unknown
  try {
    parsed = JSON.parse(extractJson(String(text)))
  } catch {
    throw new Error('오마주 구조를 분석하지 못했어요. 다른 영상을 골라보세요.')
  }
  return sanitizeHomageStructure(parsed)
}

/**
 * 1회 재시도한다. LLM 은 같은 입력에도 형식이 흔들려서, 한 번 더 물으면
 * 성공하는 경우가 많다. 두 번 다 실패하면 사용자에게 알리고 선택지를 준다
 * (조용히 템플릿으로 폴백하지 않는다 — 사용자가 명시적으로 고른 모드다).
 *
 * ⚠️ 키 없음처럼 재시도가 무의미한 오류는 즉시 던진다.
 */
async function runGemini(parts: unknown[]): Promise<HomageStructure> {
  try {
    return await runGeminiOnce(parts)
  } catch (e) {
    const msg = e instanceof Error ? e.message : ''
    if (/키가 필요해요/.test(msg)) throw e
    return await runGeminiOnce(parts)
  }
}

const VIDEO_INSTRUCTION = `
You are analyzing a video advertisement to extract its STRUCTURAL grammar so that a
different product's ad can borrow its rhythm — an homage, not a copy.

Break the ad into its shots. For each shot report only: duration, shot size,
camera movement, what kind of subject fills the frame, the emotional beat it lands,
and how it transitions out.

${HOMAGE_JSON_SCHEMA_HINT}
`.trim()

const DESCRIPTION_INSTRUCTION = `
A user is describing the FEELING and RHYTHM they want for their ad. Turn that
description into a concrete shot structure they can build from.

Infer a sensible number of shots (3-12) from what they describe. If they mention
specific timing ("first 3 seconds", "last 5 seconds"), honor it.

${HOMAGE_JSON_SCHEMA_HINT}
`.trim()

/**
 * 유튜브 영상을 직접 분석해 구조를 뽑는다.
 * Gemini 는 YouTube URL 을 영상 입력으로 직접 받는다(공개 영상만 가능).
 */
export async function analyzeFromVideo(videoId: string): Promise<HomageStructure> {
  const id = parseYoutubeVideoId(videoId)
  if (!id) throw new Error('영상 주소를 알아보지 못했어요.')

  return runGemini([
    { text: VIDEO_INSTRUCTION },
    { fileData: { fileUri: `https://www.youtube.com/watch?v=${id}` } },
  ])
}

/**
 * 원하는 느낌을 글로 적은 것을 같은 구조로 변환한다.
 * 유튜브에 참고할 광고가 없을 때의 입구이며, 영상 입구와 출력 계약이 동일하다.
 */
export async function analyzeFromDescription(text: string): Promise<HomageStructure> {
  const desc = (text || '').trim()
  if (desc.length < MIN_DESCRIPTION_LEN) {
    throw new Error('원하는 느낌을 조금 더 자세히 적어주세요.')
  }
  return runGemini([{ text: `${DESCRIPTION_INSTRUCTION}\n\n---\n사용자 설명:\n${desc}` }])
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `npm test -- homageAnalyzer`
Expected: PASS 8개.

- [ ] **Step 5: 전체 테스트·타입 검사**

Run: `npm test && npx tsc -b`
Expected: 전부 PASS, 타입 에러 0.

- [ ] **Step 6: 실제 Gemini 로 페이로드 형태 확인 (수동 스모크)**

`npm run dev` 로 앱을 띄우고 키 페이지에서 Gemini 키를 등록한 뒤, 브라우저 콘솔에서:

```js
const m = await import('/src/services/homageAnalyzer.ts')
await m.analyzeFromVideo('dQw4w9WgXcQ')   // 아무 공개 광고 영상 id 로 교체
```

Expected: `{scenes: [...], pacing, overallArc}` 반환.
실패하면 응답 본문의 오류 메시지를 보고 `fileData.fileUri` 형태를 조정한다.

- [ ] **Step 7: 커밋**

```bash
git add src/services/homageAnalyzer.ts src/services/homageAnalyzer.test.ts src/services/aiAdapters.ts
git commit -m "feat(homage): 영상·글 두 입구를 같은 구조로 수렴시키는 분석기"
```

---

## Task 9: storyboardGenerator 통합

**Files:**
- Modify: `src/utils/storyboardGenerator.ts:1824` (씬 풀 선택)
- Modify: `src/utils/storyboardGenerator.ts:1871-1872` (Gemini 에 넘길 구성 설명)

**Interfaces:**
- Consumes: `resampleHomageScenes`(Task 5), `buildSceneDurations(_, _, weights)`(Task 5), `useAdStore().adConcept`(Task 2)
- Produces: 없음 (기존 `generateStoryboardScenes` 동작 확장)

- [ ] **Step 1: import 추가**

`src/utils/storyboardGenerator.ts` 상단:

```ts
import { resampleHomageScenes } from './homageResampler'
import { HOMAGE_STRUCTURE_ID } from '../types/homage'
```

- [ ] **Step 2: 씬 풀 선택 분기 (`:1824` 부근)**

`const pool = ...` 줄 **앞에** `adState` 를 끌어오고(현재는 `:1851` 에서 가져온다), 분기를 넣는다.

```ts
  // 오마주 모드면 레퍼런스에서 뽑은 구조를 씬 뼈대로 쓴다.
  // ⚠️ homage 인데 structure 가 없으면 조용히 DEFAULT_CONCEPT_TEMPLATE 으로 흘러가면 안 된다 —
  //    사용자가 명시적으로 고른 모드라 템플릿으로 바꿔치기하면 "왜 내가 고른 영상 느낌이 안 나지"가 된다.
  const adStateEarly = useAdStore.getState()
  const isHomage = adStateEarly.adConcept?.structureSource === 'homage'
  const homageStructure = adStateEarly.adConcept?.homage?.structure

  if (isHomage && !homageStructure) {
    throw new Error('오마주 구조가 없어요. 레퍼런스를 다시 선택해주세요.')
  }

  // 1. 해당 컨셉 아이디의 템플릿 풀 가져오기 — 광고 구성(ad_*)은 adConcepts의 광고 템플릿 뱅크에서
  const pool = CONCEPT_TEMPLATES[conceptId] || AD_CONCEPT_TEMPLATES[conceptId] || DEFAULT_CONCEPT_TEMPLATE
```

- [ ] **Step 3: 씬 개수·길이 계산 분기 (`:1826-1830` 교체)**

```ts
  // 2. 요청된 영상 길이에 맞춰 필요한 씬 개수를 정하고(최소 3개), 풀 크기 안으로 자른다
  const desiredCount = Math.max(3, Math.round(durationSec / SCENE_SEC_TARGET))

  let sceneCount: number
  let chosen: typeof pool
  let durations: number[]

  if (isHomage && homageStructure) {
    // 레퍼런스 씬 수를 목표에 맞춰 리샘플링하고, 그 상대 길이를 가중치로 넘긴다.
    // 균등 분배하면 오마주의 핵심인 완급이 사라진다.
    const homageScenes = resampleHomageScenes(homageStructure.scenes, desiredCount)
    sceneCount = homageScenes.length
    // 텍스트 뼈대는 템플릿 풀에서 빌려오되(길이만 맞춤), 실제 내용은 아래 Gemini 창작으로 덮인다
    chosen = Array.from({ length: sceneCount }, (_, i) => pool[i % pool.length])
    durations = buildSceneDurations(durationSec, sceneCount, homageScenes.map(s => s.durationSec))
  } else {
    sceneCount = Math.min(desiredCount, pool.length)
    chosen = pool.slice(0, sceneCount)
    durations = buildSceneDurations(durationSec, chosen.length)
  }
```

- [ ] **Step 4: Gemini 에 넘길 구성 설명 분기 (`:1871-1872` 교체)**

```ts
                structureLabel: isHomage
                  ? '레퍼런스 오마주'
                  : (AD_STRUCTURES.find(s => s.id === conceptId)?.label || conceptId),
                structureFlow: isHomage && homageStructure
                  ? buildHomageFlowText(homageStructure, resampleHomageScenes(homageStructure.scenes, sceneCount))
                  : (AD_STRUCTURES.find(s => s.id === conceptId)?.flow || ''),
```

- [ ] **Step 5: flow 텍스트 헬퍼 추가**

`generateStoryboardScenes` 위에 추가한다.

```ts
/**
 * 오마주 구조를 Gemini 프롬프트용 한 줄 흐름 설명으로 바꾼다.
 *
 * ⚠️ 여기에 원본 대사를 넣지 않는다 — HomageStructure 에 애초에 그런 필드가 없다.
 *    샷 문법과 감정 단계만 전달하고, 실제 대사는 제품 분석 결과에서 창작된다.
 */
function buildHomageFlowText(structure: HomageStructure, scenes: HomageScene[]): string {
  const beats = scenes
    .map((s, i) => `${i + 1}) ${s.shotType}/${s.cameraMove} · ${s.subjectRole} · ${s.emotionBeat || '-'}`)
    .join('  →  ')
  return `[${structure.pacing} 페이싱] ${structure.overallArc}\n${beats}`
}
```

상단 import 에 타입을 추가한다:

```ts
import type { HomageStructure, HomageScene } from '../types/homage'
```

- [ ] **Step 6: 회귀 테스트 재확인 — 가장 중요한 단계**

Run: `npm test && npx tsc -b && npm run build`
Expected: 전부 PASS, 타입 에러 0, 빌드 성공.

- [ ] **Step 7: 커밋**

```bash
git add src/utils/storyboardGenerator.ts
git commit -m "feat(homage): 스토리보드 생성기에 오마주 구조 분기 연결"
```

---

## Task 10: A5b 레퍼런스 선택 화면

**Files:**
- Create: `src/pages/A5b_Reference.tsx`

**Interfaces:**
- Consumes: `searchAdVideos`·`buildSearchQuery`·`parseYoutubeVideoId`·`YoutubeQuotaError`(Task 4,7), `analyzeFromVideo`·`analyzeFromDescription`(Task 8), `useAdStore`(Task 2), `AD_CATEGORIES`(`src/utils/adConcepts.ts`)
- Produces: `/reference` 화면. 확정 시 `setAdConcept({ structureSource: 'homage', structureId: HOMAGE_STRUCTURE_ID, homage })` 후 `/concept` 으로 복귀

- [ ] **Step 1: 페이지 작성**

`src/pages/A5b_Reference.tsx`:

```tsx
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Link2, PenLine, AlertCircle, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { useAdStore } from '../stores/adStore'
import { AD_CATEGORIES } from '../utils/adConcepts'
import {
  buildSearchQuery, parseYoutubeVideoId, searchAdVideos, getVideoInfo, YoutubeQuotaError,
} from '../services/youtubeService'
import { analyzeFromVideo, analyzeFromDescription } from '../services/homageAnalyzer'
import { HOMAGE_STRUCTURE_ID } from '../types/homage'
import type { HomageCandidate } from '../types/homage'

const PAGE_SIZE = 5
/** 레퍼런스 영상 길이 상한 — 광고는 대개 1분 이내라 10분이면 충분히 여유롭다 */
const MAX_REFERENCE_SEC = 600

type Tab = 'search' | 'url' | 'describe'

/**
 * [5b] 레퍼런스 선택 — 입구 3개가 모두 같은 HomageStructure 로 수렴한다.
 *
 * 검색만이 입구가 아니다. 원하는 광고가 유튜브에 없는 경우가 흔해서
 * URL 직접 입력과 글로 설명하기를 대등한 탭으로 둔다.
 */
export default function A5b_Reference() {
  const navigate = useNavigate()
  const { analysis, adConcept, setAdConcept } = useAdStore()

  const subLabel = AD_CATEGORIES
    .find(c => c.id === adConcept.categoryMain)?.subs
    ?.find(s => s.id === adConcept.categorySub)?.label ?? ''

  // 제품군은 productName 의 마지막 낱말로 어림잡는다 ("미리집 수분크림" → "수분크림").
  //
  // ⚠️ 스펙 §6-1 은 Gemini 로 일반명사를 추출하라고 했으나, 여기서는 휴리스틱을 쓴다.
  //    이유: 조립 결과가 편집 가능한 입력창에 그대로 노출되므로, 빗나가도 사용자가
  //    한 번에 고칠 수 있다. 첫 화면을 띄우는 데 LLM 왕복을 넣으면 체감 지연만 생긴다.
  //    한국어 상품명은 "브랜드 + 제품군" 어순이 지배적이라 마지막 낱말이 대체로 맞는다.
  //    실사용에서 빗나가는 비율이 높으면 그때 Gemini 추출로 승격한다.
  const guessedType = (analysis?.productName || '').trim().split(/\s+/).pop() || ''

  const [tab, setTab] = useState<Tab>('search')
  const [query, setQuery] = useState(buildSearchQuery(guessedType, subLabel))
  const [candidates, setCandidates] = useState<HomageCandidate[]>([])
  const [shown, setShown] = useState(PAGE_SIZE)
  const [urlInput, setUrlInput] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const runSearch = async () => {
    setError(''); setNotice(''); setBusy(true); setShown(PAGE_SIZE)
    try {
      const items = await searchAdVideos(query)
      setCandidates(items)
      if (items.length === 0) setNotice('결과가 없어요. 검색어를 바꾸거나 URL·설명으로 진행해보세요.')
    } catch (e) {
      if (e instanceof YoutubeQuotaError) {
        setNotice('오늘 자동검색 한도를 다 썼어요. URL 붙여넣기나 직접 설명으로 진행하세요.')
        setTab('url')
      } else {
        setError(e instanceof Error ? e.message : '검색에 실패했어요.')
      }
    } finally { setBusy(false) }
  }

  /** 세 입구가 공통으로 쓰는 확정 경로 */
  const commit = async (build: () => Promise<Parameters<typeof setAdConcept>[0]>) => {
    setError(''); setBusy(true)
    try {
      const patch = await build()
      setAdConcept({ structureSource: 'homage', structureId: HOMAGE_STRUCTURE_ID, ...patch })
      navigate('/concept')
    } catch (e) {
      setError(e instanceof Error ? e.message : '분석에 실패했어요.')
    } finally { setBusy(false) }
  }

  const pickVideo = (c: HomageCandidate) => commit(async () => ({
    homage: {
      source: 'search' as const,
      videoId: c.videoId, title: c.title, channelTitle: c.channelTitle,
      thumbnailUrl: c.thumbnailUrl,
      structure: await analyzeFromVideo(c.videoId),
      analyzedAt: Date.now(),
    },
  }))

  const useUrl = () => commit(async () => {
    const id = parseYoutubeVideoId(urlInput)
    if (!id) throw new Error('유튜브 주소를 확인해주세요.')

    // 분석 전에 길이를 먼저 본다 — 2시간짜리를 넣으면 Gemini 무료 한도
    // (하루 8시간 분량)를 한 번에 태운다. 1유닛짜리 조회라 부담이 없다.
    const info = await getVideoInfo(id)
    if (info.durationSec > MAX_REFERENCE_SEC) {
      throw new Error(
        `${Math.round(info.durationSec / 60)}분짜리 영상이에요. `
        + `${MAX_REFERENCE_SEC / 60}분 이하의 광고 영상을 골라주세요.`,
      )
    }

    return {
      homage: {
        source: 'url' as const,
        videoId: id,
        title: info.title,
        channelTitle: info.channelTitle,
        thumbnailUrl: info.thumbnailUrl,
        durationSec: info.durationSec,
        structure: await analyzeFromVideo(id),
        analyzedAt: Date.now(),
      },
    }
  })

  const useDescription = () => commit(async () => ({
    homage: {
      source: 'description' as const,
      userDescription: description,
      structure: await analyzeFromDescription(description),
      analyzedAt: Date.now(),
    },
  }))

  const backToTemplate = () => {
    setAdConcept({ structureSource: 'template', structureId: '', homage: undefined })
    navigate('/concept')
  }

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
        참고할 광고의 <strong>컷 순서와 완급</strong>을 가져옵니다.
        컷 길이는 영상 생성 한계에 맞춰 조정됩니다.
      </p>

      <div style={{ display: 'flex', gap: 8 }}>
        {([['search', '검색으로 찾기', Search], ['url', 'URL 넣기', Link2], ['describe', '글로 설명', PenLine]] as const)
          .map(([id, label, Icon]) => (
            <button key={id} onClick={() => { setTab(id); setError(''); }}
              className={clsx('btn btn-sm', tab === id ? 'btn-primary' : 'btn-outline')}>
              <Icon size={14} /> {label}
            </button>
          ))}
      </div>

      {tab === 'search' && (
        <>
          <div style={{ display: 'flex', gap: 8 }}>
            <input value={query} onChange={e => setQuery(e.target.value)}
              placeholder="예: 수분크림 화장품 광고" style={{ flex: 1 }}
              onKeyDown={e => { if (e.key === 'Enter') runSearch() }} />
            <button className="btn btn-primary" onClick={runSearch} disabled={busy || !query.trim()}>
              {busy ? <Loader2 size={14} className="spin" /> : '검색'}
            </button>
          </div>

          {candidates.slice(0, shown).map(c => (
            <button key={c.videoId} onClick={() => pickVideo(c)} disabled={busy}
              style={{ display: 'flex', gap: 12, textAlign: 'left', background: 'var(--color-bg-card)',
                       border: '1px solid var(--color-border)', borderRadius: 8, padding: 8 }}>
              <img src={c.thumbnailUrl} alt="" width={120} style={{ borderRadius: 4 }} />
              <span>
                <span style={{ display: 'block', fontWeight: 600, fontSize: 14 }}>{c.title}</span>
                <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>{c.channelTitle}</span>
              </span>
            </button>
          ))}

          {shown < candidates.length && (
            <button className="btn btn-outline" onClick={() => setShown(s => s + PAGE_SIZE)}>
              다른 후보 보기 ({candidates.length - shown}개 남음)
            </button>
          )}
        </>
      )}

      {tab === 'url' && (
        <>
          <input value={urlInput} onChange={e => setUrlInput(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..." />
          <button className="btn btn-primary" onClick={useUrl} disabled={busy || !urlInput.trim()}>
            {busy ? '분석 중…' : '이 영상으로 진행'}
          </button>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>공개 영상만 분석할 수 있어요.</p>
        </>
      )}

      {tab === 'describe' && (
        <>
          <textarea value={description} onChange={e => setDescription(e.target.value)} rows={5}
            placeholder="예: 첫 3초에 문제 상황을 훅으로 던지고, 중간에 제품 클로즈업을 빠르게 몰아친 다음, 마지막 5초는 조용하게 브랜드 한 컷으로 마무리" />
          <button className="btn btn-primary" onClick={useDescription} disabled={busy || description.trim().length < 10}>
            {busy ? '구성 만드는 중…' : '이 느낌으로 진행'}
          </button>
        </>
      )}

      {notice && <p style={{ fontSize: 13 }}>{notice}</p>}
      {error && (
        <p style={{ color: 'var(--color-danger)', fontSize: 13, display: 'flex', gap: 6 }}>
          <AlertCircle size={16} /> {error}
        </p>
      )}

      <button className="btn btn-outline" onClick={backToTemplate}>그냥 템플릿에서 고르기</button>
    </div>
  )
}
```

- [ ] **Step 2: 타입 검사**

Run: `npx tsc -b`
Expected: 에러 0.

> `AD_CATEGORIES` 는 `{ id, emoji, label, subs: [{ id, label }] }` 구조다(`src/utils/adConcepts.ts:17-25` 확인 완료). 위 코드의 `.subs?.find(s => s.id === ...)?.label` 이 그대로 맞는다.

- [ ] **Step 3: 커밋**

```bash
git add src/pages/A5b_Reference.tsx
git commit -m "feat(homage): 레퍼런스 선택 화면 — 검색·URL·설명 3입구"
```

---

## Task 11: A5 모드 분기와 라우트 연결

**Files:**
- Modify: `src/pages/A5_Concept.tsx` (스토리 구성 영역에 탭 추가)
- Modify: `src/App.tsx` (`/reference` 라우트)

**Interfaces:**
- Consumes: Task 10 의 `A5b_Reference`, Task 2 의 `structureSource`
- Produces: 사용자가 오마주 모드에 도달할 수 있는 경로

- [ ] **Step 1: 라우트 추가**

`src/App.tsx` 의 `/concept` 라우트(`:154-156`) 바로 아래에 추가한다.

```tsx
      <Route element={<AppShell headerProps={{ showBack: true, title: '레퍼런스 선택' }} hideBottomNav />}>
        <Route path="/reference" element={<A5bReference />} />
      </Route>
```

상단 import 에 추가:

```tsx
import A5bReference from './pages/A5b_Reference'
```

- [ ] **Step 2: A5_Concept 에 모드 선택 UI 추가**

`src/pages/A5_Concept.tsx` 의 "스토리 구성" 목록(`:179` 부근) **위에** 삽입한다.

```tsx
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <button
          className={clsx('btn btn-sm', adConcept.structureSource !== 'homage' ? 'btn-primary' : 'btn-outline')}
          onClick={() => setAdConcept({ structureSource: 'template', homage: undefined, structureId: '' })}
        >
          템플릿에서 고르기
        </button>
        <button
          className={clsx('btn btn-sm', adConcept.structureSource === 'homage' ? 'btn-primary' : 'btn-outline')}
          onClick={() => navigate('/reference')}
        >
          유튜브 오마주
        </button>
      </div>

      {adConcept.structureSource === 'homage' && adConcept.homage && (
        <div style={{ padding: 12, borderRadius: 8, background: 'rgba(124,58,255,0.10)', marginBottom: 12 }}>
          <strong style={{ fontSize: 13 }}>
            {adConcept.homage.title || (adConcept.homage.source === 'description' ? '내가 설명한 느낌' : '선택한 영상')}
          </strong>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
            {adConcept.homage.structure.scenes.length}씬 · {adConcept.homage.structure.pacing} 페이싱
            {adConcept.homage.structure.overallArc ? ` · ${adConcept.homage.structure.overallArc}` : ''}
          </p>
          <button className="btn btn-sm btn-outline" style={{ marginTop: 8 }} onClick={() => navigate('/reference')}>
            레퍼런스 바꾸기
          </button>
        </div>
      )}
```

- [ ] **Step 3: 템플릿 목록을 오마주 모드에서 숨긴다**

`A5_Concept.tsx:179` 의 `onClick={() => setAdConcept({ structureId: s.id })}` 가 들어 있는
`AD_STRUCTURES.map(...)` 블록 **전체**를 찾아, 그 JSX 표현식을 조건부로 감싼다.
`{AD_STRUCTURES.map(` 로 시작해 그 map 의 닫는 `)}` 까지가 대상이다.

```tsx
      {adConcept.structureSource !== 'homage' && AD_STRUCTURES.map(s => (
        /* ... 기존 map 콜백 본문을 그대로 둔다 ... */
      ))}
```

즉 `{AD_STRUCTURES.map(` 를 `{adConcept.structureSource !== 'homage' && AD_STRUCTURES.map(` 로
바꾸는 한 줄 수정이다. 콜백 본문과 닫는 괄호는 손대지 않는다.

- [ ] **Step 4: 타입 검사·빌드**

Run: `npx tsc -b && npm run build`
Expected: 에러 0.

- [ ] **Step 5: 커밋**

```bash
git add src/pages/A5_Concept.tsx src/App.tsx
git commit -m "feat(homage): A5 모드 분기와 /reference 라우트 연결"
```

---

## Task 12: 통합 검증

**Files:** 없음 (검증만)

- [ ] **Step 1: 전체 자동 테스트**

Run: `npm test`
Expected: 전부 PASS.

- [ ] **Step 2: 회귀 — 기존 사용자 상태 복원 확인**

`npm run dev` 후 브라우저 콘솔에서:

```js
// persist 된 기존 상태에는 structureSource 가 없다 → undefined
// (실제 zustand persist 키는 'adstudio-ad' — src/stores/adStore.ts 의 `name` 필드)
const s = JSON.parse(localStorage.getItem('adstudio-ad') || '{}')
console.log(s?.state?.adConcept?.structureSource)   // undefined 또는 'template' 둘 다 정상
```

Expected: `undefined` 여도 이후 흐름이 템플릿 경로로 정상 동작한다(Task 9 의 분기가 `=== 'homage'` 판정이므로).

- [ ] **Step 3: 템플릿 모드 E2E — 기존 동작이 그대로인지**

자료 업로드 → 분석 → 설정 → 배우 → **템플릿에서 고르기** → 스토리보드 생성.
Expected: 도입 전과 동일하게 씬이 생성된다.

- [ ] **Step 4: 오마주 모드 E2E — 검색 입구**

A5 에서 "유튜브 오마주" → 검색 → 후보 선택 → 분석 → 스토리보드.
Expected: 씬 수와 완급이 레퍼런스를 반영한다. A5 에 레퍼런스 요약 카드가 보인다.

- [ ] **Step 5: 오마주 모드 E2E — 나머지 두 입구**

URL 직접 입력, 글로 설명 각각으로 스토리보드까지 도달하는지 확인한다.
Expected: 세 입구 모두 동일하게 스토리보드가 생성된다.

- [ ] **Step 6: 저작권 가드레일 실검증**

대사가 뚜렷한 광고를 하나 골라 분석한 뒤 콘솔에서:

```js
const s = JSON.parse(localStorage.getItem('adstudio-ad')).state.adConcept.homage.structure
console.log(JSON.stringify(s))
```

Expected: 원본 대사·자막 문구·브랜드명이 **하나도 들어 있지 않다**. `emotionBeat` 은 전부 40자 이하.

- [ ] **Step 7: 탈출로 확인**

레퍼런스 화면에서 "그냥 템플릿에서 고르기" → A5 로 복귀 후 템플릿 목록이 다시 보이고 정상 진행되는지.
Expected: 오마주 상태가 깨끗이 지워진다.

- [ ] **Step 8: 커밋**

```bash
git commit --allow-empty -m "test(homage): 통합 검증 완료 — 회귀·3입구·가드레일"
```

---

## 배포 노트 (구현 범위 밖)

`youtubeSearch` 함수는 **이 저장소에서 배포할 수 없다** — `deploy-guard.cjs` 가 `headjim-ai` 배포를 차단한다(의도된 설계). 운영 반영 절차:

1. Google Cloud Console 에서 **YouTube Data API v3** 를 활성화하고 API 키를 발급한다.
2. 운영 저장소 `D:\광고영상-AdStudio` 의 `functions/.env` 에 `YOUTUBE_API_KEY=...` 를 넣는다.
3. 이 저장소의 `youtubeSearch` 코드를 운영 저장소 `functions/index.js` 로 옮긴다.
4. 운영 저장소에서 `firebase deploy --only functions:youtubeSearch` 로 **함수 하나만** 배포한다.
   `--only functions` (전체)는 절대 쓰지 않는다 — 라이브 5개 함수를 덮어쓴다.

`firestore.rules` 에 `youtubeSearchCache` 규칙은 **불필요하다**. 이 컬렉션은 Admin SDK(Cloud Function)로만 읽고 쓰며, 클라이언트가 직접 접근하지 않는다. 기본 거부가 올바른 상태다.
