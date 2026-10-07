// ════════════════════════════════════════════════════════════════
// 스토리보드 생성 — (매물정보 + 컨셉 + 길이 + 선택 사진) → 씬 시퀀스
// 블로그의 사진이 각 씬의 배경이 되고, 컨셉이 정한 문구가 그 위에 얹힌다.
// 길이(30/60/180초)에 맞춰 씬 개수와 각 컷 길이를 자동 배분한다.
// ════════════════════════════════════════════════════════════════
import type { EstateScene, Storyboard, ListingInfo, DurationSec, Aspect, KenBurns, RenderConfig, AiScene, BlogImage, ImageCategory } from '../types'
import { getConcept, buildConceptPoints } from './estateConcepts'
import { buildHookLines, buildBadges } from './hooks'
import { buildSceneNarration, ensureDistinct } from './narration'

const KB_CYCLE: KenBurns[] = ['in', 'left', 'out', 'right', 'up', 'in', 'right', 'left']

// 길이별 목표 컷 수와 평균 컷 길이 — 3분은 컷을 길게 잡아 과하게 쪼개지지 않게 한다
function planCounts(duration: DurationSec): { scenes: number; avg: number } {
  switch (duration) {
    case 30:  return { scenes: 7,  avg: 4.3 }
    case 60:  return { scenes: 13, avg: 4.6 }
    case 180: return { scenes: 26, avg: 6.9 }
  }
}

let seq = 0
const sid = () => `sc_${Date.now().toString(36)}_${(seq++).toString(36)}`

export function buildStoryboard(
  info: ListingInfo,
  config: RenderConfig,
  photoIds: string[],
): Storyboard {
  seq = 0
  const def = getConcept(config.conceptId)
  const { scenes: targetScenes } = planCounts(config.duration)

  const points = buildConceptPoints(def, info)
  const hook = def.hook(info)
  const cta = def.cta(info)

  // 컨텐츠 컷 개수 = 목표 - (hook + cta)
  const contentCount = Math.max(3, targetScenes - 2)

  // 컨텐츠 포인트가 부족하면 컨셉 보이스 라인으로 부드럽게 채운다(사진 쇼케이스 컷)
  const fillers = Array.from(new Set(Object.values(def.voice).filter(Boolean) as string[]))
  const contentPts: { main: string; sub?: string; badge?: string }[] = []
  for (let i = 0; i < contentCount; i++) {
    if (i < points.length) {
      const p = points[i]
      contentPts.push({ main: p.main, sub: p.sub, badge: p.badge })
    } else {
      // 포인트 소진 후: 남은 사진을 요약/보이스 문구와 함께 계속 보여준다
      const soft = fillers.length ? fillers[i % fillers.length] : info.summary
      contentPts.push({ main: info.title || info.region || '이 매물의 매력', sub: soft })
    }
  }

  // 씬 골격 만들기
  const raw: Omit<EstateScene, 'id' | 'seq' | 'photoId' | 'duration' | 'kenBurns'>[] = []
  // 오프닝은 검증된 "이기는 훅"으로 — 밋밋한 정보 나열 대신 스크롤을 멈추는 첫 문장
  const strongHook = buildHookLines(info, config.conceptId)[0] || hook.main
  const hookBadge = buildBadges(info, config.conceptId)[0] || def.hookBadge
  // 자막(caption 사실 + sub 이점)은 화면에 그대로 두고, 나레이션은 이를 "되풀이하지 않는"
  // 음성 대사로 별도 생성한다(buildSceneNarration): 훅=도입멘트, 포인트=이점 문장, CTA=문의안내.
  // → 화면 메인 자막(사실)이 음성으로 반복되지 않아 중복이 사라진다.
  raw.push({ role: 'hook', caption: strongHook, sub: hook.sub, badge: hookBadge, narration: buildSceneNarration('hook', strongHook, hook.sub, info, config.conceptId, 0) })
  let pIdx = 0
  for (const p of contentPts) {
    raw.push({ role: 'point', caption: p.main, sub: p.sub, badge: p.badge, narration: buildSceneNarration('point', p.main, p.sub, info, config.conceptId, pIdx++) })
  }
  const ctaSub = config.showContact && info.contact ? info.contact : cta.sub
  raw.push({ role: 'cta', caption: cta.main, sub: ctaSub, badge: undefined, narration: buildSceneNarration('cta', cta.main, ctaSub, info, config.conceptId, 0) })

  // 사진 배정 — 연속 컷이 다른 사진이 되도록 순환 배정. 사진 없으면 null(그라디언트 카드)
  const ring = photoIds.length ? photoIds : []
  const scenes: EstateScene[] = raw.map((r, i) => ({
    ...r,
    id: sid(),
    seq: i,
    photoId: ring.length ? ring[i % ring.length] : null,
    duration: 0,          // 아래에서 배분
    kenBurns: KB_CYCLE[i % KB_CYCLE.length],
  }))

  const total = distributeDurations(scenes, config.duration)

  return { conceptId: config.conceptId, aspect: config.aspect, totalSec: total, scenes }
}

// 길이 배분 — hook/cta에 가중치를 더 주고 총합을 duration에 맞춘다(최소 2.2초). 반환=실제 총합.
function distributeDurations(scenes: EstateScene[], duration: number): number {
  const weightOf = (role: EstateScene['role']) => (role === 'hook' ? 1.35 : role === 'cta' ? 1.45 : 1)
  const totalW = scenes.reduce((s, sc) => s + weightOf(sc.role), 0)
  let acc = 0
  scenes.forEach((sc, i) => {
    let d = (weightOf(sc.role) / totalW) * duration
    d = Math.max(2.2, Math.round(d * 10) / 10)
    if (i === scenes.length - 1) d = Math.max(2.2, Math.round((duration - acc) * 10) / 10)
    sc.duration = d
    acc += d
  })
  return Math.round(acc)
}

/** 보유 사진의 카테고리별 개수 — AI 스크립트 프롬프트에 넘겨 실제 사진에 맞춰 구성하게 한다. */
export function imageSummary(images: BlogImage[]): Partial<Record<ImageCategory, number>> {
  const s: Partial<Record<ImageCategory, number>> = {}
  for (const im of images) { const c = im.category || '기타'; s[c] = (s[c] || 0) + 1 }
  return s
}

/**
 * AI 스토리보드 — Gemini 스크립트(AiScene[]) + 분석된 사진 카테고리로 씬을 만들고,
 * 각 컷의 wantCategory에 맞는 사진을 우선 배치한다(임의 순서로 올린 사진도 알맞게 배치됨).
 */
export function buildStoryboardAI(config: RenderConfig, script: AiScene[], images: BlogImage[], info: ListingInfo): Storyboard {
  seq = 0
  const def = getConcept(config.conceptId)
  const used = new Set<string>()
  let cycle = 0
  const pick = (want?: ImageCategory): string | null => {
    if (want) {
      const m = images.find(im => !used.has(im.id) && im.category === want)
      if (m) { used.add(m.id); return m.id }
    }
    const any = images.find(im => !used.has(im.id))
    if (any) { used.add(any.id); return any.id }
    if (!images.length) return null
    return images[cycle++ % images.length].id // 소진 후에는 순서대로 순환(항상 첫 장 반환 버그 방지)
  }

  let pIdx = 0
  const scenes: EstateScene[] = script.map((s, i) => ({
    id: sid(), seq: i, role: s.role,
    photoId: pick(s.wantCategory),
    caption: s.caption,
    sub: s.sub,
    badge: s.role === 'hook' ? def.hookBadge : undefined,
    // AI 대사가 자막을 그대로 읽으면 겹치지 않는 대사로 교체(자막≠나레이션 보장)
    narration: ensureDistinct(s.role, s.caption, s.sub, s.narration, info, config.conceptId, s.role === 'point' ? pIdx++ : 0),
    duration: 0,
    kenBurns: KB_CYCLE[i % KB_CYCLE.length],
  }))

  const total = distributeDurations(scenes, config.duration)
  return { conceptId: config.conceptId, aspect: config.aspect, totalSec: total, scenes }
}

// 미리보기용 — 컨셉/길이만으로 예상 컷 수를 알려준다(사진 배정 전)
export function estimateSceneCount(duration: DurationSec): number {
  return planCounts(duration).scenes
}

// 렌더 해상도 — 브라우저 wasm(단일스레드) 인코딩 속도를 고려한 720급.
// 소셜/릴스·유튜브는 어차피 재압축하므로 720이 화질·속도 균형점이다(1080 대비 픽셀 ~2.5배↓).
export function aspectDims(aspect: Aspect): { w: number; h: number } {
  switch (aspect) {
    case '9:16': return { w: 720, h: 1280 }
    case '1:1':  return { w: 800, h: 800 }
    case '16:9': return { w: 1280, h: 720 }
  }
}
