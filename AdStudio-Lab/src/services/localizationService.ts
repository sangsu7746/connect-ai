import type { AppLocale } from '../types'
import { KeyVault } from '../stores/keysStore'
import { GeminiAdapter } from './aiAdapters'

// Edge TTS에 실제로 보이스가 있는 것을 VoicesManager로 확인한 10개 언어만 지원한다.
export const SUPPORTED_LOCALES: AppLocale[] = ['ko', 'en', 'zh', 'es', 'hi', 'pt', 'it', 'de', 'ja', 'fr']

export const LOCALE_INFO: Record<AppLocale, { labelKo: string; labelNative: string; geminiName: string }> = {
  ko: { labelKo: '한국어',     labelNative: '한국어',      geminiName: 'Korean' },
  en: { labelKo: '영어',       labelNative: 'English',    geminiName: 'English' },
  zh: { labelKo: '중국어',     labelNative: '中文',        geminiName: 'Chinese (Simplified)' },
  es: { labelKo: '스페인어',   labelNative: 'Español',    geminiName: 'Spanish' },
  hi: { labelKo: '힌디어',     labelNative: 'हिन्दी',       geminiName: 'Hindi' },
  pt: { labelKo: '포르투갈어', labelNative: 'Português',  geminiName: 'Portuguese' },
  it: { labelKo: '이탈리아어', labelNative: 'Italiano',   geminiName: 'Italian' },
  de: { labelKo: '독일어',     labelNative: 'Deutsch',    geminiName: 'German' },
  ja: { labelKo: '일본어',     labelNative: '日本語',      geminiName: 'Japanese' },
  fr: { labelKo: '프랑스어',   labelNative: 'Français',   geminiName: 'French' },
}

// (원문, 대상 언어)별 번역 캐시 — 같은 대사가 여러 씬/재시도에서 반복 번역되는 것을 막는다.
// ⚠️ 성공한 번역만 담는다. 실패(키 없음·쿼터 소진)까지 캐싱하면 사용자가 '다시 시도'를 눌러도
// 캐시 히트로 원문이 그대로 나와, 페이지를 새로고침하기 전까지 영영 복구되지 않는다.
const translationCache = new Map<string, Promise<string>>()

/** 텍스트가 어떤 언어로 쓰였는지 문자 체계로 대략 판정한다(비용 0). 번역 실패 시 성우 언어를 맞추는 데 쓴다. */
export function detectTextLocale(text: string): AppLocale {
  if (/[가-힣]/.test(text)) return 'ko'
  if (/[぀-ヿ]/.test(text)) return 'ja'
  if (/[一-鿿]/.test(text)) return 'zh'
  return 'en'
}

/**
 * 대상이 한국어일 때 "번역이 필요한가"를 판정한다.
 * - 한글이 충분히 섞여 있으면 이미 한국어 문장으로 보고 번역 생략(API 호출 0)
 * - 한글이 거의 없으면(영어 위주) 번역 필요 — 한국어 성우가 영어를 읽는 사고를 막는다
 * - 단, 브랜드명·URL·전화번호처럼 짧은 비한글 라인은 원문 표기를 지켜야 하므로 번역하지 않는다
 *   (예: "AirPods Pro", "www.brand.com", "1588-0000" → '에어팟 프로'로 바뀌면 안 된다)
 */
function needsKoreanTranslation(text: string): boolean {
  const t = text.trim()
  const hangul = (t.match(/[가-힣]/g) ?? []).length
  const latin = (t.match(/[A-Za-z]/g) ?? []).length
  if (hangul === 0 && latin === 0) return false            // 숫자·기호만 → 그대로
  const koreanRatio = hangul / (hangul + latin || 1)
  if (koreanRatio >= 0.3) return false                     // 충분히 한국어 문장
  // 한글 비중이 낮아도, 짧은 고유명사/URL/번호 라인은 원문을 지킨다
  const words = t.split(/\s+/).filter(Boolean)
  const looksLikeIdentifier = /^[\w\s.\-/:@+()]+$/.test(t) && words.length <= 2
  return !looksLikeIdentifier
}

/**
 * 씬 텍스트(대사·설명)를 대상 언어로 번역한다.
 *
 * ⚠️ 예전에는 "대상이 한국어면 무조건 원문 그대로"였는데, 이는 원문이 항상 한국어라는 가정에
 * 기댄 것이었다. 광고 파이프라인에서는 영어 제품 자료를 분석하면 AI가 영어 대사를 만들어내는
 * 경우가 있고, 그러면 한국어 음성을 골라도 한국어 성우가 영어 문장을 읽어버린다.
 * 그래서 한국어가 대상일 때는 원문이 실제로 한국어인지 보고, 아니면 번역한다.
 *
 * 번역이 실패해도 원문을 그대로 돌려주어 파이프라인이 멈추지 않게 하되, 성공 여부를 함께
 * 알려준다 — 호출부가 "번역 못 했으니 성우 언어도 원문에 맞춘다" 같은 보정을 할 수 있어야
 * 텍스트와 성우 언어가 어긋난 영상이 조용히 완성되는 것을 막을 수 있다.
 */
export async function translateSceneTextDetailed(
  text: string,
  targetLocale: AppLocale,
): Promise<{ text: string; translated: boolean; skipped: boolean }> {
  if (!text.trim()) return { text, translated: false, skipped: true }
  // 대상이 한국어인데 원문이 이미 한국어(또는 지켜야 할 고유명사)면 번역 불필요
  if (targetLocale === 'ko' && !needsKoreanTranslation(text)) {
    return { text, translated: false, skipped: true }
  }
  // 대상 언어의 문자 체계와 원문이 이미 일치하면(비한국어 대상) 굳이 재번역하지 않는다
  if (targetLocale !== 'ko' && detectTextLocale(text) === targetLocale && targetLocale === 'en') {
    return { text, translated: false, skipped: true }
  }

  const cacheKey = `${targetLocale}::${text}`
  const cached = translationCache.get(cacheKey)
  if (cached) return { text: await cached, translated: true, skipped: false }

  const apiKey = await KeyVault.getKey('gemini')
  if (!apiKey) {
    console.warn(`Gemini 키가 없어 "${targetLocale}" 번역을 건너뜁니다 — 원문 그대로 읽힙니다.`)
    return { text, translated: false, skipped: false }
  }

  const promise = GeminiAdapter.translateText(text, LOCALE_INFO[targetLocale].geminiName, apiKey)
  translationCache.set(cacheKey, promise)
  try {
    return { text: await promise, translated: true, skipped: false }
  } catch (e) {
    // 실패한 결과는 캐시에 남기지 않는다 — 재시도 때 다시 번역할 수 있어야 한다
    translationCache.delete(cacheKey)
    console.warn(`"${targetLocale}" 번역 실패 — 원문 그대로 진행합니다:`, e)
    return { text, translated: false, skipped: false }
  }
}

/** 기존 호출부 호환용 얇은 래퍼 — 번역된 텍스트만 필요할 때 쓴다. */
export async function translateSceneText(text: string, targetLocale: AppLocale): Promise<string> {
  return (await translateSceneTextDetailed(text, targetLocale)).text
}
