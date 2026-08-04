// P4 — 정렬 크롭: face_ref(눈 수평 정렬 1024²) + half_body_ref(1024×1536)
// 크롭 좌표는 원본 해상도에서 계산(품질 손실 최소화) — 정규화 좌표라 해상도 독립
import th from './thresholds.json'
import type { FaceDet } from './types'
import { makeCanvas, ctx2d, toBlob, clamp } from './util'

export async function cropFaceRef(orig: ImageBitmap, det: FaceDet): Promise<Blob> {
  const W = orig.width, H = orig.height
  const r = det.kps.rEye, l = det.kps.lEye
  const rx = r.x * W, ry = r.y * H, lx = l.x * W, ly = l.y * H
  const eyeDist = Math.max(8, Math.hypot(lx - rx, ly - ry))
  const roll = Math.atan2(ly - ry, lx - rx)      // 눈 수평 정렬용
  const midX = (rx + lx) / 2, midY = (ry + ly) / 2

  const c = th.crops
  const boxSize = eyeDist * (c.faceUp + c.faceDown)   // 정방(상 0.9 + 하 1.3 = 2.2×눈간거리)
  const out = c.faceRefSize
  const s = out / boxSize
  const eyeLineY = out * (c.faceUp / (c.faceUp + c.faceDown)) // ≈ 40.9% 지점에 눈선 배치

  const canvas = makeCanvas(out, out)
  const ctx = ctx2d(canvas)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.translate(out / 2, eyeLineY)
  ctx.rotate(-roll)
  ctx.scale(s, s)
  ctx.drawImage(orig, -midX, -midY)
  return toBlob(canvas, 'image/png')
}

export interface HalfBodyRect { left: number; top: number; width: number; height: number } // 원본 픽셀 좌표

/** half_body_ref 크롭 사각형(원본 픽셀 좌표)을 계산한다 — 색상 크롭과 P5 매팅 알파 크롭이 동일 좌표를 공유하기 위해 분리. */
export function computeHalfBodyRect(orig: ImageBitmap, det: FaceDet): HalfBodyRect {
  const W = orig.width, H = orig.height
  const c = th.crops
  const fx = det.bbox[0] * W, fy = det.bbox[1] * H
  const fw = det.bbox[2] * W, fh = det.bbox[3] * H

  let boxH = fh * c.halfBodyHMul + fh * c.headroomMul
  let boxW = fw * c.halfBodyWMul
  let top = fy - fh * c.headroomMul
  const cx = fx + fw / 2

  // 목표 비율(2:3)에 맞춰 부족한 축 확장
  const target = c.halfBodyW / c.halfBodyH
  if (boxW / boxH < target) boxW = boxH * target; else boxH = boxW / target

  // 이미지보다 크면 비율 유지 축소 → 경계 안으로 평행이동
  const k = Math.min(1, W / boxW, H / boxH)
  boxW *= k; boxH *= k
  const left = clamp(cx - boxW / 2, 0, W - boxW)
  top = clamp(top, 0, H - boxH)

  return { left, top, width: boxW, height: boxH }
}

export async function cropHalfBody(orig: ImageBitmap, det: FaceDet): Promise<Blob> {
  const c = th.crops
  const { left, top, width, height } = computeHalfBodyRect(orig, det)

  const canvas = makeCanvas(c.halfBodyW, c.halfBodyH)
  const ctx = ctx2d(canvas)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(orig, left, top, width, height, 0, 0, c.halfBodyW, c.halfBodyH)
  return toBlob(canvas, 'image/jpeg', 0.92)
}
