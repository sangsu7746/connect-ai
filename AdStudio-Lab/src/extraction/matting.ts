// P5 — 매팅: 얼굴-시드 연결요소 필터링(플러드필) + 2px 페더 + 단색 배경 합성
// P-07(매팅 품질)·P-09(얼굴-몸 연결성) 판정에 쓰이는 지표도 여기서 계산한다(판정 자체는 quality.ts).
import th from './thresholds.json'
import type { SegMask } from './segmenter'
import { makeCanvas, ctx2d, toBitmap, toBlob } from './util'

export type NormBox = [number, number, number, number] // [x, y, w, h] 0~1 정규화

export interface ComponentAnalysis {
  fg: Uint8Array    // 이진화된 전경 마스크 (mask 해상도)
  keep: Uint8Array  // 얼굴과 4연결된 성분만 남긴 마스크 (mask 해상도) — 다른 사람/잡음 블롭 제외
  maskW: number
  maskH: number
}

function clampInt(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, Math.round(v)))
}

/**
 * 얼굴 bbox 안의 여러 시드 지점에서 4방향 플러드필로 확장해, 얼굴과 실제로 이어진
 * 픽셀만 "keep"으로 남긴다. 사진 속 다른 사람·배경 잡음 블롭은 연결되지 않는 한 자동 배제된다.
 * (단, 두 사람이 맞닿아 실루엣이 병합된 경우까지는 분리하지 못한다 — 의미론적 분할의 한계, §9)
 */
export function analyzeComponents(mask: SegMask, faceBboxNorm: NormBox, threshold: number): ComponentAnalysis {
  const { data, width, height } = mask
  const fg = new Uint8Array(width * height)
  for (let i = 0; i < data.length; i++) fg[i] = data[i] >= threshold ? 1 : 0

  const visited = new Uint8Array(width * height)
  const keep = new Uint8Array(width * height)

  const [bx, by, bw, bh] = faceBboxNorm
  const seeds: [number, number][] = [
    [bx + bw * 0.5, by + bh * 0.5],
    [bx + bw * 0.3, by + bh * 0.5],
    [bx + bw * 0.7, by + bh * 0.5],
    [bx + bw * 0.5, by + bh * 0.3],
    [bx + bw * 0.5, by + bh * 0.7],
  ]

  const queue: number[] = []
  for (const [sx, sy] of seeds) {
    const px = clampInt(sx * width, 0, width - 1)
    const py = clampInt(sy * height, 0, height - 1)
    queue.push(py * width + px)
  }

  while (queue.length) {
    const idx = queue.pop()!
    if (visited[idx]) continue
    visited[idx] = 1
    if (!fg[idx]) continue
    keep[idx] = 1
    const x = idx % width, y = (idx / width) | 0
    if (x > 0) queue.push(idx - 1)
    if (x < width - 1) queue.push(idx + 1)
    if (y > 0) queue.push(idx - width)
    if (y < height - 1) queue.push(idx + width)
  }

  return { fg, keep, maskW: width, maskH: height }
}

/** 주어진 정규화 영역 내에서 keep(또는 fg) 마스크의 전경 비율을 계산한다. (P-07 면적비 · P-09 커버리지 겸용) */
export function regionForegroundRatio(bin: Uint8Array, maskW: number, maskH: number, regionNorm: NormBox): number {
  const [rx, ry, rw, rh] = regionNorm
  const x0 = clampInt(rx * maskW, 0, maskW - 1)
  const y0 = clampInt(ry * maskH, 0, maskH - 1)
  const x1 = clampInt((rx + rw) * maskW, 0, maskW)
  const y1 = clampInt((ry + rh) * maskH, 0, maskH)
  let total = 0, fg = 0
  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      total++
      if (bin[y * maskW + x]) fg++
    }
  }
  return total > 0 ? fg / total : 0
}

/** 크롭 영역 안에서 keep에 포함되지 않은 다른 전경 블롭(잡음 아닌 것) 개수를 센다. (P-07 경계 파편 수) */
export function countStrayFragments(analysis: ComponentAnalysis, regionNorm: NormBox, minAreaRatio: number): number {
  const { fg, keep, maskW, maskH } = analysis
  const [rx, ry, rw, rh] = regionNorm
  const x0 = clampInt(rx * maskW, 0, maskW - 1)
  const y0 = clampInt(ry * maskH, 0, maskH - 1)
  const x1 = clampInt((rx + rw) * maskW, 0, maskW)
  const y1 = clampInt((ry + rh) * maskH, 0, maskH)

  const regionArea = Math.max(1, (x1 - x0) * (y1 - y0))
  const noiseFloor = Math.max(4, Math.round(regionArea * minAreaRatio))

  const visited = new Uint8Array(maskW * maskH)
  let fragments = 0

  for (let y = y0; y < y1; y++) {
    for (let x = x0; x < x1; x++) {
      const idx = y * maskW + x
      if (!fg[idx] || keep[idx] || visited[idx]) continue

      // 새 블롭 플러드필(영역 밖으로도 번질 수 있어 전체 마스크 기준으로 채우되, 카운트는 1회만)
      let area = 0
      const q = [idx]
      while (q.length) {
        const i = q.pop()!
        if (visited[i]) continue
        visited[i] = 1
        if (!fg[i] || keep[i]) continue
        area++
        const px = i % maskW, py = (i / maskW) | 0
        if (px > 0) q.push(i - 1)
        if (px < maskW - 1) q.push(i + 1)
        if (py > 0) q.push(i - maskW)
        if (py < maskH - 1) q.push(i + maskW)
      }
      if (area >= noiseFloor) fragments++
    }
  }
  return fragments
}

/**
 * keep 마스크를 half_body_ref 크롭 좌표계로 스케일해 알파 채널을 만들고, 페더 후
 * 단색 배경 위에 합성한다. face_ref는 대상이 아니다(§2 P5 — 배경 유지 원칙).
 */
export async function compositeHalfBodyMatte(
  orig: ImageBitmap,
  rectPx: { left: number; top: number; width: number; height: number },
  analysis: ComponentAnalysis,
  outW: number,
  outH: number,
  bgColor = th.matting.bgColor,
  featherPx = th.matting.featherPx,
): Promise<Blob> {
  // 1) 색상 크롭
  const colorCanvas = makeCanvas(outW, outH)
  const cctx = ctx2d(colorCanvas)
  cctx.imageSmoothingEnabled = true
  cctx.imageSmoothingQuality = 'high'
  cctx.drawImage(orig, rectPx.left, rectPx.top, rectPx.width, rectPx.height, 0, 0, outW, outH)

  // 2) keep 마스크를 알파 채널에 인코딩한 소형 캔버스 생성
  const { keep, maskW, maskH } = analysis
  const maskCanvas = makeCanvas(maskW, maskH)
  const maskCtx = ctx2d(maskCanvas)
  const maskImg = maskCtx.createImageData(maskW, maskH)
  for (let i = 0; i < keep.length; i++) {
    const a = keep[i] ? 255 : 0
    maskImg.data[i * 4] = 255
    maskImg.data[i * 4 + 1] = 255
    maskImg.data[i * 4 + 2] = 255
    maskImg.data[i * 4 + 3] = a
  }
  maskCtx.putImageData(maskImg, 0, 0)
  const maskBitmap = await toBitmap(maskCanvas)

  // 3) rectPx(원본 픽셀)를 정규화 후 마스크 픽셀 좌표로 변환해 동일 영역을 크롭 캔버스로 확대
  const rectNormX = rectPx.left / orig.width, rectNormY = rectPx.top / orig.height
  const rectNormW = rectPx.width / orig.width, rectNormH = rectPx.height / orig.height
  const sx = rectNormX * maskW, sy = rectNormY * maskH
  const sw = rectNormW * maskW, sh = rectNormH * maskH

  const alphaCanvas = makeCanvas(outW, outH)
  const actx = ctx2d(alphaCanvas)
  actx.imageSmoothingEnabled = true
  actx.imageSmoothingQuality = 'high'
  actx.drawImage(maskBitmap, sx, sy, sw, sh, 0, 0, outW, outH)
  maskBitmap.close()

  // 4) 페더: 별도 캔버스에 blur 필터로 그려서 경계를 부드럽게
  const featherCanvas = makeCanvas(outW, outH)
  const fctx = ctx2d(featherCanvas)
  fctx.filter = `blur(${featherPx}px)`
  fctx.drawImage(alphaCanvas as unknown as CanvasImageSource, 0, 0)
  fctx.filter = 'none'

  // 5) destination-in으로 색상 크롭에 알파 적용
  cctx.globalCompositeOperation = 'destination-in'
  cctx.drawImage(featherCanvas as unknown as CanvasImageSource, 0, 0)
  cctx.globalCompositeOperation = 'source-over'

  // 6) 단색 배경 위에 최종 합성
  const finalCanvas = makeCanvas(outW, outH)
  const fnctx = ctx2d(finalCanvas)
  fnctx.fillStyle = bgColor
  fnctx.fillRect(0, 0, outW, outH)
  fnctx.drawImage(colorCanvas as unknown as CanvasImageSource, 0, 0)

  return toBlob(finalCanvas, 'image/jpeg', 0.92)
}
