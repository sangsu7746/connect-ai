import { KeyVault, useKeysStore, assertAlibabaUsable } from '../stores/keysStore'
import { useAdStore } from '../stores/adStore'
import { auth } from './firebase'
import { fnUrl } from './firebaseTarget'
import type { ProviderKey, DialogueMode } from '../types'

// 접속 대상(프로젝트·리전·에뮬레이터 여부)은 firebaseTarget 이 단독으로 결정한다.
const PROXY_BASE_URL = fnUrl('corsProxy')

/**
 * 무료 쿼터/결제 관련 사유로 제공자 API 호출이 거부됐을 때 던지는 전용 에러.
 * 일반 오류와 구분해 "정지 + 유료 전환 안내" UI를 띄우는 데 쓴다.
 */
export class QuotaExhaustedError extends Error {
  constructor(public provider: ProviderKey, message: string) {
    super(message)
    this.name = 'QuotaExhaustedError'
  }
}

// DashScope(알리바바)가 무료 쿼터 소진·연체·미구매 상태에서 반환하는 것으로 공식 문서에 확인된 에러 코드
// (https://www.alibabacloud.com/help/en/model-studio/error-code) — Throttling류(RateQuota/BurstRate 등)는
// 일시적 속도 제한이라 여기서 제외하고, "더 이상 호출이 불가능한" 상태만 포함한다.
const ALIBABA_QUOTA_EXHAUSTED_CODES = [
  'Arrearage',
  'AllocationQuota.FreeTierOnly',
  'CommodityNotPurchased',
  'PrepaidBillOverdue',
  'PostpaidBillOverdue',
]

interface ProxyRequestParams {
  provider: ProviderKey
  apiKey: string
  method: 'GET' | 'POST'
  endpoint: string
  headers?: Record<string, string>
  body?: any
}

/**
 * 프록시 호출에 Firebase ID 토큰을 실어 보낸다.
 *
 * corsProxy는 요청 본문의 임의 endpoint로 fetch하고 사용자의 유료 API 키를 그대로 전달하는데,
 * 인증이 없으면 누구나 이 함수를 임의 URL 릴레이(SSRF)로 쓸 수 있고 Functions 비용도 남에게 물린다.
 * 같은 파일의 edgeTTS 등 다른 함수는 이미 Bearer 토큰을 검증하고 있어 그 방식에 맞춘다.
 *
 * ⚠️ 배포 순서: 이 클라이언트 변경(토큰을 "보내기만" 함)은 지금 함수와도 호환되므로 먼저 배포해도
 * 안전하다. 서버(corsProxy)의 검증은 그 다음에 배포해야 구버전 클라이언트가 끊기지 않는다.
 * 비로그인 상태에서도 기존처럼 동작하도록 토큰이 없으면 헤더 없이 보낸다(서버 검증 도입 시 401이 된다).
 */
async function fetchProxyOnce(requestBody: string): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  try {
    const token = await auth.currentUser?.getIdToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch {
    // 토큰 발급 실패는 호출 자체를 막지 않는다 — 서버가 판단하게 둔다
  }
  return fetch(PROXY_BASE_URL, { method: 'POST', headers, body: requestBody })
}

/**
 * CORS 우회를 위해 Firebase Functions 프록시를 통해 요청을 전달합니다.
 * fetch 자체가 던지는 오류(프록시 서버 연결 거부·일시적 네트워크 끊김 등, HTTP 상태 코드를 받기도
 * 전의 네트워크 레벨 오류)는 짧게 대기 후 한 번 재시도한다 — 단, GET(상태 조회 등 멱등 호출)만
 * 대상이다. fetch()는 "연결 자체가 안 됨"과 "서버는 처리했지만 응답만 유실됨"을 구분해 주지 않아서,
 * generateImage/generateVideo 같은 비멱등 POST(유료 생성 요청)를 맹목적으로 재시도하면 서버가 이미
 * 처리를 마친 요청이 중복 실행돼 이중 과금될 위험이 있다. 실제 API 오류(4xx/5xx 응답)는 재시도해도
 * 결과가 달라지지 않으므로 마찬가지로 대상에서 제외한다.
 */
export async function callProxy({ provider, apiKey, method, endpoint, headers = {}, body }: ProxyRequestParams) {
  const requestBody = JSON.stringify({ provider, apiKey, method, endpoint, headers, payload: body })

  let response: Response
  try {
    response = await fetchProxyOnce(requestBody)
  } catch (e) {
    if (method !== 'GET') throw e
    console.warn('AI 프록시 연결 실패, 잠시 후 한 번 재시도합니다:', e)
    await new Promise(r => setTimeout(r, 600))
    response = await fetchProxyOnce(requestBody)
  }

  if (!response.ok) {
    const errorText = await response.text()

    if (provider === 'alibaba') {
      try {
        const errorBody = JSON.parse(errorText)
        if (ALIBABA_QUOTA_EXHAUSTED_CODES.includes(errorBody.code)) {
          throw new QuotaExhaustedError(
            'alibaba',
            '알리바바 무료 쿼터가 모두 소진됐어요(또는 결제가 필요해요). 콘솔에서 "무료 쿼터만 사용" 설정을 해제하면 이후 생성부터 실제 요금이 청구되는 유료 모드로 전환돼요.'
          )
        }
      } catch (e) {
        if (e instanceof QuotaExhaustedError) throw e
        // JSON 파싱 실패 시 원래 하던 대로 일반 오류로 폴백
      }
    }

    // Gemini 계열 쿼터/크레딧 소진 — 원본 JSON을 그대로 보여주면 원인을 알 수 없어 전용 에러로 바꾼다.
    // Veo(영상)도 같은 Gemini API를 쓰지만 성격이 완전히 달라 구분해서 안내한다: Veo는 무료 등급에
    // 쿼터가 아예 없는 유료 전용 기능이라, 429는 "오늘치 소진"이 아니라 "결제·등급 문제"인 경우가 대부분이다.
    if (provider === 'gemini' && (response.status === 429 || errorText.includes('RESOURCE_EXHAUSTED'))) {
      const isVeo = endpoint.includes('veo-') || endpoint.includes('predictLongRunning')
      const isPrepaid = errorText.includes('prepayment') || errorText.includes('credits are depleted')

      if (isVeo) {
        throw new QuotaExhaustedError(
          'veo',
          isPrepaid
            ? 'Veo 키의 선불 크레딧이 모두 소진됐어요. AI Studio(aistudio.google.com)에서 크레딧을 충전하거나, 고퀄 레인에서 다른 영상 모델을 선택해주세요.'
            : 'Veo 영상 생성 쿼터가 없어요. Veo는 결제가 연결된 유료 등급에서만 동작하는 기능이라, 무료 등급 키이거나 프로젝트에 결제·크레딧이 없으면 이 오류가 납니다. AI Studio에서 이 키의 결제 상태를 확인하거나, 고퀄 레인에서 다른 영상 모델(Hailuo·Seedance)을 선택해주세요.'
        )
      }

      throw new QuotaExhaustedError(
        'gemini',
        isPrepaid
          ? 'Gemini 키의 선불 크레딧이 모두 소진됐어요. 키 페이지에서 무료 등급 프로젝트의 새 키로 교체하거나(aistudio.google.com/apikey), AI Studio에서 크레딧을 충전해주세요.'
          : 'Gemini 무료 쿼터를 오늘치 다 썼어요. 내일 자동으로 초기화되며, 급하면 키 페이지에서 다른 Google 계정의 키로 교체할 수 있어요.'
      )
    }

    // Seedance(BytePlus ModelArk) 리소스팩 미구매 — 사용자가 실제로 겪은 400 오류
    // ("No available resource packs. Please purchase a resource pack first").
    // 원문을 Proxy error로 그대로 노출하면 원인을 알 수 없어서, alibaba·gemini와 같은 패턴으로
    // 전용 에러를 던져 "무엇을 사야 하는지"를 안내한다. ModelArk는 결제수단 등록만으로는
    // Seedance 호출이 안 되고, 모델별 전용 리소스팩을 선불로 사야 한다.
    // ⚠️ 미확인: 이 응답의 error code 필드값 — 문서에서 확인되지 않아 코드 대신 메시지 문구로 판별한다.
    //   콘솔/문서에서 정확한 code를 확인하면 alibaba처럼 코드 목록 매칭으로 바꾸는 게 안전하다.
    if (provider === 'seedance' && /resource pack/i.test(errorText)) {
      throw new QuotaExhaustedError(
        'seedance',
        'ModelArk에서 Dreamina-Seedance-2.0-fast 전용 리소스팩을 먼저 구매해야 해요 — '
        + '결제수단만 등록해도 이 모델은 호출되지 않아요. 콘솔의 Resource packs 메뉴에서 '
        + '"Dreamina-Seedance-2.0-fast" 팩을 구매해주세요(fast 팩은 fast 모델에만 차감돼서, '
        + '일반 2.0 팩을 사면 이 오류가 그대로 납니다). 급하면 고퀄 레인에서 다른 영상 모델을 선택해주세요.'
      )
    }

    // Kling 리소스 패키지 소진·만료 — 공식 에러코드 1102(429). 활성 패키지가 없으면 태스크 생성 자체가
    // 거부되므로, 원문 대신 "무엇을 사야 하는지"를 안내하는 전용 에러로 바꾼다.
    if (provider === 'kling' && (response.status === 429 || /1102|resource pack/i.test(errorText))) {
      throw new QuotaExhaustedError(
        'kling',
        'Kling 리소스 패키지가 없거나 소진·만료됐어요(1102). kling.ai/dev 에서 영상용 리소스 패키지를 구매한 뒤 다시 시도해주세요. '
        + '급하면 고퀄 레인에서 다른 영상 모델을 선택해주세요.'
      )
    }

    throw new Error(`Proxy error (${response.status}): ${errorText}`)
  }

  return response.json()
}

/**
 * (AdStudio) 광고 프로젝트의 "배우 사용 방식"에 따른 인물 유지 지시문.
 * 광고가 아니면(null 반환) 오마주 기본 지시문(얼굴·헤어·체형·의상 전부 유지)을 그대로 쓴다.
 */
function adPreservationDirective(): string | null {
  const s = useAdStore.getState()
  if (!s.analysis) return null
  const { scope, outfit } = s.actorUsage
  if (scope === 'face') {
    return 'preserving the exact same face and hairstyle as shown in the reference image(s) — '
      + 'body build, pose, and outfit are NOT constrained by the reference and should follow the scene description naturally'
  }
  if (outfit === 'restyle') {
    return 'preserving the exact same face, hairstyle, and body type as shown in the reference image(s) — '
      + 'the outfit may be restyled to suit the scene and advertising mood'
  }
  return null // 상반신/전신 + 의상 유지 = 오마주 기본 지시문과 동일
}

// ── Gemini 모델 자동 해석 ─────────────────────────────────────
// Google이 구모델을 예고일보다 빨리 내리는 일이 반복된다(gemini-2.5-flash가 신규 사용자에게
// 2026-07-09부터 404). 모델명을 하드코딩하지 않고, 키로 ListModels를 조회해 실제 사용 가능한
// 최신 flash 모델을 고른다 — 다음 세대 모델이 나와도 코드 수정 없이 자동 대응된다.
const GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta'

// ListModels 조회 자체가 실패했을 때의 폴백 (2026-07 기준 최신 → 구형 순)
const GEMINI_TEXT_FALLBACK = 'gemini-3.5-flash'
const GEMINI_IMAGE_FALLBACK = 'gemini-3.1-flash-image-preview'

let geminiModelCache: { text: string; image: string } | null = null
let geminiModelPromise: Promise<{ text: string; image: string }> | null = null

/** "gemini-3.5-flash" → 305 처럼 버전을 정수화해 최신순 정렬에 쓴다 */
function geminiVersionOf(name: string): number {
  const m = name.match(/gemini-(\d+)(?:\.(\d+))?/)
  if (!m) return 0
  return parseInt(m[1], 10) * 100 + (m[2] ? parseInt(m[2], 10) : 0)
}

async function resolveGeminiModels(apiKey: string): Promise<{ text: string; image: string }> {
  if (geminiModelCache) return geminiModelCache
  if (!geminiModelPromise) {
    geminiModelPromise = (async () => {
      try {
        const data = await callProxy({
          provider: 'gemini',
          apiKey,
          method: 'GET',
          endpoint: `${GEMINI_API_BASE}/models?key=${apiKey}&pageSize=1000`,
        })
        const models: { name: string; supportedGenerationMethods?: string[] }[] = data.models || []
        const usable = models
          .filter(m => (m.supportedGenerationMethods || []).includes('generateContent'))
          .map(m => m.name.replace(/^models\//, ''))

        // 텍스트: 정식 flash 모델(프리뷰·lite·image 변형 제외) 중 최신 버전
        const text = usable
          .filter(n => /^gemini-[\d.]+-flash$/.test(n))
          .sort((a, b) => geminiVersionOf(b) - geminiVersionOf(a))[0] || GEMINI_TEXT_FALLBACK

        // 이미지: flash 계열 이미지 모델 중 최신 버전 (같은 버전이면 lite가 아닌 쪽 우선)
        const image = usable
          .filter(n => n.includes('flash') && n.includes('image'))
          .sort((a, b) => {
            const v = geminiVersionOf(b) - geminiVersionOf(a)
            if (v !== 0) return v
            return (a.includes('lite') ? 1 : 0) - (b.includes('lite') ? 1 : 0)
          })[0] || GEMINI_IMAGE_FALLBACK

        geminiModelCache = { text, image }
        console.log('Gemini 모델 자동 선택:', geminiModelCache)
        return geminiModelCache
      } catch (e) {
        console.warn('Gemini 모델 목록 조회 실패 — 기본 최신 모델명으로 진행:', e)
        geminiModelCache = { text: GEMINI_TEXT_FALLBACK, image: GEMINI_IMAGE_FALLBACK }
        return geminiModelCache
      } finally {
        geminiModelPromise = null
      }
    })()
  }
  return geminiModelPromise
}

export async function geminiTextEndpoint(apiKey: string): Promise<string> {
  const { text } = await resolveGeminiModels(apiKey)
  return `${GEMINI_API_BASE}/models/${text}:generateContent?key=${apiKey}`
}

async function geminiImageEndpoint(apiKey: string): Promise<string> {
  const { image } = await resolveGeminiModels(apiKey)
  return `${GEMINI_API_BASE}/models/${image}:generateContent?key=${apiKey}`
}

/**
 * Gemini 응답에서 본문 텍스트를 뽑는다.
 * Gemini 3.x 사고형(thinking) 모델은 한 응답을 여러 part로 쪼개 보내고 앞쪽에 사고 요약
 * part가 붙기도 한다 — parts[0]만 읽으면 정작 답(JSON)이 든 뒷부분을 놓쳐 "형식을 이해하지
 * 못했어요" 오류가 난다. 그래서 thought part는 걸러내고 나머지 텍스트를 모두 이어 붙인다.
 */
export function geminiText(data: any): string {
  const parts = data?.candidates?.[0]?.content?.parts
  if (!Array.isArray(parts)) return ''
  return parts
    .filter((p: any) => p && typeof p.text === 'string' && !p.thought)
    .map((p: any) => p.text)
    .join('')
    .trim()
}

/** 응답이 비었을 때 원인을 로그로 남긴다 (안전 필터·토큰 한도 등 finishReason 확인용). */
function logGeminiEmpty(where: string, data: any): void {
  console.error(`${where}: Gemini 응답에서 텍스트를 얻지 못했습니다.`, {
    finishReason: data?.candidates?.[0]?.finishReason,
    safetyRatings: data?.candidates?.[0]?.safetyRatings,
    promptFeedback: data?.promptFeedback,
    error: data?.error,
  })
}

/** blob: URL 등 로컬 이미지를 base64로 읽어들인다(원격 API가 접근 못 하는 URL이라 페이로드에 직접 실어 보낸다). */
async function toBase64(imageUrl: string): Promise<{ data: string; mimeType: string }> {
  const res = await fetch(imageUrl)
  const blob = await res.blob()
  const buf = await blob.arrayBuffer()
  const bytes = new Uint8Array(buf)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return { data: btoa(binary), mimeType: blob.type || 'image/jpeg' }
}

/**
 * blob:/data: 같은 이 브라우저 세션에만 존재하는 URL(예: Gemini가 만든 키프레임 — base64를 Blob URL로
 * 변환해 반환함)은 영상 생성 서버가 직접 접근할 수 없어, 그대로 image-to-video API에 넘기면 서버가
 * 첫 프레임 이미지를 못 받아와 생성 태스크가 조용히 실패한다("Alibaba generation task failed" 등).
 * 실제 http(s) URL(Alibaba 자체 생성 이미지, Pollinations 등)은 원격에서 접근 가능하므로 그대로 두고,
 * 로컬 전용 URL만 base64 data URI로 변환해 페이로드에 직접 실어 보낸다.
 */
async function toRemoteAccessibleImage(url: string): Promise<string> {
  if (url.startsWith('http://') || url.startsWith('https://')) return url
  const { data, mimeType } = await toBase64(url)
  return `data:${mimeType};base64,${data}`
}

// ── 알리바바 (Alibaba DashScope) 어댑터 ──
export const AlibabaAdapter = {
  /**
   * Wan2.7 Text-to-Image(및 참조 이미지가 있으면 Image Fusion) API를 호출해 키프레임을 생성합니다.
   * referenceImageUrls를 넘기면 content 배열 앞쪽에 이미지 파트로 실어 보내 인물 일관성을 유도하고,
   * 프롬프트 끝에 "참조 이미지와 동일한 얼굴·체형·의상 유지" 지시문을 덧붙입니다(§인물 일관성 강화).
   * seed를 넘기면(보통 person.id에서 결정론적으로 뽑음) 같은 인물의 여러 씬 생성 호출이 비슷한 결과를
   * 내도록 유도합니다 — DashScope 문서상 "동일 seed+동일 파라미터는 시각적으로 일관된 결과"를 낸다고
   * 명시돼 있지만, 씬마다 프롬프트 텍스트 자체가 달라지므로 완벽한 보장은 아닌 최선의 노력입니다.
   * (DashScope 멀티모달 생성 API는 최대 3장까지 참조 이미지를 지원). 배열이 비어 있으면 순수 T2I로 동작합니다.
   */
  async generateImage(prompt: string, apiKey: string, referenceImageUrls: string[] = [], seed?: number): Promise<string> {
    assertAlibabaUsable() // 무료 기한 만료 시 호출 자체를 차단 (기한 후 호출은 실요금 청구 위험)
    const isIntl = apiKey.startsWith('sk-ws-')
    const baseDomain = isIntl ? 'https://dashscope-intl.aliyuncs.com' : 'https://dashscope.aliyuncs.com'

    const referenceParts = await Promise.all(
      referenceImageUrls.slice(0, 3).map(async url => {
        const { data, mimeType } = await toBase64(url)
        return { image: `data:${mimeType};base64,${data}` }
      })
    )

    const finalPrompt = referenceParts.length > 0
      ? `${prompt}, ${adPreservationDirective() ?? "preserving the exact same face, hairstyle, body type, and outfit as shown in the reference image(s) — do not change the person's appearance"}`
        + '. Even if the scene calls for a non-photorealistic art style (claymation, pixel art, cel-shaded animation, ink wash painting, watercolor, 3D cartoon, etc.), carry this exact person\'s identifiable facial structure, hairstyle, and build into that style rather than defaulting to a generic or different-looking character.'
        + (referenceParts.length > 1
          ? ' The reference images are provided in the same order as the Actor labels in the scene description above (reference image 1 = Actor 1, reference image 2 = Actor 2, etc.) — each actor must keep only the face and appearance of their own corresponding reference image, never swapped with another actor.'
          : '')
      : prompt

    const payload = {
      model: 'wan2.7-image',
      input: {
        messages: [
          {
            role: 'user',
            content: [...referenceParts, { text: finalPrompt }]
          }
        ]
      },
      parameters: {
        size: '1024*576',
        n: 1,
        ...(seed !== undefined ? { seed } : {}),
      }
    }

    const data = await callProxy({
      provider: 'alibaba',
      apiKey,
      method: 'POST',
      endpoint: `${baseDomain}/api/v1/services/aigc/multimodal-generation/generation`,
      body: payload,
    })

    const imageUrl = data.output?.choices?.[0]?.message?.content?.[0]?.image
    if (!imageUrl) {
      throw new Error(data.message || 'Failed to generate image via Alibaba')
    }

    return imageUrl
  },

  /**
   * Wan2.7 Image-to-Video 태스크를 생성합니다 (공식 문서 확인된 실제 모델/엔드포인트로 교정 —
   * 이전 'wan-video-to-video-1.4'는 실존하지 않는 자리표시자 모델명이었음).
   */
  async generateVideo(photoUrl: string, prompt: string, motionPrompt: string, apiKey: string): Promise<string> {
    assertAlibabaUsable() // 무료 기한 만료 시 호출 자체를 차단 (기한 후 호출은 실요금 청구 위험)
    const isIntl = apiKey.startsWith('sk-ws-')
    const baseDomain = isIntl ? 'https://dashscope-intl.aliyuncs.com' : 'https://dashscope.aliyuncs.com'
    const mediaUrl = await toRemoteAccessibleImage(photoUrl)

    const payload = {
      model: 'wan2.7-i2v-2026-04-25',
      input: {
        prompt: `${prompt}, ${motionPrompt}`,
        media: [{ type: 'first_frame', url: mediaUrl }],
      },
      parameters: {
        resolution: '720P',
        duration: 5,
      }
    }

    const data = await callProxy({
      provider: 'alibaba',
      apiKey,
      method: 'POST',
      endpoint: `${baseDomain}/api/v1/services/aigc/video-generation/video-synthesis`,
      headers: { 'X-DashScope-Async': 'enable' },
      body: payload,
    })

    if (!data.output?.task_id) {
      throw new Error(data.message || 'Failed to create Alibaba video generation task')
    }

    return data.output.task_id
  },

  async pollStatus(taskId: string, apiKey: string): Promise<{ status: 'processing' | 'done' | 'failed'; videoUrl?: string }> {
    const isIntl = apiKey.startsWith('sk-ws-')
    const baseDomain = isIntl ? 'https://dashscope-intl.aliyuncs.com' : 'https://dashscope.aliyuncs.com'

    const data = await callProxy({
      provider: 'alibaba',
      apiKey,
      method: 'GET',
      endpoint: `${baseDomain}/api/v1/tasks/${taskId}`,
    })

    const taskStatus = data.output?.task_status
    if (taskStatus === 'SUCCEEDED') {
      return { status: 'done', videoUrl: data.output.video_url }
    } else if (taskStatus === 'FAILED' || taskStatus === 'CANCELED') {
      return { status: 'failed' }
    }

    return { status: 'processing' }
  }
}

// ── Kling (클링) 어댑터 ──
// 공식 문서(https://kling.ai/document-api/apiReference/model/imageToVideo) 확인값으로 전면 교정했다.
// 이전 구현은 낡은 규격(api.klingai.com · /v1/video/image-to-video · model · 대문자 상태값)이라
// 호출 자체가 성립하지 않았다.
//
// ⚠️ 중국 본토 밖에서는 api-singapore 도메인을 써야 한다 — 우리 프록시(Cloud Functions)는
// GCP us-central1에서 밖으로 나가므로 싱가포르 엔드포인트가 맞다.
const KLING_API_BASE = 'https://api-singapore.klingai.com'
// 모델은 반드시 model_name으로 보내야 한다. 공식 문서상 model 필드는 오류 없이 조용히 무시되고
// 기본값(V1)으로 생성돼, "3.0 값을 보내고 V1 결과를 받는" 상태가 된다.
const KLING_MODEL_NAME = 'kling-v3'
// mode를 생략하면 기본 std(720p)로 생성된다 — 기본값에 의존하지 않고 명시해 비용 상한을 고정한다.
// 공식 단가: 1 Unit = $0.14, Kling 3.0(오디오 없음) 720p = 0.6 Unit/초 → 5초 $0.42.
// (pro=1080p는 0.8 Unit/초 → 5초 $0.56. 1080p로 올리려면 여기와 UI 단가 표기를 함께 바꿀 것)
const KLING_MODE = 'std'
const KLING_DURATION = '5'
// 폴링 최대 대기시간. 5초 클립은 보통 1~3분이면 끝나지만, 상한이 없으면 태스크가 제공자 쪽에서
// 멈췄을 때 영원히 pending으로 남는다.
const KLING_POLL_TIMEOUT_MS = 10 * 60 * 1000

export const KlingAdapter = {
  async generateVideo(photoUrl: string, prompt: string, apiKey: string): Promise<string> {
    const image = await toRemoteAccessibleImage(photoUrl)
    // 공통 헬퍼는 로컬 이미지를 'data:<mime>;base64,...' 형태로 만들지만, Kling은 이 data URI
    // 접두사가 붙어 있으면 'Incorrect Base64 format'으로 거부한다 → Kling에 보낼 때만 접두사를
    // 떼어 순수 base64로 넣는다(공통 헬퍼는 다른 제공자가 그대로 쓰므로 건드리지 않는다).
    // http(s) URL은 접두사가 없으니 그대로 통과한다.
    const klingImage = image.replace(/^data:[^;,]*;base64,/, '')

    const payload = {
      model_name: KLING_MODEL_NAME,
      image: klingImage,
      prompt,
      mode: KLING_MODE,
      duration: KLING_DURATION,
    }

    const data = await callProxy({
      provider: 'kling',
      apiKey,
      method: 'POST',
      endpoint: `${KLING_API_BASE}/v1/videos/image2video`,
      body: payload,
    })

    if (!data.data?.task_id) {
      throw new Error(data.message || 'Failed to create Kling task')
    }

    return data.data.task_id
  },

  async pollStatus(taskId: string, apiKey: string): Promise<{ status: 'processing' | 'done' | 'failed'; videoUrl?: string }> {
    const data = await callProxy({
      provider: 'kling',
      apiKey,
      method: 'GET',
      endpoint: `${KLING_API_BASE}/v1/videos/image2video/${taskId}`,
    })

    // 공식 task_status enum은 소문자 submitted / processing / succeed / failed 네 가지다.
    // ('succeeded'가 아니라 'succeed'이며, CANCELLED 같은 값은 존재하지 않는다)
    const state = data.data?.task_status
    if (state === 'succeed') {
      // ⚠️ 공식 경고: 이 결과 URL은 생성 30일 후 서버에서 삭제된다 — 받으면 바로 합성/저장해야 한다.
      const videoUrl = data.data.task_result?.videos?.[0]?.url
      if (!videoUrl) {
        console.error('Kling 응답에 영상 URL이 없습니다:', data.data)
        return { status: 'failed' }
      }
      return { status: 'done', videoUrl }
    } else if (state === 'failed') {
      console.error('Kling task failed:', data.data?.task_status_msg ?? data.message)
      return { status: 'failed' }
    }

    return { status: 'processing' } // submitted · processing
  }
}

// ── Hailuo (MiniMax) 어댑터 ──
// 공식 문서 기준 3단계 비동기 흐름이다:
//   1) 생성 태스크 만들기 → task_id
//   2) task_id로 상태 폴링 → 성공하면 file_id
//   3) file_id로 실제 다운로드 주소 얻기  ← 이 단계가 빠져 있어 영상이 회수되지 않았다
// ⚠️ 국제판(platform.minimax.io 가입)과 중국판(platform.minimaxi.com)은 API 도메인이 다르고,
// 키는 발급받은 쪽 도메인에서만 동작한다(교차 사용 시 인증 실패).
// 국제 계정 기준이며, 중국판 계정 키를 쓴다면 이 한 줄을 https://api.minimaxi.com/v1 로 교체하면 된다.
const MINIMAX_API_BASE = 'https://api.minimax.io/v1'
// 공식 가격표에서 확인한 모델 ID (구형 video-01-live는 더 이상 쓰지 않는다).
const MINIMAX_VIDEO_MODEL = 'MiniMax-Hailuo-2.3'
// 해상도·길이를 명시해 과금을 예측 가능하게 고정한다 — 공식 단가 기준 768P·6초가 최저가
// ($0.28/영상, 1080P 6초는 $0.49, 768P 10초는 $0.56). 씬 길이는 어차피 ffmpeg 병합에서 맞춘다.
const MINIMAX_VIDEO_DURATION = 6
const MINIMAX_VIDEO_RESOLUTION = '768P'
// 폴링 상한 — 공식 문서 권장 폴링 간격은 10초이고, 768P·6초 생성은 보통 수 분 안에 끝난다.
// 상한이 없으면 태스크가 영구 대기 상태에 빠질 때 setInterval이 무한히 돌면서 진행률이 멈춘 채
// 사용자를 붙잡아 둔다(과금은 이미 발생한 상태). 10분을 넘기면 명시적으로 실패시킨다.
const MINIMAX_POLL_TIMEOUT_MS = 10 * 60_000

/**
 * MiniMax는 생성/조회 API의 오류를 응답 본문의 base_resp.status_code(0이 아닌 값)로 알려준다.
 * 코드 의미는 공식 에러코드 문서 기준: 1002=rate limit, 1004=not authorized,
 * 1008=insufficient balance, 1026=입력 민감콘텐츠, 1027=출력 민감콘텐츠,
 * 2049=invalid API Key, 2056=usage limit exceeded.
 * ⚠️ 미확인: 이 오류들이 HTTP 200으로 오는지 4xx로 오는지는 문서에 명시가 없다 — 콘솔/문서에서 확인 후 적용.
 *   (어느 쪽이든 4xx는 callProxy가 먼저 throw하므로, 본문 검사를 추가해도 동작은 안전하다)
 * base_resp가 아예 없는 응답(files/retrieve 등)은 검사를 건너뛴다.
 * Hailuo(MiniMax) 전용 헬퍼다 — 다른 제공자 경로에서는 쓰지 않는다.
 */
function assertMinimaxOk(data: any, context: string): void {
  const raw = data?.base_resp?.status_code
  if (raw === undefined || raw === null) return
  const code = Number(raw)
  if (code === 0) return

  const msg = String(data?.base_resp?.status_msg ?? '').trim()
  const detail = msg ? ` (${msg})` : ''

  if (code === 1008) {
    // QuotaExhaustedError로 던져야 제작 화면이 '잔액 충전' 전용 배너·버튼을 띄운다
    // (일반 Error로 던지면 원인 없는 generic 오류 화면으로 떨어진다)
    throw new QuotaExhaustedError(
      'hailuo',
      'MiniMax 지갑(Balance) 잔액이 부족해요. platform.minimax.io → User Center → Payment → Balance 를 충전한 뒤 다시 시도해주세요. ' +
      'Token Plan의 Credits는 영상 생성에 쓰이지 않아요.'
    )
  }
  if (code === 2056) {
    throw new QuotaExhaustedError(
      'hailuo',
      `MiniMax 사용량 한도를 초과했어요(2056). 플랫폼에서 한도·잔액을 확인해주세요.${detail}`
    )
  }
  if (code === 2049) {
    throw new Error('MiniMax API 키가 올바르지 않아요(2049). 키 문자열 전체를 다시 복사해 키 설정 화면에 등록해주세요.')
  }
  if (code === 1004) {
    throw new Error(
      'MiniMax 인증에 실패했어요(1004). 키가 국제판(platform.minimax.io)에서 발급된 것인지 확인해주세요 — ' +
      '중국판(platform.minimaxi.com) 키는 이 도메인에서 동작하지 않아요.'
    )
  }
  if (code === 1026 || code === 1027) {
    throw new Error(`MiniMax 안전 필터에 걸렸어요(${code}). 사진이나 동작 프롬프트를 바꿔서 다시 시도해주세요.${detail}`)
  }
  throw new Error(`MiniMax ${context} 오류 (${code})${detail}`)
}

export const HailuoAdapter = {
  async generateVideo(photoUrl: string, prompt: string, apiKey: string): Promise<string> {
    const first_frame_image = await toRemoteAccessibleImage(photoUrl)
    const payload = {
      model: MINIMAX_VIDEO_MODEL,
      prompt,
      first_frame_image,
      duration: MINIMAX_VIDEO_DURATION,
      resolution: MINIMAX_VIDEO_RESOLUTION,
      // ⚠️ 미확인: prompt_optimizer는 공식 기본값이 true이며 여기서는 보내지 않아 기본값이 적용된다.
      // 끄는 편이 프롬프트를 그대로 따르게 하지만 품질 영향은 검증되지 않았다 — 콘솔/문서에서 확인 후 적용.
    }

    const data = await callProxy({
      provider: 'hailuo',
      apiKey,
      method: 'POST',
      endpoint: `${MINIMAX_API_BASE}/video_generation`,
      body: payload,
    })

    // 태스크가 만들어지지 않았는데 조용히 넘어가면 곧바로 존재하지 않는 task_id로 폴링하게 된다.
    // 오류 사유(잔액 부족·키 오류 등)를 먼저 사용자에게 그대로 전달한다.
    assertMinimaxOk(data, '영상 생성 요청')

    if (!data.task_id) {
      throw new Error(data.base_resp?.status_msg || 'Failed to create Hailuo task')
    }

    return data.task_id
  },

  async pollStatus(taskId: string, apiKey: string): Promise<{ status: 'processing' | 'done' | 'failed'; videoUrl?: string }> {
    const data = await callProxy({
      provider: 'hailuo',
      apiKey,
      method: 'GET',
      // 공식 조회 경로는 query/video_generation(슬래시)이다 — query_video_generation(언더스코어)이
      // 아니다. 언더스코어로 부르면 태스크는 이미 생성돼 과금된 상태에서 폴링만 404로 실패해서
      // "요금은 나가고 영상은 못 받는" 최악의 결과가 된다. 이 한 글자를 바꾸지 말 것.
      endpoint: `${MINIMAX_API_BASE}/query/video_generation?task_id=${taskId}`,
    })

    // 조회 응답도 오류를 본문(base_resp)으로 돌려준다. 단, 1002(rate limit)는 일시적 제한이라
    // 여기서 실패시키면 이미 과금된 태스크의 결과를 버리게 되므로 계속 대기시킨다
    // (무한 대기는 아래 runTask의 10분 상한이 막아준다).
    if (Number(data?.base_resp?.status_code ?? 0) === 1002) {
      console.warn('Hailuo 조회가 호출 빈도 제한(1002)에 걸렸어요 — 다음 폴링에서 재시도합니다.')
      return { status: 'processing' }
    }
    assertMinimaxOk(data, '영상 상태 조회')

    // 상태 문자열은 대문자로 시작한다(Preparing·Queueing·Processing·Success·Fail) —
    // 대소문자에 흔들리지 않게 정규화해서 비교한다
    const status = String(data.status ?? '').toLowerCase()

    if (status === 'fail' || status === 'failed') {
      console.error('Hailuo task failed:', data.base_resp ?? data)
      return { status: 'failed' }
    }

    if (status === 'success') {
      // 3단계: 폴링이 돌려준 file_id로 실제 다운로드 주소를 받아온다.
      // (구버전 코드는 존재하지 않는 data.file_url을 그대로 썼다 — 그래서 영상이 비어 있었다)
      const fileId = data.file_id
      if (!fileId) {
        console.error('Hailuo 응답에 file_id가 없습니다:', data)
        return { status: 'failed' }
      }

      const fileRes = await callProxy({
        provider: 'hailuo',
        apiKey,
        method: 'GET',
        endpoint: `${MINIMAX_API_BASE}/files/retrieve?file_id=${fileId}`,
      })
      assertMinimaxOk(fileRes, '영상 파일 조회')

      // 공식 응답 스키마의 file 객체에는 download_url만 있다(backup_download_url은 존재하지 않는다).
      // ⚠️ 미확인: 이 download_url의 유효기간과 브라우저 직접 접근(CORS) 허용 여부는 공식 문서에
      // 명시가 없다 — 콘솔/문서에서 확인 후 적용. 회수 즉시 합성에 쓰는 현재 흐름은 유지한다.
      const downloadUrl = fileRes.file?.download_url
      if (!downloadUrl) {
        console.error('Hailuo 파일 다운로드 주소를 얻지 못했습니다:', fileRes)
        return { status: 'failed' }
      }
      return { status: 'done', videoUrl: downloadUrl }
    }

    return { status: 'processing' } // Preparing · Queueing · Processing
  }
}

// ── Seedance (BytePlus ModelArk) 어댑터 ─────────────────────────
// ModelArk 영상 생성 태스크 API: POST /contents/generations/tasks → 태스크 생성,
// GET /contents/generations/tasks/{id} → 폴링. 인증은 Bearer API 키.
//
// ⚠️ 리전 고정: 아래 base URL은 ap-southeast(Asia Pacific / Johor = ap-southeast-1)로 하드코딩돼
// 있다. ModelArk 키는 발급 리전에 묶이므로, 다른 리전에서 만든 키를 넣으면 키 자체는 정상인데도
// 401(인증 실패) 또는 404(모델/엔드포인트 없음)로 실패한다 — 키를 다시 만들어도 같은 증상이면
// 콘솔 가입 리전이 Asia Pacific(Johor)인지 먼저 확인해야 한다. 다른 리전을 쓰려면 이 호스트를
// 해당 리전 호스트로 바꿔야 한다(리전별 호스트는 콘솔/문서에서 확인).
const SEEDANCE_API_BASE = 'https://ark.ap-southeast.bytepluses.com/api/v3'
// ModelArk 콘솔 Model details에서 확인한 실제 Model ID (2026-07 기준).
// fast 변형 사용 중 — 기본 2.0 대비 토큰 소모가 적어 같은 리소스팩으로 더 많은 씬 생성.
// 다른 변형으로 바꾸려면 콘솔의 해당 탭에 표시된 Model ID로 교체하면 된다.
const SEEDANCE_MODEL_ID = 'dreamina-seedance-2-0-fast-260128'
// 폴링 상한 — 다른 유료 제공자(Kling·Hailuo·Veo)와 같은 10분.
const SEEDANCE_POLL_TIMEOUT_MS = 10 * 60_000

export const SeedanceAdapter = {
  async generateVideo(photoUrl: string, prompt: string, apiKey: string): Promise<string> {
    // ⚠️ 미확인: 키프레임을 base64 data URI로 인라인 전송 중이다(toRemoteAccessibleImage). 이미지를
    //   Storage 공개 URL로 올려 url만 넘기는 방식이 페이로드 한도·전송 시간 면에서 더 나은지,
    //   ModelArk가 data URI를 정식 지원하는지 콘솔 Playground/문서에서 확인 후 적용.
    const imageUrl = await toRemoteAccessibleImage(photoUrl)

    // 생성 파라미터는 요청 본문 "최상위 JSON 필드"로 보낸다 — Seedance 2.0은 model·content와 형제
    // 레벨의 resolution/ratio/duration/generate_audio/watermark를 받는다(공식 SDK의
    // tasks.create(model=…, content=[…], resolution=…, ratio=…, duration=…, generate_audio=…,
    // watermark=…) 호출 형태로 확인. 3자 출처 3곳 일치: DataCamp 튜토리얼 · seedance-cli · laozhang).
    //
    // ⚠️ 여기를 프롬프트 텍스트 플래그(`${prompt} --resolution 720p --duration 5`)로 되돌리지 말 것.
    // 그 표기법은 Seedance 1.0 시절 관례이고 2.0에서는 무시된다 — 무시되면 모델 기본값(더 큰 해상도·
    // 긴 길이·오디오 포함)으로 생성돼 씬당 토큰이 2~4배로 뛴다. 게다가 플래그 문자열이 프롬프트
    // 본문의 일부로 해석돼 화면에 글자가 박히는 부작용까지 생길 수 있다.
    //
    // generate_audio: false — AdStudio는 대사를 edgeTTS로 따로 만들고 ffmpeg으로 합성하므로 모델이
    // 만든 오디오는 전부 버려진다. 켜두면 쓰지도 않는 오디오에 토큰을 쓰는 순수 낭비다.
    // resolution 720p · duration 5 — 씬 길이는 병합 단계(ffmpeg)에서 맞춘다. 비용을 더 줄이려면
    // 480p로 낮추면 된다(같은 5초 씬 기준 약 $0.34 → $0.16).
    const payload = {
      model: SEEDANCE_MODEL_ID,
      content: [
        { type: 'text', text: prompt },
        // ⚠️ 미확인: 이미지 role 필드(first_frame)가 필요한지 콘솔 Playground에서 확인 후 적용.
        //   3자 출처끼리도 값이 갈린다(first_frame vs reference_image) — 둘은 의미가 완전히 달라서
        //   (첫 프레임 고정 vs 스타일 참조) 추측으로 넣으면 결과물 성격이 바뀐다. 지금은 role 없이 보낸다.
        { type: 'image_url', image_url: { url: imageUrl } },
      ],
      resolution: '720p',
      ratio: '16:9',
      duration: 5,
      generate_audio: false,
      watermark: false,
    }

    const data = await callProxy({
      provider: 'seedance',
      apiKey,
      method: 'POST',
      endpoint: `${SEEDANCE_API_BASE}/contents/generations/tasks`,
      headers: { 'Content-Type': 'application/json' },
      body: payload,
    })

    if (!data.id) {
      throw new Error(data.error?.message || data.message || 'Failed to create Seedance task')
    }
    return data.id
  },

  async pollStatus(taskId: string, apiKey: string): Promise<{ status: 'processing' | 'done' | 'failed'; videoUrl?: string }> {
    const data = await callProxy({
      provider: 'seedance',
      apiKey,
      method: 'GET',
      endpoint: `${SEEDANCE_API_BASE}/contents/generations/tasks/${taskId}`,
    })

    if (data.status === 'succeeded') {
      return { status: 'done', videoUrl: data.content?.video_url }
    }
    if (data.status === 'failed' || data.status === 'cancelled') {
      console.error('Seedance task failed:', data.error || data)
      return { status: 'failed' }
    }
    return { status: 'processing' } // queued | running
  },
}

// ── Veo (Google) 어댑터 ─────────────────────────────────────────
// ⚠️ 인증 경로 주의: Vertex AI(aiplatform.googleapis.com)는 API 키를 받지 않고 OAuth2 액세스
// 토큰을 요구해서, 브라우저 BYOK(키 하나) 구조로는 호출할 수 없다. 그래서 API 키로 인증되는
// Gemini API(generativelanguage.googleapis.com)의 Veo 엔드포인트를 쓴다 — 같은 Veo 모델이고
// 결제만 프로젝트에 연결돼 있으면(무료 등급 키로는 Veo 호출 불가) 동작한다.
// 호출은 장기 실행 작업(predictLongRunning) → operation 폴링 → 파일 URI 다운로드 3단계다.
//
// ⚠️ 미확인: 인증을 ?key= 쿼리파라미터 대신 x-goog-api-key 헤더로 바꾸는 것 — 콘솔/문서에서 확인 후 적용.
//   (지금 429가 돌아오는 것으로 보아 쿼리파라미터 인증 자체는 통과 중이고, 영상 파일 다운로드 URI가
//    서명 리다이렉트를 타므로 헤더 방식으로 바꾸면 다운로드 단계까지 재검증이 필요하다)
const VEO_API_BASE = 'https://generativelanguage.googleapis.com/v1beta'
const VEO_MODEL_ID = 'veo-3.1-fast-generate-preview'
// 공식 문서(ai.google.dev/gemini-api/docs/video) 확인값 — 생성 길이·해상도를 반드시 명시한다.
// · durationSeconds 허용값은 4 | 6 | 8 뿐이다(5초는 불가). extension·referenceImages를 쓰거나
//   1080p·4k로 올리면 8만 허용되므로, 6초를 쓰는 지금 조합에서는 720p를 벗어날 수 없다.
// · 미지정 시 Veo 기본값은 8초 → 우리 씬은 5~6초라 ffmpeg 병합에서 뒤가 잘려 나가는데도 8초로 청구됐다.
// · resolution 미지정은 문서화되지 않은 기본값 의존이다. 단가가 720p $0.10/초, 1080p $0.12/초,
//   4k $0.30/초로 최대 3배 차이나므로 최저가인 720p로 고정한다.
//   → 6초 × $0.10 = 씬당 약 $0.60 (UI 단가 표기와 함께 관리할 것)
export const VEO_DURATION_SECONDS = 6
const VEO_RESOLUTION = '720p'
// 폴링 최대 대기시간. 상한이 없으면 작업이 Google 쪽에서 멈췄을 때 폴링이 영원히 반복되면서
// Cloud Functions(프록시) 호출 비용만 계속 쌓인다.
const VEO_POLL_TIMEOUT_MS = 10 * 60 * 1000

export const VeoAdapter = {
  /** 이미지+프롬프트로 영상 생성 작업을 만들고 operation 이름을 반환한다. */
  async generateVideo(photoUrl: string, prompt: string, apiKey: string): Promise<string> {
    const { data: base64, mimeType } = await toBase64(photoUrl)

    const data = await callProxy({
      // Gemini API는 Authorization 헤더가 아니라 endpoint의 key 쿼리파라미터로 인증한다 —
      // 프록시의 'gemini' 분기가 이 규칙을 그대로 따르므로 provider를 gemini로 보낸다
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: `${VEO_API_BASE}/models/${VEO_MODEL_ID}:predictLongRunning?key=${apiKey}`,
      body: {
        instances: [{ prompt, image: { bytesBase64Encoded: base64, mimeType } }],
        parameters: {
          // ⚠️ 이 프로젝트의 기본 출력은 세로(9:16)인데 여기는 16:9다 — 세로 광고로 내보낼 때
          // 레터박스(위아래 검은 띠) 또는 좌우 크롭이 생긴다. 다만 키프레임 이미지 생성도 16:9라
          // 지금은 파이프라인 내부적으로 일관된 상태여서 값을 바꾸지 않았다. 세로로 돌리려면
          // 키프레임 생성 비율까지 함께 바꿔야 한다(공식 허용값은 '16:9' | '9:16').
          aspectRatio: '16:9',
          // 길이·해상도 미지정 시 Veo는 8초·문서화되지 않은 기본 해상도로 만들고 그만큼 청구한다.
          durationSeconds: VEO_DURATION_SECONDS,
          resolution: VEO_RESOLUTION,
        },
      },
    })

    if (!data.name) {
      throw new Error(data.error?.message || 'Veo 영상 생성 작업을 만들지 못했어요')
    }
    return data.name
  },

  /**
   * 작업 상태를 확인하고, 완료됐으면 결과 영상을 내려받아 blob URL로 돌려준다.
   * (Veo 결과 URI는 API 키가 있어야 접근 가능한 주소라 프록시로 받아 base64 → blob으로 바꾼다)
   */
  async pollStatus(operationName: string, apiKey: string): Promise<{ status: 'processing' | 'done' | 'failed'; videoUrl?: string }> {
    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'GET',
      endpoint: `${VEO_API_BASE}/${operationName}?key=${apiKey}`,
    })

    if (!data.done) return { status: 'processing' }
    if (data.error) {
      console.error('Veo task failed:', data.error)
      return { status: 'failed' }
    }

    const uri = data.response?.generateVideoResponse?.generatedSamples?.[0]?.video?.uri
      ?? data.response?.generatedSamples?.[0]?.video?.uri
    if (!uri) {
      console.error('Veo 응답에 영상 URI가 없습니다:', data.response)
      return { status: 'failed' }
    }

    // 파일 다운로드 — 프록시가 바이너리를 base64로 감싸 돌려준다(functions/index.js 참고)
    const file = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'GET',
      endpoint: uri.includes('?') ? `${uri}&key=${apiKey}` : `${uri}?key=${apiKey}`,
    })
    if (!file.base64) {
      console.error('Veo 영상 파일을 내려받지 못했습니다:', file)
      return { status: 'failed' }
    }

    const bytes = Uint8Array.from(atob(file.base64), c => c.charCodeAt(0))
    const blobUrl = URL.createObjectURL(new Blob([bytes], { type: file.contentType || 'video/mp4' }))
    return { status: 'done', videoUrl: blobUrl }
  },
}

// ── 제공자 공통 라우터 ──
export const GenericAIAdapter = {
  async runTask(provider: ProviderKey, photoUrl: string, prompt: string): Promise<{ videoUrl: string }> {
    const apiKey = await KeyVault.getKey(provider)
    if (!apiKey) {
      throw new Error(`No API key found for ${provider}`)
    }

    // 각 제공자별 라우팅
    if (provider === 'alibaba') {
      const taskId = await AlibabaAdapter.generateVideo(photoUrl, prompt, 'slow camera motion', apiKey)
      return new Promise((resolve, reject) => {
        const interval = setInterval(async () => {
          try {
            const res = await AlibabaAdapter.pollStatus(taskId, apiKey)
            if (res.status === 'done' && res.videoUrl) {
              clearInterval(interval)
              resolve({ videoUrl: res.videoUrl })
            } else if (res.status === 'failed') {
              clearInterval(interval)
              reject(new Error('Alibaba generation task failed'))
            }
          } catch (e) {
            clearInterval(interval)
            reject(e)
          }
        }, 5000)
      })
    }

    if (provider === 'kling') {
      const taskId = await KlingAdapter.generateVideo(photoUrl, prompt, apiKey)
      return new Promise((resolve, reject) => {
        // 폴링 상한 10분 — 상한이 없으면 제공자 쪽 태스크가 멈췄을 때 interval이 영구히 돌며
        // 씬이 영영 "생성 중"으로 남는다. 상한을 넘기면 실패로 끊어 재시도/다른 모델로 넘길 수 있게 한다.
        const startedAt = Date.now()
        const interval = setInterval(async () => {
          try {
            if (Date.now() - startedAt > KLING_POLL_TIMEOUT_MS) {
              clearInterval(interval)
              reject(new Error('Kling 영상 생성이 10분 안에 끝나지 않았어요. 잠시 뒤 다시 시도하거나 다른 모델을 선택해주세요.'))
              return
            }
            const res = await KlingAdapter.pollStatus(taskId, apiKey)
            if (res.status === 'done' && res.videoUrl) {
              clearInterval(interval)
              resolve({ videoUrl: res.videoUrl })
            } else if (res.status === 'failed') {
              clearInterval(interval)
              reject(new Error('Kling generation task failed'))
            }
          } catch (e) {
            clearInterval(interval)
            reject(e)
          }
        }, 5000)
      })
    }

    if (provider === 'hailuo') {
      const taskId = await HailuoAdapter.generateVideo(photoUrl, prompt, apiKey)
      return new Promise((resolve, reject) => {
        // 상한 없는 폴링은 태스크가 큐에 갇히면 영원히 돌면서 진행 화면을 멈춰 세운다(Kaggle 경로와 동일한 방식으로 상한을 둔다).
        const startedAt = Date.now()
        const interval = setInterval(async () => {
          try {
            if (Date.now() - startedAt > MINIMAX_POLL_TIMEOUT_MS) {
              clearInterval(interval)
              reject(new Error(
                `Hailuo 영상 생성이 ${Math.round(MINIMAX_POLL_TIMEOUT_MS / 60_000)}분 안에 끝나지 않았어요. ` +
                'MiniMax 플랫폼(platform.minimax.io)에서 태스크 상태를 확인해주세요 — 이미 생성된 태스크는 요금이 청구될 수 있어요.'
              ))
              return
            }
            const res = await HailuoAdapter.pollStatus(taskId, apiKey)
            if (res.status === 'done' && res.videoUrl) {
              clearInterval(interval)
              resolve({ videoUrl: res.videoUrl })
            } else if (res.status === 'failed') {
              clearInterval(interval)
              reject(new Error('Hailuo generation task failed'))
            }
          } catch (e) {
            clearInterval(interval)
            reject(e)
          }
        }, 5000)
      })
    }

    if (provider === 'seedance') {
      const taskId = await SeedanceAdapter.generateVideo(photoUrl, prompt, apiKey)
      return new Promise((resolve, reject) => {
        // 상한 없는 폴링은 ModelArk 태스크가 큐에 갇히면 영원히 돌면서 진행 화면을 멈춰 세운다
        // (Kling·Hailuo 경로와 동일한 방식으로 상한을 둔다).
        const startedAt = Date.now()
        const interval = setInterval(async () => {
          try {
            if (Date.now() - startedAt > SEEDANCE_POLL_TIMEOUT_MS) {
              clearInterval(interval)
              reject(new Error(
                `Seedance 영상 생성이 ${Math.round(SEEDANCE_POLL_TIMEOUT_MS / 60_000)}분 안에 끝나지 않았어요. ` +
                `ModelArk 콘솔에서 태스크 상태를 확인해주세요 — 이미 생성된 태스크는 리소스팩 토큰이 차감될 수 있어요(task: ${taskId}).`
              ))
              return
            }
            const res = await SeedanceAdapter.pollStatus(taskId, apiKey)
            if (res.status === 'done' && res.videoUrl) {
              clearInterval(interval)
              resolve({ videoUrl: res.videoUrl })
            } else if (res.status === 'failed') {
              clearInterval(interval)
              reject(new Error('Seedance generation task failed'))
            }
          } catch (e) {
            clearInterval(interval)
            reject(e)
          }
        }, 5000)
      })
    }

    if (provider === 'veo') {
      const operationName = await VeoAdapter.generateVideo(photoUrl, prompt, apiKey)
      return new Promise((resolve, reject) => {
        // Veo는 보통 1~3분 걸린다 — 폴링 간격을 다른 제공자(5초)보다 길게 잡아 호출 수를 줄인다
        const startedAt = Date.now()
        const interval = setInterval(async () => {
          try {
            if (Date.now() - startedAt > VEO_POLL_TIMEOUT_MS) {
              clearInterval(interval)
              // 이미 생성이 시작된(=과금된) 작업이므로, 나중에 수동으로 결과를 회수할 수 있게
              // operation name을 콘솔에 남긴다.
              // 회수: GET https://generativelanguage.googleapis.com/v1beta/{operationName}?key=<API 키>
              console.error(
                `Veo 폴링 시간 초과(${VEO_POLL_TIMEOUT_MS / 60000}분) — 작업은 서버에서 계속 진행될 수 있어요. ` +
                `수동 회수용 operation name: ${operationName}`
              )
              reject(new Error(`Veo 영상 생성이 ${VEO_POLL_TIMEOUT_MS / 60000}분 안에 끝나지 않았어요. 이미 시작된 작업이라 요금은 청구될 수 있어요(operation: ${operationName}).`))
              return
            }
            const res = await VeoAdapter.pollStatus(operationName, apiKey)
            if (res.status === 'done' && res.videoUrl) {
              clearInterval(interval)
              resolve({ videoUrl: res.videoUrl })
            } else if (res.status === 'failed') {
              clearInterval(interval)
              reject(new Error('Veo generation task failed'))
            }
          } catch (e) {
            clearInterval(interval)
            reject(e)
          }
        }, 10000)
      })
    }

    // 기본 폴백 (목업 비디오 출력) — 위 분기가 없는 제공자는 'runway' 하나뿐이라 여기로 오는 것도 runway뿐이다.
    // (sceneRenderer의 REAL_ADAPTER_PROVIDERS 목록과 반드시 짝을 맞춰 유지할 것 — 어긋나면 실제로 과금된
    //  생성에 "연동 준비 중이라 임시 영상으로 대체했다"는 거짓 안내가 뜬다)
    await new Promise(r => setTimeout(r, 3000))
    return { videoUrl: 'https://sample-videos.com/video321/mp4/720/big_buck_bunny_720p_1mb.mp4' }
  }
}

// ── Kaggle + LTX (저품질 무료 레인) 어댑터 ──────────────────────
//
// 사용자 본인의 Kaggle 계정(주 30 GPU시간, 매주 갱신)에 이미지→영상 파이썬 스크립트 커널을
// push하고, 완료를 폴링한 뒤 output의 mp4를 회수한다 — 전 과정이 BYOK(본인 토큰·본인 GPU)라
// 앱 비용이 0원이고, 그래서 포인트 차감 없는 "저품질·느림·무료" 경로가 성립한다.
//
// 모델은 LTX 계열 오픈소스(Lightricks) 중 diffusers로 실행 가능한 경량 LTX-Video를 쓴다 —
// 최신 LTX-2.3(22B)은 Kaggle 무료 GPU(16GB)에 올라가지 않아서, diffusers가 2.3 양자화 변형을
// 지원하게 되면 아래 KAGGLE_LTX_MODEL_ID만 교체하면 된다.
const KAGGLE_API_BASE = 'https://www.kaggle.com/api/v1'
const KAGGLE_LTX_MODEL_ID = 'Lightricks/LTX-Video'
const KAGGLE_POLL_INTERVAL_MS = 20_000
const KAGGLE_TIMEOUT_MS = 40 * 60_000 // 부팅+의존성 설치+모델 다운로드+생성까지 최대 40분

/** KeyVault의 'kaggle' 값("username:key")을 분해한다. 형식이 틀리면 null. */
function parseKaggleCredential(raw: string): { username: string; token: string } | null {
  const idx = raw.indexOf(':')
  if (idx <= 0 || idx === raw.length - 1) return null
  return { username: raw.slice(0, idx).trim(), token: raw.slice(idx + 1).trim() }
}

/**
 * 커널에서 실행될 파이썬 스크립트를 만든다. 키프레임 이미지는 별도 업로드 채널 없이
 * base64로 소스에 직접 심는다(1024² JPG 기준 약 0.5MB — push 페이로드 한도 내).
 * 프롬프트는 JSON.stringify로 감싼다 — JSON 문자열 리터럴은 파이썬에서도 유효해서
 * 따옴표·줄바꿈이 섞여도 안전하게 이스케이프된다.
 */
function buildLtxKernelSource(imageB64: string, prompt: string, durationSec: number): string {
  // LTX 제약: 프레임 수는 8n+1, 해상도는 32의 배수 — 세로(9:16) 480×832, 24fps 기준
  const rawFrames = Math.round(Math.max(2, durationSec) * 24)
  const frames = Math.min(121, Math.max(9, Math.floor((rawFrames - 1) / 8) * 8 + 1))
  return [
    '# AdStudio LTX runner — generated automatically, do not edit',
    'import base64, subprocess, sys',
    "subprocess.run([sys.executable, '-m', 'pip', 'install', '-q',",
    "  'diffusers>=0.32.0', 'transformers', 'accelerate', 'imageio[ffmpeg]', 'sentencepiece', 'protobuf'], check=True)",
    'import torch',
    'from diffusers import LTXImageToVideoPipeline',
    'from diffusers.utils import export_to_video, load_image',
    '',
    `IMG_B64 = "${imageB64}"`,
    `PROMPT = ${JSON.stringify(prompt)}`,
    'NEGATIVE = "worst quality, inconsistent motion, blurry, jittery, distorted, deformed"',
    `NUM_FRAMES = ${frames}`,
    '',
    "with open('input.png', 'wb') as f:",
    '    f.write(base64.b64decode(IMG_B64))',
    '',
    '# T4는 bf16 텐서코어가 없어 fp16으로 실행한다',
    `pipe = LTXImageToVideoPipeline.from_pretrained('${KAGGLE_LTX_MODEL_ID}', torch_dtype=torch.float16)`,
    'pipe.enable_model_cpu_offload()',
    "image = load_image('input.png')",
    'video = pipe(image=image, prompt=PROMPT, negative_prompt=NEGATIVE,',
    '             width=480, height=832, num_frames=NUM_FRAMES, num_inference_steps=30).frames[0]',
    "export_to_video(video, 'output.mp4', fps=24)",
    "print('MEMORYFRAME_DONE')",
  ].join('\n')
}

export const KaggleLtxAdapter = {
  /** Kaggle API 호출 공통부 — Basic 인증은 corsProxy의 'kaggle' 분기가 붙여준다. */
  async call(method: 'GET' | 'POST', path: string, basicToken: string, body?: any): Promise<any> {
    return callProxy({
      provider: 'kaggle',
      apiKey: basicToken,
      method,
      endpoint: `${KAGGLE_API_BASE}${path}`,
      body,
    })
  },

  /**
   * 키프레임 이미지 1장 → LTX 영상 1클립. push → status 폴링 → output mp4 회수.
   * sceneId 기반 고정 슬러그를 써서 같은 씬의 재시도는 새 커널이 아니라 새 버전으로 쌓인다.
   */
  async runTask(photoUrl: string, prompt: string, durationSec: number, sceneId: string): Promise<{ videoUrl: string }> {
    const raw = await KeyVault.getKey('kaggle')
    const cred = raw ? parseKaggleCredential(raw) : null
    if (!cred) {
      throw new Error('Kaggle 토큰 형식이 올바르지 않아요. 키 설정에서 "유저명:키" 형식으로 다시 등록해주세요.')
    }
    const basicToken = btoa(`${cred.username}:${cred.token}`)

    // 1) 키프레임을 base64로 준비해 스크립트에 심는다
    const { data: imageB64 } = await toBase64(photoUrl)
    const slug = `mf-ltx-${sceneId.replace(/-/g, '').slice(0, 12)}`
    const source = buildLtxKernelSource(imageB64, prompt, durationSec)

    // 2) 커널 push — GPU·인터넷 활성, 비공개 스크립트
    const pushRes = await this.call('POST', '/kernels/push', basicToken, {
      slug: `${cred.username}/${slug}`,
      newTitle: `AdStudio LTX ${slug}`,
      text: source,
      language: 'python',
      kernelType: 'script',
      isPrivate: true,
      enableGpu: true,
      enableTpu: false,
      enableInternet: true,
      datasetDataSources: [],
      competitionDataSources: [],
      kernelDataSources: [],
      modelDataSources: [],
      categoryIds: [],
    })
    if (pushRes?.error) {
      throw new Error(`Kaggle 커널 등록에 실패했어요: ${pushRes.error}`)
    }

    // 3) 완료 폴링 — 세션 부팅·pip 설치·모델 다운로드가 있어 오래 걸린다(정상)
    const startedAt = Date.now()
    for (;;) {
      await new Promise(r => setTimeout(r, KAGGLE_POLL_INTERVAL_MS))
      if (Date.now() - startedAt > KAGGLE_TIMEOUT_MS) {
        throw new Error('Kaggle 생성이 40분 안에 끝나지 않았어요. kaggle.com 내 노트북에서 상태를 확인해주세요.')
      }
      const st = await this.call('GET', `/kernels/status?userName=${encodeURIComponent(cred.username)}&kernelSlug=${encodeURIComponent(slug)}`, basicToken)
      const status = String(st?.status ?? '').toLowerCase()
      if (status === 'complete') break
      if (status === 'error' || status === 'cancelacknowledged') {
        const reason = st?.failureMessage || '알 수 없는 오류'
        throw new Error(
          `Kaggle 커널 실행이 실패했어요: ${reason}. GPU 사용에는 전화번호 인증이 필요하고, 주간 GPU 쿼터(30시간)가 남아있어야 해요.`
        )
      }
      // queued/running → 계속 대기
    }

    // 4) output에서 mp4 회수 — 서명 URL은 브라우저에서 CORS가 막혀 프록시의 바이너리 경로로 받는다
    const out = await this.call('GET', `/kernels/output?userName=${encodeURIComponent(cred.username)}&kernelSlug=${encodeURIComponent(slug)}`, basicToken)
    const mp4 = (out?.files ?? []).find((f: any) => String(f.fileName ?? '').endsWith('.mp4'))
    if (!mp4?.url) {
      throw new Error('Kaggle 커널은 완료됐지만 출력 mp4를 찾지 못했어요. 노트북 로그를 확인해주세요.')
    }
    const fileRes = await callProxy({
      provider: 'kaggle' as ProviderKey, // 인증 헤더 불필요한 서명 URL — corsProxy가 binary→base64로 변환해 돌려준다
      apiKey: basicToken,
      method: 'GET',
      endpoint: mp4.url,
    })
    if (!fileRes?.base64) {
      throw new Error('출력 영상 다운로드에 실패했어요. 잠시 후 다시 시도해주세요.')
    }
    const bytes = Uint8Array.from(atob(fileRes.base64), c => c.charCodeAt(0))
    const blobUrl = URL.createObjectURL(new Blob([bytes], { type: fileRes.contentType || 'video/mp4' }))
    return { videoUrl: blobUrl }
  },
}

export interface GeneratedStoryboardScene {
  descKo: string
  dialogueKo: string
  keyframePromptEn: string
  motionPromptEn: string
}

// ── Gemini (비전 디스크립터 · 이미지 생성) 어댑터 ──
export const GeminiAdapter = {
  /**
   * Gemini 이미지 생성 모델(자동 해석 — resolveGeminiModels)로 키프레임을 생성한다.
   * referenceImageUrls(인물 크롭)를 inlineData로 실어 보내 "참조 사진 속 인물과 동일 인물"로
   * 그리도록 지시한다 — 이 모델은 참조 이미지 기반 인물 동일성 유지가 강점이라, 선정된 배우의
   * 얼굴·헤어·체형을 씬마다 일관되게 유지하는 핵심 경로다. 결과는 base64로 내려오므로
   * Blob URL로 변환해 반환한다(앱 내 <img>/ffmpeg 소스로 바로 사용 가능).
   */
  async generateImage(prompt: string, apiKey: string, referenceImageUrls: string[] = []): Promise<string> {
    const referenceParts = await Promise.all(
      referenceImageUrls.slice(0, 3).map(async url => {
        const { data, mimeType } = await toBase64(url)
        return { inlineData: { mimeType, data } }
      })
    )

    const adDirective = adPreservationDirective()
    const finalPrompt = referenceParts.length > 0
      ? `Generate a cinematic 16:9 image of this scene: ${prompt}. `
        + 'The person(s) in the scene MUST be the exact same person(s) as in the attached reference photo(s) — '
        + (adDirective
          ? `${adDirective}. `
          : 'keep the identical face, hairstyle, hair color, body type, and overall appearance. ')
        + 'Do not replace them with a different or generic person. '
        + 'Even if the scene calls for a non-photorealistic art style (claymation, pixel art, cel-shaded animation, '
        + 'ink wash painting, watercolor, 3D cartoon, etc.), translate this exact person\'s identifiable facial '
        + 'structure, hairstyle, and build into that style — do not default to a generic or different-looking '
        + 'character just because the rendering medium changes.'
        + (referenceParts.length > 1
          ? ' The reference images are attached in the same order as the Actor labels in the scene description above '
            + '(1st attached image = Actor 1, 2nd attached image = Actor 2, etc.) — each actor must keep only the face '
            + 'and appearance of their own corresponding reference image, never swapped with another actor.'
          : '')
      : prompt

    const payload = {
      contents: [{
        parts: [...referenceParts, { text: finalPrompt }],
      }],
      generationConfig: {
        responseModalities: ['TEXT', 'IMAGE'],
        imageConfig: { aspectRatio: '16:9' },
      },
    }

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiImageEndpoint(apiKey),
      body: payload,
    })
    useKeysStore.getState().updateGeminiUsage('image')

    const parts: any[] = data.candidates?.[0]?.content?.parts ?? []
    const imagePart = parts.find(p => p.inlineData?.data)
    if (!imagePart) {
      const textPart = parts.find(p => p.text)?.text
      throw new Error(textPart || data.error?.message || 'Gemini 이미지 생성에 실패했어요')
    }

    const { mimeType, data: b64 } = imagePart.inlineData
    const binary = atob(b64)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    const blob = new Blob([bytes], { type: mimeType || 'image/png' })
    return URL.createObjectURL(blob)
  },

  /**
   * 인물 크롭 이미지를 짧은 영어 특징 문구로 캡션화한다(키프레임 프롬프트에 주입해 T2I가
   * "protagonist" 같은 일반 명사 대신 실제 인물의 특징을 반영하도록 유도). 신원 추정(이름 등)은
   * 요청하지 않고 연령대·성별표현·헤어·복장 등 순수 시각 특징만 받는다.
   */
  async describePersonImage(imageUrl: string, apiKey: string): Promise<string> {
    const { data: base64, mimeType } = await toBase64(imageUrl)

    const payload = {
      contents: [{
        parts: [
          {
            text: "Describe this person's visible appearance as a short comma-separated phrase "
              + '(under 20 words) for use in an AI image generation prompt. Mention only: apparent '
              + 'age range, gender presentation, hair style/color, and clothing style. Do not guess '
              + 'a name or identity, do not mention the background. English only, no full sentences, no markdown.',
          },
          { inlineData: { mimeType, data: base64 } },
        ],
      }],
    }

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiTextEndpoint(apiKey),
      body: payload,
    })
    useKeysStore.getState().updateGeminiUsage('text')

    const text = geminiText(data)
    if (!text) throw new Error(data.error?.message || 'Gemini 이미지 분석에 실패했어요')
    return String(text).trim()
  },

  /**
   * 대사·씬 설명 텍스트를 대상 언어로 번역한다(글로벌 지원용). 번역문만 돌려받도록
   * 프롬프트를 강하게 제약한다 — 설명이나 따옴표가 섞이면 자막/TTS 입력이 오염되기 때문.
   */
  async translateText(text: string, targetLanguageName: string, apiKey: string): Promise<string> {
    const payload = {
      contents: [{
        parts: [{
          text: `Translate the following text into ${targetLanguageName}. `
            + 'Reply with ONLY the translated text — no explanation, no quotes, no original text, no markdown.\n\n'
            + text,
        }],
      }],
    }

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiTextEndpoint(apiKey),
      body: payload,
    })
    useKeysStore.getState().updateGeminiUsage('text')

    const translated = geminiText(data)
    if (!translated) throw new Error(data.error?.message || 'Gemini 번역에 실패했어요')
    return String(translated).trim()
  },

  /**
   * 템플릿의 참고용 원본 씬들을 few-shot 예시로 주고, 같은 인물 구성·전개(기승전결)를 유지한 채
   * 완전히 새로운 대사·설명·프롬프트를 창작하게 한다. responseMimeType으로 JSON을 강제해 파싱
   * 실패 리스크를 줄이지만, 배열 길이·필드 공백 등 스키마 검증은 얇은 어댑터 원칙에 따라
   * 호출부(storyboardGenerator.ts)가 한다. (예전엔 Groq가 이 역할이었으나 BYOK 키 하나를 줄이려고
   * Gemini로 통합했다 — 키 등록 부담과 관리할 제공자 수를 줄이는 게 목적.)
   */
  async generateStoryboardScenes(
    referenceScenes: GeneratedStoryboardScene[],
    context: { relationKo: string; dialogueMode: DialogueMode; sceneCount: number },
    apiKey: string
  ): Promise<GeneratedStoryboardScene[]> {
    const dialogueInstruction = context.dialogueMode === 'none'
      ? '이 스토리는 대사가 없습니다. dialogueKo는 빈 문자열("")로 두세요.'
      : '각 씬에 짧고 자연스러운 한국어 대사를 하나씩 넣으세요(1~2문장, 소리 내어 말하는 대사처럼).'

    const prompt = `당신은 세로형(9:16) 짧은 영상 스토리보드를 쓰는 한국어 각본가입니다. 아래는 "${context.relationKo}" 관계의 인물이 나오는 ${context.sceneCount}개 씬짜리 세로형(9:16) 영상 스토리보드 예시입니다 (참고용 — 분위기와 각 씬의 역할만 참고하고 내용은 그대로 베끼지 마세요):
${referenceScenes.map((s, i) => `씬 ${i + 1}: 설명="${s.descKo}" / 대사="${s.dialogueKo}" / 비주얼프롬프트="${s.keyframePromptEn}" / 카메라모션="${s.motionPromptEn}"`).join('\n')}

위 예시와 같은 인물 구성·전개 순서(기승전결)를 유지하되, 완전히 새로운 스토리로 ${context.sceneCount}개 씬을 창작하세요. ${dialogueInstruction} 실존 유명인, 브랜드명, 폭력적이거나 선정적인 내용은 절대 포함하지 마세요.

반드시 아래 JSON 형식으로만, 정확히 ${context.sceneCount}개의 항목을 담아 응답하세요. 다른 설명은 절대 포함하지 마세요:
{"scenes":[{"descKo":"한국어 장면 설명","dialogueKo":"한국어 대사(없으면 빈 문자열)","keyframePromptEn":"영어 비주얼 프롬프트(쉼표로 구분된 시각 요소, 완성된 문장 아님, 카메라 움직임 언급 금지)","motionPromptEn":"영어 카메라 움직임 지시(예: slow dolly-in, gentle pan left)"}, ...]}`

    const payload = {
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: {
        temperature: 0.9,
        responseMimeType: 'application/json',
      },
    }

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiTextEndpoint(apiKey),
      body: payload,
    })
    useKeysStore.getState().updateGeminiUsage('text')

    const content = geminiText(data)
    if (!content) throw new Error(data.error?.message || 'Gemini 스토리보드 생성에 실패했어요')
    const parsed = JSON.parse(content)
    return parsed.scenes
  },

  /**
   * (AdStudio) 제품/기업 자료를 분석해 광고 컨셉 JSON을 만든다. 텍스트 자료 또는
   * URL(Gemini의 urlContext 도구가 페이지를 직접 읽음 — 클라이언트 CORS 우회 불필요) 중
   * 하나를 받는다. 스키마 검증은 얇은 어댑터 원칙에 따라 호출부(adService.ts)가 한다.
   */
  async analyzeProductInfo(
    source: { text?: string; url?: string },
    apiKey: string
  ): Promise<unknown> {
    const material = source.url
      ? `다음 URL의 제품/기업 페이지를 직접 읽고 분석하세요: ${source.url}`
      : `자료:\n${(source.text || '').slice(0, 8000)}`

    const prompt = `당신은 광고 영상 기획 전문가입니다. 아래 제품/기업 자료를 분석해 광고 컨셉을 만들어주세요.

${material}

반드시 아래 JSON 형식으로만 답하세요 (한국어, 다른 설명 금지):
{"productName":"제품명","description":"한 문장 설명","keyFeatures":["기능1","기능2","기능3"],"targetAudience":"타겟 고객층","mainBenefit":"핵심 이점 한 문장","narration":"광고 나레이션 스크립트 (핵심만 간결하게, 자연스러운 구어체 — 실제 길이는 영상 길이에 맞춰 이후 단계에서 조정됨)","callToAction":"행동 유도 문구","tone":"energetic|calm|professional 중 하나"}

페이지를 읽을 수 없거나 제품/기업 정보를 찾을 수 없으면, 다른 설명 없이 정확히 {"error":"이유 한 문장"} 형식으로만 답하세요.`

    // urlContext 도구와 responseMimeType JSON 강제는 함께 쓸 수 없어, URL일 땐 텍스트로 받아 파싱한다
    const generationConfig: Record<string, unknown> = { temperature: 0.7 }
    const payload: Record<string, unknown> = {
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig,
    }
    if (source.url) {
      payload.tools = [{ urlContext: {} }]
    } else {
      generationConfig.responseMimeType = 'application/json'
    }

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiTextEndpoint(apiKey),
      body: payload,
    })
    useKeysStore.getState().updateGeminiUsage('text')

    const content = geminiText(data)
    if (!content) throw new Error(data.error?.message || 'Gemini 제품 분석에 실패했어요')
    const jsonMatch = String(content).match(/\{[\s\S]*\}/)
    if (!jsonMatch) {
      // urlContext 도구가 페이지를 못 가져온 경우 응답 메타데이터에 실패 상태가 남는다
      const urlMeta = data.candidates?.[0]?.urlContextMetadata?.urlMetadata
      const retrievalFailed = Array.isArray(urlMeta)
        && urlMeta.some((m: { urlRetrievalStatus?: string }) =>
          m.urlRetrievalStatus && m.urlRetrievalStatus !== 'URL_RETRIEVAL_STATUS_SUCCESS')
      throw new Error(retrievalFailed
        ? '해당 주소의 페이지를 읽지 못했어요. 주소를 확인하거나, 텍스트 탭에 제품 설명을 붙여넣어 주세요.'
        : '분석 결과 형식을 이해하지 못했어요. 텍스트 탭에 제품 설명을 붙여넣으면 더 정확하게 분석할 수 있어요.')
    }
    const parsed = JSON.parse(jsonMatch[0]) as Record<string, unknown>
    if (parsed && typeof parsed.error === 'string' && !parsed.productName) {
      // 페이지가 스크립트로만 그려지는 SPA면 HTML에 읽을 내용이 없어 여기로 온다
      throw new Error(`페이지에서 제품 정보를 찾지 못했어요 (${parsed.error}) 텍스트 탭에 제품 소개를 붙여넣어 주세요.`)
    }
    return parsed
  },

  /**
   * (AdStudio) 광고 스토리보드 씬 창작 — 제품 분석 결과 + 4축 컨셉(카테고리·강조·구성·톤)을
   * 반영해, 선택한 스토리 구성의 기승전결을 유지한 채 실제 제품 광고 씬들을 창작한다.
   * generateStoryboardScenes(기념영상용)의 광고 버전 — 검증은 호출부(storyboardGenerator)가 한다.
   */
  async generateAdStoryboardScenes(
    referenceScenes: GeneratedStoryboardScene[],
    context: {
      productName: string
      description: string
      keyFeatures: string[]
      narration: string
      callToAction: string
      emphasisKo: string[]
      toneKo: string
      visualStyleKo?: string   // 사용자가 고른 비주얼 스타일(룩) — 조명·질감의 방향을 정한다
      visualStyleEn?: string
      structureLabel: string
      structureFlow: string
      sceneCount: number
      durationSec: number     // 영상 총 길이 — 나레이션 분량을 이 안에 끝나도록 제약하는 기준
      hasModel: boolean       // 배우(인물) 사진이 있는 프로젝트인지
      virtualActorKo?: string // hasModel=false일 때 AI 가상 배우 프로필 (한국어, 예: "여성, 30대, 밝고 친근한 이미지")
      virtualActorEn?: string // 같은 프로필의 영어 프롬프트 조각 (키프레임 묘사용)
      dialogueMode: DialogueMode
    },
    apiKey: string
  ): Promise<GeneratedStoryboardScene[]> {
    // 영상 길이에 맞는 나레이션 글자 예산 — 한국어 나레이션은 초당 약 4.5자가 편안한 속도다.
    // 안내·CTA에 쓰는 여유를 위해 0.85를 곱하고, 이 총량을 씬 수로 나눠 씬당 한도를 준다.
    const totalCharBudget = Math.round(context.durationSec * 4.5 * 0.85)
    const perSceneCharBudget = Math.max(8, Math.floor(totalCharBudget / context.sceneCount))

    const dialogueInstruction = context.dialogueMode === 'none'
      ? '이 광고는 대사(나레이션 자막)가 없습니다. dialogueKo는 빈 문자열("")로 두세요.'
      : `[대사 분량 — 매우 중요]
이 광고는 총 ${context.durationSec}초입니다. 나레이션이 이 시간을 넘으면 영상 안에 다 담기지 못하고 잘립니다.
· 모든 씬의 dialogueKo 글자 수 합계가 한국어 기준 약 ${totalCharBudget}자를 넘지 않게 하세요(공백 포함, 이것은 상한이며 넘기면 안 됩니다).
· 각 씬 dialogueKo는 약 ${perSceneCharBudget}자 이내의 짧고 힘 있는 한 문장으로 쓰세요. 길면 반드시 줄이세요.
· 참고로 넘겨드린 나레이션 초안이 이 예산보다 길면 그대로 나누지 말고, 핵심만 남겨 압축해 다시 쓰세요. 원문을 채워 넣는 것보다 시간 안에 끝나는 것이 우선입니다.
· ⚠️ dialogueKo는 반드시 **한국어**로 쓰세요. 제품 자료가 영어로 돼 있어도 대사는 한국어로 새로 쓰는 것이며, 영어 문장을 그대로 옮기지 마세요(제품명·브랜드명만 원문 표기를 허용).
· 마지막 씬은 반드시 행동 유도 문구("${context.callToAction}")로 짧게 끝내세요.
나레이션 초안(압축의 재료로만 사용): "${context.narration}"`

    const modelInstruction = context.hasModel
      ? '모델(배우)이 등장하는 씬은 참고 예시의 인물 등장 여부를 그대로 따르세요.'
      : `이 광고에는 실제 모델 사진이 없습니다. 인물이 등장하는 씬의 모델은 반드시 다음 설정을 따르세요: ${context.virtualActorKo || '가상의 일반적인 모델'}. 특정 실존 인물을 닮지 않게 하고, 인물이 나오는 씬의 keyframePromptEn에는 이 모델의 영어 묘사("${context.virtualActorEn || 'a generic model, not resembling any real person'}")를 포함하세요. 모든 씬에서 같은 모델이 일관되게 등장해야 합니다.`

    const prompt = `당신은 세로형(9:16) 짧은 광고 영상을 쓰는 한국어 광고 각본가입니다.

광고할 제품/서비스:
- 이름: ${context.productName}
- 설명: ${context.description}
- 핵심 특징: ${context.keyFeatures.join(', ')}
- 강조할 소구점: ${context.emphasisKo.join(', ') || '자유'}
- 톤&무드: ${context.toneKo}

스토리 구성: "${context.structureLabel}" — 흐름: ${context.structureFlow}

아래는 같은 구성의 ${context.sceneCount}개 씬짜리 참고 예시입니다 (구성과 각 씬의 역할만 참고하고, 내용은 위 제품에 맞게 완전히 새로 창작하세요):
${referenceScenes.map((s, i) => `씬 ${i + 1}: 설명="${s.descKo}" / 대사="${s.dialogueKo}" / 비주얼프롬프트="${s.keyframePromptEn}" / 카메라모션="${s.motionPromptEn}"`).join('\n')}

${dialogueInstruction}
${modelInstruction}
keyframePromptEn에는 반드시 이 제품("${context.productName}")이 시각적으로 어떻게 보이는지 구체적으로 묘사해 넣으세요. 실존 유명인, 경쟁 브랜드명, 과장 광고성 허위 문구는 절대 포함하지 마세요.

[비주얼 방향]
이 광고의 룩은 "${context.visualStyleKo || '클린 브라이트'}"입니다. 영어 키워드: ${context.visualStyleEn || 'bright clean commercial look'}
모든 씬의 조명·질감은 이 룩에 맞춰 일관되게 묘사하세요. 이 룩이 어두운 연출을 요구한다면 어둡게 가도 됩니다.

[단 하나의 불변 원칙]
제품·로고·핵심 피사체가 화면에 있을 때는 어떤 룩이든 **또렷하게 읽혀야** 합니다.
이건 "밝게 하라"는 뜻이 아니라 "묻히지 않게 하라"는 뜻입니다 — 어두운 화면에서도 키라이트·림라이트·네온·플래시 등으로 피사체를 도드라지게 만들면 됩니다.

[참고 — 절대 규칙이 아니라 판단 기준]
· 세로 피드에서 첫 씬은 사실상 썸네일이라 시선을 끄는 힘이 중요합니다. 밝게 열든, 강렬한 대비로 열든, "지나치기 아까운 한 컷"이면 됩니다.
· "문제 상황 → 해결" 같은 대비 구간은 밝기를 떨어뜨리는 것 외에 채도·온기·질감(pale, flat, cool, grainy)을 낮추는 방법도 효과적입니다. 어느 쪽이든 제품 컷에서는 확실히 반전시키세요.
· 위 판단들은 이 제품·브랜드·룩에 무엇이 가장 잘 맞는지에 따라 자유롭게 선택하세요. 관성적으로 같은 연출을 반복하지 말고 매번 새롭게 창작하세요.

반드시 아래 JSON 형식으로만, 정확히 ${context.sceneCount}개의 항목을 담아 응답하세요. 다른 설명은 절대 포함하지 마세요:
{"scenes":[{"descKo":"한국어 장면 설명","dialogueKo":"한국어 나레이션(없으면 빈 문자열)","keyframePromptEn":"영어 비주얼 프롬프트(쉼표로 구분된 시각 요소, 완성된 문장 아님, 카메라 움직임 언급 금지)","motionPromptEn":"영어 카메라 움직임 지시(예: slow dolly-in, gentle pan left)"}, ...]}`

    const payload = {
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: {
        temperature: 0.9,
        responseMimeType: 'application/json',
      },
    }

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiTextEndpoint(apiKey),
      body: payload,
    })
    useKeysStore.getState().updateGeminiUsage('text')

    const content = geminiText(data)
    if (!content) throw new Error(data.error?.message || 'Gemini 광고 스토리보드 생성에 실패했어요')
    const parsed = JSON.parse(content)
    return parsed.scenes
  },

  /**
   * (AdStudio) 상품 페이지 스크린샷을 Gemini Vision으로 읽어 광고 컨셉 JSON을 만든다.
   * 네이버·쿠팡처럼 봇 접근을 차단하는 페이지도 사용자가 화면을 캡처해 올리면 분석할 수 있다.
   */
  async analyzeProductImage(imageDataUrl: string, apiKey: string): Promise<unknown> {
    const { data: base64, mimeType } = await toBase64(imageDataUrl)

    const prompt = `당신은 광고 영상 기획 전문가입니다. 이 이미지는 제품/기업 소개 페이지의 스크린샷입니다. 이미지 속 텍스트·상품 정보를 읽고 광고 컨셉을 만들어주세요.

반드시 아래 JSON 형식으로만 답하세요 (한국어, 다른 설명 금지):
{"productName":"제품명","description":"한 문장 설명","keyFeatures":["기능1","기능2","기능3"],"targetAudience":"타겟 고객층","mainBenefit":"핵심 이점 한 문장","narration":"광고 나레이션 스크립트 (핵심만 간결하게, 자연스러운 구어체 — 실제 길이는 영상 길이에 맞춰 이후 단계에서 조정됨)","callToAction":"행동 유도 문구","tone":"energetic|calm|professional 중 하나"}

이미지에서 제품/기업 정보를 읽을 수 없으면 {"error":"이유 한 문장"} 형식으로만 답하세요.`

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiTextEndpoint(apiKey),
      body: {
        contents: [{ parts: [{ text: prompt }, { inlineData: { mimeType, data: base64 } }] }],
        generationConfig: { temperature: 0.7, responseMimeType: 'application/json' },
      },
    })
    useKeysStore.getState().updateGeminiUsage('text')

    const content = geminiText(data)
    if (!content) throw new Error(data.error?.message || 'Gemini 이미지 분석에 실패했어요')
    const jsonMatch = String(content).match(/\{[\s\S]*\}/)
    if (!jsonMatch) throw new Error('분석 결과 형식을 이해하지 못했어요. 다른 스크린샷으로 다시 시도해주세요.')
    const parsed = JSON.parse(jsonMatch[0]) as Record<string, unknown>
    if (parsed && typeof parsed.error === 'string' && !parsed.productName) {
      throw new Error(`이미지에서 제품 정보를 찾지 못했어요 (${parsed.error}) 상품 설명이 보이는 스크린샷을 올려주세요.`)
    }
    return parsed
  },

  /**
   * (AdStudio) 제품 설명서 문서(PDF)를 Gemini에 통째로 넘겨 광고 컨셉 JSON을 만든다.
   * Gemini는 PDF를 네이티브로 읽는다(표·이미지 포함) — 별도 텍스트 추출 라이브러리가 필요 없다.
   * 워드(.docx)는 호출부(A2_Source)에서 mammoth로 텍스트를 추출해 analyzeProductInfo로 보낸다.
   */
  async analyzeProductDocument(base64: string, mimeType: string, apiKey: string): Promise<unknown> {
    const prompt = `당신은 광고 영상 기획 전문가입니다. 첨부된 문서는 제품/기업 소개 자료 또는 제품 설명서입니다. 문서 내용을 읽고 광고 컨셉을 만들어주세요.

반드시 아래 JSON 형식으로만 답하세요 (한국어, 다른 설명 금지):
{"productName":"제품명","description":"한 문장 설명","keyFeatures":["기능1","기능2","기능3"],"targetAudience":"타겟 고객층","mainBenefit":"핵심 이점 한 문장","narration":"광고 나레이션 스크립트 (핵심만 간결하게, 자연스러운 구어체 — 실제 길이는 영상 길이에 맞춰 이후 단계에서 조정됨)","callToAction":"행동 유도 문구","tone":"energetic|calm|professional 중 하나"}

문서에서 제품/기업 정보를 읽을 수 없으면 {"error":"이유 한 문장"} 형식으로만 답하세요.`

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiTextEndpoint(apiKey),
      body: {
        contents: [{ parts: [{ text: prompt }, { inlineData: { mimeType, data: base64 } }] }],
        generationConfig: { temperature: 0.7, responseMimeType: 'application/json' },
      },
    })
    useKeysStore.getState().updateGeminiUsage('text')

    const content = geminiText(data)
    if (!content) {
      logGeminiEmpty('analyzeProductDocument', data)
      // 안전 필터·토큰 한도 등 원인별로 사용자가 취할 수 있는 행동이 달라 구분해 안내한다
      const reason = data?.candidates?.[0]?.finishReason
      if (reason === 'MAX_TOKENS') {
        throw new Error('문서가 너무 길어 분석이 중간에 끊겼어요. 제품 소개 부분만 추린 PDF로 다시 시도해주세요.')
      }
      if (reason === 'SAFETY' || reason === 'PROHIBITED_CONTENT') {
        throw new Error('문서 내용이 AI 안전 정책에 걸려 분석되지 않았어요. 다른 문서로 시도해주세요.')
      }
      throw new Error(data.error?.message || 'Gemini 문서 분석에 실패했어요')
    }
    const jsonMatch = String(content).match(/\{[\s\S]*\}/)
    if (!jsonMatch) {
      console.error('analyzeProductDocument: JSON을 찾지 못한 원본 응답:', content.slice(0, 500))
      throw new Error('분석 결과 형식을 이해하지 못했어요. 다른 문서로 다시 시도해주세요.')
    }
    const parsed = JSON.parse(jsonMatch[0]) as Record<string, unknown>
    if (parsed && typeof parsed.error === 'string' && !parsed.productName) {
      throw new Error(`문서에서 제품 정보를 찾지 못했어요 (${parsed.error}) 제품 소개가 담긴 문서를 올려주세요.`)
    }
    return parsed
  },

  /**
   * 생성된 키프레임 이미지를 Gemini Vision에게 직접 보여주고 해부학적으로 이상한 부분(여분의
   * 팔다리, 공중에 뜬 신체 일부, 인물이 뭉개져 겹침 등)이 있는지 판단시킨다. 자세 검출 휴리스틱
   * (poseDetector.ts)보다 정확하지만 API 호출 비용이 있어 프로 전용 수동 검수 버튼에서만 쓴다.
   */
  async checkImageAnatomy(imageUrl: string, apiKey: string): Promise<{ ok: boolean; issue?: string }> {
    const { data: base64, mimeType } = await toBase64(imageUrl)

    const payload = {
      contents: [{
        parts: [
          {
            text: "Look at this AI-generated image carefully. Does it show any anatomically impossible or "
              + 'physically incoherent human body content — such as extra limbs, a floating or disconnected '
              + "body part, merged or duplicated figures, or an impossible pose? Reply with exactly 'OK' if "
              + 'the body/bodies look anatomically normal. Otherwise reply with a short phrase (under 15 words) '
              + 'in Korean describing the specific issue.',
          },
          { inlineData: { mimeType, data: base64 } },
        ],
      }],
    }

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiTextEndpoint(apiKey),
      body: payload,
    })
    useKeysStore.getState().updateGeminiUsage('text')

    const text = geminiText(data)?.trim()
    if (!text) throw new Error(data.error?.message || 'Gemini 이미지 검수에 실패했어요')

    const ok = text.toUpperCase().startsWith('OK')
    return { ok, issue: ok ? undefined : text }
  },

  /**
   * 생성된 키프레임이 참조 인물 사진과 실제로 같은 사람처럼 보이는지 Gemini Vision에게 직접
   * 판정시킨다. "에러 없이 생성됨"과 "그 인물처럼 보임"은 다르다는 걸 강등 체인에 반영하기 위함 —
   * 여기서 불일치로 나오면 호출부(generateKeyframe)가 이 결과를 채택하지 않고 다음 제공자로 넘어간다.
   * generationPrompt(생성에 실제로 쓰인 프롬프트, 스타일 지시 포함)를 같이 넘기면, 클레이메이션·
   * 픽셀아트·셀셰이딩·수묵화 등 비포토리얼 스타일을 요청한 씬에서 렌더링 매체 차이 자체를 "다른
   * 인물"로 오판하지 않도록 판정 기준을 조정한다 — 그런 오판은 정상 이미지를 버리고 다른 AI
   * 제공자로 씬을 재생성시켜 스토리보드 전체의 그림체 연속성을 깨는 더 큰 비용을 유발하기 때문이다.
   */
  async verifyActorLikeness(generatedImageUrl: string, referenceImageUrls: string[], apiKey: string, generationPrompt?: string): Promise<boolean> {
    const { data: genData, mimeType: genMime } = await toBase64(generatedImageUrl)
    const refParts = await Promise.all(
      referenceImageUrls.slice(0, 3).map(async url => {
        const { data, mimeType } = await toBase64(url)
        return { inlineData: { mimeType, data } }
      })
    )

    const styleNote = generationPrompt
      ? ` The first image was generated using this art-direction instruction: "${generationPrompt}". If that instruction `
        + 'calls for a non-photorealistic rendering style (claymation/stop-motion clay, 8-bit pixel art, cel-shaded/anime '
        + 'animation, traditional ink wash painting, watercolor, 3D cartoon, etc.), the first image is EXPECTED to look '
        + 'nothing like an ordinary photograph — differences in medium, surface texture, color palette, line work, or '
        + 'realism level are NOT identity mismatches. Judge identity only by structural cues that survive a style '
        + 'transfer: face shape/proportions, hairstyle silhouette and color, apparent age range, gender presentation. '
        + 'When a difference is plausibly explained by the requested art style rather than a genuinely different '
        + 'person, treat it as MATCH.'
      : ''

    const payload = {
      contents: [{
        parts: [
          {
            text: 'Compare the person in the FIRST image to the reference photo(s) that follow. Is the '
              + 'first image showing the SAME identifiable individual as in the reference(s) — same face '
              + 'shape and features, allowing for different pose, expression, lighting, clothing, and artistic '
              + `rendering style?${styleNote} Reply MISMATCH only if structural identity cues themselves clearly `
              + 'point to a different person (different age band, different gender presentation, unrelated hairstyle '
              + 'or face shape, or — in a multi-person scene — an actor swapped with the wrong reference). '
              + "Reply with exactly one word: 'MATCH' or 'MISMATCH'.",
          },
          { inlineData: { mimeType: genMime, data: genData } },
          ...refParts,
        ],
      }],
    }

    const data = await callProxy({
      provider: 'gemini',
      apiKey,
      method: 'POST',
      endpoint: await geminiTextEndpoint(apiKey),
      body: payload,
    })
    useKeysStore.getState().updateGeminiUsage('text')

    const text = geminiText(data)?.trim().toUpperCase()
    if (!text) throw new Error(data.error?.message || 'Gemini 닮음새 검증에 실패했어요')
    return text.startsWith('MATCH')
  }
}

export interface KeyframeGenerationResult {
  url: string
  // referenceImageUrls가 주어졌는데도(=인물 참조가 필요한 씬인데도) 참조 이미지 기반 생성이 끝내
  // 성공하지 못해 텍스트 전용 생성이나 Pollinations로 대체된 경우 true — 호출부가 "이 씬은 인물
  // 외형이 다르게 나올 수 있어요" 같은 안내를 띄우는 데 쓴다.
  degraded: boolean
  // 실제 사용된(또는 사용 시도된) seed — 자세 이상 감지로 재시도할 때 이 값을 변형해 같은 결과가
  // 반복되지 않게 하는 데 쓴다.
  seed: number
}

// ── 키프레임 이미지 제너레이터 ──
export const ImageGenerator = {
  /**
   * 5단계로 우아하게 강등하며 키프레임을 생성한다:
   * 1) Gemini 키가 있으면 Gemini 이미지 생성(참조 이미지 기반 인물 동일성 유지가 가장 강력 —
   *    선정된 배우의 얼굴이 씬마다 그대로 유지되는 핵심 경로, 이 앱의 기본 이미지 생성기)
   * 2) 실패하거나 Gemini 키가 없으면 Alibaba 참조 이미지 기반 생성
   * 3) 실패하거나 참조 이미지가 없으면 Alibaba 텍스트 전용 T2I(디스크립터가 녹아든 프롬프트만으로)
   * 4) 그마저 실패하거나 키가 없으면 Pollinations 텍스트 전용 폴백(무료, 키 불필요) —
   *    이 단계는 인물 참조가 불가능해 임의의 인물이 그려질 수 있으므로 degraded로 표시한다
   * 5) 참조 이미지가 필요한 씬에서는 1)·2) 단계 결과를 Gemini Vision으로 닮음새 검증한다 — "에러
   *    없이 생성됨"과 "그 배우처럼 보임"은 다르므로, 불일치 시 그 결과를 채택하지 않는다. 검증에는
   *    실제 생성 프롬프트(스타일 지시 포함)도 같이 넘겨, 클레이메이션·픽셀아트·셀셰이딩·수묵화 등
   *    비포토리얼 스타일 씬에서 렌더링 매체 차이를 "다른 인물"로 오판하지 않게 한다. Gemini는
   *    seed를 지원하지 않아 매번 결과가 조금씩 달라지므로, 불일치가 나와도 곧장 다른 제공자로
   *    넘어가지 않고 같은 제공자 안에서 최대 3회까지 재시도한다(제공자가 바뀌면 스토리보드 안에서
   *    씬마다 그림체가 달라지므로 그 전환 자체를 최대한 늦춘다). 그래도 실패하면 Alibaba로 넘어가
   *    같은 검증을 재적용하고, 모든 참조 기반 시도가 불일치로 끝나면 완전히 무관한 인물이 나오는
   *    텍스트 전용/Pollinations 결과보다는 최초의 참조 기반 결과(degraded 표시)를 최후 수단으로 쓴다.
   */
  async generateKeyframe(prompt: string, referenceImageUrls: string[] = [], seed?: number): Promise<KeyframeGenerationResult> {
    const neededReference = referenceImageUrls.length > 0
    // 호출부가 이 값을 몰라도(seed 미지정) 재시도 시 변형할 수 있는 실제 숫자를 항상 돌려주기 위해 확정해둔다
    const effectiveSeed = seed ?? Math.floor(Math.random() * 1000000)

    const geminiKey = await KeyVault.getKey('gemini')
    // 닮음새 검증에 실패(불일치)한 참조기반 결과 중 가장 먼저 나온 후보 — 완전 무관한 텍스트
    // 전용/Pollinations 결과보다는 이쪽이 그나마 낫다
    let bestEffortUrl: string | null = null

    const verify = async (url: string): Promise<boolean> => {
      if (!neededReference || !geminiKey) return true
      try {
        return await GeminiAdapter.verifyActorLikeness(url, referenceImageUrls, geminiKey, prompt)
      } catch (e) {
        console.warn('닮음새 검증 실패 — 검증 없이 통과 처리합니다:', e)
        return true
      }
    }

    // Gemini는 seed를 지원하지 않아 매 호출마다 결과가 조금씩 달라진다 — 한 번 불일치가 나와도
    // 같은 제공자로 몇 번 더 시도해볼 가치가 있다는 뜻이다. 곧바로 다른 제공자(Alibaba)로 넘어가면
    // 렌더링 엔진 자체가 바뀌어 스토리보드 안에서 씬마다 그림체가 달라지므로, 그 전환 자체를
    // 최대한 늦춘다(최초 시도 포함 최대 3회까지 Gemini 안에서 재시도).
    const GEMINI_LIKENESS_RETRIES = 2
    if (geminiKey) {
      for (let attempt = 0; attempt <= GEMINI_LIKENESS_RETRIES; attempt++) {
        try {
          const url = await GeminiAdapter.generateImage(prompt, geminiKey, referenceImageUrls)
          if (await verify(url)) return { url, degraded: false, seed: effectiveSeed }
          bestEffortUrl = bestEffortUrl ?? url
          if (attempt < GEMINI_LIKENESS_RETRIES) {
            console.warn(`Gemini 결과가 참조 인물과 다르게 보여 같은 제공자로 재시도합니다 (${attempt + 1}/${GEMINI_LIKENESS_RETRIES + 1})`)
          } else {
            console.warn('Gemini 재시도로도 참조 인물과 다르게 보여 다른 제공자로 대체 시도합니다')
          }
        } catch (e) {
          console.warn('Gemini 이미지 생성 실패, Alibaba/Pollinations 경로로 폴백합니다:', e)
          break
        }
      }
    }

    const alibabaKey = await KeyVault.getKey('alibaba')
    if (alibabaKey) {
      if (neededReference) {
        try {
          const url = await AlibabaAdapter.generateImage(prompt, alibabaKey, referenceImageUrls, effectiveSeed)
          if (await verify(url)) return { url, degraded: false, seed: effectiveSeed }
          bestEffortUrl = bestEffortUrl ?? url
          console.warn('Alibaba 참조 이미지 결과도 검증 실패, 남은 후보로 대체합니다')
        } catch (e) {
          // 쿼터 소진은 "일시적 생성 실패"가 아니라 사용자가 반드시 알아야 할 상태 변화이므로,
          // Pollinations로 조용히 대체하지 않고 그대로 위로 던져 호출부의 오류 배너에 노출한다.
          if (e instanceof QuotaExhaustedError) throw e
          console.warn('참조 이미지 기반 생성 실패, 텍스트 전용 생성으로 폴백합니다:', e)
        }
      }
      if (bestEffortUrl) return { url: bestEffortUrl, degraded: true, seed: effectiveSeed }
      try {
        // 참조 이미지 없이 텍스트만으로 생성하더라도, seed는 그대로 넘겨 같은 인물(조합)의 결과가
        // 매번 무작위가 아니라 최대한 비슷하게 나오도록 유지한다
        const url = await AlibabaAdapter.generateImage(prompt, alibabaKey, [], effectiveSeed)
        return { url, degraded: neededReference, seed: effectiveSeed }
      } catch (e) {
        if (e instanceof QuotaExhaustedError) throw e
        console.warn('Alibaba T2I generation failed, falling back to Pollinations:', e)
      }
    }

    if (bestEffortUrl) return { url: bestEffortUrl, degraded: true, seed: effectiveSeed }

    // Fallback: Pollinations AI (100% free, no key required, cinematic beautiful images)
    // 16:9 ratio
    const url = `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?width=1024&height=576&nologo=true&seed=${effectiveSeed}`
    return { url, degraded: neededReference, seed: effectiveSeed }
  }
}

