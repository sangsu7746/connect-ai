import { useState } from 'react';
import { signIn, emailSignUp, emailSignIn, resetPassword } from './firebase.js';

const AUTH_ERRORS = {
  'auth/email-already-in-use': 'This email is already registered.',
  'auth/invalid-email': 'Invalid email address.',
  'auth/weak-password': 'Password must be at least 6 characters.',
  'auth/invalid-credential': 'Wrong email or password.',
  'auth/user-not-found': 'No account found with this email.',
  'auth/wrong-password': 'Wrong email or password.',
  'auth/too-many-requests': 'Too many attempts. Try again later.',
};

/** 로그인/가입 모달 — Google + 이메일/비밀번호 (가입 시 인증 메일 발송) */
export default function AuthModal({ onClose }) {
  const [mode, setMode] = useState('signin'); // signin | signup | reset
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // {type: 'error'|'info', text}

  const fail = (e) => {
    setMsg({ type: 'error', text: AUTH_ERRORS[e?.code] || e.message });
  };

  const google = async () => {
    setBusy(true); setMsg(null);
    try { await signIn(); onClose(); } catch (e) { fail(e); } finally { setBusy(false); }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setMsg(null);
    try {
      if (mode === 'signup') {
        await emailSignUp(email, password);
        setMsg({ type: 'info', text: '📧 Verification email sent! Please check your inbox, then sign in.' });
        setMode('signin');
      } else if (mode === 'reset') {
        await resetPassword(email);
        setMsg({ type: 'info', text: '📧 Password reset email sent.' });
        setMode('signin');
      } else {
        await emailSignIn(email, password);
        onClose();
      }
    } catch (err) { fail(err); } finally { setBusy(false); }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>✕</button>
        <h3>
          {mode === 'signup' ? 'Create account' : mode === 'reset' ? 'Reset password' : 'Sign in'}
        </h3>

        <button className="cta google-btn" onClick={google} disabled={busy}>
          <svg width="18" height="18" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.1H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.1 29.4 4 24 4 13 4 4 13 4 24s9 20 20 20 20-9 20-20c0-1.3-.1-2.6-.4-3.9z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.9 1.2 8 3l5.7-5.7C34.3 6.1 29.4 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.1H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C41.4 34.9 44 30 44 24c0-1.3-.1-2.6-.4-3.9z"/></svg>
          Continue with Google
        </button>

        <div className="divider"><span>or email</span></div>

        <form onSubmit={submit} className="auth-form">
          <input
            type="email" required placeholder="Email"
            value={email} onChange={(e) => setEmail(e.target.value)}
          />
          {mode !== 'reset' && (
            <input
              type="password" required minLength={6} placeholder="Password (6+ chars)"
              value={password} onChange={(e) => setPassword(e.target.value)}
            />
          )}
          <button className="cta" type="submit" disabled={busy}>
            {busy ? '…' : mode === 'signup' ? 'Create account' : mode === 'reset' ? 'Send reset email' : 'Sign in'}
          </button>
        </form>

        {msg && <p className={msg.type === 'error' ? 'error' : 'info-msg'}>{msg.text}</p>}

        <div className="auth-links">
          {mode === 'signin' ? (
            <>
              <button onClick={() => { setMode('signup'); setMsg(null); }}>Create account</button>
              <button onClick={() => { setMode('reset'); setMsg(null); }}>Forgot password?</button>
            </>
          ) : (
            <button onClick={() => { setMode('signin'); setMsg(null); }}>← Back to sign in</button>
          )}
        </div>
      </div>
    </div>
  );
}
