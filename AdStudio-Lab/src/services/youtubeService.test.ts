import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  buildSearchQuery, extractProductType, parseYoutubeVideoId, searchAdVideos, getVideoInfo, YoutubeQuotaError,
} from './youtubeService'

vi.mock('./firebase', () => ({ auth: { currentUser: { getIdToken: async () => 'tok' } } }))
vi.mock('./firebaseTarget', () => ({ fnUrl: (n: string) => `https://fake/${n}` }))

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

// ── I2(Important) 최종 리뷰: 검색어 기본값이 용량/수량 토큰을 집는다 ──────────
// 한국 상품명은 "브랜드 + 제품군 + 용량/수량"(예: "미리집 수분크림 50ml") 순서가 지배적이라
// 마지막 낱말을 그대로 쓰면 제품군이 아니라 포장 단위가 검색어에 들어간다. search.list 는
// 1회 100유닛에 전체 사용자 합계 하루 약 100회뿐이라, 기본값이 나쁘면 사용자가 검색어를
// 고쳐 두 번 검색하게 돼 공용 한도가 반토막 난다.
describe('extractProductType', () => {
  it('용량 토큰(ml)으로 끝나면 그 앞 낱말을 제품군으로 쓴다', () => {
    expect(extractProductType('미리집 수분크림 50ml')).toBe('수분크림')
  })

  it('용량+수량 토큰이 연달아 있으면 둘 다 건너뛴다', () => {
    expect(extractProductType('ABC 세럼 30ml 2개입')).toBe('세럼')
  })

  it.each([
    ['브랜드 크림 100g', '크림'],
    ['브랜드 영양제 500kg', '영양제'],
    ['브랜드 토너 1.5L', '토너'],
    ['브랜드 알약 30정', '알약'],
    ['브랜드 마스크팩 10매', '마스크팩'],
    ['브랜드 유산균 60포', '유산균'],
  ])('%s → %s', (input, expected) => {
    expect(extractProductType(input)).toBe(expected)
  })

  it('용량 토큰이 없으면 기존처럼 마지막 낱말을 그대로 쓴다', () => {
    expect(extractProductType('나이키 러닝화')).toBe('러닝화')
  })

  it('상품명이 용량 토큰 하나뿐이면(앞 낱말이 없으면) 그대로 쓴다 — 더 나은 대안이 없다', () => {
    expect(extractProductType('50ml')).toBe('50ml')
  })

  it('빈 문자열은 빈 문자열을 돌려준다', () => {
    expect(extractProductType('')).toBe('')
    expect(extractProductType('   ')).toBe('')
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
    // 회귀 테스트: 적대적 URL이 null을 반환해야 한다
    ['https://youtube.com.evil.com/watch?v=dQw4w9WgXcQ'],  // 호스트 위장 (서브도메인 접미사 공격)
    ['https://www.youtube.com/watch?v=dQw4w9WgXcQextra'],  // videoId 뒤 잉여 문자
    ['//youtube.com/watch?v=dQw4w9WgXcQ'],                 // 스킴 없는 protocol-relative URL
  ])('잘못된 입력은 null: %s', (input) => {
    expect(parseYoutubeVideoId(input)).toBeNull()
  })
})

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

  // 회귀 테스트(Task 12 검증에서 발견): fetch 자체가 reject하면(서버 미가동·네트워크
  // 단절·CORS 등) 브라우저 원문("Failed to fetch")이 아니라 한국어 안내가 나와야 한다.
  it('fetch 자체가 실패하면(네트워크 단절) 브라우저 원문 대신 한국어 안내를 던진다', async () => {
    ;(fetch as any).mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(searchAdVideos('x')).rejects.toThrow(/연결.*확인|다시 시도/)
    await expect(searchAdVideos('x')).rejects.not.toThrow(/Failed to fetch/)
  })

  // fetch 예외를 감싸더라도, 응답을 받은 뒤의 429 → YoutubeQuotaError 구분은 그대로 살아
  // 있어야 한다(대체 입구 유도 분기가 이 타입 구분에 의존한다).
  it('네트워크 안내 도입 후에도 429 는 여전히 YoutubeQuotaError 로 구분된다', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 429, text: async () => '한도' })
    await expect(searchAdVideos('x')).rejects.toBeInstanceOf(YoutubeQuotaError)
  })

  // T7 승격(Important) 최종 리뷰: 401(로그인 필요)·503(서버에 키 미설정)은 초기 운영에서
  // 가장 흔한 상태인데도 범용 "검색에 실패했어요"로 뭉개져 사용자가 뭘 해야 할지 알 수
  // 없었다. 각각 다음 행동을 알려주는 문구여야 한다.
  it('401 은 로그인을 안내한다', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 401, text: async () => '' })
    await expect(searchAdVideos('x')).rejects.toThrow(/로그인/)
  })

  it('503 은 서버 설정 문제를 안내한다(사용자 재시도/문의로 유도)', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 503, text: async () => '' })
    await expect(searchAdVideos('x')).rejects.toThrow(/서버|설정/)
  })
})

describe('getVideoInfo', () => {
  beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
  afterEach(() => { vi.unstubAllGlobals() })

  it('성공 시 영상 정보를 돌려준다', async () => {
    const info = { videoId: 'dQw4w9WgXcQ', title: 'Title', channelTitle: 'Channel', thumbnailUrl: 'url', durationSec: 180 }
    ;(fetch as any).mockResolvedValue({ ok: true, status: 200, json: async () => info })
    await expect(getVideoInfo('dQw4w9WgXcQ')).resolves.toEqual(info)
  })

  it('Authorization 헤더에 ID 토큰을 싣는다', async () => {
    ;(fetch as any).mockResolvedValue({ ok: true, status: 200, json: async () => ({ videoId: 'x'.repeat(11) }) })
    await getVideoInfo('x'.repeat(11))
    const init = (fetch as any).mock.calls[0][1]
    expect(init.headers.Authorization).toBe('Bearer tok')
  })

  it('404 는 "영상을 찾을 수 없어요" 오류', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 404, text: async () => '' })
    await expect(getVideoInfo('notfound')).rejects.toThrow(/영상을 찾을 수 없어요/)
  })

  it('429 는 YoutubeQuotaError 로 구분한다', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 429, text: async () => '' })
    await expect(getVideoInfo('x'.repeat(11))).rejects.toBeInstanceOf(YoutubeQuotaError)
  })

  // T7 승격(Important) 최종 리뷰: getVideoInfo(URL 입구)도 searchAdVideos 와 같은 서버 함수를
  // 공유하므로 401/503 안내가 동일하게 있어야 한다.
  it('401 은 로그인을 안내한다', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 401, text: async () => '' })
    await expect(getVideoInfo('x'.repeat(11))).rejects.toThrow(/로그인/)
  })

  it('503 은 서버 설정 문제를 안내한다(사용자 재시도/문의로 유도)', async () => {
    ;(fetch as any).mockResolvedValue({ ok: false, status: 503, text: async () => '' })
    await expect(getVideoInfo('x'.repeat(11))).rejects.toThrow(/서버|설정/)
  })

  // 회귀 테스트(Task 12 검증에서 발견): searchAdVideos 와 동일한 네트워크 실패 처리가
  // getVideoInfo(URL 입구)에도 있어야 한다 — 같은 postYoutubeFn 을 공유하므로 문구도 동일해야 한다.
  it('fetch 자체가 실패하면(네트워크 단절) 브라우저 원문 대신 한국어 안내를 던진다', async () => {
    ;(fetch as any).mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(getVideoInfo('x'.repeat(11))).rejects.toThrow(/연결.*확인|다시 시도/)
    await expect(getVideoInfo('x'.repeat(11))).rejects.not.toThrow(/Failed to fetch/)
  })
})
