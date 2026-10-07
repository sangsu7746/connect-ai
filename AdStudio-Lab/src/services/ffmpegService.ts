import { FFmpeg } from '@ffmpeg/ffmpeg'
import { fetchFile, toBlobURL } from '@ffmpeg/util'

let ffmpegInstance: FFmpeg | null = null
let isLoaded = false

// 나레이션 대비 BGM 음량 비율 — 배경음악이 대사를 덮지 않도록 낮춰 깐다.
// (amix를 normalize=0으로 쓰기 때문에 이 값이 그대로 최종 믹스 비율이 된다)
const BGM_VOLUME = 0.25

/**
 * 최종 병합 영상의 마감 품질 옵션 — 무료(영구) 티어의 무료 슬롯 제작에 적용된다.
 * 포인트 결제·pro 제작은 옵션 없이(원본 화질·워터마크 없음) 마감한다.
 */
export interface FinishOptions {
  // 우측 하단에 얹을 반투명 워터마크 텍스트 (예: 'AdStudio')
  watermarkText?: string
  // 출력 가로 해상도 상한 (예: 720 → 세로영상 720×1280) — 지정 시 초과분을 다운스케일
  maxWidth?: number
}

/** mergeVideoClips의 반환값 — 실제로 최종 영상에 반영된 요소가 무엇인지 호출부에 알려준다. */
export interface MergeResult {
  url: string
  hasSubtitles: boolean
  hasVoice: boolean
  hasBgm: boolean
}

/**
 * 워터마크 텍스트를 Canvas로 그려 PNG 바이트로 만든다 — ffmpeg.wasm 기본 코어는 drawtext용
 * 폰트 파일이 없어서, 브라우저 폰트로 미리 그린 이미지를 overlay 필터로 얹는 방식이 가장 확실하다.
 */
async function renderWatermarkPng(text: string): Promise<Uint8Array | null> {
  try {
    const font = '600 30px -apple-system, "Segoe UI", Roboto, sans-serif'
    const measure = document.createElement('canvas').getContext('2d')!
    measure.font = font
    const textWidth = Math.ceil(measure.measureText(text).width)

    const pad = 10
    const canvas = document.createElement('canvas')
    canvas.width = textWidth + pad * 2
    canvas.height = 44 + pad
    const ctx = canvas.getContext('2d')!
    ctx.font = font
    ctx.textBaseline = 'middle'
    // 밝은 배경에서도 읽히도록 어두운 그림자 + 반투명 흰 글자
    ctx.shadowColor = 'rgba(0,0,0,0.45)'
    ctx.shadowBlur = 4
    ctx.shadowOffsetY = 1
    ctx.fillStyle = 'rgba(255,255,255,0.55)'
    ctx.fillText(text, pad, canvas.height / 2)

    const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/png'))
    if (!blob) return null
    return new Uint8Array(await blob.arrayBuffer())
  } catch (e) {
    console.warn('워터마크 이미지를 만들지 못해 워터마크 없이 진행합니다:', e)
    return null
  }
}

/**
 * 자막 한 줄(한 씬 대사)을 Canvas로 그려 PNG 바이트 + 크기를 반환한다.
 * ffmpeg.wasm 코어에는 한글 폰트가 없어 subtitles 필터로는 한글이 □□□로 깨지거나 안 보인다 —
 * 워터마크와 동일하게 브라우저 폰트로 미리 그려 overlay로 얹는 방식이 한글에 가장 확실하다.
 *
 * 스타일: 하단 중앙, 굵게, 흰 글자 + 반투명 검정 박스. 길면 videoWidth에 맞춰 자동 줄바꿈.
 */
function renderSubtitlePng(
  text: string,
  videoWidth: number
): { bytes: Uint8Array; width: number; height: number } | null {
  try {
    // 세로 영상 기준 가독 크기 — 폭의 4.5%를 글자 크기로, 좌우 8% 여백
    const fontSize = Math.round(videoWidth * 0.045)
    const sidePad = Math.round(videoWidth * 0.08)
    const maxTextWidth = videoWidth - sidePad * 2
    const font = `700 ${fontSize}px "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif`

    const measure = document.createElement('canvas').getContext('2d')!
    measure.font = font

    // 자동 줄바꿈 — 어절 단위로 최대 폭 안에 맞춘다. 한 어절이 폭을 넘으면 글자 단위로 쪼갠다.
    const lines: string[] = []
    let cur = ''
    const pushWord = (w: string) => {
      const trial = cur ? cur + ' ' + w : w
      if (measure.measureText(trial).width <= maxTextWidth) { cur = trial; return }
      if (cur) { lines.push(cur); cur = '' }
      if (measure.measureText(w).width <= maxTextWidth) { cur = w; return }
      // 아주 긴 한 어절: 글자 단위로 강제 분할
      let chunk = ''
      for (const ch of w) {
        if (measure.measureText(chunk + ch).width > maxTextWidth) { lines.push(chunk); chunk = ch }
        else chunk += ch
      }
      cur = chunk
    }
    for (const w of text.trim().split(/\s+/)) pushWord(w)
    if (cur) lines.push(cur)

    const lineHeight = Math.round(fontSize * 1.35)
    const boxPadX = Math.round(fontSize * 0.5)
    const boxPadY = Math.round(fontSize * 0.35)
    const textBlockH = lineHeight * lines.length
    const canvasH = textBlockH + boxPadY * 2

    const canvas = document.createElement('canvas')
    canvas.width = videoWidth
    canvas.height = canvasH
    const ctx = canvas.getContext('2d')!
    ctx.font = font
    ctx.textBaseline = 'middle'
    ctx.textAlign = 'center'

    // 각 줄마다 딱 맞는 반투명 검정 박스 + 흰 글자(가독용 얇은 외곽선)
    lines.forEach((line, i) => {
      const cy = boxPadY + lineHeight * i + lineHeight / 2
      const w = measure.measureText(line).width
      const boxW = w + boxPadX * 2
      const boxX = (videoWidth - boxW) / 2
      ctx.fillStyle = 'rgba(0,0,0,0.55)'
      const r = Math.round(fontSize * 0.25)
      // 둥근 모서리 박스
      ctx.beginPath()
      ctx.roundRect(boxX, boxPadY + lineHeight * i, boxW, lineHeight, r)
      ctx.fill()
      ctx.lineJoin = 'round'
      ctx.strokeStyle = 'rgba(0,0,0,0.85)'
      ctx.lineWidth = Math.max(2, Math.round(fontSize * 0.08))
      ctx.strokeText(line, videoWidth / 2, cy)
      ctx.fillStyle = '#ffffff'
      ctx.fillText(line, videoWidth / 2, cy)
    })

    // 동기 경로가 필요 없으므로 즉시 바이트로
    const url = canvas.toDataURL('image/png')
    const b64 = url.split(',')[1]
    const bin = atob(b64)
    const bytes = new Uint8Array(bin.length)
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
    return { bytes, width: canvas.width, height: canvas.height }
  } catch (e) {
    console.warn('자막 이미지를 만들지 못해 이 자막은 건너뜁니다:', e)
    return null
  }
}

export const FFmpegService = {
  /**
   * FFmpeg.wasm을 로드하고 초기화합니다.
   */
  async load(): Promise<boolean> {
    if (isLoaded && ffmpegInstance) return true

    try {
      ffmpegInstance = new FFmpeg()

      // CDN에서 FFmpeg 코어 및 wasm 로드
      const baseURL = 'https://unpkg.com/@ffmpeg/core@0.12.6/dist/esm'
      await ffmpegInstance.load({
        coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, 'text/javascript'),
        wasmURL: await toBlobURL(`${baseURL}/ffmpeg-core.wasm`, 'application/wasm'),
      })

      isLoaded = true
      console.log('FFmpeg.wasm loaded successfully')
      return true
    } catch (e) {
      console.error('Failed to load FFmpeg.wasm:', e)
      return false // 폴백 처리 대상
    }
  },

  /**
   * 정지된 키프레임 이미지 한 장을 Ken Burns(서서히 줌인) 효과의 짧은 영상 클립으로 변환합니다.
   * '무빙포토' 레인처럼 외부 AI 영상 생성 API 없이 즉시·무료로 클립을 만들 때 사용합니다.
   * 무음 오디오 트랙(anullsrc)을 같이 넣어두는데, 이게 없으면 이 클립이 다른 씬과 이어붙을 때
   * concat 결과의 0:a 스트림 자체가 사라져서 mergeVideoClips의 대사/BGM 믹스 시도(0:a에 기대는
   * 단계들)가 전부 실패해 최종 영상이 원치 않게 완전 무음으로 떨어지는 원인이 된다.
   */
  async imageToVideoClip(
    imageUrl: string,
    durationSec: number,
    targetW = 1080,
    targetH = 1920
  ): Promise<string> {
    const loaded = await this.load()
    if (!loaded || !ffmpegInstance) {
      throw new Error('FFmpeg를 불러오지 못해 무빙포토 클립을 만들 수 없어요.')
    }

    const ffmpeg = ffmpegInstance
    const safeDuration = Math.max(1, durationSec)
    const inputName = `kf_${Date.now()}_${Math.floor(Math.random() * 1e6)}.jpg`
    const outputName = `mv_${Date.now()}_${Math.floor(Math.random() * 1e6)}.mp4`

    await ffmpeg.writeFile(inputName, await fetchFile(imageUrl))

    const fps = 24
    const frames = Math.round(safeDuration * fps)
    // 입력을 크게 업스케일한 뒤 서서히 확대하며 목표 해상도로 크롭 (표준 zoompan Ken Burns 기법)
    const scaleW = targetW * 2
    const vf = `scale=${scaleW}:-2,zoompan=z='min(zoom+0.0015,1.4)':d=${frames}:s=${targetW}x${targetH}:fps=${fps}`

    await ffmpeg.exec([
      '-loop', '1',
      '-i', inputName,
      '-f', 'lavfi',
      '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
      '-vf', vf,
      '-t', String(safeDuration),
      '-map', '0:v',
      '-map', '1:a',
      '-c:v', 'libx264',
      '-pix_fmt', 'yuv420p',
      '-c:a', 'aac',
      '-shortest',
      outputName,
    ])

    const data = await ffmpeg.readFile(outputName)
    return URL.createObjectURL(new Blob([data as any], { type: 'video/mp4' }))
  },

  /**
   * 여러 개의 비디오 URL과 음악 트랙, 대사 음성, 자막을 받아 하나로 병합합니다.
   * ffmpeg.wasm 기본 코어는 자막(libass) 렌더링을 지원하지 않는 경우가 있고, 무빙포토 클립은
   * 애초에 오디오 트랙 자체가 없어서(정지 이미지 소스) 원본 오디오(0:a)에 기대는 필터는 씬 소스에
   * 따라 실패할 수 있습니다 — 그래서 대사 음성/BGM 믹스는 원본 오디오 트랙에 의존하지 않고
   * 새로 추가한 오디오 입력들만으로 구성하며, 자막+음성+BGM → 음성+BGM → BGM만(기존 방식) →
   * 기본 병합 순으로 단계적으로 대체하며 최대한 온전한 결과물을 만듭니다.
   * 반환값에는 실제로 최종 결과물에 반영된 요소(자막/음성/BGM)를 같이 돌려줘, 호출부가 "이번
   * 영상은 대사가 빠졌어요" 같은 안내를 사용자에게 보여줄 수 있게 한다.
   */
  async mergeVideoClips(
    videoUrls: string[],
    subtitles: { text: string; start: number; end: number }[],
    voiceClips: { audioUrl: string; start: number }[] = [],
    bgmUrl?: string,
    finish?: FinishOptions,
    // 최종 출력 길이 상한(초). 보통 실제 영상 길이를 넘겨 BGM이 더 길어도 함께 끊기게 한다.
    // (-shortest는 filter_complex와 함께 쓸 때 신뢰도가 떨어져, 길이를 명시적으로 못박는다)
    maxDurationSec?: number
  ): Promise<MergeResult> {
    if (videoUrls.length === 0) return { url: '', hasSubtitles: false, hasVoice: false, hasBgm: false }

    const loaded = await this.load()
    if (!loaded || !ffmpegInstance) {
      console.warn('FFmpeg loading failed, falling back to first clip')
      return { url: videoUrls[0], hasSubtitles: false, hasVoice: false, hasBgm: false }
    }

    const ffmpeg = ffmpegInstance

    try {
      // 0. 무료 마감 준비 — 워터마크 PNG 생성/로드 (실패해도 병합 자체는 계속)
      let hasWatermark = false
      if (finish?.watermarkText) {
        const wmBytes = await renderWatermarkPng(finish.watermarkText)
        if (wmBytes) {
          await ffmpeg.writeFile('wm.png', wmBytes)
          hasWatermark = true
        }
      }
      const maxWidth = finish?.maxWidth
      // 1. 비디오 파일 쓰기
      const inputNames: string[] = []
      for (let i = 0; i < videoUrls.length; i++) {
        const name = `input_${i}.mp4`
        await ffmpeg.writeFile(name, await fetchFile(videoUrls[i]))
        inputNames.push(name)
      }

      // 2. Concat 파일 내용 작성
      const concatContent = inputNames.map(name => `file '${name}'`).join('\n')
      await ffmpeg.writeFile('concat.txt', concatContent)

      // 3. 자막 이미지(PNG) 사전 렌더링 — ffmpeg.wasm은 한글 폰트가 없어 subtitles 필터로는
      //    한글이 깨지므로, 워터마크와 같은 방식으로 브라우저 Canvas에서 그려 overlay로 얹는다.
      //    각 자막은 자기 씬 대사가 나오는 구간(start~end)에만 나타나게 enable로 시간 제어한다.
      // 자막 폭 기준이 될 영상 가로 해상도를 첫 클립에서 읽는다(무료 마감 다운스케일 폭도 반영).
      let subtitleVideoWidth = 720
      try {
        const probeW = await new Promise<number>((resolve) => {
          const v = document.createElement('video')
          const t = setTimeout(() => resolve(0), 5000)
          v.onloadedmetadata = () => { clearTimeout(t); resolve(v.videoWidth || 0); v.src = '' }
          v.onerror = () => { clearTimeout(t); resolve(0) }
          v.preload = 'metadata'; v.src = videoUrls[0]
        })
        if (probeW > 0) subtitleVideoWidth = maxWidth ? Math.min(maxWidth, probeW) : probeW
        else if (maxWidth) subtitleVideoWidth = maxWidth
      } catch { /* 기본값 720 사용 */ }

      const loadedSubs: { filename: string; start: number; end: number; height: number }[] = []
      for (let i = 0; i < subtitles.length; i++) {
        const s = subtitles[i]
        if (!s.text.trim()) continue
        const png = renderSubtitlePng(s.text, subtitleVideoWidth)
        if (!png) continue
        const filename = `sub_${i}.png`
        await ffmpeg.writeFile(filename, png.bytes)
        loadedSubs.push({ filename, start: s.start, end: s.end, height: png.height })
      }
      const hasSubtitles = loadedSubs.length > 0

      // 4. BGM 로드 (실패 시 BGM 없이 진행)
      let hasBgm = false
      if (bgmUrl) {
        try {
          await ffmpeg.writeFile('bgm.mp3', await fetchFile(bgmUrl))
          hasBgm = true
        } catch (e) {
          console.warn('BGM 파일을 불러오지 못해 BGM 없이 진행합니다:', e)
        }
      }

      // 5. 대사 음성 클립 로드 (개별 클립 실패는 건너뛰고 나머지로 진행)
      const loadedVoiceClips: { filename: string; start: number }[] = []
      for (let i = 0; i < voiceClips.length; i++) {
        const filename = `voice_${i}.mp3`
        try {
          await ffmpeg.writeFile(filename, await fetchFile(voiceClips[i].audioUrl))
          loadedVoiceClips.push({ filename, start: voiceClips[i].start })
        } catch (e) {
          console.warn(`음성 클립 ${i}를 불러오지 못해 건너뜁니다:`, e)
        }
      }
      const hasVoice = loadedVoiceClips.length > 0

      // 6. 단계적 병합 시도: 자막+음성+BGM → 음성+BGM → BGM만(원본 오디오+BGM, 기존 방식) → 기본 병합
      // → 무음 병합(영상만) — 무빙포토 클립은 오디오 트랙이 아예 없어 '0:a' 매핑 자체가 실패하므로,
      // 오디오를 전부 포기하고 영상 트랙만이라도 병합(+무료 마감 필터)하는 최후 단계가 필요하다
      // 강등 순서는 "덜 중요한 것부터 버린다" 원칙을 따른다.
      // 광고에서 나레이션은 메시지 그 자체라 BGM보다 우선순위가 높다 — 그래서 음성을 포기하기 전에
      // 반드시 'BGM만 제외하고 음성은 살리는' 단계를 먼저 시도한다.
      const attempts: { label: string; includeSubs: boolean; includeVoice: boolean; includeBgm: boolean; videoOnly?: boolean }[] = [
        { label: '자막+음성+BGM 병합', includeSubs: hasSubtitles, includeVoice: hasVoice, includeBgm: hasBgm },
        { label: '음성+BGM 병합 (자막 제외)', includeSubs: false, includeVoice: hasVoice, includeBgm: hasBgm },
        { label: '음성 병합 (BGM 제외)', includeSubs: false, includeVoice: hasVoice, includeBgm: false },
        { label: 'BGM 병합 (음성 제외)', includeSubs: false, includeVoice: false, includeBgm: hasBgm },
        { label: '기본 병합', includeSubs: false, includeVoice: false, includeBgm: false },
        { label: '무음 병합 (영상만)', includeSubs: hasSubtitles, includeVoice: false, includeBgm: false, videoOnly: true },
      ]

      let lastError: unknown = null
      for (const attempt of attempts) {
        try {
          const args = ['-f', 'concat', '-safe', '0', '-i', 'concat.txt']
          let nextInputIdx = 1

          const filterParts: string[] = []
          // 항상 videoLabel을 기준으로 다음 필터를 체이닝한다 — 그대로 최종 -map에도 쓸 수 있게
          // 가공 안 된 상태(0:v)는 대괄호 없이, 필터를 거친 중간 라벨은 대괄호를 유지한다
          let videoLabel = '0:v'
          const videoInputRef = () => (videoLabel.startsWith('[') ? videoLabel : `[${videoLabel}]`)
          let audioMap = '0:a'

          // 무료 마감: 해상도 상한 다운스케일 → (자막) → 워터마크 오버레이 순서로 체이닝
          let wmIdx = -1
          if (hasWatermark) {
            args.push('-i', 'wm.png')
            wmIdx = nextInputIdx++
          }

          // 자막 PNG들을 입력으로 등록 (이 시도에서 자막을 포함할 때만)
          const subInputIdx: number[] = []
          if (attempt.includeSubs) {
            for (const sub of loadedSubs) {
              args.push('-i', sub.filename)
              subInputIdx.push(nextInputIdx++)
            }
          }
          if (maxWidth) {
            // 원본이 상한보다 작으면 업스케일하지 않도록 min()으로 묶는다 (-2: 짝수 높이 자동)
            filterParts.push(`${videoInputRef()}scale='min(${maxWidth},iw)':-2[vscaled]`)
            videoLabel = '[vscaled]'
          }

          if (attempt.includeSubs && subInputIdx.length > 0) {
            // 각 자막 PNG를 하단 중앙에, 자기 대사 구간(start~end)에만 표시한다.
            // 여러 자막이 순차로 겹치지 않게 각각 enable 시간창을 건다. 위치는 하단에서 살짝 띄운다.
            loadedSubs.forEach((sub, k) => {
              const bottomMargin = 40
              const y = `main_h-${sub.height}-${bottomMargin}`
              const outLabel = `[vsub${k}]`
              filterParts.push(
                `${videoInputRef()}[${subInputIdx[k]}:v]overlay=(main_w-overlay_w)/2:${y}:enable='between(t,${sub.start.toFixed(2)},${sub.end.toFixed(2)})'${outLabel}`
              )
              videoLabel = outLabel
            })
          }

          if (wmIdx >= 0) {
            filterParts.push(`${videoInputRef()}[${wmIdx}:v]overlay=main_w-overlay_w-24:main_h-overlay_h-24[vwm]`)
            videoLabel = '[vwm]'
          }

          if (attempt.includeVoice) {
            // 음성(+BGM)은 원본 클립 오디오(0:a)에 기대지 않고 새로 추가한 입력만으로 믹스한다
            // (무빙포토 클립은 오디오 트랙이 아예 없어 0:a를 참조하면 실패하기 때문)
            let bgmLabel = ''
            if (attempt.includeBgm) {
              args.push('-i', 'bgm.mp3')
              const bgmIdx = nextInputIdx++
              // BGM은 나레이션에 묻히지 않도록 낮춰 깐다
              filterParts.push(`[${bgmIdx}:a]volume=${BGM_VOLUME}[bgmq]`)
              bgmLabel = '[bgmq]'
            }

            const audioSources: string[] = []
            loadedVoiceClips.forEach((vc, i) => {
              args.push('-i', vc.filename)
              const idx = nextInputIdx++
              filterParts.push(`[${idx}:a]adelay=${Math.round(vc.start * 1000)}:all=1[voice${i}]`)
              audioSources.push(`[voice${i}]`)
            })
            if (bgmLabel) audioSources.push(bgmLabel)

            // duration=longest — first로 두면 "가장 먼저 끝나는 입력"인 첫 나레이션 클립이 끝나는
            // 순간 오디오 전체가 잘려서, 영상 앞 3~5초에만 소리가 나는 증상이 생긴다.
            // normalize=0 — 입력 개수만큼 음량이 1/N로 깎이는 것을 막는다(나레이션 클립들은 adelay로
            // 서로 다른 구간에 배치돼 겹치지 않으므로 합산해도 과도해지지 않는다).
            filterParts.push(
              `${audioSources.join('')}amix=inputs=${audioSources.length}:duration=longest:dropout_transition=0:normalize=0[aout]`
            )
            audioMap = '[aout]'
          } else if (attempt.includeBgm) {
            // 음성 없이 BGM만 — 원본 오디오와 믹스. 여기서는 첫 입력이 영상 길이라 duration=first가 맞다.
            args.push('-i', 'bgm.mp3')
            const bgmIdx = nextInputIdx++
            filterParts.push(`[${bgmIdx}:a]volume=${BGM_VOLUME}[bgmq]`)
            filterParts.push(`[0:a][bgmq]amix=inputs=2:duration=first:normalize=0[aout]`)
            audioMap = '[aout]'
          }

          if (filterParts.length > 0) {
            args.push('-filter_complex', filterParts.join(';'))
          }

          if (attempt.videoOnly) {
            args.push('-map', videoLabel, '-an')
          } else {
            args.push('-map', videoLabel, '-map', audioMap)
            args.push('-shortest')
          }
          // 출력 길이를 영상 길이로 못박는다 — BGM이 더 길어도 "정지화면 + 음악만"으로 늘어지지 않는다
          if (maxDurationSec && maxDurationSec > 0) {
            args.push('-t', String(Math.max(1, maxDurationSec)))
          }
          args.push('-c:v', 'libx264', '-pix_fmt', 'yuv420p', 'output.mp4')

          await ffmpeg.exec(args)
          const data = await ffmpeg.readFile('output.mp4')
          const url = URL.createObjectURL(new Blob([data as any], { type: 'video/mp4' }))
          return { url, hasSubtitles: attempt.includeSubs, hasVoice: attempt.includeVoice, hasBgm: attempt.includeBgm }
        } catch (e) {
          console.warn(`[FFmpeg] "${attempt.label}" 실패, 다음 단계로 대체합니다:`, e)
          lastError = e
        }
      }

      console.error('모든 병합 시도가 실패했습니다:', lastError)
      return { url: videoUrls[0], hasSubtitles: false, hasVoice: false, hasBgm: false }
    } catch (err) {
      console.error('Error during FFmpeg merge execution:', err)
      return { url: videoUrls[0], hasSubtitles: false, hasVoice: false, hasBgm: false }
    }
  }
}

/**
 * SRT 시간 포맷 변환 유틸 (00:00:00,000)
 */
function formatTime(seconds: number): string {
  const date = new Date(0)
  date.setSeconds(seconds)
  const ms = Math.floor((seconds % 1) * 1000)
  const timeString = date.toISOString().substr(11, 8)
  return `${timeString},${ms.toString().padStart(3, '0')}`
}
