// ── 배경음악(BGM) 해석 서비스 ──────────────────────────────────
// public/bgm/<mood>-<01..NN>.mp3 로 미리 분류·정리해둔 무료 음원 풀에서, 컨셉에 맞는 무드를
// 찾아 프로젝트별로 결정론적인 한 곡을 고른다. StoryboardMeta.bgmMood는 실제로 채워지는 곳이
// 없어(죽은 필드) 이 서비스는 그 대신 conceptId로 직접 무드를 판정한다.
import { useAdStore } from '../stores/adStore'

export type BgmMood =
  | 'noir_mystery' | 'horror_gothic' | 'romance' | 'family_warm' | 'sad_melancholy'
  | 'epic_war' | 'fantasy' | 'dance_kpop' | 'hiphop' | 'vocal_ballad' | 'anime'
  | 'celebration' | 'documentary_calm' | 'tension_suspense' | 'emotional_daily'

// public/bgm 안에 실제로 몇 곡씩 있는지 — resolveBgmUrl이 이 개수 안에서만 인덱스를 고른다
const BGM_COUNTS: Record<BgmMood, number> = {
  noir_mystery: 11,
  horror_gothic: 12,
  romance: 23,
  family_warm: 6,
  sad_melancholy: 17,
  epic_war: 19,
  fantasy: 11,
  dance_kpop: 19,
  hiphop: 8,
  vocal_ballad: 8,
  anime: 13,
  celebration: 13,
  documentary_calm: 17,
  tension_suspense: 13,
  emotional_daily: 19,
}

// 컨셉 카드(storyboardGenerator.ts의 c1~c35)별로 어울리는 BGM 무드 — 새 컨셉을 추가하면 여기도
// 같이 채워야 한다(없으면 DEFAULT_MOOD로 조용히 대체됨).
const CONCEPT_BGM_MOOD: Record<string, BgmMood> = {
  c1: 'noir_mystery',       // 느와르 스릴러
  c2: 'romance',            // 로맨틱 멜로
  c3: 'emotional_daily',    // 청춘 성장기
  c4: 'family_warm',        // 가족 드라마
  c5: 'fantasy',            // 로맨스 판타지
  c6: 'romance',            // 직장인 로맨스
  c7: 'romance',            // 시대극 멜로
  c8: 'emotional_daily',    // 청춘 우정
  c9: 'vocal_ballad',       // 감성 발라드
  c10: 'hiphop',            // 힙합 비트
  c11: 'dance_kpop',        // 팝 댄스
  c12: 'emotional_daily',   // 레트로 애니 감성
  c13: 'documentary_calm',  // 수묵 동양화
  c14: 'emotional_daily',   // 럭셔리 광고
  c15: 'documentary_calm',  // 인생 화보
  c16: 'horror_gothic',     // 고딕 공포극
  c17: 'epic_war',          // 사막 서부극
  c18: 'tension_suspense',  // 카지노 강탈극
  c19: 'epic_war',          // 재난 생존 드라마
  c20: 'tension_suspense',  // 법정 드라마
  c21: 'family_warm',       // 이민자 가족 서사
  c22: 'dance_kpop',        // 아이돌 그룹 무대
  c23: 'hiphop',            // 록 밴드 라이브
  c24: 'dance_kpop',        // 시티팝 레트로
  c25: 'vocal_ballad',      // 어쿠스틱 버스킹
  c26: 'tension_suspense',  // 사이버펑크 도시
  c27: 'fantasy',           // 이세계 판타지
  c28: 'anime',             // 점토 애니메이션
  c29: 'fantasy',           // 스팀펑크 모험
  c30: 'anime',             // 레트로 게임 감성
  c31: 'celebration',       // 결혼기념일 광고
  c32: 'documentary_calm',  // 스타트업 브랜드 광고
  c33: 'dance_kpop',        // 여행 브이로그 광고
  c34: 'dance_kpop',        // 피트니스 광고
  c35: 'emotional_daily',   // 미식 광고
}

const DEFAULT_MOOD: BgmMood = 'emotional_daily'

/**
 * (AdStudio) 광고 프로젝트의 BGM 무드 자동 선정 — 광고 컨셉[3]의 음악 무드와
 * 컨셉 선택[5]의 톤&무드 조합으로 오마주 음원 풀에서 어울리는 무드를 고른다.
 */
function resolveAdMood(musicMood: string, tone: string): BgmMood {
  if (musicMood === 'corporate') {
    return tone === 'premium' ? 'epic_war' : 'documentary_calm'
  }
  if (musicMood === 'calm') {
    if (tone === 'warm') return 'family_warm'
    if (tone === 'premium') return 'documentary_calm'
    if (tone === 'emotional') return 'emotional_daily'
    return 'emotional_daily'
  }
  // energetic
  if (tone === 'trendy') return 'dance_kpop'
  if (tone === 'humorous') return 'anime'
  if (tone === 'premium') return 'epic_war'
  return 'celebration'
}

/** 문자열을 결정론적으로 정수로 해시한다 — 같은 프로젝트를 다시 렌더링해도 같은 곡이 나오게 한다. */
function hashToIndex(seed: string, count: number): number {
  let h = 0
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) | 0
  return Math.abs(h) % count
}

/**
 * 컨셉 ID로 어울리는 BGM 무드를 찾고, 그 무드 풀 안에서 seed(보통 project.id) 기반으로
 * 한 곡을 결정론적으로 골라 정적 파일 경로를 돌려준다(public/bgm 아래 파일이라 그대로 fetch 가능).
 * 광고 프로젝트(ad_*)는 CONCEPT_BGM_MOOD 대신 음악 무드+톤 조합으로 자동 선정한다.
 */
export function resolveBgmUrl(conceptId: string | undefined, seed: string): string {
  let mood: BgmMood
  if (conceptId?.startsWith('ad_')) {
    // 순환 의존을 피하려고 지연 로드 대신 require 형태가 아닌 동적 접근을 쓰지 않고,
    // adStore는 zustand 단독 모듈이라 정적 import가 안전하다
    const ad = useAdStore.getState()
    mood = resolveAdMood(ad.config.musicMood, ad.adConcept.tone)
  } else {
    mood = (conceptId && CONCEPT_BGM_MOOD[conceptId]) || DEFAULT_MOOD
  }
  const count = BGM_COUNTS[mood]
  const idx = hashToIndex(seed || mood, count) + 1
  return `/bgm/${mood}-${String(idx).padStart(2, '0')}.mp3`
}
