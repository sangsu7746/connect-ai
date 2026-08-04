import { describe, it, expect, vi, beforeEach } from 'vitest'

// 실제 aiAdapters.ts 의 QuotaExhaustedError 와 형태(provider, message)를 맞춘 목 —
// homageAnalyzer.ts 가 instanceof 로 판별하므로 목도 진짜 클래스여야 한다.
// vi.mock 팩토리는 import 그래프 해석 시점(파일의 다른 top-level 문보다 먼저)에 실행되므로,
// 그 안에서 직접 참조할 값은 vi.hoisted 로 만들어야 한다(그냥 top-level class 는 TDZ 에 걸린다).
const { MockQuotaExhaustedError } = vi.hoisted(() => {
  class MockQuotaExhaustedError extends Error {
    constructor(public provider: string, message: string) {
      super(message)
      this.name = 'QuotaExhaustedError'
    }
  }
  return { MockQuotaExhaustedError }
})

const callProxy = vi.fn()
vi.mock('./aiAdapters', () => ({
  callProxy: (...a: unknown[]) => callProxy(...a),
  geminiTextEndpoint: async () => 'https://fake/gen',
  geminiText: (d: any) => d.text,
  QuotaExhaustedError: MockQuotaExhaustedError,
}))
vi.mock('../stores/keysStore', () => ({
  KeyVault: { getKey: async () => 'FAKE_KEY' },
  useKeysStore: { getState: () => ({ updateGeminiUsage: () => {} }) },
}))
// parseYoutubeVideoId(youtubeService.ts)를 실제 구현 그대로 쓰기 위해 mock하지 않는다.
// 다만 youtubeService.ts가 모듈 상단에서 끌어오는 firebase.ts/firebaseTarget.ts는
// 로드 시점에 window.location을 읽어 vitest의 node 환경(jsdom 미설치)에서 즉시 죽는다.
// youtubeService.test.ts와 동일한 방식으로 그 두 모듈만 잘라낸다.
vi.mock('./firebase', () => ({ auth: { currentUser: null } }))
vi.mock('./firebaseTarget', () => ({ fnUrl: (n: string) => `https://fake/${n}` }))

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

  it('쿼터 소진 오류는 재시도하지 않고 즉시 던진다 (1회만 호출)', async () => {
    // mockRejectedValue(지속형)이 아니라 Once 를 쓴다 — 재시도가 실제로 스킵됐는지
    // 검증하는 게 목적이므로, 혹시라도 재시도가 일어나면 두 번째 호출은 기본 동작(undefined
    // 반환)으로 떨어져 테스트가 명확하게 실패하게 만든다.
    callProxy.mockRejectedValueOnce(new MockQuotaExhaustedError('gemini', 'Gemini 무료 쿼터를 오늘치 다 썼어요.'))
    await expect(analyzeFromVideo('dQw4w9WgXcQ')).rejects.toThrow(/쿼터/)
    expect(callProxy).toHaveBeenCalledTimes(1)
  })

  it('프롬프트에 저작권 지시문(구조만 · 대사·브랜드명 금지)이 실려 나간다', async () => {
    callProxy.mockResolvedValue({ text: goodJson })
    await analyzeFromVideo('dQw4w9WgXcQ')
    const parts = callProxy.mock.calls[0][0].body.contents[0].parts
    const allText = parts.filter((p: any) => typeof p.text === 'string').map((p: any) => p.text).join('\n')
    expect(allText).toContain('Do NOT transcribe or paraphrase')
    expect(allText).toContain('brand names')
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
    // MIN_DESCRIPTION_LEN(10자) 이상 — 원문의 '아무 설명'(5자)은 구현의 최소 길이
    // 가드를 통과하지 못해 이 테스트가 검증하려는 "성공 경로"에 도달하지 못했다.
    const out = await analyzeFromDescription('아무 설명이나 상관없어요')
    expect(out.scenes).toHaveLength(3)
    expect(out.overallArc).toBe('일상 → 주목 → 해소')
  })

  it('설명이 너무 짧으면 막는다', async () => {
    await expect(analyzeFromDescription('짧')).rejects.toThrow(/조금 더 자세히/)
    expect(callProxy).not.toHaveBeenCalled()
  })

  it('프롬프트에 저작권 지시문(구조만 · 대사·브랜드명 금지)이 실려 나간다', async () => {
    callProxy.mockResolvedValue({ text: goodJson })
    await analyzeFromDescription('아무 설명이나 상관없어요')
    const parts = callProxy.mock.calls[0][0].body.contents[0].parts
    const allText = parts.filter((p: any) => typeof p.text === 'string').map((p: any) => p.text).join('\n')
    expect(allText).toContain('Do NOT transcribe or paraphrase')
    expect(allText).toContain('brand names')
  })
})
