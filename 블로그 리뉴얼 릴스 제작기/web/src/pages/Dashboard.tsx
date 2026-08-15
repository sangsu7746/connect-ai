import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { type Category, getCategories, addCategory, refreshTrends } from '../api'

export default function Dashboard() {
  const [cats, setCats] = useState<Category[]>([])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState<number | null>(null)

  const load = () => getCategories().then(setCats)
  useEffect(() => { load() }, [])

  const onRefresh = async (cid: number) => {
    setBusy(cid)
    try { await refreshTrends(cid); await load() }
    catch (e) { alert(`트렌드 갱신 실패: ${e}`) }
    finally { setBusy(null) }
  }

  return (
    <div className="page">
      <h1>📋 카테고리</h1>
      <div className="cards">
        {cats.map(c => (
          <div className="card" key={c.id}>
            <Link to={`/category/${c.id}`} className="card-title">
              {c.emoji} {c.name}
            </Link>
            <div className="chips">
              {(c.top_keywords.length ? c.top_keywords
                : c.keywords.slice(0, 5).map(k => ({ keyword: k, rise_pct: 0 })))
                .map(t => (
                  <span className="chip" key={t.keyword}>
                    {t.keyword}
                    {t.rise_pct !== 0 &&
                      <em className={t.rise_pct > 0 ? 'up' : 'down'}>
                        {t.rise_pct > 0 ? '▲' : '▼'}{Math.abs(t.rise_pct)}%
                      </em>}
                  </span>
                ))}
            </div>
            <button onClick={() => onRefresh(c.id)} disabled={busy === c.id}>
              {busy === c.id ? '갱신 중…' : '🔄 트렌드 갱신'}
            </button>
          </div>
        ))}
      </div>
      <div className="add-row">
        <input value={name} placeholder="새 카테고리 이름"
               onChange={e => setName(e.target.value)} />
        <button onClick={async () => {
          if (!name.trim()) return
          await addCategory(name.trim()); setName(''); load()
        }}>+ 추가</button>
      </div>
    </div>
  )
}
