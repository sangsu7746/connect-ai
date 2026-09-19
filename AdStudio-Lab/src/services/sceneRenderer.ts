import type { Scene, Lane, ProviderKey, Person, Photo, AppLocale } from '../types'
import { KeyVault, useKeysStore, ALIBABA_FREE_QUOTA_SECONDS, isAlibabaBlocked } from '../stores/keysStore'
import { useUserStore, LoginRequiredError } from '../stores/userStore'
import { useProjectStore } from '../stores/projectStore'
import { GenericAIAdapter, KaggleLtxAdapter, ImageGenerator, GeminiAdapter, QuotaExhaustedError, VEO_DURATION_SECONDS, type KeyframeGenerationResult } from './aiAdapters'
import { FFmpegService } from './ffmpegService'
import { synthesizeDialogue, type SpeakerVoice } from './voiceService'
import { translateSceneTextDetailed, detectTextLocale } from './localizationService'
import { resolveSceneSubjects, findSharedSourcePhoto } from '../utils/personResolver'
import { getBodyConceptModifier, getOutfitConceptModifier } from '../utils/storyboardGenerator'
import { useAdStore } from '../stores/adStore'

export interface SceneRenderOutcome {
  videoUrl: string
  provider: ProviderKey | 'local'
  // true면 아직 실제 어댑터가 연결되지 않아 GenericAIAdapter의 임시 영상으로 대체된 경우
  isMocked: boolean
  // true면 이 씬에 지정된 인물이 있는데도 참조 이미지 기반 키프레임 생성이 실패해 텍스트 설명만으로
  // 대체된 경우 — 인물 외형이 다르게 나올 수 있다는 걸 호출부가 사용자에게 알리는 데 쓴다.
  consistencyDegraded: boolean
}

// 실제 API 어댑터가 연결된 제공자 — 목업 폴백(GenericAIAdapter 마지막 분기)을 타는 것은 'runway' 하나뿐이다.
// 이 목록에서 빠지면 isMocked=true가 되어, 실제 요금이 나갔는데도 사용자에게 "연동 준비 중이라
// 임시 영상으로 대체했다"는 사실과 다른 안내가 뜬다(veo·seedance가 그래서 누락돼 있었다).
const REAL_ADAPTER_PROVIDERS: ProviderKey[] = ['alibaba', 'kling', 'hailuo', 'seedance', 'veo']

// 유료(premium) 레인에서 선호 제공자의 키가 없을 때 대체할 우선순위.
// 실제로 연동된 제공자를 먼저 시도해, 가능하면 목업이 아닌 진짜 결과를 준다.
const PREMIUM_FALLBACK_ORDER: ProviderKey[] = ['kling', 'hailuo', 'alibaba', 'veo', 'seedance', 'runway']

/**
 * KeysPage에 안내된 "스마트 라우팅" 규칙(대사→Veo, 클로즈업→Kling, 동작/스타일 과다→Hailuo,
 * 그 외 일반 씬→Seedance)을 씬에 실제로 존재하는 정보만으로 근사한다.
 */
function routePremiumProvider(scene: Scene): ProviderKey {
  if (scene.dialogueKo?.trim()) return 'veo'

  const haystack = `${scene.descKo} ${scene.keyframePromptEn}`.toLowerCase()
  const isCloseup = scene.subjectRefs.length === 1 && /close.?up|클로즈업|portrait/.test(haystack)
  if (isCloseup) return 'kling'

  if ((scene.motionPromptEn ?? '').length > 50) return 'hailuo'

  return 'seedance'
}

/**
 * 씬에 맞는 선호 제공자를 우선 시도하고, 키가 없으면 등록된 다른 제공자로 대체한다.
 * 등록된 유료 키가 하나도 없으면 null을 반환한다.
 */
export async function resolvePremiumProvider(scene: Scene): Promise<ProviderKey | null> {
  // 사용자가 고퀄 레인에서 제공자를 직접 골랐으면 그것만 쓴다 — 자동 라우팅으로 다른 제공자에
  // (그래서 예상 못 한 단가로) 넘어가지 않도록, 키가 없으면 폴백하지 않고 null을 반환한다.
  const picked = useProjectStore.getState().premiumProvider
  if (picked) {
    if (picked === 'alibaba' && isAlibabaBlocked()) return null
    return (await KeyVault.hasKey(picked)) ? picked : null
  }

  const preferred = routePremiumProvider(scene)
  const candidates = [preferred, ...PREMIUM_FALLBACK_ORDER.filter(p => p !== preferred)]
  for (const provider of candidates) {
    // 무료 기한이 만료된 알리바바는 폴백 후보에서도 제외 — 기한 후 호출은 실요금 위험
    if (provider === 'alibaba' && isAlibabaBlocked()) continue
    if (await KeyVault.hasKey(provider)) return provider
  }
  return null
}

// person.id별 Gemini 비전 디스크립터 캐시 (세션 내 동일 인물 재요청 방지)
const descriptorCache = new Map<string, Promise<string | null>>()

/**
 * 인물 크롭 이미지를 Gemini로 캡션화해 캐싱한다. Gemini 키가 없거나 소스 이미지가 없거나
 * 호출이 실패하면 null을 반환한다 — 디스크립터는 어디까지나 프롬프트 향상 기능이라
 * 실패해도 파이프라인을 막지 않고 조용히 기본 템플릿 문구로 진행한다.
 */
async function getPersonDescriptor(person: Person): Promise<string | null> {
  const cached = descriptorCache.get(person.id)
  if (cached) return cached

  const promise = (async () => {
    const apiKey = await KeyVault.getKey('gemini')
    const sourceImage = person.halfBodyUrl ?? person.cropUrl
    if (!apiKey || !sourceImage) return null
    try {
      return await GeminiAdapter.describePersonImage(sourceImage, apiKey)
    } catch (e) {
      console.warn('인물 디스크립터 생성 실패 — 템플릿 기본 표현으로 진행합니다:', e)
      return null
    }
  })()

  descriptorCache.set(person.id, promise)
  return promise
}

/** 바디·의상 컨셉 중 하나라도 지정된 인물인지 — 지정 시 사진 속 실제 모습 대신 컨셉으로 그린다 */
function hasConceptOverride(person: Person): boolean {
  return (!!person.bodyConcept && person.bodyConcept !== 'none')
    || (!!person.outfitConcept && person.outfitConcept !== 'none')
}

/**
 * 인물 한 명의 프롬프트 조각을 만든다. 바디/의상 컨셉이 지정됐으면 Gemini 캡션을 아예 시도하지
 * 않고 선택한 컨셉의 고정 텍스트로 대체한다(API 키·네트워크 상태와 무관하게 항상 적용되므로
 * 오히려 Gemini 캡션보다 안정적이다). 지정 안 했으면 기존처럼 사진 기반 캡션을 그대로 쓴다.
 */
async function getPersonPromptFragment(person: Person): Promise<string | null> {
  if (hasConceptOverride(person)) {
    return [getBodyConceptModifier(person.bodyConcept), getOutfitConceptModifier(person.outfitConcept)]
      .filter(Boolean)
      .join(', ')
  }
  return getPersonDescriptor(person)
}

interface KeyframeContext {
  prompt: string
  referenceImageUrls: string[] // Alibaba 참조 이미지 기반 생성(§B)에 실어 보낼 인물 크롭, 최대 3장
  seed: number // subjectRefs 조합에서 결정론적으로 뽑은 시드 — 같은 인물(조합)의 씬마다 재사용해 일관성을 돕는다
}

/** 문자열을 0~2147483647 범위의 정수로 결정론적으로 해시한다(DashScope seed 파라미터 유효 범위). */
function seedFromString(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h) % 2147483647
}

/**
 * subjectRefs로 해석되는 인물들을 바탕으로 키프레임 생성 컨텍스트를 만든다.
 * - prompt: "Actor N (reference image N): 디스크립터" 형태로 인물마다 번호를 매겨 덧붙인 문구
 *   (해석되는 인물이 없거나 디스크립터를 하나도 못 얻으면 원본 프롬프트 그대로)
 * - referenceImageUrls: 인물별 단독 크롭(half_body_ref/face_ref) — "이미지 하나에 배우 1명" 원칙으로
 *   항상 1:1 대응만 쓴다(그룹 사진처럼 한 이미지에 여러 인물이 섞이면 모델이 참조 이미지와 Actor 라벨을
 *   순서만으로 추측해야 해서 인물이 뒤바뀌기 쉬워지므로 더 이상 그룹 사진은 참조로 쓰지 않는다)
 * - seed: 같은 인물 조합(예: "person_1" 단독 vs "person_1+person_2")이면 씬이 달라도 항상 같은 값 —
 *   씬마다 매번 랜덤 시드를 쓰면 같은 사람인데도 매번 다른 얼굴/체형/의상으로 그려지는 문제를 완화한다
 */
async function buildKeyframeContext(scene: Scene, persons: Person[]): Promise<KeyframeContext> {
  const subjects = resolveSceneSubjects(scene, persons)
  const seed = seedFromString(subjects.map(p => p.id).sort().join('|') || scene.id)
  if (subjects.length === 0) return { prompt: scene.keyframePromptEn, referenceImageUrls: [], seed }

  // (AdStudio) 광고 프로젝트면 "배우 사용 방식"의 반영 범위가 참조 이미지를 결정한다:
  // 얼굴만 → face_ref(cropUrl) 우선, 상반신/전신 → half_body_ref 우선. 광고가 아니면 오마주 기본 규칙.
  const adScope = useAdStore.getState().analysis ? useAdStore.getState().actorUsage.scope : null
  const entries = await Promise.all(subjects.map(async (p, i) => ({
    actorNo: i + 1,
    descriptor: await getPersonPromptFragment(p),
    cropUrl: adScope === 'face'
      ? (p.cropUrl ?? p.halfBodyUrl)
      : adScope === 'half' || adScope === 'full'
      ? (p.halfBodyUrl ?? p.cropUrl)
      : hasConceptOverride(p) ? (p.cropUrl ?? p.halfBodyUrl) : (p.halfBodyUrl ?? p.cropUrl),
  })))

  // DashScope/Gemini 참조 이미지 한도(3장)를 넘는 인물은 텍스트 디스크립터로만 남기고 참조 이미지는 생략한다
  const withCrop = entries.filter((e): e is typeof e & { cropUrl: string } => !!e.cropUrl).slice(0, 3)
  const referenceImageUrls = withCrop.map(e => e.cropUrl)
  const refIndexByActor = new Map(withCrop.map((e, i) => [e.actorNo, i + 1]))

  const descriptorLines = entries
    .filter((e): e is typeof e & { descriptor: string } => !!e.descriptor)
    .map(e => {
      const refIdx = refIndexByActor.get(e.actorNo)
      const label = refIdx ? `Actor ${e.actorNo} (reference image ${refIdx})` : `Actor ${e.actorNo}`
      return `${label}: ${e.descriptor}`
    })

  const basePrompt = descriptorLines.length > 0
    ? `${scene.keyframePromptEn}, featuring: ${descriptorLines.join('; ')}`
    : scene.keyframePromptEn
  // 팔 여러 개·공중에 뜬 신체 일부 같은 인체 구조 이상을 줄이기 위해 항상 덧붙이는 예방 문구
  const prompt = `${basePrompt}, anatomically correct human body, natural proportions, correct number of limbs and fingers, single coherent figure per person`

  return { prompt, referenceImageUrls, seed }
}

async function ensureKeyframe(scene: Scene, ctx: KeyframeContext): Promise<KeyframeGenerationResult> {
  if (scene.keyframeUrl) return { url: scene.keyframeUrl, degraded: false, seed: ctx.seed }
  return ImageGenerator.generateKeyframe(ctx.prompt, ctx.referenceImageUrls, ctx.seed)
}

/**
 * S4 스토리보드 화면(자동/수동 키프레임 생성)에서 쓰는 공개 API — buildKeyframeContext(디스크립터+
 * 참조이미지)를 그대로 ImageGenerator.generateKeyframe에 흘려보낸다. renderScene의 free_ai/premium
 * 레인과 동일한 인물 반영 로직을 S4 단계에서도 재사용해, S4가 미리 채워둔 keyframeUrl 때문에
 * S5에서 인물 반영 생성이 건너뛰어지지 않도록 한다.
 */
export async function generateSceneKeyframe(scene: Scene, persons: Person[], photos: Photo[], seedOverride?: number): Promise<KeyframeGenerationResult> {
  const ctx = await buildKeyframeContext(scene, persons)
  return ImageGenerator.generateKeyframe(ctx.prompt, ctx.referenceImageUrls, seedOverride ?? ctx.seed)
}

/**
 * moving_photo 레인은 AI 생성 없이 실제 인물 사진을 그대로 Ken Burns 소스로 쓴다.
 * subjectRefs를 실제 Person으로 해석해 half_body_ref(매팅됐거나 원본 배경인 인물 크롭)를 우선 사용하고,
 * 두 명 이상이 같은 원본 사진에서 나왔다면(커플/단체 구도 보존) 그 원본 사진을 대신 쓴다.
 * 해석되는 인물이 하나도 없을 때만 기존 AI 키프레임 생성으로 폴백한다.
 */
async function resolveMovingPhotoSource(scene: Scene, persons: Person[], photos: Photo[]): Promise<{ url: string; degraded: boolean }> {
  const subjects = resolveSceneSubjects(scene, persons)
  const sharedPhoto = findSharedSourcePhoto(subjects, photos)
  if (sharedPhoto) return { url: sharedPhoto.previewUrl, degraded: false }

  const primary = subjects[0]
  if (primary?.halfBodyUrl) return { url: primary.halfBodyUrl, degraded: false }
  if (primary?.cropUrl) return { url: primary.cropUrl, degraded: false }

  return ensureKeyframe(scene, await buildKeyframeContext(scene, persons))
}

/**
 * 레인/씬 정보를 바탕으로 실제 씬 영상을 생성한다.
 * - moving_photo: 실제 인물 사진(half_body_ref 또는 원본)을 ffmpeg으로 무빙포토(Ken Burns) 클립으로 변환 (외부 API 없음, 무료·즉시)
 * - free_ai: 품질 선택 — LTX(내 Kaggle GPU, 저품질·무료) 또는 알리바바 Wan(중품질·포인트)
 * - premium: 씬 특성에 맞는 유료 제공자로 라우팅, 등록된 키가 없으면 실제 연동된 제공자로 대체
 */
export async function renderScene(scene: Scene, lane: Lane, persons: Person[], photos: Photo[]): Promise<SceneRenderOutcome> {
  const tier = useUserStore.getState().accessTier()

  // 비로그인은 어떤 레인이든 생성을 막는다 — 무료 한도·지갑이 계정 기준이라 로그인이 전제다.
  if (tier === 'guest') {
    throw new LoginRequiredError('영상을 만들려면 먼저 로그인해주세요. 가입하면 웰컴 포인트 1,000개를 드려요.')
  }
  // free 티어는 제작 시작 시점에 인가(무료 슬롯 또는 포인트 결제 — ensureRenderAuthorization)가
  // 반드시 선행돼야 한다. S4/S5가 이미 처리하지만, 다른 경로로 우회 호출되는 걸 막는 안전망.
  if (tier === 'free' && !useProjectStore.getState().pointPayment) {
    throw new Error('제작 인가 정보가 없어요. 스토리보드 화면에서 다시 제작을 시작해주세요.')
  }

  if (lane === 'moving_photo') {
    const source = await resolveMovingPhotoSource(scene, persons, photos)
    const videoUrl = await FFmpegService.imageToVideoClip(source.url, scene.duration)
    return { videoUrl, provider: 'local', isMocked: false, consistencyDegraded: source.degraded }
  }

  if (lane === 'free_ai') {
    // 품질 선택 분기 — kaggle_ltx: 내 Kaggle GPU에서 LTX 오픈소스 실행(저품질·느림·무료),
    // alibaba: Wan 무료 쿼터(중품질·빠름·포인트). 과금 차이는 ensureRenderAuthorization이 처리한다.
    if (useProjectStore.getState().freeAiProvider === 'kaggle_ltx') {
      if (!(await KeyVault.hasKey('kaggle'))) {
        throw new Error('Kaggle API 토큰이 설정되어 있지 않아요. 키 설정 화면에서 "유저명:키" 형식으로 등록해주세요.')
      }
      const ctx = await buildKeyframeContext(scene, persons)
      const keyframe = await ensureKeyframe(scene, ctx)
      const { videoUrl } = await KaggleLtxAdapter.runTask(
        keyframe.url,
        `${ctx.prompt}, ${scene.motionPromptEn}`,
        scene.duration,
        scene.id
      )
      return { videoUrl, provider: 'kaggle', isMocked: false, consistencyDegraded: keyframe.degraded }
    }

    if (!(await KeyVault.hasKey('alibaba'))) {
      throw new Error('알리바바 API 키가 설정되어 있지 않아요. 키 설정 화면에서 등록한 뒤 다시 시도해주세요.')
    }

    // 개인 알리바바 무료 쿼터(1650초) 기준 — 실제 API 호출 전에 앱이 추정해 온 사용량으로
    // 먼저 걸러낸다(어차피 실패할 호출을 아끼고 즉시 정지 요구를 충족)
    const estimatedUsed = useKeysStore.getState().quotas['alibaba']?.estimatedSecondsUsed ?? 0
    if (estimatedUsed + scene.duration > ALIBABA_FREE_QUOTA_SECONDS) {
      throw new QuotaExhaustedError(
        'alibaba',
        `알리바바 무료 쿼터(${ALIBABA_FREE_QUOTA_SECONDS}초)를 모두 사용한 것으로 추정돼요(약 ${estimatedUsed}초 사용). 콘솔에서 "무료 쿼터만 사용" 설정을 해제하면 이후 생성부터 실제 요금이 청구되는 유료 모드로 전환돼요.`
      )
    }

    const ctx = await buildKeyframeContext(scene, persons)
    const keyframe = await ensureKeyframe(scene, ctx)
    const { videoUrl } = await GenericAIAdapter.runTask(
      'alibaba',
      keyframe.url,
      `${ctx.prompt}, ${scene.motionPromptEn}`
    )
    useKeysStore.getState().updateUsage('alibaba', scene.duration)
    return { videoUrl, provider: 'alibaba', isMocked: false, consistencyDegraded: keyframe.degraded }
  }

  // premium
  const provider = await resolvePremiumProvider(scene)
  if (!provider) {
    throw new Error('사용 가능한 유료 API 키가 없어요. 키 설정 화면에서 하나 이상 등록한 뒤 다시 시도해주세요.')
  }
  const ctx = await buildKeyframeContext(scene, persons)
  const keyframe = await ensureKeyframe(scene, ctx)
  const { videoUrl } = await GenericAIAdapter.runTask(
    provider,
    keyframe.url,
    `${ctx.prompt}, ${scene.motionPromptEn}`
  )
  // 지출 추적 — 무료 레인(alibaba)만 집계하고 있어서 유료 레인(Veo·Kling·Hailuo·Seedance) 지출이
  // 앱에서 전혀 보이지 않았다. Veo는 씬 길이가 아니라 요청에 실어 보낸 durationSeconds로 청구되므로
  // 그 값을 그대로 넣어야 실제 청구액과 맞는다.
  // ⚠️ 미확인: kling·hailuo·seedance의 청구 기준 초(각 어댑터가 고정해 보내는 duration과 실제 청구
  // 단위가 일치하는지) — 콘솔/문서에서 확인 후 적용. 지금은 씬 길이로 근사해 둔다.
  useKeysStore.getState().updateUsage(provider, provider === 'veo' ? VEO_DURATION_SECONDS : scene.duration)
  return { videoUrl, provider, isMocked: !REAL_ADAPTER_PROVIDERS.includes(provider), consistencyDegraded: keyframe.degraded }
}

/**
 * 씬 대사의 화자를 정한다: speakerId가 지정돼 있으면 그 인물, 아니면 subjectRefs의 첫 인물.
 * voiceOverride("이 씬만 톤 다르게")가 있으면 화자의 기본값보다 우선한다.
 */
function resolveSpeakerVoice(scene: Scene, persons: Person[]): SpeakerVoice {
  // (AdStudio) 광고 프로젝트의 대사는 인물 대사가 아니라 성우 나레이션 — 광고 컨셉[3]에서 고른
  // 음성으로 전 씬을 통일한다. (AI 가상 배우 모드는 persons가 비어 화자를 못 정해 합성이
  // 실패하던 문제도 이것으로 해결)
  // 광고 여부는 분석 결과 또는 저장된 프로젝트의 컨셉 ID(ad_*)로 판정한다 — 둘 중 하나만 살아 있어도
  // 광고 나레이션 경로를 타게 해서, 상태 유실 시 인물 화자 경로로 잘못 빠지는 것을 막는다.
  const ad = useAdStore.getState()
  const isAdProject = !!ad.analysis || !!useProjectStore.getState().currentProject?.conceptId?.startsWith('ad_')
  if (isAdProject) {
    return {
      gender: ad.config.voice,
      ageBand: 'adult',
      voiceStyle: scene.voiceOverride?.voiceStyle,
      // 사용자가 특정 성우를 고르면 그 목소리로 고정, "씬마다 다른 목소리"면 씬 번호로 순환.
      // scene.seq는 1부터 시작하므로 0-기반으로 바꿔 넘긴다 — 그대로 넘기면 목록 0번(그 언어의
      // 원어민 성우, 한국어 여성은 '선희' 하나뿐)이 영영 선택되지 않아 전 씬이 외국 억양이 된다.
      voiceId: ad.config.voiceVariety ? undefined : ad.config.voiceId,
      varietyIndex: ad.config.voiceVariety ? Math.max(0, (scene.seq ?? 1) - 1) : undefined,
    }
  }

  const speaker = scene.speakerId
    ? persons.find(p => p.id === scene.speakerId || p.label === scene.speakerId)
    : resolveSceneSubjects(scene, persons)[0]

  return {
    gender: scene.voiceOverride?.gender ?? speaker?.gender,
    ageBand: scene.voiceOverride?.ageBand ?? speaker?.ageBand,
    voiceStyle: scene.voiceOverride?.voiceStyle ?? speaker?.voiceStyle,
  }
}

export interface LocalizedDialogue {
  start: number // 병합된 최종 영상 기준 시작 시각(초)
  end: number
  text: string // 선택된 언어로 번역된(한국어면 원문 그대로인) 자막 텍스트
  audioUrl?: string // 음성 합성 성공했을 때만 존재 — 실패해도 text(자막)는 항상 있음
  translationFailed?: boolean // 선택 언어로 번역하지 못해 원문 언어 성우로 대체했는지 (사용자 안내용)
  voiceError?: string // 음성 합성이 실패한 이유 — 월 한도 초과 같은 원인을 사용자에게 그대로 알리기 위함
}

/**
 * 대사가 있는 씬들을 선택된 언어로 번역하고(한국어면 번역 생략) 그 텍스트로 목소리를 합성해,
 * 최종 영상 타임라인 기준 시작 시각과 함께 반환한다 — 자막·음성이 항상 같은 번역문을 쓰도록
 * 한 곳에서 처리한다. Edge TTS는 비공식 API라 개별 씬에서 실패할 수 있는데, 한 번 실패하면
 * 잠깐 대기 후 한 번 더 시도해보고(일시적 네트워크·서비스 hiccup 구제), 그래도 안 되면 그 씬은
 * audioUrl 없이 자막(text)만 남기고 조용히 넘어간다(영상 전체 제작을 막지 않는다).
 */
export async function buildLocalizedDialogue(
  entries: { scene: Scene; start: number; end: number }[],
  persons: Person[],
  locale: AppLocale
): Promise<LocalizedDialogue[]> {
  return Promise.all(entries.map(async ({ scene, start, end }) => {
    const original = scene.dialogueKo!.trim()
    const r = await translateSceneTextDetailed(original, locale)
    const text = r.text

    // 번역이 실제로 실패했다면(키 없음·쿼터 소진 등) 텍스트는 여전히 원문 언어다.
    // 이때 선택한 언어의 성우를 쓰면 "한국어 성우가 영어를 읽는" 언어 불일치가 그대로 재현되므로,
    // 성우 언어를 실제 텍스트 언어에 맞춰 최소한 발음이라도 맞게 만든다.
    const voiceLocale = (!r.translated && !r.skipped) ? detectTextLocale(text) : locale
    if (voiceLocale !== locale) {
      console.warn(`씬 ${scene.seq}: "${locale}" 번역에 실패해 성우 언어를 "${voiceLocale}"로 맞춥니다.`)
    }

    const speaker = resolveSpeakerVoice(scene, persons)
    // 원문 언어로 폴백한 경우엔 사용자가 고른 성우(다른 언어 전용일 수 있음) 대신 그 언어 기본 성우를 쓴다
    const effectiveSpeaker = voiceLocale === locale ? speaker : { ...speaker, voiceId: undefined }

    try {
      const audioUrl = await synthesizeDialogue(text, voiceLocale, effectiveSpeaker)
      return { start, end, text, audioUrl, translationFailed: voiceLocale !== locale }
    } catch (e) {
      console.warn(`씬 ${scene.seq} 음성 합성 실패, 잠시 후 한 번 더 시도합니다:`, e)
      try {
        await new Promise(r2 => setTimeout(r2, 1000))
        const audioUrl = await synthesizeDialogue(text, voiceLocale, effectiveSpeaker)
        return { start, end, text, audioUrl, translationFailed: voiceLocale !== locale }
      } catch (e2) {
        console.warn(`씬 ${scene.seq} 음성 합성 재시도도 실패 — 이 씬은 자막만 표시됩니다:`, e2)
        // 실패 사유를 위로 올린다 — "월 한도 초과(429)" 같은 원인은 사용자가 알아야 조치할 수 있고,
        // 모르면 그냥 "음성 없는 영상"이 나온 이유를 영영 알 수 없다.
        const msg = e2 instanceof Error ? e2.message : String(e2)
        return { start, end, text, translationFailed: voiceLocale !== locale, voiceError: msg }
      }
    }
  }))
}
