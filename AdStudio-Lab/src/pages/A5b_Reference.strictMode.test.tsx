// @vitest-environment jsdom
import { StrictMode, useEffect, useRef } from 'react'
import { createRoot } from 'react-dom/client'
// React 19 는 act() 를 react-dom/test-utils 대신 'react' 에서 직접 내보낸다.
import { act } from 'react'
import { describe, it, expect, afterEach, beforeAll } from 'vitest'

// React 18+ 의 act() 는 테스트 환경임을 명시적으로 알려줘야 경고 없이 동작한다.
// @testing-library/react 는 이걸 내부에서 자동으로 세팅해주지만, 여기서는 직접 쓴다.
declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean | undefined
}

/**
 * A5b_Reference.tsx 의 cancelledRef 취소 플래그 패턴을 그대로 복제한 최소 재현 컴포넌트.
 *
 * ⚠️ 회귀 배경(코디네이터 2차 리뷰, Critical): 최초 구현은
 *   `useEffect(() => () => { cancelledRef.current = true }, [])` 처럼 cleanup 에서만
 *   값을 세웠다. main.tsx 가 앱 전체를 <React.StrictMode> 로 감싸고 있어, 개발 모드에서
 *   React 가 마운트 직후 이펙트를 setup → cleanup → setup 순으로 이중 호출한다.
 *   `useRef(false)` 는 최초 렌더에서만 초기화되므로, 첫 setup 뒤 합성 cleanup 이
 *   cancelledRef.current 를 true 로 세우면 두 번째 setup 이 그 값을 되돌리지 않아
 *   "마운트 직후부터 취소 상태"로 굳어버렸다. 그 결과 commit() 이 항상 조용히 return 해
 *   setAdConcept/navigate 가 전혀 실행되지 않고, busy 도 영원히 풀리지 않았다
 *   (프로덕션 빌드는 StrictMode 이중 호출이 꺼져 있어 재현되지 않는다).
 *
 * 고친 버전은 setup 에서도 false 로 리셋한다 — 이 테스트는 그 리셋이 실제로
 * StrictMode 이중 마운트를 이겨내는지를 jsdom 렌더로 고정한다.
 */
function CancelFlagProbe({ onReady }: { onReady: (ref: { current: boolean }) => void }) {
  const cancelledRef = useRef(false)
  useEffect(() => {
    cancelledRef.current = false
    return () => { cancelledRef.current = true }
  }, [])
  onReady(cancelledRef)
  return null
}

describe('cancelledRef 패턴 — StrictMode 이중 마운트 회귀 (A5b_Reference.tsx)', () => {
  beforeAll(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true })

  let container: HTMLDivElement | null = null

  afterEach(() => {
    if (container) {
      document.body.removeChild(container)
      container = null
    }
  })

  it('StrictMode 의 setup→cleanup→setup 이중 호출 후에도 취소 플래그가 false 로 남는다', () => {
    container = document.createElement('div')
    document.body.appendChild(container)

    let latestRef: { current: boolean } | null = null
    const root = createRoot(container)

    act(() => {
      root.render(
        <StrictMode>
          <CancelFlagProbe onReady={(ref) => { latestRef = ref }} />
        </StrictMode>,
      )
    })

    expect(latestRef).not.toBeNull()
    // setup 에서 리셋하지 않는 옛 패턴이었다면, StrictMode 의 두 번째 커밋 이후에도
    // 첫 cleanup 이 세운 true 가 남아 이 지점에서 실패한다.
    expect(latestRef!.current).toBe(false)

    act(() => { root.unmount() })
  })
})
