// 공용 지표 — 캘리브레이션(calibrate_extraction.py)과 산식 동일 유지가 원칙
import { makeCanvas, ctx2d, clamp, deg } from './util'
import type { FaceDet } from './types'

function toGray(d: Uint8ClampedArray): Float32Array {
  const n = d.length / 4
  const g = new Float32Array(n)
  for (let i = 0; i < n; i++) g[i] = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2]
  return g
}

/** 3x3 Laplacian 분산 (200x200 표준화 크롭 전제) */
function laplacianVar(g: Float32Array, w: number, h: number): number {
  let sum = 0, sum2 = 0, n = 0
  for (let y = 1; y < h - 1; y++)
    for (let x = 1; x < w - 1; x++) {
      const i = y * w + x
      const v = g[i - w] + g[i + w] + g[i - 1] + g[i + 1] - 4 * g[i]
      sum += v; sum2 += v * v; n++
    }
  const mean = sum / n
  return sum2 / n - mean * mean
}

export interface FaceCropStats { blur200: number; clip: number; faceMean: number }

/** 얼굴 크롭을 200x200으로 표준화 후 블러·노출 지표 계산 */
export function faceCropStats(img: ImageBitmap, bboxNorm: [number, number, number, number]): FaceCropStats {
  const W = img.width, H = img.height
  const sx = clamp(bboxNorm[0] * W, 0, W - 1)
  const sy = clamp(bboxNorm[1] * H, 0, H - 1)
  const sw = clamp(bboxNorm[2] * W, 1, W - sx)
  const sh = clamp(bboxNorm[3] * H, 1, H - sy)
  const c = makeCanvas(200, 200)
  const ctx = ctx2d(c)
  ctx.drawImage(img, sx, sy, sw, sh, 0, 0, 200, 200)
  const d = ctx.getImageData(0, 0, 200, 200).data
  const g = toGray(d)
  let mean = 0, lo = 0, hi = 0
  for (let i = 0; i < g.length; i++) {
    mean += g[i]
    if (g[i] < 10) lo++; else if (g[i] > 245) hi++
  }
  mean /= g.length
  return { blur200: laplacianVar(g, 200, 200), clip: (lo + hi) / g.length, faceMean: mean }
}

/** 전체 이미지 평균 밝기 (256px 썸네일 기준) */
export function imageMean(img: ImageBitmap): number {
  const s = 256 / Math.max(img.width, img.height)
  const w = Math.max(1, Math.round(img.width * s))
  const h = Math.max(1, Math.round(img.height * s))
  const c = makeCanvas(w, h)
  const ctx = ctx2d(c)
  ctx.drawImage(img, 0, 0, w, h)
  const g = toGray(ctx.getImageData(0, 0, w, h).data)
  let m = 0
  for (let i = 0; i < g.length; i++) m += g[i]
  return m / g.length
}

export interface Pose { yaw: number; pitch: number; roll: number }

/** 포즈 추정치 — 캘리브레이션과 동일한 눈-코 기반 산식(임계 35°/25°가 이 산식으로 보정됨) */
export function poseFromKps(k: FaceDet['kps']): Pose {
  const eyeDist = Math.max(1e-6, Math.hypot(k.lEye.x - k.rEye.x, k.lEye.y - k.rEye.y))
  const midX = (k.rEye.x + k.lEye.x) / 2
  const yaw = clamp(((k.nose.x - midX) / eyeDist) * 90, -90, 90)
  const eyeY = (k.rEye.y + k.lEye.y) / 2
  const v = (k.nose.y - eyeY) / Math.max(1e-6, k.mouth.y - eyeY)
  const pitch = clamp((v - 0.55) * 120, -60, 60)
  const roll = deg(Math.atan2(k.lEye.y - k.rEye.y, k.lEye.x - k.rEye.x))
  return { yaw, pitch, roll }
}
