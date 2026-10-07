// ════════════════════════════════════════════════════════════════
// 블로그 수집 — URL 자동 가져오기 + 사진 업로드(폴백)
//
// 정찰로 확인한 사실:
//  · 네이버 본문 이미지(mblogthumb-phinf.pstatic.net/.../SE-*.jpg)는 브라우저에서 직접 fetch 시
//    CORS(ACAO 없음)로 막힌다 → 반드시 프록시(weserv / 배포된 corsProxy) 경유해야 blob이 된다.
//  · 이미지 URL은 corsProxy로 받은 페이지 HTML의 data-lazy-src + jina 리더에서 추출한다
//    (allorigins는 네이버에 520으로 막혀 URL을 못 뽑던 것이 사진 실패의 원인이었다).
// ════════════════════════════════════════════════════════════════
import type { BlogImage, BlogSource } from '../types'

let uid = 0
const newId = () => `img_${Date.now().toString(36)}_${(uid++).toString(36)}`

const LOCAL_HELPER_BASE = 'http://127.0.0.1:8791'
const CORS_PROXY = 'https://us-central1-headjim-ai.cloudfunctions.net/corsProxy'
const PSTATIC = /https?:\/\/[^\s"')<>\\]+?(?:pstatic\.net|blogfiles\.naver\.net)[^\s"')<>\\]*/gi

/** 네이버 블로그 URL을 본문이 살아있는 모바일(PostView) 형태로 정규화한다. */
export function normalizeUrl(raw: string): string {
  let url = raw.trim()
  if (!/^https?:\/\//i.test(url)) url = 'https://' + url
  try {
    const u = new URL(url)
    if (/(^|\.)blog\.naver\.com$/.test(u.hostname)) {
      const blogId = u.searchParams.get('blogId')
      const logNo = u.searchParams.get('logNo')
      if (blogId && logNo) return `https://m.blog.naver.com/${blogId}/${logNo}`
      const m = u.pathname.match(/^\/([^/]+)\/(\d+)/)
      if (m) return `https://m.blog.naver.com/${m[1]}/${m[2]}`
    }
  } catch { /* keep as-is */ }
  return url
}

// ── 원격 텍스트/HTML 수집 (여러 경로 폴백) ──
async function tryLocalHelper(url: string): Promise<{ title: string; text: string; images: string[] } | null> {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), 40000)
    const res = await fetch(`${LOCAL_HELPER_BASE}/fetch`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }), signal: ctrl.signal,
    })
    clearTimeout(t)
    if (!res.ok) return null
    const j = await res.json() as { title?: string; text?: string; images?: string[] }
    if (!j.text || j.text.trim().length < 60) return null
    return { title: j.title || '', text: j.text, images: Array.isArray(j.images) ? j.images : [] }
  } catch { return null }
}

// 외부 프록시는 언제든 무한 대기할 수 있으므로 반드시 타임아웃을 건다(hang 방지).
async function fetchT(input: string, init: RequestInit, ms: number): Promise<Response> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), ms)
  try { return await fetch(input, { ...init, signal: ctrl.signal }) }
  finally { clearTimeout(t) }
}

async function fetchViaCorsProxyText(url: string): Promise<string> {
  // corsProxy(Firebase 함수)는 콜드스타트로 첫 요청이 느릴 수 있다 → 재시도(타임아웃↑)로
  // 같은 수집 안에서 회복시킨다(안 그러면 jina 폴백으로 빠져 이미지 URL을 거의 못 뽑는다).
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetchT(CORS_PROXY, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: 'gemini', apiKey: '-', method: 'GET', endpoint: url,
          headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126', Referer: 'https://m.blog.naver.com/' },
        }),
      }, attempt === 0 ? 15000 : 25000)
      const ct = res.headers.get('content-type') || ''
      if (ct.includes('json')) return '' // 바이너리 응답이면 텍스트가 아님
      const t = await res.text()
      if (t.length > 200) return t
    } catch { /* 다음 시도 */ }
  }
  return ''
}

async function fetchTextViaJina(url: string): Promise<string> {
  try {
    const res = await fetchT(`https://r.jina.ai/${url}`, {}, 12000)
    if (!res.ok) return ''
    const t = await res.text()
    return t.trim().length >= 60 ? t : ''
  } catch { return '' }
}

async function fetchHtmlViaAllorigins(url: string): Promise<string> {
  try {
    const res = await fetchT(`https://api.allorigins.win/raw?url=${encodeURIComponent(url)}`, {}, 12000)
    if (!res.ok) return ''
    const html = await res.text()
    return html.length > 400 ? html : ''
  } catch { return '' }
}

function stripHtmlToText(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/(p|div|h[1-6]|li)>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim()
}

function extractTitle(html: string): string {
  const og = html.match(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']/i)
  if (og) return og[1].trim()
  const t = html.match(/<title[^>]*>([^<]+)<\/title>/i)
  return t ? t[1].replace(/\s*[:|-]\s*네이버.*$/, '').trim() : ''
}

// ── 이미지 URL 추출 · 필터 · 정규화 ──
function isJunkImage(u: string): boolean {
  if (/storep-phinf|ssl\.pstatic\.net|blogimgs\.pstatic\.net|favicon|sprite|\/icon|logo|profile|button|blank|spacer|emoticon|sticker|static\.blog|nmobile|versioning|\.css|\.js|_blur|1x1|\/se-sticker/i.test(u)) return true
  if (/\.(svg|gif)(\?|$)/i.test(u)) return true
  return false
}
function isImageUrl(u: string): boolean {
  if (isJunkImage(u)) return false
  if (/pstatic\.net|blogfiles\.naver\.net/i.test(u)) return /mblogthumb-phinf|postfiles|blogfiles|blogthumb/i.test(u)
  return /\.(jpe?g|png|webp)(\?|$)/i.test(u) || /(tistory|kakaocdn|daumcdn|cloudfront|googleusercontent)/i.test(u)
}
function normalizeImg(u: string): string {
  if (u.startsWith('//')) u = 'https:' + u
  // 원본 type을 보존한다. 크기 조정은 다운로드 시 imgVariants가 처리한다.
  // (type=w966 강제는 blogthumb 등 일부 호스트에서 404를 유발했다 — 간헐 실패의 주원인.)
  return u.replace(/&amp;/g, '&')
}

/** 네이버 type 파라미터를 지정 값으로 바꾼다(없으면 추가). */
function forceType(u: string, val: string): string {
  if (/[?&]type=/i.test(u)) return u.replace(/([?&]type=)[^&]*/i, `$1${val}`)
  return u + (u.includes('?') ? '&' : '?') + `type=${val}`
}

/** 다운로드 후보 URL들 — 지원 호스트는 큰 사이즈(w966) 우선, 그다음 원본. 원본 type 보존이 핵심. */
function imgVariants(u: string): string[] {
  const out: string[] = []
  if (/mblogthumb-phinf|postfiles/i.test(u)) {
    const big = forceType(u, 'w966')
    if (big !== u) out.push(big)
  }
  out.push(u)
  return Array.from(new Set(out))
}

function collectImageUrls(sources: { html: string; base: string }[]): string[] {
  const raw: string[] = []
  for (const { html, base } of sources) {
    // 네이버 pstatic
    raw.push(...(html.match(PSTATIC) || []))
    // data-lazy-src (네이버 스마트에디터 실제 이미지)
    for (const m of html.matchAll(/data-lazy-src=["']([^"']+)["']/gi)) raw.push(m[1])
    // 일반 img 태그 (티스토리·워드프레스 등)
    for (const m of html.matchAll(/<img[^>]+(?:data-original|data-src|src)=["']([^"']+)["']/gi)) {
      let s = m[1]
      if (s.startsWith('/')) { try { s = new URL(s, base).href } catch { continue } }
      raw.push(s)
    }
    // 마크다운 이미지(jina) 및 og:image
    for (const m of html.matchAll(/!\[[^\]]*\]\((https?:\/\/[^)\s]+)\)/gi)) raw.push(m[1])
    const og = html.match(/property=["']og:image["'][^>]+content=["']([^"']+)["']/i)
    if (og) raw.push(og[1])
  }
  const seen = new Set<string>()
  const out: string[] = []
  for (const r of raw) {
    if (!isImageUrl(r)) continue
    const n = normalizeImg(r)
    let key: string
    try { key = new URL(n).pathname } catch { continue }
    if (key.length < 8) continue // 경로 없는 호스트-only URL(오탐) 제외
    if (seen.has(key)) continue
    seen.add(key)
    out.push(n)
  }
  return out.slice(0, 24)
}

// ── 이미지 실제 다운로드 (CORS 우회) ──
function weservUrl(url: string, w = 1280): string {
  return `https://images.weserv.nl/?url=${encodeURIComponent(url.replace(/^https?:\/\//i, ''))}&w=${w}&output=jpg&q=88`
}

async function blobToBlogImage(blob: Blob): Promise<BlogImage | null> {
  if (blob.size < 6000) return null
  const bmp = await createImageBitmap(blob)
  const width = bmp.width, height = bmp.height
  bmp.close?.()
  if (width < 260 || height < 260) return null
  return { id: newId(), src: URL.createObjectURL(blob), width, height, selected: true }
}

async function fetchImageViaCorsProxy(url: string): Promise<BlogImage | null> {
  try {
    const res = await fetchT(CORS_PROXY, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider: 'gemini', apiKey: '-', method: 'GET', endpoint: url, headers: { Referer: 'https://blog.naver.com/', 'User-Agent': 'Mozilla/5.0' } }),
    }, 15000)
    if (!res.ok) return null
    const j = await res.json() as { base64?: string; contentType?: string }
    if (!j.base64) return null
    const bin = atob(j.base64)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    return blobToBlogImage(new Blob([bytes], { type: j.contentType || 'image/jpeg' }))
  } catch { return null }
}

async function tryWeserv(url: string): Promise<BlogImage | null> {
  try {
    const res = await fetchT(weservUrl(url), {}, 15000)
    if (res.ok) return await blobToBlogImage(await res.blob())
  } catch { /* ignore */ }
  return null
}

async function fetchAsBlogImage(url: string): Promise<BlogImage | null> {
  // 각 이미지에 여러 번의 기회를 준다: (사이즈 변형 × [weserv → corsProxy base64])
  // weserv(리사이즈·CORS ok)를 먼저, 실패 시 배포된 corsProxy(base64, 원본 fetch)로.
  const variants = imgVariants(url)
  for (const v of variants) { const img = await tryWeserv(v); if (img) return img }
  for (const v of variants) { const img = await fetchImageViaCorsProxy(v); if (img) return img }
  return null
}

/** 동시 요청 수를 제한해 프록시 레이트리밋(간헐 실패)을 방지하는 풀 매핑. */
async function mapPool<T, R>(items: T[], limit: number, fn: (t: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length)
  let idx = 0
  const worker = async () => { while (idx < items.length) { const i = idx++; out[i] = await fn(items[i]) } }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return out
}

async function dataUrlToBlogImage(dataUrl: string): Promise<BlogImage | null> {
  try {
    const res = await fetch(dataUrl)
    return blobToBlogImage(await res.blob())
  } catch { return null }
}

export interface ImportResult {
  source: BlogSource
  images: BlogImage[]
  imageNote?: string
}

/** URL에서 본문+이미지를 가져온다. 본문은 반드시 확보하려 시도하고, 이미지는 프록시로 실제 다운로드한다. */
export async function importFromUrl(rawUrl: string): Promise<ImportResult> {
  const url = normalizeUrl(rawUrl)

  // 1) 로컬 도우미(있으면) — 본문 + 이미지 data URL을 바로 준다(가장 확실)
  const helper = await tryLocalHelper(url)
  if (helper && helper.images.length) {
    const images = (await Promise.all(helper.images.map(dataUrlToBlogImage))).filter((x): x is BlogImage => !!x)
    if (images.length) {
      return { source: { url, title: helper.title, rawText: helper.text, fetchedVia: 'helper' }, images }
    }
  }

  // 2) 본문 HTML(corsProxy) 우선. 충분하면 jina는 생략(느리거나 hang 방지), 부족할 때만 jina→allorigins.
  const corsHtml = await fetchViaCorsProxyText(url)
  const corsText = corsHtml ? stripHtmlToText(corsHtml) : ''
  let jinaText = ''
  let allorigins = ''
  if (corsText.length < 200) {
    jinaText = await fetchTextViaJina(url)
    if (!corsHtml && !jinaText) allorigins = await fetchHtmlViaAllorigins(url)
  }

  const htmlText = corsText || (allorigins ? stripHtmlToText(allorigins) : '')
  // 깨끗한 jina 텍스트를 우선(있고 충분하면), 없으면 HTML 본문
  const text = (helper?.text) || (jinaText.length >= 150 ? jinaText : (htmlText || jinaText))
  const title = (helper?.title) || extractTitle(corsHtml || allorigins || '')

  if (!text || text.trim().length < 60) {
    throw new Error('이 주소에서 본문을 읽지 못했어요. 네이버가 잠시 막았을 수 있어요 — 다시 시도하거나, 본문을 복사해 "붙여넣기"로 진행해 주세요.')
  }

  // 3) 이미지 URL 추출 → 프록시로 실제 다운로드
  const imgUrls = collectImageUrls([
    { html: corsHtml, base: url },
    { html: jinaText, base: url },
    { html: allorigins, base: url },
  ].filter(s => s.html))

  let images: BlogImage[] = []
  if (imgUrls.length) {
    // 동시 요청을 6개로 제한(버스트 레이트리밋 방지) + 각 이미지는 다중 전략으로 재시도
    const settled = await mapPool(imgUrls, 6, fetchAsBlogImage)
    images = settled.filter((x): x is BlogImage => !!x)
  }

  let imageNote: string | undefined
  if (images.length === 0) {
    imageNote = '본문은 가져왔지만 사진을 자동으로 받지 못했어요. 아래에서 사진을 직접 올려주세요(드래그).'
  } else if (imgUrls.length > images.length) {
    imageNote = `사진 ${images.length}장을 가져왔어요. 빠진 사진이 있으면 직접 올려도 돼요.`
  }

  return { source: { url, title, rawText: text, fetchedVia: helper ? 'helper' : 'url' }, images, imageNote }
}

// ── 사진 직접 업로드 (항상 동작 — HEIC 지원) ──
export async function filesToImages(files: File[]): Promise<BlogImage[]> {
  const out: BlogImage[] = []
  for (const f of files) {
    try {
      let blob: Blob = f
      if (/\.hei[cf]$/i.test(f.name) || f.type === 'image/heic' || f.type === 'image/heif') {
        const heic2any = (await import('heic2any')).default as (o: { blob: Blob; toType?: string; quality?: number }) => Promise<Blob | Blob[]>
        const conv = await heic2any({ blob: f, toType: 'image/jpeg', quality: 0.92 })
        blob = Array.isArray(conv) ? conv[0] : conv
      } else if (!f.type.startsWith('image/')) {
        continue
      }
      const bmp = await createImageBitmap(blob)
      const width = bmp.width, height = bmp.height
      bmp.close?.()
      out.push({ id: newId(), src: URL.createObjectURL(blob), width, height, selected: true })
    } catch (e) {
      console.warn('사진 처리 실패:', f.name, e)
    }
  }
  return out
}
