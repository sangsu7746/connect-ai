import { useState, useEffect, useCallback, useRef } from 'react';
import { STYLES, SUBJECT_SEEDS, COLOR_MODES } from './presets.js';
import { buildFlashSheet } from './pdf.js';
import {
  firebaseEnabled, watchAuth, signOut, generateDesignViaFirebase,
  chargeFeature, watchWallet, isInsufficientBalance,
  creditTossPayment, resendVerification, applyTattooViaFirebase,
  modelViewViaFirebase, modelApplyViaFirebase,
} from './firebase.js';
import AuthModal from './AuthModal.jsx';
import TopupModal from './TopupModal.jsx';
import TryOnStudio from './TryOnStudio.jsx';
import ModelStudio from './ModelStudio.jsx';
import { removeWhiteBg } from './ink.js';

const SHEET_COST = 300; // 무료 1시트/일 소진 후 (functions와 일치)

export default function App() {
  const [subject, setSubject] = useState('');
  const [style, setStyle] = useState('oldschool');
  const [colorMode, setColorMode] = useState('bw'); // bw | color
  const [count, setCount] = useState(1);
  const [premium, setPremium] = useState(false);

  const [designs, setDesigns] = useState([]); // [{id, image, subject, style, engine, checked}]
  const [current, setCurrent] = useState(null);
  const [sheetTitle, setSheetTitle] = useState('');

  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(null); // {done, total}
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [quota, setQuota] = useState(null);

  const [user, setUser] = useState(null);
  const [coins, setCoins] = useState(null);
  const [showAuth, setShowAuth] = useState(false);
  const [showTopup, setShowTopup] = useState(false);

  // 시착 탭: photo(내 사진) / model(AI 가상 모델 — 프레임은 App이 보관해 도안 바꿔도 유지)
  const [tryOnTab, setTryOnTab] = useState('photo');
  const [model, setModel] = useState({ gender: 'female', frames: null, applied: null });

  useEffect(() => watchAuth(setUser), []);
  useEffect(() => watchWallet(user?.uid, setCoins), [user?.uid]);

  const handleChargeError = (e) => {
    setError(isInsufficientBalance(e) ? 'INSUFFICIENT_BALANCE' : e.message);
  };

  // 토스 결제 리디렉션 처리 (/payment/success · /payment/fail)
  const tossHandledRef = useRef(false);
  useEffect(() => {
    const path = window.location.pathname;
    if (path !== '/payment/success' && path !== '/payment/fail') return;
    if (tossHandledRef.current) return;
    if (path === '/payment/fail') {
      tossHandledRef.current = true;
      const qs = new URLSearchParams(window.location.search);
      setNotice(`❌ 결제가 실패했습니다. ${qs.get('message') || qs.get('code') || ''}`);
      window.history.replaceState(null, '', '/');
      return;
    }
    if (!user) return;
    const qs = new URLSearchParams(window.location.search);
    const paymentKey = qs.get('paymentKey');
    const orderId = qs.get('orderId');
    const amount = Number(qs.get('amount'));
    if (!paymentKey || !orderId || !Number.isFinite(amount)) {
      window.history.replaceState(null, '', '/');
      return;
    }
    tossHandledRef.current = true;
    (async () => {
      try {
        const r = await creditTossPayment({ paymentKey, orderId, amount });
        setNotice(
          r.alreadyCredited
            ? `이미 적립된 주문입니다. 잔액 ${r.balance.toLocaleString()}코인`
            : `✅ ${r.credited.toLocaleString()}코인이 충전되었습니다!`
        );
      } catch {
        setNotice(`⚠️ 결제 승인 확인 실패 (주문번호 ${orderId}) — 잠시 후 잔액을 확인해주세요.`);
      } finally {
        window.history.replaceState(null, '', '/');
      }
    })();
  }, [user]);

  const generateOne = async (s) => {
    const engine = premium ? 'premium' : 'standard';
    if (firebaseEnabled) {
      return generateDesignViaFirebase({ subject: s, style, engine, color: colorMode });
    }
    const res = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subject: s, style, engine, color: colorMode }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  };

  const generate = useCallback(async () => {
    const s = subject.trim();
    if (!s || loading) return;
    if (firebaseEnabled && !user) {
      setError('Please sign in to create designs.');
      return;
    }
    setLoading(true);
    setError('');
    try {
      for (let i = 0; i < count; i++) {
        setProgress({ done: i, total: count });
        const data = await generateOne(s);
        const item = {
          id: Date.now() + i,
          image: data.image,
          subject: s,
          style,
          engine: data.engine,
          translatedPrompt: data.translatedPrompt || null,
          checked: true,
        };
        setDesigns((p) => [item, ...p].slice(0, 60));
        setCurrent(item);
        if (data.quota) setQuota(data.quota);
      }
    } catch (e) {
      handleChargeError(e);
    } finally {
      setLoading(false);
      setProgress(null);
    }
  }, [subject, style, count, premium, loading, user]);

  const toggleCheck = (id) => {
    setDesigns((p) => p.map((x) => (x.id === id ? { ...x, checked: !x.checked } : x)));
  };

  const removeDesign = (id) => {
    setDesigns((p) => p.filter((x) => x.id !== id));
    setCurrent((c) => (c?.id === id ? null : c));
  };

  const downloadPng = (item) => {
    const a = document.createElement('a');
    a.href = item.image;
    a.download = `inkcraft-${item.id}.jpg`;
    a.click();
  };

  // 흰 종이 배경을 투명으로 제거한 도안 PNG (클라이언트 연산, 무료)
  const downloadNoBg = async (item) => {
    try {
      const png = await removeWhiteBg(item.image);
      const a = document.createElement('a');
      a.href = png;
      a.download = `inkcraft-${item.id}-nobg.png`;
      a.click();
    } catch {
      setError('Background removal failed.');
    }
  };

  const selectedDesigns = designs.filter((p) => p.checked);

  const exportSheet = async () => {
    if (!selectedDesigns.length || exporting) return;
    if (firebaseEnabled && !user) {
      setError('Please sign in to export a flash sheet.');
      return;
    }
    setExporting(true);
    setError('');
    try {
      // PDF는 로컬 생성이라, 과금 게이트만 서버에서 확인 (무료 1시트/일 → 300코인)
      if (firebaseEnabled) await chargeFeature('sheet_export');
      await buildFlashSheet({
        title: sheetTitle.trim() || 'My Flash Sheet',
        pages: selectedDesigns.map((p) => p.image).reverse(), // 만든 순서대로
        fileName: (sheetTitle.trim() || 'inkcraft-flash-sheet').replace(/[^\w가-힣-]+/g, '-'),
      });
      setNotice(`🖋️ 플래시 시트 다운로드 완료! (${selectedDesigns.length} designs)`);
    } catch (e) {
      handleChargeError(e);
    } finally {
      setExporting(false);
    }
  };

  const randomSubject = () => {
    setSubject(SUBJECT_SEEDS[Math.floor(Math.random() * SUBJECT_SEEDS.length)]);
  };

  const scrollToStudio = () => {
    document.getElementById('studio')?.scrollIntoView({ behavior: 'smooth' });
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">🖋️</span> Ink<b>Craft</b>
        </div>
        <div className="topbar-right">
          {quota && (
            <span className="quota">
              Free today: {Math.max(0, quota.limit - quota.used)}/{quota.limit}
            </span>
          )}
          {firebaseEnabled && user && typeof coins === 'number' && (
            <button className="coins" onClick={() => setShowTopup(true)} title="코인 충전">
              🪙 {coins.toLocaleString()} <span className="coins-plus">+</span>
            </button>
          )}
          {firebaseEnabled &&
            (user ? (
              <button className="auth-btn" onClick={signOut} title={user.email}>
                {user.photoURL ? <img className="avatar" src={user.photoURL} alt="" /> : '👤'} Sign out
              </button>
            ) : (
              <button className="auth-btn primary" onClick={() => setShowAuth(true)}>
                Sign in
              </button>
            ))}
          {!firebaseEnabled && <span className="devchip">local dev</span>}
        </div>
      </header>

      {firebaseEnabled && user && !user.emailVerified &&
        user.providerData?.some((p) => p.providerId === 'password') && (
          <div className="verify-banner">
            📧 이메일 인증이 필요합니다. 받은편지함을 확인해주세요.
            <button onClick={() => resendVerification().then(() => setNotice('📧 인증 메일을 다시 보냈습니다.'))}>
              인증 메일 재발송
            </button>
          </div>
        )}

      {notice && (
        <div className="notice-bar">
          {notice}
          <button onClick={() => setNotice('')}>✕</button>
        </div>
      )}

      {/* ── 히어로 ── */}
      <section className="hero">
        <h1>
          Your idea, inked as a <em>tattoo design.</em>
        </h1>
        <p className="hero-sub">
          Type an idea, pick a style — <b>stencil-ready designs in seconds</b>. No subscription.
        </p>
        <button className="cta hero-cta" onClick={scrollToStudio}>🖋️ Design My Tattoo — Free</button>
        <div className="hero-features">
          <div className="feature">
            <span>⚓</span>
            <h3>14 styles</h3>
            <p>Old school to anime — black &amp; grey or color.</p>
          </div>
          <div className="feature">
            <span>🧍</span>
            <h3>Try it on</h3>
            <p>Your photo or a 360° AI model, before/after.</p>
          </div>
          <div className="feature">
            <span>📄</span>
            <h3>Flash sheet</h3>
            <p>Print-ready A4 PDF for your artist.</p>
          </div>
        </div>
      </section>

      <main className="layout" id="studio">
        {/* 좌측: 입력 패널 */}
        <section className="panel controls">
          <h2>1. Idea</h2>
          <div className="prompt-row">
            <textarea
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); generate(); }
              }}
              placeholder="e.g. a snake coiled around a dagger (한국어 OK)"
              rows={3}
            />
            <button className="ghost" onClick={randomSubject} title="Random idea">🎲</button>
          </div>

          <h2>2. Ink</h2>
          <div className="seg ink-seg">
            {COLOR_MODES.map((c) => (
              <button
                key={c.id}
                className={colorMode === c.id ? 'active' : ''}
                onClick={() => setColorMode(c.id)}
                title={c.desc}
              >
                {c.emoji} {c.label}
              </button>
            ))}
          </div>

          <h2>3. Style</h2>
          <div className="style-grid">
            {STYLES.map((d) => (
              <button
                key={d.id}
                className={`style-card ${style === d.id ? 'active' : ''}`}
                onClick={() => setStyle(d.id)}
              >
                <span className="style-emoji">{d.emoji}</span>
                <b>{d.label}</b>
                <small>{d.tag}</small>
                <span className="style-desc">{d.desc}</span>
              </button>
            ))}
          </div>

          <h2>4. Variations</h2>
          <div className="seg">
            {[1, 2, 4].map((n) => (
              <button key={n} className={count === n ? 'active' : ''} onClick={() => setCount(n)}>
                {n} design{n > 1 ? 's' : ''}
              </button>
            ))}
          </div>

          <label className={`premium-toggle ${premium ? 'on' : ''}`}>
            <input type="checkbox" checked={premium} onChange={(e) => setPremium(e.target.checked)} />
            <span className="pt-slider" aria-hidden="true" />
            <span className="pt-text">
              <b>✨ Premium</b>
              <small>Cleaner lines{firebaseEnabled ? ' · 150 coins' : ''}</small>
            </span>
          </label>

          <button className="cta" onClick={generate} disabled={loading || !subject.trim()}>
            {loading
              ? progress
                ? `Inking… ${progress.done + 1}/${progress.total}`
                : 'Inking…'
              : `🖋️ Create ${count > 1 ? `${count} Designs` : 'Design'}`}
          </button>
          {error === 'INSUFFICIENT_BALANCE' ? (
            <p className="error">
              🪙 코인이 부족합니다.{' '}
              <button className="link-btn" onClick={() => { setError(''); setShowTopup(true); }}>
                충전하기 →
              </button>
            </p>
          ) : (
            error && <p className="error">{error}</p>
          )}
        </section>

        {/* 우측: 미리보기 + 도안 보관함 */}
        <section className="panel preview">
          <h2>Preview</h2>
          <div className="preview-stage">
            {!current && !loading && (
              <div className="placeholder">
                <p>👈 Create a design to see it here.</p>
              </div>
            )}
            {loading && <div className="spinner" aria-label="loading" />}
            {current && !loading && (
              <img className="page-view" src={current.image} alt={current.subject} />
            )}
          </div>
          {current && (
            <div className="preview-actions">
              <div className="btn-row">
                <button className="cta secondary" onClick={() => downloadPng(current)}>⬇️ Download PNG</button>
                {!current.isTryOn && (
                  <button className="cta secondary" onClick={() => downloadNoBg(current)} title="흰 배경을 투명으로 제거한 PNG">
                    ⬇️ PNG (no bg)
                  </button>
                )}
                <button className="cta secondary" onClick={() => removeDesign(current.id)}>🗑️ Remove</button>
              </div>
              <p className="caption">
                {current.engine === 'premium' && <span className="engine-badge">✨ Premium</span>}
                {current.isTryOn && <span className="engine-badge">🧴 Try-on</span>}
                <span>{current.subject}</span>
                {current.translatedPrompt && (
                  <span className="translated"> → EN: "{current.translatedPrompt}"</span>
                )}
              </p>
            </div>
          )}

          {/* 시착: 내 사진 or AI 가상 모델 — 시착 결과물은 다시 도안으로 쓸 수 없으므로 숨김 */}
          {current && !current.isTryOn && (
            <div className="seg tryon-tabs">
              <button className={tryOnTab === 'photo' ? 'active' : ''} onClick={() => setTryOnTab('photo')}>
                📷 My photo
              </button>
              <button className={tryOnTab === 'model' ? 'active' : ''} onClick={() => setTryOnTab('model')}>
                🧍 AI model 360°
              </button>
            </div>
          )}
          {current && !current.isTryOn && tryOnTab === 'model' && (
            <ModelStudio
              design={current.image}
              model={model}
              setModel={setModel}
              onError={handleChargeError}
              showCosts={firebaseEnabled}
              beforeManual={firebaseEnabled ? () => chargeFeature('manual_apply') : null}
              aiView={async (payload) => {
                if (firebaseEnabled) {
                  if (!user) throw new Error('Please sign in to use the AI model.');
                  return modelViewViaFirebase(payload);
                }
                const res = await fetch('/api/model-view', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
                return data;
              }}
              aiApply={async (payload) => {
                if (firebaseEnabled) {
                  if (!user) throw new Error('Please sign in to use the AI model.');
                  return modelApplyViaFirebase(payload);
                }
                const res = await fetch('/api/model-apply', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(payload),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
                return data;
              }}
            />
          )}
          {current && !current.isTryOn && tryOnTab === 'photo' && (
            <TryOnStudio
              design={current.image}
              onError={handleChargeError}
              showCosts={firebaseEnabled}
              beforeManual={firebaseEnabled ? () => chargeFeature('manual_apply') : null}
              aiApply={async ({ photo, design, bodyPart }) => {
                if (firebaseEnabled) return applyTattooViaFirebase({ photo, design, bodyPart });
                const res = await fetch('/api/apply-tattoo', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ photo, design, bodyPart }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
                return data;
              }}
              onResult={({ image, method, bodyPart }) => {
                const item = {
                  id: Date.now(),
                  image,
                  subject: `${current.subject} → on my ${bodyPart} (${method === 'ai' ? 'AI' : 'manual'})`,
                  style: current.style,
                  engine: method === 'ai' ? 'premium' : current.engine,
                  translatedPrompt: null,
                  isTryOn: true,
                  checked: false, // 시착 결과는 플래시 시트에서 기본 제외
                };
                setDesigns((p) => [item, ...p].slice(0, 60));
                setCurrent(item);
                setNotice(method === 'ai' ? '✨ AI 시착 완료!' : '✅ 시착 적용 완료!');
              }}
            />
          )}

          {designs.length > 0 && (
            <>
              <h2>My designs ({selectedDesigns.length} selected)</h2>
              <div className="pages-grid">
                {designs.map((p) => (
                  <div key={p.id} className={`page-thumb ${current?.id === p.id ? 'active' : ''}`}>
                    <img src={p.image} alt={p.subject} onClick={() => setCurrent(p)} />
                    <label className="thumb-check">
                      <input type="checkbox" checked={p.checked} onChange={() => toggleCheck(p.id)} />
                    </label>
                  </div>
                ))}
              </div>

              {/* 플래시 시트 바 */}
              <div className="pack-bar">
                <input
                  type="text"
                  maxLength={40}
                  placeholder="Sheet title (optional)"
                  value={sheetTitle}
                  onChange={(e) => setSheetTitle(e.target.value)}
                />
                <button
                  className="cta"
                  onClick={exportSheet}
                  disabled={exporting || !selectedDesigns.length}
                  title={firebaseEnabled ? `무료 1시트/일, 이후 ${SHEET_COST}코인` : undefined}
                >
                  {exporting
                    ? 'Building…'
                    : `📄 Flash Sheet (${selectedDesigns.length})${firebaseEnabled ? ` · ${SHEET_COST}🪙` : ''}`}
                </button>
              </div>
            </>
          )}
        </section>
      </main>

      <footer className="footer">
        FLUX.1 [schnell] · reference art — final stencil by your artist.
      </footer>

      {showAuth && <AuthModal onClose={() => setShowAuth(false)} />}
      {showTopup && user && (
        <TopupModal user={user} onClose={() => setShowTopup(false)} onNotice={setNotice} />
      )}
    </div>
  );
}
