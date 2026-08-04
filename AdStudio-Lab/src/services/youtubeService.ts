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
    await res.text().catch(() => '')
    throw new Error('유튜브 검색에 실패했어요.')
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
