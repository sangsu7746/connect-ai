import { auth, db, doc, getDoc, onSnapshot } from './firebase'
import { getFunctions, httpsCallable } from 'firebase/functions'
import { useUserStore, LoginRequiredError } from '../stores/userStore'
import { useProjectStore } from '../stores/projectStore'
import { checkAndIncrementDaily, decrementDaily, DailyLimitError } from './dailyUsage'
import type { Scene, Lane } from '../types'

/**
 * HEADJIM 공용 포인트 지갑 클라이언트.
 *
 * 잔액·원장 조회는 Firestore에서 직접 읽고(본인 읽기만 규칙 허용),
 * 차감(spend)·환급(refund)은 반드시 지갑 서버(Cloud Functions:
 * spendCoins / refundSpentCoins — codebase 'headjimweb')를 거친다 —
 * Firestore 규칙이 클라이언트 쓰기를 전면 차단하므로 이 경로 외 조작은 불가능하다.
 * (구 Cloudflare Worker(headjim-wallet.headjim.workers.dev)는 배포된 적 없는
 *  죽은 주소였고 2026-07-16 Cloud Functions로 전환됨 — WALLET_API.md 참고)
 *
 * 과금 정책 ("무료 영구 + 포인트" 모델 — renderScene·S4·S5가 공유):
 *  - guest : 생성 불가 (사용량 집계·지갑이 계정 기준이라 로그인 필수)
 *  - free  : 무빙포토는 하루 FREE_DAILY_MOVING_PHOTO_LIMIT개까지 무료(워터마크+720p 마감),
 *            초과분과 free_ai/premium 레인은 포인트 차감(프리미엄 마감 — 워터마크 없음·원본 화질)
 *  - pro   : 무과금 특권 계정(개발자 오버라이드) — 차감 없음
 */

// 무료(영구) 티어의 무빙포토 일일 무료 한도 — 영상 1편 = 슬롯 1개 (씬 수와 무관)
export const FREE_DAILY_MOVING_PHOTO_LIMIT = 5

// S4 스토리보드 키프레임(정지 이미지) 다운로드 — 이미 생성이 끝난 부산물이라 앱 측 한계비용이
// 0에 가깝다. 그래서 완성 영상(500~P 1500)보다 훨씬 후하게: 하루 10장(스토리보드 풀 하나가
// 최대 6씬이라 하루 1편 전체를 무료로 받아갈 수 있는 양)까지 무료, 초과분만 장당 P 50
// (영상 최저가의 1/10 수준)으로 막아 "스토리보드만 반복 생성해 이미지만 무한정 채굴"하는
// 것만 방지한다.
export const FREE_DAILY_KEYFRAME_DOWNLOAD_LIMIT = 10
export const KEYFRAME_DOWNLOAD_PRICE = 50

// 포인트 충전 페이지 (headjim.com 포인트 상점) — 인앱 충전 모달의 외부 링크 폴백
export const CHARGE_URL = 'https://www.headjim.com/#points'

export interface Pricing {
  movingPhotoPerVideo: number
  freeAiPerVideo: number
  premiumPerSceneDefault: number
  premiumPerScene: Record<string, number>
  apiKeyIssuePerKey: number
}

// 서버(config/pricing) 조회 실패 시에도 제작이 멈추지 않도록 하는 로컬 기본값 —
// Worker의 DEFAULT_PRICING과 같은 값으로 유지할 것.
// 단위: 포인트 (headjim.com 판매 스케일 — P 1,500 = $1, P 1 ≈ 1원)
const FALLBACK_PRICING: Pricing = {
  movingPhotoPerVideo: 500,
  freeAiPerVideo: 1000,
  premiumPerSceneDefault: 1000,
  premiumPerScene: { veo: 1500, kling: 1200, hailuo: 800, seedance: 500, alibaba: 500, runway: 1000 },
  apiKeyIssuePerKey: 3000,
}

let pricingCache: { value: Pricing; fetchedAt: number } | null = null

export async function fetchPricing(): Promise<Pricing> {
  if (pricingCache && Date.now() - pricingCache.fetchedAt < 10 * 60_000) return pricingCache.value
  try {
    // 단가표는 Firestore config/pricing 문서(공개 읽기)에서 중앙 관리한다.
    // 문서가 없거나 읽기 실패 시 로컬 기본값으로 제작이 멈추지 않게 한다.
    const snap = await getDoc(doc(db, 'config', 'pricing'))
    if (snap.exists()) {
      const value = { ...FALLBACK_PRICING, ...(snap.data() as Partial<Pricing>) }
      pricingCache = { value, fetchedAt: Date.now() }
      return value
    }
  } catch {
    // 읽기 실패 → 기본값
  }
  return FALLBACK_PRICING
}

/** 선택한 레인 기준 이번 제작의 포인트 비용을 계산한다. */
export function computeRenderCost(scenes: Scene[], lane: Lane, pricing: Pricing): number {
  if (lane === 'moving_photo') return pricing.movingPhotoPerVideo
  if (lane === 'free_ai') return pricing.freeAiPerVideo
  // premium: 씬별 라우팅 제공자는 키 보유 상황에 따라 달라지므로 기본 단가 × 씬 수로 견적한다
  return scenes.length * pricing.premiumPerSceneDefault
}

export class InsufficientPointsError extends Error {
  constructor(public balance: number, public required: number) {
    super(`포인트가 부족해요. 필요 P ${required.toLocaleString()} · 보유 P ${balance.toLocaleString()} — headjim.com에서 충전해주세요.`)
    this.name = 'InsufficientPointsError'
  }
}

export async function getBalance(): Promise<number> {
  const user = auth.currentUser
  if (!user) throw new Error('로그인이 필요해요.')
  const snap = await getDoc(doc(db, 'wallets', user.uid))
  return (snap.data()?.balance as number) ?? 0
}

/** refId 멱등 차감 — 같은 refId로 재호출해도 이중 차감되지 않는다 (서버: spendCoins). */
export async function spendPoints(cost: number, reason: string, refId: string): Promise<number> {
  const fn = httpsCallable<
    { coins: number; service: string; reason: string; refId: string },
    { alreadySpent: boolean; spent: number; balance: number }
  >(getFunctions(), 'spendCoins')
  try {
    const res = await fn({ coins: cost, service: 'homage-video', reason, refId })
    return res.data.balance ?? 0
  } catch (e: any) {
    // 잔액 부족: failed-precondition + "INSUFFICIENT_BALANCE: balance=N, required=M"
    const msg = String(e?.message || '')
    if (e?.code === 'functions/failed-precondition' && msg.includes('INSUFFICIENT_BALANCE')) {
      const balance = Number(/balance=(\d+)/.exec(msg)?.[1] ?? 0)
      const required = Number(/required=(\d+)/.exec(msg)?.[1] ?? cost)
      throw new InsufficientPointsError(balance, required)
    }
    if (e?.code === 'functions/unauthenticated') throw new Error('로그인이 필요해요.')
    throw new Error(msg || '지갑 서버 오류')
  }
}

/** 서버가 원장에서 원래 차감액을 찾아 환급한다(금액 조작 불가). 이미 환급된 건은 멱등 처리 (서버: refundSpentCoins). */
export async function refundPoints(refId: string): Promise<void> {
  const fn = httpsCallable<{ refId: string }, { alreadyRefunded: boolean; refunded: number; balance: number }>(
    getFunctions(),
    'refundSpentCoins'
  )
  await fn({ refId })
}

/** 잔액 실시간 구독 (헤더 칩 등 UI용). 반환값은 구독 해제 함수. */
export function subscribeBalance(uid: string, cb: (balance: number) => void): () => void {
  return onSnapshot(
    doc(db, 'wallets', uid),
    snap => cb((snap.data()?.balance as number) ?? 0),
    () => cb(0)
  )
}

/** 이번 제작 건의 인가 기록 — cost 0은 "오늘의 무료 슬롯으로 통과"(워터마크 마감), 양수는 포인트 결제(프리미엄 마감) */
export type RenderAuthorization = { refId: string; cost: number }

/**
 * 제작 시작 전 "이 제작을 진행해도 되는가"를 한 번에 보장한다 — S4 제작 시작과 S5 재시도가
 * 공유하는 단일 경로.
 * - guest면 LoginRequiredError, pro(무과금 특권)면 null
 * - 이미 이번 제작 건의 인가가 있으면(재시도) 추가 차감 없이 그대로 반환
 * - 무빙포토: 오늘 무료 슬롯이 남았으면 무료(cost 0)로 통과, 소진됐으면 포인트로 계속
 * - free_ai/premium: 포인트 차감
 * 잔액 부족 시 InsufficientPointsError를 던진다 (메시지에 무료 한도 초과 사유 포함).
 */
export async function ensureRenderAuthorization(scenes: Scene[], lane: Lane): Promise<RenderAuthorization | null> {
  const { user, accessTier } = useUserStore.getState()
  const tier = accessTier()
  if (tier === 'guest') {
    throw new LoginRequiredError('영상을 만들려면 먼저 로그인해주세요. 가입하면 웰컴 포인트 1,000개를 드려요.')
  }
  if (tier === 'pro') return null

  const existing = useProjectStore.getState().pointPayment
  if (existing) return existing

  // 무료 AI 영상에서 LTX(Kaggle) 품질을 고른 경우 — 사용자 본인 Kaggle GPU에서 오픈소스 모델이
  // 돌아 앱 비용이 0이라 포인트 차감 없이 통과시킨다. cost 0 인가는 무료 마감(워터마크+720p)
  // 규칙과 자동으로 맞물린다. refId 접두사 'kfree-'는 무빙포토 무료 슬롯('free-')과 구분해
  // releaseRenderAuthorization이 일일 카운트를 잘못 되돌리지 않게 하는 표식이다.
  if (lane === 'free_ai' && useProjectStore.getState().freeAiProvider === 'kaggle_ltx') {
    const freePass = { refId: `kfree-${crypto.randomUUID().replace(/-/g, '').slice(0, 24)}`, cost: 0 }
    useProjectStore.getState().setPointPayment(freePass)
    return freePass
  }

  // 무빙포토는 먼저 오늘의 무료 슬롯을 시도한다 — 남아있으면 차감 없이 통과(무료 마감)
  if (lane === 'moving_photo') {
    try {
      await checkAndIncrementDaily(
        user!.uid, 'movingPhoto', 'count', FREE_DAILY_MOVING_PHOTO_LIMIT, 1,
        `오늘의 무료 무빙포토 ${FREE_DAILY_MOVING_PHOTO_LIMIT}개를 모두 사용했어요.`
      )
      const freePass = { refId: `free-${crypto.randomUUID().replace(/-/g, '').slice(0, 24)}`, cost: 0 }
      useProjectStore.getState().setPointPayment(freePass)
      return freePass
    } catch (e) {
      if (!(e instanceof DailyLimitError)) throw e
      // 무료 한도 소진 → 아래 포인트 결제 경로로 계속 (포인트 결제분은 워터마크 없는 프리미엄 마감)
    }
  }

  const pricing = await fetchPricing()
  const cost = computeRenderCost(scenes, lane, pricing)
  const refId = `render-${crypto.randomUUID().replace(/-/g, '').slice(0, 24)}`
  await spendPoints(cost, `render:${lane}:${scenes.length}scenes`, refId)

  const payment = { refId, cost }
  useProjectStore.getState().setPointPayment(payment)
  return payment
}

/**
 * 전체 실패한 제작 건의 인가를 되돌린다 — 포인트 결제 건은 지갑 서버 환급(멱등),
 * 무료 슬롯 건은 오늘의 일일 카운트를 되살린다.
 */
export async function releaseRenderAuthorization(authz: RenderAuthorization): Promise<void> {
  if (authz.cost > 0) {
    await refundPoints(authz.refId)
    return
  }
  // 'kfree-'(Kaggle LTX 무료 통과)는 일일 슬롯을 소비하지 않았으므로 되돌릴 것도 없다
  if (!authz.refId.startsWith('free-')) return
  const uid = auth.currentUser?.uid
  if (uid) await decrementDaily(uid, 'movingPhoto', 'count', 1)
}

/**
 * 키프레임 이미지 다운로드 1건을 인가한다 — 오늘의 무료 슬롯이 남았으면 무료로 통과시키고,
 * 소진됐으면 그 자리에서 포인트를 차감한다. 렌더링과 달리 다운로드는 파일을 저장하거나 못 하거나
 * 둘 중 하나뿐인 단발성 동작이라(부분 실패가 없다) ensureRenderAuthorization과 달리 결과를
 * pointPayment처럼 프로젝트에 저장해두거나 실패 시 환급하는 로직이 필요 없다.
 */
export async function ensureKeyframeDownloadAuthorization(): Promise<void> {
  const { user, accessTier } = useUserStore.getState()
  const tier = accessTier()
  if (tier === 'guest') {
    throw new LoginRequiredError('이미지를 다운로드하려면 먼저 로그인해주세요. 가입하면 웰컴 포인트 1,000개를 드려요.')
  }
  if (tier === 'pro') return

  try {
    await checkAndIncrementDaily(
      user!.uid, 'keyframeDownload', 'count', FREE_DAILY_KEYFRAME_DOWNLOAD_LIMIT, 1,
      `오늘의 무료 이미지 다운로드 ${FREE_DAILY_KEYFRAME_DOWNLOAD_LIMIT}장을 모두 사용했어요.`
    )
    return
  } catch (e) {
    if (!(e instanceof DailyLimitError)) throw e
    // 무료 한도 소진 → 포인트 결제로 계속
  }

  const refId = `keyframe-dl-${crypto.randomUUID().replace(/-/g, '').slice(0, 24)}`
  await spendPoints(KEYFRAME_DOWNLOAD_PRICE, 'keyframe-download', refId)
}
