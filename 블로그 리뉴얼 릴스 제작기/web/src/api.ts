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
export const refreshTrends = (cid: number) =>
  fetch(`/api/categories/${cid}/trends/refresh`, { method: 'POST' })
    .then(r => j<TrendRow[]>(r))
export const discover = (cid: number, keyword: string) =>
  fetch(`/api/categories/${cid}/discover`, { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ keyword }) }).then(r => j<{ count: number }>(r))
export const getPosts = (cid: number, source: string) =>
  fetch(`/api/categories/${cid}/posts?source=${source}`).then(r => j<Post[]>(r))
