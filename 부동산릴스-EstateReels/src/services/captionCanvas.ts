// ════════════════════════════════════════════════════════════════
// 자막 카드 렌더러 — 씬 문구를 "프레임 크기 투명 PNG"로 그려 ffmpeg 오버레이로 얹는다.
// ffmpeg.wasm 코어에는 한글 폰트가 없어 drawtext로는 한글이 깨진다 → 브라우저 Canvas가 정답.
// 사진 위에 얹혀도 읽히도록 하단 스크림(어둡게)을 함께 굽는다.
// ════════════════════════════════════════════════════════════════
import type { SceneRole } from '../types'

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath()
  ctx.roundRect(x, y, w, h, r)
}

function wrap(ctx: CanvasRenderingContext2D, text: string, maxW: number): string[] {
  const lines: string[] = []
  let cur = ''
  const push = (w: string) => {
    const trial = cur ? cur + ' ' + w : w
    if (ctx.measureText(trial).width <= maxW) { cur = trial; return }
    if (cur) { lines.push(cur); cur = '' }
    if (ctx.measureText(w).width <= maxW) { cur = w; return }
    let chunk = ''
    for (const ch of w) {
      if (ctx.measureText(chunk + ch).width > maxW) { lines.push(chunk); chunk = ch }
      else chunk += ch
    }
    cur = chunk
  }
  for (const w of text.trim().split(/\s+/)) push(w)
  if (cur) lines.push(cur)
  return lines
}

async function toBlobUrl(canvas: HTMLCanvasElement): Promise<string> {
  const blob = await new Promise<Blob | null>(res => canvas.toBlob(res, 'image/png'))
  if (!blob) throw new Error('캡션 이미지를 만들지 못했어요.')
  return URL.createObjectURL(blob)
}

const FONT = (px: number, weight = 800) =>
  `${weight} ${px}px "Pretendard", "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif`

export interface CaptionOpts {
  W: number
  H: number
  role: SceneRole
  caption: string
  sub?: string
  badge?: string
  accent: string
  brand?: string
}

/** 씬 자막 카드 (프레임 크기 투명 PNG). role에 따라 hook/cta는 중앙 강조, point는 하단 로어서드. */
export async function renderCaptionOverlay(o: CaptionOpts): Promise<string> {
  const { W, H, role, caption, sub, badge, accent, brand } = o
  const canvas = document.createElement('canvas')
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')!
  const isPortrait = H >= W
  const centered = role === 'hook' || role === 'cta'

  // ── 하단(또는 전체) 스크림 — 사진 위 가독성 확보 ──
  const scrim = ctx.createLinearGradient(0, centered ? 0 : H * 0.45, 0, H)
  if (centered) {
    scrim.addColorStop(0, 'rgba(8,12,20,0.55)')
    scrim.addColorStop(0.5, 'rgba(8,12,20,0.35)')
    scrim.addColorStop(1, 'rgba(8,12,20,0.75)')
  } else {
    scrim.addColorStop(0, 'rgba(8,12,20,0)')
    scrim.addColorStop(1, 'rgba(8,12,20,0.82)')
  }
  ctx.fillStyle = scrim
  ctx.fillRect(0, 0, W, H)

  const sidePad = Math.round(W * 0.07)
  const maxTextW = W - sidePad * 2

  // ── 배지 ──
  let topY = Math.round(H * (centered ? 0.30 : 0.62))
  if (badge) {
    const bf = Math.round(W * (isPortrait ? 0.036 : 0.03))
    ctx.font = FONT(bf, 800)
    const bw = ctx.measureText(badge).width
    const padX = Math.round(bf * 0.7), padY = Math.round(bf * 0.45)
    const boxW = bw + padX * 2, boxH = bf + padY * 2
    const bx = centered ? (W - boxW) / 2 : sidePad
    const by = centered ? Math.round(H * 0.24) : topY - boxH - Math.round(H * 0.012)
    ctx.fillStyle = accent
    roundRect(ctx, bx, by, boxW, boxH, boxH / 2); ctx.fill()
    ctx.fillStyle = '#0b111c'
    ctx.textBaseline = 'middle'; ctx.textAlign = 'left'
    ctx.fillText(badge, bx + padX, by + boxH / 2 + 1)
  }

  // ── 메인 문구 ──
  const mainF = Math.round(W * (centered ? (isPortrait ? 0.078 : 0.06) : (isPortrait ? 0.062 : 0.05)))
  ctx.font = FONT(mainF, 900)
  ctx.textAlign = centered ? 'center' : 'left'
  const mainLines = wrap(ctx, caption, maxTextW)
  const mainLH = Math.round(mainF * 1.24)

  const subF = Math.round(W * (isPortrait ? 0.038 : 0.03))
  ctx.font = FONT(subF, 600)
  const subLines = sub ? wrap(ctx, sub, maxTextW) : []
  const subLH = Math.round(subF * 1.3)

  const blockH = mainLines.length * mainLH + (subLines.length ? subLines.length * subLH + Math.round(mainF * 0.4) : 0)
  let y = centered ? Math.round(H / 2 - blockH / 2 + mainF * 0.3) : Math.round(H * 0.88 - blockH)
  const x = centered ? W / 2 : sidePad
  ctx.textBaseline = 'alphabetic'

  // 메인 (그림자 + 흰 글자)
  ctx.font = FONT(mainF, 900)
  ctx.fillStyle = '#ffffff'
  ctx.shadowColor = 'rgba(0,0,0,0.6)'; ctx.shadowBlur = Math.round(mainF * 0.28); ctx.shadowOffsetY = 2
  for (const line of mainLines) { y += mainLH; ctx.fillText(line, x, y) }
  ctx.shadowColor = 'transparent'; ctx.shadowBlur = 0; ctx.shadowOffsetY = 0

  // 서브 (accent 색 강조 라인)
  if (subLines.length) {
    y += Math.round(mainF * 0.4)
    ctx.font = FONT(subF, 600)
    ctx.fillStyle = accent
    for (const line of subLines) { y += subLH; ctx.fillText(line, x, y) }
  }

  // ── 브랜드 태그 (하단 코너, 은은하게) ──
  if (brand) {
    const brF = Math.round(W * 0.026)
    ctx.font = FONT(brF, 700)
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'
    ctx.fillStyle = 'rgba(255,255,255,0.62)'
    ctx.fillText(brand, sidePad, H - Math.round(H * 0.03))
  }

  return toBlobUrl(canvas)
}

/** 매물번호 코너 라벨 — 영상 전체에 얹히는 작은 시리즈 워터마크 PNG(텍스트 크기). */
export async function renderCornerLabel(text: string, W: number): Promise<string> {
  const fs = Math.max(20, Math.round(W * 0.032))
  const font = FONT(fs, 800)
  const measure = document.createElement('canvas').getContext('2d')!
  measure.font = font
  const tw = Math.ceil(measure.measureText(text).width)
  const padX = Math.round(fs * 0.6), padY = Math.round(fs * 0.34)
  const canvas = document.createElement('canvas')
  canvas.width = tw + padX * 2
  canvas.height = fs + padY * 2
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = 'rgba(8,12,20,0.62)'
  roundRect(ctx, 0, 0, canvas.width, canvas.height, canvas.height / 2)
  ctx.fill()
  ctx.font = font
  ctx.fillStyle = 'rgba(255,255,255,0.92)'
  ctx.textBaseline = 'middle'
  ctx.textAlign = 'left'
  ctx.fillText(text, padX, canvas.height / 2 + 1)
  return toBlobUrl(canvas)
}

/** 사진이 없는 씬용 그라디언트 배경 (불투명 WxH) — Ken Burns 소스로 쓴다. */
export async function renderGradientBg(W: number, H: number, accent: string, glyph = '🏠'): Promise<string> {
  const canvas = document.createElement('canvas')
  canvas.width = W; canvas.height = H
  const ctx = canvas.getContext('2d')!
  const g = ctx.createLinearGradient(0, 0, W, H)
  g.addColorStop(0, '#0e1420'); g.addColorStop(1, '#141d2e')
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H)
  // accent 글로우
  const rg = ctx.createRadialGradient(W * 0.5, H * 0.38, 0, W * 0.5, H * 0.38, W * 0.7)
  rg.addColorStop(0, accent + '33'); rg.addColorStop(1, 'transparent')
  ctx.fillStyle = rg; ctx.fillRect(0, 0, W, H)
  ctx.globalAlpha = 0.08
  ctx.font = FONT(Math.round(W * 0.5), 900)
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText(glyph, W / 2, H * 0.42)
  ctx.globalAlpha = 1
  const blob = await new Promise<Blob | null>(res => canvas.toBlob(res, 'image/jpeg', 0.92))
  if (!blob) throw new Error('배경 이미지를 만들지 못했어요.')
  return URL.createObjectURL(blob)
}
