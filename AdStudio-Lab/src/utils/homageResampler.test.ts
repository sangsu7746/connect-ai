import { describe, it, expect } from 'vitest'
import { resampleHomageScenes } from './homageResampler'
import type { HomageScene } from '../types/homage'

const scene = (seq: number, durationSec: number, subjectRole: HomageScene['subjectRole'] = 'product'): HomageScene => ({
  seq, durationSec, shotType: 'medium', cameraMove: 'static',
  subjectRole, emotionBeat: `beat${seq}`, transition: 'cut',
})

describe('resampleHomageScenes', () => {
  it('개수가 이미 맞으면 그대로 돌려준다', () => {
    const input = [scene(1, 3), scene(2, 3), scene(3, 3)]
    expect(resampleHomageScenes(input, 3)).toEqual(input)
  })

  it('줄일 때 첫 씬(훅)과 마지막 씬(마무리)을 보존한다', () => {
    const input = [scene(1, 5, 'environment'), scene(2, 1), scene(3, 1), scene(4, 1), scene(5, 4, 'text')]
    const out = resampleHomageScenes(input, 3)
    expect(out).toHaveLength(3)
    expect(out[0].emotionBeat).toBe('beat1')
    expect(out[out.length - 1].emotionBeat).toBe('beat5')
  })

  it('줄일 때 가장 짧은 중간 씬부터 병합한다', () => {
    const input = [scene(1, 5), scene(2, 0.5), scene(3, 4), scene(4, 4)]
    const out = resampleHomageScenes(input, 3)
    expect(out).toHaveLength(3)
    // 0.5초 씬이 이웃과 합쳐져 사라진다
    expect(out.map(s => s.emotionBeat)).not.toContain('beat2')
  })

  it('늘릴 때 가장 긴 씬을 나눈다', () => {
    const input = [scene(1, 2), scene(2, 10), scene(3, 2)]
    const out = resampleHomageScenes(input, 4)
    expect(out).toHaveLength(4)
    // 10초 씬이 둘로 갈려 총 길이는 보존된다
    expect(out.reduce((a, s) => a + s.durationSec, 0)).toBeCloseTo(14, 1)
  })

  it('나뉜 씬은 샷 타입이 한 단계 좁아진다', () => {
    const input = [scene(1, 2), { ...scene(2, 10), shotType: 'wide' as const }, scene(3, 2)]
    const out = resampleHomageScenes(input, 4)
    const widened = out.filter(s => s.emotionBeat === 'beat2')
    expect(widened).toHaveLength(2)
    expect(widened[1].shotType).toBe('medium')
  })

  it('seq 를 1부터 다시 매긴다', () => {
    const out = resampleHomageScenes([scene(1, 5), scene(2, 1), scene(3, 1), scene(4, 5)], 3)
    expect(out.map(s => s.seq)).toEqual([1, 2, 3])
  })

  it('목표가 3 미만이면 3으로 올린다', () => {
    expect(resampleHomageScenes([scene(1, 3), scene(2, 3), scene(3, 3), scene(4, 3)], 1)).toHaveLength(3)
  })

  it('입력이 3개 미만이어도 목표 개수를 채운다', () => {
    expect(resampleHomageScenes([scene(1, 6), scene(2, 6)], 4)).toHaveLength(4)
  })

  // 리뷰에서 재현된 Critical 회귀: splitLongest 가 전체 배열을 스캔해 CTA(마지막 씬)가
  // 최장이면 그걸 쪼갰다. 이 파일 상단 docstring의 "첫 씬(훅)과 마지막 씬(마무리)은
  // 병합·분할 대상에서 항상 제외한다" 약속을 어긴 것 — 늘릴 때도 지켜야 한다.
  it('늘릴 때도 CTA(마지막 씬)가 가장 길면 쪼개지 않고 보존한다', () => {
    const input = [scene(1, 3, 'environment'), scene(2, 3), scene(3, 20, 'text')]
    const out = resampleHomageScenes(input, 4)
    expect(out).toHaveLength(4)
    const cta = out[out.length - 1]
    expect(cta.emotionBeat).toBe('beat3')
    expect(cta.durationSec).toBe(20)
    expect(cta.shotType).toBe('medium') // 쪼개졌다면 뒤 조각의 shotType 이 좁아졌을 것
  })
})
