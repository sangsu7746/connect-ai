import { describe, it, expect, beforeAll, vi } from 'vitest'

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

// firebaseTarget.ts 는 위 목과 무관하게 aiAdapters.ts 가 직접 임포트하며, 모듈 최상단에서
// window.location.hostname 을 읽는다 — node 환경엔 window 가 없으므로 최소 스텁을 채운다.
// 정적 import 는 다른 모든 코드보다 먼저 끌어올려져 스텁이 무의미해지므로, 동적 import 로 미룬다.
let buildSceneDurations: (durationSec: number, sceneCount: number, weights?: number[]) => number[]

beforeAll(async () => {
  const g = globalThis as { window?: unknown }
  g.window ??= { location: { hostname: 'localhost' } }
  ;({ buildSceneDurations } = await import('./storyboardGenerator'))
})

describe('buildSceneDurations 회귀', () => {
  it.each([
    [15, 5, 15],
    [30, 10, 30],
    [60, 20, 60],
    // 씬당 최대 4초(SCENE_SEC_SOFT_MAX) 클램프로 1단계에서 못 채운 나머지는
    // 2단계에서 SCENE_SEC_HARD_MAX(6초)까지 흡수한다 — 이 기존 안전장치 때문에
    // 15초/3씬은 12초로 줄지 않고 15초 그대로 유지된다([6,5,4]).
    [15, 3, 15],
  ])('weights 없이 호출하면 기존 동작을 유지한다 (%i초 %i씬)', (dur, count, expectedTotal) => {
    const out = buildSceneDurations(dur, count)
    expect(out).toHaveLength(count)
    expect(out.reduce((a, b) => a + b, 0)).toBe(expectedTotal)
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
