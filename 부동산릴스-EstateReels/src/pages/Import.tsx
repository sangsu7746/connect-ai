import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Link2, ClipboardType, ImagePlus, Loader2, AlertTriangle, CheckCircle2, ArrowRight, X } from 'lucide-react'
import { clsx } from 'clsx'
import { importFromUrl, filesToImages } from '../services/blogImport'
import { parseListing } from '../services/estateParser'
import { useEstateStore } from '../stores/estateStore'
import type { BlogImage, BlogSource } from '../types'

type Mode = 'url' | 'paste'

export default function Import() {
  const nav = useNavigate()
  const store = useEstateStore()
  const fileInput = useRef<HTMLInputElement>(null)

  const [mode, setMode] = useState<Mode>('url')
  const [url, setUrl] = useState('')
  const [pasteTitle, setPasteTitle] = useState('')
  const [pasteText, setPasteText] = useState('')
  const [importedSource, setImportedSource] = useState<BlogSource | null>(null)
  const [images, setImages] = useState<BlogImage[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [drag, setDrag] = useState(false)

  const importedText = importedSource?.rawText || ''

  const handleImportUrl = async () => {
    if (!url.trim()) return
    setBusy(true); setError(''); setNote('')
    try {
      const r = await importFromUrl(url.trim())
      setImportedSource(r.source)
      setImages(prev => [...prev, ...r.images])
      if (r.imageNote) setNote(r.imageNote)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }

  const handleFiles = async (files: FileList | null) => {
    if (!files || !files.length) return
    const imgs = await filesToImages(Array.from(files))
    setImages(prev => [...prev, ...imgs])
  }

  const removeImg = (id: string) => setImages(prev => prev.filter(i => i.id !== id))

  const canNext = (mode === 'url' ? importedText : pasteText).trim().length > 20

  const handleNext = () => {
    const text = mode === 'url' ? importedText : pasteText
    const title = mode === 'url' ? (importedSource?.title || '') : pasteTitle
    if (text.trim().length < 20) { setError('본문이 너무 짧아요. URL을 가져오거나 내용을 붙여넣어 주세요.'); return }
    const source: BlogSource = mode === 'url' && importedSource
      ? importedSource
      : { url: '', title, rawText: text, fetchedVia: 'paste' }
    store.setImport(source, images)
    store.setListing(parseListing(text, title))
    nav('/review')
  }

  return (
    <div style={{ padding: '18px 16px 120px', maxWidth: 560, margin: '0 auto' }} className="animate-fade-in">
      {/* 모드 토글 */}
      <div className="seg" style={{ marginBottom: 16 }}>
        <button className={clsx('seg__btn', mode === 'url' && 'active')} onClick={() => { setMode('url'); setError('') }}>
          <Link2 size={15} style={{ marginRight: 6, verticalAlign: -2 }} />URL 자동
        </button>
        <button className={clsx('seg__btn', mode === 'paste' && 'active')} onClick={() => { setMode('paste'); setError('') }}>
          <ClipboardType size={15} style={{ marginRight: 6, verticalAlign: -2 }} />붙여넣기
        </button>
      </div>

      {mode === 'url' ? (
        <div style={{ marginBottom: 18 }}>
          <label className="input-label"><Link2 size={15} color="var(--color-gold-400)" /> 블로그 주소</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input className="input" placeholder="blog.naver.com/... 또는 티스토리 주소"
              value={url} onChange={e => setUrl(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleImportUrl()} />
            <button className="btn btn-primary" style={{ flexShrink: 0 }} disabled={busy || !url.trim()} onClick={handleImportUrl}>
              {busy ? <Loader2 size={16} className="animate-spin" /> : '가져오기'}
            </button>
          </div>
          <p style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)', marginTop: 8, lineHeight: 1.5 }}>
            공개 블로그를 외부 리더로 불러옵니다. 네이버 등은 자동수집이 막힐 수 있어요 —
            그럴 땐 <b style={{ color: 'var(--color-text-secondary)' }}>붙여넣기</b>로 진행하세요.
          </p>
          {importedText && (
            <div className="card" style={{ marginTop: 12, borderColor: 'var(--color-border-gold)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                <CheckCircle2 size={16} color="var(--color-success)" />
                <b style={{ fontSize: '0.9rem' }}>{importedSource?.title || '본문을 가져왔어요'}</b>
              </div>
              <p style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', margin: 0 }}>
                {importedText.length.toLocaleString()}자 · 사진 {images.length}장
              </p>
            </div>
          )}
        </div>
      ) : (
        <div style={{ marginBottom: 18 }}>
          <label className="input-label">제목 (선택)</label>
          <input className="input" placeholder="예: 송파 헬리오시티 84㎡ 매매" value={pasteTitle}
            onChange={e => setPasteTitle(e.target.value)} style={{ marginBottom: 12 }} />
          <label className="input-label"><ClipboardType size={15} color="var(--color-gold-400)" /> 블로그 본문 붙여넣기</label>
          <textarea className="input" style={{ minHeight: 180 }}
            placeholder="블로그 글 전체를 복사해 붙여넣으세요. 가격·평형·교통·학군 등이 있으면 자동으로 정리됩니다."
            value={pasteText} onChange={e => setPasteText(e.target.value)} />
        </div>
      )}

      {/* 사진 */}
      <label className="input-label"><ImagePlus size={15} color="var(--color-gold-400)" /> 매물 사진 ({images.length})</label>
      <div
        className={clsx('upload-zone', drag && 'drag-over')}
        onClick={() => fileInput.current?.click()}
        onDragOver={e => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); handleFiles(e.dataTransfer.files) }}
        style={{ padding: '22px 16px', marginBottom: 12 }}
      >
        <ImagePlus size={30} color="var(--color-gold-400)" />
        <div>
          <div style={{ fontWeight: 800, fontSize: '0.92rem' }}>사진 올리기 (드래그 · 클릭)</div>
          <div style={{ fontSize: '0.76rem', color: 'var(--color-text-muted)' }}>JPG · PNG · HEIC — 여러 장 한 번에</div>
        </div>
        <input ref={fileInput} type="file" accept="image/*,.heic,.heif" multiple style={{ display: 'none' }}
          onChange={e => handleFiles(e.target.files)} />
      </div>

      {images.length > 0 && (
        <div className="photo-grid" style={{ marginBottom: 8 }}>
          {images.map((img, i) => (
            <div key={img.id} className="photo-item">
              <img src={img.src} alt="" />
              <span className="photo-item__idx">{i + 1}</span>
              <button className="photo-item__remove" onClick={() => removeImg(img.id)}><X size={14} /></button>
            </div>
          ))}
        </div>
      )}

      {note && (
        <div className="card" style={{ display: 'flex', gap: 8, alignItems: 'flex-start', borderColor: 'var(--color-border-gold)', marginBottom: 12 }}>
          <AlertTriangle size={15} color="var(--color-warning)" style={{ flexShrink: 0, marginTop: 2 }} />
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>{note}</span>
        </div>
      )}
      {error && (
        <div className="card" style={{ display: 'flex', gap: 8, alignItems: 'flex-start', borderColor: 'rgba(240,99,122,0.4)', marginBottom: 12 }}>
          <AlertTriangle size={15} color="var(--color-error)" style={{ flexShrink: 0, marginTop: 2 }} />
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>{error}</span>
        </div>
      )}

      <button className="btn btn-gold btn-lg btn-full" disabled={!canNext} onClick={handleNext}
        style={{ position: 'sticky', bottom: 16, marginTop: 8 }}>
        매물 정보 확인하기 <ArrowRight size={18} />
      </button>
    </div>
  )
}
