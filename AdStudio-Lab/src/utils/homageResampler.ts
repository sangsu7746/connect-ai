import type { HomageScene, ShotType } from '../types/homage'

const MIN_SCENES = 3

/** 넓은 → 좁은 순서. 씬을 나눌 때 뒤쪽 조각의 시선을 한 단계 좁힌다 */
const SHOT_NARROWING: Record<ShotType, ShotType> = {
  wide: 'medium',
  medium: 'close',
  close: 'extreme_close',
  extreme_close: 'extreme_close',
  insert: 'insert',
  text_card: 'text_card',
}

/**
 * 레퍼런스 씬 수를 내 영상 길이에 맞춘다.
 *
 * ⚠️ 앞에서 잘라내지 않는다 — 그러면 광고의 마무리(CTA)가 통째로 날아간다.
 *    첫 씬(훅)과 마지막 씬(마무리)은 병합·분할 대상에서 항상 제외한다.
 */
export function resampleHomageScenes(scenes: HomageScene[], targetCount: number): HomageScene[] {
  const target = Math.max(MIN_SCENES, targetCount)
  let work = scenes.map(s => ({ ...s }))

  // 입력이 목표보다 적으면 분할, 많으면 병합
  while (work.length > target && work.length > 1) {
    work = mergeShortestMiddle(work)
  }
  while (work.length < target) {
    work = splitLongest(work)
  }

  return work.map((s, i) => ({ ...s, seq: i + 1 }))
}

/** 가장 짧은 중간 씬을 이웃과 합친다. 같은 subjectRole 이웃을 우선한다 */
function mergeShortestMiddle(scenes: HomageScene[]): HomageScene[] {
  // 첫·마지막은 보호. 보호 대상만 남으면 어쩔 수 없이 마지막 직전을 쓴다
  const first = 1
  const last = scenes.length - 2
  let idx = first <= last ? first : Math.max(0, scenes.length - 2)
  for (let i = first; i <= last; i++) {
    if (scenes[i].durationSec < scenes[idx].durationSec) idx = i
  }

  const prev = scenes[idx - 1]
  const next = scenes[idx + 1]
  // 같은 역할의 이웃과 합치면 서사 단계가 덜 뭉개진다
  const mergeIntoPrev = !next || (prev && prev.subjectRole === scenes[idx].subjectRole)
  const targetIdx = mergeIntoPrev ? idx - 1 : idx + 1

  const out = scenes.map(s => ({ ...s }))
  out[targetIdx] = {
    ...out[targetIdx],
    durationSec: Math.round((out[targetIdx].durationSec + scenes[idx].durationSec) * 10) / 10,
  }
  out.splice(idx, 1)
  return out
}

/** 가장 긴 씬을 둘로 나눈다. 뒤 조각은 샷을 한 단계 좁힌다 */
function splitLongest(scenes: HomageScene[]): HomageScene[] {
  if (scenes.length === 0) {
    return [{
      seq: 1, durationSec: 3, shotType: 'medium', cameraMove: 'static',
      subjectRole: 'product', emotionBeat: '', transition: 'cut',
    }]
  }

  let idx = 0
  for (let i = 1; i < scenes.length; i++) {
    if (scenes[i].durationSec > scenes[idx].durationSec) idx = i
  }

  const src = scenes[idx]
  const half = Math.round((src.durationSec / 2) * 10) / 10
  const front: HomageScene = { ...src, durationSec: half }
  const back: HomageScene = {
    ...src,
    durationSec: Math.round((src.durationSec - half) * 10) / 10,
    shotType: SHOT_NARROWING[src.shotType],
    transition: 'cut',
  }

  const out = scenes.map(s => ({ ...s }))
  out.splice(idx, 1, front, back)
  return out
}
