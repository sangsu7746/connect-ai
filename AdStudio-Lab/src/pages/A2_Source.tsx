import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Link2, FileUp, Type, Sparkles, AlertTriangle } from 'lucide-react'
import { clsx } from 'clsx'
import { useAdStore } from '../stores/adStore'
import { useUserStore } from '../stores/userStore'
import { analyzeProduct } from '../services/adService'

type Tab = 'text' | 'url' | 'file'

// 1단계: 자료 업로드 — 텍스트/URL/파일 세 방식 모두 지원, 분석은 서버(Gemini)에서
export default function A2_Source() {
  const navigate = useNavigate()
  const user = useUserStore(s => s.user)
  const { setSource, setAnalysis } = useAdStore()

  const [tab, setTab] = useState<Tab>('text')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const [fileName, setFileName] = useState('')
  const [imageDataUrl, setImageDataUrl] = useState('')
  const [docFile, setDocFile] = useState<{ base64: string; mimeType: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const tabs: { id: Tab; icon: typeof Type; label: string }[] = [
    { id: 'text', icon: Type, label: '텍스트' },
    { id: 'url', icon: Link2, label: 'URL' },
    { id: 'file', icon: FileUp, label: '파일' },
  ]

  const handleFile = async (f: File) => {
    setError('')
    if (f.type.startsWith('image/')) {
      // 상품 페이지 스크린샷 — Gemini Vision이 이미지 속 텍스트를 읽어 분석한다
      // base64 변환 시 1.33배로 커지고 프록시/함수 요청 한도가 10MB라 4MB로 제한
      if (f.size > 4 * 1024 * 1024) {
        setError('이미지가 너무 커요 (4MB 이하). 상품 설명 부분만 잘라서 캡처해 주세요.')
        return
      }
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result))
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(f)
      })
      setImageDataUrl(dataUrl)
      setText('')
      setDocFile(null)
      setFileName(f.name)
    } else if (f.type === 'application/pdf' || /\.pdf$/i.test(f.name)) {
      // PDF — Gemini가 문서를 네이티브로 읽는다 (표·이미지 포함, 추출 라이브러리 불필요)
      if (f.size > 6 * 1024 * 1024) {
        setError('PDF가 너무 커요 (6MB 이하). 제품 소개 부분만 추려서 저장해 주세요.')
        return
      }
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result))
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(f)
      })
      setDocFile({ base64: dataUrl.split(',')[1] || '', mimeType: 'application/pdf' })
      setText('')
      setImageDataUrl('')
      setFileName(f.name)
    } else if (/\.docx$/i.test(f.name) || f.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
      // 워드(.docx) — mammoth로 브라우저에서 텍스트를 추출해 텍스트 분석 경로로 보낸다
      try {
        const mammoth = await import('mammoth')
        const { value } = await mammoth.extractRawText({ arrayBuffer: await f.arrayBuffer() })
        if (!value || value.trim().length < 20) {
          setError('워드 문서에서 읽을 텍스트를 찾지 못했어요. 내용을 확인해 주세요.')
          return
        }
        setText(value.trim())
        setImageDataUrl('')
        setDocFile(null)
        setFileName(f.name)
      } catch (e) {
        console.error('docx 추출 실패:', e)
        setError('워드 문서를 읽지 못했어요. PDF로 저장해서 올리면 확실하게 분석돼요.')
      }
    } else if (/\.(doc|hwp|hwpx|ppt|pptx|xls|xlsx|odt|odp|ods|key|pages|numbers)$/i.test(f.name)) {
      // 파워포인트·엑셀·한글·구버전 워드 등 — 직접 읽기 미지원 문서는 모두 PDF 변환 안내
      setError('이 문서 형식은 직접 읽을 수 없어요. PDF로 저장해서 올려주세요. (파워포인트·엑셀·한글 모두 "다른 이름으로 저장 → PDF"면 돼요)')
    } else if (f.type === 'text/plain' || /\.(txt|md|csv)$/i.test(f.name)) {
      const content = await f.text()
      setText(content)
      setImageDataUrl('')
      setDocFile(null)
      setFileName(f.name)
    } else {
      setError('지원 형식: PDF · 워드(.docx) · 텍스트(.txt/.md/.csv) · 이미지(스크린샷) — 그 외 문서는 PDF로 저장해서 올려주세요.')
    }
  }

  const canAnalyze =
    tab === 'url' ? url.trim().length > 0
    : tab === 'file' ? text.trim().length > 0 || imageDataUrl.length > 0 || docFile !== null
    : text.trim().length > 0

  const handleAnalyze = async () => {
    if (!user) {
      setError('분석은 로그인 후 이용할 수 있어요.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const input =
        tab === 'url' ? { url: url.trim() }
        : tab === 'file' && docFile ? { document: docFile }
        : tab === 'file' && imageDataUrl ? { imageDataUrl }
        : { text: text.trim() }
      const analysis = await analyzeProduct(input)
      setSource(tab === 'url' || imageDataUrl ? '' : text.trim(), tab === 'url' ? url.trim() : '')
      setAnalysis(analysis)
      navigate('/adconcept')
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg === 'LOGIN_REQUIRED' ? '분석은 로그인 후 이용할 수 있어요.' : msg)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ padding: '24px 16px', paddingBottom: 110, maxWidth: 540, margin: '0 auto' }}>
      <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.88rem', marginBottom: 16 }}>
        제품 URL, 설명서 PDF, 또는 텍스트를 첨부해 주세요.
      </p>

      {/* 탭 */}
      <div style={{
        display: 'flex', gap: 6, marginBottom: 16, padding: 4,
        background: 'rgba(15, 15, 24, 0.8)', borderRadius: 'var(--radius-md)',
        border: '1px solid var(--color-border-cyan)', backdropFilter: 'blur(12px)',
      }}>
        {tabs.map(t => (
          <button
            key={t.id}
            className={clsx('btn btn-sm', tab === t.id ? 'btn-primary' : 'btn-outline')}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
              padding: '10px 14px', borderRadius: 'var(--radius-sm)', fontWeight: 700,
              background: tab === t.id ? 'var(--gradient-cyber)' : 'transparent',
              color: tab === t.id ? '#07070d' : 'var(--color-text-secondary)',
              border: tab === t.id ? 'none' : '1px solid transparent',
              boxShadow: tab === t.id ? 'var(--shadow-cyan)' : 'none',
              transition: 'var(--transition-normal)',
            }}
            onClick={() => { setTab(t.id); setError('') }}
          >
            <t.icon size={16} color={tab === t.id ? '#07070d' : 'var(--color-cyber-cyan)'} /> {t.label}
          </button>
        ))}
      </div>

      {/* 텍스트 입력 */}
      {tab === 'text' && (
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder={'제품 이름, 주요 특징, 타겟 고객 등을 입력하세요.'}
          style={{
            width: '100%', minHeight: 180, padding: 16, borderRadius: 'var(--radius-md)',
            background: 'var(--color-bg-card)', border: '1px solid var(--color-border-cyan)',
            color: 'var(--color-text-primary)', fontSize: '0.92rem', resize: 'vertical',
            boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.5)',
            outline: 'none', transition: 'var(--transition-normal)',
          }}
        />
      )}

      {/* URL 입력 */}
      {tab === 'url' && (
        <input
          type="url"
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="https://제품-사이트-주소.com"
          style={{
            width: '100%', padding: '16px 18px', borderRadius: 'var(--radius-md)',
            background: 'var(--color-bg-card)', border: '1px solid var(--color-border-cyan)',
            color: 'var(--color-text-primary)', fontSize: '0.95rem',
            outline: 'none', boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.5)',
          }}
        />
      )}

      {/* 파일 업로드 */}
      {tab === 'file' && (
        <div
          onClick={() => fileInput.current?.click()}
          style={{
            padding: '36px 20px', borderRadius: 'var(--radius-md)', textAlign: 'center', cursor: 'pointer',
            background: 'var(--color-bg-card)', border: '2px dashed var(--color-border-cyan)',
            boxShadow: 'var(--shadow-sm)', transition: 'var(--transition-normal)',
          }}
        >
          <FileUp size={30} color="var(--color-cyber-cyan)" style={{ marginBottom: 10, filter: 'drop-shadow(0 0 8px rgba(0,240,255,0.4))' }} />
          <p style={{ fontWeight: 800, fontSize: '0.95rem', marginBottom: 4, color: '#fff' }}>
            {fileName || '파일 첨부하기'}
          </p>
          <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.78rem', lineHeight: 1.4 }}>
            제품 설명서 (PDF · Word · TXT) 또는 상품 페이지 캡처 이미지
          </p>
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.docx,.txt,.md,.csv,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,image/*"
            style={{ display: 'none' }}
            onChange={e => e.target.files?.[0] && handleFile(e.target.files[0])}
          />
        </div>
      )}

      {/* 파일 탭 미리보기 */}
      {tab === 'file' && text && (
        <p style={{ marginTop: 12, fontSize: '0.82rem', color: 'var(--color-cyber-cyan)', fontWeight: 600 }}>
          ✓ {text.length.toLocaleString()}자 읽음 완료 — 분석하기를 누르면 이 내용으로 분석돼요.
        </p>
      )}
      {tab === 'file' && imageDataUrl && (
        <div style={{ marginTop: 12, display: 'flex', gap: 12, alignItems: 'center', padding: 10, background: 'rgba(0,240,255,0.06)', borderRadius: 12, border: '1px solid rgba(0,240,255,0.2)' }}>
          <img
            src={imageDataUrl}
            alt="업로드한 스크린샷 미리보기"
            style={{
              width: 72, height: 72, objectFit: 'cover', borderRadius: 8,
              border: '1px solid var(--color-border-cyan)',
            }}
          />
          <p style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', margin: 0 }}>
            스크린샷 준비 완료 — AI가 이미지 속 텍스트와 상품 디자인을 정밀 분석합니다.
          </p>
        </div>
      )}
      {tab === 'file' && docFile && (
        <p style={{ marginTop: 10, fontSize: '0.78rem', color: 'var(--color-text-muted)' }}>
          📄 {fileName} 준비 완료 — 분석하기를 누르면 AI가 문서 내용(표·이미지 포함)을 읽어요.
        </p>
      )}

      {error && (
        <div style={{
          marginTop: 14, padding: '10px 12px', borderRadius: 10, display: 'flex', gap: 8,
          alignItems: 'flex-start', background: 'rgba(255,90,90,0.08)',
          border: '1px solid rgba(255,90,90,0.35)', fontSize: '0.82rem',
        }}>
          <AlertTriangle size={15} color="#ff5a5a" style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      )}

      <button
        className="btn btn-primary btn-lg"
        style={{ width: '100%', marginTop: 18 }}
        disabled={!canAnalyze || busy}
        onClick={handleAnalyze}
      >
        <Sparkles size={17} /> {busy ? 'Gemini 분석 중…' : '분석하기'}
      </button>
    </div>
  )
}
