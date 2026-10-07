import type { HomageCandidate } from '../types/homage'
import { auth } from './firebase'
import { fnUrl } from './firebaseTarget'

/** 유튜브 videoId 는 11자 [A-Za-z0-9_-] 로 고정돼 있다 */
const VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/

/**
 * 검색어를 조립한다 — `{제품군} {소분류} 광고`.
 *
 * ⚠️ 브랜드명은 절대 넣지 않는다. 넣으면 그 브랜드의 기존 광고만 나오거나
 *    (신규 브랜드면) 결과가 0건이 된다. 어느 쪽도 "같은 결의 광고 참고"에 맞지 않다.
 *    브랜드 제거는 호출부(extractProductType)가 책임진다.
 */
export function buildSearchQuery(productTypeKo: string, categorySubLabel: string): string {
  const a = productTypeKo.trim()
  const b = categorySubLabel.trim()
  const words = a && b && a !== b ? [a, b] : [a || b].filter(Boolean)
  if (words.length === 0) return ''
  return `${words.join(' ')} 광고`
}

/** "숫자 + 용량/수량 단위" 형태의 낱말 — 제품군이 아니라 포장 단위다 */
const CAPACITY_QUANTITY_TOKEN_RE = /^\d+(\.\d+)?(ml|g|kg|l|개입|매|정|포)$/i

/**
 * 상품명에서 제품군을 어림잡는다(마지막 낱말 휴리스틱) — buildSearchQuery의 productTypeKo 입력으로 쓰인다.
 *
 * ⚠️ 스펙 §6-1 은 Gemini 로 일반명사를 추출하라고 했으나, 여기서는 휴리스틱을 쓴다. 이유: 조립
 *    결과가 편집 가능한 입력창에 그대로 노출되므로, 빗나가도 사용자가 한 번에 고칠 수 있다.
 *    첫 화면을 띄우는 데 LLM 왕복을 넣으면 체감 지연만 생긴다. 한국어 상품명은
 *    "브랜드 + 제품군 + 용량/수량"(예: "미리집 수분크림 50ml", "ABC 세럼 30ml 2개입") 순서가
 *    지배적이라 마지막 낱말이 대체로 맞는다 — 단, 그 마지막 낱말이 "50ml"·"2개입" 같은 포장
 *    단위면 안 맞는다. search.list 는 1회 100유닛에 전체 사용자 합계 하루 약 100회뿐이라, 기본값이
 *    나쁘면 사용자가 검색어를 고쳐 두 번 검색하게 돼 공용 한도가 반토막 난다. 그래서 끝에서부터
 *    용량·수량 토큰을 만나는 동안(여러 개일 수 있다 — "30ml 2개입"처럼) 계속 건너뛰고, 그렇지 않은
 *    낱말을 만나면 그걸 쓴다. 실사용에서 빗나가는 비율이 높으면 그때 Gemini 추출로 승격한다.
 */
export function extractProductType(productName: string): string {
  const words = (productName || '').trim().split(/\s+/).filter(Boolean)
  let i = words.length - 1
  // i > 0 (마지막 남은 한 낱말은 더 나은 대안이 없으니 용량 토큰이어도 그대로 쓴다)
  while (i > 0 && CAPACITY_QUANTITY_TOKEN_RE.test(words[i])) {
    i--
  }
  return words[i] ?? ''
}

/**
 * 다양한 유튜브 URL 형태에서 videoId 를 뽑는다.
 * watch?v= / youtu.be / shorts / embed / m.youtube 를 모두 받는다.
 * 순수 11자 id 를 그대로 넣는 것도 허용한다.
 */
export function parseYoutubeVideoId(input: string): string | null {
  const s = (input || '').trim()
  if (!s) return null

  if (VIDEO_ID_RE.test(s)) return s

  let url: URL
  try {
    url = new URL(s)
  } catch {
    return null
  }

  const host = url.hostname.replace(/^www\./, '').replace(/^m\./, '')

  let candidate: string | null = null
  if (host === 'youtu.be') {
    candidate = url.pathname.slice(1).split('/')[0]
  } else if (host === 'youtube.com' || host === 'youtube-nocookie.com') {
    if (url.pathname === '/watch') {
      candidate = url.searchParams.get('v')
    } else {
      const m = url.pathname.match(/^\/(?:shorts|embed|v)\/([^/?]+)/)
      candidate = m ? m[1] : null
    }
  }

  return candidate && VIDEO_ID_RE.test(candidate) ? candidate : null
}

/** 검색 쿼터 소진 — 호출부가 URL·글 입구로 유도하기 위해 따로 구분한다 */
export class YoutubeQuotaError extends Error {
  constructor(message = '오늘 자동검색 한도를 다 썼어요.') {
    super(message)
    this.name = 'YoutubeQuotaError'
  }
}

/**
 * 네트워크 자체가 끊겼을 때(서버 미가동·DNS 실패·CORS 차단 등) 보여줄 안내.
 * ⚠️ 응답을 받은 뒤의 실패(상태코드 404/429/기타)는 각 호출부가 이미 자기 문맥에 맞는
 *    한국어 문구로 처리한다 — 이 메시지는 오직 `fetch` 자체가 reject할 때, 즉 응답을
 *    아예 받지 못했을 때만 쓰인다. searchAdVideos·getVideoInfo 양쪽에서 같은 문구를 써야
 *    사용자가 어느 입구로 들어왔든 같은 안내(연결 확인·재시도)를 보게 된다.
 */
const NETWORK_ERROR_MESSAGE = '유튜브 서버에 연결하지 못했어요. 인터넷 연결을 확인하고 잠시 후 다시 시도해주세요.'

/**
 * 401/503 은 초기 운영에서 가장 흔히 마주치는 상태인데도 기존엔 둘 다 "검색에 실패했어요"
 * 범용 문구로 뭉개져 사용자가 뭘 해야 할지 알 수 없었다(T7 승격 리뷰). 서버(functions/index.js
 * youtubeSearch)가 실제로 이 두 코드를 보내는 경우는 각각 딱 하나뿐이다 —
 *  - 401: verifyBearer 실패, 즉 로그인 세션이 없거나 만료됨 → "로그인하라"
 *  - 503: process.env.YOUTUBE_API_KEY 미설정(배포 초기) 또는 유튜브 쪽 403(키/쿼터 문제)을
 *    재매핑한 값 → 사용자가 고칠 수 있는 게 아니라 "잠시 후 재시도/문의"가 맞는 행동이다
 * searchAdVideos·getVideoInfo 둘 다 같은 서버 함수(postYoutubeFn → youtubeSearch)를 쓰므로
 * 문구를 공유한다.
 */
const LOGIN_REQUIRED_MESSAGE = '로그인이 필요해요. 로그인한 뒤 다시 시도해주세요.'
const SERVER_NOT_CONFIGURED_MESSAGE = '서버에 유튜브 검색 기능이 아직 설정되지 않았어요. 잠시 후 다시 시도하거나 문의해주세요.'

/**
 * youtubeSearch 함수에 인증 헤더를 붙여 POST 한다.
 * `fetch` 가 던지는 예외만 여기서 잡아 한국어 안내로 바꾼다 — 응답 상태코드별 처리는
 * 손대지 않고 그대로 호출부(searchAdVideos·getVideoInfo)로 넘긴다. `YoutubeQuotaError`
 * 판정은 응답을 받은 "이후"에만 일어나므로 이 단계에서 삼켜질 일이 없다.
 */
async function postYoutubeFn(body: Record<string, unknown>): Promise<Response> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  try {
    const token = await auth.currentUser?.getIdToken()
    if (token) headers['Authorization'] = `Bearer ${token}`
  } catch { /* 토큰 발급 실패가 호출 자체를 막지는 않는다 — 서버가 401로 답한다 */ }

  try {
    return await fetch(fnUrl('youtubeSearch'), {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error(NETWORK_ERROR_MESSAGE)
  }
}

/** youtubeSearch 함수를 호출해 광고 후보를 받아온다 */
export async function searchAdVideos(q: string): Promise<HomageCandidate[]> {
  const query = (q || '').trim()
  if (!query) return []

  const res = await postYoutubeFn({ q: query })

  if (res.status === 429) throw new YoutubeQuotaError()
  if (res.status === 401) throw new Error(LOGIN_REQUIRED_MESSAGE)
  if (res.status === 503) throw new Error(SERVER_NOT_CONFIGURED_MESSAGE)
  if (!res.ok) {
    await res.text().catch(() => '')
    throw new Error('유튜브 검색에 실패했어요.')
  }

  let data
  try {
    data = await res.json()
  } catch {
    throw new Error('검색 결과를 파싱하지 못했어요.')
  }
  return (data.items || []) as HomageCandidate[]
}

export interface YoutubeVideoInfo {
  videoId: string
  title: string
  channelTitle: string
  thumbnailUrl: string
  durationSec: number
}

/**
 * 단일 영상 정보(제목·길이)를 조회한다. 직접 URL 입력 시 분석 전에 부른다.
 * videos.list 는 1유닛이라 검색(100유닛)과 달리 자주 불러도 부담이 없다.
 */
export async function getVideoInfo(videoId: string): Promise<YoutubeVideoInfo> {
  const res = await postYoutubeFn({ videoId })

  if (res.status === 404) throw new Error('영상을 찾을 수 없어요. 공개 영상인지 확인해주세요.')
  if (res.status === 429) throw new YoutubeQuotaError()
  if (res.status === 401) throw new Error(LOGIN_REQUIRED_MESSAGE)
  if (res.status === 503) throw new Error(SERVER_NOT_CONFIGURED_MESSAGE)
  if (!res.ok) {
    await res.text().catch(() => '')
    throw new Error('영상 정보를 가져오지 못했어요.')
  }

  let data
  try {
    data = await res.json()
  } catch {
    throw new Error('영상 정보를 파싱하지 못했어요.')
  }
  return data as YoutubeVideoInfo
}
