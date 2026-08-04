// P5 — 인물 세그멘테이션 (MediaPipe Tasks Vision · Image Segmenter · selfie_segmenter, Apache-2.0)
// "기본" 티어만 구현한다. 고정밀 모드(ISNet/U²-Net, WebGPU)는 후속 과제(§9).
import { ImageSegmenter, FilesetResolver } from '@mediapipe/tasks-vision'
import th from './thresholds.json'

export interface SegMask { data: Float32Array; width: number; height: number }

let segmenter: ImageSegmenter | null = null
let segmenterFailed = false

async function initSegmenter(): Promise<ImageSegmenter | null> {
  if (segmenter) return segmenter
  if (segmenterFailed) return null
  try {
    const fileset = await FilesetResolver.forVisionTasks(th.model.wasmBase)
    const opts = (delegate: 'GPU' | 'CPU') => ({
      baseOptions: { modelAssetPath: th.model.imageSegmenter, delegate },
      runningMode: 'IMAGE' as const,
      outputCategoryMask: false,
      outputConfidenceMasks: true,
    })
    try {
      segmenter = await ImageSegmenter.createFromOptions(fileset, opts('GPU'))
    } catch {
      segmenter = await ImageSegmenter.createFromOptions(fileset, opts('CPU'))
    }
    return segmenter
  } catch (e) {
    console.warn('P5 세그멘터 초기화 실패 — 매팅을 건너뜁니다:', e)
    segmenterFailed = true
    return null
  }
}

/** 미리 모델을 내려받아 초기화한다(선택적 워밍업). */
export function warmupSegmenter(): void {
  void initSegmenter()
}

/**
 * 인물(person) 신뢰도 마스크를 계산한다. 모델 로드/추론에 실패하면 null을 반환해
 * 호출부가 매팅 없이(원본 배경 유지) 우아하게 진행할 수 있도록 한다.
 */
export async function segmentPerson(bitmap: ImageBitmap): Promise<SegMask | null> {
  const seg = await initSegmenter()
  if (!seg) return null

  try {
    const result = seg.segment(bitmap)
    const mask = result.confidenceMasks?.[0]
    if (!mask) return null
    const data = mask.getAsFloat32Array()
    const out: SegMask = { data: new Float32Array(data), width: mask.width, height: mask.height }
    mask.close()
    result.confidenceMasks?.forEach(m => { if (m !== mask) m.close() })
    return out
  } catch (e) {
    console.warn('P5 세그멘테이션 실행 실패 — 매팅을 건너뜁니다:', e)
    return null
  }
}
