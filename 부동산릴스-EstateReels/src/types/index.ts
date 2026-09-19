// ============================================================
// 부동산릴스 — 전역 타입 정의
// ============================================================

// ── 사용자 & 인증 (선택적 로그인 — HEADJIM 공용 지갑 연동 준비) ──
export interface User {
  uid: string
  email: string
  displayName?: string
  photoURL?: string
  emailVerified?: boolean
  createdAt: Date
}

// ── 매물 정보 (블로그 본문에서 파싱, 사용자 편집 가능) ──
export type DealType = '매매' | '전세' | '월세' | '분양' | '기타'
export type PropertyType = '아파트' | '오피스텔' | '빌라/주택' | '상가/사무실' | '공장·창고' | '토지' | '분양권' | '기타'

// ── 물건 성격 분류 ──
// 카테고리(대분류) — 스토리 컨셉을 이 축으로 필터링한다(주거/상업/산업/토지).
export type PropertyCategory = '아파트' | '주택' | '오피스텔' | '상가' | '공장·창고' | '토지' | '기타'

// 세부 성격(kind) — 카테고리별 구체 물건 유형. hook·컨셉 추천을 미세 조정한다.
export interface PropertyKindDef { id: string; category: PropertyCategory; label: string }
export const PROPERTY_KINDS: PropertyKindDef[] = [
  // 아파트
  { id: 'apt-old', category: '아파트', label: '구축 아파트' },
  { id: 'apt-new', category: '아파트', label: '신축 아파트' },
  { id: 'apt-redev', category: '아파트', label: '재건축·재개발' },
  { id: 'apt-presale', category: '아파트', label: '분양예정 아파트' },
  { id: 'apt-mixed', category: '아파트', label: '주상복합' },
  // 주택
  { id: 'house-new', category: '주택', label: '신축 주택' },
  { id: 'house-country', category: '주택', label: '전원주택' },
  { id: 'house-remodel', category: '주택', label: '리모델링 주택' },
  { id: 'house-multi', category: '주택', label: '단독·다가구' },
  { id: 'house-villa', category: '주택', label: '빌라·연립' },
  // 오피스텔
  { id: 'offi-live', category: '오피스텔', label: '주거용 오피스텔' },
  { id: 'offi-work', category: '오피스텔', label: '업무용 오피스텔' },
  { id: 'offi-presale', category: '오피스텔', label: '분양예정 오피스텔' },
  // 상가
  { id: 'shop-new', category: '상가', label: '신축 상가' },
  { id: 'shop-apt', category: '상가', label: '아파트 단지내 상가' },
  { id: 'shop-mixed', category: '상가', label: '주상복합 상가' },
  { id: 'shop-presale', category: '상가', label: '분양예정 상가' },
  { id: 'shop-house', category: '상가', label: '상가주택' },
  { id: 'shop-resi', category: '상가', label: '주택가 상가' },
  { id: 'shop-center', category: '상가', label: '중심·근린상가' },
  { id: 'shop-unit', category: '상가', label: '구분상가' },
  // 공장·창고
  { id: 'fac-new', category: '공장·창고', label: '신축 공장' },
  { id: 'fac-rent', category: '공장·창고', label: '임대 공장' },
  { id: 'fac-presale', category: '공장·창고', label: '분양 공장' },
  { id: 'fac-wh', category: '공장·창고', label: '창고' },
  { id: 'fac-knc', category: '공장·창고', label: '지식산업센터' },
  // 토지
  { id: 'land-plot', category: '토지', label: '대지' },
  { id: 'land-farm', category: '토지', label: '경작지(전·답)' },
  { id: 'land-dev', category: '토지', label: '개발부지' },
  { id: 'land-forest', category: '토지', label: '산지·임야' },
  { id: 'land-plan', category: '토지', label: '계획관리·창고부지' },
]

/** PropertyType → 컨셉 필터용 카테고리. */
export function categoryOf(pt: PropertyType): PropertyCategory {
  switch (pt) {
    case '아파트': return '아파트'
    case '오피스텔': return '오피스텔'
    case '빌라/주택': return '주택'
    case '상가/사무실': return '상가'
    case '공장·창고': return '공장·창고'
    case '토지': return '토지'
    case '분양권': return '아파트'
    default: return '기타'
  }
}

export interface ListingInfo {
  title: string           // 매물 대표 타이틀 (예: "송파 헬리오시티 84㎡")
  dealType: DealType
  priceText: string       // 원문 그대로의 가격 표기 (예: "매매 21억", "보증금 1억/월 250")
  propertyType: PropertyType
  areaText: string        // 면적 (예: "84㎡ (34평)")
  rooms: string           // 방/욕실 (예: "방3 · 욕실2")
  floorText: string       // 층 (예: "중층 (12/25층)")
  direction: string       // 향 (예: "남향")
  region: string          // 지역/동 (예: "서울 송파구 가락동")
  station: string         // 가까운 역 (예: "8호선 송파역")
  walkText: string        // 도보 (예: "도보 5분")
  schools: string[]       // 학군/학교
  amenities: string[]     // 편의시설 (마트·공원·병원 등)
  features: string[]      // 셀링 포인트 (올수리·풀옵션·저층·확장 등)
  investPoints: string[]  // 투자 포인트/호재 (재건축·GTX·개발 등)
  manageText: string      // 관리비
  moveInText: string      // 입주 가능
  contact: string         // 문의/연락처
  listingNo: string       // 매물번호(시리즈 카탈로그용, 예: "1532" / "H190")
  summary: string         // 한 줄 요약

  // ── 물건 성격 & 상가·공장·토지 전용 추가 정보(선택) ──
  kind: string            // 세부 성격 id (PROPERTY_KINDS, 예: 'apt-new' / 'shop-apt')
  yieldText: string       // 수익률·임대수익 (예: "수익률 5.2%", "보증금 5천 / 월 250")
  zoningText: string      // 용도지역·지목 (예: "제2종일반주거", "계획관리지역", "지목: 전")
  accessText: string      // 도로·접근성 (예: "6m 도로 접함", "서울외곽순환 IC 5분", "대로변")
  footfallText: string    // 유동인구·배후수요 (예: "일 유동 2만", "배후 3,200세대")
  usageText: string       // 추천/현 업종·용도 (예: "카페·병원 적합", "제조·물류")
}

export function emptyListing(): ListingInfo {
  return {
    title: '', dealType: '매매', priceText: '', propertyType: '아파트',
    areaText: '', rooms: '', floorText: '', direction: '', region: '',
    station: '', walkText: '', schools: [], amenities: [], features: [],
    investPoints: [], manageText: '', moveInText: '', contact: '', listingNo: '', summary: '',
    kind: '', yieldText: '', zoningText: '', accessText: '', footfallText: '', usageText: '',
  }
}

// ── 블로그 원본 & 사진 ──
// 이미지 카테고리 — Gemini 비전이 분류하고, AI 스토리보드가 씬에 맞게 배치하는 기준
export type ImageCategory =
  | '외관' | '거실' | '주방' | '침실' | '욕실' | '뷰' | '평면도' | '지도' | '주변' | '단지' | '기타'

export const IMAGE_CATEGORIES: ImageCategory[] =
  ['외관', '거실', '주방', '침실', '욕실', '뷰', '평면도', '지도', '주변', '단지', '기타']

export interface BlogImage {
  id: string
  src: string          // blob: / data: URL (ffmpeg가 바로 fetch 가능한 동일출처 소스)
  width: number
  height: number
  selected: boolean    // 영상에 쓸지 여부
  category?: ImageCategory  // Gemini 비전 분석 결과 (없으면 미분석)
  note?: string             // 이미지 한 줄 설명 (분석 결과)
}

export interface BlogSource {
  url: string
  title: string
  rawText: string
  fetchedVia: 'url' | 'paste' | 'helper'
}

// ── 컨셉 & 설정 ──
// 컨셉 종류가 유형(주거/상업/산업/토지)별로 많아져, 문자열 id로 둔다(정의는 estateConcepts.CONCEPTS가 단일 진실).
export type ConceptId = string

export type DurationSec = 30 | 60 | 180
export type Aspect = '9:16' | '1:1' | '16:9'
export type VoiceGender = 'female' | 'male'

export interface RenderConfig {
  conceptId: ConceptId
  duration: DurationSec
  aspect: Aspect
  subtitles: boolean       // 자막(캡션 카드) 굽기
  narration: boolean       // 나레이션 음성(Gemini TTS) 합성
  voice: VoiceGender
  showContact: boolean     // 마지막 컷에 연락처 노출
  aiMode: boolean          // AI 자동 구성(Gemini 스토리·이미지분석·배치) 사용 여부
}

// ── AI 스토리보드 스크립트 (Gemini가 생성) ──
// 각 컷의 문구·나레이션과, 이 컷에 어울리는 사진 카테고리(배치 기준)를 담는다.
export interface AiScene {
  role: SceneRole
  caption: string          // 화면 메인 문구
  sub?: string             // 보조 문구
  narration: string        // 나레이션 대사
  wantCategory?: ImageCategory  // 이 컷에 배치할 사진 카테고리
}

// ── 스토리보드 & 씬 ──
export type KenBurns = 'in' | 'out' | 'left' | 'right' | 'up'
export type SceneRole = 'hook' | 'point' | 'cta'

export interface EstateScene {
  id: string
  seq: number
  role: SceneRole
  photoId: string | null   // 배정된 사진 (없으면 그라디언트 배경 카드)
  caption: string          // 화면 메인 문구
  sub?: string             // 보조 문구
  badge?: string           // 좌상단 배지 (예: "역세권", "급매")
  narration?: string       // 나레이션 대사 (자막과 별개)
  duration: number         // 초
  kenBurns: KenBurns
}

export interface Storyboard {
  conceptId: ConceptId
  aspect: Aspect
  totalSec: number
  scenes: EstateScene[]
}

// ── 렌더 결과 ──
export interface RenderOutput {
  id: string               // 이 영상 고유 id — 다운로드 결제 멱등·재다운로드 무료 판별용
  url: string
  durationSec: number
  aspect: Aspect
  hasSubtitles: boolean
  hasNarration: boolean
  hasBgm: boolean
}
