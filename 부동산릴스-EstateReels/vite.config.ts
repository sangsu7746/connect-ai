import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// 주: ffmpeg.wasm은 단일스레드 코어(@ffmpeg/core)를 쓰므로 COOP/COEP(SharedArrayBuffer) 헤더가
// 필요 없다. 오히려 그 헤더를 켜면 폰트·ffmpeg 코어(unpkg)·이미지 프록시 등 교차출처 리소스가
// CORP 없이는 막히므로 설정하지 않는다.
export default defineConfig({
  plugins: [react()],
})
