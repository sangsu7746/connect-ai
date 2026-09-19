// 주인공 추출 파이프라인 오케스트레이터 — 앱의 Photo/Person 타입과 엔진(P0~P5, P-11/12)을 연결한다.
// 엔진 본체(normalize/detector/metrics/quality/scorer/cropper)는 명세 v1.2·임계값 v0.3(28장 캘리브레이션
// 동결) 구현을 그대로 가져왔고, P5(매팅) 기본 티어와 P-12(눈 감김 EAR)는 이 프로젝트에서 추가로 병합했다.
//
// 무거운 연산(P1 타일 폴백 등)을 Web Worker로 옮기는 worker.ts도 함께 배치했지만,
// 이 오케스트레이터는 사진별로 원본+작업 비트맵을 계속 캐싱해 다중 사진·수동 재선택을 지원해야 해서
// 1회성 blob→결과 왕복에 최적화된 worker.ts 그대로는 맞지 않는다 — 메인 스레드 실행을 유지한다(후속 과제).

import th from './thresholds.json'
import { preprocessFile, loadNormalized } from './normalize'
import { detectWithFallback, warmupDetector } from './detector'
import {
  buildCandidates, pickTop,
  expectedHeadcountLabel, expectedHeadcountRange, validatePersonCount,
} from './scorer'
import { cropFaceRef, cropHalfBody, computeHalfBodyRect } from './cropper'
import { imageMean } from './metrics'
import { isBacklit, gateP12, gateP07, gateP09 } from './quality'
import { segmentPerson, warmupSegmenter } from './segmenter'
import { analyzeComponents, regionForegroundRatio, countStrayFragments, compositeHalfBodyMatte, type NormBox } from './matting'
import type { PersonCandidate, GateResult, FaceDet } from './types'
import type { Person, Photo, Relation, GateCheckItem } from '../types'

export { warmupDetector, expectedHeadcountLabel, expectedHeadcountRange, validatePersonCount }
export type { PersonCandidate, GateResult } from './types'

export function warmupExtraction(): void {
  warmupDetector()
  warmupSegmenter()
}

export interface IndexedCandidate {
  id: string          // `${photoId}:${순번}` — 사진 내 후보의 안정적인 키
  photoId: string
  candidate: PersonCandidate
  isStarPick: boolean
}

export interface PhotoExtraction {
  photoId: string
  candidates: IndexedCandidate[]
  backlit: boolean
  p11Recovered: boolean
  tiledUsed: boolean
}

interface CachedBitmaps { orig: ImageBitmap; work: ImageBitmap; scale: number }
const bitmapCache = new Map<string, CachedBitmaps>()

async function getBitmaps(photo: Photo): Promise<CachedBitmaps> {
  const cached = bitmapCache.get(photo.id)
  if (cached) return cached
  if (!photo.file) {
    throw new Error('원본 사진 파일을 찾을 수 없어요. 사진을 다시 업로드해주세요.')
  }
  const { blob, name } = await preprocessFile(photo.file)
  const { orig, work, scale } = await loadNormalized(blob, name)
  const bitmaps: CachedBitmaps = { orig, work, scale }
  bitmapCache.set(photo.id, bitmaps)
  return bitmaps
}

/**
 * P0(HEIC/EXIF/리사이즈)→P1(검출+P-11 감마+타일 폴백)→P2(스코어링+자격규칙)을 사진마다 실행한다.
 * relation(관계 프리셋) 기준 인원수만큼 사진 전체를 통틀어 상위 점수 후보에 ★(자동 제안)을 매긴다.
 */
export async function detectAndScoreAll(photos: Photo[], relation: Relation): Promise<PhotoExtraction[]> {
  const results: PhotoExtraction[] = []

  for (const photo of photos) {
    const { work, scale } = await getBitmaps(photo)
    const imgMeanVal = imageMean(work)
    const { faces, p11Recovered, tiledUsed, workUsed } = await detectWithFallback(work)
    const cands = buildCandidates(faces, workUsed, scale)

    const indexed: IndexedCandidate[] = cands.map((candidate, i) => ({
      id: `${photo.id}:${i}`,
      photoId: photo.id,
      candidate,
      isStarPick: false,
    }))

    const topIdx = pickTop(cands)
    const backlit = topIdx >= 0 ? isBacklit(cands[topIdx].m.faceMean, imgMeanVal) : false

    results.push({ photoId: photo.id, candidates: indexed, backlit, p11Recovered, tiledUsed })
  }

  // 사진 전체를 통틀어 자격 있는 얼굴 중 상위 점수에 ★ 자동 제안 (자격자가 없으면 전체 중 상위)
  const [minCount] = expectedHeadcountRange(relation)
  const allCandidates = results.flatMap(r => r.candidates)
  const eligible = allCandidates.filter(c => c.candidate.m.eligible)
  const pool = eligible.length > 0 ? eligible : allCandidates
  const starIds = new Set(
    [...pool]
      .sort((a, b) => b.candidate.m.score - a.candidate.m.score)
      .slice(0, minCount)
      .map(c => c.id)
  )

  return results.map(r => ({
    ...r,
    candidates: r.candidates.map(c => ({ ...c, isStarPick: starIds.has(c.id) })),
  }))
}

function blobToUrl(blob: Blob): string {
  return URL.createObjectURL(blob)
}

function toGateCheckItem(g: GateResult): GateCheckItem {
  // 앱 공용 GateCheckItem은 'warn_strong' 레벨이 없어 'warn'으로 접어 넣고, 메시지로 긴급도를 구분한다.
  return { code: g.code, level: g.level === 'warn_strong' ? 'warn' : g.level, messageKo: g.messageKo }
}

interface MatteAttempt {
  gateP07: GateResult
  gateP09: GateResult
  blob: Blob | null // null이면 게이트 실패 — 호출부가 원본 배경 크롭을 그대로 쓴다
}

/**
 * P5: half_body_ref에만 매팅을 시도한다(face_ref는 배경 유지 원칙, §2).
 * 세그멘터 로드 실패·P-07·P-09 실패 시 null-ish 결과를 반환해 호출부가 원본 배경 크롭으로
 * 조용히 강등할 수 있게 한다 — 매팅은 어디까지나 향상 기능이지, 파이프라인을 막는 필수 단계가 아니다.
 */
async function tryMatteHalfBody(cached: CachedBitmaps, det: FaceDet): Promise<MatteAttempt | null> {
  const mask = await segmentPerson(cached.work)
  if (!mask) return null

  const analysis = analyzeComponents(mask, det.bbox, th.matting.maskThreshold)
  const rect = computeHalfBodyRect(cached.orig, det)
  const rectNorm: NormBox = [
    rect.left / cached.orig.width, rect.top / cached.orig.height,
    rect.width / cached.orig.width, rect.height / cached.orig.height,
  ]

  const areaRatio = regionForegroundRatio(analysis.keep, analysis.maskW, analysis.maskH, rectNorm)
  const fragments = countStrayFragments(analysis, rectNorm, th.p07.fragmentMinAreaRatio)
  const faceCoverage = regionForegroundRatio(analysis.keep, analysis.maskW, analysis.maskH, det.bbox)

  const p07 = gateP07(areaRatio, fragments)
  const p09 = gateP09(faceCoverage)

  if (p07.level === 'fail' || p09.level === 'fail') {
    return { gateP07: p07, gateP09: p09, blob: null }
  }

  const c = th.crops
  const blob = await compositeHalfBodyMatte(cached.orig, rect, analysis, c.halfBodyW, c.halfBodyH)
  return { gateP07: p07, gateP09: p09, blob }
}

/** P4(원본 해상도 크롭)→P5(매팅)→P-12(눈 감김)→P9: 확정된 후보 하나를 앱의 Person으로 조립한다. */
export async function buildPerson(label: string, indexed: IndexedCandidate): Promise<Person> {
  const cached = bitmapCache.get(indexed.photoId)
  if (!cached) {
    throw new Error('사진 데이터를 찾을 수 없어요. 사진을 다시 업로드해주세요.')
  }

  const { det, m } = indexed.candidate
  const [faceRefBlob, plainHalfBodyBlob] = await Promise.all([
    cropFaceRef(cached.orig, det),
    cropHalfBody(cached.orig, det),
  ])

  const gates: GateCheckItem[] = m.gates.map(toGateCheckItem)

  const eyeGate = await gateP12(faceRefBlob)
  if (eyeGate) gates.push(toGateCheckItem(eyeGate))

  let halfBodyBlob = plainHalfBodyBlob
  try {
    const matte = await tryMatteHalfBody(cached, det)
    if (matte) {
      gates.push(toGateCheckItem(matte.gateP07), toGateCheckItem(matte.gateP09))
      if (matte.blob) halfBodyBlob = matte.blob
    }
  } catch (e) {
    console.warn('P5 매팅 중 오류 — 원본 배경 크롭으로 진행합니다:', e)
  }

  return {
    id: crypto.randomUUID(),
    label,
    faceId: indexed.id,
    cropUrl: blobToUrl(faceRefBlob),
    halfBodyUrl: blobToUrl(halfBodyBlob),
    quality: { score: m.score, facePx: m.facePxOrig, blur: m.blur200, yaw: m.yaw },
    gateResults: gates,
    sourcePhotoId: indexed.photoId,
  }
}

/** 사진이 목록에서 제거되었을 때 캐시된 비트맵을 정리한다(메모리 반환). */
export function releasePhoto(photoId: string): void {
  const cached = bitmapCache.get(photoId)
  if (cached) {
    cached.orig.close()
    if (cached.work !== cached.orig) cached.work.close()
  }
  bitmapCache.delete(photoId)
}

export function clearExtractionCache(): void {
  for (const photoId of [...bitmapCache.keys()]) releasePhoto(photoId)
}
