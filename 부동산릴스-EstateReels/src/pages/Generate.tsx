// ════════════════════════════════════════════════════════════════
// 제작(렌더) — 편집이 끝난 스토리보드를 "그대로" 영상으로 합성한다.
//   구성(AI 스크립트·마케팅·훅통일)은 /storyboard(대본 편집)에서 끝났다.
//   여기선: ffmpeg 로드 → 씬별 클립(자막·워터마크 굽기) → 나레이션 TTS → BGM 병합.
//   나레이션 TTS는 "편집된 나레이션 문구"를 읽는다(자막과 별개).
// ════════════════════════════════════════════════════════════════
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, AlertTriangle, Film, RotateCcw } from 'lucide-react'
import { useEstateStore } from '../stores/estateStore'
import { getConcept } from '../utils/estateConcepts'
import { aspectDims } from '../utils/storyboard'
import { FFmpegService, type VoiceClip } from '../services/ffmpegService'
import { renderCaptionOverlay, renderGradientBg, renderCornerLabel } from '../services/captionCanvas'
import { resolveBgmUrl } from '../services/bgmService'
import { hasGeminiKey, synthesizeTTS } from '../services/gemini'
import { makeVideoId } from '../services/credits'

export default function Generate() {
  const nav = useNavigate()
  const store = useEstateStore()
  const { storyboard, images, listing, config, result, setResult } = store
  const [pct, setPct] = useState(2)
  const [status, setStatus] = useState('준비 중…')
  const [error, setError] = useState('')
  const started = useRef(false)

  useEffect(() => {
    // 완성된 결과가 이미 있으면(예: /result에서 뒤로가기로 재진입) 재렌더하지 않고 결과로 보낸다.
    // 새 제작은 Storyboard의 "영상 만들기"가 setResult(null)로 초기화하므로 이 가드에 걸리지 않는다.
    if (result) { nav('/result', { replace: true }); return }
    if (!storyboard) { nav('/concept', { replace: true }); return }
    if (started.current) return
    started.current = true
    run()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function run() {
    setError('')
    const concept = getConcept(config.conceptId)
    const { w: W, h: H } = aspectDims(config.aspect)
    const brand = listing.contact || listing.region || '부동산릴스'
    const created: string[] = []
    let gradientBg: string | null = null

    try {
      const sb = storyboard!

      // ── 1) 영상 엔진 ──
      setStatus('영상 엔진 불러오는 중…')
      const ok = await FFmpegService.load()
      if (!ok) throw new Error('영상 엔진을 불러오지 못했어요. 새로고침 후 다시 시도해주세요.')
      setPct(10)

      // 매물번호 코너 라벨(시리즈 워터마크) — 모든 클립에 함께 구워 넣는다
      let watermarkUrl: string | undefined
      const no = listing.listingNo.trim()
      if (no) { watermarkUrl = await renderCornerLabel(/^[A-Za-z]/.test(no) ? no : `NO.${no}`, W); created.push(watermarkUrl) }

      // ── 2) 씬별 클립(Ken Burns + 자막·워터마크 굽기) + 나레이션 대상 수집 ──
      const imgById = new Map(images.map(i => [i.id, i]))
      const clips: string[] = []
      const narrationJobs: { text: string; start: number }[] = []
      let cursor = 0
      let anyCaption = false
      for (let i = 0; i < sb.scenes.length; i++) {
        const sc = sb.scenes[i]
        setStatus(`컷 만드는 중 ${i + 1} / ${sb.scenes.length}`)

        let srcUrl = sc.photoId ? imgById.get(sc.photoId)?.src : undefined
        if (!srcUrl) {
          if (!gradientBg) gradientBg = await renderGradientBg(W, H, concept.accent)
          srcUrl = gradientBg
        }
        // 자막 카드(옵션)를 만들어 이 클립에 정적 오버레이로 구워 넣는다(줌과 무관하게 선명)
        let captionPng: string | undefined
        if (config.subtitles && (sc.caption || sc.sub)) {
          captionPng = await renderCaptionOverlay({
            W, H, role: sc.role, caption: sc.caption, sub: sc.sub, badge: sc.badge,
            accent: concept.accent, brand: sc.role === 'cta' ? brand : undefined,
          })
          created.push(captionPng); anyCaption = true
        }
        const clip = await FFmpegService.imageToSceneClip(srcUrl, sc.duration, W, H, captionPng, watermarkUrl)
        clips.push(clip); created.push(clip)

        // 나레이션은 "편집된 나레이션 문구"를 읽는다(자막과 별개)
        if (sc.narration?.trim()) narrationJobs.push({ text: sc.narration.trim(), start: cursor })
        cursor += sc.duration
        setPct(10 + Math.round((58 * (i + 1)) / sb.scenes.length))
      }

      // ── 3) 나레이션 음성(선택, best-effort) ──
      const voiceClips: VoiceClip[] = []
      if (config.narration && hasGeminiKey() && narrationJobs.length) {
        for (let i = 0; i < narrationJobs.length; i++) {
          setStatus(`나레이션 음성 생성 중 ${i + 1} / ${narrationJobs.length}`)
          try {
            const audioUrl = await synthesizeTTS(narrationJobs[i].text, config.voice)
            voiceClips.push({ audioUrl, start: narrationJobs[i].start })
            created.push(audioUrl)
          } catch (e) { console.warn(`나레이션 ${i + 1} 실패 — 건너뜀:`, e) }
          setPct(68 + Math.round((14 * (i + 1)) / narrationJobs.length))
        }
      }

      // ── 4) BGM + 병합(자막·워터마크는 이미 구워져 있어 재인코딩 불필요 → 빠른 concat) ──
      const seed = `${sb.conceptId}-${sb.aspect}-${sb.scenes.length}-${listing.title}`
      const bgmUrl = resolveBgmUrl(concept.bgmMood, seed)
      setStatus(voiceClips.length ? '나레이션·음악 입혀 합치는 중…' : '음악 입히고 합치는 중…')
      setPct(86)
      const merged = await FFmpegService.concatClips(clips, bgmUrl, voiceClips, sb.totalSec)
      setPct(98)
      if (!merged.url) throw new Error('영상 합치기에 실패했어요. 사진 수를 줄여 다시 시도해보세요.')

      setResult({
        id: makeVideoId(), url: merged.url, durationSec: sb.totalSec, aspect: sb.aspect,
        hasSubtitles: anyCaption, hasNarration: merged.hasNarration, hasBgm: merged.hasBgm,
      })
      setPct(100)
      created.forEach(u => { if (u !== merged.url) URL.revokeObjectURL(u) })
      setStatus('완성!')
      setTimeout(() => nav('/result'), 350)
    } catch (e) {
      console.error(e)
      created.forEach(u => URL.revokeObjectURL(u))
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const retry = () => { started.current = false; setPct(2); setError(''); started.current = true; run() }

  return (
    <div style={{ padding: '40px 24px', maxWidth: 460, margin: '0 auto', minHeight: '70vh', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
      {error ? (
        <div className="animate-fade-in" style={{ textAlign: 'center' }}>
          <AlertTriangle size={44} color="var(--color-error)" style={{ margin: '0 auto 16px' }} />
          <h2 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: 8 }}>제작 중 문제가 생겼어요</h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', marginBottom: 20, lineHeight: 1.6 }}>{error}</p>
          <button className="btn btn-gold btn-full" onClick={retry}><RotateCcw size={16} /> 다시 시도</button>
          <button className="btn btn-ghost btn-full" style={{ marginTop: 8 }} onClick={() => nav('/storyboard')}>대본 편집으로</button>
        </div>
      ) : (
        <div className="animate-fade-in" style={{ textAlign: 'center' }}>
          <div className="flex-center" style={{ width: 76, height: 76, borderRadius: 24, background: 'var(--gradient-card)', border: '1px solid var(--color-border-gold)', margin: '0 auto 22px', animation: 'pulse-gold 2s infinite' }}>
            <Film size={34} color="var(--color-gold-400)" />
          </div>
          <h2 style={{ fontSize: '1.15rem', fontWeight: 800, marginBottom: 6 }}>영상을 만들고 있어요</h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', marginBottom: 22, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
            <Loader2 size={15} className="animate-spin" /> {status}
          </p>
          <div className="progress-bar"><div className="progress-bar__fill" style={{ width: `${pct}%` }} /></div>
          <div style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', marginTop: 10 }}>{pct}%</div>
          <p style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)', marginTop: 20, lineHeight: 1.5 }}>
            모든 처리는 브라우저 안에서 진행돼요. 창을 닫지 말고 잠시만 기다려주세요.
          </p>
        </div>
      )}
    </div>
  )
}
