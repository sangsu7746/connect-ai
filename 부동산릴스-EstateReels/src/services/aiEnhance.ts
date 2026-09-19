// ════════════════════════════════════════════════════════════════
// (선택) AI로 다듬기 — 오프라인 파서 초안을 Gemini로 보정(타이틀·요약·셀링/투자포인트).
// 키 관리·호출은 gemini.ts를 재사용한다.
// ════════════════════════════════════════════════════════════════
import type { ListingInfo, ConceptId } from '../types'
import { getConcept } from '../utils/estateConcepts'
import { geminiJson } from './gemini'

export { getGeminiKey, setGeminiKey, hasGeminiKey } from './gemini'

export async function enhanceListing(
  rawText: string,
  draft: ListingInfo,
  conceptId: ConceptId,
): Promise<Partial<ListingInfo>> {
  const concept = getConcept(conceptId)
  const prompt = [
    '너는 부동산 홍보 영상 카피라이터다. 아래 블로그 원문과 초안을 바탕으로',
    `"${concept.label}"(${concept.need}) 컨셉에 맞는 매물 정보를 다듬어라.`,
    '과장·허위 금지, 원문에 있는 사실만. 셀링포인트/투자포인트는 짧은 명사구로.',
    '',
    '초안(JSON):',
    JSON.stringify({
      title: draft.title, priceText: draft.priceText, region: draft.region,
      areaText: draft.areaText, station: draft.station, features: draft.features,
      investPoints: draft.investPoints, summary: draft.summary,
    }),
    '',
    '블로그 원문:',
    rawText.slice(0, 6000),
    '',
    '다음 JSON 형식으로만 답해라(한국어, 다른 텍스트 금지):',
    '{"title":"20자 이내 타이틀","summary":"한 줄 요약(35자 이내)",',
    '"features":["셀링포인트1","셀링포인트2","셀링포인트3"],',
    '"investPoints":["투자포인트1","투자포인트2"]}',
  ].join('\n')

  const parsed = await geminiJson<Partial<ListingInfo>>(prompt)
  const patch: Partial<ListingInfo> = {}
  if (typeof parsed.title === 'string' && parsed.title.trim()) patch.title = parsed.title.trim().slice(0, 40)
  if (typeof parsed.summary === 'string' && parsed.summary.trim()) patch.summary = parsed.summary.trim().slice(0, 60)
  if (Array.isArray(parsed.features) && parsed.features.length) patch.features = parsed.features.map(String).slice(0, 6)
  if (Array.isArray(parsed.investPoints) && parsed.investPoints.length) patch.investPoints = parsed.investPoints.map(String).slice(0, 5)
  return patch
}
