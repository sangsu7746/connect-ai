import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Scene, type Script, getScript, patchScene, regenScene } from '../api'

const ROLE_LABEL: Record<string, string> = {
  hook: '훅', summary: '요약', chapter: '챕터', point: '포인트',
  twist: '반전', cta: 'CTA',
}

export default function Storyboard() {
  const { id } = useParams()
  const sid = Number(id)
  const [script, setScript] = useState<Script | null>(null)
  const [busy, setBusy] = useState<number | null>(null)

  useEffect(() => { getScript(sid).then(setScript).catch(e => alert(e)) }, [sid])
  if (!script) return <div className="page">불러오는 중…</div>

  const save = async (idx: number, patch: Partial<Scene>) => {
    try {
      const { warnings, ...s } = await patchScene(sid, idx, patch)
      if (warnings && warnings.length) alert('⚠ 게이트 경고:\n' + warnings.join('\n'))
      setScript(prev => prev && { ...prev, scenes: prev.scenes.map(x => x.idx === idx ? s : x) })
    } catch (e) { alert(`저장 실패: ${e}`) }
  }
  const regen = async (idx: number) => {
    setBusy(idx)
    try {
      const s = await regenScene(sid, idx)
      setScript(prev => prev && { ...prev, scenes: prev.scenes.map(x => x.idx === idx ? s : x) })
    } catch (e) { alert(`재생성 실패: ${e}`) }
    finally { setBusy(null) }
  }

  return (
    <div className="page">
      <h1><Link to={`/category/${script.category_id}`}>←</Link> 스토리보드
        <span className="meta">{script.fmt === 'reels' ? '릴스' : '롱폼'} ·
          {' '}{script.duration_sec}초 · 진단 {script.diag.score}/4 {script.diag.verdict}</span>
      </h1>
      {script.scenes.map(s => (
        <div className={`scene role-${s.role}`} key={s.idx}>
          <div className="scene-head">
            <span>#{s.idx} {ROLE_LABEL[s.role] ?? s.role}
              {s.chapter && s.role !== 'chapter' ? ` · ${s.chapter}` : ''}</span>
            <span>{s.sec}s</span>
            {s.role !== 'chapter' &&
              <button className="ghost" disabled={busy !== null}
                      onClick={() => regen(s.idx)}>
                {busy === s.idx ? '재생성 중…' : '♻ AI 재생성'}
              </button>}
          </div>
          <input key={`c${s.idx}:${s.caption}`} defaultValue={s.caption}
                 maxLength={18} placeholder="자막(≤18자)"
                 onBlur={e => e.target.value !== s.caption &&
                   save(s.idx, { caption: e.target.value })} />
          <textarea key={`n${s.idx}:${s.narration}`} defaultValue={s.narration}
                    placeholder="나레이션" rows={2}
                    onBlur={e => e.target.value !== s.narration &&
                      save(s.idx, { narration: e.target.value })} />
        </div>
      ))}
      <h2>📋 유튜브 설명란 (GEO)</h2>
      <textarea className="desc" readOnly value={script.description_md} rows={10} />
      <button onClick={() => navigator.clipboard.writeText(script.description_md)}>
        복사
      </button>
    </div>
  )
}
