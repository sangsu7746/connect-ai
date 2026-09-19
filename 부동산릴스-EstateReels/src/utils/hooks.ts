// ════════════════════════════════════════════════════════════════
// 훅·제목 엔진 — 유튜브 매물영상 벤치마킹에서 검증된 "이기는 공식" 적용
//   · 오프닝 훅: 질문·궁금증·충격숫자·급매·혜택형 (조회수를 가르는 첫 문장)
//   · 제목: [훅] │ [숫자·혜택 배지] │ [단지·입지]  (스캔되는 파이프 포맷)
//   · 혜택 배지: 역세권·초품아·올수리·즉시입주·급매 등 데이터에서 뽑아낸 어휘
// 키 없이도 매물정보만으로 동작(템플릿). 있으면 gemini.ts가 더 매끄럽게 다듬는다.
// 원칙: 매물정보에 있는 사실만 사용 — 없는 혜택·가격은 만들지 않는다(허위·과장 금지).
// ════════════════════════════════════════════════════════════════
import type { ListingInfo, ConceptId } from '../types'
import { getConcept } from './estateConcepts'

const nz = (s?: string) => !!s && s.trim().length > 0
const clean = (s: string) => s.replace(/\s{2,}/g, ' ').replace(/\s*│\s*/g, ' │ ').trim()
const uniq = (a: string[]) => Array.from(new Set(a.map(s => s.trim()).filter(Boolean)))

/** 도보 분(예: "도보 5분")에서 숫자만 — 없으면 null */
function walkMinutes(walk: string): number | null {
  const m = walk.match(/(\d{1,2})\s*분/)
  return m ? Number(m[1]) : null
}

/** 매물정보에서 검증된 혜택 배지 어휘를 뽑는다 (최대 5개). */
export function buildBadges(info: ListingInfo, conceptId?: ConceptId): string[] {
  const b: string[] = []
  // 교통
  if (nz(info.station) || nz(info.walkText)) {
    const min = walkMinutes(info.walkText)
    if (min !== null && min <= 5) b.push('초역세권')
    else if (nz(info.walkText) || nz(info.station)) b.push('역세권')
  }
  // 학군 (초등학교 품음)
  if (info.schools.some(s => /초/.test(s))) b.push('초품아')
  else if (info.schools.length) b.push('학세권')
  // 생활/자연
  if ([...info.features, ...info.amenities].some(s => /숲|공원|산책|호수/.test(s))) b.push('숲세권')
  // 상태
  if (info.features.some(s => /올수리|리모델링/.test(s))) b.push('올수리')
  if (info.features.some(s => /풀옵션/.test(s))) b.push('풀옵션')
  if (info.features.some(s => /확장/.test(s))) b.push('확장')
  // 입주
  if (/즉시|바로/.test(info.moveInText)) b.push('즉시입주')
  // 향
  if (/남/.test(info.direction)) b.push('남향')
  // 투자
  const inv = info.investPoints.find(s => /재건축|재개발|GTX|호재|개통|시세차익/.test(s))
  if (inv) b.push(inv.length <= 6 ? inv : '개발호재')
  // 신축 / 분양
  if (/(?:^|-)new$/.test(info.kind) || info.features.some(s => /신축/.test(s))) b.push('신축')
  if (info.kind.endsWith('presale') || info.dealType === '분양') b.push('분양')
  // 상가·공장·토지
  if (nz(info.yieldText) && /%/.test(info.yieldText)) b.push(info.yieldText.match(/수익률\s*[0-9.]+\s*%/)?.[0].replace(/\s+/g, '') || '수익형')
  if (/코너|사거리|삼거리/.test(info.accessText)) b.push('코너')
  else if (/대로변/.test(info.accessText)) b.push('대로변')
  if (/유동|배후/.test(info.footfallText)) b.push('배후수요')
  // 급매(컨셉이 급매일 때)
  if (conceptId === 'deal') b.push('급매')
  return uniq(b).slice(0, 5)
}

/** 면적을 짧게 — "34평" 우선, 없으면 "84㎡" (훅·제목에서 슬래시 중복을 피한다) */
function shortArea(info: ListingInfo): string {
  const py = info.areaText.match(/(\d{1,3}(?:\.\d)?)\s*평/)
  if (py) return `${py[1]}평`
  const m2 = info.areaText.match(/(\d{2,3}(?:\.\d)?)\s*㎡/)
  if (m2) return `${m2[1]}㎡`
  return info.areaText.trim()
}
/** 가격에서 거래유형 접두어를 떼어 짧게 — "매매 21억" → "21억" */
function shortPrice(info: ListingInfo): string {
  return info.priceText.replace(/^(매매|전세|분양가|보증금)\s*/, '').trim()
}

/** 오프닝 훅 후보들 — 컨셉의 리드 훅(leadHooks) + 데이터 기반 범용 훅. */
export function buildHookLines(info: ListingInfo, conceptId: ConceptId): string[] {
  const sp = shortPrice(info)
  const sa = shortArea(info)
  const region = (info.region || info.title).trim()
  const station = info.station.trim()
  const walk = info.walkText.trim()
  const type = info.propertyType

  // 데이터 기반 범용 훅 (충격숫자·질문) — 조사 어색함을 피해 쉼표로 붙인다
  const generic: string[] = []
  if (nz(sa) && nz(sp)) generic.push(`${sa}, ${sp}?!`)
  if (nz(sp)) generic.push('이 가격, 실화인가요?')
  if (nz(station) && nz(walk)) generic.push(`${station} ${walk}, 이 입지 실화?`)
  if (nz(region)) generic.push(`${region} ${type}, 이런 매물 어떠세요?`)
  generic.push('안 보면 후회하는 매물')

  // 컨셉별 리드 훅 — 각 컨셉 정의(estateConcepts) 안에 있다.
  const lead = getConcept(conceptId).leadHooks(info).filter(nz)

  return uniq([...lead, ...generic]).slice(0, 5)
}

/** 제목 후보 3개 — [훅] │ [숫자·혜택] │ [단지·입지]. 훅에 이미 든 정보는 중앙에서 뺀다. */
export function buildTitles(info: ListingInfo, conceptId: ConceptId): string[] {
  const hooks = buildHookLines(info, conceptId)
  const badges = buildBadges(info, conceptId)
  const region = (info.region || info.title).trim()
  const sp = shortPrice(info)
  const sa = shortArea(info)
  // 단지·입지 = 지역 + 짧은 면적(중복 없이)
  const place = clean([region, region.includes(sa) ? '' : sa].filter(Boolean).join(' ')) || info.propertyType

  const badgeMid = badges.slice(0, 2).join('·')
  const priceMid = info.priceText.trim()
  const specMid = [sa, info.rooms].filter(nz).join(' · ')
  // 매물번호 시리즈 태그 — 문자로 시작하면 [H190], 숫자면 [NO.1532]
  const no = info.listingNo.trim()
  const noTag = no ? (/^[A-Za-z]/.test(no) ? ` [${no}]` : ` [NO.${no}]`) : ''

  const titles: string[] = []
  for (let i = 0; i < Math.min(3, hooks.length); i++) {
    const hook = hooks[i]
    const hasPrice = nz(sp) && hook.includes(sp)
    // 중앙부: 훅에 가격이 있으면 배지/스펙을, 없으면 가격을 우선
    const candidates = hasPrice ? [badgeMid, specMid, priceMid] : [priceMid, badgeMid, specMid]
    const mid = candidates.find(m => nz(m) && !hook.includes(m)) || badgeMid || ''
    titles.push(clean([hook, mid, place].filter(Boolean).join(' │ ')) + noTag)
  }
  return uniq(titles).slice(0, 3)
}

export interface Marketing {
  hook: string          // 오프닝 컷에 쓸 강한 훅
  titles: string[]      // 유튜브·블로그·릴스 제목 후보
  badges: string[]      // 혜택 배지
  aiUsed: boolean       // Gemini로 다듬었는지
}

/** 템플릿만으로 마케팅 세트를 만든다(키 불필요). */
export function buildMarketing(info: ListingInfo, conceptId: ConceptId): Marketing {
  const hooks = buildHookLines(info, conceptId)
  return {
    hook: hooks[0] || info.title || '안 보면 후회하는 매물',
    titles: buildTitles(info, conceptId),
    badges: buildBadges(info, conceptId),
    aiUsed: false,
  }
}
