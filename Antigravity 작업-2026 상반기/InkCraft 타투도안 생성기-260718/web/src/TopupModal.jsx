import { useState, useEffect, useCallback } from 'react';
import { PayPalScriptProvider, PayPalButtons } from '@paypal/react-paypal-js';
import { COIN_PACKAGES, creditPayPalOrder, makeTossOrderId } from './firebase.js';

const PAYPAL_CLIENT_ID = import.meta.env.VITE_PAYPAL_CLIENT_ID || '';
const TOSS_CLIENT_KEY = import.meta.env.VITE_TOSS_CLIENT_KEY || '';

/** 코인 충전 모달 — 메인 홈과 동일한 상품/서버검증 흐름 (PayPal + Toss) */
export default function TopupModal({ user, onClose, onNotice }) {
  const [pkg, setPkg] = useState(COIN_PACKAGES[1]); // 기본: Standard
  const [method, setMethod] = useState('toss'); // toss | paypal
  const [tossReady, setTossReady] = useState(false);
  const [busy, setBusy] = useState(false);

  // 토스 SDK 로드
  useEffect(() => {
    if (window.TossPayments) { setTossReady(true); return; }
    const existing = document.querySelector('script[src*="tosspayments"]');
    if (existing) { existing.addEventListener('load', () => setTossReady(true)); return; }
    const s = document.createElement('script');
    s.src = 'https://js.tosspayments.com/v1/payment';
    s.async = true;
    s.onload = () => setTossReady(true);
    document.head.appendChild(s);
  }, []);

  const payToss = useCallback(async () => {
    if (!window.TossPayments || busy) return;
    setBusy(true);
    try {
      const toss = window.TossPayments(TOSS_CLIENT_KEY);
      await toss.requestPayment('카드', {
        amount: pkg.krw,
        orderId: makeTossOrderId(user.uid, pkg.code),
        orderName: `HEADJIM 코인 ${pkg.label} ${pkg.coins.toLocaleString()}코인`,
        customerName: user.displayName || '고객',
        customerEmail: user.email || undefined,
        successUrl: `${window.location.origin}/payment/success`,
        failUrl: `${window.location.origin}/payment/fail`,
      });
    } catch (e) {
      if (e?.code !== 'USER_CANCEL') onNotice(`❌ ${e.message || 'Toss payment failed'}`);
    } finally {
      setBusy(false);
    }
  }, [pkg, user, busy, onNotice]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal topup" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <h3>🪙 Buy coins</h3>
        <p className="hint">1 coin = ₩1 · shared across all HEADJIM apps</p>

        <div className="pkg-grid">
          {COIN_PACKAGES.map((p) => (
            <button
              key={p.code}
              className={`pkg-card ${pkg.code === p.code ? 'active' : ''}`}
              onClick={() => setPkg(p)}
            >
              <b>{p.coins.toLocaleString()}</b>
              <span>coins {p.bonus && <em className="bonus">{p.bonus}</em>}</span>
              <span className="pkg-price">₩{p.krw.toLocaleString()}</span>
            </button>
          ))}
        </div>

        <div className="seg pay-method">
          <button className={method === 'toss' ? 'active' : ''} onClick={() => setMethod('toss')}>
            💳 카드/토스 (KRW)
          </button>
          <button className={method === 'paypal' ? 'active' : ''} onClick={() => setMethod('paypal')}>
            PayPal (USD ${pkg.usd})
          </button>
        </div>

        {method === 'toss' ? (
          <button className="cta toss-btn" onClick={payToss} disabled={!tossReady || busy}>
            {busy ? '결제 처리 중…' : !tossReady ? '로딩 중…' : `₩${pkg.krw.toLocaleString()} 결제하기`}
          </button>
        ) : (
          <PayPalScriptProvider options={{ clientId: PAYPAL_CLIENT_ID, currency: 'USD', intent: 'capture' }}>
            <PayPalButtons
              key={pkg.code}
              style={{ layout: 'vertical', color: 'gold', shape: 'rect', label: 'paypal', height: 45, tagline: false }}
              createOrder={(_d, actions) =>
                actions.order.create({
                  intent: 'CAPTURE',
                  purchase_units: [{
                    description: `${pkg.coins.toLocaleString()} HEADJIM coins`,
                    custom_id: `${user.uid}|${pkg.paypalId}`,
                    amount: { currency_code: 'USD', value: pkg.usd },
                  }],
                  application_context: { brand_name: 'HEADJIM', shipping_preference: 'NO_SHIPPING', user_action: 'PAY_NOW' },
                })
              }
              onApprove={async (_d, actions) => {
                const details = await actions.order.capture();
                try {
                  const r = await creditPayPalOrder(details.id);
                  onNotice(
                    r.alreadyCredited
                      ? `이미 적립된 주문입니다. 잔액 ${r.balance.toLocaleString()}코인`
                      : `✅ ${r.credited.toLocaleString()}코인이 충전되었습니다!`
                  );
                  onClose();
                } catch (e) {
                  onNotice(`⚠️ 결제는 완료됐지만 적립 확인에 실패했습니다. 문의: 주문번호 ${details.id}`);
                }
              }}
              onError={() => onNotice('❌ PayPal payment failed.')}
            />
          </PayPalScriptProvider>
        )}
      </div>
    </div>
  );
}
