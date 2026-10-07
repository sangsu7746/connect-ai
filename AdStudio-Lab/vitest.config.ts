import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    // 순수 함수 위주라 node 환경이면 충분하다. DOM 이 필요한 테스트가 생기면
    // 해당 파일 상단에 `// @vitest-environment jsdom` 을 붙인다.
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    // 브라우저 전용 모듈(ffmpeg.wasm, mediapipe)을 끌어오는 파일은 테스트하지 않는다
    exclude: ['**/node_modules/**', '**/dist/**'],
  },
})
