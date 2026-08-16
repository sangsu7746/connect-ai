import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Article, getArticle, patchArticle, publishArticle } from '../api'

export default function ArticlePage() {
  const { id } = useParams()
  const aid = Number(id)
  const [article, setArticle] = useState<Article | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => { getArticle(aid).then(setArticle).catch(e => alert(e)) }, [aid])
  if (!article) return <div className="page">불러오는 중…</div>

  const save = async (patch: { title?: string; body_md?: string }) => {
    try { setArticle(await patchArticle(aid, patch)) }
    catch (e) { alert(`저장 실패: ${e}`) }
  }

  const publish = async (platform: string) => {
    if (platform === 'naver' && !confirm(
      '네이버는 즉시 공개 발행됩니다. 되돌리려면 블로그에서 직접 삭제해야 합니다.\n계속할까요?'
    )) return
    setBusy(platform)
    try {
      const r = await publishArticle(aid, platform)
      alert(`발행 완료: ${r.url || '(URL 미확인 — 블로그 관리에서 확인)'}`)
      setArticle(await getArticle(aid))
    } catch (e) {
      const msg = String(e)
      if (msg.includes('409') &&
          confirm(`게이트 경고가 있습니다.\n${msg}\n무시하고 발행할까요?`)) {
        try {
          const r = await publishArticle(aid, platform, true)
          alert(`발행 완료: ${r.url || ''}`)
          setArticle(await getArticle(aid))
        } catch (e2) { alert(`발행 실패: ${e2}`) }
      } else { alert(`발행 실패: ${msg}`) }
    } finally { setBusy(null) }
  }

  return (
    <div className="page">
      <h1><Link to={`/category/${article.category_id}`}>←</Link> 블로그 글
        <span className="meta">{article.status === 'published' ? '발행됨' : '초안'}</span>
      </h1>
      <input key={`t:${article.title}`} defaultValue={article.title} maxLength={32}
             placeholder="제목(≤32자)"
             onBlur={e => e.target.value !== article.title &&
               save({ title: e.target.value })} />
      <textarea key={`b:${article.body_md}`} className="desc"
                defaultValue={article.body_md} rows={22}
                onBlur={e => e.target.value !== article.body_md &&
                  save({ body_md: e.target.value })} />
      {article.warnings.length > 0 && (
        <div className="warn-panel">
          <b>⚠ 게이트 경고 {article.warnings.length}건</b>
          {article.warnings.map((w, i) => <div key={i}>{w}</div>)}
        </div>
      )}
      <div className="make-bar">
        <button disabled={busy !== null} onClick={() => publish('naver')}>
          {busy === 'naver' ? '발행 중…' : 'N 네이버 발행(즉시 공개)'}
        </button>
        <button disabled={busy !== null} onClick={() => publish('tistory')}>
          {busy === 'tistory' ? '발행 중…' : 'T 티스토리 발행(비공개)'}
        </button>
        {Object.entries(article.published_urls).map(([p, u]) => (
          u
            ? <a key={p} href={u} target="_blank" rel="noreferrer">🔗 {p}</a>
            : <span key={p}>🔗 {p} (URL 미확인)</span>
        ))}
      </div>
      <p className="meta">발행은 수 분 걸릴 수 있습니다. 세션이 만료됐으면 브라우저
        창이 열립니다 — 직접 로그인하면 이어서 발행됩니다. 네이버는 즉시 공개,
        티스토리는 비공개로 올라가며 공개 전환은 블로그 관리에서 직접 합니다.</p>
    </div>
  )
}
