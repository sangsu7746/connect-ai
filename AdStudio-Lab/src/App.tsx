import { Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import { Clock, CheckCircle, Loader } from 'lucide-react'
import { AppShell } from './components/layout/AppShell'
import { ChargeModal } from './components/ChargeModal'

// AdStudio 9단계 파이프라인:
// [1] A1 홈 → [2] A2 자료 업로드(분석) → [3] A3 광고 컨셉 → [4] A4 배우 설정(+사진이면 A4 업로드)
// → [5] A5 컨셉 선택 → [6] A6 스토리보드([7] 영상모델 설정 포함) → [8] A8 제작 중 → [9] A9 완성 광고
// [5]~[9]는 오마주 구성 그대로 (extraction·LTX·지갑 인가·ffmpeg 합성)
import A1Home from './pages/A1_Home'
import A2Source from './pages/A2_Source'
import A3AdConcept from './pages/A3_AdConcept'
import A4Actor from './pages/A4_Actor'
import A4Upload from './pages/A4_Upload'
import A5Concept from './pages/A5_Concept'
import A5bReference from './pages/A5b_Reference'
import A6Storyboard from './pages/A6_Storyboard'
import A8Progress from './pages/A8_Progress'
import A9Result from './pages/A9_Result'
import KeysPage from './pages/KeysPage'
import ProfilePage from './pages/ProfilePage'
import { PaymentSuccess, PaymentFail } from './pages/PaymentReturn'

import { useProjectStore } from './stores/projectStore'
import { useUserStore } from './stores/userStore'
import { useAdStore } from './stores/adStore'

/**
 * "새 광고 만들기" 진입점(/create) — 이전 광고의 분석·컨셉 상태를 반드시 비우고 시작한다.
 * 설정을 저장(persist)하게 되면서, 초기화하지 않으면 지난 광고의 제품 분석·컨셉 4축이
 * 브라우저를 껐다 켜도 그대로 남아 새 광고에 섞여 들어간다.
 */
function StartNewAd() {
  const reset = useAdStore(s => s.reset)
  useEffect(() => { reset() }, [reset])
  return <Navigate to="/source" replace />
}

// 내 작업 목록
function ProjectsPage() {
  const navigate = useNavigate()
  const { projects, loadProjects } = useProjectStore()
  const { user } = useUserStore()

  useEffect(() => {
    if (user) {
      loadProjects(user.uid)
    }
  }, [user, loadProjects])

  const statusInfo = (status: string) => {
    if (status === 'done') return { icon: <CheckCircle size={14} color="var(--color-success)" />, text: '완료' }
    if (status === 'rendering') return { icon: <Loader size={14} color="var(--color-brand-400)" />, text: '생성 중' }
    return { icon: <Clock size={14} color="var(--color-text-muted)" />, text: '대기 중' }
  }

  return (
    <div style={{ padding: '20px 16px', paddingBottom: 100 }}>
      <h1 style={{ fontSize: '1.375rem', fontWeight: 800, marginBottom: 16 }}>내 광고</h1>

      {!user ? (
        <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--color-text-muted)' }}>
          <p style={{ marginBottom: 14 }}>로그인하시면 제작 내역을 보실 수 있습니다.</p>
          <button className="btn btn-primary" onClick={() => navigate('/profile')}>
            로그인하러 가기
          </button>
        </div>
      ) : projects.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--color-text-muted)' }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>🎬</div>
          <p>아직 만든 광고가 없습니다.</p>
          <button
            className="btn btn-primary"
            style={{ marginTop: 16 }}
            onClick={() => navigate('/source')}
          >
            첫 광고 만들기
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {projects.map(p => {
            const s = statusInfo(p.status)
            return (
              <div
                key={p.id}
                style={{
                  display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px',
                  background: 'var(--color-bg-card)', border: '1px solid var(--color-border)',
                  borderRadius: 12,
                }}
              >
                {p.thumbUrl ? (
                  <img src={p.thumbUrl} alt="" style={{ width: 44, height: 44, objectFit: 'cover', borderRadius: 8 }} />
                ) : (
                  <div style={{
                    width: 44, height: 44, borderRadius: 8, display: 'flex',
                    alignItems: 'center', justifyContent: 'center', fontSize: 20,
                    background: 'rgba(124,58,255,0.12)',
                  }}>🎬</div>
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 700, fontSize: '0.9rem' }}>광고 영상</div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                    {p.createdAt instanceof Date ? p.createdAt.toLocaleDateString() : ''}
                  </div>
                </div>
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                  {s.icon} {s.text}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <>
    <ChargeModal />
    <Routes>
      {/* 메인 앱 셸 (헤더 + 바텀 내비) */}
      <Route element={<AppShell />}>
        <Route path="/"         element={<A1Home />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/keys"     element={<KeysPage />} />
        <Route path="/profile"  element={<ProfilePage />} />
      </Route>

      {/* [2] 자료 업로드 → Gemini 분석 */}
      <Route element={<AppShell headerProps={{ showBack: true, title: '자료 업로드' }} hideBottomNav />}>
        <Route path="/source" element={<A2Source />} />
      </Route>

      {/* [3] 광고 컨셉 (나레이션·길이·음악·음성) */}
      <Route element={<AppShell headerProps={{ showBack: true, title: '광고 컨셉' }} hideBottomNav />}>
        <Route path="/adconcept" element={<A3AdConcept />} />
      </Route>

      {/* [4] 배우 설정 — AI 가상 배우 / 내 사진 모델 */}
      <Route element={<AppShell headerProps={{ showBack: true, title: '배우 설정' }} hideBottomNav />}>
        <Route path="/actor" element={<A4Actor />} />
      </Route>

      {/* [4-사진] 배우 사진 업로드 (오마주 S2 그대로 — 얼굴 인식·동의) */}
      <Route element={<AppShell headerProps={{ showBack: true, title: '배우 사진 업로드' }} hideBottomNav />}>
        <Route path="/upload" element={<A4Upload />} />
      </Route>

      {/* [5] 컨셉 선택 (오마주 S3 그대로) */}
      <Route element={<AppShell headerProps={{ showBack: true, title: '컨셉 선택' }} hideBottomNav />}>
        <Route path="/concept" element={<A5Concept />} />
      </Route>

      {/* [5b] 유튜브 오마주 — 레퍼런스 영상 선택 */}
      <Route element={<AppShell headerProps={{ showBack: true, title: '레퍼런스 선택' }} hideBottomNav />}>
        <Route path="/reference" element={<A5bReference />} />
      </Route>

      {/* [6] 스토리보드 + [7] 영상모델 설정 (오마주 S4 그대로) */}
      <Route element={<AppShell headerProps={{ showBack: true, title: '스토리보드' }} hideBottomNav />}>
        <Route path="/storyboard" element={<A6Storyboard />} />
      </Route>

      {/* [8] 제작 중 (오마주 S5 그대로 — 지갑 인가·렌더 파이프라인) */}
      <Route element={<AppShell headerProps={{ title: '제작 중' }} hideBottomNav />}>
        <Route path="/progress"     element={<A8Progress />} />
        <Route path="/progress/:id" element={<A8Progress />} />
      </Route>

      {/* [9] 완성 광고 (오마주 S6 그대로) */}
      <Route element={<AppShell headerProps={{ title: '완성 광고' }} hideBottomNav />}>
        <Route path="/result"     element={<A9Result />} />
        <Route path="/result/:id" element={<A9Result />} />
      </Route>

      {/* 토스 결제 복귀 (충전 모달 → 토스 결제창 → 여기로 리디렉션) */}
      <Route element={<AppShell headerProps={{ title: '포인트 충전' }} hideBottomNav />}>
        <Route path="/payment/success" element={<PaymentSuccess />} />
        <Route path="/payment/fail"    element={<PaymentFail />} />
      </Route>

      {/* 리디렉트 — 바텀 내비 가운데 + 버튼은 /create를 가리킨다 */}
      <Route path="/create" element={<StartNewAd />} />
      <Route path="*"       element={<Navigate to="/" replace />} />
    </Routes>
    </>
  )
}
