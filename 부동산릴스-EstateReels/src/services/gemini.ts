// ════════════════════════════════════════════════════════════════
// Gemini 통합 서비스 (BYOK) — 배포된 corsProxy 경유로 브라우저 CORS 우회
//   · analyzeImages   : 사진을 카테고리+한줄설명으로 분류 (비전)
//   · generateScript  : 매물+컨셉+사진구성 → 컷별 자막·나레이션·배치카테고리 (스토리)
//   · synthesizeTTS   : 나레이션 대본 → 음성(WAV) (Gemini TTS)
// 키는 사용자가 로컬(localStorage)에 넣은 BYOK 키를 쓴다 — 서버로 보내지 않는다.
// ════════════════════════════════════════════════════════════════
import type { ListingInfo, ImageCategory, AiScene, BlogImage, SceneRole, VoiceGender, ConceptId } from '../types'
import { IMAGE_CATEGORIES } from '../types'
import { getConcept, type ConceptDef } from '../utils/estateConcepts'
import type { Marketing } from '../utils/hooks'

const CORS_PROXY = 'https://us-central1-headjim-ai.cloudfunctions.net/corsProxy'
const TEXT_MODELS = ['gemini-3.5-flash', 'gemini-2.5-flash', 'gemini-1.5-flash']
const TTS_MODELS = ['gemini-2.5-flash-preview-tts', 'gemini-3.1-flash-tts-preview', 'gemini-2.5-pro-preview-tts']
const KEY_STORAGE = 'estate_gemini_key'

export function getGeminiKey(): string { return localStorage.getItem(KEY_STORAGE) || '' }
export function setGeminiKey(k: string) { localStorage.setItem(KEY_STORAGE, k.trim()) }
export function hasGeminiKey(): boolean { return getGeminiKey().length > 10 }

interface Part { text?: string; inlineData?: { mimeType: string; data: string } }

async function callGemini(models: string[], parts: Part[], genConfig: Record<string, unknown>): Promise<Record<string, unknown>> {
  const key = getGeminiKey()
  if (!key) throw new Error('NO_KEY')
  let lastErr = ''
  for (const model of models) {
    try {
      const res = await fetch(CORS_PROXY, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: 'gemini', apiKey: key, method: 'POST',
          endpoint: `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${key}`,
          payload: { contents: [{ parts }], generationConfig: genConfig },
        }),
      })
      const data = await res.json() as Record<string, unknown>
      if (res.ok && (data as { candidates?: unknown[] }).candidates?.length) return data
      lastErr = `${model}: ${res.status}`
    } catch (e) { lastErr = e instanceof Error ? e.message : String(e) }
  }
  throw new Error(lastErr || 'Gemini 호출 실패')
}

function textOf(data: Record<string, unknown>): string {
  const c = data as { candidates?: { content?: { parts?: { text?: string }[] } }[] }
  return c.candidates?.[0]?.content?.parts?.[0]?.text || ''
}
function parseJson<T>(text: string): T {
  const m = text.match(/[[{][\s\S]*[\]}]/)
  if (!m) throw new Error('AI 응답을 이해하지 못했어요.')
  return JSON.parse(m[0]) as T
}

// ── 이미지를 작게(≤512px) 인라인 데이터로 — 비전 요청 페이로드를 가볍게 ──
async function srcToInline(src: string, max = 512): Promise<{ mimeType: string; data: string }> {
  const blob = await (await fetch(src)).blob()
  const bmp = await createImageBitmap(blob)
  const scale = Math.min(1, max / Math.max(bmp.width, bmp.height))
  const w = Math.max(1, Math.round(bmp.width * scale)), h = Math.max(1, Math.round(bmp.height * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w; canvas.height = h
  canvas.getContext('2d')!.drawImage(bmp, 0, 0, w, h)
  bmp.close?.()
  const dataUrl = canvas.toDataURL('image/jpeg', 0.8)
  return { mimeType: 'image/jpeg', data: dataUrl.split(',')[1] }
}

/**
 * 사진들을 카테고리+한줄설명으로 분류한다(비전). 8장씩 배치로 나눠 호출한다.
 * 반환은 입력 순서와 정렬된 [{id, category, note}].
 */
export async function analyzeImages(images: BlogImage[]): Promise<{ id: string; category: ImageCategory; note: string }[]> {
  const out: { id: string; category: ImageCategory; note: string }[] = []
  const BATCH = 8
  for (let b = 0; b < images.length; b += BATCH) {
    const batch = images.slice(b, b + BATCH)
    const inlines = await Promise.all(batch.map(im => srcToInline(im.src)))
    const parts: Part[] = [{
      text: [
        '너는 부동산 매물 사진 분류기다. 아래 사진들을 순서대로 분류해줘.',
        `카테고리는 다음 중 하나: ${IMAGE_CATEGORIES.join(', ')}`,
        '외관=건물/아파트 전경, 거실, 주방, 침실, 욕실, 뷰=창밖 전망/조망, 평면도=도면, 지도=위치/지도, 주변=편의시설/거리, 단지=조경/커뮤니티/단지 전경, 기타.',
        `사진은 총 ${batch.length}장이다. 다음 JSON 배열로만 답해라(다른 텍스트 금지):`,
        '[{"i":0,"category":"거실","note":"밝은 거실 (12자 이내)"}, ...]',
      ].join('\n'),
    }]
    for (const inl of inlines) parts.push({ inlineData: inl })

    try {
      const data = await callGemini(TEXT_MODELS, parts, { temperature: 0.2, maxOutputTokens: 800 })
      const arr = parseJson<{ i: number; category: string; note?: string }[]>(textOf(data))
      for (const item of arr) {
        const img = batch[item.i]
        if (!img) continue
        const cat = (IMAGE_CATEGORIES as string[]).includes(item.category) ? item.category as ImageCategory : '기타'
        out.push({ id: img.id, category: cat, note: (item.note || '').slice(0, 20) })
      }
    } catch (e) {
      console.warn('이미지 분석 배치 실패 — 기타로 처리:', e)
      for (const img of batch) out.push({ id: img.id, category: '기타', note: '' })
    }
  }
  return out
}

/**
 * 매물+컨셉+사진 구성 → 컷별 스토리(자막·나레이션·배치 카테고리)를 생성한다.
 * imageSummary: 보유 사진 카테고리별 개수 (AI가 실제 있는 사진에 맞춰 구성하도록).
 */
export async function generateScript(opts: {
  listing: ListingInfo
  concept: ConceptDef
  durationSec: number
  sceneCount: number
  imageSummary: Partial<Record<ImageCategory, number>>
}): Promise<AiScene[]> {
  const { listing, concept, durationSec, sceneCount, imageSummary } = opts
  const inventory = Object.entries(imageSummary).filter(([, n]) => n && n > 0)
    .map(([c, n]) => `${c}×${n}`).join(', ') || '없음'

  const prompt = [
    '너는 부동산 홍보 숏폼 영상 카피라이터다. 아래 매물을 정확히 이 컨셉으로 구성한 영상 스크립트를 만든다.',
    `컨셉: "${concept.label}" — 소비자 니즈: ${concept.need}`,
    `총 길이 ${durationSec}초, 컷 수 정확히 ${sceneCount}개. 첫 컷 role="hook", 마지막 role="cta", 나머지 role="point".`,
    '규칙: 과장·허위 금지(매물 정보에 있는 사실만). 자막(caption)은 18자 이내 임팩트 있게, sub는 22자 이내.',
    '★ 첫 컷(hook) 자막은 스크롤을 멈추게 하는 훅으로: [질문·궁금증]("이 가격 실화?","OO역 5분인데?") / [충격 숫자]("84㎡가 O억대?!") / [급매·할인]("반값 급매") / [경고]("놓치면 후회") 중 하나. 밋밋한 정보 나열은 금지.',
    '★★ narration(음성)은 자막(caption·sub)을 "그대로 읽지 마라". 화면엔 짧은 키워드가 보이고, 음성은 그 의미를 다른 표현으로 풀어 말하는 구어체 한 문장이어야 한다(이점·느낌·맥락 추가). 자막 단어를 그대로 반복하면 안 된다.',
    '  예) caption="🚇 초역세권 3분" → narration="지하철역이 걸어서 3분 거리라, 바쁜 아침에도 여유가 생깁니다." (자막을 반복하지 않고 이점을 말함)',
    '  예) caption="올수리·확장" → narration="집 안 곳곳을 새로 손봐서, 들어오자마자 바로 생활하실 수 있어요."',
    'narration은 성우가 읽을 자연스러운 구어체 한 문장. wantCategory는 이 컷에 어울리는 사진 카테고리.',
    `보유 사진(카테고리×개수): ${inventory} — 이 안에서 wantCategory를 고르되, 없으면 "기타".`,
    '',
    '매물 정보(JSON):',
    JSON.stringify({
      title: listing.title, dealType: listing.dealType, price: listing.priceText, type: listing.propertyType,
      area: listing.areaText, rooms: listing.rooms, floor: listing.floorText, dir: listing.direction,
      region: listing.region, station: listing.station, walk: listing.walkText,
      schools: listing.schools, amenities: listing.amenities, features: listing.features,
      invest: listing.investPoints, manage: listing.manageText, moveIn: listing.moveInText, contact: listing.contact,
    }),
    '',
    `카테고리 후보: ${IMAGE_CATEGORIES.join(', ')}`,
    '다음 JSON 배열로만 답해라(다른 텍스트 금지):',
    '[{"role":"hook","caption":"...","sub":"...","narration":"...","wantCategory":"외관"}, ...]',
  ].join('\n')

  const data = await callGemini(TEXT_MODELS, [{ text: prompt }], { temperature: 0.8, maxOutputTokens: 2048 })
  const arr = parseJson<AiScene[]>(textOf(data))
  // 정규화 — role/카테고리 보정, 개수 맞춤
  return arr.slice(0, sceneCount).map((s, i) => ({
    role: (i === 0 ? 'hook' : i === Math.min(arr.length, sceneCount) - 1 ? 'cta' : 'point') as SceneRole,
    caption: (s.caption || '').slice(0, 30),
    sub: s.sub ? s.sub.slice(0, 40) : undefined,
    narration: s.narration || s.caption || '',
    wantCategory: (IMAGE_CATEGORIES as string[]).includes(s.wantCategory as string) ? s.wantCategory : undefined,
  }))
}

/** 범용 JSON 텍스트 호출 — "AI로 다듬기" 등에서 재사용 */
export async function geminiJson<T>(prompt: string): Promise<T> {
  const data = await callGemini(TEXT_MODELS, [{ text: prompt }], { temperature: 0.7, maxOutputTokens: 1024 })
  return parseJson<T>(textOf(data))
}

/**
 * 훅·제목 다듬기 — 템플릿 초안(fallback)을 유튜브 검증 공식으로 매끄럽게 보정한다.
 * 키가 없으면 throw(NO_KEY) → 호출부가 fallback 그대로 사용.
 */
export async function generateHooksAndTitles(
  info: ListingInfo, conceptId: ConceptId, fallback: Marketing,
): Promise<Marketing> {
  const concept = getConcept(conceptId)
  const prompt = [
    '너는 부동산 홍보 숏폼 카피라이터다. 유튜브에서 조회수 잘 나오는 "훅 공식"으로 오프닝 훅과 제목을 만든다.',
    `컨셉: "${concept.label}" (${concept.need})`,
    '검증된 공식 — 오프닝 훅은 [질문·궁금증]/[충격 숫자]/[급매·할인]/[경고] 중 하나로 스크롤을 멈추게. 제목은 "[훅] │ [숫자·혜택 배지] │ [단지·입지]" 파이프 포맷.',
    '규칙: 매물정보에 있는 사실만. 없는 가격·혜택·수치 창작 금지(허위·과장 금지). 훅 18자 이내, 제목 40자 이내, 제목 3개.',
    '',
    '매물정보(JSON):',
    JSON.stringify({
      title: info.title, dealType: info.dealType, price: info.priceText, type: info.propertyType,
      area: info.areaText, rooms: info.rooms, region: info.region, station: info.station,
      walk: info.walkText, schools: info.schools, features: info.features, invest: info.investPoints,
      moveIn: info.moveInText,
    }),
    '참고(템플릿 초안):',
    JSON.stringify({ hook: fallback.hook, titles: fallback.titles, badges: fallback.badges }),
    '',
    '다음 JSON으로만 답해라(다른 텍스트 금지): {"hook":"오프닝 훅","titles":["제목1","제목2","제목3"]}',
  ].join('\n')

  const parsed = await geminiJson<{ hook?: string; titles?: string[] }>(prompt)
  return {
    hook: parsed.hook && parsed.hook.trim() ? parsed.hook.trim().slice(0, 30) : fallback.hook,
    titles: Array.isArray(parsed.titles) && parsed.titles.length
      ? parsed.titles.map(String).map(s => s.trim()).filter(Boolean).slice(0, 3)
      : fallback.titles,
    badges: fallback.badges,
    aiUsed: true,
  }
}

// ── Gemini TTS → WAV ──
function pcmToWav(pcm: Uint8Array, sampleRate = 24000): Blob {
  const numCh = 1, bps = 16
  const blockAlign = numCh * bps / 8
  const byteRate = sampleRate * blockAlign
  const buf = new ArrayBuffer(44 + pcm.length)
  const dv = new DataView(buf)
  const wstr = (o: number, s: string) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)) }
  wstr(0, 'RIFF'); dv.setUint32(4, 36 + pcm.length, true); wstr(8, 'WAVE')
  wstr(12, 'fmt '); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true)
  dv.setUint16(22, numCh, true); dv.setUint32(24, sampleRate, true)
  dv.setUint32(28, byteRate, true); dv.setUint16(32, blockAlign, true); dv.setUint16(34, bps, true)
  wstr(36, 'data'); dv.setUint32(40, pcm.length, true)
  new Uint8Array(buf, 44).set(pcm)
  return new Blob([buf], { type: 'audio/wav' })
}

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes
}

/** 나레이션 대본 → 음성(WAV blob URL). 실패 시 throw(호출부가 자막만으로 진행). */
export async function synthesizeTTS(text: string, voice: VoiceGender): Promise<string> {
  const voiceName = voice === 'male' ? 'Charon' : 'Kore'
  const data = await callGemini(TTS_MODELS, [{ text }], {
    responseModalities: ['AUDIO'],
    speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName } } },
  })
  const c = data as { candidates?: { content?: { parts?: { inlineData?: { data?: string; mimeType?: string } }[] } }[] }
  const inline = c.candidates?.[0]?.content?.parts?.find(p => p.inlineData)?.inlineData
  if (!inline?.data) throw new Error('음성 데이터를 받지 못했어요.')
  // Gemini TTS는 보통 audio/L16;rate=24000 PCM — WAV로 감싼다
  const rate = Number((inline.mimeType || '').match(/rate=(\d+)/)?.[1]) || 24000
  const wav = pcmToWav(b64ToBytes(inline.data), rate)
  return URL.createObjectURL(wav)
}
