// 캔버스 유틸 — 메인 스레드/워커 겸용 (OffscreenCanvas 우선)
export type AnyCanvas = OffscreenCanvas | HTMLCanvasElement

export function makeCanvas(w: number, h: number): AnyCanvas {
  if (typeof OffscreenCanvas !== 'undefined') return new OffscreenCanvas(w, h)
  const c = document.createElement('canvas')
  c.width = w; c.height = h
  return c
}

export function ctx2d(c: AnyCanvas): CanvasRenderingContext2D {
  const ctx = (c as HTMLCanvasElement).getContext('2d', { willReadFrequently: true })
  if (!ctx) throw new Error('2D 컨텍스트 생성 실패')
  return ctx as CanvasRenderingContext2D
}

export async function toBlob(c: AnyCanvas, type = 'image/png', quality?: number): Promise<Blob> {
  if ('convertToBlob' in c) return (c as OffscreenCanvas).convertToBlob({ type, quality })
  return new Promise((res, rej) =>
    (c as HTMLCanvasElement).toBlob(b => (b ? res(b) : rej(new Error('toBlob 실패'))), type, quality))
}

export function toBitmap(c: AnyCanvas): Promise<ImageBitmap> {
  return createImageBitmap(c as CanvasImageSource as ImageBitmapSource)
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))
export const deg = (rad: number) => (rad * 180) / Math.PI
