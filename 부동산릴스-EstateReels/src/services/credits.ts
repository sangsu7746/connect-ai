// ════════════════════════════════════════════════════════════════
// 제작 크레딧 — "만드는 건 부담 없이, 가져갈 때 과금".
//   · 제작(렌더): 프로젝트(영상)당 FREE_RENDERS(2)회 무료(입력 실수 수정용),
//                 그 이상 다시 만들면 COINS_PER_RENDER(100)코인/편.
//   · 미리보기: 무료(앱 안 재생).
//   · 다운로드/공유/연동: 첫 편부터 COINS_PER_DOWNLOAD(500)코인/편.
//     같은 영상 재다운로드는 무료(로컬 결제 기록 + spendCoins refId 멱등).
//   충전은 메인 홈에서만 → TOPUP_URL(#points).
// ════════════════════════════════════════════════════════════════

export const FREE_RENDERS = 2                 // 프로젝트당 무료 제작 횟수
export const COINS_PER_RENDER = 100           // 무료 초과 제작 편당 코인
export const COINS_PER_DOWNLOAD = 500         // 다운로드·공유·연동 편당 코인
export const TOPUP_URL = 'https://www.headjim.com/#points'
export const WALLET_SERVICE = 'estate-reels'  // spendCoins service 식별자(2~40자)

/** 제작/다운로드 결제 멱등 키(refId, [A-Za-z0-9_-]). */
export function makeVideoId(): string {
  return `er_${Date.now().toString(36)}_${Math.floor(Math.random() * 1e6).toString(36)}`
}

// ── 다운로드 결제 추적(로컬) — 결제한 영상은 재다운로드 무료 ──
const PAID_KEY = 'estate_paid_downloads'
function paidSet(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(PAID_KEY) || '[]') as string[]) }
  catch { return new Set() }
}
export function isDownloadPaid(videoId: string): boolean {
  return !!videoId && paidSet().has(videoId)
}
export function markDownloadPaid(videoId: string): void {
  if (!videoId) return
  const s = paidSet(); s.add(videoId)
  localStorage.setItem(PAID_KEY, JSON.stringify([...s].slice(-300))) // 최근 300개만 유지
}
