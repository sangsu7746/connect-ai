import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { AppLocale } from '../types'

// Gemini 분석 결과 — 광고 컨셉의 원천 데이터
export interface AdAnalysis {
  productName: string
  description: string
  keyFeatures: string[]
  targetAudience: string
  mainBenefit: string
  narration: string        // 나레이션 스크립트 (편집 가능)
  callToAction: string
  tone: 'energetic' | 'calm' | 'professional'
}

// 광고 영상 설정
export interface AdConfig {
  duration: 15 | 30 | 60
  musicMood: 'energetic' | 'calm' | 'corporate'
  voice: 'female' | 'male'
  voiceId?: string             // 사용자가 직접 고른 성우 보이스 ID (없으면 성별 기본값)
  voiceVariety: boolean        // 씬마다 다른 목소리로 읽기
  narrationLocale: AppLocale   // 나레이션·자막 언어 — UI 언어와 별개 (수출용 다국어 광고)
  subtitles: boolean           // 영상에 자막을 넣을지 여부
}

export type ActorMode = 'ai' | 'photo'

// [5] 광고 컨셉 4축 선택 (utils/adConcepts.ts의 분류체계 기준)
export interface AdConceptSelection {
  categoryMain: string   // 대분류 id (예: 'food')
  categorySub: string    // 소분류 id (예: 'fresh')
  emphasis: string[]     // 강조 포인트 id, 최대 2개
  structureId: string    // 스토리 구성 id (ad_*) — project.conceptId로 저장된다
  tone: string           // 톤&무드 id
  visualStyle: string    // 비주얼 스타일(룩) id — 조명·질감의 방향을 정한다
}

const DEFAULT_AD_CONCEPT: AdConceptSelection = {
  categoryMain: '', categorySub: '', emphasis: [], structureId: '', tone: 'energetic',
  visualStyle: 'clean_bright',
}

// AI 가상 배우 기본 프로필 — 값 정의는 utils/adConcepts.ts (AI_ACTOR_*)
export interface AiActorProfile {
  gender: string   // 'female' | 'male'
  age: string      // '20s' | '30s' | '4050' | 'senior'
  vibe: string     // 'friendly' | 'professional' | 'luxury' | 'casual' | 'sporty'
}

const DEFAULT_AI_ACTOR: AiActorProfile = { gender: 'female', age: '30s', vibe: 'friendly' }

// 사진 배우 사용 방식 — 업로드한 사진을 어디까지 참조할지
export interface ActorUsage {
  scope: 'face' | 'half' | 'full'        // 얼굴만 / 상반신(얼굴+체형+의상) / 전신 사진 그대로
  outfit: 'keep' | 'restyle'             // 사진 의상 유지 / 광고에 맞게 AI 스타일링
  background: 'remove' | 'keep'          // 배경 제거하고 배우만 / 사진 배경 분위기 활용
}

const DEFAULT_ACTOR_USAGE: ActorUsage = { scope: 'face', outfit: 'restyle', background: 'remove' }

interface AdState {
  // 1단계: 원본 자료
  sourceText: string
  sourceUrl: string
  // 2단계: 분석 결과
  analysis: AdAnalysis | null
  // 3단계: 영상 설정
  config: AdConfig
  // 4단계: 배우
  actorMode: ActorMode | null
  actorPhotoDataUrl: string | null   // 사진 배우 모드일 때 (data URL)
  aiActor: AiActorProfile            // AI 가상 배우 모드일 때의 기본 프로필
  actorUsage: ActorUsage             // 사진 배우 모드일 때의 사용 방식
  // 5단계: 광고 컨셉 4축
  adConcept: AdConceptSelection
  // 생성 작업
  jobId: string | null
  resultVideoUrl: string | null

  setSource: (text: string, url: string) => void
  setAnalysis: (a: AdAnalysis | null) => void
  updateNarration: (narration: string) => void
  setConfig: (patch: Partial<AdConfig>) => void
  setActor: (mode: ActorMode, photoDataUrl?: string | null) => void
  setAiActor: (patch: Partial<AiActorProfile>) => void
  setActorUsage: (patch: Partial<ActorUsage>) => void
  setAdConcept: (patch: Partial<AdConceptSelection>) => void
  setJob: (jobId: string | null) => void
  setResult: (url: string | null) => void
  reset: () => void
}

const DEFAULT_CONFIG: AdConfig = {
  duration: 30, musicMood: 'energetic', voice: 'female', voiceVariety: false,
  narrationLocale: 'ko', subtitles: true,
}

export const useAdStore = create<AdState>()(persist((set) => ({
  sourceText: '',
  sourceUrl: '',
  analysis: null,
  config: DEFAULT_CONFIG,
  actorMode: null,
  actorPhotoDataUrl: null,
  aiActor: DEFAULT_AI_ACTOR,
  actorUsage: DEFAULT_ACTOR_USAGE,
  adConcept: DEFAULT_AD_CONCEPT,
  jobId: null,
  resultVideoUrl: null,

  setSource: (text, url) => set({ sourceText: text, sourceUrl: url }),
  setAnalysis: (analysis) => set({ analysis }),
  updateNarration: (narration) =>
    set((s) => (s.analysis ? { analysis: { ...s.analysis, narration } } : {})),
  setConfig: (patch) => set((s) => ({ config: { ...s.config, ...patch } })),
  setActor: (actorMode, actorPhotoDataUrl = null) => set({ actorMode, actorPhotoDataUrl }),
  setAiActor: (patch) => set((s) => ({ aiActor: { ...s.aiActor, ...patch } })),
  setActorUsage: (patch) => set((s) => {
    const next = { ...s.actorUsage, ...patch }
    // 얼굴만 쓰면 의상은 항상 AI 스타일링 (사진 의상을 유지할 대상이 없음)
    if (next.scope === 'face') next.outfit = 'restyle'
    return { actorUsage: next }
  }),
  setAdConcept: (patch) => set((s) => ({ adConcept: { ...s.adConcept, ...patch } })),
  setJob: (jobId) => set({ jobId }),
  setResult: (resultVideoUrl) => set({ resultVideoUrl }),
  reset: () =>
    set({
      sourceText: '', sourceUrl: '', analysis: null, config: DEFAULT_CONFIG,
      actorMode: null, actorPhotoDataUrl: null, aiActor: DEFAULT_AI_ACTOR,
      actorUsage: DEFAULT_ACTOR_USAGE, adConcept: DEFAULT_AD_CONCEPT,
      jobId: null, resultVideoUrl: null,
    }),
}), {
  name: 'adstudio-ad',
  // 새로고침에도 제작 설정이 유지되게 저장한다 — 저장이 안 되면 렌더 시점에 analysis가 사라져
  // 나레이션 언어가 UI 언어(브라우저 기본값=영어)로 되돌아가는 사고가 난다.
  // 단 actorPhotoDataUrl(사진 data URL)은 수 MB라 localStorage 한도를 넘길 수 있어 제외한다.
  partialize: (s) => ({
    sourceText: s.sourceText,
    sourceUrl: s.sourceUrl,
    analysis: s.analysis,
    config: s.config,
    actorMode: s.actorMode,
    aiActor: s.aiActor,
    actorUsage: s.actorUsage,
    adConcept: s.adConcept,
  }),
}))
