import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import { ArrowRight, Captions, Phone, Clock, Smartphone, Square, Monitor, Images, Wand2, Mic, KeyRound, Building2 } from 'lucide-react'
import { useEstateStore } from '../stores/estateStore'
import { conceptsForCategory, recommendConcept } from '../utils/estateConcepts'
import { estimateSceneCount } from '../utils/storyboard'
import { hasGeminiKey } from '../services/gemini'
import { categoryOf, PROPERTY_KINDS } from '../types'
import type { DurationSec, Aspect, PropertyCategory } from '../types'

const CATEGORIES: PropertyCategory[] = ['아파트', '주택', '오피스텔', '상가', '공장·창고', '토지']

const DURATIONS: { v: DurationSec; label: string; use: string; rec?: boolean }[] = [
  { v: 30, label: '티저 30초', use: '숏츠·릴스·카톡 공유 — 조회수 최상위 레인', rec: true },
  { v: 60, label: '핵심 1분', use: '피드·인스타 — 핵심만 빠르게' },
  { v: 180, label: '완전공개 3분', use: '블로그 상단·상세 소개' },
]
const ASPECTS: { v: Aspect; label: string; icon: typeof Smartphone }[] = [
  { v: '9:16', label: '세로', icon: Smartphone },
  { v: '1:1', label: '정사각', icon: Square },
  { v: '16:9', label: '가로', icon: Monitor },
]

export default function Concept() {
  const nav = useNavigate()
  const { listing, source, config, setConfig, selectedImages } = useEstateStore()
  const [category, setCategory] = useState<PropertyCategory>(() => {
    const c = categoryOf(listing.propertyType)
    return c === '기타' ? '아파트' : c
  })

  useEffect(() => { if (!source) nav('/import', { replace: true }) }, [source, nav])
  // 진입 시: 현재 선택된 컨셉이 이 물건 카테고리에 안 맞으면, 세부성격에 맞는 컨셉을 추천 선택
  useEffect(() => {
    const fit = conceptsForCategory(category).some(c => c.id === config.conceptId)
    if (!fit) setConfig({ conceptId: recommendConcept(category, listing.kind) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  if (!source) return null

  const photos = selectedImages()
  const sceneCount = estimateSceneCount(config.duration)
  const concepts = conceptsForCategory(category)
  const kindLabel = PROPERTY_KINDS.find(k => k.id === listing.kind)?.label

  const pickCategory = (c: PropertyCategory) => {
    setCategory(c)
    // 새 카테고리에 현재 컨셉이 없으면 추천 컨셉으로 바꾼다
    if (!conceptsForCategory(c).some(x => x.id === config.conceptId)) {
      setConfig({ conceptId: recommendConcept(c, listing.kind) })
    }
  }

  // 다음 단계: 대본·씬 편집(/storyboard)에서 구성 후 자막·나레이션을 확인·수정한다.
  const start = () => nav('/storyboard')

  return (
    <div style={{ padding: '16px 16px 120px', maxWidth: 560, margin: '0 auto' }} className="animate-fade-in">
      {/* 물건 유형(카테고리) */}
      <label className="input-label"><Building2 size={15} color="var(--color-gold-400)" /> 물건 유형
        {kindLabel && <span className="badge badge-muted" style={{ marginLeft: 6, fontSize: '0.68rem' }}>{kindLabel}</span>}
      </label>
      <div className="seg" style={{ marginBottom: 18, overflowX: 'auto' }}>
        {CATEGORIES.map(c => (
          <button key={c} className={clsx('seg__btn', category === c && 'active')} onClick={() => pickCategory(c)}
            style={{ fontSize: '0.8rem', whiteSpace: 'nowrap', flex: '1 0 auto' }}>
            {c}
          </button>
        ))}
      </div>

      {/* 컨셉 */}
      <h2 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: 4 }}>어떤 컨셉으로 만들까요?</h2>
      <p style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', marginBottom: 14 }}>
        <b style={{ color: 'var(--color-text-secondary)' }}>{category}</b> 물건에 맞는 스토리 컨셉이에요. 소비자가 궁금해하는 니즈 축으로 구성됩니다.
      </p>
      <div className="concept-grid" style={{ marginBottom: 22 }}>
        {concepts.map(c => (
          <div key={c.id} className={clsx('concept-card', config.conceptId === c.id && 'selected')}
            onClick={() => setConfig({ conceptId: c.id })}>
            <span className="concept-card__emoji">{c.emoji}</span>
            <span className="concept-card__name">{c.label}</span>
            <span className="concept-card__desc">{c.desc}</span>
            <span className="concept-card__need">{c.need}</span>
          </div>
        ))}
      </div>

      {/* 길이 · 용도 */}
      <label className="input-label"><Clock size={15} color="var(--color-gold-400)" /> 영상 길이 · 용도</label>
      <div className="seg" style={{ marginBottom: 6 }}>
        {DURATIONS.map(d => (
          <button key={d.v} className={clsx('seg__btn', config.duration === d.v && 'active')} onClick={() => setConfig({ duration: d.v })} style={{ fontSize: '0.8rem' }}>
            {d.label}
          </button>
        ))}
      </div>
      <p style={{ fontSize: '0.76rem', color: 'var(--color-text-muted)', marginBottom: 18 }}>
        {DURATIONS.find(d => d.v === config.duration)?.use}
        {config.duration === 30 && <b style={{ color: 'var(--color-gold-400)' }}> · 추천</b>}
      </p>

      {/* 비율 */}
      <label className="input-label"><Smartphone size={15} color="var(--color-gold-400)" /> 화면 비율</label>
      <div className="seg" style={{ marginBottom: 18 }}>
        {ASPECTS.map(a => (
          <button key={a.v} className={clsx('seg__btn', config.aspect === a.v && 'active')} onClick={() => setConfig({ aspect: a.v })}>
            <a.icon size={15} style={{ marginRight: 5, verticalAlign: -2 }} />{a.label}
            <span style={{ fontSize: '0.7rem', opacity: 0.7, marginLeft: 4 }}>{a.v}</span>
          </button>
        ))}
      </div>

      {/* AI 옵션 */}
      <div style={{ display: 'grid', gap: 8, marginBottom: 12 }}>
        <ToggleRow icon={Wand2} label="AI 자동 구성" desc="사진 분석·스토리·자막·배치를 AI가" on={config.aiMode} onClick={() => setConfig({ aiMode: !config.aiMode })} />
        <ToggleRow icon={Mic} label="AI 나레이션 음성" desc="대본을 성우 음성으로 (AI)" on={config.narration} onClick={() => setConfig({ narration: !config.narration })} />
        {config.narration && (
          <div className="seg" style={{ marginLeft: 2 }}>
            {(['female', 'male'] as const).map(v => (
              <button key={v} className={clsx('seg__btn', config.voice === v && 'active')} onClick={() => setConfig({ voice: v })}>
                {v === 'female' ? '여성 음성' : '남성 음성'}
              </button>
            ))}
          </div>
        )}
      </div>
      {(config.aiMode || config.narration) && !hasGeminiKey() && (
        <button className="card" onClick={() => nav('/profile')}
          style={{ display: 'flex', gap: 10, alignItems: 'center', width: '100%', textAlign: 'left', marginBottom: 12, borderColor: 'var(--color-border-gold)' }}>
          <KeyRound size={17} color="var(--color-gold-400)" style={{ flexShrink: 0 }} />
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', flex: 1 }}>
            AI 기능은 <b style={{ color: 'var(--color-gold-400)' }}>Gemini 키</b>가 필요해요. 눌러서 등록 → 없으면 기본(템플릿) 구성으로 제작됩니다.
          </span>
          <ArrowRight size={15} color="var(--color-text-muted)" />
        </button>
      )}

      {/* 옵션 */}
      <div style={{ display: 'grid', gap: 8, marginBottom: 18 }}>
        <ToggleRow icon={Captions} label="자막 넣기" desc="핵심 문구를 화면에 표시" on={config.subtitles} onClick={() => setConfig({ subtitles: !config.subtitles })} />
        <ToggleRow icon={Phone} label="마지막에 연락처" desc={listing.contact || '연락처 미입력'} on={config.showContact} onClick={() => setConfig({ showContact: !config.showContact })} />
      </div>

      {/* 요약 */}
      <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, borderColor: 'var(--color-border-gold)' }}>
        <Images size={20} color="var(--color-gold-400)" />
        <div style={{ flex: 1, fontSize: '0.82rem', color: 'var(--color-text-secondary)' }}>
          사진 <b style={{ color: 'var(--color-text-primary)' }}>{photos.length}장</b> · 약 <b style={{ color: 'var(--color-text-primary)' }}>{sceneCount}컷</b> 구성
          {photos.length === 0 && <span style={{ color: 'var(--color-warning)' }}> · 사진 없이 배경 카드로 제작</span>}
        </div>
      </div>

      <button className="btn btn-gold btn-lg btn-full" onClick={start} style={{ position: 'sticky', bottom: 16, marginTop: 8 }}>
        다음: 대본 · 씬 편집 <ArrowRight size={18} />
      </button>
    </div>
  )
}

function ToggleRow({ icon: Icon, label, desc, on, onClick }: { icon: typeof Captions; label: string; desc: string; on: boolean; onClick: () => void }) {
  return (
    <button className="card" onClick={onClick} style={{ display: 'flex', alignItems: 'center', gap: 12, textAlign: 'left', cursor: 'pointer' }}>
      <Icon size={18} color={on ? 'var(--color-gold-400)' : 'var(--color-text-muted)'} />
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 700, fontSize: '0.88rem' }}>{label}</div>
        <div style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)' }}>{desc}</div>
      </div>
      <div style={{
        width: 42, height: 24, borderRadius: 12, background: on ? 'var(--gradient-gold)' : 'var(--color-bg-base)',
        border: '1px solid var(--color-border)', position: 'relative', transition: 'all .2s', flexShrink: 0,
      }}>
        <div style={{
          width: 18, height: 18, borderRadius: '50%', background: on ? '#3a2708' : 'var(--color-text-muted)',
          position: 'absolute', top: 2, left: on ? 21 : 3, transition: 'all .2s',
        }} />
      </div>
    </button>
  )
}
