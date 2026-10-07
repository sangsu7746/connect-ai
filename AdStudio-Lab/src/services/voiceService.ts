import type { AppLocale, Person, VoiceStyle } from '../types'
import { auth } from './firebase'
import { fnUrl } from './firebaseTarget'

// 접속 대상(프로젝트·리전·에뮬레이터 여부)은 firebaseTarget 이 단독으로 결정한다.
const EDGE_TTS_BASE_URL = fnUrl('edgeTTS')

/**
 * 언어별 성별 보이스 풀 — edge-tts-universal의 VoicesManager로 실시간 조회해 실존이
 * 확인된 이름만 담았다(추정 매핑 아님). 언어마다 실제 보이스 개수가 다르므로(한국어 1~2개 ~
 * 영어 17개) 길이가 제각각이며, voiceStyle은 이 목록의 인덱스로 매핑해 짧은 목록에서도
 * 안전하게(모자라면 순환) 동작하게 한다.
 */
const LANGUAGE_VOICES: Record<AppLocale, { female: string[]; male: string[] }> = {
  ko: {
    female: ['ko-KR-SunHiNeural'],
    male: ['ko-KR-InJoonNeural', 'ko-KR-HyunsuMultilingualNeural'],
  },
  en: {
    female: ['en-US-AvaNeural', 'en-US-EmmaNeural', 'en-US-JennyNeural', 'en-US-MichelleNeural'],
    male: ['en-US-AndrewNeural', 'en-US-BrianNeural', 'en-US-GuyNeural', 'en-US-EricNeural'],
  },
  zh: {
    female: ['zh-CN-XiaoxiaoNeural', 'zh-CN-XiaoyiNeural'],
    male: ['zh-CN-YunxiNeural', 'zh-CN-YunjianNeural', 'zh-CN-YunyangNeural', 'zh-CN-YunxiaNeural'],
  },
  es: {
    female: ['es-ES-ElviraNeural', 'es-ES-XimenaNeural', 'es-MX-DaliaNeural'],
    male: ['es-ES-AlvaroNeural', 'es-MX-JorgeNeural'],
  },
  hi: {
    female: ['hi-IN-SwaraNeural'],
    male: ['hi-IN-MadhurNeural'],
  },
  pt: {
    female: ['pt-BR-FranciscaNeural', 'pt-PT-RaquelNeural', 'pt-BR-ThalitaMultilingualNeural'],
    male: ['pt-BR-AntonioNeural', 'pt-PT-DuarteNeural'],
  },
  it: {
    female: ['it-IT-ElsaNeural', 'it-IT-IsabellaNeural'],
    male: ['it-IT-DiegoNeural', 'it-IT-GiuseppeMultilingualNeural'],
  },
  de: {
    female: ['de-DE-KatjaNeural', 'de-DE-AmalaNeural', 'de-DE-SeraphinaMultilingualNeural'],
    male: ['de-DE-ConradNeural', 'de-DE-KillianNeural', 'de-DE-FlorianMultilingualNeural'],
  },
  ja: {
    female: ['ja-JP-NanamiNeural'],
    male: ['ja-JP-KeitaNeural'],
  },
  fr: {
    female: ['fr-FR-DeniseNeural', 'fr-FR-EloiseNeural', 'fr-FR-VivienneMultilingualNeural'],
    male: ['fr-FR-HenriNeural', 'fr-FR-RemyMultilingualNeural'],
  },
}

const VOICE_STYLE_INDEX: Record<VoiceStyle, number> = { calm: 0, bright: 1, husky_deep: 2, warm_soft: 3 }

/**
 * 다국어(Multilingual) 보이스 — Edge TTS 공식 목록에서 실존이 확인된 12종.
 * 이 보이스들은 입력 텍스트의 언어를 따라가므로 어떤 언어로도 읽을 수 있다.
 * 한국어 전용 보이스는 3개(여1·남2)뿐이라, 목소리를 다양하게 고르려면 이 풀이 사실상 유일한 확장 수단이다.
 * (원어민 보이스보다 억양이 미세하게 다를 수 있어 UI에서 '다국어'로 구분해 표시한다)
 */
const MULTILINGUAL_VOICES: VoiceOption[] = [
  { id: 'en-US-AvaMultilingualNeural', label: '에이바', gender: 'female', native: false, desc: '표현력·친근함' },
  { id: 'en-US-EmmaMultilingualNeural', label: '엠마', gender: 'female', native: false, desc: '밝고 또렷함' },
  { id: 'fr-FR-VivienneMultilingualNeural', label: '비비안', gender: 'female', native: false, desc: '부드러움' },
  { id: 'de-DE-SeraphinaMultilingualNeural', label: '세라피나', gender: 'female', native: false, desc: '차분함' },
  { id: 'pt-BR-ThalitaMultilingualNeural', label: '탈리타', gender: 'female', native: false, desc: '따뜻함' },
  { id: 'en-US-AndrewMultilingualNeural', label: '앤드류', gender: 'male', native: false, desc: '신뢰감·중저음' },
  { id: 'en-US-BrianMultilingualNeural', label: '브라이언', gender: 'male', native: false, desc: '편안한 대화체' },
  { id: 'en-AU-WilliamMultilingualNeural', label: '윌리엄', gender: 'male', native: false, desc: '친근함' },
  { id: 'fr-FR-RemyMultilingualNeural', label: '레미', gender: 'male', native: false, desc: '부드러움' },
  { id: 'de-DE-FlorianMultilingualNeural', label: '플로리안', gender: 'male', native: false, desc: '차분함' },
  { id: 'it-IT-GiuseppeMultilingualNeural', label: '주세페', gender: 'male', native: false, desc: '활기참' },
]

/** 언어별 원어민 보이스의 표시 이름 — 목록에 없으면 보이스 ID에서 이름 부분을 뽑아 쓴다. */
const NATIVE_VOICE_LABELS: Record<string, string> = {
  'ko-KR-SunHiNeural': '선희', 'ko-KR-InJoonNeural': '인준', 'ko-KR-HyunsuMultilingualNeural': '현수',
  'ja-JP-NanamiNeural': '나나미', 'ja-JP-KeitaNeural': '케이타',
}

export interface VoiceOption {
  id: string                       // Edge TTS 보이스 ShortName
  label: string                    // UI 표시 이름
  gender: 'female' | 'male'
  native: boolean                  // 해당 언어 원어민 보이스인지
  desc?: string
}

/**
 * 특정 언어에서 고를 수 있는 보이스 목록 — 원어민 보이스를 앞에, 다국어 보이스를 뒤에 둔다.
 * UI(음성 선택)와 씬별 목소리 순환(variety) 모두 이 목록을 기준으로 동작한다.
 */
export function getVoiceOptions(locale: AppLocale, gender?: 'male' | 'female'): VoiceOption[] {
  const pool = LANGUAGE_VOICES[locale] ?? LANGUAGE_VOICES.en
  // 보이스 ID(xx-YY-NameNeural)에서 사람 이름만 뽑는다. 'Multilingual'까지 붙어 있으면 떼어내
  // 'ThalitaMultilingual' 같은 기계적인 라벨이 그대로 노출되지 않게 한다.
  const labelOf = (id: string) =>
    NATIVE_VOICE_LABELS[id] ?? (id.split('-')[2] ?? id).replace(/Neural$/, '').replace(/Multilingual$/, '')
  const native: VoiceOption[] = [
    ...pool.female.map(id => ({ id, label: labelOf(id), gender: 'female' as const, native: !/Multilingual/.test(id) })),
    ...pool.male.map(id => ({ id, label: labelOf(id), gender: 'male' as const, native: !/Multilingual/.test(id) })),
  ]
  // 원어민 목록에 이미 있는 다국어 보이스(예: 한국어의 현수)는 중복으로 넣지 않는다
  const nativeIds = new Set(native.map(v => v.id))
  const all = [...native, ...MULTILINGUAL_VOICES.filter(v => !nativeIds.has(v.id))]
  return gender ? all.filter(v => v.gender === gender) : all
}

/**
 * 언어×성별×음성톤 → 실제 Edge TTS 보이스 이름. voiceStyle은 그 언어의 보이스 풀 크기로
 * 나눈 나머지로 인덱싱한다 — 보이스가 1개뿐인 언어(한국어 여성, 일본어, 힌디어 등)는 톤을
 * 골라도 실제로는 같은 보이스로 수렴한다(현재 Edge TTS 공급 한계, 억지로 다양화하지 않음).
 */
export function resolveVoiceName(
  locale: AppLocale,
  gender?: 'male' | 'female' | 'unknown',
  voiceStyle?: VoiceStyle,
  // 사용자가 특정 보이스를 직접 고른 경우 — 언어·성별 추론보다 항상 우선한다
  voiceId?: string,
  // 씬마다 목소리를 바꾸는 모드에서 쓰는 순환 인덱스(보통 씬 번호)
  varietyIndex?: number,
): string {
  if (voiceId) return voiceId

  if (varietyIndex !== undefined) {
    const g = gender === 'male' || gender === 'female' ? gender : undefined
    const options = getVoiceOptions(locale, g)
    if (options.length > 0) return options[Math.abs(varietyIndex) % options.length].id
  }

  const pool = LANGUAGE_VOICES[locale] ?? LANGUAGE_VOICES.en
  const list = gender === 'male' ? pool.male : gender === 'female' ? pool.female : (pool.female[0] ? pool.female : pool.male)
  const idx = VOICE_STYLE_INDEX[voiceStyle ?? 'calm'] % list.length
  return list[idx]
}

/**
 * 나이대별 rate/pitch 보정치 — 언어와 무관한 순수 오디오 프로소디 조정이라 모든 언어에
 * 동일하게 적용한다. Edge TTS 대부분의 언어엔 아동/청소년 전용 보이스가 따로 없어서,
 * 같은 보이스의 속도·피치를 조정해 어린/나이 든 인상을 흉내내는 근사치다.
 */
const AGE_PROSODY: Record<NonNullable<Person['ageBand']>, { rate: string; pitch: string }> = {
  child: { rate: '+15%', pitch: '+20Hz' },
  teen: { rate: '+8%', pitch: '+10Hz' },
  adult: { rate: '+0%', pitch: '+0Hz' },
  senior: { rate: '-10%', pitch: '-15Hz' },
}

export function resolveProsody(ageBand?: Person['ageBand']): { rate: string; pitch: string } {
  return AGE_PROSODY[ageBand ?? 'adult']
}

export interface SpeakerVoice {
  gender?: 'male' | 'female' | 'unknown'
  ageBand?: Person['ageBand']
  voiceStyle?: VoiceStyle
  voiceId?: string        // 사용자가 직접 고른 보이스 (있으면 최우선)
  varietyIndex?: number   // 씬마다 다른 목소리 모드일 때의 순환 인덱스
}

/**
 * 대사 텍스트를 지정된 화자 목소리·언어로 합성해 재생 가능한 blob URL을 반환한다.
 * Edge TTS는 비공식 API라 실패할 수 있다 — 호출부가 실패 시 해당 씬은 음성 없이(자막만)
 * 우아하게 진행할 수 있도록 에러를 그대로 던진다(억지 폴백 없음, 상위에서 판단).
 */
export async function synthesizeDialogue(text: string, locale: AppLocale, speaker: SpeakerVoice): Promise<string> {
  const voice = resolveVoiceName(locale, speaker.gender, speaker.voiceStyle, speaker.voiceId, speaker.varietyIndex)
  const { rate, pitch } = resolveProsody(speaker.ageBand)

  // Cloud Functions 비용이 발생하는 호출이라 로그인한 사용자만 쓸 수 있다 — 서버가 이 토큰으로
  // 신원을 확인하고 플랜별 월간 한도를 센다. 비로그인이면 호출부의 기존 자막 전용 폴백으로 넘어간다.
  const idToken = await auth.currentUser?.getIdToken()
  if (!idToken) {
    throw new Error('음성 생성은 로그인 후 이용할 수 있어요.')
  }

  const res = await fetch(EDGE_TTS_BASE_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${idToken}` },
    body: JSON.stringify({ text, voice, rate, pitch }),
  })
  if (!res.ok) {
    const errText = await res.text().catch(() => '')
    throw new Error(`음성 합성 실패 (${res.status}): ${errText}`)
  }
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}
