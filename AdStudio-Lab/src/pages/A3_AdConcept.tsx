import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronRight, Music, Timer, Mic, Globe, Captions } from 'lucide-react'
import { clsx } from 'clsx'
import { useAdStore } from '../stores/adStore'
import { SUPPORTED_LOCALES, LOCALE_INFO } from '../services/localizationService'
import { getVoiceOptions, synthesizeDialogue } from '../services/voiceService'
import { translateSceneTextDetailed } from '../services/localizationService'

const DURATIONS = [15, 30, 60] as const
const MOODS = [
  { id: 'energetic', label: '활기찬' },
  { id: 'calm', label: '차분한' },
  { id: 'corporate', label: '비즈니스' },
] as const
const VOICES = [
  { id: 'female', label: '여성 음성' },
  { id: 'male', label: '남성 음성' },
] as const

// 2단계: 광고 컨셉 — Gemini 분석 결과 확인 + 나레이션 편집 + 길이/음악/음성 설정
export default function A3_Concept() {
  const navigate = useNavigate()
  const { analysis, config, updateNarration, setConfig } = useAdStore()
  const [preview, setPreview] = useState<{ busy: boolean; msg: string }>({ busy: false, msg: '' })

  // 분석 없이 직접 진입(새로고침 포함)한 경우 자료 업로드부터 — 렌더 중 navigate는 금지라 effect에서
  useEffect(() => {
    if (!analysis) navigate('/source', { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis])

  /**
   * 지금 설정 그대로 짧게 합성해 들려준다 — 포인트를 쓰기 전에 언어·성우가 맞는지 바로 확인할 수 있다.
   * 실제 제작과 같은 경로(번역 → 성우 선택 → Edge TTS)를 타므로, 여기서 영어로 들리면
   * 완성 영상도 영어로 나온다는 뜻이라 원인 진단에도 그대로 쓸 수 있다.
   */
  const playPreview = async () => {
    if (!analysis) return
    setPreview({ busy: true, msg: '합성 중…' })
    try {
      const sample = (analysis.narration || '').split(/(?<=[.!?。…])\s+/)[0]?.trim() || analysis.productName
      const r = await translateSceneTextDetailed(sample, config.narrationLocale)
      const spoken = r.text
      // 번역에 실패했으면 텍스트가 원문 언어 그대로이므로, 실제 제작과 동일하게 그 사실을 알린다
      const mismatched = !r.translated && !r.skipped
      const url = await synthesizeDialogue(spoken, config.narrationLocale, {
        gender: config.voice,
        ageBand: 'adult',
        voiceId: config.voiceVariety ? undefined : config.voiceId,
        varietyIndex: config.voiceVariety ? 0 : undefined,
      })
      await new Audio(url).play()
      setPreview({
        busy: false,
        msg: mismatched
          ? `⚠️ 번역에 실패해 원문 그대로 읽었어요 — Gemini 키·쿼터를 확인해주세요. 들린 문장: "${spoken.slice(0, 40)}"`
          : `들린 문장: "${spoken.slice(0, 40)}${spoken.length > 40 ? '…' : ''}"`,
      })
    } catch (e) {
      setPreview({ busy: false, msg: `미리듣기 실패: ${e instanceof Error ? e.message : String(e)}` })
    }
  }

  if (!analysis) return null

  return (
    <div style={{ padding: '24px 16px', paddingBottom: 110, maxWidth: 600, margin: '0 auto' }}>
      {/* 분석 결과 카드 */}
      <div style={{
        padding: '20px', borderRadius: 'var(--radius-lg)', marginBottom: 22,
        background: 'var(--color-bg-card)', border: '1px solid var(--color-border-cyan)',
        boxShadow: 'var(--shadow-sm)', backdropFilter: 'blur(12px)',
      }}>
        <div style={{ fontWeight: 900, fontSize: '1.15rem', marginBottom: 6, color: '#fff' }}>
          {analysis.productName}
        </div>
        <p style={{ fontSize: '0.88rem', color: 'var(--color-text-secondary)', marginBottom: 12, lineHeight: 1.5 }}>
          {analysis.description}
        </p>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          {analysis.keyFeatures.map(f => (
            <span key={f} style={{
              fontSize: '0.75rem', padding: '4px 10px', borderRadius: 20, fontWeight: 700,
              background: 'rgba(0,240,255,0.12)', color: '#00f0ff', border: '1px solid rgba(0,240,255,0.3)',
            }}>
              #{f}
            </span>
          ))}
        </div>
        <p style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', margin: 0 }}>
          🎯 타겟: <strong style={{ color: 'var(--color-text-secondary)' }}>{analysis.targetAudience}</strong> · 핵심 혜택: <strong style={{ color: 'var(--color-text-secondary)' }}>{analysis.mainBenefit}</strong>
        </p>
      </div>

      {/* 나레이션 편집 */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 800, fontSize: '0.92rem', marginBottom: 10, color: '#fff' }}>
        <Mic size={16} color="#00f0ff" /> 나레이션 대사 (수정 가능)
      </label>
      <textarea
        value={analysis.narration}
        onChange={e => updateNarration(e.target.value)}
        style={{
          width: '100%', minHeight: 120, padding: 16, borderRadius: 'var(--radius-md)', marginBottom: 20,
          background: 'var(--color-bg-card)', border: '1px solid var(--color-border-cyan)',
          color: 'var(--color-text-primary)', fontSize: '0.9rem', resize: 'vertical',
          boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.5)', outline: 'none',
        }}
      />

      {/* 영상 길이 */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 800, fontSize: '0.92rem', marginBottom: 10, color: '#fff' }}>
        <Timer size={16} color="#00f0ff" /> 영상 길이
      </label>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {DURATIONS.map(d => (
          <button
            key={d}
            className="btn btn-sm"
            style={{
              flex: 1, padding: '10px 14px', borderRadius: 'var(--radius-sm)', fontWeight: 700,
              background: config.duration === d ? 'var(--gradient-cyber)' : 'rgba(15,15,24,0.8)',
              color: config.duration === d ? '#07070d' : 'var(--color-text-secondary)',
              border: config.duration === d ? 'none' : '1px solid var(--color-border-cyan)',
              boxShadow: config.duration === d ? 'var(--shadow-cyan)' : 'none',
            }}
            onClick={() => setConfig({ duration: d })}
          >
            {d}초
          </button>
        ))}
      </div>

      {/* 배경음악 무드 */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 800, fontSize: '0.92rem', marginBottom: 10, color: '#fff' }}>
        <Music size={16} color="#00f0ff" /> 배경음악 무드
      </label>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {MOODS.map(m => (
          <button
            key={m.id}
            className="btn btn-sm"
            style={{
              flex: 1, padding: '10px 14px', borderRadius: 'var(--radius-sm)', fontWeight: 700,
              background: config.musicMood === m.id ? 'var(--gradient-cyber)' : 'rgba(15,15,24,0.8)',
              color: config.musicMood === m.id ? '#07070d' : 'var(--color-text-secondary)',
              border: config.musicMood === m.id ? 'none' : '1px solid var(--color-border-cyan)',
              boxShadow: config.musicMood === m.id ? 'var(--shadow-cyan)' : 'none',
            }}
            onClick={() => setConfig({ musicMood: m.id })}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* 나레이션 언어 — 성우 목록이 이 언어에 따라 달라지므로 반드시 성우 선택보다 위에 둔다
          (아래에 두면 언어를 바꿀 때 화면 밖에서 성우 선택이 조용히 초기화돼 사용자가 모른다) */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 800, fontSize: '0.92rem', marginBottom: 10, color: '#fff' }}>
        <Globe size={16} color="#00f0ff" /> 나레이션 더빙 언어
      </label>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        {SUPPORTED_LOCALES.map(loc => (
          <button
            key={loc}
            className="btn btn-sm"
            style={{
              fontSize: '0.78rem', padding: '6px 12px', borderRadius: 8, fontWeight: 700,
              background: config.narrationLocale === loc ? 'var(--gradient-cyber)' : 'rgba(15,15,24,0.8)',
              color: config.narrationLocale === loc ? '#07070d' : 'var(--color-text-secondary)',
              border: config.narrationLocale === loc ? 'none' : '1px solid var(--color-border)',
            }}
            // 언어가 바뀌면 이전 언어에서 고른 성우는 목록에 없을 수 있어 자동으로 되돌린다
            onClick={() => setConfig({ narrationLocale: loc, voiceId: undefined })}
          >
            {LOCALE_INFO[loc].labelNative}
          </button>
        ))}
      </div>
      <p style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginBottom: 20 }}>
        선택한 언어로 자동 번역 및 성우 음성 더빙이 진행됩니다.
      </p>

      {/* 나레이션 음성 */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 800, fontSize: '0.92rem', marginBottom: 10, color: '#fff' }}>
        <Mic size={16} color="#00f0ff" /> 음성 타입
      </label>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {VOICES.map(v => (
          <button
            key={v.id}
            className="btn btn-sm"
            style={{
              flex: 1, padding: '10px 14px', borderRadius: 'var(--radius-sm)', fontWeight: 700,
              background: config.voice === v.id ? 'var(--gradient-cyber)' : 'rgba(15,15,24,0.8)',
              color: config.voice === v.id ? '#07070d' : 'var(--color-text-secondary)',
              border: config.voice === v.id ? 'none' : '1px solid var(--color-border-cyan)',
              boxShadow: config.voice === v.id ? 'var(--shadow-cyan)' : 'none',
            }}
            // 성별을 바꾸면 이전 성별에서 고른 성우 선택은 무효 — 기본값으로 되돌린다
            onClick={() => setConfig({ voice: v.id, voiceId: undefined })}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* 성우 선택 — 선택한 더빙 언어·성별에 맞는 실제 보이스 목록 */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 800, fontSize: '0.92rem', marginBottom: 10, color: '#fff' }}>
        <Mic size={16} color="#00f0ff" /> 성우 선택
      </label>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        {[{ id: undefined as string | undefined, label: '자동', desc: '' }, ...getVoiceOptions(config.narrationLocale, config.voice)
          .map(v => ({ id: v.id as string | undefined, label: v.native ? v.label : `${v.label} (다국어)`, desc: v.desc ?? '' }))]
          .map(v => {
            const selected = !config.voiceVariety && config.voiceId === v.id
            return (
              <button
                key={v.id ?? 'auto'}
                className="btn btn-sm"
                disabled={config.voiceVariety}
                title={v.desc}
                style={{
                  fontSize: '0.78rem', padding: '6px 12px', borderRadius: 8, fontWeight: 700,
                  opacity: config.voiceVariety ? 0.4 : 1,
                  background: selected ? 'var(--gradient-cyber)' : 'rgba(15,15,24,0.8)',
                  color: selected ? '#07070d' : 'var(--color-text-secondary)',
                  border: selected ? 'none' : '1px solid var(--color-border)',
                }}
                onClick={() => setConfig({ voiceId: v.id })}
              >
                {v.label}
              </button>
            )
          })}
      </div>

      {/* 씬마다 다른 목소리 */}
      <button
        className="btn btn-sm"
        style={{
          width: '100%', padding: '9px 14px', borderRadius: 8, fontWeight: 700, marginBottom: 8,
          background: config.voiceVariety ? 'var(--gradient-cyber)' : 'rgba(15,15,24,0.8)',
          color: config.voiceVariety ? '#07070d' : 'var(--color-text-secondary)',
          border: config.voiceVariety ? 'none' : '1px solid var(--color-border-cyan)',
        }}
        onClick={() => setConfig({ voiceVariety: !config.voiceVariety })}
      >
        {config.voiceVariety ? '✓ 씬마다 다른 목소리' : '씬마다 다른 목소리'}
      </button>
      <p style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', marginBottom: 10, lineHeight: 1.5 }}>
        {config.voiceVariety
          ? '씬이 바뀔 때마다 다른 성우가 읽어요. 인터뷰·후기형 광고에 잘 어울려요.'
          : `한 성우가 전체를 읽어요.${config.narrationLocale === 'ko' ? ' 한국어 전용 성우는 3명(여1·남2)이라, 더 다양하게 쓰려면 다국어 성우를 골라보세요.' : ''}`}
      </p>

      {/* 미리듣기 — 포인트 쓰기 전에 언어·성우가 맞는지 확인 */}
      <button
        className="btn btn-sm"
        disabled={preview.busy}
        style={{
          width: '100%', padding: '9px 14px', borderRadius: 8, fontWeight: 700, marginBottom: 6,
          background: 'rgba(15,15,24,0.8)', color: 'var(--color-text-secondary)',
          border: '1px solid var(--color-border-cyan)', opacity: preview.busy ? 0.5 : 1,
        }}
        onClick={playPreview}
      >
        {preview.busy ? '합성 중…' : '🔊 이 설정으로 미리 들어보기'}
      </button>
      {preview.msg && (
        <p style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', marginBottom: 20, lineHeight: 1.5 }}>
          {preview.msg}
        </p>
      )}
      {!preview.msg && <div style={{ marginBottom: 20 }} />}

      {/* 자막 on/off */}
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 800, fontSize: '0.92rem', marginBottom: 10, color: '#fff' }}>
        <Captions size={16} color="#00f0ff" /> 영상 자막
      </label>
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        <button
          className="btn btn-sm"
          style={{
            flex: 1, padding: '10px 14px', borderRadius: 'var(--radius-sm)', fontWeight: 700,
            background: config.subtitles ? 'var(--gradient-cyber)' : 'rgba(15,15,24,0.8)',
            color: config.subtitles ? '#07070d' : 'var(--color-text-secondary)',
            border: config.subtitles ? 'none' : '1px solid var(--color-border-cyan)',
          }}
          onClick={() => setConfig({ subtitles: true })}
        >
          자막 포함
        </button>
        <button
          className="btn btn-sm"
          style={{
            flex: 1, padding: '10px 14px', borderRadius: 'var(--radius-sm)', fontWeight: 700,
            background: !config.subtitles ? 'var(--gradient-cyber)' : 'rgba(15,15,24,0.8)',
            color: !config.subtitles ? '#07070d' : 'var(--color-text-secondary)',
            border: !config.subtitles ? 'none' : '1px solid var(--color-border-cyan)',
          }}
          onClick={() => setConfig({ subtitles: false })}
        >
          자막 없음
        </button>
      </div>
      <p style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginBottom: 24 }}>
        {config.subtitles ? '화면 하단에 자막을 구워 넣습니다.' : '자막 없이 음성만 출력됩니다.'}
      </p>

      <button
        className="btn"
        style={{
          width: '100%', padding: '16px', fontSize: '1.05rem', fontWeight: 800,
          background: 'var(--gradient-cyber)', color: '#07070d',
          borderRadius: 'var(--radius-lg)', boxShadow: 'var(--shadow-cyan)', border: 'none',
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, cursor: 'pointer',
        }}
        onClick={() => navigate('/actor')}
      >
        <span>다음: 배우 설정</span>
        <ChevronRight size={19} color="#07070d" />
      </button>
    </div>
  )
}
