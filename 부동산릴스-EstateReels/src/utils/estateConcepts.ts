// ════════════════════════════════════════════════════════════════
// 부동산릴스 — 물건 성격(아파트·주택·오피스텔·상가·공장·토지)별 스토리 컨셉 엔진
//   컨셉 = 특정 니즈로 매물을 바라보는 "각도" + 문구 톤(voice) + 포인트 배열 + BGM 무드
//   각 컨셉은 categories(어울리는 물건 카테고리)를 달고, Concept 화면이 이 축으로 필터링한다.
//   leadHooks/narrationHook을 컨셉 안에 두어(자기완결), hooks.ts·narration.ts가 그대로 가져다 쓴다.
// storyboard.ts가 이 정의 + 파싱된 ListingInfo로 씬 시퀀스를 만든다.
// ════════════════════════════════════════════════════════════════
import type { ConceptId, ListingInfo, PropertyCategory } from '../types'
import type { BgmMood } from '../services/bgmService'

// 한 컷의 콘텐츠 포인트 (사실 문구 main + 컨셉 보이스 sub)
export interface ConceptPoint {
  key: string
  main: string
  sub?: string
  badge?: string
}

export interface ConceptDef {
  id: ConceptId
  emoji: string
  label: string
  need: string          // 소비자 니즈 한 줄 (카드에 노출)
  desc: string          // 컨셉 설명
  accent: string        // 배지·강조 색
  bgmMood: BgmMood
  hookBadge: string     // 오프닝 배지
  categories: PropertyCategory[]  // 이 컨셉이 어울리는 물건 카테고리(필터 기준)
  kinds?: string[]      // 특히 추천되는 세부 성격 id (있으면 그 물건에서 우선 추천)
  // 오프닝(hook) 문구
  hook: (i: ListingInfo) => { main: string; sub?: string }
  // 오프닝 훅 후보들(검증된 훅 공식 — 질문/충격숫자/급매/경고). hooks.ts가 사용.
  leadHooks: (i: ListingInfo) => string[]
  // 나레이션 도입 멘트(자막을 반복하지 않는 음성 대사). narration.ts가 사용.
  narrationHook: (i: ListingInfo) => string
  // 이 컨셉이 강조할 포인트 순서 (있는 정보만 씬이 된다)
  pointOrder: PointKey[]
  // 포인트별 컨셉 보이스(보조 문구) — 같은 사실도 컨셉마다 다르게 읽히게 한다
  voice: Partial<Record<PointKey, string>>
  // 마무리(cta) 문구
  cta: (i: ListingInfo) => { main: string; sub?: string }
}

export type PointKey =
  | 'price' | 'location' | 'station' | 'school' | 'size' | 'floor'
  | 'amenity' | 'feature' | 'invest' | 'manage' | 'moveIn' | 'value'
  | 'yield' | 'zoning' | 'access' | 'footfall' | 'usage' | 'land'

// ── 사실 포인트 빌더 — 정보가 있으면 1개 이상의 컷 문구를 만든다 ──
const nz = (s?: string) => !!s && s.trim().length > 0

const POINT_BUILDERS: Record<PointKey, (i: ListingInfo) => ConceptPoint[]> = {
  price: (i) => nz(i.priceText) ? [{ key: 'price', main: i.priceText, badge: i.dealType }] : [],
  value: (i) => nz(i.priceText) ? [{ key: 'value', main: i.priceText, badge: '가격' }] : [],
  location: (i) => {
    const main = [i.region, i.propertyType].filter(nz).join(' ') || i.title
    return nz(main) ? [{ key: 'location', main }] : []
  },
  station: (i) => {
    const main = [i.station, i.walkText].filter(nz).join(' ')
    return nz(main) ? [{ key: 'station', main, badge: '역세권' }] : []
  },
  school: (i) => i.schools.filter(nz).slice(0, 3).map((s, k) => ({ key: `school${k}`, main: s, badge: '학군' })),
  size: (i) => {
    const main = [i.areaText, i.rooms].filter(nz).join(' · ')
    return nz(main) ? [{ key: 'size', main }] : []
  },
  floor: (i) => {
    const main = [i.floorText, i.direction].filter(nz).join(' · ')
    return nz(main) ? [{ key: 'floor', main }] : []
  },
  amenity: (i) => i.amenities.filter(nz).slice(0, 4).map((s, k) => ({ key: `amenity${k}`, main: s, badge: '생활인프라' })),
  feature: (i) => i.features.filter(nz).slice(0, 5).map((s, k) => ({ key: `feature${k}`, main: s })),
  invest: (i) => i.investPoints.filter(nz).slice(0, 4).map((s, k) => ({ key: `invest${k}`, main: s, badge: '투자포인트' })),
  manage: (i) => nz(i.manageText) ? [{ key: 'manage', main: `관리비 ${i.manageText}` }] : [],
  moveIn: (i) => nz(i.moveInText) ? [{ key: 'moveIn', main: `입주 ${i.moveInText}`, badge: '입주' }] : [],
  // ── 상가·공장·토지 전용 ──
  yield: (i) => nz(i.yieldText) ? [{ key: 'yield', main: i.yieldText, badge: '수익률' }] : [],
  zoning: (i) => nz(i.zoningText) ? [{ key: 'zoning', main: i.zoningText, badge: '용도지역' }] : [],
  access: (i) => {
    const main = nz(i.accessText) ? i.accessText : [i.station, i.walkText].filter(nz).join(' ')
    return nz(main) ? [{ key: 'access', main, badge: '접근성' }] : []
  },
  footfall: (i) => nz(i.footfallText) ? [{ key: 'footfall', main: i.footfallText, badge: '유동인구' }] : [],
  usage: (i) => nz(i.usageText) ? [{ key: 'usage', main: i.usageText, badge: '업종·용도' }] : [],
  land: (i) => nz(i.areaText) ? [{ key: 'land', main: i.areaText, badge: '대지' }] : [],
}

/** 컨셉의 pointOrder를 따라 실제 존재하는 정보만 컷 포인트로 펼친다(보이스 sub 부착). */
export function buildConceptPoints(def: ConceptDef, info: ListingInfo): ConceptPoint[] {
  const out: ConceptPoint[] = []
  const seen = new Set<string>()
  for (const key of def.pointOrder) {
    const pts = POINT_BUILDERS[key](info)
    for (const p of pts) {
      const dedup = `${key}:${p.main}`
      if (seen.has(dedup)) continue
      seen.add(dedup)
      out.push({ ...p, sub: p.sub ?? def.voice[key] })
    }
  }
  return out
}

const fne = (...xs: string[]) => xs.find(x => x && x.trim().length > 0)?.trim() || ''

// ════════════════════════════════════════════════════════════════
// 컨셉 정의 — 주거(아파트·주택·오피스텔) / 상가 / 공장·창고 / 토지
// ════════════════════════════════════════════════════════════════
export const CONCEPTS: ConceptDef[] = [
  // ───────────────────────── 주거 공통(아파트·주택·오피스텔) ─────────────────────────
  {
    id: 'transit', emoji: '🚇', label: '역세권·입지', need: '“출퇴근·이동 편한가요?”',
    desc: '교통·접근성을 앞세워 이동이 편한 입지를 강조', accent: '#3f6fc4', bgmMood: 'documentary_calm',
    hookBadge: '역세권', categories: ['아파트', '오피스텔', '주택'],
    hook: (i) => ({ main: fne(i.station && `${i.station} ${i.walkText}`.trim(), i.region, i.title), sub: '이동이 편한 입지의 조건' }),
    leadHooks: (i) => [nz(i.station) ? `${i.station} ${i.walkText || ''} 실화?`.trim() : '출퇴근 이게 되네요', '이 입지, 놓치기 아깝습니다'],
    narrationHook: (i) => `출퇴근이 편한 집을 찾으신다면, ${fne(i.region, i.title, '이 매물')} 지금부터 함께 살펴볼게요.`,
    pointOrder: ['station', 'location', 'size', 'floor', 'amenity', 'feature', 'price', 'moveIn'],
    voice: {
      station: '교통 걱정 없는 하루의 시작', location: '누구나 알아보는 확실한 입지',
      size: '실속 있는 공간 구성', amenity: '걸어서 누리는 편의', price: '이 입지에 이 조건',
    },
    cta: (i) => ({ main: '이 입지, 놓치기 아깝습니다', sub: fne(i.contact, '지금 문의하세요') }),
  },
  {
    id: 'school', emoji: '🏫', label: '학군·교육환경', need: '“아이 키우기 좋은가요?”',
    desc: '학교·학원가·안전을 앞세운 학부모 타깃', accent: '#10b981', bgmMood: 'family_warm',
    hookBadge: '학세권', categories: ['아파트', '주택', '오피스텔'],
    hook: (i) => ({ main: fne(i.schools[0], i.region, i.title), sub: '아이와 함께 자라는 동네' }),
    leadHooks: (i) => ['아이 키우기, 여기라면', nz(i.schools[0]) ? `${i.schools[0]} 품은 집` : '학군까지 챙긴 집'],
    narrationHook: () => '아이 키우기 좋은 동네를 찾고 계셨다면, 이 집을 눈여겨보세요.',
    pointOrder: ['school', 'location', 'station', 'amenity', 'size', 'feature', 'price', 'moveIn'],
    voice: {
      school: '가까운 배움의 거리', location: '가족이 살기 좋은 자리', amenity: '아이 동선까지 안심',
      size: '가족을 위한 넉넉한 공간', price: '교육환경까지 이 조건',
    },
    cta: (i) => ({ main: '아이의 내일이 달라지는 집', sub: fne(i.contact, '지금 문의하세요') }),
  },
  {
    id: 'invest', emoji: '💰', label: '투자가치·미래', need: '“오를 만한가요?”',
    desc: '개발호재·미래가치·시세 흐름을 앞세운 투자자 타깃', accent: '#eec269', bgmMood: 'documentary_calm',
    hookBadge: '투자포인트', categories: ['아파트', '오피스텔', '주택'],
    hook: (i) => ({ main: fne(i.investPoints[0], i.region, i.title), sub: '숫자가 말해주는 미래가치' }),
    leadHooks: (i) => [nz(i.investPoints[0]) ? `${i.investPoints[0]}, 지금이 진입 타이밍?` : '숫자가 말해주는 미래가치'],
    narrationHook: () => '미래가치가 궁금하셨다면, 이 매물의 진짜 이유를 함께 짚어드릴게요.',
    pointOrder: ['invest', 'price', 'location', 'station', 'size', 'moveIn', 'feature'],
    voice: {
      invest: '지금 주목받는 이유', price: '진입 시점을 만드는 가격', location: '수요가 탄탄한 자리',
      station: '가치를 받쳐주는 교통', size: '환금성 좋은 구성',
    },
    cta: (i) => ({ main: '기회는 준비된 사람의 것', sub: fne(i.contact, '지금 상담받으세요') }),
  },
  {
    id: 'interior', emoji: '🏠', label: '내부·구조', need: '“집 상태 어떤가요?”',
    desc: '평면·채광·옵션·수리상태 등 실내를 앞세움', accent: '#c084fc', bgmMood: 'emotional_daily',
    hookBadge: '내부컨디션', categories: ['아파트', '주택', '오피스텔'],
    hook: (i) => ({ main: fne(i.title, i.region), sub: '들어서는 순간 느껴지는 공간감' }),
    leadHooks: (i) => ['들어서면 공간감이 다릅니다', nz(i.features[0]) ? `${i.features[0]}, 직접 보면 압니다` : '이 구조, 처음입니다'],
    narrationHook: () => '문을 여는 순간 느껴지는 공간감, 지금 안으로 들어가 보겠습니다.',
    pointOrder: ['size', 'floor', 'feature', 'amenity', 'manage', 'price', 'moveIn'],
    voice: {
      size: '실사용 편한 구조', floor: '채광과 전망까지', feature: '살아보면 아는 디테일',
      manage: '합리적인 유지비', price: '이 컨디션에 이 가격',
    },
    cta: (i) => ({ main: '직접 보면 더 좋은 집', sub: fne(i.contact, '방문 예약하세요') }),
  },
  {
    id: 'living', emoji: '🌳', label: '생활환경·편의', need: '“살기 편한가요?”',
    desc: '마트·공원·병원·상권 등 일상 편의를 앞세움', accent: '#34d399', bgmMood: 'family_warm',
    hookBadge: '생활인프라', categories: ['아파트', '주택', '오피스텔'],
    hook: (i) => ({ main: fne(i.region, i.title), sub: '걸어서 누리는 편리한 일상' }),
    leadHooks: () => ['걸어서 다 되는 동네', '살기 편한 게 곧 삶의 질'],
    narrationHook: () => '걸어서 다 되는 편리한 일상, 바로 이 동네에서 시작됩니다.',
    pointOrder: ['amenity', 'location', 'station', 'school', 'size', 'feature', 'price'],
    voice: {
      amenity: '문 열면 펼쳐지는 생활권', location: '하루가 편해지는 동네', station: '어디든 편한 교통',
      school: '가족 모두를 위한 환경', size: '일상에 딱 맞는 공간',
    },
    cta: (i) => ({ main: '편리함이 곧 삶의 질', sub: fne(i.contact, '지금 문의하세요') }),
  },
  {
    id: 'complex', emoji: '🏢', label: '단지·브랜드', need: '“어떤 단지인가요?”',
    desc: '브랜드·규모·커뮤니티·조경 등 단지 프리미엄을 앞세움', accent: '#6f97dd', bgmMood: 'documentary_calm',
    hookBadge: '프리미엄 단지', categories: ['아파트'], kinds: ['apt-mixed'],
    hook: (i) => ({ main: fne(i.title, i.region), sub: '格이 다른 단지의 품격' }),
    leadHooks: () => ['이름값 하는 단지', '格이 다른 단지의 품격'],
    narrationHook: () => '격이 다른 단지의 품격, 지금부터 하나씩 소개해 드릴게요.',
    pointOrder: ['location', 'feature', 'amenity', 'size', 'floor', 'station', 'price'],
    voice: {
      location: '이름값 하는 자리', feature: '단지가 주는 프리미엄', amenity: '단지 안에서 누리는 여유',
      size: '품격 있는 공간', price: '가치에 걸맞은 조건',
    },
    cta: (i) => ({ main: '살아보면 아는 단지의 격', sub: fne(i.contact, '지금 문의하세요') }),
  },
  {
    id: 'deal', emoji: '⚡', label: '급매·가격강조', need: '“지금 사면 이득인가요?”',
    desc: '급매·한정·시세대비 강점을 속도감 있게 어필', accent: '#f0637a', bgmMood: 'celebration',
    hookBadge: '급매', categories: ['아파트', '주택', '오피스텔', '상가', '공장·창고', '토지'],
    hook: (i) => ({ main: fne(i.priceText, i.title), sub: '이 가격, 지금이 아니면' }),
    leadHooks: (i) => {
      const sp = i.priceText.replace(/^(매매|전세|분양가|보증금)\s*/, '').trim()
      return [
        nz(sp) ? `${sp} 급매, 지금이 아니면` : '지금 아니면 못 잡는 급매',
        '이 가격 놓치면 후회합니다', '이 조건, 오늘 지나면 없어요',
        nz(sp) ? `${sp}?! 이건 잡아야죠` : '이건 무조건 잡아야죠',
      ]
    },
    narrationHook: () => '이런 조건은 자주 나오지 않습니다. 놓치기 전에 지금 확인하세요.',
    pointOrder: ['value', 'location', 'station', 'size', 'floor', 'feature', 'moveIn'],
    voice: {
      value: '시세보다 확실한 메리트', location: '입지까지 놓치지 않은 매물', station: '교통도 합격',
      size: '실속까지 챙긴 구성', feature: '이 조건에 이 가격이라니', moveIn: '바로 들어갈 수 있어요',
    },
    cta: (i) => ({ main: '먼저 연락하는 분이 임자', sub: fne(i.contact, '지금 바로 전화주세요') }),
  },
  {
    id: 'lifestyle', emoji: '🌅', label: '감성·라이프스타일', need: '“여기서 어떻게 살까?”',
    desc: '뷰·분위기·사는 모습을 감성적으로 그려냄', accent: '#f6d488', bgmMood: 'emotional_daily',
    hookBadge: 'LIFESTYLE', categories: ['아파트', '주택', '오피스텔'],
    hook: (i) => ({ main: fne(i.title, i.region), sub: '이곳에서 시작될 당신의 하루' }),
    leadHooks: () => ['여기서 살면 이런 하루', '이 뷰, 이 분위기 실화?'],
    narrationHook: () => '이곳에서 펼쳐질 당신의 하루를, 잠시 상상해 보세요.',
    pointOrder: ['floor', 'feature', 'amenity', 'size', 'location', 'station', 'price'],
    voice: {
      floor: '창밖으로 담기는 풍경', feature: '매일이 특별해지는 이유', amenity: '여유가 있는 동네',
      size: '나를 위한 공간', location: '살고 싶은 자리', price: '이 삶의 값',
    },
    cta: (i) => ({ main: '당신의 일상을 초대합니다', sub: fne(i.contact, '지금 문의하세요') }),
  },

  // ───────────────────────── 주거 세부(신축·구축·분양·전원·리모델링) ─────────────────────────
  {
    id: 'newbuild', emoji: '✨', label: '신축·새것의 가치', need: '“새 집 그대로인가요?”',
    desc: '한 번도 살지 않은 새것의 컨디션과 최신 설계를 강조', accent: '#8ab4f8', bgmMood: 'documentary_calm',
    hookBadge: '신축', categories: ['아파트', '주택', '오피스텔'], kinds: ['apt-new', 'house-new'],
    hook: (i) => ({ main: fne(i.title, i.region), sub: '한 번도 살지 않은 새것 그대로' }),
    leadHooks: () => ['한 번도 안 산 새 집', '신축 프리미엄, 지금 선점', '요즘 신축은 다릅니다'],
    narrationHook: () => '한 번도 살지 않은 새 집의 컨디션, 지금 안에서 보여드릴게요.',
    pointOrder: ['feature', 'size', 'floor', 'station', 'amenity', 'moveIn', 'price'],
    voice: {
      feature: '최신 설계의 디테일', size: '군더더기 없는 신축 구조', floor: '요즘 감각의 채광',
      moveIn: '입주만 하면 되는 컨디션', price: '신축인데 이 조건',
    },
    cta: (i) => ({ main: '새것의 가치를 먼저 잡으세요', sub: fne(i.contact, '지금 문의하세요') }),
  },
  {
    id: 'redevelop', emoji: '🏗️', label: '재건축·재개발 기대', need: '“앞으로 오를까요?”',
    desc: '노후 단지의 사업성·미래가치를 앞세운 투자 시선', accent: '#e0a94a', bgmMood: 'documentary_calm',
    hookBadge: '재건축', categories: ['아파트', '주택'], kinds: ['apt-old', 'apt-redev'],
    hook: (i) => ({ main: fne(i.investPoints[0], i.region, i.title), sub: '지금 사두는 미래가치' }),
    leadHooks: (i) => [nz(i.investPoints[0]) ? `${i.investPoints[0]} 기대` : '지금 사두는 미래가치', '낡았지만 이유가 있습니다', '재건축, 시간이 값을 만듭니다'],
    narrationHook: () => '지금은 낡았지만, 이 집이 주목받는 진짜 이유를 짚어드릴게요.',
    pointOrder: ['invest', 'value', 'location', 'station', 'size', 'feature'],
    voice: {
      invest: '사업이 그리는 미래', value: '지금의 진입 가격', location: '수요가 받쳐주는 자리',
      station: '가치를 더하는 교통', size: '실사용도 괜찮은 구성',
    },
    cta: (i) => ({ main: '미래가치를 지금의 가격에', sub: fne(i.contact, '지금 상담받으세요') }),
  },
  {
    id: 'presale', emoji: '📢', label: '분양·선점 혜택', need: '“지금 분양 받을까요?”',
    desc: '분양 일정·동호수 선점·프리미엄 기대를 앞세움', accent: '#f0a45a', bgmMood: 'celebration',
    hookBadge: '분양', categories: ['아파트', '오피스텔', '상가', '공장·창고'], kinds: ['apt-presale', 'offi-presale', 'shop-presale', 'fac-presale'],
    hook: (i) => ({ main: fne(i.region, i.title), sub: '좋은 자리는 먼저 계약합니다' }),
    leadHooks: (i) => ['분양 시작, 지금이 선점 타이밍', nz(i.region) ? `${i.region} 분양 소식` : '좋은 자리는 먼저 계약합니다', '분양가, 지금이 가장 쌉니다'],
    narrationHook: () => '분양 일정과 지금 계약해야 하는 이유를, 핵심만 정리해 드릴게요.',
    pointOrder: ['value', 'location', 'feature', 'station', 'size', 'moveIn'],
    voice: {
      value: '지금이 가장 좋은 조건', location: '분양가치가 받쳐지는 입지', feature: '설계로 앞서는 상품성',
      station: '분양의 값을 더하는 교통', moveIn: '입주 시점의 프리미엄',
    },
    cta: (i) => ({ main: '좋은 동호수는 지금 정해집니다', sub: fne(i.contact, '분양 상담 받으세요') }),
  },
  {
    id: 'house', emoji: '🌲', label: '단독·전원 생활', need: '“마당 있는 집, 어떤가요?”',
    desc: '단독의 프라이버시·마당·자연을 감성적으로', accent: '#6b9e63', bgmMood: 'emotional_daily',
    hookBadge: '단독', categories: ['주택'], kinds: ['house-country', 'house-multi', 'house-new'],
    hook: (i) => ({ main: fne(i.region, i.title), sub: '층간소음 없는 나만의 집' }),
    leadHooks: (i) => ['마당 있는 삶, 상상해보셨나요?', '층간소음 없는 나만의 집', nz(i.region) ? `${i.region}에서의 단독 생활` : '아파트에선 못 누리는 여유'],
    narrationHook: () => '마당과 프라이버시가 있는 단독의 하루를, 잠시 그려보세요.',
    pointOrder: ['size', 'feature', 'floor', 'location', 'amenity', 'price'],
    voice: {
      size: '넉넉한 나만의 공간', feature: '단독이라 가능한 자유', floor: '사방으로 트인 채광',
      location: '조용히 살기 좋은 자리', price: '이 여유에 이 가격',
    },
    cta: (i) => ({ main: '나만의 마당이 있는 집', sub: fne(i.contact, '방문 예약하세요') }),
  },
  {
    id: 'remodel', emoji: '🛠️', label: '리모델링·새집효과', need: '“수리는 다 됐나요?”',
    desc: '올수리·새집효과로 바로 입주 가능한 컨디션', accent: '#b98be6', bgmMood: 'emotional_daily',
    hookBadge: '올수리', categories: ['주택', '아파트'], kinds: ['house-remodel'],
    hook: (i) => ({ main: fne(i.title, i.region), sub: '들어와서 손댈 게 없어요' }),
    leadHooks: (i) => ['수리 걱정 끝, 바로 입주', '새집 같은 구축', nz(i.features[0]) ? `${i.features[0]} 완료` : '들어와서 손댈 게 없어요'],
    narrationHook: () => '집 안 곳곳을 새로 손봐서, 들어오자마자 바로 생활하실 수 있어요.',
    pointOrder: ['feature', 'size', 'floor', 'amenity', 'moveIn', 'price'],
    voice: {
      feature: '새것처럼 바꾼 디테일', size: '깔끔하게 정돈된 구조', moveIn: '입주만 하면 끝', price: '수리비까지 아끼는 가격',
    },
    cta: (i) => ({ main: '수리 걱정 없는 집', sub: fne(i.contact, '지금 문의하세요') }),
  },

  // ───────────────────────── 상가 ─────────────────────────
  {
    id: 'footfall', emoji: '🚶', label: '유동인구·상권', need: '“사람이 얼마나 다니나요?”',
    desc: '유동인구·상권 활성도로 매출 잠재력을 강조', accent: '#e8894a', bgmMood: 'celebration',
    hookBadge: '핵심상권', categories: ['상가', '오피스텔'],
    hook: (i) => ({ main: fne(i.footfallText, i.region, i.title), sub: '지나는 사람이 곧 매출입니다' }),
    leadHooks: (i) => [nz(i.footfallText) ? `${i.footfallText}, 매출이 다릅니다` : '하루 유동인구가 다릅니다', '지나는 사람이 곧 매출입니다', nz(i.region) ? `${i.region} 핵심 상권` : '이 자리, 사람이 모입니다'],
    narrationHook: () => '이 자리를 하루에 얼마나 많은 사람이 지나는지, 상권부터 짚어드릴게요.',
    pointOrder: ['footfall', 'access', 'usage', 'location', 'value', 'feature'],
    voice: {
      footfall: '매출로 이어지는 발길', access: '어디서든 닿는 접근성', usage: '어울리는 업종이 명확',
      location: '검증된 상권의 힘', value: '이 상권에 이 조건',
    },
    cta: (i) => ({ main: '좋은 자리는 매출로 답합니다', sub: fne(i.contact, '수익 상담 받으세요') }),
  },
  {
    id: 'yield', emoji: '💵', label: '임대수익·수익률', need: '“수익률이 얼마죠?”',
    desc: '월 임대료·수익률 등 현금흐름 관점', accent: '#e2b93b', bgmMood: 'documentary_calm',
    hookBadge: '수익형', categories: ['상가', '오피스텔', '공장·창고'],
    hook: (i) => ({ main: fne(i.yieldText, i.priceText, i.title), sub: '통장에 꽂히는 임대수익' }),
    leadHooks: (i) => [nz(i.yieldText) ? `${i.yieldText}, 요즘 흔치 않죠` : '월세가 만드는 현금흐름', '통장에 꽂히는 임대수익', '수익률로 증명하는 물건'],
    narrationHook: () => '매달 들어오는 임대수익과 수익률을, 숫자로 정리해 드릴게요.',
    pointOrder: ['yield', 'value', 'usage', 'access', 'footfall', 'location'],
    voice: {
      yield: '매달 들어오는 현금흐름', value: '수익 대비 좋은 가격', usage: '안정적인 임차 업종',
      access: '임차 수요를 부르는 입지', footfall: '공실 걱정 줄이는 상권',
    },
    cta: (i) => ({ main: '숫자가 증명하는 수익형', sub: fne(i.contact, '수익률 상담 받으세요') }),
  },
  {
    id: 'tenant', emoji: '🏪', label: '업종·MD 적합', need: '“어떤 장사가 될까요?”',
    desc: '이 자리에 맞는 업종·MD 구성을 제안', accent: '#df7b52', bgmMood: 'family_warm',
    hookBadge: '업종추천', categories: ['상가'],
    hook: (i) => ({ main: fne(i.usageText, i.region, i.title), sub: '장사가 되는 자리엔 이유가 있죠' }),
    leadHooks: (i) => [nz(i.usageText) ? `이 자리엔 ${i.usageText}` : '이 자리엔 이 업종입니다', '장사가 되는 자리엔 이유가 있죠', '업종만 맞으면 대박 자리'],
    narrationHook: () => '이 자리에 어떤 업종이 잘 어울리는지, 상권에 맞춰 제안드릴게요.',
    pointOrder: ['usage', 'footfall', 'access', 'location', 'value', 'feature'],
    voice: {
      usage: '자리에 딱 맞는 업종', footfall: '업종을 받쳐줄 수요', access: '손님이 찾기 쉬운 위치',
      location: '검증된 장사 자리', value: '권리 대비 좋은 조건',
    },
    cta: (i) => ({ main: '자리가 업종을 만듭니다', sub: fne(i.contact, '창업 상담 받으세요') }),
  },
  {
    id: 'visibility', emoji: '📍', label: '코너·간판노출', need: '“눈에 잘 띄나요?”',
    desc: '코너·대로변·간판 노출 등 시인성을 강조', accent: '#d9633f', bgmMood: 'celebration',
    hookBadge: '코너자리', categories: ['상가'],
    hook: (i) => ({ main: fne(i.accessText, i.region, i.title), sub: '지나가다 저절로 보이는 자리' }),
    leadHooks: (i) => ['눈에 띄어야 손님이 옵니다', '지나가다 저절로 보이는 자리', nz(i.accessText) ? `${i.accessText} 노출 상가` : '간판이 사는 코너 자리'],
    narrationHook: () => '멀리서도 눈에 들어오는 이 자리의 노출과 간판 효과를 보여드릴게요.',
    pointOrder: ['access', 'footfall', 'usage', 'location', 'value'],
    voice: {
      access: '멀리서도 보이는 노출', footfall: '노출이 만드는 유입', usage: '간판 효과 큰 업종',
      location: '지나칠 수 없는 자리', value: '노출값 하는 조건',
    },
    cta: (i) => ({ main: '보이는 자리가 이깁니다', sub: fne(i.contact, '지금 문의하세요') }),
  },
  {
    id: 'anchor', emoji: '🏘️', label: '배후수요·독점', need: '“고정 손님이 있나요?”',
    desc: '단지·주택가 배후세대를 고정 수요로 강조', accent: '#e08a5b', bgmMood: 'family_warm',
    hookBadge: '독점상권', categories: ['상가'], kinds: ['shop-apt', 'shop-mixed', 'shop-resi'],
    hook: (i) => ({ main: fne(i.footfallText, i.region, i.title), sub: '고정 손님이 있는 상가' }),
    leadHooks: (i) => [nz(i.footfallText) ? `${i.footfallText}, 통째로 고객입니다` : '단지가 통째로 고객입니다', '배후수요가 받쳐주는 자리', '경쟁 없는 독점 자리'],
    narrationHook: () => '이 상가를 받쳐주는 배후 세대와 고정 수요를, 숫자로 짚어드릴게요.',
    pointOrder: ['footfall', 'usage', 'access', 'location', 'yield', 'value'],
    voice: {
      footfall: '단지가 만드는 고정 수요', usage: '생활밀착 업종에 최적', access: '단지 동선 위의 자리',
      location: '경쟁 적은 독점 입지', yield: '공실 걱정 적은 수익',
    },
    cta: (i) => ({ main: '고정 수요가 있는 자리', sub: fne(i.contact, '수익 상담 받으세요') }),
  },

  // ───────────────────────── 공장·창고 ─────────────────────────
  {
    id: 'logistics', emoji: '🚚', label: '물류·접근성', need: '“물류가 편한가요?”',
    desc: 'IC·간선도로·항만 접근 등 물류 효율을 강조', accent: '#5f83a6', bgmMood: 'documentary_calm',
    hookBadge: '물류입지', categories: ['공장·창고'], kinds: ['fac-wh', 'fac-rent', 'fac-new'],
    hook: (i) => ({ main: fne(i.accessText, i.region, i.title), sub: '물류비를 줄이는 입지' }),
    leadHooks: (i) => [nz(i.accessText) ? `${i.accessText}, 물류가 빠릅니다` : 'IC 코앞, 물류가 빠릅니다', '트럭이 편한 자리', '접근성이 곧 경쟁력'],
    narrationHook: () => '고속도로와 간선 접근성 등, 물류 효율을 좌우하는 입지부터 짚어드릴게요.',
    pointOrder: ['access', 'usage', 'size', 'zoning', 'value', 'yield'],
    voice: {
      access: '물류비를 줄이는 접근성', usage: '제조·물류에 적합', size: '작업 동선 넉넉한 규모',
      zoning: '용도까지 맞는 부지', value: '입지 대비 좋은 가격',
    },
    cta: (i) => ({ main: '물류가 빠른 자리', sub: fne(i.contact, '지금 문의하세요') }),
  },
  {
    id: 'spec', emoji: '🏭', label: '용도·설비 스펙', need: '“우리 공정에 맞나요?”',
    desc: '전력·층고·바닥하중·용도지역 등 스펙 적합성', accent: '#6b8e8e', bgmMood: 'documentary_calm',
    hookBadge: '스펙', categories: ['공장·창고'], kinds: ['fac-new', 'fac-knc'],
    hook: (i) => ({ main: fne(i.usageText, i.title, i.region), sub: '바로 가동 가능한 공장' }),
    leadHooks: (i) => ['스펙부터 다릅니다', nz(i.usageText) ? `${i.usageText}에 맞는 설비` : '전력·층고 걱정 끝', '바로 가동 가능한 공장'],
    narrationHook: () => '전력, 층고, 바닥하중, 용도지역까지 — 공정에 필요한 스펙을 정리해 드릴게요.',
    pointOrder: ['usage', 'zoning', 'size', 'access', 'feature', 'value'],
    voice: {
      usage: '공정에 맞는 용도', zoning: '허가에 유리한 용도지역', size: '설비가 들어가는 규모',
      access: '자재·출하 편한 입지', feature: '갖춰진 설비',
    },
    cta: (i) => ({ main: '바로 가동할 수 있는 공장', sub: fne(i.contact, '스펙 상담 받으세요') }),
  },

  // ───────────────────────── 토지 ─────────────────────────
  {
    id: 'zoning', emoji: '🗺️', label: '용도지역·개발', need: '“뭘 지을 수 있나요?”',
    desc: '용도지역·건폐율/용적률 등 개발 가능성을 강조', accent: '#7a9a5b', bgmMood: 'documentary_calm',
    hookBadge: '용도지역', categories: ['토지'], kinds: ['land-plot', 'land-plan', 'land-dev'],
    hook: (i) => ({ main: fne(i.zoningText, i.region, i.title), sub: '지을 수 있어야 진짜 땅값' }),
    leadHooks: (i) => [nz(i.zoningText) ? `${i.zoningText}, 뭘 지을 수 있을까?` : '용도지역이 값을 만듭니다', '개발 가능한 땅', '지을 수 있어야 진짜 땅값'],
    narrationHook: () => '이 땅에 무엇을 지을 수 있는지, 용도지역과 개발 가능성부터 짚어드릴게요.',
    pointOrder: ['zoning', 'land', 'access', 'invest', 'value', 'usage'],
    voice: {
      zoning: '개발을 여는 용도지역', land: '쓸모 있는 대지 규모', access: '값을 올리는 도로 조건',
      invest: '주변이 그리는 미래', value: '개발가치 대비 가격',
    },
    cta: (i) => ({ main: '지을 수 있는 땅의 가치', sub: fne(i.contact, '개발 상담 받으세요') }),
  },
  {
    id: 'roadaccess', emoji: '🛣️', label: '도로·접근성', need: '“길이 닿나요?”',
    desc: '도로 접함·폭·진입 등 토지의 기본 값', accent: '#8a8a4a', bgmMood: 'documentary_calm',
    hookBadge: '도로접함', categories: ['토지'],
    hook: (i) => ({ main: fne(i.accessText, i.region, i.title), sub: '맹지 아닙니다, 도로 접함' }),
    leadHooks: (i) => [nz(i.accessText) ? `${i.accessText}, 길이 닿는 땅` : '길이 닿는 땅입니다', '맹지 아닙니다, 도로 접함', '도로가 곧 땅값'],
    narrationHook: () => '땅값을 좌우하는 도로 조건 — 접함, 폭, 진입까지 확인해 드릴게요.',
    pointOrder: ['access', 'zoning', 'land', 'invest', 'value'],
    voice: {
      access: '가치를 여는 도로 조건', zoning: '활용 가능한 용도', land: '반듯한 대지',
      invest: '길 따라 오르는 가치', value: '입지 대비 가격',
    },
    cta: (i) => ({ main: '길이 닿는 땅', sub: fne(i.contact, '지금 문의하세요') }),
  },
  {
    id: 'landvalue', emoji: '📈', label: '개발·시세차익', need: '“오를 땅인가요?”',
    desc: '개발 호재·주변 확장으로 시세차익 기대', accent: '#c9a24a', bgmMood: 'documentary_calm',
    hookBadge: '개발호재', categories: ['토지'], kinds: ['land-dev'],
    hook: (i) => ({ main: fne(i.investPoints[0], i.region, i.title), sub: '지금의 밭이 내일의 대지' }),
    leadHooks: (i) => [nz(i.investPoints[0]) ? `${i.investPoints[0]}, 지금이 진입 타이밍` : '오를 자리에 미리 사두는 땅', '개발이 그리는 미래', '지금의 밭이 내일의 대지'],
    narrationHook: () => '주변 개발과 확장으로 이 땅이 오를 이유를, 하나씩 짚어드릴게요.',
    pointOrder: ['invest', 'zoning', 'access', 'land', 'value'],
    voice: {
      invest: '가치를 끌어올릴 호재', zoning: '전환 가능성 있는 용도', access: '개발을 부르는 도로',
      land: '규모 있는 부지', value: '미래가치 대비 가격',
    },
    cta: (i) => ({ main: '오를 자리를 미리', sub: fne(i.contact, '투자 상담 받으세요') }),
  },
  {
    id: 'farm', emoji: '🌾', label: '경작·실사용', need: '“농사지을 수 있나요?”',
    desc: '경작지·주말농장 등 실사용 가치를 강조', accent: '#8fa85a', bgmMood: 'family_warm',
    hookBadge: '경작지', categories: ['토지'], kinds: ['land-farm'],
    hook: (i) => ({ main: fne(i.region, i.title), sub: '바로 농사지을 수 있는 땅' }),
    leadHooks: (i) => ['바로 농사지을 수 있는 땅', '주말농장으로 딱', nz(i.zoningText) ? `${i.zoningText} 경작지` : '땅 밟고 사는 즐거움'],
    narrationHook: () => '바로 농사짓거나 주말농장으로 쓰기 좋은 이 땅의 쓸모를 보여드릴게요.',
    pointOrder: ['land', 'zoning', 'access', 'feature', 'value'],
    voice: {
      land: '넉넉한 경작 면적', zoning: '농사에 맞는 지목', access: '오가기 편한 진입',
      feature: '물·볕 좋은 조건', value: '실사용에 딱 맞는 가격',
    },
    cta: (i) => ({ main: '밟고 누리는 나의 땅', sub: fne(i.contact, '지금 문의하세요') }),
  },
  {
    id: 'forest', emoji: '⛰️', label: '산지·전망', need: '“자연을 품나요?”',
    desc: '임야·산지의 전망·규모·개발 잠재를 강조', accent: '#6b8e5a', bgmMood: 'emotional_daily',
    hookBadge: '산지·임야', categories: ['토지'], kinds: ['land-forest'],
    hook: (i) => ({ main: fne(i.region, i.title), sub: '자연을 통째로 품은 땅' }),
    leadHooks: (i) => ['자연을 통째로 품은 땅', nz(i.region) ? `${i.region} 임야` : '전망이 값을 만듭니다', '넓게 사두는 미래'],
    narrationHook: () => '탁 트인 전망과 넓은 규모 — 이 산지가 품은 가능성을 보여드릴게요.',
    pointOrder: ['land', 'zoning', 'access', 'invest', 'value'],
    voice: {
      land: '광활한 규모', zoning: '활용 여지 있는 지목', access: '접근 가능한 진입로',
      invest: '길게 보는 가치', value: '평당 부담 적은 가격',
    },
    cta: (i) => ({ main: '넓게 품는 자연', sub: fne(i.contact, '지금 문의하세요') }),
  },
]

export const CONCEPT_BY_ID: Record<string, ConceptDef> =
  Object.fromEntries(CONCEPTS.map(c => [c.id, c]))

export function getConcept(id: ConceptId): ConceptDef {
  return CONCEPT_BY_ID[id] ?? CONCEPTS[0]
}

export function conceptIdList(): ConceptId[] {
  return CONCEPTS.map(c => c.id)
}

/** 카테고리에 맞는 컨셉들(그 카테고리를 categories에 포함). */
export function conceptsForCategory(cat: PropertyCategory): ConceptDef[] {
  const list = CONCEPTS.filter(c => c.categories.includes(cat))
  return list.length ? list : CONCEPTS.filter(c => c.categories.includes('아파트'))
}

// ════════════════════════════════════════════════════════════════
// 대분류(그룹) — 25개 컨셉을 4개 대분류로 묶어 보여준다(Home 아코디언).
//   대분류만 노출하고, 선택하면 그 안의 소분류(컨셉)를 펼친다.
//   각 컨셉을 딱 하나의 대분류에 배치(카테고리 필터와 달리 중복 없음).
// ════════════════════════════════════════════════════════════════
export type ConceptGroup = '주거' | '상가' | '공장·창고' | '토지'
export interface ConceptGroupDef {
  id: ConceptGroup
  emoji: string
  label: string
  desc: string
  conceptIds: ConceptId[]  // 이 대분류에 속한 컨셉(순서=표시 순서). 새 컨셉 추가 시 여기에도 넣을 것.
}
export const CONCEPT_GROUP_DEFS: ConceptGroupDef[] = [
  {
    id: '주거', emoji: '🏘️', label: '주거 — 아파트·주택·오피스텔',
    desc: '역세권·학군·투자·급매부터 신축·재건축·분양·전원·리모델링까지',
    conceptIds: ['transit', 'school', 'invest', 'interior', 'living', 'complex', 'deal', 'lifestyle', 'newbuild', 'redevelop', 'presale', 'house', 'remodel'],
  },
  {
    id: '상가', emoji: '🏪', label: '상가 — 수익형',
    desc: '유동인구·수익률·업종·코너노출·배후수요',
    conceptIds: ['footfall', 'yield', 'tenant', 'visibility', 'anchor'],
  },
  {
    id: '공장·창고', emoji: '🏭', label: '공장·창고 — 산업',
    desc: '물류 접근성·용도/설비 스펙',
    conceptIds: ['logistics', 'spec'],
  },
  {
    id: '토지', emoji: '⛰️', label: '토지 — 개발·실사용',
    desc: '용도지역·도로·개발차익·경작·산지',
    conceptIds: ['zoning', 'roadaccess', 'landvalue', 'farm', 'forest'],
  },
]

/** 대분류에 속한 컨셉 정의들(표시 순서대로). */
export function conceptsByGroup(id: ConceptGroup): ConceptDef[] {
  const g = CONCEPT_GROUP_DEFS.find(x => x.id === id)
  return g ? g.conceptIds.map(cid => CONCEPT_BY_ID[cid]).filter(Boolean) : []
}

/** 물건정보로 추천 기본 컨셉 id — 세부성격(kind) 특화 > 유형 대표 컨셉 > 범용(급매/분양) 순. */
export function recommendConcept(cat: PropertyCategory, kind: string): ConceptId {
  const pool = conceptsForCategory(cat)
  if (kind) {
    const kindHit = pool.find(c => c.kinds?.includes(kind))
    if (kindHit) return kindHit.id
  }
  // 범용 컨셉(급매·분양)은 기본값으로 두지 않고, 그 유형을 대표하는 특화 컨셉을 우선한다.
  const GENERIC = new Set(['deal', 'presale'])
  const specific = pool.find(c => !GENERIC.has(c.id))
  return (specific || pool[0])?.id ?? 'transit'
}
