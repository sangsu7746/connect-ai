import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { buildSearchQuery, parseYoutubeVideoId, searchAdVideos, getVideoInfo, YoutubeQuotaError } from './youtubeService'

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
})
