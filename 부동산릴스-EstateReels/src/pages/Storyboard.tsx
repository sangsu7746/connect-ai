// ════════════════════════════════════════════════════════════════
// 대본·씬 편집 — 컨셉/길이로 씬을 "구성"한 뒤, 씬마다 자막·나레이션을 눈으로 보고 고친다.
//   · 자막(화면)과 나레이션(음성)을 분리해 편집 → 둘이 같은 말을 반복하지 않게.
//   · AI 구성(사진분석·스크립트·훅/제목 다듬기)은 여기서 끝내고, Generate는 렌더만.
// ════════════════════════════════════════════════════════════════
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import {
  ArrowRight, Loader2, Wand2, RefreshCw, Mic, Captions, Sparkles, AlertTriangle, RotateCcw, Image as ImageIcon,
  Coins, LogIn, Gift, Trash2, Plus,
} from 'lucide-react'
import { useEstateStore } from '../stores/estateStore'
import { useUserStore } from '../stores/userStore'
import { getConcept } from '../utils/estateConcepts'
import { buildStoryboard, buildStoryboardAI, estimateSceneCount, imageSummary } from '../utils/storyboard'
import { hasGeminiKey, analyzeImages, generateScript, generateHooksAndTitles } from '../services/gemini'
import { buildMarketing } from '../utils/hooks'
import { hookNarration, buildSceneNarration, isRedundantNarration } from '../utils/narration'
import { spendCoins, type SpendError } from '../services/walletService'
import { makeVideoId, COINS_PER_RENDER, FREE_RENDERS, TOPUP_URL, WALLET_SERVICE } from '../services/credits'

// 같은 컨셉·길이로 다시 들어오면 편집 내용을 보존한다(모듈 스코프라 라우트 이동엔 유지, 새 프로젝트(reset)엔 storyboard=null이라 재구성).
let lastComposeSig = ''

const ROLE_LABEL: Record<string, string> = { hook: '훅 · 오프닝', point: '포인트', cta: '마무리 · CTA' }

export default function Storyboard() {
  const nav = useNavigate()
  const store = useEstateStore()
  const { storyboard, images, listing, config, setConfig, setStoryboard, setMarketing, setImageAnalysis, updateScene, addScene, removeScene } = store

  const [phase, setPhase] = useState<'busy' | 'ready' | 'error'>('busy')
  const [msg, setMsg] = useState('대본을 구성하는 중…')
  const [aiUsed, setAiUsed] = useState(false)
  const [error, setError] = useState('')
  const [pickFor, setPickFor] = useState<string | null>(null)  // 사진 피커가 열린 씬 id
  const [gate, setGate] = useState<{ kind: 'login' | 'topup' | 'error'; msg: string } | null>(null)
  const [charging, setCharging] = useState(false)
  const started = useRef(false)
  const user = useUserStore(s => s.user)
  const loginWithGoogle = useUserStore(s => s.loginWithGoogle)

  useEffect(() => {
    if (!store.source) { nav('/import', { replace: true }); return }
    if (started.current) return
    started.current = true
    const sig = composeSig()
    if (storyboard && lastComposeSig === sig) { setPhase('ready'); setAiUsed(!!store.marketing?.aiUsed) }
    else compose(sig)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function composeSig() {
    // 선택 사진의 "개수"가 아니라 "id·순서"까지 반영해야, 개수가 같은 교체·재정렬 후에도 재구성된다.
    const sel = images.filter(i => i.selected).map(i => i.id).join(',')
    return `${config.conceptId}|${config.aspect}|${config.duration}|${config.aiMode ? 'ai' : 't'}|${sel}`
  }

  async function compose(sig: string) {
    setPhase('busy'); setError(''); setAiUsed(false)
    try {
      const concept = getConcept(config.conceptId)
      const photos = images.filter(i => i.selected)
      // 1) 기본(템플릿) 골격 — 즉시
      let sb = buildStoryboard(listing, config, photos.map(p => p.id))

      // 2) AI 자동 구성(선택) — 사진 분석 → 스크립트 → 배치
      const useAi = config.aiMode && hasGeminiKey()
      if (useAi) {
        try {
          if (photos.length) {
            setMsg('사진을 분석하는 중… (AI 비전)')
            const tags = await analyzeImages(photos)
            setImageAnalysis(tags)
          }
          setMsg('AI가 컷별 자막·나레이션을 짜는 중…')
          const tagged = useEstateStore.getState().images.filter(i => i.selected)
          const script = await generateScript({
            listing, concept, durationSec: config.duration,
            sceneCount: estimateSceneCount(config.duration), imageSummary: imageSummary(tagged),
          })
          // AI가 빈 스크립트(0컷)를 주면 예외가 없어 폴백이 안 걸리므로, 유효할 때만 템플릿을 교체한다.
          if (script.length) { sb = buildStoryboardAI(config, script, tagged, listing); setAiUsed(true) }
          else console.warn('AI 스크립트가 비어 템플릿 구성을 유지합니다.')
        } catch (e) {
          console.warn('AI 구성 실패 — 기본(템플릿) 구성으로 진행:', e)
        }
      }

      // 3) 훅·제목(마케팅) — 템플릿 + 선택 AI 다듬기
      setMsg('훅·제목을 다듬는 중…')
      let marketing = buildMarketing(listing, config.conceptId)
      if (hasGeminiKey()) {
        try { marketing = await generateHooksAndTitles(listing, config.conceptId, marketing) }
        catch (e) { console.warn('훅·제목 AI 다듬기 실패 — 템플릿 사용:', e) }
      }
      setMarketing(marketing)

      // 4) 오프닝 자막을 최종 훅으로, 나레이션은 자막과 겹치지 않는 "도입 멘트"로 통일
      const first = sb.scenes[0]
      if (first && first.role === 'hook' && marketing.hook) {
        first.caption = marketing.hook
        first.narration = hookNarration(listing, config.conceptId)
      }

      setStoryboard(sb)
      lastComposeSig = sig
      setPhase('ready')
    } catch (e) {
      console.error(e)
      setError(e instanceof Error ? e.message : String(e))
      setPhase('error')
    }
  }

  const recompose = () => { started.current = true; lastComposeSig = ''; compose(composeSig()) }

  const goGenerate = () => { store.setResult(null); nav('/generate') }

  // 제작 게이트 — 제작은 로그인 필수. 로그인 후 프로젝트당 FREE_RENDERS(2)회 무료,
  // 이후 제작은 COINS_PER_RENDER(100)코인/편. (다운로드/공유/연동 과금은 Result에서 별도.)
  async function startGenerate() {
    setGate(null)
    if (!user) {                                                                    // 제작은 로그인부터
      setGate({ kind: 'login', msg: '영상 제작은 로그인 후 이용할 수 있어요. HEADJIM 계정으로 로그인해주세요. (제작 무료 2회 후 초과분·다운로드는 코인)' })
      return
    }
    if (store.renderCount < FREE_RENDERS) { store.bumpRenderCount(); goGenerate(); return }  // 무료 제작
    setCharging(true)                                                               // 무료 초과 → 코인(이미 로그인)
    try {
      await spendCoins({ coins: COINS_PER_RENDER, service: WALLET_SERVICE, reason: '부동산 홍보영상 추가 제작', refId: makeVideoId() })
      store.bumpRenderCount(); goGenerate()
    } catch (e) {
      const err = e as SpendError
      if (err.code === 'insufficient') {
        setGate({ kind: 'topup', msg: `코인이 부족해요 (보유 ${err.balance?.toLocaleString() ?? 0} / 필요 ${COINS_PER_RENDER}). 충전 후 이어서 만들 수 있어요.` })
      } else if (err.code === 'unauthenticated') {
        setGate({ kind: 'login', msg: '로그인이 필요해요.' })
      } else {
        setGate({ kind: 'error', msg: '결제 처리 중 문제가 생겼어요. 잠시 후 다시 시도해주세요.' })
      }
    } finally { setCharging(false) }
  }

  if (phase === 'busy') {
    return (
      <div style={{ padding: '40px 24px', maxWidth: 460, margin: '0 auto', minHeight: '70vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', textAlign: 'center' }}>
        <div className="flex-center" style={{ width: 72, height: 72, borderRadius: 22, background: 'var(--gradient-card)', border: '1px solid var(--color-border-gold)', margin: '0 auto 20px', animation: 'pulse-gold 2s infinite' }}>
          <Wand2 size={32} color="var(--color-gold-400)" />
        </div>
        <h2 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: 8 }}>대본을 구성하고 있어요</h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'center' }}>
          <Loader2 size={15} className="animate-spin" /> {msg}
        </p>
      </div>
    )
  }

  if (phase === 'error' || !storyboard) {
    return (
      <div style={{ padding: '40px 24px', maxWidth: 460, margin: '0 auto', minHeight: '70vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', textAlign: 'center' }}>
        <AlertTriangle size={44} color="var(--color-error)" style={{ margin: '0 auto 16px' }} />
        <h2 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: 8 }}>대본 구성에 문제가 생겼어요</h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', marginBottom: 20 }}>{error || '다시 시도해주세요.'}</p>
        <button className="btn btn-gold btn-full" onClick={recompose}><RotateCcw size={16} /> 다시 구성</button>
        <button className="btn btn-ghost btn-full" style={{ marginTop: 8 }} onClick={() => nav('/concept')}>컨셉으로 돌아가기</button>
      </div>
    )
  }

  const imgById = new Map(images.map(i => [i.id, i]))
  const concept = getConcept(config.conceptId)
  const narrationOn = config.narration
  const keyMissing = (config.narration || config.aiMode) && !hasGeminiKey()
  const renderLeft = Math.max(0, FREE_RENDERS - store.renderCount)

  return (
    <div style={{ padding: '16px 16px 120px', maxWidth: 560, margin: '0 auto' }} className="animate-fade-in">
      <div className="flex-between" style={{ marginBottom: 4 }}>
        <h2 style={{ fontSize: '1.05rem', fontWeight: 800 }}>대본 · 씬 편집</h2>
        <span className="badge" style={{ background: concept.accent + '22', color: concept.accent }}>{concept.emoji} {concept.label}</span>
      </div>
      <p style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', marginBottom: 12, lineHeight: 1.5 }}>
        <b style={{ color: 'var(--color-text-secondary)' }}>자막</b>은 화면에 보이는 글자, <b style={{ color: 'var(--color-text-secondary)' }}>나레이션</b>은 음성으로 나가는 대사예요.
        서로 다른 말을 하도록 나눠 두었어요 — 필요하면 자유롭게 고치세요.
      </p>

      {/* 상단 컨트롤 */}
      <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
        <button className="btn btn-outline btn-sm" onClick={recompose} title="컨셉·사진으로 다시 구성">
          <RefreshCw size={13} /> 다시 구성
        </button>
        {aiUsed && <span className="badge badge-gold"><Sparkles size={11} /> AI 구성</span>}
        <div style={{ flex: 1 }} />
        <button className={clsx('badge', narrationOn ? 'badge-gold' : 'badge-muted')} onClick={() => setConfig({ narration: !narrationOn })}
          style={{ cursor: 'pointer', border: 'none' }} title="나레이션 음성 켜기/끄기">
          <Mic size={12} /> 나레이션 음성 {narrationOn ? '켜짐' : '꺼짐'}
        </button>
      </div>
      {narrationOn && (
        <div className="seg" style={{ marginBottom: 8 }}>
          {(['female', 'male'] as const).map(v => (
            <button key={v} className={clsx('seg__btn', config.voice === v && 'active')} onClick={() => setConfig({ voice: v })} style={{ fontSize: '0.8rem' }}>
              {v === 'female' ? '여성 음성' : '남성 음성'}
            </button>
          ))}
        </div>
      )}
      {keyMissing && (
        <button className="card" onClick={() => nav('/profile')}
          style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', textAlign: 'left', marginBottom: 8, borderColor: 'var(--color-border-gold)', fontSize: '0.78rem', color: 'var(--color-text-secondary)' }}>
          <Sparkles size={15} color="var(--color-gold-400)" style={{ flexShrink: 0 }} />
          <span style={{ flex: 1 }}>AI 구성·나레이션 음성은 <b style={{ color: 'var(--color-gold-400)' }}>Gemini 키</b>가 필요해요. 없으면 기본 대본으로 제작돼요.</span>
          <ArrowRight size={14} />
        </button>
      )}

      {/* 씬 카드들 */}
      <div style={{ display: 'grid', gap: 12, marginTop: 6 }}>
        {storyboard.scenes.map((sc, i) => {
          const img = sc.photoId ? imgById.get(sc.photoId) : null
          const redundant = narrationOn && !!sc.narration && isRedundantNarration(sc.caption, sc.sub, sc.narration)
          return (
            <div key={sc.id} className="card" style={{ padding: 12 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: pickFor === sc.id ? 8 : 10 }}>
                {/* 썸네일(누르면 사진 피커 열림) */}
                <button onClick={() => setPickFor(pickFor === sc.id ? null : sc.id)} title="이 컷의 사진 바꾸기"
                  style={{ width: 44, height: 44, borderRadius: 8, flexShrink: 0, padding: 0, overflow: 'hidden', cursor: 'pointer', position: 'relative',
                    border: pickFor === sc.id ? '2px solid var(--color-gold-400)' : '1px solid var(--color-border)', background: 'var(--color-bg-base)' }}>
                  {img
                    ? <img src={img.src} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    : <span className="flex-center" style={{ width: '100%', height: '100%' }}><ImageIcon size={18} color="var(--color-text-muted)" /></span>}
                </button>
                <div style={{ flex: 1 }}>
                  <span className="badge badge-muted" style={{ fontSize: '0.68rem' }}>컷 {i + 1} · {ROLE_LABEL[sc.role] || sc.role}</span>
                </div>
                <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem', padding: '2px 8px' }}
                  onClick={() => setPickFor(pickFor === sc.id ? null : sc.id)} title="이 컷의 사진 바꾸기">
                  <ImageIcon size={12} /> 사진
                </button>
                <span style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)' }}>{sc.duration}초</span>
                <button className="btn btn-ghost btn-icon btn-sm" onClick={() => removeScene(sc.id)}
                  disabled={storyboard.scenes.length <= 1} title="이 컷 삭제" style={{ padding: '2px 6px' }}>
                  <Trash2 size={15} color={storyboard.scenes.length <= 1 ? 'var(--color-text-muted)' : 'var(--color-error)'} />
                </button>
              </div>

              {/* 사진 피커 — 업로드한 사진 중 이 컷에 쓸 사진을 고른다(배경 카드 포함) */}
              {pickFor === sc.id && (
                <div style={{ display: 'flex', gap: 6, overflowX: 'auto', padding: '2px 0 10px', marginBottom: 4 }}>
                  <button onClick={() => updateScene(sc.id, { photoId: null })} title="배경 카드 (사진 없음)"
                    style={{ width: 52, height: 52, flexShrink: 0, borderRadius: 8, cursor: 'pointer', display: 'grid', placeItems: 'center', gap: 0,
                      border: !sc.photoId ? '2px solid var(--color-gold-400)' : '1px solid var(--color-border)', background: 'var(--color-bg-base)', color: 'var(--color-text-muted)', fontSize: '0.6rem' }}>
                    <ImageIcon size={15} /><span>배경</span>
                  </button>
                  {images.map(im => (
                    <button key={im.id} onClick={() => updateScene(sc.id, { photoId: im.id })} title="이 사진 사용"
                      style={{ width: 52, height: 52, flexShrink: 0, borderRadius: 8, padding: 0, overflow: 'hidden', cursor: 'pointer',
                        border: sc.photoId === im.id ? '2px solid var(--color-gold-400)' : '1px solid var(--color-border)', opacity: im.selected ? 1 : 0.55 }}>
                      <img src={im.src} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    </button>
                  ))}
                  {images.length === 0 && (
                    <span style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)', alignSelf: 'center' }}>업로드한 사진이 없어요 — 배경 카드로 제작돼요.</span>
                  )}
                </div>
              )}

              {/* 자막 */}
              <label className="input-label" style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--color-text-secondary)', display: 'flex', alignItems: 'center', gap: 5 }}>
                <Captions size={13} color="var(--color-gold-400)" /> 자막 (화면)
              </label>
              <input className="input" value={sc.caption} onChange={e => updateScene(sc.id, { caption: e.target.value })} placeholder="화면에 보일 핵심 문구" style={{ marginBottom: 6 }} />
              <input className="input" value={sc.sub || ''} onChange={e => updateScene(sc.id, { sub: e.target.value })} placeholder="보조 문구 (선택)" style={{ fontSize: '0.82rem', marginBottom: 10 }} />

              {/* 나레이션 */}
              <div className="flex-between" style={{ marginBottom: 4 }}>
                <label className="input-label" style={{ fontSize: '0.74rem', fontWeight: 700, color: narrationOn ? 'var(--color-text-secondary)' : 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: 5, margin: 0 }}>
                  <Mic size={13} color={narrationOn ? 'var(--color-gold-400)' : 'var(--color-text-muted)'} /> 나레이션 (음성)
                </label>
                <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem', padding: '2px 8px' }}
                  onClick={() => updateScene(sc.id, { narration: buildSceneNarration(sc.role, sc.caption, sc.sub, listing, config.conceptId, i) })}
                  title="자막과 겹치지 않게 다시 만들기">
                  <RefreshCw size={11} /> 다시
                </button>
              </div>
              <textarea className="input" value={sc.narration || ''} onChange={e => updateScene(sc.id, { narration: e.target.value })}
                placeholder={narrationOn ? '성우가 읽을 대사 (자막과 다른 말로)' : '나레이션 음성이 꺼져 있어요'}
                rows={2} style={{ minHeight: 52, resize: 'vertical', lineHeight: 1.5, opacity: narrationOn ? 1 : 0.55 }} />
              {redundant && (
                <p style={{ fontSize: '0.72rem', color: 'var(--color-warning)', marginTop: 5, display: 'flex', alignItems: 'center', gap: 4 }}>
                  <AlertTriangle size={12} /> 자막과 거의 같아요 — “다시”를 눌러 겹치지 않게 바꿔보세요.
                </p>
              )}
              {/* 이 컷 아래에 새 컷 추가 */}
              <button onClick={() => addScene(sc.id)} title="이 컷 아래에 새 컷 추가"
                style={{ width: '100%', marginTop: 10, padding: '7px', fontSize: '0.74rem', fontWeight: 700, color: 'var(--color-text-muted)',
                  background: 'transparent', border: '1px dashed var(--color-border)', borderRadius: 8, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
                <Plus size={13} /> 아래에 컷 추가
              </button>
            </div>
          )
        })}
      </div>

      {/* 제작 게이트 안내(로그인/충전 필요 시) */}
      {gate && (
        <div className="card" style={{ marginTop: 16, borderColor: 'var(--color-border-gold)', background: 'var(--gradient-card)' }}>
          <p style={{ fontSize: '0.82rem', color: gate.kind === 'error' ? 'var(--color-warning)' : 'var(--color-text-secondary)', margin: '0 0 10px', lineHeight: 1.6 }}>{gate.msg}</p>
          {gate.kind === 'login' && (
            <div style={{ display: 'grid', gap: 8 }}>
              <button className="btn btn-primary btn-full" onClick={() => loginWithGoogle()}><LogIn size={16} /> Google로 로그인</button>
              <button className="btn btn-ghost btn-full" onClick={() => nav('/profile')}>이메일로 로그인 · 회원가입</button>
            </div>
          )}
          {gate.kind === 'topup' && (
            <a className="btn btn-gold btn-full" href={TOPUP_URL} target="_blank" rel="noreferrer"><Coins size={16} /> 코인 충전하러 가기</a>
          )}
        </div>
      )}

      <button className="btn btn-gold btn-lg btn-full" onClick={startGenerate} disabled={charging}
        style={{ position: 'sticky', bottom: 16, marginTop: 14 }}>
        {charging ? <><Loader2 size={18} className="animate-spin" /> 코인 확인 중…</>
          : !user ? <><LogIn size={17} /> 로그인하고 영상 만들기</>
          : renderLeft > 0 ? <>영상 만들기 <ArrowRight size={18} /></>
          : <><Coins size={16} /> {COINS_PER_RENDER}코인으로 제작 <ArrowRight size={18} /></>}
      </button>
      <p style={{ textAlign: 'center', fontSize: '0.74rem', color: 'var(--color-text-muted)', marginTop: 8 }}>
        {!user
          ? <>제작은 로그인 후 이용 · 로그인하면 <b style={{ color: 'var(--color-text-secondary)' }}>2회 무료 제작</b></>
          : renderLeft > 0
            ? <><Gift size={12} style={{ verticalAlign: -2 }} /> 무료 제작 {renderLeft}/{FREE_RENDERS}회 남음 · 미리보기 무료</>
            : <>무료 제작 {FREE_RENDERS}회 소진 · 추가 제작 {COINS_PER_RENDER}코인/편 (다운로드는 별도)</>}
      </p>
    </div>
  )
}
