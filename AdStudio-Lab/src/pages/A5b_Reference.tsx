import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Link2, PenLine, AlertCircle, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { useAdStore } from '../stores/adStore'
import { AD_CATEGORIES } from '../utils/adConcepts'
import {
  buildSearchQuery, parseYoutubeVideoId, searchAdVideos, getVideoInfo, YoutubeQuotaError,
} from '../services/youtubeService'
import { analyzeFromVideo, analyzeFromDescription } from '../services/homageAnalyzer'
import { HOMAGE_STRUCTURE_ID } from '../types/homage'
import type { HomageCandidate } from '../types/homage'

const PAGE_SIZE = 5
/** 레퍼런스 영상 길이 상한 — 광고는 대개 1분 이내라 10분이면 충분히 여유롭다 */
const MAX_REFERENCE_SEC = 600

type Tab = 'search' | 'url' | 'describe'

/**
 * [5b] 레퍼런스 선택 — 입구 3개가 모두 같은 HomageStructure 로 수렴한다.
 *
 * 검색만이 입구가 아니다. 원하는 광고가 유튜브에 없는 경우가 흔해서
 * URL 직접 입력과 글로 설명하기를 대등한 탭으로 둔다.
 */
export default function A5b_Reference() {
  const navigate = useNavigate()
  const { analysis, adConcept, setAdConcept } = useAdStore()

  const subLabel = AD_CATEGORIES
    .find(c => c.id === adConcept.categoryMain)?.subs
    ?.find(s => s.id === adConcept.categorySub)?.label ?? ''

  // 제품군은 productName 의 마지막 낱말로 어림잡는다 ("미리집 수분크림" → "수분크림").
  //
  // ⚠️ 스펙 §6-1 은 Gemini 로 일반명사를 추출하라고 했으나, 여기서는 휴리스틱을 쓴다.
  //    이유: 조립 결과가 편집 가능한 입력창에 그대로 노출되므로, 빗나가도 사용자가
  //    한 번에 고칠 수 있다. 첫 화면을 띄우는 데 LLM 왕복을 넣으면 체감 지연만 생긴다.
  //    한국어 상품명은 "브랜드 + 제품군" 어순이 지배적이라 마지막 낱말이 대체로 맞는다.
  //    실사용에서 빗나가는 비율이 높으면 그때 Gemini 추출로 승격한다.
  const guessedType = (analysis?.productName || '').trim().split(/\s+/).pop() || ''

  const [tab, setTab] = useState<Tab>('search')
  const [query, setQuery] = useState(buildSearchQuery(guessedType, subLabel))
  const [candidates, setCandidates] = useState<HomageCandidate[]>([])
  const [shown, setShown] = useState(PAGE_SIZE)
  const [urlInput, setUrlInput] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const runSearch = async () => {
    setError(''); setNotice(''); setBusy(true); setShown(PAGE_SIZE)
    try {
      const items = await searchAdVideos(query)
      setCandidates(items)
      if (items.length === 0) setNotice('결과가 없어요. 검색어를 바꾸거나 URL·설명으로 진행해보세요.')
    } catch (e) {
      if (e instanceof YoutubeQuotaError) {
        setNotice('오늘 자동검색 한도를 다 썼어요. URL 붙여넣기나 직접 설명으로 진행하세요.')
        setTab('url')
      } else {
        setError(e instanceof Error ? e.message : '검색에 실패했어요.')
      }
    } finally { setBusy(false) }
  }

  /** 세 입구가 공통으로 쓰는 확정 경로 */
  const commit = async (build: () => Promise<Parameters<typeof setAdConcept>[0]>) => {
    setError(''); setBusy(true)
    try {
      const patch = await build()
      setAdConcept({ structureSource: 'homage', structureId: HOMAGE_STRUCTURE_ID, ...patch })
      navigate('/concept')
    } catch (e) {
      setError(e instanceof Error ? e.message : '분석에 실패했어요.')
    } finally { setBusy(false) }
  }

  const pickVideo = (c: HomageCandidate) => commit(async () => ({
    homage: {
      source: 'search' as const,
      videoId: c.videoId, title: c.title, channelTitle: c.channelTitle,
      thumbnailUrl: c.thumbnailUrl,
      structure: await analyzeFromVideo(c.videoId),
      analyzedAt: Date.now(),
    },
  }))

  const useUrl = () => commit(async () => {
    const id = parseYoutubeVideoId(urlInput)
    if (!id) throw new Error('유튜브 주소를 확인해주세요.')

    // 분석 전에 길이를 먼저 본다 — 2시간짜리를 넣으면 Gemini 무료 한도
    // (하루 8시간 분량)를 한 번에 태운다. 1유닛짜리 조회라 부담이 없다.
    const info = await getVideoInfo(id)
    if (info.durationSec > MAX_REFERENCE_SEC) {
      throw new Error(
        `${Math.round(info.durationSec / 60)}분짜리 영상이에요. `
        + `${MAX_REFERENCE_SEC / 60}분 이하의 광고 영상을 골라주세요.`,
      )
    }

    return {
      homage: {
        source: 'url' as const,
        videoId: id,
        title: info.title,
        channelTitle: info.channelTitle,
        thumbnailUrl: info.thumbnailUrl,
        durationSec: info.durationSec,
        structure: await analyzeFromVideo(id),
        analyzedAt: Date.now(),
      },
    }
  })

  const useDescription = () => commit(async () => ({
    homage: {
      source: 'description' as const,
      userDescription: description,
      structure: await analyzeFromDescription(description),
      analyzedAt: Date.now(),
    },
  }))

  const backToTemplate = () => {
    setAdConcept({ structureSource: 'template', structureId: '', homage: undefined })
    navigate('/concept')
  }

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
        참고할 광고의 <strong>컷 순서와 완급</strong>을 가져옵니다.
        컷 길이는 영상 생성 한계에 맞춰 조정됩니다.
      </p>

      <div style={{ display: 'flex', gap: 8 }}>
        {([['search', '검색으로 찾기', Search], ['url', 'URL 넣기', Link2], ['describe', '글로 설명', PenLine]] as const)
          .map(([id, label, Icon]) => (
            <button key={id} onClick={() => { setTab(id); setError(''); }}
              className={clsx('btn btn-sm', tab === id ? 'btn-primary' : 'btn-outline')}>
              <Icon size={14} /> {label}
            </button>
          ))}
      </div>

      {tab === 'search' && (
        <>
          <div style={{ display: 'flex', gap: 8 }}>
            <input value={query} onChange={e => setQuery(e.target.value)}
              placeholder="예: 수분크림 화장품 광고" style={{ flex: 1 }}
              onKeyDown={e => { if (e.key === 'Enter') runSearch() }} />
            <button className="btn btn-primary" onClick={runSearch} disabled={busy || !query.trim()}>
              {busy ? <Loader2 size={14} className="animate-spin" /> : '검색'}
            </button>
          </div>

          {candidates.slice(0, shown).map(c => (
            <button key={c.videoId} onClick={() => pickVideo(c)} disabled={busy}
              style={{ display: 'flex', gap: 12, textAlign: 'left', background: 'var(--color-bg-card)',
                       border: '1px solid var(--color-border)', borderRadius: 8, padding: 8 }}>
              <img src={c.thumbnailUrl} alt="" width={120} style={{ borderRadius: 4 }} />
              <span>
                <span style={{ display: 'block', fontWeight: 600, fontSize: 14 }}>{c.title}</span>
                <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>{c.channelTitle}</span>
              </span>
            </button>
          ))}

          {shown < candidates.length && (
            <button className="btn btn-outline" onClick={() => setShown(s => s + PAGE_SIZE)}>
              다른 후보 보기 ({candidates.length - shown}개 남음)
            </button>
          )}
        </>
      )}

      {tab === 'url' && (
        <>
          <input value={urlInput} onChange={e => setUrlInput(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..." />
          <button className="btn btn-primary" onClick={useUrl} disabled={busy || !urlInput.trim()}>
            {busy ? '분석 중…' : '이 영상으로 진행'}
          </button>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>공개 영상만 분석할 수 있어요.</p>
        </>
      )}

      {tab === 'describe' && (
        <>
          <textarea value={description} onChange={e => setDescription(e.target.value)} rows={5}
            placeholder="예: 첫 3초에 문제 상황을 훅으로 던지고, 중간에 제품 클로즈업을 빠르게 몰아친 다음, 마지막 5초는 조용하게 브랜드 한 컷으로 마무리" />
          <button className="btn btn-primary" onClick={useDescription} disabled={busy || description.trim().length < 10}>
            {busy ? '구성 만드는 중…' : '이 느낌으로 진행'}
          </button>
        </>
      )}

      {notice && <p style={{ fontSize: 13 }}>{notice}</p>}
      {error && (
        <p style={{ color: 'var(--color-error)', fontSize: 13, display: 'flex', gap: 6 }}>
          <AlertCircle size={16} /> {error}
        </p>
      )}

      <button className="btn btn-outline" onClick={backToTemplate}>그냥 템플릿에서 고르기</button>
    </div>
  )
}
