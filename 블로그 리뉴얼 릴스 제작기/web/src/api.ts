export interface TrendRow { keyword: string; rise_pct: number }
export interface Category {
  id: number; name: string; emoji: string
  keywords: string[]; top_keywords: TrendRow[]
}
export interface Post {
  id: number; source: 'naver' | 'google'; title: string; url: string
  summary: string; blogger: string; posted_at: string; keyword: string
  score: number | null; verdict: string | null; hooks: string[]
}

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}
export const getCategories = () =>
  fetch('/api/categories').then(r => j<Category[]>(r))
export const addCategory = (name: string) =>
  fetch('/api/categories', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }) }).then(r => j<{ id: number }>(r))
export const addKeyword = (cid: number, keyword: string) =>
  fetch(`/api/categories/${cid}/keywords`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword }) }).then(r => j<{ ok: boolean }>(r))
export const deleteKeyword = (cid: number, keyword: string) =>
  fetch(`/api/categories/${cid}/keywords/${encodeURIComponent(keyword)}`,
    { method: 'DELETE' }).then(r => j<{ ok: boolean }>(r))
export const refreshTrends = (cid: number) =>
  fetch(`/api/categories/${cid}/trends/refresh`, { method: 'POST' })
    .then(r => j<TrendRow[]>(r))
export const discover = (cid: number, keyword: string) =>
  fetch(`/api/categories/${cid}/discover`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword }) }).then(r => j<{ count: number }>(r))
export const getPosts = (cid: number, source: string) =>
  fetch(`/api/categories/${cid}/posts?source=${source}`).then(r => j<Post[]>(r))

export interface Scene {
  idx: number; role: string; sec: number; chapter: string
  caption: string; sub: string; narration: string; image_prompt: string
  image_file?: string; image_fallback?: boolean
}
export interface Script {
  id: number; category_id: number; fmt: string; duration_sec: number
  scenes: Scene[]; description_md: string; post_ids: number[]
  chapters: string[]; diag: { score: number; verdict: string; hooks: string[] }
  fact_sheet: { fact: string; source_title: string; source_url: string }[]
}
export const createScript = (category_id: number, post_ids: number[],
                             fmt: string, duration: number) =>
  fetch('/api/scripts', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category_id, post_ids, fmt, duration }) })
    .then(r => j<{ id: number }>(r))
export const getScript = (id: number) =>
  fetch(`/api/scripts/${id}`).then(r => j<Script>(r))
export const patchScene = (sid: number, idx: number, body: Partial<Scene>) =>
  fetch(`/api/scripts/${sid}/scenes/${idx}`, { method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }).then(r => j<Scene & { warnings?: string[] }>(r))
export const regenScene = (sid: number, idx: number) =>
  fetch(`/api/scripts/${sid}/scenes/${idx}/regen`, { method: 'POST' })
    .then(r => j<Scene>(r))

export interface Article {
  id: number; category_id: number; title: string; body_md: string
  warnings: string[]; status: 'draft' | 'published'
  published_urls: Record<string, string>; post_ids: number[]; created_at: string
}
export const createArticle = (category_id: number, post_ids: number[]) =>
  fetch('/api/articles', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ category_id, post_ids }) }).then(r => j<{ id: number }>(r))
export const getArticle = (id: number) =>
  fetch(`/api/articles/${id}`).then(r => j<Article>(r))
export const patchArticle = (id: number, body: { title?: string; body_md?: string }) =>
  fetch(`/api/articles/${id}`, { method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }).then(r => j<Article>(r))
export const publishArticle = (id: number, platform: string, force = false) =>
  fetch(`/api/articles/${id}/publish`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ platform, force }) }).then(r => j<{ ok: boolean; url: string }>(r))

export interface Job {
  id: number; kind: string; status: 'running' | 'done' | 'error'
  progress: number; total: number; error: string
}
export const startImages = (sid: number, force = false) =>
  fetch(`/api/scripts/${sid}/images`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force }) }).then(r => j<{ job_id: number }>(r))
export const getJob = (id: number) =>
  fetch(`/api/jobs/${id}`).then(r => j<Job>(r))
export const regenSceneImage = (sid: number, idx: number) =>
  fetch(`/api/scripts/${sid}/scenes/${idx}/image`, { method: 'POST' })
    .then(r => j<Scene>(r))
