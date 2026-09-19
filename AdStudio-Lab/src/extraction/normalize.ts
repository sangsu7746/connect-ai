// P0 — 입력 정규화: HEIC 디코드(메인 스레드), EXIF 회전, ≤2048 리사이즈
import th from './thresholds.json'

export interface NormalizedPhoto {
  name: string
  orig: ImageBitmap   // 원본 해상도 (크롭·P-01용)
  work: ImageBitmap   // 작업 해상도 ≤ maxSide (검출·지표용)
  scale: number       // work/orig 배율 (≤1)
}

/** HEIC/HEIF → JPEG. 메인 스레드에서 호출(워커 진입 전). 그 외 형식은 그대로 통과 */
export async function preprocessFile(file: File): Promise<{ blob: Blob; name: string }> {
  const isHeic = /image\/hei[cf]/i.test(file.type) || /\.hei[cf]$/i.test(file.name)
  if (!isHeic) return { blob: file, name: file.name }
  const { default: heic2any } = await import('heic2any')
  const out = await heic2any({ blob: file, toType: 'image/jpeg', quality: 0.95 })
  return { blob: Array.isArray(out) ? out[0] : out, name: file.name }
}

export async function loadNormalized(blob: Blob, name: string): Promise<NormalizedPhoto> {
  // imageOrientation: 'from-image' → EXIF 회전 보정
  const orig = await createImageBitmap(blob, { imageOrientation: 'from-image' })
  const scale = Math.min(1, th.maxSide / Math.max(orig.width, orig.height))
  let work = orig
  if (scale < 1) {
    work = await createImageBitmap(blob, {
      imageOrientation: 'from-image',
      resizeWidth: Math.round(orig.width * scale),
      resizeHeight: Math.round(orig.height * scale),
      resizeQuality: 'high',
    })
  }
  return { name, orig, work, scale }
}
