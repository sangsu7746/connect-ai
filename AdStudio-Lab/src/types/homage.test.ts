import { describe, it, expect } from 'vitest'
import { HOMAGE_STRUCTURE_ID, SHOT_TYPES, CAMERA_MOVES } from './homage'

describe('오마주 타입 상수', () => {
  it('예약 structureId 는 ad_ 접두사를 가진다', () => {
    // storyboardGenerator 의 isAdProject 판정이 conceptId.startsWith('ad_') 이므로
    // 이 접두사가 빠지면 광고 각본 생성 분기가 통째로 안 돈다
    expect(HOMAGE_STRUCTURE_ID).toBe('ad_homage')
    expect(HOMAGE_STRUCTURE_ID.startsWith('ad_')).toBe(true)
  })

  it('샷 타입과 카메라 무브가 정의돼 있다', () => {
    expect(SHOT_TYPES).toContain('close')
    expect(CAMERA_MOVES).toContain('push_in')
  })
})
