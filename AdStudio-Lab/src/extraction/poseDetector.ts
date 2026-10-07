// P-13(가칭) — AI 생성 키프레임의 자세 이상 검출: MediaPipe Tasks PoseLandmarker(GPU→CPU 폴백).
// FaceDetector(detector.ts)·ImageSegmenter(segmenter.ts)와 동일한 모듈 스코프 싱글턴 패턴.
import { PoseLandmarker, FilesetResolver } from '@mediapipe/tasks-vision'
import th from './thresholds.json'

let poseLandmarker: PoseLandmarker | null = null
let poseLandmarkerFailed = false

async function initPoseLandmarker(): Promise<PoseLandmarker | null> {
  if (poseLandmarker) return poseLandmarker
  if (poseLandmarkerFailed) return null
  try {
    const fileset = await FilesetResolver.forVisionTasks(th.model.wasmBase)
    const opts = (delegate: 'GPU' | 'CPU') => ({
      baseOptions: { modelAssetPath: th.model.poseLandmarker, delegate },
      runningMode: 'IMAGE' as const,
      numPoses: 4, // 이 앱 관계(relation) 중 최대 인원(가족 2~4명) 기준 — 친구(최대 6명)는 초과분 생략
    })
    try {
      poseLandmarker = await PoseLandmarker.createFromOptions(fileset, opts('GPU'))
    } catch {
      poseLandmarker = await PoseLandmarker.createFromOptions(fileset, opts('CPU'))
    }
    return poseLandmarker
  } catch (e) {
    console.warn('자세 검출 모델 초기화 실패 — 자세 이상 검사를 건너뜁니다:', e)
    poseLandmarkerFailed = true
    return null
  }
}

/** 미리 모델을 내려받아 초기화한다(선택적 워밍업). */
export function warmupPoseLandmarker(): void {
  void initPoseLandmarker()
}

export interface PoseAnomalyResult {
  ok: boolean
  detectedPoseCount: number
  reason?: string
}

/**
 * 생성된 키프레임에서 감지된 인원수·관절 평균 신뢰도를 예상 인원수와 비교한다. "팔 3개"를 직접
 * 판정하진 못하지만, 인원수 불일치나 신뢰도 급락은 인체 구조가 깨졌을 때 통계적으로 함께 나타나는
 * 간접 신호라 재생성 트리거로 쓸 만하다. 모델 로드 실패 시에는 차단하지 않고 통과 처리한다(기존
 * segmenter.ts의 "실패해도 파이프라인은 막지 않는다" 원칙과 동일).
 */
export async function checkPoseAnomaly(img: HTMLImageElement, expectedPoseCount: number): Promise<PoseAnomalyResult> {
  const landmarker = await initPoseLandmarker()
  if (!landmarker) return { ok: true, detectedPoseCount: expectedPoseCount }

  const result = landmarker.detect(img) // FaceDetector와 동일하게 동기 호출(await 불필요)
  const poses = result.landmarks ?? []
  const detectedPoseCount = poses.length

  const allVisibility = poses.flatMap(p => p.map(kp => kp.visibility ?? 0))
  const avgVisibility = allVisibility.length > 0
    ? allVisibility.reduce((a, b) => a + b, 0) / allVisibility.length
    : 0

  if (detectedPoseCount !== Math.min(expectedPoseCount, 4)) {
    return { ok: false, detectedPoseCount, reason: `인원수 불일치(예상 ${expectedPoseCount}명, 감지 ${detectedPoseCount}명)` }
  }
  if (avgVisibility < th.pose.minVisibility) {
    return { ok: false, detectedPoseCount, reason: '관절 신뢰도 낮음(자세 붕괴 가능성)' }
  }
  return { ok: true, detectedPoseCount }
}
