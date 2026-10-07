import React, { useState, useEffect } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Home, FolderOpen, Plus, Key, User as UserIcon,
  Film, Globe, ChevronLeft, Coins, AlertTriangle, X
} from 'lucide-react'
import { useUserStore } from '../../stores/userStore'
import { useKeysStore, alibabaFreeDaysLeft } from '../../stores/keysStore'
import { SUPPORTED_LOCALES, LOCALE_INFO } from '../../services/localizationService'
import { subscribeBalance } from '../../services/walletService'
import { useChargeModal } from '../../stores/chargeModalStore'
import { clsx } from 'clsx'

// ── 포인트 잔액 칩 (로그인 시에만 표시, 클릭 → 인앱 충전 모달) ──
function PointBalanceChip() {
  const user = useUserStore(s => s.user)
  const [balance, setBalance] = useState<number | null>(null)

  useEffect(() => {
    if (!user) { setBalance(null); return }
    return subscribeBalance(user.uid, setBalance)
  }, [user?.uid])

  if (!user || balance === null) return null

  return (
    <button
      className="btn btn-ghost btn-sm"
      onClick={() => useChargeModal.getState().open()}
      title="포인트 잔액 — 클릭하면 충전 창이 열려요"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 8px' }}
    >
      <Coins size={14} color="var(--color-gold-400, #f0b429)" />
      <span style={{ fontSize: 12, fontWeight: 700 }}>P {balance.toLocaleString()}</span>
    </button>
  )
}

// ── 헤더 ──────────────────────────────────────────────────────

interface HeaderProps {
  title?: string
  showBack?: boolean
  onBack?: () => void
  rightSlot?: React.ReactNode
}

export function AppHeader({ title, showBack, onBack, rightSlot }: HeaderProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { language, setLanguage } = useUserStore()
  const [langMenuOpen, setLangMenuOpen] = useState(false)

  const handleBack = () => {
    if (onBack) onBack()
    else navigate(-1)
  }

  return (
    <header className="app-header" style={{ position: 'relative' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
        {showBack ? (
          <button className="btn btn-ghost btn-icon" onClick={handleBack} aria-label="뒤로">
            <ChevronLeft size={20} />
          </button>
        ) : (
          <div className="app-header__logo">
            <Film size={22} style={{ filter: 'drop-shadow(0 0 10px #00f0ff)' }} color="#00f0ff" />
            <span style={{
              fontWeight: 900,
              background: 'var(--gradient-cyber)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              letterSpacing: '-0.02em',
            }}>{title || t('app_name')}</span>
          </div>
        )}
        {showBack && title && (
          <span style={{ fontWeight: 700, fontSize: '1.05rem', color: 'var(--color-text-primary)' }}>
            {title}
          </span>
        )}
      </div>
      <div className="app-header__actions" style={{ position: 'relative' }}>
        <PointBalanceChip />
        <button
          className="btn btn-ghost btn-icon btn-sm"
          onClick={() => setLangMenuOpen(v => !v)}
          title="언어 변경 (UI·대사·음성·자막 공통)"
        >
          <Globe size={16} color="#00f0ff" />
          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-cyber-cyan)' }}>{language.toUpperCase()}</span>
        </button>
        {rightSlot}

        {langMenuOpen && (
          <>
            <div
              style={{ position: 'fixed', inset: 0, zIndex: 40 }}
              onClick={() => setLangMenuOpen(false)}
            />
            <div style={{
              position: 'absolute', top: '100%', right: 0, marginTop: 6, zIndex: 41,
              background: 'var(--color-bg-surface)', border: '1px solid var(--color-border-cyan)',
              borderRadius: 12, boxShadow: 'var(--shadow-brand)',
              padding: 6, minWidth: 160, maxHeight: 320, overflowY: 'auto',
              backdropFilter: 'blur(16px)',
            }}>
              {SUPPORTED_LOCALES.map(loc => (
                <button
                  key={loc}
                  onClick={() => { setLanguage(loc); setLangMenuOpen(false) }}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    width: '100%', padding: '8px 10px', borderRadius: 8, border: 'none',
                    background: loc === language ? 'rgba(0, 240, 255, 0.15)' : 'transparent',
                    color: loc === language ? '#00f0ff' : 'var(--color-text-primary)', fontSize: '0.8rem', cursor: 'pointer',
                    textAlign: 'left', fontWeight: loc === language ? 700 : 400,
                  }}
                >
                  <span>{LOCALE_INFO[loc].labelNative}</span>
                  <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>{LOCALE_INFO[loc].labelKo}</span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </header>
  )
}

// ── 바텀 내비게이션 ───────────────────────────────────────────

const NAV_ITEMS = [
  { path: '/',         icon: Home,       key: 'nav_home'     },
  { path: '/projects', icon: FolderOpen, key: 'nav_projects' },
  { path: '/create',   icon: Plus,       key: 'nav_create',  isCreate: true },
  { path: '/keys',     icon: Key,        key: 'nav_keys'     },
  { path: '/profile',  icon: UserIcon,   key: 'nav_profile'  },
]

export function BottomNav() {
  const { t } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <nav className="bottom-nav" style={{
      background: 'rgba(10, 10, 18, 0.85)',
      backdropFilter: 'blur(20px)',
      borderTop: '1px solid var(--color-border-cyan)'
    }}>
      {NAV_ITEMS.map(({ path, icon: Icon, key, isCreate }) => {
        const active = location.pathname === path
        return (
          <button
            key={path}
            className={clsx('bottom-nav__item', active && 'active')}
            onClick={() => navigate(path)}
          >
            {isCreate ? (
              <div style={{
                width: 48, height: 48, borderRadius: '50%',
                background: 'var(--gradient-cyber)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: '0 0 20px rgba(0, 240, 255, 0.5)', marginTop: -22,
                border: '2px solid #07070d',
              }}>
                <Icon size={24} color="#07070d" strokeWidth={3} />
              </div>
            ) : (
              <>
                <Icon size={22} color={active ? '#00f0ff' : undefined} />
                <span style={{ color: active ? '#00f0ff' : undefined, fontWeight: active ? 700 : 400 }}>{t(key)}</span>
              </>
            )}
          </button>
        )
      })}
    </nav>
  )
}

// ── 앱 셸 ─────────────────────────────────────────────────────

interface AppShellProps {
  headerProps?: HeaderProps
  hideBottomNav?: boolean
  hideHeader?: boolean
  className?: string
}

// 알리바바 무료 기한 만료 알림 배너 — 사용이 자동 중단됐음을 앱 어디서든 바로 알 수 있게 한다.
// (세션 내 닫기 가능, 키 설정에서 갱신을 확인하면 자동으로 사라진다)
function AlibabaExpiryNotice() {
  const navigate = useNavigate()
  // 스토어 필드를 구독해야 갱신 버튼을 누른 즉시 배너가 사라진다
  const { keyStatuses, alibabaFreeExpiresAt, alibabaPaidMode } = useKeysStore()
  const [dismissed, setDismissed] = useState(false)
  void alibabaFreeExpiresAt; void alibabaPaidMode
  const daysLeft = alibabaFreeDaysLeft()
  const expired = daysLeft !== null && daysLeft <= 0
  if (dismissed || !expired || !keyStatuses['alibaba']?.isSet) return null

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
      background: 'rgba(239,68,68,0.12)', borderBottom: '1px solid rgba(239,68,68,0.3)',
      fontSize: '0.75rem', color: 'var(--color-text-secondary)',
    }}>
      <AlertTriangle size={14} color="var(--color-error)" style={{ flexShrink: 0 }} />
      <span style={{ flex: 1, lineHeight: 1.4 }}>
        <strong style={{ color: 'var(--color-error)' }}>알리바바 무료 기한 만료</strong> — 요금 청구 방지를 위해
        사용을 자동 중단했어요. 갱신 확인 후 다시 쓸 수 있어요.
      </span>
      <button className="btn btn-outline btn-sm" style={{ flexShrink: 0, fontSize: '0.7rem' }} onClick={() => navigate('/keys')}>
        갱신 확인
      </button>
      <button className="btn btn-ghost btn-icon btn-sm" style={{ flexShrink: 0 }} onClick={() => setDismissed(true)} aria-label="닫기">
        <X size={14} />
      </button>
    </div>
  )
}

export function AppShell({ headerProps, hideBottomNav, hideHeader, className }: AppShellProps) {
  return (
    <div className="app-shell">
      {!hideHeader && <AppHeader {...headerProps} />}
      <AlibabaExpiryNotice />
      <main className={clsx('page-content', hideBottomNav && 'no-bottom', className)}>
        <Outlet />
      </main>
      {!hideBottomNav && <BottomNav />}
    </div>
  )
}
