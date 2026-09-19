// ════════════════════════════════════════════════════════════════
// SNS 업로드·공유 — 플랫폼별 업로드 화면 바로가기 + 게시 문구 자동생성.
//   · 브라우저에서 다른 사이트 업로드 폼에 파일을 자동 첨부할 수는 없다(보안).
//     → 플랫폼 버튼을 누르면 그 플랫폼 업로드/작성 화면을 열고, 문구를 클립보드에 복사한다.
//   · Threads·X는 intent URL로 문구를 미리 채워 연다.
//   · 문구는 자동 작성되며 사용자가 결과 화면에서 자유롭게 수정한다.
// ════════════════════════════════════════════════════════════════
import type { ListingInfo } from '../types'
import type { Marketing } from './hooks'

export interface Platform {
  id: string
  name: string
  emoji: string
  hint: string
  prefill: boolean            // intent로 문구가 미리 채워지는가
  url: (text: string) => string
}

export const PLATFORMS: Platform[] = [
  { id: 'youtube', name: 'YouTube 쇼츠', emoji: '▶️', hint: '업로드 화면에서 영상 선택', prefill: false, url: () => 'https://www.youtube.com/upload' },
  { id: 'instagram', name: 'Instagram 릴스', emoji: '📸', hint: '앱/웹에서 릴스로 업로드', prefill: false, url: () => 'https://www.instagram.com/' },
  { id: 'tiktok', name: 'TikTok', emoji: '🎵', hint: '업로드 화면에서 영상 선택', prefill: false, url: () => 'https://www.tiktok.com/upload' },
  { id: 'threads', name: 'Threads', emoji: '🧵', hint: '문구가 미리 채워져요', prefill: true, url: (t) => `https://www.threads.net/intent/post?text=${encodeURIComponent(t)}` },
  { id: 'x', name: 'X (트위터)', emoji: '𝕏', hint: '문구가 미리 채워져요', prefill: true, url: (t) => `https://x.com/intent/post?text=${encodeURIComponent(t)}` },
]

const clean = (s: string) => s.replace(/[^가-힣A-Za-z0-9]/g, '')

function hashtagsFor(listing: ListingInfo, marketing: Marketing | null): string[] {
  const t = new Set<string>(['부동산', '매물', '부동산홍보', '릴스', 'shorts'])
    ; (listing.region || '').split(/\s+/).filter(Boolean).slice(0, 3).forEach(r => { const c = clean(r); if (c.length >= 2) t.add(c) })
  const pt = clean(listing.propertyType); if (pt) t.add(pt)
    ; (marketing?.badges || []).forEach(b => { const c = clean(b); if (c.length >= 2) t.add(c) })
  return [...t].slice(0, 11)
}

/** 게시 문구 자동 작성 — 훅 제목 + 매물 요약 + 해시태그. variant로 다른 제목/버전. */
export function buildCaption(listing: ListingInfo, marketing: Marketing | null, variant = 0): string {
  const titles = (marketing?.titles && marketing.titles.length) ? marketing.titles : [listing.title].filter(Boolean)
  const headline = titles.length ? titles[variant % titles.length] : (listing.title || '좋은 매물 소개합니다')

  const info: string[] = []
  const loc = [listing.region, listing.propertyType].filter(Boolean).join(' ')
  if (loc) info.push(`📍 ${loc}`)
  const size = [listing.areaText, listing.rooms].filter(Boolean).join(' · ')
  if (size) info.push(`📐 ${size}`)
  if (listing.priceText) info.push(`💰 ${listing.priceText}`)
  if (listing.station && listing.walkText) info.push(`🚇 ${listing.station} ${listing.walkText}`)
  else if (listing.accessText) info.push(`🛣️ ${listing.accessText}`)
  if (listing.yieldText) info.push(`📈 ${listing.yieldText}`)
  const feats = [...listing.features, ...listing.investPoints].filter(Boolean).slice(0, 3)
  if (feats.length) info.push(`✨ ${feats.join(' · ')}`)

  const lines = [headline, '', ...info]
  if (listing.contact) lines.push('', `📞 문의 ${listing.contact}`)
  lines.push('', hashtagsFor(listing, marketing).map(h => `#${h}`).join(' '))
  return lines.join('\n').replace(/\n{3,}/g, '\n\n').trim()
}
