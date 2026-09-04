// P1 — 얼굴 검출: MediaPipe Tasks FaceDetector(GPU→CPU 폴백) + P-11 감마 폴백 + 소형 얼굴용 타일 폴백
// P-12(눈 감김): FaceLandmarker EAR — 확정된 주인공 크롭에만 지연 로드해서 쓴다(§7.3).
import { FaceDetector, FaceLandmarker, FilesetResolver, type Detection } from '@mediapipe/tasks-vision'
import th from './thresholds.json'
import type { FaceDet } from './types'
import { makeCanvas, ctx2d, toBitmap } from './util'

let detector: FaceDetector | null = null

export async function initDetector(): Promise<void> {
  if (detector) return
  const fileset = await FilesetResolver.forVisionTasks(th.model.wasmBase)
  const opts = (delegate: 'GPU' | 'CPU') => ({
    baseOptions: { modelAssetPath: th.model.faceDetector, delegate },
    runningMode: 'IMAGE' as const,
    minDetectionConfidence: th.detect.minConf,
  })
  try {
    detector = await FaceDetector.createFromOptions(fileset, opts('GPU'))
  } catch {
    detector = await FaceDetector.createFromOptions(fileset, opts('CPU'))
  }
}

/** 미리 모델을 내려받아 초기화한다(첫 사진 업로드 시 지연을 줄이기 위한 선택적 워밍업). */
export function warmupDetector(): void {
  void initDetector()
}

function mapDetection(d: Detection, w: number, h: number, source: FaceDet['source']): FaceDet | null {
  const bb = d.boundingBox
  if (!bb || !d.keypoints || d.keypoints.length < 6) return null
  const conf = d.categories[0]?.score ?? 0
  const k = d.keypoints // 순서: 0 R눈, 1 L눈, 2 코끝, 3 입 중심, 4 R귀, 5 L귀
  return {
    conf,
    bbox: [bb.originX / w, bb.originY / h, bb.width / w, bb.height / h],
    kps: { rEye: k[0], lEye: k[1], nose: k[2], mouth: k[3], rEar: k[4], lEar: k[5] },
    source,
  }
}

function detectOn(bm: ImageBitmap, source: FaceDet['source']): FaceDet[] {
  const res = detector!.detect(bm)
  return res.detections
    .map(d => mapDetection(d, bm.width, bm.height, source))
    .filter((f): f is FaceDet => !!f && f.conf >= th.detect.minConf)
}

async function applyGamma(bm: ImageBitmap, gamma: number): Promise<ImageBitmap> {
  const c = makeCanvas(bm.width, bm.height)
  const ctx = ctx2d(c)
  ctx.drawImage(bm, 0, 0)
  const im = ctx.getImageData(0, 0, bm.width, bm.height)
  const lut = new Uint8ClampedArray(256)
  for (let i = 0; i < 256; i++) lut[i] = Math.round(255 * Math.pow(i / 255, 1 / gamma))
  const d = im.data
  for (let i = 0; i < d.length; i += 4) {
    d[i] = lut[d[i]]; d[i + 1] = lut[d[i + 1]]; d[i + 2] = lut[d[i + 2]]
  }
  ctx.putImageData(im, 0, 0)
  return toBitmap(c)
}

function iou(a: FaceDet, b: FaceDet): number {
  const [ax, ay, aw, ah] = a.bbox, [bx, by, bw, bh] = b.bbox
  const x1 = Math.max(ax, bx), y1 = Math.max(ay, by)
  const x2 = Math.min(ax + aw, bx + bw), y2 = Math.min(ay + ah, by + bh)
  const inter = Math.max(0, x2 - x1) * Math.max(0, y2 - y1)
  return inter / (aw * ah + bw * bh - inter + 1e-9)
}

function nms(faces: FaceDet[]): FaceDet[] {
  const sorted = [...faces].sort((a, b) => b.conf - a.conf)
  const keep: FaceDet[] = []
  for (const f of sorted) if (!keep.some(k => iou(k, f) > th.detect.nmsIou)) keep.push(f)
  return keep
}

/** 소형 얼굴 폴백: 5개 영역(코너 4 + 중앙)을 2배 확대해 재검출 후 좌표 역매핑 */
async function detectTiled(work: ImageBitmap): Promise<FaceDet[]> {
  const W = work.width, H = work.height
  const rw = 0.6 * W, rh = 0.6 * H
  const origins: [number, number][] = [[0, 0], [W - rw, 0], [0, H - rh], [W - rw, H - rh], [0.2 * W, 0.2 * H]]
  const out: FaceDet[] = []
  for (const [ox, oy] of origins) {
    const scaleUp = Math.min(2, th.maxSide / Math.max(rw, rh))
    const cw = Math.round(rw * scaleUp), ch = Math.round(rh * scaleUp)
    const c = makeCanvas(cw, ch)
    ctx2d(c).drawImage(work, ox, oy, rw, rh, 0, 0, cw, ch)
    const bm = await toBitmap(c)
    for (const f of detectOn(bm, 'tile')) {
      out.push({
        ...f,
        bbox: [(ox + f.bbox[0] * rw) / W, (oy + f.bbox[1] * rh) / H, (f.bbox[2] * rw) / W, (f.bbox[3] * rh) / H],
        kps: Object.fromEntries(
          Object.entries(f.kps).map(([n, p]) => [n, { x: (ox + p.x * rw) / W, y: (oy + p.y * rh) / H }]),
        ) as FaceDet['kps'],
      })
    }
    bm.close()
  }
  return out
}

export interface DetectOutcome {
  faces: FaceDet[]
  p11Recovered: boolean
  tiledUsed: boolean
  workUsed: ImageBitmap // 지표 계산에 쓸 이미지(감마 회복 시 보정본)
}

export async function detectWithFallback(work: ImageBitmap): Promise<DetectOutcome> {
  await initDetector()
  let faces = detectOn(work, 'primary')
  let p11 = false, tiled = false, used = work
  if (!faces.length) {
    // P-11: 미검출 시 감마 보정 1회 재검출 (캘리브레이션 실증)
    const g = await applyGamma(work, th.detect.gammaRetry)
    faces = detectOn(g, 'gamma')
    if (faces.length) { p11 = true; used = g } else g.close()
  }
  if (!faces.length && th.detect.tileFallback) {
    faces = await detectTiled(work)
    tiled = faces.length > 0
  }
  return { faces: nms(faces), p11Recovered: p11, tiledUsed: tiled, workUsed: used }
}

// ── P-12 눈 감김(EAR) ──────────────────────────────────────────
// MediaPipe FaceMesh 478pt 표준 랜드마크 인덱스(널리 쓰이는 6점 EAR 서브셋).
// EAR = (‖p2-p6‖ + ‖p3-p5‖) / (2‖p1-p4‖)  (Soukupová & Čech, 2016)
const RIGHT_EYE_EAR_IDX = [33, 160, 158, 133, 153, 144] as const
const LEFT_EYE_EAR_IDX  = [362, 385, 387, 263, 373, 380] as const

let landmarker: FaceLandmarker | null = null

async function getLandmarker(): Promise<FaceLandmarker> {
  if (!landmarker) {
    const fileset = await FilesetResolver.forVisionTasks(th.model.wasmBase)
    landmarker = await FaceLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: th.model.faceLandmarker },
      runningMode: 'IMAGE',
      numFaces: 1,
      outputFaceBlendshapes: false,
      outputFacialTransformationMatrixes: false,
    })
  }
  return landmarker
}

function dist(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

function earFromPoints(pts: { x: number; y: number }[]): number {
  const [p1, p2, p3, p4, p5, p6] = pts
  const vertical = dist(p2, p6) + dist(p3, p5)
  const horizontal = dist(p1, p4)
  return horizontal > 0 ? vertical / (2 * horizontal) : 0
}

export interface EyeOpenness {
  leftEAR: number
  rightEAR: number
  avgEAR: number
}

/**
 * 얼굴 하나가 들어있는 크롭(정렬 불필요)에서 FaceLandmarker로 EAR을 계산한다.
 * 크롭에서 얼굴을 못 찾으면 null을 반환한다(호출부는 P-12를 생략 처리).
 */
export async function detectEyeOpenness(faceCropBitmap: ImageBitmap): Promise<EyeOpenness | null> {
  const lm = await getLandmarker()
  const result = lm.detect(faceCropBitmap)
  const points = result.faceLandmarks?.[0]
  if (!points || points.length < 468) return null

  const rightEAR = earFromPoints(RIGHT_EYE_EAR_IDX.map(i => points[i]))
  const leftEAR = earFromPoints(LEFT_EYE_EAR_IDX.map(i => points[i]))
  return { leftEAR, rightEAR, avgEAR: (leftEAR + rightEAR) / 2 }
}
