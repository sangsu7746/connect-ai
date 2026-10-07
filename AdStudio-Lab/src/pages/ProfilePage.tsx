import React, { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { useNavigate } from 'react-router-dom'
import {
  User, Globe, Coins,
  FileText, Shield, HelpCircle, ChevronRight,
} from 'lucide-react'
import { useUserStore } from '../stores/userStore'
import { subscribeBalance } from '../services/walletService'
import { useChargeModal } from '../stores/chargeModalStore'
import { clsx } from 'clsx'

// 목업 소셜 로그인
function LoginPrompt({ onLogin }: { onLogin: (provider: string) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ textAlign: 'center', padding: '20px 0 16px' }}>
        <div style={{
          width: 72, height: 72, borderRadius: '50%',
          background: 'var(--color-bg-base)',
          border: '2px dashed var(--color-border-strong)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 14px',
        }}>
          <User size={32} color="var(--color-text-muted)" />
        </div>
        <h2 style={{ fontSize: '1.125rem', fontWeight: 700, marginBottom: 6 }}>로그인이 필요해요</h2>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
          로그인하면 내 프로젝트를 저장하고<br />모든 기기에서 불러올 수 있어요        </p>
      </div>

      {[
        { provider: 'google', label: 'Google로 계속하기', emoji: '🇬' },
        { provider: 'apple',  label: 'Apple로 계속하기',  emoji: '🍎' },
        { provider: 'email',  label: '이메일로 계속하기', emoji: '📧' },
      ].map(({ provider, label, emoji }) => (
        <motion.button
          key={provider}
          className="btn btn-outline btn-full"
          onClick={() => onLogin(provider)}
          whileTap={{ scale: 0.98 }}
          style={{ justifyContent: 'flex-start', gap: 12, fontSize: '0.9rem' }}
        >
          <span style={{ fontSize: 20 }}>{emoji}</span>
          {label}
        </motion.button>
      ))}

      <p style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', textAlign: 'center', marginTop: 4 }}>
        가입하면 웰컴 포인트 1,000개를 드려요 — 프리미엄 영상을 바로 만들어 볼 수 있어요      </p>
    </div>
  )
}

// 포인트 지갑 카드 — 잔액 실시간 구독 + headjim.com 충전 페이지 연결.
// (구독 결제는 포인트 전용 모델로 전환하면서 UI에서 내렸다 — 코드는 services/paypal.ts에 남아있고,
// 이후 "월간 포인트 번들 구독"으로 재도입할 때 다시 붙인다)
function CoinWalletCard({ uid }: { uid: string }) {
  const [balance, setBalance] = useState<number | null>(null)

  useEffect(() => subscribeBalance(uid, setBalance), [uid])

  return (
    <div className="card" style={{
      background: 'linear-gradient(145deg, rgba(124,58,255,0.1), rgba(245,158,11,0.04))',
      borderColor: 'rgba(245,158,11,0.3)',
    }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 14 }}>
        <div style={{
          width: 42, height: 42, borderRadius: 12,
          background: 'var(--gradient-gold)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          <Coins size={20} color="#1a0a00" />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 800, fontSize: '1rem' }}>내 포인트</div>
          <div style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>
            프리미엄 영상 · 워터마크 제거 · HD 마감에 사용해요
          </div>
        </div>
      </div>

      <div style={{ textAlign: 'center', marginBottom: 14 }}>
        <div style={{ fontSize: '2rem', fontWeight: 900, color: 'var(--color-gold-400)' }}>
          {balance === null ? '···' : balance.toLocaleString()}
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>포인트 · P 1,500 = $1</div>
      </div>

      <button
        className="btn btn-gold btn-full"
        onClick={() => useChargeModal.getState().open()}
      >
        <Coins size={16} /> 포인트 충전하기
      </button>
    </div>
  )
}

export default function ProfilePage() {
  const navigate = useNavigate()
  const { user, effectivePlan: getEffectivePlan, language, setLanguage, logout } = useUserStore()
  const effectivePlan = getEffectivePlan()
  const [isLoggingIn, setIsLoggingIn] = useState(false)

  const handleLogin = async (provider: string) => {
    setIsLoggingIn(true)
    try {
      if (provider === 'google') {
        // 카카오톡 등 인앱 브라우저는 Google이 OAuth를 차단(403 disallowed_useragent)한다
        const { guardGoogleSignIn } = await import('../services/inAppBrowser')
        guardGoogleSignIn()
        const { signInWithPopup, googleProvider, auth } = await import('../services/firebase')
        await signInWithPopup(auth, googleProvider)
      } else {
        alert('Google 로그인을 이용해 주세요. 다른 소셜 로그인은 준비 중입니다.')
      }
    } catch (e: any) {
      console.error(e)
      alert(`로그인 실패: ${e.message}`)
    } finally {
      setIsLoggingIn(false)
    }
  }

  const handleLogout = async () => {
    try {
      await logout()
    } catch (e) {
      console.error(e)
    }
  }

  return (
    <div style={{ padding: '20px 16px', paddingBottom: 100 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontSize: '1.375rem', fontWeight: 800 }}>프로필</h1>
      </div>

      {/* 로그인 상태 */}
      {!user ? (
        <LoginPrompt onLogin={handleLogin} />
      ) : (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          style={{ display: 'flex', flexDirection: 'column', gap: 16 }}
        >
          {/* 사용자 정보 */}
          <div className="card" style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
            <div style={{
              width: 56, height: 56, borderRadius: '50%',
              background: 'var(--gradient-brand)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              <User size={26} color="#fff" />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 700, fontSize: '1rem' }}>{user.displayName ?? '사용자'}</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>{user.email}</div>
              <div style={{ marginTop: 4 }}>
                <span className={clsx('badge', effectivePlan === 'pro' ? 'badge-gold' : 'badge-brand')}>
                  {effectivePlan === 'pro' ? '⭐ Pro' : '무료 멤버'}
                </span>
              </div>
            </div>
          </div>

          {/* 포인트 지갑 — 잔액 확인·충전 (구독 대신 포인트 전용 과금 모델) */}
          <CoinWalletCard uid={user.uid} />

          <div style={{
            fontSize: '0.75rem', color: 'var(--color-text-muted)', lineHeight: 1.6,
            padding: '10px 14px', background: 'var(--color-bg-base)', borderRadius: 10,
          }}>
            💡 무빙포토는 매일 5개까지 <strong>무료</strong>예요(워터마크 포함).
            AI 영상·고퀄 영상과 워터마크 없는 HD 마감은 포인트로 만들어요.
          </div>

          {/* 설정 목록 */}
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            {[
              { icon: <Globe size={18} />, label: '언어', value: language === 'ko' ? '한국어' : 'English', action: () => setLanguage(language === 'ko' ? 'en' : 'ko') },
              { icon: <FileText size={18} />, label: '서비스 이용약관', value: '', action: () => {} },
              { icon: <Shield size={18} />, label: '개인정보처리방침', value: '', action: () => {} },
              { icon: <HelpCircle size={18} />, label: '고객지원', value: '', action: () => {} },
            ].map(({ icon, label, value, action }, i, arr) => (
              <button
                key={label}
                onClick={action}
                style={{
                  width: '100%', display: 'flex', alignItems: 'center',
                  gap: 12, padding: '14px 16px', background: 'none', border: 'none',
                  cursor: 'pointer', textAlign: 'left',
                  borderBottom: i < arr.length - 1 ? '1px solid var(--color-border)' : 'none',
                }}
              >
                <span style={{ color: 'var(--color-brand-400)' }}>{icon}</span>
                <span style={{ flex: 1, fontSize: '0.875rem', color: 'var(--color-text-primary)' }}>{label}</span>
                {value && <span style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>{value}</span>}
                <ChevronRight size={16} color="var(--color-text-muted)" />
              </button>
            ))}
          </div>

          {/* 로그아웃 */}
          <button className="btn btn-danger btn-full" onClick={handleLogout}>
            로그아웃
          </button>

          <p style={{ textAlign: 'center', fontSize: '0.7rem', color: 'var(--color-text-muted)' }}>
            AdStudio v1.0 쨌 BYOK Edition<br />
            by HEADJIM AI LABORATORY
          </p>
        </motion.div>
      )}
    </div>
  )
}
