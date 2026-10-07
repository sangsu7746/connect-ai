// ════════════════════════════════════════════════════════════════
// 배경음악(BGM) — public/bgm/<mood>-<NN>.mp3 무료 음원 풀에서 컨셉 무드로 한 곡 결정론 선택
// (AdStudio 음원 풀에서 부동산에 어울리는 4개 무드를 선별 복제해 사용)
// ════════════════════════════════════════════════════════════════
export type BgmMood = 'documentary_calm' | 'emotional_daily' | 'celebration' | 'family_warm'

const BGM_COUNTS: Record<BgmMood, number> = {
  documentary_calm: 6,
  emotional_daily: 6,
  celebration: 6,
  family_warm: 6,
}

export const BGM_MOOD_LABEL: Record<BgmMood, string> = {
  documentary_calm: '차분·신뢰',
  emotional_daily: '감성·따뜻',
  celebration: '활기·경쾌',
  family_warm: '포근·가족',
}

function hashToIndex(seed: string, count: number): number {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0
  return Math.abs(h) % count
}

/** 무드 + seed(프로젝트 식별)로 결정론적으로 한 곡을 골라 정적 경로를 돌려준다. */
export function resolveBgmUrl(mood: BgmMood, seed: string): string {
  const count = BGM_COUNTS[mood] ?? 6
  const idx = hashToIndex(seed || mood, count) + 1
  return `/bgm/${mood}-${String(idx).padStart(2, '0')}.mp3`
}
