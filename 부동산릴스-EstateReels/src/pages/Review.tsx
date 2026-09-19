import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowRight, Sparkles, Loader2, Check, ChevronUp, ChevronDown, X, Eye, EyeOff, Wand2, KeyRound,
} from 'lucide-react'
import { useEstateStore } from '../stores/estateStore'
import { countFilled } from '../services/estateParser'
import { enhanceListing, hasGeminiKey, setGeminiKey } from '../services/aiEnhance'
import { categoryOf, PROPERTY_KINDS } from '../types'
import type { ListingInfo, DealType, PropertyType } from '../types'

const DEAL_TYPES: DealType[] = ['매매', '전세', '월세', '분양', '기타']
const PROP_TYPES: PropertyType[] = ['아파트', '오피스텔', '빌라/주택', '상가/사무실', '공장·창고', '토지', '분양권', '기타']

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div>
      <label className="input-label" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--color-text-secondary)' }}>{label}</label>
      <input className="input" value={value} placeholder={placeholder} onChange={e => onChange(e.target.value)} />
    </div>
  )
}

export default function Review() {
  const nav = useNavigate()
  const { source, listing, images, setListing, setListingArray, moveImage, toggleImage, removeImage } = useEstateStore()

  const [ai, setAi] = useState<'idle' | 'busy' | 'done' | 'error'>('idle')
  const [aiMsg, setAiMsg] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [showAdv, setShowAdv] = useState(false)

  useEffect(() => {
    if (!source) nav('/import', { replace: true })
  }, [source, nav])
  if (!source) return null

  const filled = countFilled(listing)
  const selectedCount = images.filter(i => i.selected).length
  const kinds = PROPERTY_KINDS.filter(k => k.category === categoryOf(listing.propertyType))
  const isCommercialLand = ['상가', '공장·창고', '토지'].includes(categoryOf(listing.propertyType))

  const arrField = (field: 'schools' | 'amenities' | 'features' | 'investPoints', label: string, ph: string) => (
    <div>
      <label className="input-label" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--color-text-secondary)' }}>{label}</label>
      <input className="input" placeholder={ph}
        value={listing[field].join(', ')}
        onChange={e => setListingArray(field, e.target.value.split(',').map(s => s.trim()).filter(Boolean))} />
    </div>
  )

  const runAi = async () => {
    if (!hasGeminiKey()) { setShowKey(true); return }
    setAi('busy'); setAiMsg('')
    try {
      const patch = await enhanceListing(source.rawText, listing, useEstateStore.getState().config.conceptId)
      setListing(patch)
      setAi('done'); setAiMsg('AI가 문구를 다듬었어요. 필요하면 더 고쳐도 돼요.')
    } catch (e) {
      setAi('error')
      setAiMsg(e instanceof Error && e.message === 'NO_KEY' ? 'Gemini 키가 필요해요.' : 'AI 다듬기에 실패했어요. 템플릿 문구로 진행해도 좋아요.')
      if (e instanceof Error && e.message === 'NO_KEY') setShowKey(true)
    }
  }

  const set = (patch: Partial<ListingInfo>) => setListing(patch)

  return (
    <div style={{ padding: '16px 16px 120px', maxWidth: 560, margin: '0 auto' }} className="animate-fade-in">
      <div className="flex-between" style={{ marginBottom: 4 }}>
        <h2 style={{ fontSize: '1.05rem', fontWeight: 800 }}>매물 정보 확인</h2>
        <span className="badge badge-success"><Check size={12} /> {filled}개 항목 인식</span>
      </div>
      <p style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', marginBottom: 14 }}>
        블로그에서 읽은 내용이에요. 틀린 부분만 고치면 됩니다.
      </p>

      {/* AI 다듬기 */}
      <div className="card" style={{ marginBottom: 16, background: 'var(--gradient-card)', borderColor: 'var(--color-border-gold)' }}>
        <div className="flex-between">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Wand2 size={18} color="var(--color-gold-400)" />
            <div>
              <div style={{ fontWeight: 800, fontSize: '0.9rem' }}>AI로 다듬기 <span className="badge badge-muted" style={{ marginLeft: 4 }}>선택</span></div>
              <div style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)' }}>타이틀·셀링포인트를 매끄럽게</div>
            </div>
          </div>
          <button className="btn btn-outline btn-sm" onClick={runAi} disabled={ai === 'busy'}>
            {ai === 'busy' ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />} 다듬기
          </button>
        </div>
        {showKey && (
          <div style={{ marginTop: 10, display: 'flex', gap: 6 }}>
            <input className="input" style={{ fontSize: '0.8rem' }} placeholder="Gemini API 키 붙여넣기 (기기에만 저장)"
              value={keyInput} onChange={e => setKeyInput(e.target.value)} />
            <button className="btn btn-gold btn-sm" onClick={() => { setGeminiKey(keyInput); setShowKey(false); runAi() }}>
              <KeyRound size={13} /> 저장
            </button>
          </div>
        )}
        {aiMsg && <p style={{ fontSize: '0.78rem', color: ai === 'error' ? 'var(--color-warning)' : 'var(--color-success)', marginTop: 8 }}>{aiMsg}</p>}
      </div>

      {/* 기본 정보 */}
      <div style={{ display: 'grid', gap: 12, marginBottom: 18 }}>
        <Field label="타이틀" value={listing.title} onChange={v => set({ title: v })} placeholder="매물 대표 이름" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div>
            <label className="input-label" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--color-text-secondary)' }}>거래유형</label>
            <select className="input" value={listing.dealType} onChange={e => set({ dealType: e.target.value as DealType })}>
              {DEAL_TYPES.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
          <div>
            <label className="input-label" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--color-text-secondary)' }}>부동산 유형</label>
            <select className="input" value={listing.propertyType} onChange={e => set({ propertyType: e.target.value as PropertyType, kind: '' })}>
              {PROP_TYPES.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
        </div>
        {kinds.length > 0 && (
          <div>
            <label className="input-label" style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--color-text-secondary)' }}>세부 성격 (물건 종류)</label>
            <select className="input" value={listing.kind} onChange={e => set({ kind: e.target.value })}>
              <option value="">미지정 / 자동</option>
              {kinds.map(k => <option key={k.id} value={k.id}>{k.label}</option>)}
            </select>
          </div>
        )}
        <Field label="가격" value={listing.priceText} onChange={v => set({ priceText: v })} placeholder="예: 매매 21억 / 보증금 1억 · 월 250" />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <Field label="면적" value={listing.areaText} onChange={v => set({ areaText: v })} placeholder="84㎡ / 34평" />
          <Field label="방/욕실" value={listing.rooms} onChange={v => set({ rooms: v })} placeholder="방3 · 욕실2" />
          <Field label="층" value={listing.floorText} onChange={v => set({ floorText: v })} placeholder="중층 / 12층" />
          <Field label="향" value={listing.direction} onChange={v => set({ direction: v })} placeholder="남향" />
        </div>
        <Field label="지역" value={listing.region} onChange={v => set({ region: v })} placeholder="서울 송파구 가락동" />
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 10 }}>
          <Field label="가까운 역" value={listing.station} onChange={v => set({ station: v })} placeholder="8호선 송파역" />
          <Field label="도보" value={listing.walkText} onChange={v => set({ walkText: v })} placeholder="도보 5분" />
        </div>
        {arrField('schools', '학군 · 학교', '예: 가락초, 잠실중')}
        {arrField('amenities', '편의시설', '예: 이마트, 공원, 병원')}
        {arrField('features', '셀링 포인트', '예: 올수리, 남향, 즉시입주')}
        {arrField('investPoints', '투자 포인트 · 호재', '예: 재건축, GTX')}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <Field label="관리비" value={listing.manageText} onChange={v => set({ manageText: v })} placeholder="관리비" />
          <Field label="입주 가능" value={listing.moveInText} onChange={v => set({ moveInText: v })} placeholder="즉시입주" />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 10 }}>
          <Field label="문의 · 연락처" value={listing.contact} onChange={v => set({ contact: v })} placeholder="010-0000-0000" />
          <Field label="매물번호 (선택)" value={listing.listingNo} onChange={v => set({ listingNo: v })} placeholder="예: 1532 / H190" />
        </div>
      </div>

      {/* 상가·공장·토지 추가 정보 (수익률·용도지역·도로·유동인구·업종) */}
      <div style={{ marginBottom: 18 }}>
        <button className="btn btn-ghost btn-sm" onClick={() => setShowAdv(s => !s)} style={{ fontSize: '0.82rem', padding: '4px 0', fontWeight: 700 }}>
          {(showAdv || isCommercialLand) ? <ChevronUp size={15} /> : <ChevronDown size={15} />} 상가·공장·토지 추가 정보
          <span style={{ color: 'var(--color-text-muted)', fontWeight: 400, marginLeft: 6, fontSize: '0.76rem' }}>수익률·용도지역·도로·유동인구</span>
        </button>
        {(showAdv || isCommercialLand) && (
          <div style={{ display: 'grid', gap: 12, marginTop: 8 }}>
            <Field label="수익률 · 임대수익" value={listing.yieldText} onChange={v => set({ yieldText: v })} placeholder="예: 수익률 5.2% / 보증금 5천 · 월 250" />
            <Field label="용도지역 · 지목" value={listing.zoningText} onChange={v => set({ zoningText: v })} placeholder="예: 제2종일반주거 / 계획관리 / 지목: 전" />
            <Field label="도로 · 접근성" value={listing.accessText} onChange={v => set({ accessText: v })} placeholder="예: 6m 도로 접함 / IC 5분 / 대로변" />
            <Field label="유동인구 · 배후수요" value={listing.footfallText} onChange={v => set({ footfallText: v })} placeholder="예: 일 유동 2만 / 배후 3,200세대" />
            <Field label="추천 업종 · 용도" value={listing.usageText} onChange={v => set({ usageText: v })} placeholder="예: 카페·병원 적합 / 제조·물류" />
          </div>
        )}
      </div>

      {/* 사진 순서 */}
      <div className="flex-between" style={{ marginBottom: 10 }}>
        <h3 style={{ fontSize: '0.95rem', fontWeight: 800 }}>사진 순서 · 선택</h3>
        <span style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)' }}>{selectedCount}장 사용</span>
      </div>
      {images.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', color: 'var(--color-text-muted)', fontSize: '0.82rem' }}>
          사진이 없어요. 뒤로 가서 사진을 올리면 더 좋은 영상이 됩니다. (없어도 배경 카드로 제작돼요)
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 8 }}>
          {images.map((img, i) => (
            <div key={img.id} className="card" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: 8, opacity: img.selected ? 1 : 0.5 }}>
              <img src={img.src} alt="" style={{ width: 56, height: 56, objectFit: 'cover', borderRadius: 8, flexShrink: 0 }} />
              <span style={{ flex: 1, fontSize: '0.82rem', color: 'var(--color-text-secondary)' }}>{i + 1}번째 컷</span>
              <button className="btn btn-ghost btn-icon btn-sm" onClick={() => toggleImage(img.id)} title="사용/제외">
                {img.selected ? <Eye size={16} color="var(--color-gold-400)" /> : <EyeOff size={16} />}
              </button>
              <button className="btn btn-ghost btn-icon btn-sm" onClick={() => moveImage(img.id, -1)} disabled={i === 0}><ChevronUp size={16} /></button>
              <button className="btn btn-ghost btn-icon btn-sm" onClick={() => moveImage(img.id, 1)} disabled={i === images.length - 1}><ChevronDown size={16} /></button>
              <button className="btn btn-ghost btn-icon btn-sm" onClick={() => removeImage(img.id)}><X size={16} color="var(--color-error)" /></button>
            </div>
          ))}
        </div>
      )}

      <button className="btn btn-gold btn-lg btn-full" onClick={() => nav('/concept')}
        style={{ position: 'sticky', bottom: 16, marginTop: 18 }}>
        컨셉 선택하기 <ArrowRight size={18} />
      </button>
    </div>
  )
}
