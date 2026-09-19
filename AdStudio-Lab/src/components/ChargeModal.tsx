// ============================================================
// ChargeModal — 인앱 포인트 충전 (PayPal · 토스페이먼츠)
// ============================================================
// 메인 홈(headjim.com)과 동일한 서버 검증 흐름을 그대로 쓴다:
//  - PayPal: 결제 승인 후 creditPayPalOrder 콜러블이 PayPal 주문을
//    서버에서 조회·검증한 뒤 지갑에 적립 (custom_id = `${uid}|${productId}`)
//  - 토스: successUrl(/payment/success) 복귀 후 creditTossPayment 콜러블이
//    승인(confirm)+검증+적립 (orderId = `${uid}_${code}_${ts}`)
// 상품 구성·금액은 headjimweb functions의 COIN_PRODUCTS / TOSS_COIN_PRODUCTS와
// 반드시 일치해야 한다 (WALLET_API.md 참고).
// ============================================================

import { useEffect, useRef, useState } from 'react'
import { getFunctions, httpsCallable } from 'firebase/functions'
import { doc, onSnapshot, serverTimestamp, updateDoc } from 'firebase/firestore'
import { auth, db } from '../services/firebase'
import { useChargeModal } from '../stores/chargeModalStore'

// 결제 키 — 라이브 전환 시 두 값을 라이브 키로 교체 (메인 홈 .env와 동일하게 유지)
const PAYPAL_CLIENT_ID =
  'ATNs8NzpryiQPZJAXfFQr5zKELjQe-zlfkfM-uN5tUwagF_q5zFWMjq1Pas63qxtMdaAKvzgSAkrlUpi' // sandbox "headjim ai"
const TOSS_CLIENT_KEY = 'test_ck_Z1aOwX7K8m7lbxL4Aop0VyQxzvNP'

// 토스 심사 통과 후 true 로 되돌릴 것 — 심사 중에는 테스트 결제창이라
// 돈이 움직이지 않는데 "결제 완료"로 보여 손님이 오해한다 (2026-07-29 전 앱 숨김).
const TOSS_ENABLED = false

const PACKAGES = [
  { code: 'basic' as const, pid: 'api-coin-basic', label: '베이직', coins: '5,000', krw: 5000, usd: '3.99', bonus: null as string | null },
  { code: 'standard' as const, pid: 'api-coin-standard', label: '스탠다드', coins: '32,900', krw: 29900, usd: '19.99', bonus: '+10% 보너스' },
  { code: 'premium' as const, pid: 'api-coin-premium', label: '프리미엄', coins: '118,800', krw: 99000, usd: '69.99', bonus: '+20% 보너스' },
]

declare global {
  interface Window {
    paypal?: any
    TossPayments?: (clientKey: string) => { requestPayment: (method: string, params: any) => Promise<void> }
  }
}

/* ── 앱 안에서 바로 처리하는 계좌이체 충전 ──────────────────
   예전에는 headjim.com 으로 보냈다가 돌아오게 했는데, 손님이 창을 옮겨
   다니다 이탈했다. 무통장입금은 결제 SDK 가 필요 없고 콜러블 하나로
   끝나므로(bankTransferCreate) 각 앱에서 직접 처리한다.
   금액·포인트는 서버 BANK_PRODUCTS 가 productId 로 다시 조회하므로
   여기 값을 바꿔도 지급량은 달라지지 않는다. */
const BANK_ACCOUNT = { bank: 'MG새마을금고', number: '9003-3126-2651-9', holder: '김상수(머리짐)' }
const BANK_PRODUCT_BY_CODE: Record<string, string> = {
  basic: 'bank-coin-basic',
  standard: 'bank-coin-standard',
  premium: 'bank-coin-premium',
}

type BankReq = { id: string; code: string }

function BankPanel({ pkg, onDone }: { pkg: (typeof PACKAGES)[number]; onDone: () => void }) {
  const [name, setName] = useState(auth.currentUser?.displayName?.trim() || '')
  const [req, setReq] = useState<BankReq | null>(null)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [copied, setCopied] = useState('')

  /* 승인되면 이 자리에서 바로 알려 준다 — 관리자가 입금 확인을 누른 순간 */
  useEffect(() => {
    if (!req) return
    return onSnapshot(doc(db, 'bankTransferRequests', req.id), (s) => {
      if (s.exists()) setStatus((s.get('status') as string) || '')
    })
  }, [req])

  const submit = async () => {
    if (!name.trim()) { setErr('입금자명을 입력해 주세요.'); return }
    setBusy(true); setErr('')
    try {
      const fn = httpsCallable<{ productId: string; depositorName: string }, BankReq>(
        getFunctions(), 'bankTransferCreate'
      )
      const r = await fn({ productId: BANK_PRODUCT_BY_CODE[pkg.code], depositorName: name.trim() })
      setReq(r.data)
    } catch (e: any) {
      const m = String(e?.message || '')
      setErr(m && !m.includes('internal') ? m : '신청에 실패했어요. 잠시 후 다시 시도해 주세요.')
    } finally { setBusy(false) }
  }

  const report = async () => {
    if (!req) return
    try {
      await updateDoc(doc(db, 'bankTransferRequests', req.id), {
        status: 'reported', reportedAt: serverTimestamp(),
      })
    } catch { setErr('상태 전송에 실패했지만, 입금하셨다면 확인 후 지급됩니다.') }
  }

  const copy = (text: string, tag: string) => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(tag); setTimeout(() => setCopied(''), 1500)
    }).catch(() => {})
  }

  const box = {
    marginTop: 10, padding: '14px 16px', borderRadius: 10,
    border: '1px solid rgba(255,255,255,0.14)', background: 'rgba(255,255,255,0.04)',
  } as const
  const label = { fontSize: '0.72rem', color: 'var(--color-text-muted, #889)' } as const
  const copyBtn = {
    marginLeft: 8, fontSize: '0.68rem', padding: '2px 8px', borderRadius: 6, cursor: 'pointer',
    border: '1px solid rgba(255,255,255,0.2)', background: 'transparent', color: 'inherit',
  } as const

  if (status === 'approved') {
    return (
      <div style={box}>
        <p style={{ margin: 0, color: '#6ee7b7', fontSize: '0.9rem' }}>
          ✅ 입금이 확인돼 P {pkg.coins}이 지급됐어요. 잔액은 바로 반영됩니다.
        </p>
        <button className="btn btn-ghost btn-sm" style={{ marginTop: 10 }} onClick={onDone}>닫기</button>
      </div>
    )
  }
  if (status === 'rejected') {
    return (
      <div style={box}>
        <p style={{ margin: 0, color: '#fca5a5', fontSize: '0.9rem' }}>
          ❌ 입금이 확인되지 않아 반려됐어요. 입금하셨다면 headjimkss@gmail.com 으로 알려 주세요.
        </p>
        <button className="btn btn-ghost btn-sm" style={{ marginTop: 10 }} onClick={onDone}>닫기</button>
      </div>
    )
  }

  if (!req) {
    return (
      <div style={box}>
        <p style={{ ...label, margin: '0 0 6px' }}>입금하실 때 쓰실 입금자명</p>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={20}
          placeholder="예: 홍길동"
          style={{
            width: '100%', height: 40, borderRadius: 8, padding: '0 10px', fontSize: '0.9rem',
            border: '1px solid rgba(255,255,255,0.2)', background: 'rgba(255,255,255,0.05)', color: 'inherit',
          }}
        />
        <p style={{ ...label, margin: '8px 0 0', lineHeight: 1.6 }}>
          신청하면 입금 계좌와 매칭 코드가 여기 표시됩니다. 입금자명 뒤에 코드를 붙여 주셔야
          어느 신청인지 바로 확인할 수 있어요.
        </p>
        {err && <p style={{ margin: '8px 0 0', fontSize: '0.78rem', color: '#fca5a5' }}>{err}</p>}
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={submit}>
            {busy ? '신청 중…' : '신청하고 계좌 확인'}
          </button>
          <button className="btn btn-ghost btn-sm" onClick={onDone}>취소</button>
        </div>
      </div>
    )
  }

  const depositor = `${name.trim()}-${req.code}`
  return (
    <div style={box}>
      <p style={{ ...label, margin: 0 }}>
        입금 계좌
        <button style={copyBtn} onClick={() => copy(BANK_ACCOUNT.number, 'acc')}>
          {copied === 'acc' ? '복사됨 ✓' : '계좌 복사'}
        </button>
      </p>
      <p style={{ margin: '2px 0 8px', fontSize: '1rem' }}>
        {BANK_ACCOUNT.bank} {BANK_ACCOUNT.number} <span style={label}>· 예금주 {BANK_ACCOUNT.holder}</span>
      </p>
      <p style={{ ...label, margin: 0 }}>입금 금액</p>
      <p style={{ margin: '2px 0 8px', fontSize: '1rem' }}>{pkg.krw.toLocaleString()}원</p>
      <p style={{ ...label, margin: 0 }}>
        입금자명 (코드 포함)
        <button style={copyBtn} onClick={() => copy(depositor, 'name')}>
          {copied === 'name' ? '복사됨 ✓' : '이름 복사'}
        </button>
      </p>
      <p style={{ margin: '2px 0 0', fontSize: '1rem' }}>{depositor}</p>

      <p style={{ ...label, margin: '10px 0 0', lineHeight: 1.6 }}>
        입금이 확인되면 이 화면이 바로 바뀌고 포인트가 지급됩니다. 보통 몇 시간 안에,
        늦어도 하루 안에 확인해 드려요. 은행 앱이 입금자명 글자 수를 제한하면
        뒤의 <b>코드 4자리</b>만이라도 남겨 주세요.
      </p>
      {err && <p style={{ margin: '8px 0 0', fontSize: '0.78rem', color: '#fca5a5' }}>{err}</p>}
      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        {status === 'reported' ? (
          <p style={{ margin: 0, fontSize: '0.85rem', color: '#7dd3fc' }}>확인 요청 접수됐어요 · 지급 대기 중</p>
        ) : (
          <button className="btn btn-primary btn-sm" onClick={report}>입금했어요</button>
        )}
        <button className="btn btn-ghost btn-sm" onClick={onDone}>닫기</button>
      </div>
    </div>
  )
}

function loadScript(src: string, check: () => boolean): Promise<void> {
  return new Promise((resolve, reject) => {
    if (check()) return resolve()
    const existing = document.querySelector(`script[src^="${src.split('?')[0]}"]`)
    if (existing) {
      existing.addEventListener('load', () => resolve())
      existing.addEventListener('error', () => reject(new Error('script load failed')))
      return
    }
    const s = document.createElement('script')
    s.src = src
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => reject(new Error('script load failed'))
    document.head.appendChild(s)
  })
}

export function ChargeModal() {
  const { isOpen, close } = useChargeModal()
  const [paypalReady, setPaypalReady] = useState(false)
  /* 계좌이체 패널이 열린 패키지 코드 ('' = 닫힘) */
  const [bankOpen, setBankOpen] = useState('')
  const [busy, setBusy] = useState(false)
  const paypalRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const renderedRef = useRef(false)
  const user = auth.currentUser

  // PayPal SDK 로드 + 버튼 렌더 (모달 열릴 때 1회)
  useEffect(() => {
    if (!isOpen || !user) return
    let cancelled = false
    loadScript(
      `https://www.paypal.com/sdk/js?client-id=${PAYPAL_CLIENT_ID}&currency=USD&intent=capture`,
      () => !!window.paypal
    )
      .then(() => {
        if (cancelled || renderedRef.current || !window.paypal) return
        renderedRef.current = true
        setPaypalReady(true)
        for (const pkg of PACKAGES) {
          const el = paypalRefs.current[pkg.code]
          if (!el) continue
          window.paypal
            .Buttons({
              style: { layout: 'horizontal', color: 'gold', shape: 'rect', label: 'paypal', height: 40, tagline: false },
              createOrder: (_d: any, actions: any) =>
                actions.order.create({
                  intent: 'CAPTURE',
                  purchase_units: [
                    {
                      description: `HEADJIM 포인트 ${pkg.label} (P ${pkg.coins})`,
                      custom_id: `${user.uid}|${pkg.pid}`,
                      amount: { currency_code: 'USD', value: pkg.usd },
                    },
                  ],
                  application_context: { shipping_preference: 'NO_SHIPPING', user_action: 'PAY_NOW' },
                }),
              onApprove: async (_d: any, actions: any) => {
                const details = await actions.order.capture()
                const orderId = details.id
                try {
                  const credit = httpsCallable<{ orderId: string }, { credited: number; balance: number; alreadyCredited: boolean }>(
                    getFunctions(),
                    'creditPayPalOrder'
                  )
                  const res = await credit({ orderId })
                  alert(
                    res.data.alreadyCredited
                      ? `이미 적립된 주문이에요. 현재 잔액 P ${res.data.balance.toLocaleString()}`
                      : `✅ 결제 완료! P ${res.data.credited.toLocaleString()}이 적립되었어요.`
                  )
                  close()
                } catch (e: any) {
                  alert(`결제는 완료되었지만 적립에 실패했어요. 주문번호 ${orderId}와 함께 headjimkss@gmail.com으로 문의해주세요.\n(${e?.message || e})`)
                }
              },
              onError: (err: any) => console.error('[PayPal]', err),
            })
            .render(el)
        }
      })
      .catch((e) => console.error('[PayPal] SDK 로드 실패:', e))
    return () => {
      cancelled = true
    }
  }, [isOpen, user, close])

  // 모달 닫힐 때 다음 열림을 위해 버튼 재렌더 허용
  useEffect(() => {
    if (!isOpen) {
      renderedRef.current = false
      setPaypalReady(false)
    }
  }, [isOpen])

  const handleToss = async (pkg: (typeof PACKAGES)[number]) => {
    if (!user || busy) return
    setBusy(true)
    try {
      await loadScript('https://js.tosspayments.com/v1/payment', () => !!window.TossPayments)
      const toss = window.TossPayments!(TOSS_CLIENT_KEY)
      const orderId = `${user.uid}_${pkg.code}_${Date.now().toString(36)}`
      await toss.requestPayment('카드', {
        amount: pkg.krw,
        orderId,
        orderName: `HEADJIM 포인트 ${pkg.label} P ${pkg.coins}`,
        customerName: user.displayName || '고객',
        customerEmail: user.email || undefined,
        successUrl: `${window.location.origin}/payment/success`,
        failUrl: `${window.location.origin}/payment/fail`,
      })
    } catch (e: any) {
      if (e?.code !== 'USER_CANCEL') console.error('[Toss]', e)
    } finally {
      setBusy(false)
    }
  }

  if (!isOpen) return null

  return (
    <div
      onClick={close}
      style={{
        position: 'fixed', inset: 0, zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)', padding: 16,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: '100%', maxWidth: 720, maxHeight: '90vh', overflowY: 'auto',
          background: 'var(--color-bg-card, #14141c)', border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: 16, padding: '28px 24px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 800 }}>포인트 충전</h2>
          <button className="btn btn-ghost btn-sm" onClick={close} aria-label="닫기">✕</button>
        </div>
        <p style={{ margin: '0 0 20px', fontSize: '0.85rem', color: 'var(--color-text-muted, #9aa)' }}>
          P 1 = ₩1 · 충전한 포인트는 오마주 영상·API 자동화 등 HEADJIM 모든 서비스에서 함께 쓰여요. 만료 없음.
        </p>

        {!user ? (
          <p style={{ color: 'var(--color-text-secondary, #ccc)' }}>충전하려면 먼저 로그인해주세요.</p>
        ) : (
          <div style={{ display: 'grid', gap: 14 }}>
            {PACKAGES.map((pkg) => (
              <div
                key={pkg.code}
                style={{
                  border: pkg.bonus ? '1px solid rgba(139,92,246,0.45)' : '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 12, padding: '16px 18px', position: 'relative',
                  background: pkg.code === 'standard' ? 'rgba(139,92,246,0.06)' : 'transparent',
                }}
              >
                {pkg.bonus && (
                  <span style={{
                    position: 'absolute', top: -10, right: 14, background: 'rgb(139,92,246)', color: '#fff',
                    fontSize: 11, fontWeight: 700, padding: '2px 10px', borderRadius: 999,
                  }}>{pkg.bonus}</span>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
                  <div>
                    <span style={{ fontSize: 12, letterSpacing: '0.1em', color: 'var(--color-text-muted, #9aa)', textTransform: 'uppercase' }}>{pkg.label}</span>
                    <div style={{ fontSize: '1.4rem', fontWeight: 800, color: 'var(--color-gold-400, #f0b429)' }}>
                      <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--color-text-muted, #9aa)' }}>P </span>{pkg.coins}
                    </div>
                  </div>
                  <div style={{ fontSize: '0.95rem', color: 'var(--color-text-secondary, #ccc)' }}>
                    ₩{pkg.krw.toLocaleString()} <span style={{ color: 'var(--color-text-muted, #889)' }}>· ${pkg.usd}</span>
                  </div>
                </div>

                {/* PayPal 버튼 (해외 결제) */}
                <div ref={(el) => { paypalRefs.current[pkg.code] = el }} style={{ minHeight: paypalReady ? undefined : 0 }} />

                {/* 토스 버튼 (국내 결제) — 심사 통과 전까지 숨기고 계좌이체로 안내 */}
                {TOSS_ENABLED ? (
                  <button
                    className="btn btn-primary btn-full"
                    disabled={busy}
                    onClick={() => handleToss(pkg)}
                    style={{ marginTop: 8, background: '#0064FF', borderColor: '#0064FF' }}
                  >
                    {pkg.krw.toLocaleString()}원 결제하기 (토스)
                  </button>
                ) : bankOpen === pkg.code ? (
                  <BankPanel pkg={pkg} onDone={() => setBankOpen('')} />
                ) : (
                  <button
                    className="btn btn-full"
                    onClick={() => setBankOpen(pkg.code)}
                    style={{ marginTop: 8 }}
                  >
                    🏦 {pkg.krw.toLocaleString()}원 계좌이체로 충전
                  </button>
                )}
              </div>
            ))}
            <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--color-text-muted, #889)' }}>
              🔐 모든 결제는 서버에서 PayPal·토스 원장을 검증한 뒤 적립돼요 · 환불정책은{' '}
              <a href="https://www.headjim.com/terms.html" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>이용약관</a> 참고
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
