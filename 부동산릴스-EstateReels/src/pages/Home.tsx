import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, Clipboard, Sparkles, Film, Clock, ChevronDown } from 'lucide-react'
import { CONCEPTS, CONCEPT_GROUP_DEFS, conceptsByGroup, type ConceptGroup } from '../utils/estateConcepts'

export default function Home() {
  const nav = useNavigate()
  const [openGroup, setOpenGroup] = useState<ConceptGroup | null>(null)
  return (
    <div className="animate-fade-in">
      {/* 히어로 */}
      <section className="hero-section">
        <div style={{ position: 'relative', zIndex: 1 }}>
          <span className="badge badge-gold" style={{ marginBottom: 14 }}>블로그 → 홍보 영상 자동 제작</span>
          <h1 className="hero-title">
            부동산 블로그가<br /><span className="gradient-text">홍보 영상</span>이 됩니다
          </h1>
          <p className="hero-subtitle">
            블로그 글과 사진을 넣으면, 소비자가 궁금해하는 니즈에 맞춰<br />
            여러 컨셉의 이미지 모션영상을 자동으로 만들어드려요.
          </p>
          <button className="btn btn-gold btn-lg btn-full" onClick={() => nav('/import')}>
            <Clipboard size={18} /> 블로그로 시작하기 <ArrowRight size={18} />
          </button>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 14 }}>
            {(['30초', '1분', '3분'] as const).map(d => (
              <span key={d} className="chip" style={{ cursor: 'default', gap: 5 }}>
                <Clock size={13} color="var(--color-gold-400)" /> {d}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* 3단계 */}
      <section style={{ padding: '8px 16px 4px' }}>
        <div style={{ display: 'grid', gap: 10 }}>
          {[
            { n: '1', t: '블로그 가져오기', d: 'URL을 넣거나 글·사진을 붙여넣어요', icon: Clipboard },
            { n: '2', t: '컨셉 고르기', d: '역세권·학군·투자·급매 등 니즈별 컨셉', icon: Sparkles },
            { n: '3', t: '영상 완성', d: '자막·모션·음악까지 자동으로', icon: Film },
          ].map(s => (
            <div key={s.n} className="card" style={{ display: 'flex', alignItems: 'center', gap: 14, padding: 14 }}>
              <div className="flex-center" style={{ width: 40, height: 40, borderRadius: 12, background: 'var(--gradient-brand)', flexShrink: 0, fontWeight: 900, color: '#fff' }}>{s.n}</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 800, fontSize: '0.98rem' }}>{s.t}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>{s.d}</div>
              </div>
              <s.icon size={20} color="var(--color-gold-400)" />
            </div>
          ))}
        </div>
      </section>

      {/* 컨셉 미리보기 — 물건 유형(대분류) → 컨셉(소분류) */}
      <section style={{ padding: '18px 16px 28px' }}>
        <div className="flex-between" style={{ marginBottom: 4 }}>
          <h2 style={{ fontSize: '1.05rem', fontWeight: 800 }}>물건 유형별 스토리 컨셉</h2>
          <span style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)' }}>{CONCEPTS.length}가지</span>
        </div>
        <p style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', margin: '0 0 12px' }}>
          유형을 누르면 그 유형에 맞는 컨셉이 펼쳐져요.
        </p>
        <div style={{ display: 'grid', gap: 10 }}>
          {CONCEPT_GROUP_DEFS.map(g => {
            const open = openGroup === g.id
            const items = conceptsByGroup(g.id)
            return (
              <div key={g.id} className="card" style={{ padding: 0, overflow: 'hidden' }}>
                {/* 대분류 헤더 */}
                <button onClick={() => setOpenGroup(open ? null : g.id)}
                  style={{ display: 'flex', alignItems: 'center', gap: 12, width: '100%', padding: 14, background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left' }}>
                  <span style={{ fontSize: 26, lineHeight: 1 }}>{g.emoji}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 800, fontSize: '0.95rem' }}>{g.label}</div>
                    <div style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)', lineHeight: 1.4 }}>{g.desc}</div>
                  </div>
                  <span className="badge badge-muted" style={{ flexShrink: 0 }}>{items.length}</span>
                  <ChevronDown size={18} color="var(--color-text-muted)"
                    style={{ flexShrink: 0, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }} />
                </button>
                {/* 소분류(컨셉) */}
                {open && (
                  <div className="concept-grid" style={{ padding: '2px 12px 14px' }}>
                    {items.map(c => (
                      <div key={c.id} className="concept-card" onClick={() => nav('/import')} style={{ minHeight: 116 }}>
                        <span className="concept-card__emoji">{c.emoji}</span>
                        <span className="concept-card__name">{c.label}</span>
                        <span className="concept-card__need">{c.need}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>
    </div>
  )
}
