import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Link2, PenLine, AlertCircle, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import { useAdStore } from '../stores/adStore'
import { AD_CATEGORIES } from '../utils/adConcepts'
import {
  buildSearchQuery, extractProductType, parseYoutubeVideoId, searchAdVideos, getVideoInfo, YoutubeQuotaError,
} from '../services/youtubeService'
import { analyzeFromVideo, analyzeFromDescription } from '../services/homageAnalyzer'
import { presentableErrorMessage } from '../utils/errorMessage'
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

  // 제품군은 productName 의 마지막 낱말로 어림잡는다("미리집 수분크림" → "수분크림") — 단, 그
  // 낱말이 용량·수량 표기("50ml", "2개입")면 건너뛴다. 상세 근거는 extractProductType 참고.
  const guessedType = extractProductType(analysis?.productName || '')

  const [tab, setTab] = useState<Tab>('search')
  const [query, setQuery] = useState(buildSearchQuery(guessedType, subLabel))
  const [candidates, setCandidates] = useState<HomageCandidate[]>([])
  const [shown, setShown] = useState(PAGE_SIZE)
  const [urlInput, setUrlInput] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  // 진행 중이던 분석이 나중에 끝나도 스토어에 반영되지 않게 막는 취소 플래그.
  // commit() 은 컴포넌트 상태가 아니라 전역 스토어(setAdConcept)를 직접 건드리므로,
  // 언마운트(=backToTemplate 로 탈출하거나 다른 경로로 화면을 떠남) 후에도 진행 중이던
  // build() 프라미스는 계속 실행된다 — ref 로 "이 인스턴스는 끝났다"를 표시해 결과를 버린다.
  const cancelledRef = useRef(false)
  useEffect(() => {
    // StrictMode(main.tsx 가 앱 전체를 <React.StrictMode> 로 감싼다)는 개발 모드에서
    // 이펙트를 setup → cleanup → setup 순으로 이중 호출한다. cleanup 에서만 값을 세우면
    // useRef(false) 는 최초 렌더에서만 초기화되므로, 합성 cleanup 이 세운 true 를 두 번째
    // setup 이 되돌리지 않아 마운트 직후부터 취소 상태로 굳어버린다. 그래서 setup 에서도
    // 반드시 false 로 리셋한다.
    cancelledRef.current = false
    return () => { cancelledRef.current = true }
  }, [])

  // 분석 없이 직접 진입(새로고침 등)한 경우 자료 업로드부터 — 이 저장소의 A3~A5 화면과 동일한 관례
  useEffect(() => {
    if (!analysis) navigate('/source', { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!analysis) return null

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
        // callProxy 등 하위 레이어가 던지는 원문 영어 에러(예: `Proxy error (400): {"error":...`)를
        // 그대로 노출하지 않는다 — A5_Concept.tsx와 같은 가드(짧고 한글 섞인 문장만 통과)를 쓴다.
        setError(presentableErrorMessage(e, '검색에 실패했어요.'))
      }
    } finally { setBusy(false) }
  }

  /** 세 입구가 공통으로 쓰는 확정 경로 */
  const commit = async (build: () => Promise<Parameters<typeof setAdConcept>[0]>) => {
    setError(''); setBusy(true)
    try {
      const patch = await build()
      // 분석이 도는 사이 사용자가 "그냥 템플릿에서 고르기"로 탈출했다면, 늦게 도착한
      // 결과는 절대 스토어에 반영하지 않는다 — 탈출이 최종 상태여야 한다.
      if (cancelledRef.current) return
      setAdConcept({ structureSource: 'homage', structureId: HOMAGE_STRUCTURE_ID, ...patch })
      navigate('/concept')
    } catch (e) {
      if (cancelledRef.current) return
      // getVideoInfo(URL 입구)와 searchAdVideos(검색)는 같은 유튜브 API 쿼터를 공유한다.
      // 검색 쿼터가 소진돼 URL 탭으로 유도됐는데 거기서도 막히면, 남은 유일한 안전한
      // 입구인 '설명'으로 다시 유도한다 — 빨간 에러로 막다른 길을 만들지 않는다.
      if (e instanceof YoutubeQuotaError) {
        setNotice('오늘 자동검색 한도를 다 썼어요. 설명으로 진행해주세요.')
        setTab('describe')
      } else {
        setError(presentableErrorMessage(e, '분석에 실패했어요.'))
      }
    } finally {
      if (!cancelledRef.current) setBusy(false)
    }
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
    // 먼저 취소 플래그부터 세운다 — 아래 setAdConcept 이후 언마운트되기 전에, 이 시점 이후로
    // 끝나는 commit() 의 build() 결과가 조용히 오마주 상태를 되살리지 못하게 막는다.
    cancelledRef.current = true
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
            <button key={id} onClick={() => { setTab(id); setError(''); setNotice(''); }}
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
              onKeyDown={e => { if (e.key === 'Enter' && !busy && query.trim()) runSearch() }} />
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
