// AdStudio 분석·생성 호출 — 오마주 이중 구조를 그대로 따른다:
// 1순위 BYOK(키 페이지에 등록한 내 Gemini 키, 브라우저 암호화 보관) → corsProxy 경유
// 2순위 서버 키(Cloud Functions의 GEMINI_API_KEY) → analyzeProduct 함수가 서버에서 분석
import { auth } from './firebase'
// 접속 대상(프로젝트·리전·에뮬레이터 여부)은 firebaseTarget 이 단독으로 결정한다.
import { FN_BASE } from './firebaseTarget'
import { KeyVault } from '../stores/keysStore'
import { GeminiAdapter } from './aiAdapters'
import type { AdAnalysis, AdConfig, ActorMode } from '../stores/adStore'

async function idToken(): Promise<string> {
  const user = auth.currentUser
  if (!user) throw new Error('LOGIN_REQUIRED')
  return user.getIdToken()
}

/** 어댑터가 돌려준 느슨한 JSON을 AdAnalysis로 검증·정규화한다 (얇은 어댑터 원칙: 검증은 호출부) */
function normalizeAnalysis(raw: unknown): AdAnalysis {
  const r = (raw || {}) as Partial<AdAnalysis>
  if (!r.productName || !r.narration) {
    throw new Error('분석 결과가 불완전해요. 자료를 조금 더 자세히 주고 다시 시도해주세요.')
  }
  return {
    productName: r.productName,
    description: r.description || '',
    keyFeatures: Array.isArray(r.keyFeatures) ? r.keyFeatures.map(String) : [],
    targetAudience: r.targetAudience || '',
    mainBenefit: r.mainBenefit || '',
    narration: r.narration,
    callToAction: r.callToAction || '',
    tone: r.tone === 'calm' || r.tone === 'professional' ? r.tone : 'energetic',
  }
}

/* ── 로컬 크롤러 도우미 (선택 설치) ──
   Playwright 내장 소형 프로그램(local-helper/)이 사용자 PC에서 돌고 있으면, 봇 차단
   사이트(네이버 등)·SPA도 실제 브라우저로 렌더링해 텍스트를 가져올 수 있다.
   설치돼 있지 않으면 연결이 즉시 실패하므로 조용히 기존 경로로 폴백한다. */
const LOCAL_HELPER_BASE = 'http://127.0.0.1:8791'

async function fetchViaLocalHelper(url: string): Promise<string | null> {
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 30000)
    const res = await fetch(`${LOCAL_HELPER_BASE}/fetch`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
      signal: ctrl.signal,
    })
    clearTimeout(timer)
    if (!res.ok) return null
    const { text } = await res.json() as { text?: string }
    return typeof text === 'string' && text.trim().length >= 80 ? text : null
  } catch {
    return null
  }
}

/**
 * 제품 자료 분석 — 텍스트·URL·스크린샷 이미지·문서(PDF)를 Gemini로 분석해 광고 컨셉을 돌려준다.
 * 키 페이지에 등록한 BYOK Gemini 키가 있으면 그 키로(무료 일일 쿼터), 없으면 서버 키로 폴백.
 * URL은 로컬 크롤러 도우미가 떠 있으면 그쪽에서 렌더링된 텍스트를 먼저 가져온다.
 * 워드(.docx)는 A2_Source에서 텍스트로 추출돼 text 경로로 들어온다.
 */
export async function analyzeProduct(
  input: {
    text?: string
    url?: string
    imageDataUrl?: string
    document?: { base64: string; mimeType: string }
  }
): Promise<AdAnalysis> {
  // URL 분석: 로컬 도우미가 있으면 진짜 브라우저로 읽은 본문을 텍스트 분석으로 전환
  if (input.url && !input.text && !input.imageDataUrl && !input.document) {
    const crawled = await fetchViaLocalHelper(input.url)
    if (crawled) input = { text: crawled.slice(0, 8000) }
  }

  const byokKey = await KeyVault.getKey('gemini')
  if (byokKey) {
    const raw = input.document
      ? await GeminiAdapter.analyzeProductDocument(input.document.base64, input.document.mimeType, byokKey)
      : input.imageDataUrl
      ? await GeminiAdapter.analyzeProductImage(input.imageDataUrl, byokKey)
      : await GeminiAdapter.analyzeProductInfo(input, byokKey)
    return normalizeAnalysis(raw)
  }

  // 문서(PDF) 분석은 현재 BYOK 경로에서만 지원 — 서버 함수는 텍스트/URL만 받는다
  if (input.document) {
    throw new Error('문서 분석은 키 페이지에서 Google Gemini Flash 키를 등록하면 이용할 수 있어요.')
  }

  const token = await idToken()
  const res = await fetch(`${FN_BASE}/analyzeProduct`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(input),
  })
  if (!res.ok) {
    const msg = await res.text()
    if (msg.includes('Gemini API 키')) {
      throw new Error('Gemini 키가 필요해요. 하단 키 페이지에서 Google Gemini Flash 키를 등록하면 무료로 분석할 수 있어요.')
    }
    throw new Error(msg || `분석 실패 (${res.status})`)
  }
  return normalizeAnalysis(await res.json())
}

export interface GenerateJob {
  jobId: string
  status: string
  estimatedTime: number
  cost: number
}

/**
 * 광고 영상 생성 요청 — 배우 모드에 따라 포인트를 차감하고 작업을 큐에 넣는다.
 * ai: LTX(Kaggle) 자동 생성 / photo: 업로드 사진 무빙포토 (extraction 파이프라인)
 */
export async function generateAd(params: {
  mode: ActorMode
  analysis: AdAnalysis
  config: AdConfig
  photoDataUrl?: string | null
}): Promise<GenerateJob> {
  const token = await idToken()
  const res = await fetch(`${FN_BASE}/generateAd`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      mode: params.mode,
      narration: params.analysis.narration,
      productName: params.analysis.productName,
      sceneHint: `${params.analysis.description} / 타겟: ${params.analysis.targetAudience} / 톤: ${params.analysis.tone}`,
      duration: params.config.duration,
      musicMood: params.config.musicMood,
      voice: params.config.voice,
      photoDataUrl: params.mode === 'photo' ? params.photoDataUrl : undefined,
    }),
  })
  if (!res.ok) throw new Error(await res.text() || `생성 요청 실패 (${res.status})`)
  return res.json()
}
