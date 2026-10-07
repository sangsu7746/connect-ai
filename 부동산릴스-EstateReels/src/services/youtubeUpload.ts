// ════════════════════════════════════════════════════════════════
// YouTube 자동 업로드 — 브라우저에서 직접(Google Identity 토큰 + resumable upload).
//   서버·시크릿 불필요. OAuth 웹 클라이언트 ID(공개값)만 있으면 된다.
//   준비: GCP headjim-ai → YouTube Data API v3 사용설정 → OAuth 웹 클라이언트 생성
//        (승인된 JS 원본에 https://estate-reels.web.app 추가) → 동의화면 스코프 youtube.upload.
//   빌드 시 VITE_YT_CLIENT_ID 로 클라이언트 ID 주입.
// ════════════════════════════════════════════════════════════════
const CLIENT_ID = (import.meta.env.VITE_YT_CLIENT_ID as string) || ''
const SCOPE = 'https://www.googleapis.com/auth/youtube.upload'
const GIS_SRC = 'https://accounts.google.com/gsi/client'

export function ytConfigured(): boolean {
  return CLIENT_ID.replace(/\s/g, '').length > 20
}

// Google Identity Services 스크립트 1회 로드
let gisReady: Promise<void> | null = null
function loadGis(): Promise<void> {
  if (gisReady) return gisReady
  gisReady = new Promise((resolve, reject) => {
    if ((window as unknown as { google?: { accounts?: { oauth2?: unknown } } }).google?.accounts?.oauth2) return resolve()
    const s = document.createElement('script')
    s.src = GIS_SRC; s.async = true; s.defer = true
    s.onload = () => resolve()
    s.onerror = () => { gisReady = null; reject(new Error('구글 로그인 스크립트를 불러오지 못했어요.')) }
    document.head.appendChild(s)
  })
  return gisReady
}

// 액세스 토큰 발급(팝업/동의). youtube.upload 스코프.
let tokenClient: { callback: (r: TokenResp) => void; requestAccessToken: (o?: { prompt?: string }) => void } | null = null
interface TokenResp { access_token?: string; error?: string; error_description?: string }
function getToken(): Promise<string> {
  return new Promise((resolve, reject) => {
    const g = (window as unknown as { google?: { accounts?: { oauth2?: { initTokenClient: (o: Record<string, unknown>) => typeof tokenClient } } } }).google
    if (!g?.accounts?.oauth2) return reject(new Error('구글 인증을 초기화하지 못했어요.'))
    if (!tokenClient) tokenClient = g.accounts.oauth2.initTokenClient({ client_id: CLIENT_ID, scope: SCOPE, callback: () => {} })
    tokenClient!.callback = (resp: TokenResp) => {
      if (resp?.access_token) resolve(resp.access_token)
      else reject(new Error(resp?.error_description || resp?.error || '유튜브 인증에 실패했어요.'))
    }
    try { tokenClient!.requestAccessToken({ prompt: '' }) } catch (e) { reject(e instanceof Error ? e : new Error('인증 요청 실패')) }
  })
}

export interface YtMeta {
  title: string
  description: string
  tags: string[]
  privacy: 'public' | 'unlisted' | 'private'
}

/** result 영상(blob)을 유튜브에 업로드. onProgress(0~100). 반환 {videoId, url}. */
export async function uploadToYouTube(blob: Blob, meta: YtMeta, onProgress?: (pct: number) => void): Promise<{ videoId: string; url: string }> {
  if (!ytConfigured()) throw new Error('유튜브 업로드 설정(클라이언트 ID)이 필요해요.')
  await loadGis()
  const token = await getToken()
  const body = {
    snippet: { title: (meta.title || '부동산 홍보 영상').slice(0, 100), description: (meta.description || '').slice(0, 4900), tags: meta.tags.slice(0, 15), categoryId: '22' },
    status: { privacyStatus: meta.privacy, selfDeclaredMadeForKids: false },
  }
  const init = await fetch('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json; charset=UTF-8',
      'X-Upload-Content-Type': 'video/mp4',
      'X-Upload-Content-Length': String(blob.size),
    },
    body: JSON.stringify(body),
  })
  if (!init.ok) throw new Error(uploadErr(init.status, await init.text()))
  const uploadUrl = init.headers.get('Location')
  if (!uploadUrl) throw new Error('업로드 주소를 받지 못했어요.')
  const videoId = await putBlob(uploadUrl, blob, token, onProgress)
  return { videoId, url: `https://youtu.be/${videoId}` }
}

// 진행률을 위해 XHR로 PUT(fetch는 업로드 진행률 미제공)
function putBlob(url: string, blob: Blob, token: string, onProgress?: (p: number) => void): Promise<string> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('PUT', url, true)
    xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.setRequestHeader('Content-Type', 'video/mp4')
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100)) }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve((JSON.parse(xhr.responseText) as { id: string }).id) }
        catch { reject(new Error('업로드 응답을 해석하지 못했어요.')) }
      } else reject(new Error(uploadErr(xhr.status, xhr.responseText)))
    }
    xhr.onerror = () => reject(new Error('업로드 중 네트워크 오류가 났어요.'))
    xhr.send(blob)
  })
}

function uploadErr(status: number, body: string): string {
  if (status === 401) return '유튜브 인증이 만료됐어요. 다시 시도해주세요.'
  if (status === 403) {
    if (/quotaExceeded|uploadLimitExceeded/i.test(body)) return '오늘 업로드 한도를 초과했어요. (쿼터 증량 필요)'
    if (/youtubeSignupRequired/i.test(body)) return '이 구글 계정에 유튜브 채널이 없어요. 채널을 먼저 만들어 주세요.'
    return '유튜브 권한이 거부됐어요. (앱 승인·테스트 사용자 등록 확인)'
  }
  return `업로드에 실패했어요 (${status}).`
}
