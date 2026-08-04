import { callProxy, geminiTextEndpoint, geminiText, QuotaExhaustedError } from './aiAdapters'
import { KeyVault, useKeysStore } from '../stores/keysStore'
import { sanitizeHomageStructure, HOMAGE_JSON_SCHEMA_HINT } from './homageSchema'
import { parseYoutubeVideoId } from './youtubeService'
import type { HomageStructure } from '../types/homage'

const MIN_DESCRIPTION_LEN = 10

/**
 * 키 미등록을 재시도 스킵 판정에 쓰기 위한 전용 오류 타입.
 * 문자열 메시지 정규식 매칭 대신 instanceof 로 판별해, 나중에 메시지 문구가
 * 바뀌어도(예: 안내문 수정) 재시도 스킵 로직이 조용히 깨지지 않게 한다.
 */
class GeminiKeyMissingError extends Error {}

/** ```json 펜스나 앞뒤 잡소리를 걷어내고 JSON 본문만 남긴다 */
function extractJson(text: string): string {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/)
  const body = fenced ? fenced[1] : text
  const start = body.indexOf('{')
  const end = body.lastIndexOf('}')
  return start >= 0 && end > start ? body.slice(start, end + 1) : body
}

async function runGeminiOnce(parts: unknown[]): Promise<HomageStructure> {
  const apiKey = await KeyVault.getKey('gemini')
  if (!apiKey) throw new GeminiKeyMissingError('Gemini 키가 필요해요. 키 페이지에서 등록해주세요.')

  const data = await callProxy({
    provider: 'gemini',
    apiKey,
    method: 'POST',
    endpoint: await geminiTextEndpoint(apiKey),
    body: {
      contents: [{ parts }],
      generationConfig: { responseMimeType: 'application/json' },
    },
  })
  useKeysStore.getState().updateGeminiUsage('text')

  const text = geminiText(data)
  if (!text) throw new Error(data?.error?.message || '오마주 구조를 분석하지 못했어요.')

  let parsed: unknown
  try {
    parsed = JSON.parse(extractJson(String(text)))
  } catch {
    throw new Error('오마주 구조를 분석하지 못했어요. 다른 영상을 골라보세요.')
  }
  return sanitizeHomageStructure(parsed)
}

/**
 * 1회 재시도한다. LLM 은 같은 입력에도 형식이 흔들려서, 한 번 더 물으면
 * 성공하는 경우가 많다. 두 번 다 실패하면 사용자에게 알리고 선택지를 준다
 * (조용히 템플릿으로 폴백하지 않는다 — 사용자가 명시적으로 고른 모드다).
 *
 * ⚠️ 재시도가 무의미한 오류는 즉시 던진다 — 타입으로 판별한다(문자열 매칭 금지,
 *    메시지 문구가 바뀌면 조용히 깨지는 것을 막기 위해):
 *    - GeminiKeyMissingError: 키 미등록. 재시도해도 똑같이 실패한다.
 *    - QuotaExhaustedError(aiAdapters.ts): 일일 무료 쿼터 소진(Gemini 429/RESOURCE_EXHAUSTED
 *      포함). 이 앱은 하루 요청 수 제한(GEMINI_FREE_TEXT_RPD)이 있어, 쿼터 소진 상태에서
 *      재시도하면 남은 쿼터를 헛되이 태울 뿐 절대 성공하지 않는다.
 */
async function runGemini(parts: unknown[]): Promise<HomageStructure> {
  try {
    return await runGeminiOnce(parts)
  } catch (e) {
    if (e instanceof GeminiKeyMissingError || e instanceof QuotaExhaustedError) throw e
    return await runGeminiOnce(parts)
  }
}

const VIDEO_INSTRUCTION = `
You are analyzing a video advertisement to extract its STRUCTURAL grammar so that a
different product's ad can borrow its rhythm — an homage, not a copy.

Break the ad into its shots. For each shot report only: duration, shot size,
camera movement, what kind of subject fills the frame, the emotional beat it lands,
and how it transitions out.

${HOMAGE_JSON_SCHEMA_HINT}
`.trim()

const DESCRIPTION_INSTRUCTION = `
A user is describing the FEELING and RHYTHM they want for their ad. Turn that
description into a concrete shot structure they can build from.

Infer a sensible number of shots (3-12) from what they describe. If they mention
specific timing ("first 3 seconds", "last 5 seconds"), honor it.

${HOMAGE_JSON_SCHEMA_HINT}
`.trim()

/**
 * 유튜브 영상을 직접 분석해 구조를 뽑는다.
 * Gemini 는 YouTube URL 을 영상 입력으로 직접 받는다(공개 영상만 가능).
 */
export async function analyzeFromVideo(videoId: string): Promise<HomageStructure> {
  const id = parseYoutubeVideoId(videoId)
  if (!id) throw new Error('영상 주소를 알아보지 못했어요.')

  return runGemini([
    { text: VIDEO_INSTRUCTION },
    { fileData: { fileUri: `https://www.youtube.com/watch?v=${id}` } },
  ])
}

/**
 * 원하는 느낌을 글로 적은 것을 같은 구조로 변환한다.
 * 유튜브에 참고할 광고가 없을 때의 입구이며, 영상 입구와 출력 계약이 동일하다.
 */
export async function analyzeFromDescription(text: string): Promise<HomageStructure> {
  const desc = (text || '').trim()
  if (desc.length < MIN_DESCRIPTION_LEN) {
    throw new Error('원하는 느낌을 조금 더 자세히 적어주세요.')
  }
  return runGemini([{ text: `${DESCRIPTION_INSTRUCTION}\n\n---\n사용자 설명:\n${desc}` }])
}
