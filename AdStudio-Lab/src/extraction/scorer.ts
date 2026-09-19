// P2 — 주인공 스코어링 + 후보 자격 규칙(9%) + 관계 인원수 검증 (캘리브레이션 v0.3 동결)
import th from './thresholds.json'
import type { FaceDet, FaceMetrics, PersonCandidate, Relation } from './types'
import { faceCropStats, poseFromKps } from './metrics'
import { gateP01, gateP02, gateP03, gateP05 } from './quality'
import { clamp } from './util'

/** 검출 결과 → 지표·점수·게이트가 붙은 후보 목록(score 내림차순) */
export function buildCandidates(faces: FaceDet[], workUsed: ImageBitmap, scale: number): PersonCandidate[] {
  const W = workUsed.width, H = workUsed.height
  const s = th.score

  const cands: PersonCandidate[] = faces.map(det => {
    const [x, y, w, h] = det.bbox
    const stats = faceCropStats(workUsed, det.bbox)
    const pose = poseFromKps(det.kps)

    const areaRatio = w * h
    const areaNorm = Math.min(1, areaRatio / s.areaNormDiv)
    const centrality = 1 - Math.min(1, Math.hypot(x + w / 2 - 0.5, y + h / 2 - 0.5) / 0.7071)
    const sharpNorm = Math.min(1, stats.blur200 / s.sharpNormDiv)
    const front = Math.max(0, 1 - (Math.abs(pose.yaw) / 90) * 0.7 - (Math.abs(pose.pitch) / 60) * 0.3)
    const score = s.wArea * areaNorm + s.wCenter * centrality + s.wSharp * sharpNorm + s.wFront * front

    const facePxWork = Math.min(w * W, h * H)
    const facePxOrig = Math.round(facePxWork / clamp(scale, 1e-6, 1))

    const m: FaceMetrics = {
      facePxOrig, facePxWork: Math.round(facePxWork),
      blur200: Math.round(stats.blur200 * 10) / 10,
      clip: Math.round(stats.clip * 1000) / 1000,
      faceMean: Math.round(stats.faceMean * 10) / 10,
      yaw: Math.round(pose.yaw * 10) / 10,
      pitch: Math.round(pose.pitch * 10) / 10,
      roll: Math.round(pose.roll * 10) / 10,
      areaRatio, score: Math.round(score * 1000) / 1000,
      eligible: true,
      gates: [],
    }
    return { det, m }
  })

  cands.sort((a, b) => b.m.score - a.m.score)

  // 후보 자격 규칙: 최대 얼굴 면적의 9% 미만 → ★ 후보 박탈(배경 강등)
  const maxArea = Math.max(...cands.map(c => c.m.areaRatio), 1e-9)
  for (const c of cands) {
    c.m.eligible = c.m.areaRatio >= th.eligibility.minAreaRatioOfMax * maxArea
    c.m.gates = [gateP01(c.m.facePxOrig), gateP02(c.m.blur200), gateP03(c.m.yaw, c.m.pitch), gateP05(c.m.clip)]
  }
  return cands
}

/** ★ 선정: 자격 있는 최고 점수, 없으면 최고 점수, 후보 없으면 -1 */
export function pickTop(cands: PersonCandidate[]): number {
  if (!cands.length) return -1
  const i = cands.findIndex(c => c.m.eligible)
  return i >= 0 ? i : 0
}

// 앱 전역 Relation(6종, 'married' 포함)과 항상 동기화 — types.ts에서 재수출한 타입을 그대로 쓴다
const RELATION_RANGE: Record<Relation, [number, number]> = {
  solo: [1, 1], couple: [2, 2], married: [2, 2], siblings: [2, 2], family: [2, 4], friends: [2, 6],
}

const RELATION_LABEL: Record<Relation, string> = {
  solo: '나 혼자', couple: '연인', married: '부부', siblings: '남매·자매', family: '가족', friends: '친구',
}

export function expectedHeadcountRange(relation: Relation): [number, number] {
  return RELATION_RANGE[relation]
}

export function expectedHeadcountLabel(relation: Relation): string {
  const [lo, hi] = RELATION_RANGE[relation]
  return lo === hi ? `${lo}명` : `${lo}~${hi}명`
}

export function validatePersonCount(relation: Relation, selected: number): { ok: boolean; messageKo: string } {
  const [lo, hi] = RELATION_RANGE[relation]
  if (selected >= lo && selected <= hi) return { ok: true, messageKo: '' }
  return {
    ok: false,
    messageKo: `${RELATION_LABEL[relation]} 컨셉은 ${lo === hi ? `${lo}명` : `${lo}~${hi}명`}이 필요한데, 지금 ${selected}명이 선택됐어요.`,
  }
}
