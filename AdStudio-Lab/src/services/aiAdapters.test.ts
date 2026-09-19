import { describe, it, expect, vi, afterEach } from 'vitest'

// aiAdapters.ts 는 모듈 최상단에서 firebase.ts(auth 인스턴스)와 firebaseTarget.ts(fnUrl,
// window.location 읽음)를 끌어온다 — youtubeService.test.ts/homageAnalyzer.test.ts와 같은
// 이유로 두 모듈만 얇게 목(mock)한다. adStore.ts는 zustand persist(localStorage)라 node
// 환경에서 동작이 불확실해 storyboardGenerator.test.ts와 같은 이유로 함께 목한다 —
// 여기서 테스트하는 generateAdStoryboardScenes는 useAdStore를 쓰지 않지만, 모듈
// 최상단 import이므로 실제 스토어가 생성되는 것 자체를 막아야 한다.
vi.mock('./firebase', () => ({ auth: { currentUser: null } }))
vi.mock('./firebaseTarget', () => ({ fnUrl: (n: string) => `https://fake/${n}` }))
vi.mock('../stores/adStore', () => ({ useAdStore: { getState: () => ({}) } }))
vi.mock('../stores/keysStore', () => ({
  KeyVault: { getKey: async () => 'FAKE_KEY' },
  useKeysStore: { getState: () => ({ updateGeminiUsage: () => {} }) },
  assertAlibabaUsable: () => {},
}))

import { GeminiAdapter } from './aiAdapters'
import type { GeneratedStoryboardScene } from './aiAdapters'
import type { DialogueMode } from '../types'

const referenceScenes: GeneratedStoryboardScene[] = [
  { descKo: '기존 참고 씬 설명', dialogueKo: '기존 참고 대사', keyframePromptEn: 'wide shot', motionPromptEn: 'static' },
]

function baseContext(overrides: Partial<Parameters<typeof GeminiAdapter.generateAdStoryboardScenes>[1]> = {}) {
  return {
    productName: '테스트 수분크림',
    description: '순한 성분의 저자극 수분크림',
    keyFeatures: ['24시간 보습'],
    narration: '건조함, 이제 그만.',
    callToAction: '지금 만나보세요.',
    emphasisKo: ['보습'],
    toneKo: '차분한',
    structureLabel: '문제 → 해결형',
    structureFlow: '문제 → 제품 등장 → 해결',
    sceneCount: 1,
    durationSec: 9,
    hasModel: false,
    dialogueMode: 'auto' as DialogueMode,
    ...overrides,
  }
}

const goodLlmScenes = [
  { descKo: '수분크림 도입부', dialogueKo: '건조함, 이제 그만.', keyframePromptEn: 'wide shot moisturizer', motionPromptEn: 'static' },
]

/**
 * corsProxy를 통해 나가는 fetch를 가로채, 실제로 Gemini 각본 프롬프트로 뭘 보냈는지 캡처한다.
 * callProxy는 항상 PROXY_BASE_URL로 POST하고, 실제 대상 HTTP 메서드는 요청 본문의 `method`
 * 필드로 구분한다(GET=모델 목록 조회 resolveGeminiModels, POST=generateContent 본 호출).
 * 모델 목록 조회는 일부러 실패시켜 폴백 모델명 경로를 타게 한다 — 실제 모델 목록을 흉내 낼
 * 필요 없이 프롬프트 캡처라는 테스트 목적에 집중한다.
 */
function mockProxyFetch(): { getCapturedPrompt: () => string } {
  let capturedPrompt = ''
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init: any) => {
    const body = JSON.parse(init.body)
    if (body.method === 'GET') {
      return { ok: false, status: 500, text: async () => 'models unavailable' }
    }
    capturedPrompt = body.payload.contents[0].parts[0].text
    return {
      ok: true,
      status: 200,
      json: async () => ({
        candidates: [{ content: { parts: [{ text: JSON.stringify({ scenes: goodLlmScenes }) }] } }],
      }),
    }
  }))
  return { getCapturedPrompt: () => capturedPrompt }
}

describe('GeminiAdapter.generateAdStoryboardScenes — 광고 각본 프롬프트 (I4 최종 리뷰)', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  // I4-1: 경쟁 브랜드명·실존 유명인 금지 지시가 기존엔 keyframePromptEn 문장에만 걸려 있어서,
  // descKo(장면 설명)·dialogueKo(나레이션)에는 적용되지 않았다. 두 필드까지 확대됐는지 확인한다.
  it('경쟁 브랜드명/실존 유명인 금지가 descKo·dialogueKo·keyframePromptEn 세 필드 모두에 걸린다', async () => {
    const { getCapturedPrompt } = mockProxyFetch()

    await GeminiAdapter.generateAdStoryboardScenes(referenceScenes, baseContext(), 'FAKE_KEY')

    const prompt = getCapturedPrompt()
    expect(prompt).toContain('descKo')
    expect(prompt).toContain('dialogueKo')
    expect(prompt).toContain('keyframePromptEn')
    expect(prompt).toContain('경쟁 브랜드명')
    expect(prompt).toContain('실존 유명인')
    // 금지 문구가 세 필드 이름과 "같은 문장/절"에 함께 등장해야 한다 — 필드 이름과
    // 금지 문구가 서로 무관한 자리에 각각 존재하는 것만으로는 부족하다.
    const forbidLine = prompt.split('\n').find(line => line.includes('경쟁 브랜드명'))
    expect(forbidLine).toBeDefined()
    expect(forbidLine).toContain('descKo')
    expect(forbidLine).toContain('dialogueKo')
    expect(forbidLine).toContain('keyframePromptEn')
  })

  it('정상 응답이면 그 결과를 그대로 돌려준다(프롬프트 확대가 정상 경로를 깨지 않는다)', async () => {
    mockProxyFetch()
    const out = await GeminiAdapter.generateAdStoryboardScenes(referenceScenes, baseContext(), 'FAKE_KEY')
    expect(out).toEqual(goodLlmScenes)
  })
})
