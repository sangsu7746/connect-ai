// 주인공 추출 파이프라인 — 내부 작업 타입 (명세 v1.2)
// Relation은 앱 전역 타입(../types)을 그대로 쓴다 — 'married'를 포함한 6종 프리셋과 항상 동기화하기 위함.
import type { Relation } from '../types'

export type { Relation }

export interface Pt { x: number; y: number }               // 정규화 좌표(0~1)

export interface FaceDet {
  conf: number
  bbox: [number, number, number, number]                    // 정규화 [x, y, w, h]
  kps: { rEye: Pt; lEye: Pt; nose: Pt; mouth: Pt; rEar: Pt; lEar: Pt }
  source: 'primary' | 'gamma' | 'tile'
}

export type GateLevel = 'pass' | 'warn' | 'warn_strong' | 'fail'
export interface GateResult { code: string; level: GateLevel; messageKo: string }

export interface FaceMetrics {
  facePxOrig: number          // 원본 해상도 기준 얼굴 단변 px (P-01은 이 값 사용)
  facePxWork: number
  blur200: number             // 200x200 표준화 크롭 Laplacian 분산 (캘리브레이션 동일 산식)
  clip: number                // 노출 클리핑 비율
  faceMean: number
  yaw: number; pitch: number; roll: number   // 추정치(도) — 캘리브레이션 동일 산식(눈-코 기반)
  areaRatio: number           // 이미지 대비 얼굴 면적
  score: number                // P2 주인공 점수
  eligible: boolean           // 자격 규칙(최대 얼굴 면적의 9% 이상)
  gates: GateResult[]
}

export interface PersonCandidate { det: FaceDet; m: FaceMetrics }
export interface CropPack { faceRef: Blob; halfBodyRef: Blob }

export interface ExtractionResult {
  name: string
  origSize: [number, number]
  workSize: [number, number]
  imgMean: number
  backlit: boolean
  p11Recovered: boolean       // P-11: 감마 보정 재검출로 회복됨
  tiledUsed: boolean          // 타일 폴백 사용됨
  faces: PersonCandidate[]    // score 내림차순
  topIndex: number            // ★ 인덱스, -1 = 없음
  crops?: CropPack            // ★ 얼굴 크롭 (P4)
  preview: Blob                // 주석용 저해상 미리보기
  error?: string
}
