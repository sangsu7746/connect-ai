// 오케스트레이터(단발) — P0 → P1(+P-11·타일 폴백) → P2(+자격·게이트) → P4 최소 경로
// 사진 한 장을 받아 한 번에 끝까지 처리하는 단순 버전. worker.ts가 이 함수를 감싼다.
// 앱의 S2 업로드 화면은 다중 사진·수동 재선택을 지원해야 해서 index.ts의 오케스트레이터를 대신 쓴다.
import { loadNormalized } from './normalize'
import { detectWithFallback } from './detector'
import { buildCandidates, pickTop } from './scorer'
import { cropFaceRef, cropHalfBody } from './cropper'
import { imageMean } from './metrics'
import { isBacklit } from './quality'
import { makeCanvas, ctx2d, toBlob } from './util'
import type { ExtractionResult } from './types'

async function makePreview(bm: ImageBitmap, maxW = 640): Promise<Blob> {
  const s = Math.min(1, maxW / bm.width)
  const w = Math.round(bm.width * s), h = Math.round(bm.height * s)
  const c = makeCanvas(w, h)
  ctx2d(c).drawImage(bm, 0, 0, w, h)
  return toBlob(c, 'image/jpeg', 0.85)
}

export async function extractFromBlob(blob: Blob, name: string): Promise<ExtractionResult> {
  const { orig, work, scale } = await loadNormalized(blob, name)
  try {
    const imgMeanVal = imageMean(work)
    const preview = await makePreview(work)

    const { faces, p11Recovered, tiledUsed, workUsed } = await detectWithFallback(work)
    const cands = buildCandidates(faces, workUsed, scale)
    const topIndex = pickTop(cands)

    const result: ExtractionResult = {
      name,
      origSize: [orig.width, orig.height],
      workSize: [work.width, work.height],
      imgMean: Math.round(imgMeanVal * 10) / 10,
      backlit: topIndex >= 0 ? isBacklit(cands[topIndex].m.faceMean, imgMeanVal) : false,
      p11Recovered, tiledUsed,
      faces: cands, topIndex, preview,
    }

    if (topIndex >= 0) {
      const det = cands[topIndex].det
      result.crops = {
        faceRef: await cropFaceRef(orig, det),
        halfBodyRef: await cropHalfBody(orig, det),
      }
    }
    return result
  } finally {
    if (work !== orig) work.close()
    orig.close()
  }
}
