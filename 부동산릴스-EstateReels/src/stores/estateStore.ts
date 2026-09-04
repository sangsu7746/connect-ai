// ════════════════════════════════════════════════════════════════
// 제작 위저드 전역 상태
//  [1] 홈 → [2] 블로그 가져오기 → [3] 매물정보 확인·편집 → [4] 컨셉·길이
//   → [5] 제작(합성) → [6] 결과
// ════════════════════════════════════════════════════════════════
import { create } from 'zustand'
import type { BlogSource, BlogImage, ListingInfo, RenderConfig, Storyboard, RenderOutput, EstateScene } from '../types'
import { emptyListing } from '../types'
import type { Marketing } from '../utils/hooks'

const DEFAULT_CONFIG: RenderConfig = {
  conceptId: 'transit',
  duration: 30,
  aspect: '9:16',
  subtitles: true,
  narration: false,
  voice: 'female',
  showContact: true,
  aiMode: true,     // Gemini 키가 있으면 AI 자동 구성(스토리·이미지분석·배치) 사용
}

interface EstateState {
  source: BlogSource | null
  images: BlogImage[]
  listing: ListingInfo
  config: RenderConfig
  storyboard: Storyboard | null
  result: RenderOutput | null
  marketing: Marketing | null
  renderCount: number   // 이 프로젝트(영상)에서 제작한 횟수 — 무료 제작 한도 판별

  setImport: (source: BlogSource, images: BlogImage[]) => void
  bumpRenderCount: () => void
  addImages: (imgs: BlogImage[]) => void
  removeImage: (id: string) => void
  toggleImage: (id: string) => void
  moveImage: (id: string, dir: -1 | 1) => void
  setPastedSource: (title: string, text: string) => void

  setListing: (patch: Partial<ListingInfo>) => void
  setListingArray: (field: 'schools' | 'amenities' | 'features' | 'investPoints', values: string[]) => void

  setConfig: (patch: Partial<RenderConfig>) => void
  setImageAnalysis: (tags: { id: string; category: import('../types').ImageCategory; note: string }[]) => void
  setStoryboard: (sb: Storyboard | null) => void
  updateScene: (id: string, patch: Partial<EstateScene>) => void
  addScene: (afterId?: string) => void   // 새 컷 추가(afterId 뒤에, 없으면 맨 끝)
  removeScene: (id: string) => void      // 컷 삭제(최소 1개 유지)
  setResult: (r: RenderOutput | null) => void
  setMarketing: (m: Marketing | null) => void
  selectedImages: () => BlogImage[]
  reset: () => void
}

export const useEstateStore = create<EstateState>()((set, get) => ({
  source: null,
  images: [],
  listing: emptyListing(),
  config: DEFAULT_CONFIG,
  storyboard: null,
  result: null,
  marketing: null,
  renderCount: 0,

  // 새 블로그를 가져오면 새 프로젝트 → 제작 횟수·결과 초기화
  setImport: (source, images) => set({ source, images, renderCount: 0, result: null }),
  bumpRenderCount: () => set(s => ({ renderCount: s.renderCount + 1 })),
  addImages: (imgs) => set(s => ({ images: [...s.images, ...imgs] })),
  removeImage: (id) => set(s => ({ images: s.images.filter(i => i.id !== id) })),
  toggleImage: (id) => set(s => ({ images: s.images.map(i => i.id === id ? { ...i, selected: !i.selected } : i) })),
  moveImage: (id, dir) => set(s => {
    const arr = [...s.images]
    const idx = arr.findIndex(i => i.id === id)
    const j = idx + dir
    if (idx < 0 || j < 0 || j >= arr.length) return {}
    ;[arr[idx], arr[j]] = [arr[j], arr[idx]]
    return { images: arr }
  }),
  setPastedSource: (title, text) =>
    set({ source: { url: '', title, rawText: text, fetchedVia: 'paste' } }),

  setListing: (patch) => set(s => ({ listing: { ...s.listing, ...patch } })),
  setListingArray: (field, values) => set(s => ({ listing: { ...s.listing, [field]: values } })),

  setConfig: (patch) => set(s => ({ config: { ...s.config, ...patch } })),
  setImageAnalysis: (tags) => set(s => {
    const map = new Map(tags.map(t => [t.id, t]))
    return { images: s.images.map(im => map.has(im.id) ? { ...im, category: map.get(im.id)!.category, note: map.get(im.id)!.note } : im) }
  }),
  setStoryboard: (storyboard) => set({ storyboard }),
  updateScene: (id, patch) => set(s => s.storyboard
    ? { storyboard: { ...s.storyboard, scenes: s.storyboard.scenes.map(sc => sc.id === id ? { ...sc, ...patch } : sc) } }
    : {}),
  addScene: (afterId) => set(s => {
    if (!s.storyboard) return {}
    const scenes = [...s.storyboard.scenes]
    const avg = scenes.length ? scenes.reduce((a, sc) => a + sc.duration, 0) / scenes.length : 4
    const KB: EstateScene['kenBurns'][] = ['in', 'left', 'out', 'right', 'up']
    const nid = `sc_e_${Date.now().toString(36)}_${Math.floor(Math.random() * 46656).toString(36)}`
    const fresh: EstateScene = {
      id: nid, seq: 0, role: 'point', photoId: null,
      caption: '', sub: '', badge: undefined, narration: '',
      duration: Math.max(2.2, Math.round(avg * 10) / 10 || 4),
      kenBurns: KB[scenes.length % KB.length],
    }
    const idx = afterId ? scenes.findIndex(sc => sc.id === afterId) : -1
    if (idx >= 0) scenes.splice(idx + 1, 0, fresh); else scenes.push(fresh)
    const reseq = scenes.map((sc, i) => ({ ...sc, seq: i }))
    return { storyboard: { ...s.storyboard, scenes: reseq, totalSec: Math.round(reseq.reduce((a, sc) => a + sc.duration, 0)) } }
  }),
  removeScene: (id) => set(s => {
    if (!s.storyboard) return {}
    const scenes = s.storyboard.scenes.filter(sc => sc.id !== id)
    if (scenes.length === 0) return {}   // 최소 1개 컷은 유지
    const reseq = scenes.map((sc, i) => ({ ...sc, seq: i }))
    return { storyboard: { ...s.storyboard, scenes: reseq, totalSec: Math.round(reseq.reduce((a, sc) => a + sc.duration, 0)) } }
  }),
  setResult: (result) => set({ result }),
  setMarketing: (marketing) => set({ marketing }),
  selectedImages: () => get().images.filter(i => i.selected),

  reset: () => set({
    source: null, images: [], listing: emptyListing(),
    config: DEFAULT_CONFIG, storyboard: null, result: null, marketing: null, renderCount: 0,
  }),
}))
