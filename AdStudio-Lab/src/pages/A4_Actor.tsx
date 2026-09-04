import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, ImageUp, Coins, ChevronRight } from 'lucide-react'
import { clsx } from 'clsx'
import { useAdStore } from '../stores/adStore'
import { useProjectStore } from '../stores/projectStore'
import { AI_ACTOR_GENDERS, AI_ACTOR_AGES, AI_ACTOR_VIBES } from '../utils/adConcepts'

// [4] 배우 설정 (하이브리드) — 여기서 오마주 제작 파이프라인으로 합류한다.
//   AI 가상 배우  → 프로젝트 생성 후 곧장 [5] 컨셉 선택(/concept)
//   내 사진 모델  → 프로젝트 생성 후 오마주 사진 업로드(/upload, 얼굴 인식·동의 포함)를 거쳐 /concept
// 포인트 차감은 여기서 하지 않는다 — 오마주 구성 그대로 제작 단계(A8)의 인가 경로에서 처리된다.
export default function A4_Actor() {
  const navigate = useNavigate()
  const { analysis, setActor, aiActor, setAiActor } = useAdStore()
  const createProject = useProjectStore(s => s.createProject)

  // 분석 없이 직접 진입(새로고침 포함)한 경우 자료 업로드부터 — 렌더 중 navigate는 금지라 effect에서
  useEffect(() => {
    if (!analysis) navigate('/source', { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis])

  if (!analysis) return null

  const start = (mode: 'ai' | 'photo') => {
    setActor(mode)
    createProject()
    navigate(mode === 'photo' ? '/upload' : '/concept')
  }

  return (
    <div style={{ padding: '24px 16px', paddingBottom: 110, maxWidth: 600, margin: '0 auto' }}>
      {/* 진행 중인 광고 요약 */}
      <div style={{
        padding: '12px 16px', borderRadius: 'var(--radius-md)', marginBottom: 18,
        background: 'rgba(0, 240, 255, 0.08)', border: '1px solid var(--color-border-cyan)',
        fontSize: '0.85rem', color: 'var(--color-text-secondary)', backdropFilter: 'blur(12px)',
      }}>
        🎬 광고 제작 프로젝트: <strong style={{ color: '#00f0ff', fontWeight: 800 }}>{analysis.productName}</strong>
      </div>

      <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.88rem', marginBottom: 20, lineHeight: 1.4 }}>
        광고 영상에 등장할 배우 모델 타입을 선택하세요.
      </p>

      {/* 옵션 1: AI 가상 배우 */}
      <div style={{
        padding: 20, borderRadius: 'var(--radius-lg)', marginBottom: 18,
        background: 'var(--color-bg-card)', border: '1px solid var(--color-border-cyan)',
        boxShadow: 'var(--shadow-sm)', backdropFilter: 'blur(12px)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(0, 240, 255, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Bot size={22} color="#00f0ff" />
          </div>
          <span style={{ fontWeight: 900, fontSize: '1.05rem', color: '#fff' }}>AI 가상 배우 (LTX)</span>
          <span style={{
            marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4,
            fontSize: '0.78rem', fontWeight: 800, color: 'var(--color-gold-400)',
            background: 'rgba(245,158,11,0.12)', padding: '4px 10px', borderRadius: 20,
            border: '1px solid rgba(245,158,11,0.3)',
          }}>
            <Coins size={14} /> P 100
          </span>
        </div>
        <p style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', marginBottom: 14 }}>
          설정된 프로필에 맞춰 AI가 연기 장면을 자동 생성합니다.
        </p>

        {/* AI 배우 기본 프로필 */}
        <div style={{ marginBottom: 16, padding: 12, background: 'rgba(10,10,18,0.6)', borderRadius: 12, border: '1px solid rgba(255,255,255,0.06)' }}>
          <div style={{ fontSize: '0.78rem', color: '#00f0ff', fontWeight: 700, marginBottom: 6 }}>배우 성별</div>
          <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
            {AI_ACTOR_GENDERS.map(g => (
              <button
                key={g.id}
                className="btn btn-sm"
                style={{
                  flex: 1, padding: '8px 12px', borderRadius: 8, fontWeight: 700, fontSize: '0.8rem',
                  background: aiActor.gender === g.id ? 'var(--gradient-cyber)' : 'rgba(20,20,32,0.8)',
                  color: aiActor.gender === g.id ? '#07070d' : 'var(--color-text-secondary)',
                  border: aiActor.gender === g.id ? 'none' : '1px solid var(--color-border)',
                }}
                onClick={() => setAiActor({ gender: g.id })}
              >
                {g.label}
              </button>
            ))}
          </div>

          <div style={{ fontSize: '0.78rem', color: '#00f0ff', fontWeight: 700, marginBottom: 6 }}>연령대</div>
          <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
            {AI_ACTOR_AGES.map(a => (
              <button
                key={a.id}
                className="btn btn-sm"
                style={{
                  flex: 1, padding: '8px 10px', borderRadius: 8, fontWeight: 700, fontSize: '0.78rem',
                  background: aiActor.age === a.id ? 'var(--gradient-cyber)' : 'rgba(20,20,32,0.8)',
                  color: aiActor.age === a.id ? '#07070d' : 'var(--color-text-secondary)',
                  border: aiActor.age === a.id ? 'none' : '1px solid var(--color-border)',
                }}
                onClick={() => setAiActor({ age: a.id })}
              >
                {a.label}
              </button>
            ))}
          </div>

          <div style={{ fontSize: '0.78rem', color: '#00f0ff', fontWeight: 700, marginBottom: 6 }}>비주얼 콘셉트</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {AI_ACTOR_VIBES.map(v => (
              <button
                key={v.id}
                className="btn btn-sm"
                style={{
                  padding: '6px 12px', borderRadius: 8, fontWeight: 700, fontSize: '0.78rem',
                  background: aiActor.vibe === v.id ? 'var(--gradient-cyber)' : 'rgba(20,20,32,0.8)',
                  color: aiActor.vibe === v.id ? '#07070d' : 'var(--color-text-secondary)',
                  border: aiActor.vibe === v.id ? 'none' : '1px solid var(--color-border)',
                }}
                onClick={() => setAiActor({ vibe: v.id })}
              >
                {v.label}
              </button>
            ))}
          </div>
        </div>

        <button
          className="btn"
          style={{
            width: '100%', padding: '14px', fontSize: '0.98rem', fontWeight: 800,
            background: 'var(--gradient-cyber)', color: '#07070d',
            borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-cyan)', border: 'none',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, cursor: 'pointer',
          }}
          onClick={() => start('ai')}
        >
          <span>AI 가상 배우로 진행</span>
          <ChevronRight size={18} color="#07070d" />
        </button>
      </div>

      {/* 옵션 2: 내 사진 속 모델 */}
      <div style={{
        padding: 20, borderRadius: 'var(--radius-lg)',
        background: 'var(--color-bg-card)', border: '1px solid var(--color-border-cyan)',
        boxShadow: 'var(--shadow-sm)', backdropFilter: 'blur(12px)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(173, 0, 255, 0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <ImageUp size={22} color="#ad00ff" />
          </div>
          <span style={{ fontWeight: 900, fontSize: '1.05rem', color: '#fff' }}>내 사진 속 모델 (무빙포토)</span>
          <span style={{
            marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4,
            fontSize: '0.78rem', fontWeight: 800, color: 'var(--color-gold-400)',
            background: 'rgba(245,158,11,0.12)', padding: '4px 10px', borderRadius: 20,
            border: '1px solid rgba(245,158,11,0.3)',
          }}>
            <Coins size={14} /> P 50
          </span>
        </div>
        <p style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', marginBottom: 14 }}>
          인물 사진을 업로드하면 AI가 감정 및 입모양을 합성합니다.
        </p>
        <button
          className="btn"
          style={{
            width: '100%', padding: '14px', fontSize: '0.98rem', fontWeight: 800,
            background: 'linear-gradient(135deg, #7c3aff 0%, #ad00ff 100%)', color: '#fff',
            borderRadius: 'var(--radius-md)', boxShadow: '0 0 20px rgba(173,0,255,0.4)', border: 'none',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, cursor: 'pointer',
          }}
          onClick={() => start('photo')}
        >
          <span>내 사진 업로드하러 가기</span>
          <ChevronRight size={18} color="#fff" />
        </button>
      </div>
    </div>
  )
}
