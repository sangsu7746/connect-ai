/**
 * 유튜브 레퍼런스 오마주 — 구조 전용 타입.
 *
 * ⚠️ 저작권 경계: 이 파일의 어떤 타입에도 원본 대사·자막 문구·브랜드명·로고 묘사를
 *    담는 필드를 추가하지 않는다. "베끼지 마라"라고 프롬프트로 부탁하는 대신
 *    담을 그릇 자체를 만들지 않는 방식이다. 씬의 실제 대사와 화면 설명은
 *    항상 AdAnalysis(내 제품 분석 결과)에서 생성된다.
 */

/**
 * 오마주 모드의 예약 structureId.
 *
 * ⚠️ 비워두면 두 곳이 조용히 깨진다:
 *  - A5_Concept.tsx 의 canProceed 가 structureId !== '' 를 요구한다
 *  - storyboardGenerator 의 isAdProject 가 conceptId.startsWith('ad_') 로 판정한다
 *    → 접두사가 없으면 광고 각본 생성 분기가 안 돌고 제품 분석 결과가 무시된다
 *
 * AD_STRUCTURES / AD_CONCEPT_TEMPLATES 에는 등록하지 않는다(템플릿 목록에 뜨면 안 된다).
 */
export const HOMAGE_STRUCTURE_ID = 'ad_homage'

export const SHOT_TYPES = ['wide', 'medium', 'close', 'extreme_close', 'insert', 'text_card'] as const
export const CAMERA_MOVES = ['static', 'pan', 'tilt', 'push_in', 'pull_out', 'handheld', 'orbit'] as const
export const SUBJECT_ROLES = ['product', 'person', 'environment', 'text', 'abstract'] as const
export const TRANSITIONS = ['cut', 'dissolve', 'wipe', 'match_cut'] as const
export const PACINGS = ['slow', 'medium', 'fast', 'accelerating'] as const

export type ShotType = (typeof SHOT_TYPES)[number]
export type CameraMove = (typeof CAMERA_MOVES)[number]
export type SubjectRole = (typeof SUBJECT_ROLES)[number]
export type Transition = (typeof TRANSITIONS)[number]
export type Pacing = (typeof PACINGS)[number]

/** 자유 텍스트 상한 — 원본 대사가 통째로 새어드는 것을 막는다 */
export const EMOTION_BEAT_MAX = 40
export const OVERALL_ARC_MAX = 80

export interface HomageScene {
  seq: number
  durationSec: number
  shotType: ShotType
  cameraMove: CameraMove
  subjectRole: SubjectRole
  /** "긴장 고조" 같은 감정 단계. 원본 대사가 아니다. EMOTION_BEAT_MAX 자 제한 */
  emotionBeat: string
  transition: Transition
}

export interface HomageStructure {
  scenes: HomageScene[]
  pacing: Pacing
  /** 서사 곡선 한 줄 요약. OVERALL_ARC_MAX 자 제한 */
  overallArc: string
}

export interface HomageReference {
  source: 'search' | 'url' | 'description'
  videoId?: string           // description 입구에서는 없다
  title?: string
  channelTitle?: string
  thumbnailUrl?: string
  durationSec?: number
  userDescription?: string   // description 입구의 원문
  structure: HomageStructure
  analyzedAt: number
}

/** 검색 결과 카드 1장 — 아직 분석하지 않은 후보 */
export interface HomageCandidate {
  videoId: string
  title: string
  channelTitle: string
  thumbnailUrl: string
  publishedAt: string
}
