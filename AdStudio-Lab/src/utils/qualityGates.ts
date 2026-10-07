import type { Scene, Project, GateResult, GateCheckItem, GateLevel } from '../types'

// ── 사원/사전 데이터 (Lexicons) ──────────────────────────────────
const CELEBRITIES = ['아이유', 'iu', 'bts', '방탄소년단', '제니', 'jennie', '지드래곤', 'g-dragon']
const BRANDS = ['애플', 'apple', '나이키', 'nike', '구찌', 'gucci', '샤넬', 'chanel']
const WORKS = ['기생충', 'parasite', '오징어게임', 'squid game', '더글로리']
const RISKY_MOTIONS = ['손가락', 'finger', '연주', 'play instrument', '식사', 'dining', '거울', 'mirror', '수중', 'underwater']

/**
 * Gate 0 - 자동 보강 (자동 수정 및 최적화)
 * 프롬프트를 전처리하여 생성 성능을 높입니다.
 */
export function runGate0(scene: Scene): Scene {
  let keyframe = scene.keyframePromptEn || ''
  let motion = scene.motionPromptEn || ''

  // G0-01: 카메라 워크 미기재 시 기본 카메라 모션 추가
  const cameraVerbs = ['dolly', 'pan', 'zoom', 'tilt', 'truck', 'tracking', 'pedestal', 'camera', 'shot']
  const hasCameraWork = cameraVerbs.some(v => motion.toLowerCase().includes(v))
  if (!hasCameraWork && motion.trim() !== '') {
    motion = `slow dolly-in, ${motion}`
  } else if (motion.trim() === '') {
    motion = 'slow dolly-in'
  }

  // G0-02: 부정어 제거 (영상 생성기는 부정 지시를 이해하지 못하므로 긍정어로 교정)
  const negatives = [/\bwithout\s+(\w+)/gi, /\bno\s+(\w+)/gi, /\bnot\s+(\w+)/gi]
  negatives.forEach(regex => {
    keyframe = keyframe.replace(regex, '')
    motion = motion.replace(regex, '')
  });

  // G0-05: 종횡비/해상도 키워드 제거 (시스템이 제어하므로 낭비 방지)
  const technicalWords = ['1080p', '4k', '8k', '9:16', '16:9', 'aspect ratio', 'watermark']
  technicalWords.forEach(word => {
    const regex = new RegExp(`\\b${word}\\b`, 'gi')
    keyframe = keyframe.replace(regex, '')
    motion = motion.replace(regex, '')
  });

  return {
    ...scene,
    keyframePromptEn: keyframe.trim().replace(/,\s*,/g, ',').replace(/,\s*$/, ''),
    motionPromptEn: motion.trim().replace(/,\s*,/g, ',').replace(/,\s*$/, ''),
  }
}

/**
 * Gate 1 - 프롬프트 검사 (규칙 기반)
 * 씬 생성 전 프롬프트의 품질 및 무결성을 검사합니다.
 */
export function runGate1(scene: Scene): GateResult {
  const checks: GateCheckItem[] = []
  const desc = scene.descKo.toLowerCase()
  const keyframeEn = (scene.keyframePromptEn ?? '').toLowerCase()
  const motionEn = (scene.motionPromptEn ?? '').toLowerCase()
  const dialogue = scene.dialogueKo ?? ''

  // G1-01b: 정책 위반 (차단 필터)
  const blockedWords = ['porn', 'nsfw', 'sex', 'naked', 'nudity', 'violence', 'blood', 'hate']
  const hasBlocked = blockedWords.some(w => keyframeEn.includes(w) || motionEn.includes(w) || desc.includes(w))
  if (hasBlocked) {
    return {
      gate: 1,
      sceneId: scene.id,
      verdict: 'blocked',
      checks: [{
        code: 'G1-01b',
        level: 'blocked',
        messageKo: '정책상 제작할 수 없는 표현(성적/폭력적)이 포함되어 있습니다. 해당 내용을 수정해 주세요.'
      }]
    }
  }

  // G1-01a: 금칙어 감지 (유명인, 브랜드 등 -> 경고)
  const detectedCeleb = CELEBRITIES.find(c => desc.includes(c) || keyframeEn.includes(c))
  if (detectedCeleb) {
    checks.push({
      code: 'G1-01a',
      level: 'warn',
      messageKo: `'${detectedCeleb}' 표현이 감지되었습니다. 유명인의 인물 정보나 특정 브랜드명은 오탐 또는 오용될 수 있으므로 일반적인 설명구(예: '맑은 분위기의 인물 스타일')로 대체하는 것을 제안합니다.`,
      suggestionKo: `'${detectedCeleb}' 대신 일반 표현으로 순화해보세요.`
    })
  }

  // G1-02: 주인공 지정 확인
  if (!scene.subjectRefs || scene.subjectRefs.length === 0) {
    checks.push({
      code: 'G1-02',
      level: 'fail',
      messageKo: '이 장면에 적용될 주인공(인물) 정보가 지정되지 않았습니다.',
      suggestionKo: '업로드한 사진 속 인물을 주인공으로 씬에 지정해 주세요.'
    })
  }

  // G1-03: 모션 유무 검사
  if (!motionEn || motionEn.trim().length < 5) {
    checks.push({
      code: 'G1-03',
      level: 'warn',
      messageKo: '장면에 카메라 움직임이나 액션 지시어가 부족합니다. 영상이 다소 정적으로 보일 수 있습니다.',
      suggestionKo: "프롬프트 뒤에 'slow dolly-in' 또는 'gentle pan'을 추가해 보세요."
    })
  }

  // G1-05: 글자/자막 생성 요청 방지
  const logoKeywords = ['text', 'logo', 'sign saying', 'letters', '간판', '자막', '글자']
  const hasLogoReq = logoKeywords.some(w => desc.includes(w) || keyframeEn.includes(w))
  if (hasLogoReq) {
    checks.push({
      code: 'G1-05',
      level: 'warn',
      messageKo: '텍스트나 글자, 로고를 직접 영상 내에 그리도록 요청했습니다. AI 모델은 글자 렌더링에 취약하므로 왜곡될 수 있습니다.',
      suggestionKo: '글자는 완성 단계의 자막 처리로 입히는 것을 추천합니다.'
    })
  }

  // G1-09: 고위험 모션 감지
  const detectedRisky = RISKY_MOTIONS.find(m => desc.includes(m) || keyframeEn.includes(m) || motionEn.includes(m))
  if (detectedRisky) {
    checks.push({
      code: 'G1-09',
      level: 'warn',
      messageKo: `'${detectedRisky}' 관련 동작은 생성 모델에서 손가락 꼬임, 기형 왜곡을 일으킬 가능성이 높습니다.`,
      suggestionKo: '더 단순하거나 클로즈업 형태의 구도로 변경해 보시겠어요?'
    })
  }

  // G1-11: 대사 길이 매칭 (1초당 한글 4자 기준)
  if (dialogue && dialogue.trim().length > scene.duration * 4) {
    checks.push({
      code: 'G1-11',
      level: 'warn',
      messageKo: `대사가 장면 길이(${scene.duration}초)에 비해 너무 깁니다. 오디오 싱크가 씬 범위를 벗어날 수 있습니다.`,
      suggestionKo: `대사를 ${scene.duration * 4}자 내외로 요약하거나 장면 재생 시간을 늘려주세요.`
    })
  }

  return {
    gate: 1,
    sceneId: scene.id,
    verdict: checks.some(c => c.level === 'fail') ? 'regenerate' : 'pass',
    checks
  }
}

/**
 * Gate 2 - 키프레임 이미지 검사 (얼굴 검출 및 크기)
 * 생성된 이미지의 구도와 유사도를 평가합니다.
 */
export function runGate2(
  scene: Scene,
  faces: { x: number; y: number; w: number; h: number; confidence: number }[],
  similarity: number
): GateResult {
  const checks: GateCheckItem[] = []
  const requiredFacesCount = scene.subjectRefs?.length ?? 1

  // G2-01: 인물 수 매칭
  if (faces.length !== requiredFacesCount) {
    checks.push({
      code: 'G2-01',
      level: 'fail',
      messageKo: `검출된 인물 수(${faces.length}명)가 설정된 주인공 인물 수(${requiredFacesCount}명)와 다릅니다.`,
      suggestionKo: '구도가 맞지 않습니다. 키프레임을 다른 시드로 재생성하는 것이 좋습니다.'
    })
  }

  // G2-02: 원본 얼굴 유사도 검사
  if (similarity < 0.40) {
    checks.push({
      code: 'G2-02',
      level: 'fail',
      messageKo: '원본 인물과의 유사도가 너무 낮아 인물 일관성이 유지되지 않습니다.',
      suggestionKo: '레퍼런스 강도를 높이거나 다른 시드로 재생성해 주세요.'
    })
  } else if (similarity < 0.50) {
    checks.push({
      code: 'G2-02',
      level: 'warn',
      messageKo: '인물 유사도가 경계선 수준입니다. 조명이나 화각에 따라 약간 다르게 보일 수 있습니다.',
      suggestionKo: '정면 구도의 깨끗한 원본 사진을 사용하면 싱크율이 높아집니다.'
    })
  }

  // G2-03: 얼굴 크기 비율 검사 (얼굴이 너무 작으면 변환 시 뭉개짐)
  // 여기서는 프레임 높이를 기준으로 바운딩박스 높이 비율을 봅니다.
  const tooSmallFace = faces.some(f => f.h < 0.12)
  if (tooSmallFace) {
    checks.push({
      code: 'G2-03',
      level: 'fail',
      messageKo: '얼굴 영역이 화면 크기 대비 너무 작습니다 (12% 미만). 영상 변환 시 이목구비가 뭉개질 우려가 큽니다.',
      suggestionKo: "구도 프롬프트에 'medium close-up' 또는 'portrait'을 넣어 얼굴 크기를 키워보세요."
    })
  }

  return {
    gate: 2,
    sceneId: scene.id,
    verdict: checks.some(c => c.level === 'fail') ? 'regenerate' : 'pass',
    checks
  }
}

/**
 * Gate 3 - 영상 클립 검사
 * 영상 생성 직후 품질을 검사합니다.
 */
export function runGate3(scene: Scene, actualDuration: number, opticalFlowMean: number): GateResult {
  const checks: GateCheckItem[] = []

  // G3-01: 생성 스펙 매칭
  if (Math.abs(actualDuration - scene.duration) > 0.5) {
    checks.push({
      code: 'G3-01',
      level: 'fail',
      messageKo: `영상의 실재 재생 길이(${actualDuration.toFixed(1)}초)가 설정값(${scene.duration}초)과 일치하지 않습니다.`,
      suggestionKo: '인코딩 스펙 오류입니다. 자동 재시도 대상입니다.'
    })
  }

  // G3-03: 모션 과다 / 모션 부족 검사
  if (opticalFlowMean < 0.05) {
    checks.push({
      code: 'G3-03',
      level: 'fail',
      messageKo: '영상의 모션량이 극도로 낮아 거의 멈춰있는 사진처럼 보입니다.',
      suggestionKo: '모션 프롬프트의 강도 표현을 세게 고쳐 재생성합니다.'
    })
  } else if (opticalFlowMean > 0.85) {
    checks.push({
      code: 'G3-03',
      level: 'fail',
      messageKo: '모션 흐름이 지나치게 빠르거나 화면이 심하게 일그러집니다.',
      suggestionKo: '카메라 속도를 낮추거나 동작 묘사를 단순화하여 재생성합니다.'
    })
  }

  return {
    gate: 3,
    sceneId: scene.id,
    verdict: checks.some(c => c.level === 'fail') ? 'regenerate' : 'pass',
    checks
  }
}

/**
 * Gate 4 - 최종 완성본 검사
 * 최종 비디오 파일의 무결성을 검증합니다.
 */
export function runGate4(project: Project, scenes: Scene[], totalFileDuration: number): GateResult {
  const checks: GateCheckItem[] = []
  const expectedDuration = scenes.reduce((sum, s) => sum + s.duration, 0)

  // G4-01: 전체 길이 정밀 매칭
  if (Math.abs(totalFileDuration - expectedDuration) > 0.8) {
    checks.push({
      code: 'G4-01',
      level: 'fail',
      messageKo: `최종 병합된 파일의 재생 시간(${totalFileDuration.toFixed(1)}초)이 예정 시간(${expectedDuration}초)과 크게 다릅니다.`,
      suggestionKo: '병합 트랙 인코딩 오류가 우려됩니다.'
    })
  }

  return {
    gate: 4,
    sceneId: project.id,
    verdict: checks.some(c => c.level === 'fail') ? 'regenerate' : 'pass',
    checks
  }
}
