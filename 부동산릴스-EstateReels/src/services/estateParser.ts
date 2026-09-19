// ════════════════════════════════════════════════════════════════
// 부동산 블로그 본문 → 매물정보(ListingInfo) 휴리스틱 파서
// 완벽 추출이 목표가 아니라 "편집 출발점"을 만드는 게 목표 — 사용자가 리뷰 화면에서 고친다.
// (하이브리드: 여기서 뽑은 초안을 선택적으로 AI로 다듬을 수 있다 — services/aiEnhance.ts)
// ════════════════════════════════════════════════════════════════
import type { ListingInfo, DealType, PropertyType, PropertyCategory } from '../types'
import { emptyListing, categoryOf } from '../types'

const uniq = (arr: string[]) => Array.from(new Set(arr.map(s => s.trim()).filter(Boolean)))
const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n).trim() + '…' : s.trim())

function firstMatch(text: string, re: RegExp): string {
  const m = text.match(re)
  return m ? (m[1] ?? m[0]).trim() : ''
}

function scanKeywords(text: string, keywords: string[]): string[] {
  const found: string[] = []
  for (const k of keywords) if (text.includes(k)) found.push(k)
  return found
}

// ── 가격 추출 — 거래유형별로 자연스러운 표기를 만든다 ──
function extractPrice(text: string, deal: DealType): string {
  const t = text.replace(/\s+/g, ' ')
  // 억 + (선택) 천/백만 단위 — "21억 5,000만원"처럼 콤마가 섞여도 잡는다
  const eok = String.raw`[0-9]{1,3}\s*억(?:\s*[0-9][0-9,]{0,5}\s*(?:만원|만)?)?`
  const man = String.raw`[0-9]{2,4}\s*(?:만원|만)`

  if (deal === '월세') {
    const dep = firstMatch(t, new RegExp(String.raw`보증금\s*(${eok}|${man})`))
    const rent = firstMatch(t, new RegExp(String.raw`(?:월세|월)\s*([0-9]{2,4})\s*(?:만원|만)?`))
    if (dep || rent) return `보증금 ${dep || '-'} / 월 ${rent || '-'}`.replace(/\s*-\s*/g, '- ')
  }
  if (deal === '전세') {
    const p = firstMatch(t, new RegExp(String.raw`전세\s*(?:가)?\s*(${eok}|${man})`)) || firstMatch(t, new RegExp(String.raw`보증금\s*(${eok})`))
    if (p) return `전세 ${p}`
  }
  // 매매/분양/기타
  const p = firstMatch(t, new RegExp(String.raw`(?:매매|분양|가격)\s*(?:가)?\s*(${eok})`)) || firstMatch(t, new RegExp(eok))
  if (p) return `${deal === '분양' ? '분양가' : '매매'} ${p}`
  return ''
}

// 제목(주제) 가중 스코어링으로 부동산 유형을 판별한다. 단순 언급에 휘둘리지 않게.
function classifyPropertyType(title: string, flat: string): PropertyType {
  const T = ' ' + (title || '').replace(/\s+/g, ' ') + ' '
  const B = ' ' + flat + ' '
  const cnt = (re: RegExp, s: string) => (s.match(new RegExp(re, 'gi')) || []).length
  const score = (re: RegExp, w = 1) => (cnt(re, T) * 3 + cnt(re, B)) * w
  const scores: [PropertyType, number][] = [
    ['공장·창고', score(/공장|지식산업센터|지산|물류센터|제조시설/) + score(/창고/, 0.5)],
    ['상가/사무실', score(/상가|점포|근린생활|근생/) + score(/사무실/, 0.5)],
    ['토지', score(/토지|임야|전답|농지|잡종지|산지|경작|맹지|개발부지|대지|부지|필지|형질변경|용도지역/)],
    ['오피스텔', score(/오피스텔/)],
    ['아파트', score(/아파트/)],
    ['빌라/주택', score(/빌라|다세대|연립|단독|전원주택|다가구|주택/)],
    ['분양권', score(/분양권|입주권/)],
  ]
  // 동점이면 주거 우선(언급으로 흔한 상가·토지보다 실제 주제일 확률이 높은 순서)
  const order: PropertyType[] = ['아파트', '오피스텔', '빌라/주택', '상가/사무실', '공장·창고', '토지', '분양권']
  let best: PropertyType = '아파트', bestScore = 0
  for (const [t, s] of scores) {
    if (s > bestScore || (s === bestScore && s > 0 && order.indexOf(t) < order.indexOf(best))) { best = t; bestScore = s }
  }
  return bestScore > 0 ? best : '아파트'
}

// 역명 추출 — '지역/관리지역/주거지역'처럼 '역'으로 끝나는 일반어를 걸러낸다.
function extractStation(flat: string): string {
  const withLine = flat.match(/([0-9]{1,2}호선|신분당선|경의중앙선|공항철도|수인분당선|경춘선|GTX[-\s]?[A-C])\s*([가-힣A-Za-z0-9]{2,10}?역)(?![가-힣])/)
  if (withLine) return `${withLine[1]} ${withLine[2]}`.replace(/\s+/g, ' ').trim()
  const STOP = /지역|구역|권역|영역|유역|해역|병역|면역|역세|역할|역량|이력|경력|내역|역대|가역|역행|졸업/
  for (const m of flat.matchAll(/([가-힣A-Za-z0-9]{2,10}?역)(?![가-힣])/g)) {
    if (!STOP.test(m[1])) return m[1]
  }
  return ''
}

// 카테고리 안에서 키워드로 세부 성격(kind) id를 추론한다(없으면 '').
function inferKind(flat: string, cat: PropertyCategory): string {
  const has = (re: RegExp) => re.test(flat)
  switch (cat) {
    case '아파트':
      if (has(/재건축|재개발/)) return 'apt-redev'
      if (has(/분양\s*예정|분양예정|청약|입주자\s*모집/)) return 'apt-presale'
      if (has(/주상복합/)) return 'apt-mixed'
      if (has(/신축|준신축/)) return 'apt-new'
      if (has(/구축/)) return 'apt-old'
      return ''
    case '주택':
      if (has(/전원주택|전원/)) return 'house-country'
      if (has(/리모델링|올수리/)) return 'house-remodel'
      if (has(/다가구|단독/)) return 'house-multi'
      if (has(/빌라|연립|다세대/)) return 'house-villa'
      if (has(/신축/)) return 'house-new'
      return ''
    case '오피스텔':
      if (has(/분양\s*예정|분양예정|청약/)) return 'offi-presale'
      if (has(/업무용|사무|섹션오피스/)) return 'offi-work'
      return 'offi-live'
    case '상가':
      if (has(/분양\s*예정|분양예정|선분양/)) return 'shop-presale'
      if (has(/단지\s*내|아파트\s*상가|단지상가/)) return 'shop-apt'
      if (has(/주상복합/)) return 'shop-mixed'
      if (has(/상가주택/)) return 'shop-house'
      if (has(/구분상가/)) return 'shop-unit'
      if (has(/중심상가|근린상가|근린생활/)) return 'shop-center'
      if (has(/주택가/)) return 'shop-resi'
      if (has(/신축/)) return 'shop-new'
      return ''
    case '공장·창고':
      if (has(/지식산업센터|지산/)) return 'fac-knc'
      if (has(/창고|물류센터/)) return 'fac-wh'
      if (has(/분양/)) return 'fac-presale'
      if (has(/임대/)) return 'fac-rent'
      if (has(/신축/)) return 'fac-new'
      return ''
    case '토지':
      if (has(/전답|경작|농지|주말농장|지목\s*[:：]?\s*답|답\s*\d|논|밭/)) return 'land-farm'
      if (has(/임야|산지/)) return 'land-forest'
      if (has(/개발\s*부지|개발예정|개발\s*예정/)) return 'land-dev'
      if (has(/계획관리|창고\s*부지/)) return 'land-plan'
      return 'land-plot'
    default:
      return ''
  }
}

export function parseListing(rawText: string, blogTitle = ''): ListingInfo {
  const info = emptyListing()
  const text = rawText.replace(/\r/g, '')
  const flat = text.replace(/\s+/g, ' ')

  // 거래유형
  const deal: DealType =
    /월\s*세|월세/.test(flat) ? '월세'
    : /전\s*세|전세/.test(flat) ? '전세'
    : /분양/.test(flat) ? '분양'
    : /매\s*매|매매|매물/.test(flat) ? '매매'
    : '매매'
  info.dealType = deal

  // 부동산 유형 — 제목 가중 스코어링(제목이 주제를 담으므로 x3). 단순 언급(단지내 상가·배후 아파트)에
  // 휘둘리지 않고 동점이면 주거 우선. 오분류는 리뷰 화면에서 바로 고칠 수 있다.
  info.propertyType = classifyPropertyType(blogTitle, flat)

  // 가격
  info.priceText = extractPrice(flat, deal)

  // 면적 (전용/공급/평)
  const areaParts: string[] = []
  const m2 = firstMatch(flat, /([0-9]{2,3}(?:\.[0-9])?)\s*(?:㎡|m²|m2|제곱미터)/)
  const py = firstMatch(flat, /([0-9]{1,3}(?:\.[0-9])?)\s*평/)
  if (m2) areaParts.push(`${m2}㎡`)
  if (py) areaParts.push(`${py}평`)
  info.areaText = areaParts.join(' / ')

  // 방/욕실
  const roomN = firstMatch(flat, /방\s*([0-9])/) || (/(쓰리|3)\s*룸/.test(flat) ? '3' : /(투|2)\s*룸/.test(flat) ? '2' : /(원|1)\s*룸/.test(flat) ? '1' : '')
  const bathN = firstMatch(flat, /(?:욕실|화장실)\s*([0-9])/)
  info.rooms = [roomN && `방${roomN}`, bathN && `욕실${bathN}`].filter(Boolean).join(' · ')

  // 층
  const floorRange = flat.match(/([0-9]{1,2})\s*\/\s*([0-9]{1,2})\s*층/)
  if (floorRange) info.floorText = `${floorRange[1]}/${floorRange[2]}층`
  else {
    const band = firstMatch(flat, /(저층|중층|고층|로열층|탑층)/)
    const single = firstMatch(flat, /([0-9]{1,2})\s*층/)
    info.floorText = band || (single ? `${single}층` : '')
  }

  // 향
  info.direction = firstMatch(flat, /((?:남동|남서|북동|북서|남|북|동|서))향/)
  if (info.direction) info.direction += '향'

  // 지역
  info.region = firstMatch(flat,
    /(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)[가-힣]*\s*[가-힣]+(?:구|군|시)\s*[가-힣]+(?:동|읍|면|가|로|리)/)
    || firstMatch(flat, /[가-힣]+(?:구|군|시)\s*[가-힣]+(?:동|읍|면)/)

  // 역 / 도보 (일반어 '지역/관리지역' 오인 방지)
  info.station = extractStation(flat)
  const walk = firstMatch(flat, /도보\s*(?:약\s*)?[0-9]{1,2}\s*분/)
  info.walkText = walk || (/역세권|초역세권/.test(flat) ? '역세권' : '')

  // 학교/학군
  info.schools = uniq([
    ...(flat.match(/[가-힣A-Za-z]{2,10}(?:초등학교|중학교|고등학교)/g) || []),
    ...(/학원가/.test(flat) ? ['학원가'] : []),
    ...(/학세권/.test(flat) ? ['학세권'] : []),
  ]).slice(0, 4)

  // 편의시설
  info.amenities = uniq(scanKeywords(flat, [
    '이마트', '홈플러스', '롯데마트', '코스트코', '트레이더스', '백화점', '스타필드', '대형마트', '전통시장',
    '공원', '산책로', '한강', '호수공원', '병원', '대학병원', '스타벅스', '카페거리', '상권', '먹자골목', '문화센터', '도서관',
  ])).slice(0, 6)

  // 셀링 포인트
  info.features = uniq(scanKeywords(flat, [
    '올수리', '리모델링', '풀옵션', '확장형', '확장', '새시', '복층', '테라스', '펜트하우스', '주차', '이중주차',
    '엘리베이터', '남향', '채광', '조망', '한강뷰', '숲세권', '즉시입주', '올확장', '신축', '준신축', '베란다',
  ])).slice(0, 6)

  // 투자 포인트/호재
  info.investPoints = uniq(scanKeywords(flat, [
    '재건축', '재개발', '리모델링 추진', 'GTX', '지하철 개통', '역 신설', '개발호재', '트리플역세권', '더블역세권',
    '학군지', '대단지', '브랜드', '분양 예정', '입주장', '갭투자', '전세가율', '시세차익',
  ])).slice(0, 5)

  // 관리비 / 입주 / 연락처
  info.manageText = firstMatch(flat, /관리비[^0-9]{0,5}([0-9]{1,3}\s*만\s*원?)/)
  info.moveInText = /즉시\s*입주|즉시입주|바로\s*입주/.test(flat) ? '즉시입주'
    : firstMatch(flat, /([0-9]{4}\s*년\s*[0-9]{1,2}\s*월|[0-9]{1,2}\s*월)\s*입주/)
  info.contact = firstMatch(flat, /01[016-9][-.\s]?[0-9]{3,4}[-.\s]?[0-9]{4}/)

  // 매물번호(시리즈) — "매물번호 123" / "NO.1532" / "[H190]"
  info.listingNo = firstMatch(flat, /매물\s*번호\s*[:\-]?\s*([A-Za-z]?\d{1,5})/)
    || firstMatch(flat, /\bNO\s*[.\-]?\s*(\d{2,5})\b/i)
    || firstMatch(flat, /\[\s*(H\d{2,4})\s*\]/)

  // ── 상가·공장·토지 전용 추가 정보(있으면 채운다) ──
  // 수익률·임대수익
  info.yieldText = firstMatch(flat, /수익률\s*(?:연\s*)?[0-9]+(?:\.[0-9]+)?\s*%/)
    || firstMatch(flat, /(?:임대료|월\s*임대)\s*[0-9]{2,4}\s*(?:만원|만)/)
  // 용도지역·지목
  info.zoningText = firstMatch(flat,
    /(제?\s*[1-3]\s*종\s*(?:일반|전용)?\s*주거지역|준주거지역|(?:일반|근린|중심|유통)상업지역|준공업지역|일반공업지역|전용공업지역|(?:계획|생산|보전)관리지역|(?:자연|생산|보전)녹지지역|농림지역|(?:공익용|임업용|보전)?산지)/)
    || firstMatch(flat, /지목\s*[:\-]?\s*(대|전|답|과수원|임야|잡종지|공장용지|창고용지|도로|목장용지)/)
  // 도로·접근성 (IC/도로폭/대로변)
  info.accessText = firstMatch(flat, /[0-9]{1,2}\s*차선?\s*(?:대로|도로)변?/)
    || firstMatch(flat, /[가-힣A-Za-z]{1,8}\s*IC\s*(?:약\s*)?[0-9]{1,2}\s*분/)
    || firstMatch(flat, /(?:폭\s*)?[0-9]{1,2}\s*m\s*도로\s*(?:접|접함|접합)?/)
    || (/대로변|코너|사거리|삼거리/.test(flat) ? firstMatch(flat, /(대로변|코너|사거리|삼거리)/) : '')
  // 유동인구·배후수요
  info.footfallText = firstMatch(flat, /유동\s*인구\s*(?:약\s*)?[0-9][0-9,]*\s*(?:명|만)?/)
    || firstMatch(flat, /배후\s*(?:세대|수요)?\s*(?:약\s*)?[0-9][0-9,]*\s*세대/)
  // 추천/현 업종·용도
  info.usageText = uniq(scanKeywords(flat, [
    '카페', '음식점', '편의점', '병원', '약국', '학원', '헬스장', '미용실', '베이커리',
    '사무실', '제조', '물류', '창고', '판매시설', '근린생활시설',
  ])).slice(0, 3).join('·')

  // 세부 성격(kind) 추론 — 카테고리 안에서 키워드로 좁힌다
  info.kind = inferKind(flat, categoryOf(info.propertyType))

  // 타이틀 / 요약
  const titleGuess = blogTitle.trim() || [info.region, info.propertyType, info.areaText].filter(Boolean).join(' ')
  info.title = clip(titleGuess || '우리 동네 좋은 매물', 40)
  const firstSentence = (flat.split(/[.!?。]\s/)[0] || '').trim()
  info.summary = clip([info.region, info.dealType, info.priceText].filter(Boolean).join(' ') || firstSentence, 60)

  return info
}

/** 파싱 결과에서 실제로 채워진 정보 항목 수 — "얼마나 잘 읽었나" 표시용 */
export function countFilled(i: ListingInfo): number {
  let n = 0
  const keys: (keyof ListingInfo)[] = ['priceText', 'areaText', 'rooms', 'floorText', 'direction', 'region', 'station', 'walkText', 'manageText', 'moveInText', 'contact']
  for (const k of keys) if (typeof i[k] === 'string' && (i[k] as string).trim()) n++
  n += i.schools.length + i.amenities.length + i.features.length + i.investPoints.length
  return n
}
