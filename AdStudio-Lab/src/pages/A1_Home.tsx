import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { FileText, Sparkles, Clapperboard, ChevronRight, Coins, Video, Zap, Bot, ShieldCheck } from 'lucide-react'
import { useAdStore } from '../stores/adStore'

export default function A1_Home() {
  const navigate = useNavigate()
  const reset = useAdStore(s => s.reset)

  const startCreate = () => {
    reset()
    navigate('/source')
  }

  const steps = [
    { icon: FileText, title: '자료 업로드', desc: '웹사이트 URL · PDF 설명서 · 제품 텍스트', tag: 'Gemini AI' },
    { icon: Sparkles, title: 'AI 자동 분석', desc: '타겟 분석 · 나레이션 · BGM 자동 생성', tag: 'Auto Creative' },
    { icon: Clapperboard, title: '배우 & 영상 렌더', desc: 'AI 가상 배우 또는 내 사진 무빙포토 출연', tag: 'LTX Engine' },
  ]

  const featureBadges = [
    { label: 'Gemini 분석', icon: Bot, color: '#00f0ff' },
    { label: 'AI 가상배우', icon: Video, color: '#ad00ff' },
    { label: '초고속 렌더', icon: Zap, color: '#00ff99' },
    { label: 'P 1,000 무료', icon: ShieldCheck, color: '#f59e0b' },
  ]

  return (
    <div style={{ padding: '24px 16px', paddingBottom: 110, maxWidth: 540, margin: '0 auto' }}>
      {/* 히어로 영역 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        style={{
          textAlign: 'center',
          padding: '36px 18px 28px',
          background: 'var(--gradient-hero)',
          borderRadius: 'var(--radius-xl)',
          border: '1px solid var(--color-border-cyan)',
          boxShadow: 'var(--shadow-brand)',
          position: 'relative',
          overflow: 'hidden',
          marginBottom: 20,
        }}
      >
        {/* 상단 라이브 뱃지 */}
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderRadius: 20, background: 'rgba(0, 240, 255, 0.1)', border: '1px solid rgba(0, 240, 255, 0.3)', marginBottom: 14 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#00f0ff', boxShadow: '0 0 8px #00f0ff' }} />
          <span style={{ fontSize: '0.72rem', fontWeight: 800, color: '#00f0ff', letterSpacing: '0.05em' }}>AI STUDIO ONLINE</span>
        </div>

        <h1 style={{ fontSize: '1.8rem', fontWeight: 900, lineHeight: 1.25, marginBottom: 10, color: '#fff' }}>
          URL 한 줄로 완성되는<br />
          <span style={{
            background: 'var(--gradient-cyber)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
            filter: 'drop-shadow(0 0 12px rgba(0,240,255,0.4))'
          }}>
            AI 광고 영상
          </span>
        </h1>

        <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.88rem', marginBottom: 22, lineHeight: 1.4 }}>
          링크나 설명서만 넣으면 분석부터 가상배우 출연까지 자동!
        </p>

        {/* 메인 CTA */}
        <motion.button
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          className="btn"
          onClick={startCreate}
          style={{
            width: '100%',
            maxWidth: 300,
            padding: '15px 20px',
            fontSize: '1rem',
            fontWeight: 800,
            color: '#07070d',
            background: 'var(--gradient-cyber)',
            borderRadius: 'var(--radius-lg)',
            boxShadow: 'var(--shadow-cyan)',
            border: 'none',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            cursor: 'pointer',
          }}
        >
          <span>광고 제작 시작하기</span>
          <ChevronRight size={18} color="#07070d" />
        </motion.button>

        {/* 피처 태그 칩 */}
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 6, marginTop: 20 }}>
          {featureBadges.map((b) => (
            <div key={b.label} style={{
              display: 'inline-flex', alignItems: 'center', gap: 5, padding: '4px 9px',
              borderRadius: 10, background: 'rgba(18, 18, 30, 0.75)', border: '1px solid rgba(255,255,255,0.08)',
              fontSize: '0.72rem', color: 'var(--color-text-secondary)', fontWeight: 600,
            }}>
              <b.icon size={12} color={b.color} />
              <span>{b.label}</span>
            </div>
          ))}
        </div>
      </motion.div>

      {/* 3단계 프로세스 */}
      <h2 style={{ fontSize: '1.05rem', fontWeight: 800, color: '#fff', marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
        <Zap size={16} color="#00f0ff" />
        <span>제작 프로세스</span>
      </h2>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {steps.map((s, i) => (
          <motion.div
            key={s.title}
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1 * i }}
            style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '14px 16px',
              background: 'var(--color-bg-card)', border: '1px solid var(--color-border-cyan)',
              borderRadius: 'var(--radius-lg)', backdropFilter: 'blur(12px)',
            }}
          >
            <div style={{
              width: 40, height: 40, borderRadius: 12, display: 'flex',
              alignItems: 'center', justifyContent: 'center', flexShrink: 0,
              background: i === 0 ? 'rgba(0, 240, 255, 0.12)' : i === 1 ? 'rgba(173, 0, 255, 0.12)' : 'rgba(0, 255, 153, 0.12)',
              border: `1px solid ${i === 0 ? 'rgba(0, 240, 255, 0.3)' : i === 1 ? 'rgba(173, 0, 255, 0.3)' : 'rgba(0, 255, 153, 0.3)'}`,
            }}>
              <s.icon size={20} color={i === 0 ? '#00f0ff' : i === 1 ? '#ad00ff' : '#00ff99'} />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 }}>
                <div style={{ fontWeight: 800, fontSize: '0.92rem', color: '#fff' }}>{i + 1}. {s.title}</div>
                <span style={{ fontSize: '0.68rem', color: 'var(--color-cyber-cyan)', background: 'rgba(0, 240, 255, 0.1)', padding: '1px 6px', borderRadius: 4, fontWeight: 700 }}>{s.tag}</span>
              </div>
              <div style={{ color: 'var(--color-text-secondary)', fontSize: '0.78rem' }}>{s.desc}</div>
            </div>
          </motion.div>
        ))}
      </div>

      {/* 웰컴 포인트 안내 */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        style={{
          marginTop: 16, padding: '14px 16px', borderRadius: 'var(--radius-lg)',
          background: 'linear-gradient(135deg, rgba(245, 158, 11, 0.08) 0%, rgba(18, 18, 30, 0.8) 100%)',
          border: '1px solid rgba(245, 158, 11, 0.3)',
          display: 'flex', alignItems: 'center', gap: 12,
        }}
      >
        <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(245, 158, 11, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <Coins size={20} color="var(--color-gold-400)" />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 800, color: 'var(--color-gold-400)', marginBottom: 2 }}>
            신규 가입 시 P 1,000 무료!
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', margin: 0, lineHeight: 1.3 }}>
            가상배우 P 100 · 사진 모델 P 50으로 즉시 제작 가능합니다.
          </p>
        </div>
      </motion.div>
    </div>
  )
}

