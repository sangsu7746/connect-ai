// ════════════════════════════════════════════════════════════════
// 브라우저 영상 합성 엔진 (ffmpeg.wasm) — 서버 비용 0
//   1) imageToSceneClip : 사진 → Ken Burns 모션 + 자막·워터마크를 "클립에 구워" 만든다
//      (자막은 zoompan 이후 정적 overlay라 흔들림 없이 선명)
//   2) concatClips      : 클립들을 이어붙이고 BGM(+나레이션)만 믹스.
//      자막이 이미 구워져 있어 영상 재인코딩이 불필요 → -c:v copy(가장 빠름) 우선,
//      실패 시 필터 없는 재인코딩 → 무음 순으로 폴백. (기존 병목: 병합에서 30초 전체
//      재인코딩 + 자막 7장 오버레이 → 제거)
// ════════════════════════════════════════════════════════════════
import { FFmpeg } from '@ffmpeg/ffmpeg'
import { fetchFile, toBlobURL } from '@ffmpeg/util'

let ffmpegInstance: FFmpeg | null = null
let isLoaded = false

const BGM_VOLUME = 0.28

export interface VoiceClip { audioUrl: string; start: number }
export interface MergeResult {
  url: string
  hasNarration: boolean
  hasBgm: boolean
}

let seq = 0
const uid = () => `${Date.now().toString(36)}_${(seq++).toString(36)}`

export const FFmpegService = {
  async load(onProgress?: (ratio: number) => void): Promise<boolean> {
    if (isLoaded && ffmpegInstance) return true
    try {
      ffmpegInstance = new FFmpeg()
      if (onProgress) ffmpegInstance.on('progress', ({ progress }) => onProgress(Math.min(1, Math.max(0, progress))))
      const baseURL = 'https://unpkg.com/@ffmpeg/core@0.12.6/dist/esm'
      await ffmpegInstance.load({
        coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, 'text/javascript'),
        wasmURL: await toBlobURL(`${baseURL}/ffmpeg-core.wasm`, 'application/wasm'),
      })
      isLoaded = true
      return true
    } catch (e) {
      console.error('FFmpeg.wasm 로드 실패:', e)
      return false
    }
  },

  /**
   * 사진 1장 → Ken Burns(줌인) 모션 클립. 자막(WxH 투명 PNG)·워터마크(코너)를 함께 구워 넣는다.
   * 자막은 zoompan 이후 0:0 정적 overlay라 줌과 무관하게 선명하게 고정된다.
   * 무음 오디오 트랙을 함께 넣어 이후 concat/믹스에서 스트림이 어긋나지 않게 한다.
   */
  async imageToSceneClip(
    imageUrl: string, durationSec: number, W: number, H: number,
    captionPngUrl?: string, watermarkPngUrl?: string,
  ): Promise<string> {
    const loaded = await this.load()
    if (!loaded || !ffmpegInstance) throw new Error('FFmpeg를 불러오지 못해 모션 클립을 만들 수 없어요.')
    const ffmpeg = ffmpegInstance
    const dur = Math.max(1, durationSec)
    const tag = uid()
    const inName = `img_${tag}.jpg`
    const outName = `clip_${tag}.mp4`
    await ffmpeg.writeFile(inName, await fetchFile(imageUrl))

    const fps = 25
    const frames = Math.round(dur * fps)
    const even = (n: number) => Math.round(n / 2) * 2
    const sw = even(W * 1.25), sh = even(H * 1.25)

    // 입력 인덱스: 0=사진, (자막), (워터마크), 마지막=무음오디오
    const args = ['-loop', '1', '-i', inName]
    let idx = 1
    let capIdx = -1, wmIdx = -1
    if (captionPngUrl) {
      try { await ffmpeg.writeFile(`cap_${tag}.png`, await fetchFile(captionPngUrl)); args.push('-i', `cap_${tag}.png`); capIdx = idx++ } catch { /* skip */ }
    }
    if (watermarkPngUrl) {
      try { await ffmpeg.writeFile(`wm_${tag}.png`, await fetchFile(watermarkPngUrl)); args.push('-i', `wm_${tag}.png`); wmIdx = idx++ } catch { /* skip */ }
    }
    args.push('-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100')
    const aIdx = idx++

    const parts = [
      `[0:v]scale=${sw}:${sh}:force_original_aspect_ratio=increase,crop=${sw}:${sh},` +
      `zoompan=z='min(zoom+0.0011,1.16)':d=${frames}:s=${W}x${H}:fps=${fps}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'[bg]`,
    ]
    let vlabel = '[bg]'
    if (capIdx >= 0) { parts.push(`${vlabel}[${capIdx}:v]overlay=0:0[vc]`); vlabel = '[vc]' }
    if (wmIdx >= 0) { parts.push(`${vlabel}[${wmIdx}:v]overlay=main_w-overlay_w-24:main_h-overlay_h-24[vw]`); vlabel = '[vw]' }

    await ffmpeg.exec([
      ...args,
      '-filter_complex', parts.join(';'),
      '-map', vlabel, '-map', `${aIdx}:a`, '-t', String(dur),
      '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-r', String(fps),
      '-c:a', 'aac', '-shortest', outName,
    ])
    const data = await ffmpeg.readFile(outName)
    await ffmpeg.deleteFile(inName).catch(() => {})
    if (capIdx >= 0) await ffmpeg.deleteFile(`cap_${tag}.png`).catch(() => {})
    return URL.createObjectURL(new Blob([data as BlobPart], { type: 'video/mp4' }))
  },

  /**
   * 클립들을 이어붙이고 BGM(+나레이션)을 믹스한다. 자막·워터마크는 이미 클립에 구워져 있어
   * 영상 재인코딩이 필요 없다 → 1) -c:v copy(최속) → 2) 필터없는 재인코딩 → 3) 무음 순 폴백.
   */
  async concatClips(
    videoUrls: string[], bgmUrl?: string, voiceClips: VoiceClip[] = [], maxDurationSec?: number,
  ): Promise<MergeResult> {
    if (videoUrls.length === 0) return { url: '', hasNarration: false, hasBgm: false }
    const loaded = await this.load()
    if (!loaded || !ffmpegInstance) return { url: videoUrls[0], hasNarration: false, hasBgm: false }
    const ffmpeg = ffmpegInstance

    try {
      const inputNames: string[] = []
      for (let i = 0; i < videoUrls.length; i++) {
        const name = `in_${i}.mp4`
        await ffmpeg.writeFile(name, await fetchFile(videoUrls[i]))
        inputNames.push(name)
      }
      await ffmpeg.writeFile('concat.txt', inputNames.map(n => `file '${n}'`).join('\n'))

      let hasBgm = false
      if (bgmUrl) {
        try { await ffmpeg.writeFile('bgm.mp3', await fetchFile(bgmUrl)); hasBgm = true }
        catch (e) { console.warn('BGM 로드 실패:', e) }
      }
      const loadedVoice: { filename: string; start: number }[] = []
      for (let i = 0; i < voiceClips.length; i++) {
        try { await ffmpeg.writeFile(`voice_${i}.mp3`, await fetchFile(voiceClips[i].audioUrl)); loadedVoice.push({ filename: `voice_${i}.mp3`, start: voiceClips[i].start }) }
        catch (e) { console.warn(`나레이션 ${i} 로드 실패:`, e) }
      }
      const hasVoice = loadedVoice.length > 0

      // 오디오 필터(그래프)를 구성한다 — 없으면 무음(클립 트랙)만
      const buildAudio = (bgm: boolean, voice: boolean): { fc: string[]; inputs: string[]; map: string | null } => {
        if (!bgm && !voice) return { fc: [], inputs: [], map: null }
        const fc: string[] = [], inputs: string[] = [], srcs: string[] = []
        let n = 1 // 입력 0은 concat
        if (bgm) { inputs.push('-i', 'bgm.mp3'); fc.push(`[${n}:a]volume=${BGM_VOLUME}[bgmq]`); srcs.push('[bgmq]'); n++ }
        if (voice) loadedVoice.forEach((v, i) => { inputs.push('-i', v.filename); fc.push(`[${n}:a]adelay=${Math.round(v.start * 1000)}:all=1[nar${i}]`); srcs.push(`[nar${i}]`); n++ })
        fc.push(`${srcs.join('')}amix=inputs=${srcs.length}:duration=longest:dropout_transition=0:normalize=0[aout]`)
        return { fc, inputs, map: '[aout]' }
      }

      const attempts = [
        { label: 'copy+오디오', copy: true, bgm: hasBgm, voice: hasVoice },
        { label: '재인코딩+오디오', copy: false, bgm: hasBgm, voice: hasVoice },
        { label: '재인코딩+BGM', copy: false, bgm: hasBgm, voice: false },
        { label: '재인코딩 기본', copy: false, bgm: false, voice: false },
      ]

      let lastError: unknown = null
      for (const a of attempts) {
        try {
          const { fc, inputs, map } = buildAudio(a.bgm, a.voice)
          const args = ['-f', 'concat', '-safe', '0', '-i', 'concat.txt', ...inputs]
          if (fc.length) args.push('-filter_complex', fc.join(';'))
          args.push('-map', '0:v', '-c:v', a.copy ? 'copy' : 'libx264')
          if (!a.copy) args.push('-preset', 'ultrafast', '-pix_fmt', 'yuv420p')
          if (map) { args.push('-map', map, '-c:a', 'aac', '-shortest') }
          else { args.push('-map', '0:a?', '-c:a', 'copy') }
          if (!a.copy && maxDurationSec && maxDurationSec > 0) args.push('-t', String(Math.max(1, maxDurationSec)))
          args.push('output.mp4')

          await ffmpeg.exec(args)
          const data = await ffmpeg.readFile('output.mp4')
          const url = URL.createObjectURL(new Blob([data as BlobPart], { type: 'video/mp4' }))
          return { url, hasNarration: a.voice, hasBgm: a.bgm }
        } catch (e) {
          console.warn(`[FFmpeg] "${a.label}" 실패 — 다음 단계로:`, e)
          lastError = e
        }
      }

      // 최후: 무음(영상만)
      try {
        await ffmpeg.exec(['-f', 'concat', '-safe', '0', '-i', 'concat.txt', '-map', '0:v', '-c:v', 'copy', '-an', 'silent.mp4'])
        const data = await ffmpeg.readFile('silent.mp4')
        return { url: URL.createObjectURL(new Blob([data as BlobPart], { type: 'video/mp4' })), hasNarration: false, hasBgm: false }
      } catch (e) {
        console.error('모든 병합 시도 실패:', lastError, e)
        return { url: videoUrls[0], hasNarration: false, hasBgm: false }
      }
    } catch (err) {
      console.error('병합 실행 오류:', err)
      return { url: videoUrls[0], hasNarration: false, hasBgm: false }
    }
  },
}
