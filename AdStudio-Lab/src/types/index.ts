// ============================================================
// 사진 오마주 영상 웹앱 — 전역 타입 정의
// v3.0 BYOK · Firebase · PayPal
// ============================================================

// ── 사용자 & 인증 ───────────────────────────────────────────

export type AuthProvider = 'google' | 'apple' | 'email'

// 앱 UI·영상 콘텐츠(대사·음성·자막) 공용 언어 설정 — Edge TTS가 실제 지원 확인된 10개 언어로 한정
export type AppLocale = 'ko' | 'en' | 'zh' | 'es' | 'hi' | 'pt' | 'it' | 'de' | 'ja' | 'fr'

export interface User {
  uid: string
  email: string
  displayName?: string
  photoURL?: string
  locale: AppLocale
  createdAt: Date
}

export type Plan = 'free' | 'basic' | 'pro'

export interface Entitlement {
  plan: Plan
  source?: 'paypal_sub' | 'paypal_lifetime'
  paypalId?: string
  status?: 'active' | 'cancelled' | 'expired'
  renewedAt?: Date
  expiresAt?: Date
}

// ── API 키 & BYOK ────────────────────────────────────────────

export type ProviderKey =
  | 'alibaba'
  | 'seedance'
  | 'hailuo'
  | 'kling'
  | 'veo'
  | 'runway'
  | 'gemini'
  | 'kaggle'

// 무료 AI 영상 레인의 품질 선택 — kaggle_ltx: 내 Kaggle GPU에서 LTX 오픈소스 실행(저품질·느림·무료),
// alibaba: 알리바바 Wan 무료 쿼터(중품질·빠름·포인트 차감)
export type FreeAiProvider = 'alibaba' | 'kaggle_ltx'

export interface KeyStatus {
  provider: ProviderKey
  isSet: boolean
  isValid: boolean | null // null = 아직 검증 안 함
  validatedAt?: Date
}

export interface QuotaInfo {
  provider: ProviderKey
  estimatedSecondsUsed: number
  totalFreeSeconds?: number // 알리바바: 1650초
  expiryDays?: number
  // Gemini 전용 — 무료 티어가 "초"가 아니라 "하루 요청 수"로 리셋되는 쿼터라 별도 필드로 추적한다.
  // 이미지 생성(gemini-2.5-flash-image)과 검증·캡션·번역 등 텍스트/비전 호출(gemini-2.5-flash)은
  // 구글 쪽 일일 한도가 서로 달라 카운터를 나눈다. geminiQuotaDate(태평양 시간 'YYYY-MM-DD')가
  // 오늘과 다르면 두 카운터 모두 리셋된 것으로 취급한다(keysStore.getGeminiUsageToday 참고).
  geminiImageRequestsToday?: number
  geminiTextRequestsToday?: number
  geminiQuotaDate?: string
}

// ── 프로젝트 & 사진 ──────────────────────────────────────────

export type Relation =
  | 'solo'
  | 'couple'
  | 'married'
  | 'family'
  | 'siblings'
  | 'friends'

export interface Photo {
  id: string
  file?: File
  previewUrl: string
  width: number
  height: number
  faces: FaceDetection[]
}

export interface FaceLandmarks {
  rightEye: { x: number; y: number }
  leftEye: { x: number; y: number }
  nose: { x: number; y: number }
  mouth: { x: number; y: number }
  rightEar: { x: number; y: number }
  leftEar: { x: number; y: number }
}

export interface FaceDetection {
  id: string
  bbox: { x: number; y: number; w: number; h: number } // 0~1 정규화 (사진 기준)
  confidence: number
  landmarks?: FaceLandmarks
  yaw?: number       // 도(deg), 랜드마크 기하 추정치
  pitch?: number     // 도(deg), 랜드마크 기하 추정치
  roll?: number      // 도(deg), 눈 기울기 기준
  sharpness?: number // face_ref 크롭의 Laplacian variance (원값)
  score?: number      // P2 주인공 스코어 0~1
  isBackground?: boolean // 배경 인물(기본 비표시) 여부
  isStarPick?: boolean   // 주인공 자동 제안(★) 여부
  cropUrl?: string       // face_ref 미리보기
}

// 대사 음성 톤 — 성별별 실제 TTS 보이스 매핑은 voiceService.ts 참고
export type VoiceStyle = 'calm' | 'bright' | 'husky_deep' | 'warm_soft'

// 인물별 체형·의상 컨셉 — 지정 시 사진 속 실제 모습 대신 이 컨셉으로 그려진다('none'/미지정이면
// 사진 그대로). storyboardGenerator.ts의 getBodyConceptModifier/getOutfitConceptModifier 참고
export type BodyConcept = 'none' | 'slim' | 'athletic' | 'medium' | 'curvy' | 'sturdy' | 'petite' | 'tall'
export type OutfitConcept =
  | 'none' | 'noir' | 'hanbok' | 'enlightenment_vintage' | 'fantasy_dress'
  | 'youth_casual' | 'office' | 'street_performance' | 'high_fashion' | 'victorian' | 'artdeco_jazz'

export interface Person {
  id: string
  label: string // 예: "person_1"
  gender?: 'male' | 'female' | 'unknown'
  ageBand?: 'child' | 'teen' | 'adult' | 'senior'
  voiceStyle?: VoiceStyle // 이 인물의 기본 대사 음성 톤 (S2에서 지정, 모든 씬에 일관 적용)
  bodyConcept?: BodyConcept
  outfitConcept?: OutfitConcept
  faceId: string
  cropUrl?: string        // face_ref (1024², 정렬됨)
  halfBodyUrl?: string    // half_body_ref (배경 원본 유지 — 매팅은 후속 단계)
  quality?: { score: number; facePx: number; blur: number; yaw: number }
  gateResults?: GateCheckItem[] // P-게이트 결과 (P-01/02/03/10)
  sourcePhotoId?: string
}

// ── 컨셉 & 스타일 ────────────────────────────────────────────

export type Genre = 'film' | 'drama' | 'mv' | 'animation' | 'ad'

export interface Concept {
  id: string
  genre: Genre
  nameKo: string
  nameEn: string
  thumbnailUrl: string
  relations: Relation[]
}

export type StyleId =
  | 'cinematic'
  | 'film_grain'
  | 'documentary'
  | 'toon_3d'
  | 'anime_jp'
  | 'bw'
  | 'cyberpunk'
  | 'watercolor'
  | 'retro_vhs'
  | 'hifashion'

export type DialogueMode = 'auto' | 'manual' | 'none'

// 배경 컨셉 — 씬이 펼쳐지는 공간/장소의 성격
export type BackgroundConcept =
  | 'none'
  | 'hightech_city'
  | 'dystopian_cyberpunk'
  | 'majestic_mountains'
  | 'vast_plains'
  | 'ocean_resort'
  | 'wellness_sanctuary'
  | 'corporate_interview'
  | 'luxury_office'

// 자연현상 컨셉 — 씬에 곁들일 날씨·천체·자연 현상 연출
export type NaturalPhenomenon =
  | 'none'
  | 'aurora'
  | 'milky_way'
  | 'solar_eclipse'
  | 'meteor_shower'
  | 'dense_mist'
  | 'downpour'
  | 'serene_snowfall'
  | 'light_shafts'
  | 'bioluminescence'
  | 'golden_hour'
  | 'lightning'
  | 'volcanic_eruption'
  | 'severe_storm'
  | 'blossom_blizzard'
  | 'fiery_autumn'
  | 'desert_sand_wind'

// ── 스토리보드 & 씬 ──────────────────────────────────────────

export interface StoryboardMeta {
  title: string
  bgmMood: string
  aspect: '9:16' | '16:9' | '1:1'
}

export interface Scene {
  id: string
  seq: number
  duration: number // 초 (2~4)
  descKo: string
  keyframePromptEn: string
  originalKeyframePromptEn?: string // 최초 AI 생성 프롬프트 스냅샷 (되돌리기용, 생성 시 1회만 설정)
  motionPromptEn: string
  dialogueKo?: string
  subjectRefs: string[] // person IDs
  speakerId?: string // 이 씬 대사의 화자(Person id/label) — 미지정 시 subjectRefs[0]
  voiceOverride?: { gender?: 'male' | 'female'; ageBand?: Person['ageBand']; voiceStyle?: VoiceStyle } // "이 씬만 톤 다르게"
  keyframeUrl?: string
  videoUrl?: string
  gateResults?: GateResult[]
  status: SceneStatus
  regenCount: number
}

export type SceneStatus =
  | 'pending'
  | 'generating_keyframe'
  | 'keyframe_done'
  | 'in_queue'
  | 'generating_video'
  | 'video_done'
  | 'done'
  | 'failed'
  | 'blocked'

// ── 품질 게이트 ──────────────────────────────────────────────

export type GateLevel = 'pass' | 'warn' | 'fail' | 'blocked'

export interface GateCheckItem {
  code: string
  level: 'pass' | 'warn' | 'fail' | 'blocked'
  messageKo: string
  suggestionKo?: string
  autoFix?: { field: string; patch: string }
}

export interface GateResult {
  gate: 0 | 1 | 2 | 3 | 4
  sceneId: string
  verdict: 'pass' | 'regenerate' | 'blocked'
  checks: GateCheckItem[]
}

// ── 레인 & 렌더 ─────────────────────────────────────────────

export type Lane = 'moving_photo' | 'free_ai' | 'premium'
export type PremiumTier = 'seedance' | 'hailuo' | 'kling' | 'veo' | 'runway'

export interface RenderRequest {
  projectId: string
  lane: Lane
  tier?: PremiumTier
}

export interface RenderResult {
  id: string
  projectId: string
  lane: Lane
  tier?: PremiumTier
  videoUrl: string
  durationSec: number
  createdAt: Date
}

// ── 잡 & 큐 ─────────────────────────────────────────────────

export type JobKind = 'keyframe' | 'video' | 'merge'
export type JobStatus =
  | 'pending'
  | 'processing'
  | 'done'
  | 'failed'
  | 'retrying'

export interface Job {
  id: string
  sceneId?: string
  kind: JobKind
  lane: Lane
  provider?: string
  status: JobStatus
  queuePosition?: number
  estimatedMinutes?: number
  retryCount: number
  error?: string
  createdAt: Date
  doneAt?: Date
}

// ── 프로젝트 종합 ────────────────────────────────────────────

export type ProjectStatus =
  | 'draft'
  | 'storyboard'
  | 'editing'
  | 'rendering'
  | 'done'
  | 'failed'

export interface Project {
  id: string
  userId: string
  status: ProjectStatus
  relation: Relation
  conceptId: string
  styleId: StyleId
  backgroundId?: BackgroundConcept
  phenomenonId?: NaturalPhenomenon
  durationSec: number
  dialogueMode: DialogueMode
  aspect: '9:16'
  consentAt?: Date
  createdAt: Date
  selectedLane?: Lane
  selectedGenre?: Genre
  // 유튜브 오마주 모드로 만든 광고의 참고 영상 id (설계 §8 "참고 영상 링크 기록") — 저작권 이의
  // 발생 시 어떤 광고가 어떤 영상을 오마주했는지 서버에서 추적할 수 있게 한다. 오마주가 아니거나
  // (템플릿 모드) 설명 입력 방식(HomageReference.source === 'description')으로 만든 오마주는
  // 실제 영상이 없어 undefined다.
  homageVideoId?: string
  // "내 작업" 목록 썸네일용 소형 이미지(약 200px) — 원본 사진과 별개로 저장돼 목록 조회 시
  // 사진 서브컬렉션을 추가로 읽지 않아도 되게 한다
  thumbUrl?: string
  // 클라이언트 로컬 참조
  photos?: Photo[]
  persons?: Person[]
  storyboard?: StoryboardMeta
  scenes?: Scene[]
  renders?: RenderResult[]
}

// ── 비용 견적 ────────────────────────────────────────────────

export interface CostEstimate {
  tier: PremiumTier
  pricePerScene: number // USD
  totalScenes: number
  totalUsd: number
}

// ── 공유 ─────────────────────────────────────────────────────

export interface ShareInfo {
  url: string
  title: string
  description: string
}
