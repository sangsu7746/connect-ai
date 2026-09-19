import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import { Download, RotateCcw, Plus, Check, Captions, Music, Mic, Share2, Copy, Sparkles, Type, Coins, LogIn, Loader2, Lock, Send, RefreshCw, ExternalLink } from 'lucide-react'
import { useEstateStore } from '../stores/estateStore'
import { useUserStore } from '../stores/userStore'
import { getConcept } from '../utils/estateConcepts'
import { spendCoins, type SpendError } from '../services/walletService'
import { COINS_PER_DOWNLOAD, isDownloadPaid, markDownloadPaid, TOPUP_URL, WALLET_SERVICE } from '../services/credits'
import { PLATFORMS, buildCaption } from '../utils/socialShare'
import { uploadToYouTube, ytConfigured, type YtMeta } from '../services/youtubeUpload'

export default function Result() {
  const nav = useNavigate()
  const { result, storyboard, listing, reset, marketing } = useEstateStore()
  const [copied, setCopied] = useState(-1)
  const user = useUserStore(s => s.user)
  const loginWithGoogle = useUserStore(s => s.loginWithGoogle)
  const [paid, setPaid] = useState(() => (result ? isDownloadPaid(result.id) : false))
  const [charging, setCharging] = useState(false)
  const [gate, setGate] = useState<{ kind: 'login' | 'topup' | 'error'; msg: string } | null>(null)
  const [caption, setCaption] = useState(() => buildCaption(listing, marketing))
  const [capVariant, setCapVariant] = useState(0)
  const [capCopied, setCapCopied] = useState(false)
  const [ytPrivacy, setYtPrivacy] = useState<YtMeta['privacy']>('unlisted')
  const [yt, setYt] = useState<{ state: 'idle' | 'uploading' | 'done' | 'error'; pct: number; url: string; err: string }>({ state: 'idle', pct: 0, url: '', err: '' })

  useEffect(() => { if (!result) nav('/', { replace: true }) }, [result, nav])
  if (!result) return null

  const copyTitle = async (t: string, i: number) => {
    try { await navigator.clipboard.writeText(t) } catch { /* ignore */ }
    setCopied(i); setTimeout(() => setCopied(-1), 1600)
  }

  const concept = storyboard ? getConcept(storyboard.conceptId) : null
  const ratio = result.aspect === '9:16' ? '9 / 16' : result.aspect === '1:1' ? '1 / 1' : '16 / 9'
  const durLabel = result.durationSec >= 60 ? `${Math.round(result.durationSec / 60 * 10) / 10}분` : `${result.durationSec}초`
  const fileName = `부동산릴스_${concept?.label || '영상'}_${durLabel}.mp4`
  const videoId = result.id  // 가드 이후 확정된 값(중첩 함수 클로저용)

  const doDownload = () => {
    const a = document.createElement('a')
    a.href = result.url; a.download = fileName
    document.body.appendChild(a); a.click(); a.remove()
  }

  const doShare = async () => {
    try {
      const blob = await (await fetch(result.url)).blob()
      const file = new File([blob], fileName, { type: 'video/mp4' })
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], text: caption, title: listing.title || '부동산 홍보 영상' })
      } else doDownload()
    } catch { doDownload() }
  }

  const copyCaption = async () => {
    try { await navigator.clipboard.writeText(caption) } catch { /* ignore */ }
    setCapCopied(true); setTimeout(() => setCapCopied(false), 1600)
  }
  const regenCaption = () => { const v = capVariant + 1; setCapVariant(v); setCaption(buildCaption(listing, marketing, v)) }
  // 플랫폼 업로드 화면 열기 + 문구 복사(연동은 유료 게이트를 거친다)
  const openPlatform = (url: string) => unlockThen(async () => {
    try { await navigator.clipboard.writeText(caption) } catch { /* ignore */ }
    setCapCopied(true); setTimeout(() => setCapCopied(false), 1600)
    window.open(url, '_blank', 'noopener,noreferrer')
  })

  // 유튜브 자동 업로드(브라우저에서 직접). 결제 게이트를 거친 뒤 실행.
  const runYtUpload = async () => {
    setYt({ state: 'uploading', pct: 0, url: '', err: '' })
    try {
      const blob = await (await fetch(result.url)).blob()
      const title = caption.split('\n')[0].slice(0, 100) || listing.title || '부동산 홍보 영상'
      const description = caption + (result.aspect === '9:16' ? '\n\n#Shorts' : '')
      const tags = [...(marketing?.badges || []), listing.region, listing.propertyType]
        .map(t => (t || '').replace(/[#\s]/g, '')).filter(t => t.length >= 2)
      const { url } = await uploadToYouTube(blob, { title, description, tags, privacy: ytPrivacy }, (p) => setYt(s => ({ ...s, pct: p })))
      setYt({ state: 'done', pct: 100, url, err: '' })
    } catch (e) {
      setYt({ state: 'error', pct: 0, url: '', err: e instanceof Error ? e.message : String(e) })
    }
  }

  // 다운로드·공유·연동 게이트 — 편당 COINS_PER_DOWNLOAD(500)코인. 결제한 영상은 재다운로드 무료(멱등).
  const unlocked = paid || isDownloadPaid(videoId)
  async function unlockThen(action: () => void | Promise<void>) {
    setGate(null)
    if (unlocked) { await action(); return }
    if (!user) {
      setGate({ kind: 'login', msg: `영상 다운로드·공유·연동은 편당 ${COINS_PER_DOWNLOAD.toLocaleString()}코인이에요. 로그인 후 이용하세요. (한 번 결제하면 이 영상은 재다운로드 무료)` })
      return
    }
    setCharging(true)
    try {
      await spendCoins({ coins: COINS_PER_DOWNLOAD, service: WALLET_SERVICE, reason: '부동산 홍보영상 다운로드', refId: `dl_${videoId}` })
      markDownloadPaid(videoId); setPaid(true)
      await action()
    } catch (e) {
      const err = e as SpendError
      if (err.code === 'insufficient') setGate({ kind: 'topup', msg: `코인이 부족해요 (보유 ${err.balance?.toLocaleString() ?? 0} / 필요 ${COINS_PER_DOWNLOAD.toLocaleString()}). 충전 후 이용하세요.` })
      else if (err.code === 'unauthenticated') setGate({ kind: 'login', msg: '로그인이 필요해요.' })
      else setGate({ kind: 'error', msg: '결제 처리 중 문제가 생겼어요. 잠시 후 다시 시도해주세요.' })
    } finally { setCharging(false) }
  }

  const chips = [
    result.hasSubtitles && { icon: Captions, label: '자막' },
    result.hasBgm && { icon: Music, label: '배경음악' },
    result.hasNarration && { icon: Mic, label: '나레이션' },
  ].filter(Boolean) as { icon: typeof Captions; label: string }[]

  return (
    <div style={{ padding: '16px 16px 120px', maxWidth: 460, margin: '0 auto' }} className="animate-fade-in">
      <div style={{ textAlign: 'center', marginBottom: 14 }}>
        <span className="badge badge-success" style={{ padding: '5px 12px' }}><Check size={13} /> 영상 완성</span>
      </div>

      <div className="video-player" style={{ aspectRatio: ratio, maxHeight: '58vh', margin: '0 auto 14px' }}>
        <video src={result.url} controls loop playsInline style={{ width: '100%', height: '100%' }} />
      </div>

      <div style={{ display: 'flex', justifyContent: 'center', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
        <span className="chip" style={{ cursor: 'default' }}>{concept?.emoji} {concept?.label}</span>
        <span className="chip" style={{ cursor: 'default' }}>{durLabel} · {result.aspect}</span>
        {chips.map(c => (
          <span key={c.label} className="chip" style={{ cursor: 'default', gap: 5 }}><c.icon size={12} color="var(--color-gold-400)" /> {c.label}</span>
        ))}
      </div>

      {/* 추천 제목 — 유튜브·블로그·릴스용 (조회수를 가르는 훅) */}
      {marketing && marketing.titles.length > 0 && (
        <div className="card" style={{ marginBottom: 16, textAlign: 'left', borderColor: 'var(--color-border-gold)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <Type size={16} color="var(--color-gold-400)" />
            <b style={{ fontSize: '0.92rem' }}>추천 제목</b>
            {marketing.aiUsed && <span className="badge badge-gold" style={{ marginLeft: 'auto' }}><Sparkles size={11} /> AI</span>}
          </div>
          <p style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)', margin: '0 0 10px' }}>
            유튜브·블로그·릴스 제목으로 그대로 쓰세요 — 눌러서 복사
          </p>
          <div style={{ display: 'grid', gap: 8 }}>
            {marketing.titles.map((t, i) => (
              <button key={i} onClick={() => copyTitle(t, i)}
                style={{
                  display: 'flex', gap: 10, alignItems: 'center', padding: '11px 13px', textAlign: 'left',
                  background: 'var(--color-bg-base)', border: '1px solid var(--color-border)', borderRadius: 10, cursor: 'pointer',
                }}>
                <span style={{ flex: 1, fontSize: '0.86rem', lineHeight: 1.45, color: 'var(--color-text-primary)' }}>{t}</span>
                {copied === i
                  ? <Check size={15} color="var(--color-success)" style={{ flexShrink: 0 }} />
                  : <Copy size={15} color="var(--color-text-muted)" style={{ flexShrink: 0 }} />}
              </button>
            ))}
          </div>
          {marketing.badges.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
              {marketing.badges.map(b => (
                <span key={b} className="badge badge-gold">{b}</span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 다운로드·공유 게이트 안내(로그인/충전 필요 시) */}
      {gate && (
        <div className="card" style={{ marginBottom: 10, borderColor: 'var(--color-border-gold)', background: 'var(--gradient-card)' }}>
          <p style={{ fontSize: '0.82rem', color: gate.kind === 'error' ? 'var(--color-warning)' : 'var(--color-text-secondary)', margin: '0 0 10px', lineHeight: 1.6 }}>{gate.msg}</p>
          {gate.kind === 'login' && (
            <div style={{ display: 'grid', gap: 8 }}>
              <button className="btn btn-primary btn-full" onClick={() => loginWithGoogle()}><LogIn size={16} /> Google로 로그인</button>
              <button className="btn btn-ghost btn-full" onClick={() => nav('/profile')}>이메일로 로그인 · 회원가입</button>
            </div>
          )}
          {gate.kind === 'topup' && <a className="btn btn-gold btn-full" href={TOPUP_URL} target="_blank" rel="noreferrer"><Coins size={16} /> 코인 충전하러 가기</a>}
        </div>
      )}

      <button className="btn btn-gold btn-lg btn-full" onClick={() => unlockThen(doDownload)} disabled={charging} style={{ marginBottom: 8 }}>
        {charging ? <><Loader2 size={18} className="animate-spin" /> 코인 확인 중…</>
          : unlocked ? <><Download size={18} /> 영상 다운로드</>
          : <><Lock size={16} /> {COINS_PER_DOWNLOAD.toLocaleString()}코인으로 다운로드</>}
      </button>
      <p style={{ textAlign: 'center', fontSize: '0.74rem', color: unlocked ? 'var(--color-success)' : 'var(--color-text-muted)', marginBottom: 18, lineHeight: 1.5 }}>
        {unlocked
          ? <><Check size={12} style={{ verticalAlign: -2 }} /> 결제 완료 — 이 영상은 자유롭게 다운로드·공유·업로드하세요</>
          : <>미리보기는 무료예요. 다운로드·공유·연동은 편당 {COINS_PER_DOWNLOAD.toLocaleString()}코인 · 한 번 결제하면 재다운로드·업로드 무료</>}
      </p>

      {/* SNS 업로드·공유 */}
      <div className="card" style={{ marginBottom: 16, textAlign: 'left', borderColor: 'var(--color-border-gold)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <Send size={16} color="var(--color-gold-400)" />
          <b style={{ fontSize: '0.92rem' }}>SNS에 올리기</b>
        </div>
        <p style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)', margin: '0 0 12px', lineHeight: 1.55 }}>
          ① 위에서 <b>영상 다운로드</b> → ② 아래 플랫폼 버튼으로 업로드 화면 열기 → 문구는 자동으로 복사돼요(붙여넣기).
        </p>

        {/* 게시 문구 — 자동작성 · 편집 가능 */}
        <div className="flex-between" style={{ marginBottom: 4 }}>
          <label className="input-label" style={{ fontSize: '0.74rem', fontWeight: 700, color: 'var(--color-text-secondary)', margin: 0 }}>
            게시 문구 <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>· 자동작성, 수정 가능</span>
          </label>
          <div style={{ display: 'flex', gap: 4 }}>
            <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem', padding: '2px 8px' }} onClick={regenCaption} title="다른 문구로 다시 작성"><RefreshCw size={11} /> 다시</button>
            <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem', padding: '2px 8px' }} onClick={copyCaption}>{capCopied ? <><Check size={11} /> 복사됨</> : <><Copy size={11} /> 복사</>}</button>
          </div>
        </div>
        <textarea className="input" value={caption} onChange={e => setCaption(e.target.value)} rows={7}
          style={{ minHeight: 150, resize: 'vertical', lineHeight: 1.5, fontSize: '0.84rem', marginBottom: 12 }} />

        {/* 유튜브 자동 업로드 (Phase 1 — 브라우저에서 바로 게시) */}
        <div style={{ border: '1px solid var(--color-border-gold)', borderRadius: 12, padding: 12, marginBottom: 12, background: 'var(--color-bg-base)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ fontSize: '1.05rem', lineHeight: 1 }}>▶️</span>
            <b style={{ fontSize: '0.86rem' }}>YouTube 자동 업로드</b>
            <span className="badge badge-gold" style={{ marginLeft: 'auto', fontSize: '0.62rem' }}>바로 게시</span>
          </div>
          {!ytConfigured() ? (
            <>
              <p style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)', margin: '0 0 8px', lineHeight: 1.5 }}>
                원클릭 자동 업로드는 <b>관리자 설정</b>(유튜브 클라이언트 ID) 후 켜져요. 지금은 업로드 화면을 열어 직접 올릴 수 있어요.
              </p>
              <button className="btn btn-outline btn-full" onClick={() => openPlatform('https://www.youtube.com/upload')} disabled={charging}>
                <ExternalLink size={14} /> YouTube 업로드 화면 열기
              </button>
            </>
          ) : yt.state === 'done' ? (
            <>
              <p style={{ color: 'var(--color-success)', fontSize: '0.84rem', margin: '0 0 8px', display: 'flex', alignItems: 'center', gap: 5 }}><Check size={14} /> 업로드 완료!</p>
              <a className="btn btn-gold btn-full" href={yt.url} target="_blank" rel="noreferrer">▶️ 유튜브에서 보기 ↗</a>
            </>
          ) : yt.state === 'uploading' ? (
            <>
              <div className="progress-bar"><div className="progress-bar__fill" style={{ width: `${yt.pct}%` }} /></div>
              <p style={{ fontSize: '0.76rem', color: 'var(--color-text-muted)', marginTop: 7, display: 'flex', alignItems: 'center', gap: 6 }}><Loader2 size={13} className="animate-spin" /> 유튜브 업로드 중… {yt.pct}%</p>
            </>
          ) : (
            <>
              <div className="seg" style={{ marginBottom: 8 }}>
                {(['unlisted', 'public', 'private'] as const).map(p => (
                  <button key={p} className={clsx('seg__btn', ytPrivacy === p && 'active')} onClick={() => setYtPrivacy(p)} style={{ fontSize: '0.74rem' }}>
                    {p === 'unlisted' ? '일부공개' : p === 'public' ? '공개' : '비공개'}
                  </button>
                ))}
              </div>
              <button className="btn btn-gold btn-full" onClick={() => unlockThen(runYtUpload)} disabled={charging}>
                <span style={{ marginRight: 2 }}>▶️</span> {unlocked ? 'YouTube에 지금 올리기' : `YouTube 자동 업로드 (${COINS_PER_DOWNLOAD.toLocaleString()}코인)`}
              </button>
              {yt.state === 'error' && <p style={{ color: 'var(--color-warning)', fontSize: '0.76rem', marginTop: 7 }}>{yt.err}</p>}
              <p style={{ fontSize: '0.68rem', color: 'var(--color-text-muted)', margin: '7px 0 0' }}>세로 영상은 자동으로 쇼츠로 올라가요. 제목·설명은 위 문구를 사용합니다.</p>
            </>
          )}
        </div>

        {/* 그 외 플랫폼 — 업로드 화면 열기 + 문구 복사 */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          {PLATFORMS.filter(p => p.id !== 'youtube').map(p => (
            <button key={p.id} className="btn btn-outline" onClick={() => openPlatform(p.url(caption))} disabled={charging}
              style={{ justifyContent: 'flex-start', gap: 9, textAlign: 'left', height: 'auto', padding: '10px 12px' }}>
              <span style={{ fontSize: 18, lineHeight: 1 }}>{p.emoji}</span>
              <span style={{ display: 'grid', lineHeight: 1.25 }}>
                <b style={{ fontSize: '0.82rem' }}>{p.name}</b>
                <span style={{ fontSize: '0.66rem', color: 'var(--color-text-muted)' }}>{p.hint}</span>
              </span>
              <ExternalLink size={13} color="var(--color-text-muted)" style={{ marginLeft: 'auto', flexShrink: 0 }} />
            </button>
          ))}
        </div>

        {/* 네이티브 공유(모바일) */}
        <button className="btn btn-gold btn-full" onClick={() => unlockThen(doShare)} disabled={charging} style={{ marginTop: 10 }}>
          <Share2 size={16} /> {unlocked ? '휴대폰 공유 시트로 올리기' : `휴대폰으로 바로 공유 (${COINS_PER_DOWNLOAD.toLocaleString()}코인)`}
        </button>
        <p style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', margin: '9px 0 0', lineHeight: 1.5 }}>
          · <b>Threads·X</b>는 문구가 자동으로 채워져요 · <b>인스타·틱톡·유튜브</b>는 열린 화면에서 다운로드한 영상을 선택하고 문구를 붙여넣으세요.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <button className="btn btn-ghost" onClick={() => nav('/concept')}><RotateCcw size={15} /> 다른 컨셉</button>
        <button className="btn btn-ghost" onClick={() => { reset(); nav('/import') }}><Plus size={15} /> 새로 만들기</button>
      </div>

      <p style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)', textAlign: 'center', marginTop: 18, lineHeight: 1.6 }}>
        같은 매물로 <b style={{ color: 'var(--color-text-secondary)' }}>다른 컨셉</b>도 만들어 보세요.<br />
        역세권·학군·투자·급매 — 타깃에 따라 반응이 달라집니다.
      </p>
    </div>
  )
}
