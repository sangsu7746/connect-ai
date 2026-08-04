// P-게이트 판정 (v0.3 동결 임계 · 명세 v1.2) + P-12 눈 감김(§7.3 신설·확정)
import th from './thresholds.json'
import type { GateResult } from './types'
import { detectEyeOpenness } from './detector'

export function gateP01(facePxOrig: number): GateResult {
  const t = th.p01
  if (facePxOrig >= t.pass)
    return { code: 'P-01', level: 'pass', messageKo: '얼굴 크기가 충분해요 — 기준 사진으로 좋아요' }
  if (facePxOrig >= t.warn)
    return { code: 'P-01', level: 'warn', messageKo: '사용 가능해요 — 더 가까운 사진이면 더 좋아요' }
  if (facePxOrig >= t.warnStrong)
    return { code: 'P-01', level: 'warn_strong', messageKo: '얼굴이 작아 품질이 낮아질 수 있어요 — 셀카 한 장을 추가해 보세요' }
  return { code: 'P-01', level: 'fail', messageKo: '얼굴이 너무 작아요 — 더 크게 나온 사진을 올려주세요' }
}

export function gateP02(blur200: number): GateResult {
  const t = th.p02
  if (blur200 >= t.warn) return { code: 'P-02', level: 'pass', messageKo: '선명해요' }
  if (blur200 >= t.fail) return { code: 'P-02', level: 'warn', messageKo: '조금 흐릿해요 — 더 선명한 사진이면 더 좋아요' }
  return { code: 'P-02', level: 'fail', messageKo: '너무 흐릿해요 — 다른 사진을 올려주세요' }
}

export function gateP03(yaw: number, pitch: number): GateResult {
  const t = th.p03
  if (Math.abs(yaw) <= t.yawWarn && Math.abs(pitch) <= t.pitchWarn)
    return { code: 'P-03', level: 'pass', messageKo: '정면이에요' }
  return { code: 'P-03', level: 'warn', messageKo: '측면 각도예요 — 정면 사진이 더 잘 나와요' }
}

export function gateP05(clip: number): GateResult {
  if (clip <= th.p05.clipWarn) return { code: 'P-05', level: 'pass', messageKo: '노출이 적당해요' }
  return { code: 'P-05', level: 'warn', messageKo: '너무 밝거나 어두운 부분이 많아요' }
}

export function isBacklit(faceMean: number, imgMean: number): boolean {
  return faceMean < th.backlit.faceToImgRatio * imgMean && imgMean > th.backlit.minImgMean
}

/**
 * P-07 매팅 품질 — 크롭 영역 내 마스크 면적비(5~85%) · 경계 파편 수(잡음 블롭 개수)로 판정.
 * fail 시 호출부는 매팅 결과를 버리고 원본 배경 크롭으로 강등한다(우아한 폴백).
 */
export function gateP07(areaRatio: number, fragments: number): GateResult {
  const t = th.p07
  if (areaRatio < t.minAreaRatio) {
    return { code: 'P-07', level: 'fail', messageKo: '인물 영역을 충분히 찾지 못해 원본 배경을 유지해요' }
  }
  if (areaRatio > t.maxAreaRatio) {
    return { code: 'P-07', level: 'fail', messageKo: '배경 구분이 어려워 원본 배경을 유지해요' }
  }
  if (fragments > t.maxFragments) {
    return { code: 'P-07', level: 'fail', messageKo: '배경 제거 경계가 매끄럽지 않아 원본 배경을 유지해요' }
  }
  return { code: 'P-07', level: 'pass', messageKo: '배경 제거가 깨끗해요' }
}

/**
 * P-09 얼굴-몸 연결성 — 선택 얼굴 bbox 영역이 얼굴-시드 연결요소로 얼마나 커버되는지 확인.
 * (다른 사람 몸을 잘라오는 사고 방지. 단, 두 사람이 맞닿아 실루엣이 병합된 경우는 걸러내지 못한다 — §9)
 * fail 시 호출부는 매팅 결과를 버리고 원본 배경 크롭으로 강등한다.
 */
export function gateP09(faceCoverage: number): GateResult {
  if (faceCoverage < th.p09.minFaceCoverage) {
    return { code: 'P-09', level: 'fail', messageKo: '인물 영역 인식이 부정확해 원본 배경을 유지해요' }
  }
  return { code: 'P-09', level: 'pass', messageKo: '인물 영역이 정확히 인식됐어요' }
}

/**
 * P-12 눈 감김(EAR) — face_ref 크롭에서 FaceLandmarker로 EAR을 계산해 낮으면 warn.
 * 랜드마크를 못 찾으면(크롭 실패 등) null을 반환한다 — 판단 근거가 없을 때 억지로 통과/차단하지 않는다.
 *
 * 임계값 주의: 실제 검증에서 눈을 뜨고 활짝 웃는 사진의 EAR이 0.19로 측정됨(미소로 눈이 가늘어지는
 * 효과 포함). 오탐을 피하려 0.15로 보수적으로 설정 — 눈 감은 사진 실측 데이터가 없어 정확한 경계는
 * 아직 미확정이다(캘리브레이션 리포트의 "판정 사례 부족"과 동일 상황).
 */
export async function gateP12(faceRefBlob: Blob): Promise<GateResult | null> {
  try {
    const bitmap = await createImageBitmap(faceRefBlob)
    try {
      const eyes = await detectEyeOpenness(bitmap)
      if (!eyes) return null
      if (eyes.avgEAR < th.p12.earWarnBelow) {
        return { code: 'P-12', level: 'warn', messageKo: '눈을 감은 것 같아요 — 다른 사진을 권장해요' }
      }
      return { code: 'P-12', level: 'pass', messageKo: '눈이 잘 떠져 있어요' }
    } finally {
      bitmap.close()
    }
  } catch (e) {
    console.warn('P-12 눈 감김 검사를 건너뜁니다:', e)
    return null
  }
}

export function worstGateLevel(gates: GateResult[]): GateResult['level'] {
  const rank: Record<GateResult['level'], number> = { pass: 0, warn: 1, warn_strong: 2, fail: 3 }
  let worst: GateResult['level'] = 'pass'
  for (const g of gates) if (rank[g.level] > rank[worst]) worst = g.level
  return worst
}
