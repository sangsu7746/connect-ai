import { Routes, Route, Navigate } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import Home from './pages/Home'
import Import from './pages/Import'
import Review from './pages/Review'
import Concept from './pages/Concept'
import Storyboard from './pages/Storyboard'
import Generate from './pages/Generate'
import Result from './pages/Result'
import Profile from './pages/Profile'

// 제작 위저드: [1] 홈 → [2] 블로그 가져오기 → [3] 매물정보 확인 → [4] 컨셉·길이 → [5] 제작 → [6] 결과
export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Home />} />
        <Route path="/profile" element={<Profile />} />
      </Route>

      <Route element={<AppShell headerProps={{ showBack: true, title: '블로그 가져오기' }} hideBottomNav />}>
        <Route path="/import" element={<Import />} />
      </Route>
      <Route element={<AppShell headerProps={{ showBack: true, title: '매물 정보 확인' }} hideBottomNav />}>
        <Route path="/review" element={<Review />} />
      </Route>
      <Route element={<AppShell headerProps={{ showBack: true, title: '컨셉 · 길이' }} hideBottomNav />}>
        <Route path="/concept" element={<Concept />} />
      </Route>
      <Route element={<AppShell headerProps={{ showBack: true, title: '대본 · 씬 편집' }} hideBottomNav />}>
        <Route path="/storyboard" element={<Storyboard />} />
      </Route>
      <Route element={<AppShell headerProps={{ title: '영상 제작 중' }} hideBottomNav />}>
        <Route path="/generate" element={<Generate />} />
      </Route>
      <Route element={<AppShell headerProps={{ showBack: true, title: '완성 영상' }} hideBottomNav />}>
        <Route path="/result" element={<Result />} />
      </Route>

      <Route path="/create" element={<Navigate to="/import" replace />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
