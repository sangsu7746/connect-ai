import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Job, type Scene, type Script, getJob, getScript, patchScene,
         regenScene, regenSceneImage, startImages } from '../api'

const ROLE_LABEL: Record<string, string> = {
  hook: '훅', summary: '요약', chapter: '챕터', point: '포인트',
  twist: '반전', cta: 'CTA',
}

export default function Storyboard() {
  const { id } = useParams()
  const sid = Number(id)
  const [script, setScript] = useState<Script | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [imgJob, setImgJob] = useState<Job | null>(null)
  const imgTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mounted = useRef(true)

  useEffect(() => { getScript(sid).then(setScript).catch(e => alert(e)) }, [sid])
  // 언마운트(페이지 이동) 시 대기 중인 폴링 타이머를 정리 — 안 하면 setTimeout이
  // 계속 돌며 언마운트된 컴포넌트에 setState를 시도한다.
  useEffect(() => () => {
    mounted.current = false
    if (imgTimer.current) clearTimeout(imgTimer.current)
  }, [])
  if (!script) return <div className="page">불러오는 중…</div>

  const runImages = async (force = false) => {
    try {
      const { job_id } = await startImages(sid, force)
      const poll = async () => {
        try {
          const jb = await getJob(job_id)
          if (!mounted.current) return
          setImgJob(jb)
          if (jb.status === 'running') { imgTimer.current = setTimeout(poll, 1000); return }
          if (jb.status === 'error') alert(`이미지 생성 실패: ${jb.error}`)
          setScript(await getScript(sid))
        } catch (e) {
          if (!mounted.current) return
          setImgJob(null)
          alert(`이미지 잡 확인 실패: ${e}`)
        }
      }
      poll()
    } catch (e) { alert(`이미지 생성 시작 실패: ${e}`) }
  }

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
      <div className="make-bar">
        <button disabled={imgJob?.status === 'running'}
                onClick={() => runImages(false)}>
          {imgJob?.status === 'running'
            ? `🎨 생성 중… ${imgJob.progress}/${imgJob.total}`
            : '🎨 이미지 생성'}
        </button>
        <button className="ghost" disabled={imgJob?.status === 'running'}
                onClick={() => runImages(true)}>전부 재생성</button>
      </div>
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
          {s.image_file && (
            <div className="scene-img">
              <img src={`/images/${s.image_file}`} alt="" loading="lazy" />
              {s.image_fallback && <span className="fb-badge">⚠ 폴백</span>}
              <button className="ghost" disabled={busy !== null || imgJob?.status === 'running'}
                      onClick={async () => {
                        try {
                          const ns = await regenSceneImage(sid, s.idx)
                          setScript(prev => prev && { ...prev,
                            scenes: prev.scenes.map(x => x.idx === s.idx ? ns : x) })
                        } catch (e) { alert(`재생성 실패: ${e}`) }
                      }}>🖼 재생성</button>
            </div>
          )}
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
