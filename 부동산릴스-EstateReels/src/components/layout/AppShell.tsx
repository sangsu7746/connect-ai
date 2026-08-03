import { useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Home, Plus, User as UserIcon, ChevronLeft, Coins, Building2 } from 'lucide-react'
import { clsx } from 'clsx'
import { useUserStore } from '../../stores/userStore'
import { subscribeBalance } from '../../services/walletService'

function PointBalanceChip() {
  const user = useUserStore(s => s.user)
  const [balance, setBalance] = useState<number | null>(null)
  useEffect(() => {
    if (!user) { setBalance(null); return }
    return subscribeBalance(user.uid, setBalance)
  }, [user?.uid])
  if (!user || balance === null) return null
  return (
    <span className="chip" style={{ gap: 5, padding: '5px 10px', cursor: 'default' }} title="보유 코인">
      <Coins size={14} color="var(--color-gold-400)" />
      <span style={{ fontSize: 12, fontWeight: 800 }}>{balance.toLocaleString()}</span>
    </span>
  )
}

interface HeaderProps { title?: string; showBack?: boolean; right?: ReactNode }

export function AppHeader({ title, showBack, right }: HeaderProps) {
  const navigate = useNavigate()
  return (
    <header className="app-header">
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
        {showBack ? (
          <button className="btn btn-ghost btn-icon" onClick={() => navigate(-1)} aria-label="뒤로">
            <ChevronLeft size={20} />
          </button>
        ) : (
          <div className="app-header__logo" onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>
            <Building2 size={22} color="var(--color-gold-400)" />
            <span><span style={{ color: 'var(--color-text-primary)' }}>부동산</span><span className="gradient-text">릴스</span></span>
          </div>
        )}
        {showBack && title && (
          <span style={{ fontWeight: 800, fontSize: '1.02rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{title}</span>
        )}
      </div>
      <div className="app-header__actions">
        <PointBalanceChip />
        {right}
      </div>
    </header>
  )
}

const NAV = [
  { path: '/', icon: Home, label: '홈' },
  { path: '/create', icon: Plus, label: '만들기', center: true },
  { path: '/profile', icon: UserIcon, label: '내 정보' },
]

export function BottomNav() {
  const nav = useNavigate()
  const loc = useLocation()
  return (
    <nav className="bottom-nav">
      {NAV.map(({ path, icon: Icon, label, center }) => {
        const active = loc.pathname === path
        return (
          <button key={path} className={clsx('bottom-nav__item', active && 'active')} onClick={() => nav(path)}>
            {center ? (
              <div style={{
                width: 46, height: 46, borderRadius: '50%', marginTop: -20,
                background: 'var(--gradient-gold)', display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: 'var(--shadow-gold)', border: '2px solid var(--color-bg-surface)',
              }}>
                <Icon size={24} color="#3a2708" strokeWidth={3} />
              </div>
            ) : (
              <>
                <Icon size={22} color={active ? 'var(--color-gold-400)' : undefined} />
                <span>{label}</span>
              </>
            )}
          </button>
        )
      })}
    </nav>
  )
}

interface ShellProps { headerProps?: HeaderProps; hideBottomNav?: boolean }

export function AppShell({ headerProps, hideBottomNav }: ShellProps) {
  return (
    <div className="app-shell">
      <AppHeader {...headerProps} />
      <main className={clsx('page-content', hideBottomNav && 'no-bottom')}>
        <Outlet />
      </main>
      {!hideBottomNav && <BottomNav />}
    </div>
  )
}
