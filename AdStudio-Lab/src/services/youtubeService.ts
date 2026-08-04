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
