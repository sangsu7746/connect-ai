import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App'
import { initAuth } from './stores/userStore'

// 로그인 세션 복원(선택적 로그인) — SDK 초기화는 오프라인 안전, 실패해도 앱은 정상 동작
initAuth()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
)
