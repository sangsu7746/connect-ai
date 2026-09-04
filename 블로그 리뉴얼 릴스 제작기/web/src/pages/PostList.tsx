import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { type Category, type Post, createArticle, createScript, discover, getCategories, getPosts } from '../api'
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
  const [picked, setPicked] = useState<number[]>([])
  const [fmt, setFmt] = useState<'reels' | 'long'>('reels')
  const [dur, setDur] = useState(30)
  const [making, setMaking] = useState(false)
  const nav = useNavigate()

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
      {picked.length > 0 && (
        <div className="make-bar">
          <b>{picked.length}개 선택</b>
          <select value={`${fmt}:${dur}`} onChange={e => {
            const [f, d] = e.target.value.split(':')
            setFmt(f as 'reels' | 'long'); setDur(Number(d))
          }}>
            <option value="reels:30">릴스 30초</option>
            <option value="reels:60">릴스 60초</option>
            <option value="long:60">롱폼 1분</option>
            <option value="long:180">롱폼 3분</option>
            <option value="long:300">롱폼 5분</option>
            <option value="long:600">롱폼 10분</option>
          </select>
          <button disabled={making} onClick={async () => {
            setMaking(true)
            try {
              const { id } = await createScript(cid, picked, fmt, dur)
              nav(`/script/${id}`)
            } catch (e) { alert(`대본 생성 실패: ${e}`) }
            finally { setMaking(false) }
          }}>{making ? '생성 중… (수십 초)' : '🎬 대본 만들기'}</button>
          <button className="ghost" disabled={making} onClick={async () => {
            setMaking(true)
            try {
              const { id } = await createArticle(cid, picked)
              nav(`/article/${id}`)
            } catch (e) { alert(`글 생성 실패: ${e}`) }
            finally { setMaking(false) }
          }}>📝 블로그 글 만들기</button>
        </div>
      )}
      {posts.length === 0 && <p>키워드를 눌러 상위 글을 수집하세요.</p>}
      {posts.map(p => (
        <div className="post" key={p.id}>
          <input type="checkbox" checked={picked.includes(p.id)}
                 onChange={e => setPicked(e.target.checked
                   ? [...picked, p.id] : picked.filter(x => x !== p.id))} />
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
