import { useEffect, useState } from 'react'
import { clsx } from 'clsx'
import { LogIn, LogOut, KeyRound, Check, Coins, Info, Gift, Mail, UserPlus, Loader2, MailWarning } from 'lucide-react'
import { useUserStore } from '../stores/userStore'
import { getGeminiKey, setGeminiKey, hasGeminiKey } from '../services/aiEnhance'
import { subscribeBalance } from '../services/walletService'
import { FREE_RENDERS, COINS_PER_RENDER, COINS_PER_DOWNLOAD, TOPUP_URL } from '../services/credits'

export default function Profile() {
  const { user, loginWithGoogle, loginWithEmail, signupWithEmail, resendVerification, logout, loginError, authNotice, authBusy } = useUserStore()
  const [keyInput, setKeyInput] = useState(getGeminiKey())
  const [saved, setSaved] = useState(false)
  const [balance, setBalance] = useState<number | null>(null)
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [email, setEmail] = useState('')
  const [pw, setPw] = useState('')

  const submitAuth = () => {
    if (!email.trim() || pw.length < 6) return
    if (mode === 'signup') signupWithEmail(email, pw); else loginWithEmail(email, pw)
  }

  useEffect(() => {
    if (!user) { setBalance(null); return }
    return subscribeBalance(user.uid, setBalance)
  }, [user?.uid])

  const saveKey = () => { setGeminiKey(keyInput); setSaved(true); setTimeout(() => setSaved(false), 1600) }

  return (
    <div style={{ padding: '24px 16px 100px', maxWidth: 480, margin: '0 auto' }} className="animate-fade-in">
      <h1 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: 16 }}>내 정보</h1>

      {/* 로그인 / 회원가입 */}
      <div className="card" style={{ marginBottom: 16 }}>
        {user ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              {user.photoURL
                ? <img src={user.photoURL} alt="" style={{ width: 46, height: 46, borderRadius: '50%' }} />
                : <div className="flex-center" style={{ width: 46, height: 46, borderRadius: '50%', background: 'var(--gradient-brand)', fontWeight: 800, color: '#fff' }}>{(user.displayName || 'U')[0].toUpperCase()}</div>}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 800 }}>{user.displayName}</div>
                <div style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', overflow: 'hidden', textOverflow: 'ellipsis' }}>{user.email}</div>
              </div>
              <button className="btn btn-ghost btn-sm" onClick={logout}><LogOut size={15} /> 로그아웃</button>
            </div>
            {user.emailVerified === false && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 12, padding: 10, borderRadius: 10, background: 'var(--color-bg-base)' }}>
                <MailWarning size={16} color="var(--color-warning)" style={{ flexShrink: 0 }} />
                <span style={{ flex: 1, fontSize: '0.76rem', color: 'var(--color-text-secondary)' }}>이메일 인증을 완료해 주세요.</span>
                <button className="btn btn-ghost btn-sm" style={{ fontSize: '0.72rem', padding: '3px 8px' }} onClick={() => resendVerification()}>재발송</button>
              </div>
            )}
            {authNotice && <p style={{ fontSize: '0.76rem', color: 'var(--color-success)', marginTop: 8 }}>{authNotice}</p>}
          </>
        ) : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <LogIn size={18} color="var(--color-gold-400)" />
              <b style={{ fontSize: '0.95rem' }}>로그인 / 회원가입</b>
            </div>
            <p style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', marginBottom: 12, lineHeight: 1.6 }}>
              <b>영상 제작은 로그인이 필요해요.</b> 계정 하나로 <b>{FREE_RENDERS}회 무료 제작</b>과 미리보기가 무료, 다운로드·공유·연동은 <b>코인</b>이에요.
              <span style={{ color: 'var(--color-text-muted)' }}> (코인은 HEADJIM 전 서비스 공용)</span>
            </p>
            {/* 로그인 / 회원가입 전환 */}
            <div className="seg" style={{ marginBottom: 10 }}>
              <button className={clsx('seg__btn', mode === 'login' && 'active')} onClick={() => setMode('login')} style={{ fontSize: '0.85rem' }}>로그인</button>
              <button className={clsx('seg__btn', mode === 'signup' && 'active')} onClick={() => setMode('signup')} style={{ fontSize: '0.85rem' }}>회원가입</button>
            </div>
            {/* 이메일·비밀번호 */}
            <div style={{ display: 'grid', gap: 8, marginBottom: 10 }}>
              <input className="input" type="email" placeholder="이메일" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" />
              <input className="input" type="password" placeholder="비밀번호 (6자 이상)" value={pw} onChange={e => setPw(e.target.value)}
                autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                onKeyDown={e => { if (e.key === 'Enter') submitAuth() }} />
            </div>
            <button className="btn btn-gold btn-full" onClick={submitAuth} disabled={authBusy || !email.trim() || pw.length < 6}>
              {authBusy ? <><Loader2 size={16} className="animate-spin" /> 처리 중…</>
                : mode === 'signup' ? <><UserPlus size={16} /> 회원가입</> : <><Mail size={16} /> 이메일로 로그인</>}
            </button>
            {/* 구분선 + Google */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '12px 0' }}>
              <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
              <span style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)' }}>또는</span>
              <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
            </div>
            <button className="btn btn-outline btn-full" onClick={() => loginWithGoogle()} disabled={authBusy}><LogIn size={16} /> Google로 계속하기</button>
            {loginError && <p style={{ fontSize: '0.76rem', color: 'var(--color-warning)', marginTop: 8 }}>{loginError}</p>}
            {authNotice && <p style={{ fontSize: '0.76rem', color: 'var(--color-success)', marginTop: 8 }}>{authNotice}</p>}
          </>
        )}
      </div>

      {/* 요금 안내 */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
          <Gift size={17} color="var(--color-gold-400)" />
          <b style={{ fontSize: '0.92rem' }}>요금 안내</b>
        </div>
        <div style={{ display: 'grid', gap: 6, fontSize: '0.82rem', color: 'var(--color-text-secondary)', marginBottom: user ? 12 : 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>제작 · 미리보기</span><b style={{ color: 'var(--color-success)' }}>무료</b></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>무료 제작 {FREE_RENDERS}회 초과</span><b>{COINS_PER_RENDER}코인/편</b></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>다운로드 · 공유 · 연동</span><b>{COINS_PER_DOWNLOAD.toLocaleString()}코인/편</b></div>
        </div>
        {user && (
          <>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.84rem', margin: '0 0 10px', paddingTop: 10, borderTop: '1px solid var(--color-border)' }}>
              <span style={{ color: 'var(--color-text-secondary)' }}>보유 코인</span>
              <b style={{ display: 'flex', alignItems: 'center', gap: 4 }}><Coins size={13} color="var(--color-gold-400)" /> {balance === null ? '…' : balance.toLocaleString()}</b>
            </div>
            <a className="btn btn-outline btn-sm btn-full" href={TOPUP_URL} target="_blank" rel="noreferrer"><Coins size={14} /> 코인 충전하러 가기</a>
          </>
        )}
        <p style={{ fontSize: '0.74rem', color: 'var(--color-text-muted)', margin: '10px 0 0', lineHeight: 1.5 }}>
          같은 영상은 한 번 결제하면 재다운로드가 무료예요. 충전은 메인 홈에서만 가능합니다.
        </p>
      </div>

      {/* AI 키 (BYOK) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <KeyRound size={17} color="var(--color-gold-400)" />
          <b style={{ fontSize: '0.92rem' }}>AI 다듬기 키 (Gemini · 선택)</b>
        </div>
        <p style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', marginBottom: 10, lineHeight: 1.5 }}>
          입력하면 "AI로 다듬기"가 켜져요. 키는 <b>이 기기(브라우저)에만</b> 저장되고 서버로 보내지 않습니다.
        </p>
        <div style={{ display: 'flex', gap: 6 }}>
          <input className="input" style={{ fontSize: '0.82rem' }} type="password" placeholder="Gemini API 키"
            value={keyInput} onChange={e => setKeyInput(e.target.value)} />
          <button className="btn btn-gold btn-sm" onClick={saveKey} style={{ flexShrink: 0 }}>
            {saved ? <><Check size={14} /> 저장됨</> : '저장'}
          </button>
        </div>
        {hasGeminiKey() && !saved && <p style={{ fontSize: '0.74rem', color: 'var(--color-success)', marginTop: 6 }}>✓ 키가 등록되어 있어요</p>}
      </div>

      <div className="card" style={{ display: 'flex', gap: 10, alignItems: 'flex-start', background: 'var(--gradient-card)' }}>
        <Info size={16} color="var(--color-gold-400)" style={{ flexShrink: 0, marginTop: 2 }} />
        <p style={{ fontSize: '0.78rem', color: 'var(--color-text-secondary)', margin: 0, lineHeight: 1.6 }}>
          영상 합성은 <b>브라우저 안</b>에서만 이뤄져 사진·글이 서버로 올라가지 않아요.
          URL 자동수집만 외부 리더를 경유합니다.
        </p>
      </div>
    </div>
  )
}
