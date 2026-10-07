// ════════════════════════════════════════════════════════════════
// 나레이션(음성) 엔진 — "자막과 겹치지 않는 대사"를 만든다.
//   원칙: 화면(자막)=짧은 사실·키워드를 "보여주고",
//         음성(나레이션)=그 의미를 되풀이하지 않고 구어체 문장으로 "풀어 말한다".
//   (기존엔 narration = caption + sub 를 그대로 이어붙여 화면·음성이 100% 중복됐다.)
// 씬 편집 페이지에서 사용자가 직접 고칠 수 있고, 여기 값은 "좋은 기본값"이다.
// ════════════════════════════════════════════════════════════════
import type { ListingInfo, ConceptId, SceneRole } from '../types'
import { getConcept } from './estateConcepts'

const nz = (s?: string) => !!s && s.trim().length > 0
// 비교용 정규화 — 공백·구두점·구분기호·이모지를 제거해 "사실상 같은 문장"을 잡는다
const norm = (s?: string) =>
  (s || '').replace(/[\s.,!?~·─—–|│…"'`()[\]]/g, '').replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '').toLowerCase()

// ── 포인트(point) 나레이션 — "자막을 그대로 읽지 않는다". ──
// 화면 자막(사실)은 눈으로 보고, 음성은 그 사실이 주는 "이점"을 말한다.
// 이점(b)이 있으면 이점만 문장으로(사실 반복 X). 이점이 없으면 사실을 구어체로 살짝 풀어준다.
// 변수는 명사구로 두고 뒤에 고정 구어체 절을 붙여 조사 어색함을 피한다.
const BENEFIT_FRAMES: ((b: string) => string)[] = [
  (b) => `${b}, 직접 보시면 더 와닿으실 거예요.`,
  (b) => `${b} — 이런 점이 이 매물의 매력이죠.`,
  (b) => `${b}, 살아보면 그 차이가 느껴집니다.`,
  (b) => `${b}, 꼭 눈여겨보세요.`,
]
const FACT_FRAMES: ((f: string) => string)[] = [
  (f) => `${f}, 직접 확인해 보세요.`,
  (f) => `${f} — 놓치기 아까운 포인트입니다.`,
  (f) => `${f}, 이런 조건은 흔치 않습니다.`,
  (f) => `${f}, 실속 있게 챙기실 수 있어요.`,
]

// 화면 자막에서 배지·이모지·군더더기를 걷어낸 "말로 하기 좋은" 사실 문구
function speakableFact(caption: string): string {
  return caption
    .replace(/[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '')
    .replace(/[?!]+/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

export function hookNarration(info: ListingInfo, conceptId: ConceptId): string {
  return getConcept(conceptId).narrationHook(info)
}

export function pointNarration(caption: string, sub: string | undefined, idx: number): string {
  const b = (sub || '').trim().replace(/[.!?]+$/, '')
  // 이점이 있으면 이점만 말한다(자막의 사실을 반복하지 않음). 없으면 사실을 구어체로.
  const out = b
    ? BENEFIT_FRAMES[idx % BENEFIT_FRAMES.length](b)
    : FACT_FRAMES[idx % FACT_FRAMES.length](speakableFact(caption))
  return out.replace(/\s{2,}/g, ' ').trim()
}

export function ctaNarration(info: ListingInfo): string {
  const c = info.contact.trim()
  return c
    ? `자세한 내용과 방문 예약은 ${c}로 편하게 문의 주세요.`
    : '관심 있으시면 지금 바로 연락 주세요. 친절히 안내해 드리겠습니다.'
}

/** 자막(caption/sub)과 나레이션이 "사실상 같은지" 판정 — 편집·재생성 트리거에 쓴다. */
export function isRedundantNarration(caption: string, sub: string | undefined, narration: string): boolean {
  const n = norm(narration)
  if (!n) return true
  const cap = norm(caption), s = norm(sub), both = norm(`${caption} ${sub || ''}`)
  // 자막(또는 자막+보조)과 정규화 결과가 같거나, 나레이션이 자막을 통째로 품고 길이차가 거의 없으면 중복
  if (n === cap || n === s || n === both) return true
  if (cap && n.includes(cap) && n.length - cap.length <= 3) return true
  return false
}

/**
 * 역할·자막·매물정보로 "자막과 겹치지 않는" 나레이션 기본값을 만든다.
 * 이미 만들어진(예: AI) 나레이션이 자막과 중복이면 이 함수로 대체할 수 있다.
 */
export function buildSceneNarration(
  role: SceneRole, caption: string, sub: string | undefined, info: ListingInfo, conceptId: ConceptId, idx: number,
): string {
  if (role === 'hook') return hookNarration(info, conceptId)
  if (role === 'cta') return ctaNarration(info)
  return pointNarration(caption, sub, idx)
}

/**
 * 주어진 나레이션이 자막과 중복이면 겹치지 않는 기본 나레이션으로 교체한다.
 * (AI가 만든 대사가 자막을 그대로 읽는 경우를 방어)
 */
export function ensureDistinct(
  role: SceneRole, caption: string, sub: string | undefined, narration: string | undefined,
  info: ListingInfo, conceptId: ConceptId, idx: number,
): string {
  const n = (narration || '').trim()
  if (n && !isRedundantNarration(caption, sub, n)) return n
  return buildSceneNarration(role, caption, sub, info, conceptId, idx)
}

export { nz }
