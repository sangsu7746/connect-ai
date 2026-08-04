import { describe, it, expect } from 'vitest'
import { sanitizeHomageStructure } from './homageSchema'

const validRaw = {
  scenes: [
    { seq: 1, durationSec: 3, shotType: 'wide', cameraMove: 'static',
      subjectRole: 'environment', emotionBeat: '평온한 일상', transition: 'cut' },
    { seq: 2, durationSec: 2, shotType: 'close', cameraMove: 'push_in',
      subjectRole: 'product', emotionBeat: '문제 인식', transition: 'match_cut' },
    { seq: 3, durationSec: 4, shotType: 'medium', cameraMove: 'pan',
      subjectRole: 'person', emotionBeat: '해소', transition: 'dissolve' },
  ],
  pacing: 'medium',
  overallArc: '일상 → 문제 → 해소',
}

describe('sanitizeHomageStructure', () => {
  it('정상 구조를 그대로 통과시킨다', () => {
    const out = sanitizeHomageStructure(validRaw)
    expect(out.scenes).toHaveLength(3)
    expect(out.pacing).toBe('medium')
    expect(out.scenes[1].shotType).toBe('close')
  })

  it('스키마에 없는 필드를 버린다 — 대사 유출 차단', () => {
    const withDialogue = {
      ...validRaw,
      scenes: validRaw.scenes.map(s => ({
        ...s,
        dialogue: '지금 바로 만나보세요',   // 원본 대사
        brandName: '경쟁사브랜드',
        subtitleText: '한정 특가',
      })),
    }
    const out = sanitizeHomageStructure(withDialogue)
    for (const scene of out.scenes) {
      expect(scene).not.toHaveProperty('dialogue')
      expect(scene).not.toHaveProperty('brandName')
      expect(scene).not.toHaveProperty('subtitleText')
    }
    // 통째로 직렬화해도 원본 문구가 남아 있으면 안 된다
    expect(JSON.stringify(out)).not.toContain('지금 바로')
    expect(JSON.stringify(out)).not.toContain('경쟁사브랜드')
  })

  it('emotionBeat 이 40자를 넘으면 자른다', () => {
    const long = '가'.repeat(100)
    const out = sanitizeHomageStructure({
      ...validRaw,
      scenes: [{ ...validRaw.scenes[0], emotionBeat: long }, validRaw.scenes[1], validRaw.scenes[2]],
    })
    expect(out.scenes[0].emotionBeat).toHaveLength(40)
  })

  it('overallArc 이 80자를 넘으면 자른다', () => {
    const out = sanitizeHomageStructure({ ...validRaw, overallArc: '나'.repeat(200) })
    expect(out.overallArc).toHaveLength(80)
  })

  it('알 수 없는 enum 값은 안전한 기본값으로 바꾼다', () => {
    const out = sanitizeHomageStructure({
      ...validRaw,
      pacing: 'ludicrous',
      scenes: [{ ...validRaw.scenes[0], shotType: 'drone_shot', transition: 'star_wipe' },
               validRaw.scenes[1], validRaw.scenes[2]],
    })
    expect(out.pacing).toBe('medium')
    expect(out.scenes[0].shotType).toBe('medium')
    expect(out.scenes[0].transition).toBe('cut')
  })

  it('seq 를 1부터 다시 매긴다', () => {
    const out = sanitizeHomageStructure({
      ...validRaw,
      scenes: validRaw.scenes.map(s => ({ ...s, seq: 99 })),
    })
    expect(out.scenes.map(s => s.seq)).toEqual([1, 2, 3])
  })

  it('씬이 3개 미만이면 실패시킨다', () => {
    expect(() => sanitizeHomageStructure({ ...validRaw, scenes: [validRaw.scenes[0]] }))
      .toThrow(/씬이 너무 적/)
  })

  it('scenes 가 배열이 아니면 실패시킨다', () => {
    expect(() => sanitizeHomageStructure({ scenes: 'nope', pacing: 'fast', overallArc: 'x' }))
      .toThrow(/구조를 읽지 못/)
  })

  it('durationSec 이 숫자가 아니면 3초로 채운다', () => {
    const out = sanitizeHomageStructure({
      ...validRaw,
      scenes: [{ ...validRaw.scenes[0], durationSec: 'long' }, validRaw.scenes[1], validRaw.scenes[2]],
    })
    expect(out.scenes[0].durationSec).toBe(3)
  })
})
