import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { type Job, type RenderInfo, type Scene, type Script, deleteRender, getJob,
         getRenders, getScript, patchScene, regenScene, regenSceneImage, startImages,
         startRender } from '../api'

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
  const [renders, setRenders] = useState<RenderInfo[]>([])
  const [renderJob, setRenderJob] = useState<Job | null>(null)
  const imgTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    getScript(sid).then(setScript).catch(e => alert(e))
    getRenders(sid).then(setRenders).catch(() => {})       // 조용히 무시 — 이력 없어도 렌더는 가능
  }, [sid])
  // 언마운트(페이지 이동) 시 대기 중인 폴링 타이머를 정리 — 안 하면 setTimeout이
  // 계속 돌며 언마운트된 컴포넌트에 setState를 시도한다.
  // mount 시 true로 되돌려야 한다 — StrictMode는 effect를 mount→unmount→remount로
  // 두 번 돌리는데, cleanup만 있으면 첫 unmount에서 false가 된 뒤 영영 true로
  // 안 돌아와 폴링이 시작부터 죽는다 (C4).
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      if (imgTimer.current) clearTimeout(imgTimer.current)
    }
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

  const runRender = async () => {
    try {
      const { job_id } = await startRender(sid)
      const poll = async () => {
        try {
          const jb = await getJob(job_id)
          if (!mounted.current) return
          setRenderJob(jb)
          if (jb.status === 'running') {
            imgTimer.current = setTimeout(poll, 1000)
            return
          }
          if (jb.status === 'error') alert(`렌더 실패: ${jb.error}`)
          setRenders(await getRenders(sid))
        } catch (e) {
          if (!mounted.current) return
          setRenderJob(null)
          alert(`렌더 잡 확인 실패: ${e}`)
        }
      }
      poll()
    } catch (e) { alert(`렌더 시작 실패: ${e}`) }
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
        <button disabled={imgJob?.status === 'running' || renderJob?.status === 'running'}
                onClick={() => runImages(false)}>
          {imgJob?.status === 'running'
            ? `🎨 생성 중… ${imgJob.progress}/${imgJob.total}`
            : '🎨 이미지 생성'}
        </button>
        <button className="ghost"
                disabled={imgJob?.status === 'running' || renderJob?.status === 'running'}
                onClick={() => runImages(true)}>전부 재생성</button>
        <button disabled={imgJob?.status === 'running' || renderJob?.status === 'running'}
                onClick={runRender}>
          {renderJob?.status === 'running'
            ? `🎬 렌더 중… ${renderJob.progress}/${renderJob.total}`
            : '🎬 렌더'}
        </button>
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
              <button className="ghost"
                      disabled={busy !== null || imgJob?.status === 'running' ||
                        renderJob?.status === 'running'}
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
      {renders.length > 0 && (
        <>
          <h2>🎬 렌더 결과</h2>
          <video className="preview" controls
                 src={`/videos/${renders[0].file}`} />
          <div className="renders">
            {renders.map(r => (
              <div key={r.id} className="render-row">
                <a href={`/videos/${r.file}`} download>
                  ⬇ {r.file} ({r.duration_sec}초 · {r.created_at})
                </a>
                <button className="ghost" disabled={renderJob?.status === 'running'}
                        onClick={async () => {
                  if (!confirm('이 렌더를 삭제할까요?')) return
                  try {
                    await deleteRender(r.id)
                    setRenders(await getRenders(sid))
                  } catch (e) { alert(`삭제 실패: ${e}`) }
                }}>🗑</button>
              </div>
            ))}
          </div>
        </>
      )}
      <h2>📋 유튜브 설명란 (GEO)</h2>
      <textarea className="desc" readOnly value={script.description_md} rows={10} />
      <button onClick={() => navigator.clipboard.writeText(script.description_md)}>
        복사
      </button>
    </div>
  )
}
