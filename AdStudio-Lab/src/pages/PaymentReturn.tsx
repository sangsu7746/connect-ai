// ============================================================
// PaymentReturn — 토스페이먼츠 결제 복귀 처리 (/payment/success·fail)
// ============================================================
// 토스는 결제 후 이 주소로 리디렉션하며, 서버(creditTossPayment)의
// 승인(confirm)을 거쳐야 결제가 확정·적립된다.
// ============================================================

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getFunctions, httpsCallable } from 'firebase/functions'
import { auth } from '../services/firebase'

export function PaymentSuccess() {
  const navigate = useNavigate()
  const [status, setStatus] = useState('결제를 확인하는 중이에요…')
  const ranRef = useRef(false)

  useEffect(() => {
    // 로그인 상태 복원을 기다렸다가 1회만 실행
    const unsub = auth.onAuthStateChanged(async (user) => {
      if (ranRef.current) return
      if (!user) return // 아직 복원 전 — 다음 콜백 대기
      ranRef.current = true

      const qs = new URLSearchParams(window.location.search)
      const paymentKey = qs.get('paymentKey')
      const orderId = qs.get('orderId')
      const amount = Number(qs.get('amount'))
      if (!paymentKey || !orderId || !Number.isFinite(amount)) {
        setStatus('결제 정보가 올바르지 않아요.')
        return
      }

      try {
        const confirm = httpsCallable<
          { paymentKey: string; orderId: string; amount: number },
          { credited: number; balance: number; alreadyCredited: boolean }
        >(getFunctions(), 'creditTossPayment')
        const res = await confirm({ paymentKey, orderId, amount })
        setStatus(
          res.data.alreadyCredited
            ? `이미 적립된 주문이에요. 현재 잔액 P ${res.data.balance.toLocaleString()}`
            : `✅ 결제 완료! P ${res.data.credited.toLocaleString()}이 적립되었어요.`
        )
      } catch (e: any) {
        setStatus(`결제는 완료되었지만 적립에 실패했어요. 주문번호 ${orderId}와 함께 headjimkss@gmail.com으로 문의해주세요.\n(${e?.message || e})`)
      }
    })
    return unsub
  }, [])

  return (
    <div style={{ minHeight: '60vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 20, padding: 24, textAlign: 'center' }}>
      <p style={{ whiteSpace: 'pre-line', fontSize: '1rem', lineHeight: 1.7 }}>{status}</p>
      <button className="btn btn-primary" onClick={() => navigate('/')}>홈으로 돌아가기</button>
    </div>
  )
}

export function PaymentFail() {
  const navigate = useNavigate()
  const qs = new URLSearchParams(window.location.search)
  const msg = qs.get('message') || qs.get('code') || ''

  return (
    <div style={{ minHeight: '60vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 20, padding: 24, textAlign: 'center' }}>
      <p style={{ fontSize: '1rem', lineHeight: 1.7 }}>
        결제가 취소되었거나 실패했어요.{msg ? ` (${msg})` : ''}
      </p>
      <button className="btn btn-primary" onClick={() => navigate('/')}>홈으로 돌아가기</button>
    </div>
  )
}
