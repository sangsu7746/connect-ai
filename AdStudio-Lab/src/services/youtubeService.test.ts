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
