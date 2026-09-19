import React, { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Download, Link2, Edit3, Zap, Share2,
  Play, Pause, Volume2, VolumeX, Maximize,
  Info, ChevronRight, Star, Sparkles, CheckCircle
} from 'lucide-react'
import { useProjectStore } from '../stores/projectStore'
import { clsx } from 'clsx'

// ── 비디오 플레이어 ───────────────────────────────────────────
function VideoPlayer({ src }: { src?: string }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [progress, setProgress] = useState(0)

  const toggle = () => {
    if (!videoRef.current) return
    if (playing) { videoRef.current.pause(); setPlaying(false) }
    else { videoRef.current.play(); setPlaying(true) }
  }

  const handleTimeUpdate = () => {
    if (!videoRef.current) return
    const pct = (videoRef.current.currentTime / videoRef.current.duration) * 100
    setProgress(pct || 0)
  }

  return (
    <div style={{ position: 'relative', width: '100%', background: '#000', borderRadius: 16, overflow: 'hidden' }}>
      {/* 실제 비디오가 없을 때 목업 */}
      {!src ? (
        <div style={{
          aspectRatio: '9/16', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          background: 'linear-gradient(145deg, #1a0a2e, #0a0a1a)',
          cursor: 'pointer',
        }} onClick={() => setPlaying(!playing)}>
          {/* 목업 영상 효과 */}
          <motion.div
            animate={{ scale: [1, 1.08, 1], opacity: [0.8, 1, 0.8] }}
            transition={{ duration: 3, repeat: Infinity }}
            style={{
              width: 180, height: 240, borderRadius: 20,
              background: 'linear-gradient(145deg, rgba(124,58,255,0.3), rgba(192,132,252,0.1))',
              border: '1px solid rgba(124,58,255,0.3)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              marginBottom: 20, position: 'relative', overflow: 'hidden',
            }}
          >
            {/* 빛나는 효과 */}
            <motion.div
              style={{
                position: 'absolute', top: -50, left: -50, right: -50,
                height: 100,
                background: 'linear-gradient(180deg, transparent, rgba(255,255,255,0.05), transparent)',
              }}
              animate={{ y: ['-100%', '200%'] }}
              transition={{ duration: 2.5, repeat: Infinity, ease: 'linear' }}
            />
            <div style={{ fontSize: 48 }}>🎬</div>
          </motion.div>

          <div style={{ fontSize: '1rem', fontWeight: 700, color: '#fff', marginBottom: 8 }}>
            완성 영상
          </div>
          <div style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.5)' }}>
            AI 생성 · 30초 · 1080p
          </div>

          {/* 재생 버튼 */}
          <motion.div
            style={{
              position: 'absolute', bottom: 80,
              width: 56, height: 56, borderRadius: '50%',
              background: 'rgba(255,255,255,0.15)',
              backdropFilter: 'blur(8px)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              border: '1px solid rgba(255,255,255,0.2)',
            }}
            whileTap={{ scale: 0.9 }}
          >
            <Play size={24} color="#fff" fill="#fff" />
          </motion.div>
        </div>
      ) : (
        <>
          <video
            ref={videoRef}
            src={src}
            style={{ width: '100%', display: 'block' }}
            muted={muted}
            onTimeUpdate={handleTimeUpdate}
            onEnded={() => setPlaying(false)}
            playsInline
          />
          {/* 컨트롤 오버레이 */}
          <div
            style={{
              position: 'absolute', inset: 0,
              display: 'flex', flexDirection: 'column', justifyContent: 'flex-end',
              background: 'linear-gradient(to top, rgba(0,0,0,0.5) 0%, transparent 50%)',
              padding: '12px 16px',
            }}
            onClick={toggle}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <button onClick={e => { e.stopPropagation(); toggle() }}>
                {playing ? <Pause size={20} color="#fff" /> : <Play size={20} color="#fff" fill="#fff" />}
              </button>
              <div style={{ flex: 1, height: 3, background: 'rgba(255,255,255,0.3)', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${progress}%`, height: '100%', background: '#fff', borderRadius: 2 }} />
              </div>
              <button onClick={e => { e.stopPropagation(); setMuted(!muted) }}>
                {muted ? <VolumeX size={18} color="#fff" /> : <Volume2 size={18} color="#fff" />}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

// ── 공유 모달 ─────────────────────────────────────────────────
function ShareModal({ onClose }: { onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const mockUrl = 'https://memoryframe.app/v/abc123'

  const copyLink = () => {
    navigator.clipboard.writeText(mockUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <motion.div
      className="modal-overlay"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      onClick={onClose}
    >
      <motion.div
        className="modal-sheet"
        initial={{ y: 100 }} animate={{ y: 0 }}
        onClick={e => e.stopPropagation()}
      >
        <div className="modal-sheet__handle" />
        <h2 style={{ fontSize: '1rem', fontWeight: 700, marginBottom: 16 }}>공유하기</h2>

        {/* 링크 복사 */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
          <div style={{
            flex: 1, padding: '10px 14px', background: 'var(--color-bg-base)',
            border: '1px solid var(--color-border)', borderRadius: 10,
            fontSize: '0.8rem', color: 'var(--color-text-muted)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {mockUrl}
          </div>
          <button className="btn btn-outline btn-sm" onClick={copyLink}>
            {copied ? <CheckCircle size={14} color="var(--color-success)" /> : <Link2 size={14} />}
            {copied ? '복사됨' : '복사'}
          </button>
        </div>

        {/* SNS 공유 버튼들 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
          {[
            { name: '카카오톡', emoji: '💬', color: '#FEE500' },
            { name: 'Instagram', emoji: '📸', color: '#E1306C' },
            { name: 'Twitter', emoji: '🐦', color: '#1DA1F2' },
            { name: '더보기', emoji: '⋯', color: 'var(--color-bg-card)' },
          ].map(s => (
            <button
              key={s.name}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
                padding: '12px 8px', borderRadius: 12, border: 'none',
                background: s.name === '더보기' ? 'var(--color-bg-card)' : `${s.color}20`,
                cursor: 'pointer',
              }}
            >
              <span style={{ fontSize: 24 }}>{s.emoji}</span>
              <span style={{ fontSize: 11, color: 'var(--color-text-secondary)', fontWeight: 500 }}>
                {s.name}
              </span>
            </button>
          ))}
        </div>
      </motion.div>
    </motion.div>
  )
}

// ── S6 메인 결과 ──────────────────────────────────────────────
export default function S6Result() {
  const navigate = useNavigate()
  const { selectedLane, currentProject, scenes } = useProjectStore()
  const [showShare, setShowShare] = useState(false)
  const [downloadStarted, setDownloadStarted] = useState(false)

  const latestRender = currentProject?.renders?.[currentProject.renders.length - 1]

  const handleDownload = () => {
    if (!latestRender?.videoUrl) return
    setDownloadStarted(true)
    const link = document.createElement('a')
    link.href = latestRender.videoUrl
    link.download = `omage-${currentProject?.id ?? 'video'}.mp4`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    setTimeout(() => setDownloadStarted(false), 3000)
  }

  const isMovingPhoto = selectedLane === 'moving_photo'
  const isFreeAI = selectedLane === 'free_ai'

  return (
    <div style={{ padding: '20px 16px', paddingBottom: 100 }}>

      {/* 헤더 */}
      <motion.div
        style={{ textAlign: 'center', marginBottom: 20 }}
        initial={{ opacity: 0, y: -16 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <div style={{ fontSize: 48, marginBottom: 8 }}>🎬</div>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 800, marginBottom: 6 }}>
          완성됐어요!
        </h1>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
          오마주 영상이 완성됐어요
        </p>
      </motion.div>

      {/* 비디오 플레이어 */}
      <motion.div
        style={{ marginBottom: 20 }}
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.1 }}
      >
        <VideoPlayer src={latestRender?.videoUrl} />
      </motion.div>

      {/* AI 생성 고지 */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, marginBottom: 20,
        padding: '8px 12px', background: 'var(--color-bg-base)',
        border: '1px solid var(--color-border)', borderRadius: 8,
        fontSize: '0.75rem', color: 'var(--color-text-muted)',
      }}>
        <Info size={13} />
        이 영상은 AI가 생성한 콘텐츠입니다. AI-generated content.
      </div>

      {/* 액션 버튼들 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 24 }}>
        <motion.button
          className="btn btn-primary btn-full btn-lg"
          onClick={handleDownload}
          whileTap={{ scale: 0.98 }}
        >
          {downloadStarted ? (
            <><CheckCircle size={18} /> 다운로드 시작됨</>
          ) : (
            <><Download size={18} /> 다운로드</>
          )}
        </motion.button>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <button
            className="btn btn-outline"
            onClick={() => setShowShare(true)}
          >
            <Share2 size={16} /> 공유
          </button>
          <button
            className="btn btn-outline"
            onClick={() => navigate('/storyboard')}
          >
            <Edit3 size={16} /> 다시 편집
          </button>
        </div>
      </div>

      {/* 업그레이드 유도 */}
      {isMovingPhoto && (
        <motion.div
          className="card"
          style={{
            background: 'linear-gradient(135deg, rgba(124,58,255,0.1), rgba(0,0,0,0))',
            borderColor: 'var(--color-border-brand)',
            marginBottom: 16,
          }}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', marginBottom: 14 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10, flexShrink: 0,
              background: 'var(--color-brand-600)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Sparkles size={20} color="#fff" />
            </div>
            <div>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>진짜 AI 영상으로 업그레이드</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                알리바바 API 키를 연결하면 무료로 진짜 AI 영상을 만들 수 있어요. 1,650초 무료 쿼터 제공!
              </div>
            </div>
          </div>
          <button
            className="btn btn-primary btn-full"
            onClick={() => navigate('/keys')}
          >
            <Zap size={16} /> API 키 연결하기 →
          </button>
        </motion.div>
      )}

      {isFreeAI && (
        <motion.div
          className="card"
          style={{
            background: 'linear-gradient(135deg, rgba(245,158,11,0.08), rgba(0,0,0,0))',
            borderColor: 'rgba(245,158,11,0.3)',
            marginBottom: 16,
          }}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
        >
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', marginBottom: 14 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10, flexShrink: 0,
              background: 'var(--gradient-gold)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <Star size={20} color="#1a0a00" />
            </div>
            <div>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>1080p 고퀄 영상으로</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                {/* 씬당 단가 상한은 Veo 3.1 Fast 720p·6초 = $0.60 (기존 $0.75 표기는 8초 기본값 기준이었다)
                    ⚠️ 미확인: 위 "1080p" 문구 — Veo는 720p 고정(1080p로 올리면 8초만 허용돼 단가가 $0.96/씬),
                    Kling도 std=720p로 호출한다. 실제 출력 해상도 기준으로 문구를 정정할지는 확인 후 적용. */}
                {/* 하한은 Seedance 2.0 fast 720p·5초·오디오 없음 = $0.34
                    (fast 리소스팩 $3.30/M 토큰 × 약 103K 토큰. 기존 $0.11 표기는 실제와 3배 차이였다) */}
                Seedance·Kling·Veo로 즉시 제작. 씬당 $0.34~0.60의 본인 API 비용만 발생해요.
              </div>
            </div>
          </div>
          <button
            className="btn btn-gold btn-full"
            onClick={() => navigate('/storyboard')}
          >
            <Zap size={16} /> 고퀄 영상으로 만들기
          </button>
        </motion.div>
      )}

      {/* 영상 정보 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: 12 }}>영상 정보</h3>
        {[
          { label: '해상도', value: isMovingPhoto ? '1080×1920 (1080p)' : isFreeAI ? '1280×720 (720p)' : '1920×1080 (1080p)' },
          { label: '길이', value: `${latestRender?.durationSec ?? scenes.reduce((sum, s) => sum + s.duration, 0)}초 · ${scenes.length}씬` },
          { label: '레인', value: isMovingPhoto ? '무빙포토 (무료)' : isFreeAI ? 'AI 영상 (알리바바 무료 쿼터)' : '고퀄 영상 (유료 API)' },
          { label: '생성일', value: (latestRender?.createdAt ?? new Date()).toLocaleDateString('ko-KR') },
        ].map(({ label, value }) => (
          <div key={label} className="flex-between" style={{ padding: '8px 0', borderBottom: '1px solid var(--color-border)' }}>
            <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>{label}</span>
            <span style={{ fontSize: '0.8rem', fontWeight: 500 }}>{value}</span>
          </div>
        ))}
      </div>

      {/* 새 영상 만들기 */}
      <button
        className="btn btn-outline btn-full"
        onClick={() => navigate('/create')}
      >
        <Sparkles size={16} /> 새로운 영상만들기
      </button>

      {/* 공유 모달 */}
      {showShare && <ShareModal onClose={() => setShowShare(false)} />}

    </div>
  )
}
