import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import type { HomageScene, HomageStructure, HomageReference } from '../types/homage'
import type { Project } from '../types'
import type { AdConceptSelection, AdAnalysis, AdConfig, AiActorProfile } from '../stores/adStore'

// storyboardGenerator.ts 는 keysStore.ts/aiAdapters.ts 를 거쳐 services/firebase.ts 를 끌어오는데,
// 그 파일은 모듈 최상단에서 initializeApp/initializeAppCheck(reCAPTCHA, DOM 필요)를 실제로 실행하고,
// keysStore.ts 도 모듈 최상단에서 firebase/auth 의 onAuthStateChanged 를 실제 auth 인스턴스로 호출한다.
// 이 테스트가 검증하려는 건 순수 함수 buildSceneDurations 뿐이라 실제 Firebase 초기화가 전혀
// 필요 없고, 이 프로젝트의 vitest 기본 환경은 node 라 jsdom 도 없다(jsdom 패키지 미설치, jsdom 환경
// 지시자를 못 씀). 그래서 두 모듈을 통째로 목(mock)으로 바꿔 초기화 자체가 안 일어나게 한다.
vi.mock('../services/firebase', () => ({
  auth: {}, db: {}, googleProvider: {},
  signInWithPopup: async () => { throw new Error('not mocked for this test') },
  signOut: async () => {}, GoogleAuthProvider: class {},
  doc: () => {}, setDoc: async () => {}, getDoc: async () => {},
  collection: () => {}, query: () => {}, where: () => {}, getDocs: async () => {}, onSnapshot: () => () => {},
}))
vi.mock('firebase/auth', () => ({ onAuthStateChanged: () => () => {} }))

// 아래 3개 모듈도 같은 이유(무거운 초기화·indexedDB 등 node 환경에 없는 브라우저 API)로 통째로
// 목(mock)한다. 특히 KeyVault.getKey 는 실제로는 indexedDB 를 열어서(openDB) 값을 읽는데, node
// 환경엔 indexedDB 자체가 없어 실제 구현을 부르면 무조건 실패한다 — generateStoryboardScenes 를
// 실제로 호출해서 테스트하려면 이 세 지점을 반드시 목으로 대체해야 한다.
const mockGetKey = vi.hoisted(() => vi.fn<(provider: string) => Promise<string | null>>())
vi.mock('../stores/keysStore', () => ({
  KeyVault: { getKey: mockGetKey },
}))

const mockGenerateAdStoryboardScenes = vi.hoisted(() => vi.fn())
const mockGenerateStoryboardScenesLLM = vi.hoisted(() => vi.fn())
vi.mock('../services/aiAdapters', () => ({
  GeminiAdapter: {
    generateAdStoryboardScenes: mockGenerateAdStoryboardScenes,
    generateStoryboardScenes: mockGenerateStoryboardScenesLLM,
  },
}))

// adStore 는 진짜 zustand persist(localStorage) 스토어라 node 환경에서의 동작이 불확실하다 —
// 테스트마다 결정론적으로 상태를 갈아끼우기 위해 getState() 만 흉내 낸 얇은 목으로 대체한다.
const mockAdState = vi.hoisted(() => ({ current: {} as Record<string, unknown> }))
vi.mock('../stores/adStore', () => ({
  useAdStore: { getState: () => mockAdState.current },
}))

// firebaseTarget.ts 는 위 목과 무관하게 aiAdapters.ts 가 직접 임포트하며, 모듈 최상단에서
// window.location.hostname 을 읽는다 — node 환경엔 window 가 없으므로 최소 스텁을 채운다.
// 정적 import 는 다른 모든 코드보다 먼저 끌어올려져 스텁이 무의미해지므로, 동적 import 로 미룬다.
let buildSceneDurations: (durationSec: number, sceneCount: number, weights?: number[]) => number[]
let generateStoryboardScenes: (project: Project, persons: import('../types').Person[]) => Promise<import('../types').Scene[]>
let buildHomageFallbackScene: (scene: HomageScene, index: number) => { descKo: string; dialogueKo: string; keyframePromptEn: string; motionPromptEn: string }

beforeAll(async () => {
  const g = globalThis as { window?: unknown }
  g.window ??= { location: { hostname: 'localhost' } }
  ;({ buildSceneDurations, generateStoryboardScenes, buildHomageFallbackScene } = await import('./storyboardGenerator'))
})

describe('buildSceneDurations 회귀', () => {
  // 이 함수는 (durationSec, sceneCount) 만으로 완전히 결정론적이다. 합계·개수만 비교하면
  // remainder 분배 순서나 HARD_MAX 흡수 순서가 나중에 바뀌어도 우연히 통과할 수 있으므로,
  // 배열 자체를 비교한다. 기대 배열은 추측이 아니라 현재(수정 전과 바이트 단위로 동일한)
  // 구현을 실제로 실행해서 얻은 값이다.
  it.each([
    [15, 5, [3, 3, 3, 3, 3]],
    [30, 10, [3, 3, 3, 3, 3, 3, 3, 3, 3, 3]],
    [60, 20, [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3]],
    // 씬당 최대 4초(SCENE_SEC_SOFT_MAX) 클램프로 1단계에서 못 채운 나머지는
    // 2단계에서 SCENE_SEC_HARD_MAX(6초)까지 흡수한다 — 이 기존 안전장치 때문에
    // 15초/3씬은 12초로 줄지 않고 15초 그대로 유지된다.
    [15, 3, [6, 5, 4]],
  ])('weights 없이 호출하면 기존 동작을 유지한다 (%i초 %i씬)', (dur, count, expected) => {
    const out = buildSceneDurations(dur, count)
    expect(out).toEqual(expected)
    expect(out.reduce((a, b) => a + b, 0)).toBe(expected.reduce((a, b) => a + b, 0))
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

// ── Task 9 리뷰 Critical 회귀 테스트 ──────────────────────────────────
// 배경: HOMAGE_STRUCTURE_ID('ad_homage')는 AD_CONCEPT_TEMPLATES에 의도적으로 미등록이라, 오마주
// 모드의 씬 풀(pool)은 항상 DEFAULT_CONCEPT_TEMPLATE(개인 영상용 로맨틱 커플 대사, 예:
// "기억해줘, 우리의 시간.")로 귀결된다. Gemini 각본 생성이 (키 없음/실패/형식 불일치로) 조용히
// 폴백하던 기존 로직 그대로였다면, 이 로맨틱 대사가 아무 제품과 무관하게 최종 영상에 그대로
// 노출됐을 것이다. 이 회귀를 두 겹으로 막는다 — (1) 오마주 모드는 Gemini 실패 시 조용히 넘어가지
// 않고 명시적으로 예외를 던진다, (2) 혹시 새더라도 폴백 초기값 자체가 로맨틱 문구를 담지 않는다.

const HOMAGE_SCENES_FIXTURE: HomageScene[] = [
  { seq: 1, durationSec: 3, shotType: 'wide', cameraMove: 'static', subjectRole: 'environment', emotionBeat: '도입', transition: 'cut' },
  { seq: 2, durationSec: 3, shotType: 'medium', cameraMove: 'push_in', subjectRole: 'product', emotionBeat: '고조', transition: 'cut' },
  { seq: 3, durationSec: 3, shotType: 'close', cameraMove: 'static', subjectRole: 'product', emotionBeat: '마무리', transition: 'cut' },
]

const HOMAGE_STRUCTURE_FIXTURE: HomageStructure = {
  scenes: HOMAGE_SCENES_FIXTURE,
  pacing: 'medium',
  overallArc: '문제 제기 → 제품 등장 → 마무리',
}

const HOMAGE_REFERENCE_FIXTURE: HomageReference = {
  source: 'url',
  structure: HOMAGE_STRUCTURE_FIXTURE,
  analyzedAt: Date.now(),
}

const AD_ANALYSIS_FIXTURE: AdAnalysis = {
  productName: '테스트 수분크림',
  description: '순한 성분의 저자극 수분크림',
  keyFeatures: ['24시간 보습', '저자극'],
  targetAudience: '건성 피부 20대',
  mainBenefit: '깊은 보습',
  narration: '건조함, 이제 그만. 24시간 보습을 책임지는 수분크림.',
  callToAction: '지금 만나보세요.',
  tone: 'calm',
}

const AD_CONFIG_FIXTURE: AdConfig = {
  duration: 15, musicMood: 'calm', voice: 'female', voiceVariety: false,
  narrationLocale: 'ko', subtitles: true,
}

const AI_ACTOR_FIXTURE: AiActorProfile = { gender: 'female', age: '30s', vibe: 'friendly' }

function makeHomageAdConcept(): AdConceptSelection {
  return {
    categoryMain: 'beauty', categorySub: 'skincare', emphasis: ['moisture'],
    structureId: 'ad_homage', tone: 'calm', visualStyle: 'clean_bright',
    structureSource: 'homage', homage: HOMAGE_REFERENCE_FIXTURE,
  }
}

function makeTemplateAdConcept(): AdConceptSelection {
  return {
    categoryMain: 'beauty', categorySub: 'skincare', emphasis: ['moisture'],
    structureId: 'ad_problem', tone: 'calm', visualStyle: 'clean_bright',
    structureSource: 'template',
  }
}

function makeProject(overrides: Partial<Project> = {}): Project {
  return {
    id: 'proj_1', userId: 'user_1', status: 'storyboard', relation: 'solo',
    conceptId: 'ad_homage', styleId: 'cinematic', durationSec: 9,
    dialogueMode: 'none', aspect: '9:16', createdAt: new Date(),
    ...overrides,
  }
}

beforeEach(() => {
  mockGetKey.mockReset()
  mockGenerateAdStoryboardScenes.mockReset()
  mockGenerateStoryboardScenesLLM.mockReset()
  mockAdState.current = {}
})

describe('오마주 모드 — Gemini 실패 시 조용한 폴백 금지 (Task 9 리뷰 Critical)', () => {
  it('Gemini 키가 없으면 조용히 템플릿으로 넘어가지 않고 예외를 던진다', async () => {
    mockAdState.current = {
      adConcept: makeHomageAdConcept(),
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue(null)

    await expect(generateStoryboardScenes(makeProject(), [])).rejects.toThrow(/Gemini/)
    // 키가 없으니 Gemini 호출 자체가 시도되면 안 된다
    expect(mockGenerateAdStoryboardScenes).not.toHaveBeenCalled()
  })

  it('Gemini 호출이 실패(네트워크 오류 등)하면 조용히 템플릿으로 넘어가지 않고 예외를 던진다', async () => {
    mockAdState.current = {
      adConcept: makeHomageAdConcept(),
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue('fake-gemini-key')
    mockGenerateAdStoryboardScenes.mockRejectedValue(new Error('network down'))

    await expect(generateStoryboardScenes(makeProject(), [])).rejects.toThrow()
  })

  it('Gemini 응답 형식이 올바르지 않으면 조용히 템플릿으로 넘어가지 않고 예외를 던진다', async () => {
    mockAdState.current = {
      adConcept: makeHomageAdConcept(),
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue('fake-gemini-key')
    // descKo가 빈 문자열이라 isValid 체크(모든 씬이 descKo/keyframePromptEn/motionPromptEn을
    // 채워야 함)를 통과하지 못한다
    mockGenerateAdStoryboardScenes.mockResolvedValue([
      { descKo: '', dialogueKo: '', keyframePromptEn: '', motionPromptEn: '' },
    ])

    await expect(generateStoryboardScenes(makeProject(), [])).rejects.toThrow()
  })

  it('Gemini가 정상 응답하면 그 결과를 그대로 쓴다(오마주 모드도 정상 경로는 막지 않는다)', async () => {
    mockAdState.current = {
      adConcept: makeHomageAdConcept(),
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue('fake-gemini-key')
    const project = makeProject()
    // resampleHomageScenes(3개 씬, desiredCount)가 durationSec=9, SCENE_SEC_TARGET=3 →
    // desiredCount=3이라 그대로 3개로 리샘플된다
    const llmResult = [
      { descKo: '수분크림 도입부', dialogueKo: '건조함, 이제 그만.', keyframePromptEn: 'wide shot moisturizer', motionPromptEn: 'static' },
      { descKo: '수분크림 사용 장면', dialogueKo: '24시간 보습.', keyframePromptEn: 'medium shot moisturizer', motionPromptEn: 'push in' },
      { descKo: '수분크림 마무리', dialogueKo: '지금 만나보세요.', keyframePromptEn: 'close shot moisturizer', motionPromptEn: 'static' },
    ]
    mockGenerateAdStoryboardScenes.mockResolvedValue(llmResult)

    const scenes = await generateStoryboardScenes(project, [])
    expect(scenes).toHaveLength(3)
    expect(scenes.map(s => s.descKo)).toEqual(llmResult.map(s => s.descKo))
    // Gemini에 넘긴 구성 설명(structureFlow)에 오마주 씬의 샷 문법이 들어갔는지 확인 —
    // resampleHomageScenes를 두 번(씬 계산용/flow 텍스트용) 따로 불러 결과가 어긋나면 이 값이
    // sceneCount(3)와 안 맞을 수 있다
    const callArgs = mockGenerateAdStoryboardScenes.mock.calls[0][1]
    expect(callArgs.sceneCount).toBe(3)
    expect(callArgs.structureLabel).toBe('레퍼런스 오마주')
    expect(callArgs.structureFlow).toContain('wide/static')
  })
})

describe('오마주 모드 — 폴백 초기값이 로맨틱 템플릿과 무관하다 (Task 9 리뷰 Critical, 이중 방어)', () => {
  it('buildHomageFallbackScene은 DEFAULT_CONCEPT_TEMPLATE 로맨틱 대사를 담지 않고, dialogueKo는 항상 빈 문자열이다', () => {
    for (const [i, scene] of HOMAGE_SCENES_FIXTURE.entries()) {
      const fallback = buildHomageFallbackScene(scene, i)
      expect(fallback.dialogueKo).toBe('')
      expect(fallback.descKo).not.toContain('기억해줘')
      expect(fallback.descKo).not.toContain('우리의 시간')
      expect(fallback.descKo).not.toContain('모든 것이 변해도')
      expect(fallback.keyframePromptEn).not.toMatch(/couple|romantic/i)
      // 오마주 구조(샷 타입/피사체)에서 파생됐는지도 확인
      expect(fallback.descKo).toContain(scene.shotType)
      expect(fallback.descKo).toContain(scene.subjectRole)
    }
  })
})

// ── 최종 리뷰 C1(Critical) 회귀 테스트 ────────────────────────────────
// 배경: HOMAGE_STRUCTURE_ID('ad_homage')가 AD_CONCEPT_TEMPLATES에 미등록이라 pool은 항상
// DEFAULT_CONCEPT_TEMPLATE로 귀결되고, 그 템플릿의 subjectRefs는 전부 ['person_1']/['person_2']다.
// 수정 전에는 이 subjectRefs를 그대로 빌려 썼기 때문에, 오마주 레퍼런스가 고른 제품 단독 컷
// (subjectRole:'product'/'environment'/'text'/'abstract')에까지 인물이 강제로 들어갔다 —
// A6_Storyboard.tsx의 자세 검출(expectedCount = subjectRefs.length)이 어긋나 유료 키프레임
// 재생성이 낭비되고, AI 가상배우 묘사가 제품 클로즈업에 잘못 붙었다. 이제 subjectRefs는
// homageScenes[i].subjectRole에서 직접 파생된다: 'person' → ['person_1'], 그 외 → [].
describe('오마주 모드 — subjectRefs 는 homageScenes.subjectRole 에서 파생된다 (C1 최종 리뷰 Critical)', () => {
  it('subjectRole 이 product/environment 인 씬은 subjectRefs 가 빈 배열이다 (템플릿 subjectRefs 무시)', async () => {
    mockAdState.current = {
      // HOMAGE_SCENES_FIXTURE: environment, product, product — 사람이 없는 씬만 있다
      adConcept: makeHomageAdConcept(),
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue('fake-gemini-key')
    mockGenerateAdStoryboardScenes.mockResolvedValue([
      { descKo: '도입', dialogueKo: '', keyframePromptEn: 'wide shot', motionPromptEn: 'static' },
      { descKo: '제품 등장', dialogueKo: '', keyframePromptEn: 'medium shot', motionPromptEn: 'push in' },
      { descKo: '마무리', dialogueKo: '', keyframePromptEn: 'close shot', motionPromptEn: 'static' },
    ])

    // persons=[]: 광고 프로젝트는 실제 인물 사진 없이(AI 가상배우) 진행하는 경우가 흔하다
    const scenes = await generateStoryboardScenes(makeProject(), [])
    expect(scenes).toHaveLength(3)
    expect(scenes[0].subjectRefs).toEqual([]) // environment
    expect(scenes[1].subjectRefs).toEqual([]) // product
    expect(scenes[2].subjectRefs).toEqual([]) // product
  })

  it("subjectRole 이 'person' 인 씬만 ['person_1'] 이고, 나머지는 빈 배열이다", async () => {
    const scenesWithPerson: HomageScene[] = [
      { seq: 1, durationSec: 3, shotType: 'wide', cameraMove: 'static', subjectRole: 'environment', emotionBeat: '도입', transition: 'cut' },
      { seq: 2, durationSec: 3, shotType: 'medium', cameraMove: 'push_in', subjectRole: 'product', emotionBeat: '고조', transition: 'cut' },
      { seq: 3, durationSec: 3, shotType: 'close', cameraMove: 'static', subjectRole: 'person', emotionBeat: '마무리', transition: 'cut' },
    ]
    mockAdState.current = {
      adConcept: {
        ...makeHomageAdConcept(),
        homage: {
          ...HOMAGE_REFERENCE_FIXTURE,
          structure: { ...HOMAGE_STRUCTURE_FIXTURE, scenes: scenesWithPerson },
        },
      },
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue('fake-gemini-key')
    mockGenerateAdStoryboardScenes.mockResolvedValue([
      { descKo: '도입', dialogueKo: '', keyframePromptEn: 'wide shot', motionPromptEn: 'static' },
      { descKo: '제품 등장', dialogueKo: '', keyframePromptEn: 'medium shot', motionPromptEn: 'push in' },
      { descKo: '인물 등장', dialogueKo: '', keyframePromptEn: 'close shot', motionPromptEn: 'static' },
    ])

    const scenes = await generateStoryboardScenes(makeProject(), [])
    expect(scenes[0].subjectRefs).toEqual([])
    expect(scenes[1].subjectRefs).toEqual([])
    expect(scenes[2].subjectRefs).toEqual(['person_1'])
  })

  it('제품 단독 컷(subjectRefs 빈 배열)에는 AI 가상배우 프롬프트가 붙지 않는다', async () => {
    mockAdState.current = {
      adConcept: makeHomageAdConcept(),
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue('fake-gemini-key')
    mockGenerateAdStoryboardScenes.mockResolvedValue([
      { descKo: '도입', dialogueKo: '', keyframePromptEn: 'wide shot', motionPromptEn: 'static' },
      { descKo: '제품 등장', dialogueKo: '', keyframePromptEn: 'medium shot', motionPromptEn: 'push in' },
      { descKo: '마무리', dialogueKo: '', keyframePromptEn: 'close shot', motionPromptEn: 'static' },
    ])

    // persons=[] 이라 buildAiActorEn(AI_ACTOR_FIXTURE)이 adActorModifier 후보가 된다 —
    // subjectRefs 가 빈 배열인 씬(전부)에는 이 문구가 절대 붙으면 안 된다
    const scenes = await generateStoryboardScenes(makeProject(), [])
    for (const s of scenes) {
      expect(s.subjectRefs).toEqual([])
      expect(s.keyframePromptEn).not.toContain('generic model face not resembling any real celebrity')
    }
  })
})

describe('템플릿 모드 — subjectRefs 동작은 오마주 도입 전과 동일하다 (회귀 방지, C1)', () => {
  it('relation=solo 템플릿 모드에서 subjectRefs 는 템플릿 원본을 그대로 따른다(인물 컷=[person_1], 제품 컷=[])', async () => {
    mockAdState.current = {
      adConcept: makeTemplateAdConcept(),
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue(null) // 템플릿 모드는 키 없이도 조용히 템플릿 원문으로 완성된다

    // ad_problem 템플릿 풀(adConcepts.ts, 총 6씬)의 subjectRefs 원본 그대로:
    // [person_1], [], [], [person_1], [], [person_1]
    // durationSec=18 → desiredCount=round(18/3)=6=pool.length 이라 풀 전체가 그대로 쓰인다
    const project = makeProject({ conceptId: 'ad_problem', relation: 'solo', durationSec: 18 })
    const scenes = await generateStoryboardScenes(project, [])

    expect(scenes).toHaveLength(6)
    expect(scenes.map(s => s.subjectRefs)).toEqual([
      ['person_1'], [], [], ['person_1'], [], ['person_1'],
    ])
  })
})

describe('템플릿 모드 — 기존 조용한 폴백 동작은 그대로다 (회귀 방지)', () => {
  it('Gemini 키가 없어도 예외 없이 템플릿 원문으로 조용히 완성된다', async () => {
    mockAdState.current = {
      adConcept: makeTemplateAdConcept(),
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue(null)

    const project = makeProject({ conceptId: 'ad_problem' })
    const scenes = await generateStoryboardScenes(project, [])

    expect(scenes.length).toBeGreaterThan(0)
    // ad_problem 템플릿 풀의 실제 원문(제품 광고 문구)으로 조용히 채워졌다 — 예외 없음
    expect(scenes[0].descKo).toContain('불편한 순간')
    expect(mockGenerateAdStoryboardScenes).not.toHaveBeenCalled()
  })

  it('Gemini 호출이 실패해도 예외 없이 템플릿 원문으로 조용히 대체된다', async () => {
    mockAdState.current = {
      adConcept: makeTemplateAdConcept(),
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue('fake-gemini-key')
    mockGenerateAdStoryboardScenes.mockRejectedValue(new Error('network down'))

    const project = makeProject({ conceptId: 'ad_problem' })
    const scenes = await generateStoryboardScenes(project, [])

    expect(scenes.length).toBeGreaterThan(0)
    expect(scenes[0].descKo).toContain('불편한 순간')
  })

  it('structureSource가 undefined(기존 localStorage 사용자)여도 예외 없이 조용히 템플릿으로 완성된다', async () => {
    // adConcept 자체에 structureSource 필드가 아예 없는 기존 사용자 상태를 흉내낸다
    const legacyAdConcept = { ...makeTemplateAdConcept() } as Partial<AdConceptSelection>
    delete legacyAdConcept.structureSource
    mockAdState.current = {
      adConcept: legacyAdConcept,
      analysis: AD_ANALYSIS_FIXTURE,
      config: AD_CONFIG_FIXTURE,
      aiActor: AI_ACTOR_FIXTURE,
    }
    mockGetKey.mockResolvedValue(null)

    const project = makeProject({ conceptId: 'ad_problem' })
    const scenes = await generateStoryboardScenes(project, [])

    expect(scenes.length).toBeGreaterThan(0)
    expect(scenes[0].descKo).toContain('불편한 순간')
  })
})
