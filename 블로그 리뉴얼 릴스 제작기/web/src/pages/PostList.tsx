import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Category, type Post, discover, getCategories, getPosts } from '../api'
import PurpleBadge from '../components/PurpleBadge'

const SOURCES = [
  { id: 'all', label: '전체' },
  { id: 'naver', label: 'N 네이버' },
  { id: 'google', label: 'G 구글' },
] as const

export default function PostList() {
  const { id } = useParams()
  const cid = Number(id)
  const [cat, setCat] = useState<Category | null>(null)
  const [posts, setPosts] = useState<Post[]>([])
  const [source, setSource] = useState<string>('all')
  const [busyKw, setBusyKw] = useState<string | null>(null)

  const load = (src = source) => getPosts(cid, src).then(setPosts)
  useEffect(() => {
    getCategories().then(cs => setCat(cs.find(c => c.id === cid) ?? null))
    load()
  }, [cid])

  const keywords = useMemo(() => {
    if (!cat) return []
    const trend = cat.top_keywords.map(t => t.keyword)
    return [...new Set([...trend, ...cat.keywords])]
  }, [cat])

  const onDiscover = async (kw: string) => {
    setBusyKw(kw)
    try { await discover(cid, kw); await load() }
    catch (e) { alert(`수집 실패: ${e}`) }
    finally { setBusyKw(null) }
  }

  return (
    <div className="page">
      <h1><Link to="/">←</Link> {cat?.emoji} {cat?.name} 블로그 리스트</h1>
      <div className="chips">
        {keywords.map(kw => (
          <button key={kw} className="ghost" disabled={busyKw !== null}
                  onClick={() => onDiscover(kw)}>
            {busyKw === kw ? '수집 중…' : `🔍 ${kw}`}
          </button>
        ))}
      </div>
      <div className="tabs">
        {SOURCES.map(s => (
          <button key={s.id} className={source === s.id ? 'active ghost' : 'ghost'}
                  onClick={() => { setSource(s.id); load(s.id) }}>
            {s.label}
          </button>
        ))}
      </div>
      {posts.length === 0 && <p>키워드를 눌러 상위 글을 수집하세요.</p>}
      {posts.map(p => (
        <div className="post" key={p.id}>
          <PurpleBadge score={p.score} verdict={p.verdict} />
          <div>
            <h3>
              <span className={`src ${p.source}`}>
                {p.source === 'naver' ? 'N' : 'G'}
              </span>
              <a href={p.url} target="_blank" rel="noreferrer">{p.title}</a>
            </h3>
            <p>{p.summary}</p>
            {p.hooks.length > 0 && <div className="hooks">🪝 {p.hooks[0]}</div>}
          </div>
        </div>
      ))}
    </div>
  )
}
