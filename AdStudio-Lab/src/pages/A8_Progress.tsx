import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  CheckCircle, Loader, AlertCircle, Clock,
  ChevronRight, Sparkles, Film, RefreshCw, ExternalLink, Zap
} from 'lucide-react'
import { useProjectStore } from '../stores/projectStore'
import { useUserStore, LoginRequiredError } from '../stores/userStore'
import type { SceneStatus, RenderResult } from '../types'
import { renderScene, buildLocalizedDialogue } from '../services/sceneRenderer'
import { FFmpegService } from '../services/ffmpegService'
import { QuotaExhaustedError } from '../services/aiAdapters'
import { DailyLimitError } from '../services/dailyUsage'
import { ensureRenderAuthorization, releaseRenderAuthorization, InsufficientPointsError } from '../services/walletService'
import { useChargeModal } from '../stores/chargeModalStore'
import { useAdStore } from '../stores/adStore'
import { resolveBgmUrl } from '../services/bgmService'
import { LOCALE_INFO } from '../services/localizationService'

const ALIBABA_CONSOLE_URL = 'https://modelstudio.console.alibabacloud.com/ap-southeast-1?tab=dashboard#/api-key'
// ⚠️ 미확인: ModelArk 콘솔의 Resource packs 화면 직접 링크(딥링크) — 확인 전이라 KeysPage와 동일하게
// BytePlus 최상위 주소만 쓴다. 콘솔에서 실제 URL을 확인하면 그 주소로 교체할 것.
const BYTEPLUS_URL = 'https://www.byteplus.com'

/**
 * 쿼터·잔액 소진 배너의 제공자별 안내.
 *
 * 예전에는 ternary 체인이라 목록에 없는 제공자(hailuo·kling)가 전부 마지막 else로 떨어져
 * "알리바바 무료 쿼터가 소진됐어요" + 알리바바 콘솔 링크라는 엉뚱한 안내를 받았다.
 * 표로 바꿔 제공자가 늘어도 잘못된 콘솔로 유도되지 않게 한다(모르는 제공자는 링크 없이 원문만 표시).
 */
const QUOTA_BANNER: Record<string, { title: string; ctaLabel: string; ctaUrl: string; alibabaWarning?: boolean }> = {
  alibaba: {
    title: '알리바바 무료 쿼터가 소진돼 영상 제작이 정지됐어요',
    ctaLabel: '알리바바 콘솔에서 쿼터·결제 확인하기',
    ctaUrl: ALIBABA_CONSOLE_URL,
    alibabaWarning: true,
  },
  veo: {
    title: 'Veo 영상 생성이 거부돼 제작이 정지됐어요',
    ctaLabel: 'AI Studio에서 키·결제 상태 확인하기',
    ctaUrl: 'https://aistudio.google.com/apikey',
  },
  gemini: {
    title: 'Gemini 쿼터가 소진돼 제작이 정지됐어요',
    ctaLabel: 'AI Studio에서 키·결제 상태 확인하기',
    ctaUrl: 'https://aistudio.google.com/apikey',
  },
  seedance: {
    title: 'Seedance 전용 리소스팩이 없어 제작이 정지됐어요',
    ctaLabel: 'ModelArk에서 리소스팩 확인·구매하기',
    ctaUrl: BYTEPLUS_URL,
  },
  hailuo: {
    // 영상 생성은 Token Plan의 Credits가 아니라 지갑(Balance)에서 차감된다 — 충전 위치를 콕 집어 보낸다
    title: 'MiniMax 잔액이 부족해 제작이 정지됐어요',
    ctaLabel: 'MiniMax 지갑(Balance) 충전하러 가기',
    ctaUrl: 'https://platform.minimax.io/user-center/payment/balance',
  },
  kling: {
    title: 'Kling 리소스 패키지가 없어 제작이 정지됐어요',
    ctaLabel: 'Kling에서 리소스 패키지 구매하기',
    ctaUrl: 'https://kling.ai/dev/pricing?scrollTo=video',
  },
}

/**
 * 미디어 파일의 실제 재생 길이(초)를 읽는다. 실패하면 null.
 *
 * 씬에 설정된 길이(scene.duration)와 실제 생성된 클립 길이는 다를 수 있다 — AI 영상 제공자는
 * 자기 규격(예: 6초)으로 만들기 때문이다. 설정 길이로 자막·음성 타이밍을 잡으면 화면과 어긋나고,
 * 대사가 슬롯보다 길 때 다음 대사와 겹쳐 두 목소리가 동시에 나온다. 그래서 실제 길이를 잰다.
 */
function probeMediaDuration(url: string, kind: 'video' | 'audio'): Promise<number | null> {
  return new Promise(resolve => {
    const el = document.createElement(kind)
    let settled = false
    const done = (v: number | null) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      el.src = ''
      resolve(v)
    }
    const timer = setTimeout(() => done(null), 8000)
    const ok = () => Number.isFinite(el.duration) && el.duration > 0

    el.preload = 'metadata'
    el.onloadedmetadata = () => {
      if (ok()) return done(el.duration)
      // Chrome은 헤더에 길이가 없는 MP3(TTS 출력이 흔히 이렇다)에서 duration을 Infinity로 준다.
      // 아주 먼 시각으로 탐색시키면 실제 끝을 찾아 durationchange로 확정값을 알려준다.
      el.ondurationchange = () => { if (ok()) done(el.duration) }
      try { el.currentTime = 1e6 } catch { done(null) }
    }
    el.onerror = () => done(null)
    el.src = url
  })
}

/**
 * 음성 길이를 못 재었을 때 쓰는 추정치 — 씬 슬롯 길이로 대체하면 대사가 슬롯보다 길 때
 * 겹침이 그대로 재발하므로, 글자 수에서 발화 시간을 어림한다(한국어 TTS 대략 초당 5자).
 */
function estimateSpeechSec(text: string): number {
  const chars = text.trim().length
  return Math.max(1.2, chars / 5 + 0.4)
}

type Phase = 'generating' | 'merging' | 'done' | 'error'

// ── 씬 상태 아이콘 ────────────────────────────────────────────
function SceneStatusIcon({ status }: { status: SceneStatus }) {
  switch (status) {
    case 'done':
    case 'video_done':     return <CheckCircle size={18} color="var(--color-success)" />
    case 'generating_keyframe':
    case 'generating_video': return <Loader size={18} color="var(--color-brand-400)" className="animate-spin" />
    case 'failed':         return <AlertCircle size={18} color="var(--color-error)" />
    default:               return <Clock size={18} color="var(--color-text-muted)" />
  }
}

function statusLabel(status: SceneStatus) {
  const map: Record<SceneStatus, string> = {
    pending: '대기 중',
    generating_keyframe: '키프레임 생성 중',
    keyframe_done: '키프레임 완료',
    in_queue: '대기열 대기',
    generating_video: 'AI 영상 생성 중',
    video_done: '완료',
    done: '완료',
    failed: '실패',
    blocked: '차단됨',
  }
  return map[status] ?? '대기 중'
}

function formatElapsed(sec: number) {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return m > 0 ? `${m}분 ${s}초` : `${s}초`
}

// ── S5 메인 ───────────────────────────────────────────────────
export default function S5Progress() {
  const navigate = useNavigate()
  const {
    scenes, updateScene, selectedLane, setSelectedLane, currentProject,
    saveCurrentProject, addRender, persons, photos,
  } = useProjectStore()
  const { user, language } = useUserStore()

  const [phase, setPhase] = useState<Phase>('generating')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  // 원인별로 안내 배너와 CTA가 달라서 종류를 구분해 둔다
  const [errorKind, setErrorKind] = useState<'generic' | 'quota' | 'login' | 'daily_limit' | 'points'>('generic')
  // 쿼터 소진이 어느 제공자에서 났는지 — 배너 제목·안내·CTA가 제공자마다 달라야 한다
  // (알리바바는 콘솔에서 유료 전환, Veo/Gemini는 결제·키 교체가 해법)
  const [errorProvider, setErrorProvider] = useState<string | null>(null)
  const [noteMessage, setNoteMessage] = useState<string | null>(null)
  const [elapsedSec, setElapsedSec] = useState(0)
  const runningRef = useRef(false)
  const startedAtRef = useRef(Date.now())

  // 여러 씬을 순회하며 서로 다른 안내가 겹칠 수 있어(예: 임시영상 대체 + 인물 일관성 저하)
  // 기존 메시지를 덮어쓰지 않고 누적한다
  const addNote = (message: string) => {
    setNoteMessage(prev => {
      if (!prev) return message
      if (prev.includes(message)) return prev
      return `${prev} ${message}`
    })
  }

  // 만들 씬이 없는 상태로 진입하면 스토리보드로 되돌린다
  useEffect(() => {
    if (scenes.length === 0) {
      navigate('/storyboard', { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const id = setInterval(() => setElapsedSec(Math.round((Date.now() - startedAtRef.current) / 1000)), 1000)
    return () => clearInterval(id)
  }, [])

  // 실제 씬 영상 생성 → FFmpeg 병합까지 이어지는 파이프라인
  const runPipeline = async (resetAll: boolean) => {
    if (runningRef.current) return
    runningRef.current = true
    setPhase('generating')
    setErrorMessage(null)
    setErrorKind('generic')

    try {
      if (resetAll) {
        for (const scene of useProjectStore.getState().scenes) {
          updateScene(scene.id, { videoUrl: undefined, status: 'pending' })
        }
      }

      // 제작 인가 보장(무료 슬롯 또는 포인트 결제) — 최초 진입은 S4에서 이미 인가돼 그대로 통과하고,
      // 전체 실패로 되돌려진 뒤의 "다시 시도"에서는 여기서 다시 확보한다(멱등 refId로 이중 차감 없음)
      await ensureRenderAuthorization(useProjectStore.getState().scenes, selectedLane)

      const targets = [...useProjectStore.getState().scenes].sort((a, b) => a.seq - b.seq)

      for (const target of targets) {
        const live = useProjectStore.getState().scenes.find(s => s.id === target.id)
        if (!live || live.status === 'video_done' || live.status === 'done') continue

        updateScene(live.id, { status: 'generating_video' })
        try {
          const outcome = await renderScene(live, selectedLane, persons, photos)
          updateScene(live.id, { videoUrl: outcome.videoUrl, status: 'video_done' })
          if (outcome.isMocked) {
            addNote(`${String(outcome.provider).toUpperCase()} 연동이 아직 준비 중이라 일부 씬은 임시 영상으로 대체됐어요.`)
          }
          if (outcome.consistencyDegraded) {
            addNote('일부 씬은 인물 참조 이미지 생성에 실패해 텍스트 설명만으로 그려졌어요. 인물 외형이 다르게 보일 수 있어요.')
          }
        } catch (e) {
          updateScene(live.id, { status: 'failed' })
          throw e
        }
      }

      setPhase('merging')

      const orderedScenes = [...useProjectStore.getState().scenes].sort((a, b) => a.seq - b.seq)
      const renderedScenes = orderedScenes.filter(s => !!s.videoUrl)
      const videoUrls = renderedScenes.map(s => s.videoUrl as string)

      // 실제 클립 길이로 타임라인을 만든다 — 설정 길이로 잡으면 화면과 자막·음성이 어긋난다
      // (AI 제공자는 자기 규격대로 만들어서 scene.duration과 실제 길이가 다르다)
      const measuredClips = await Promise.all(videoUrls.map(u => probeMediaDuration(u, 'video')))
      const clipDurations = measuredClips.map((d, i) => d ?? renderedScenes[i].duration)
      const allClipsMeasured = measuredClips.every(d => d !== null)

      // 출력 길이를 못박는 값은 "전부 측정에 성공했을 때만" 넘긴다 —
      // 한 클립이라도 설정 길이로 대체됐다면 총합이 실제보다 짧을 수 있고,
      // 그 값으로 자르면 영상 뒷부분이 통째로 날아간다. 그 경우엔 자르지 않는 쪽이 안전하다.
      // (마지막 프레임이 잘리지 않게 여유 0.3초를 둔다)
      const totalVideoSec = clipDurations.reduce((a, b) => a + b, 0)
      const hardStopSec = allClipsMeasured ? totalVideoSec + 0.3 : undefined
      if (!allClipsMeasured) {
        console.warn('일부 클립 길이를 측정하지 못해 출력 길이 제한을 건너뜁니다 — BGM이 영상보다 길어질 수 있어요.')
      }

      let cursor = 0
      const dialogueEntries: { scene: typeof renderedScenes[number]; start: number; end: number }[] = []
      renderedScenes.forEach((s, i) => {
        const start = cursor
        cursor += clipDurations[i]
        if (s.dialogueKo?.trim()) dialogueEntries.push({ scene: s, start, end: cursor })
      })

      // (AdStudio) 광고 프로젝트는 광고 컨셉[3]에서 고른 나레이션 언어로 번역·더빙한다 (UI 언어와 별개)
      const adState = useAdStore.getState()
      // 광고 판정은 분석 결과 또는 저장된 컨셉 ID(ad_*) 둘 중 하나만 살아 있어도 성립하게 한다 —
      // 하나라도 유실되면 나레이션 언어가 UI 언어(브라우저 기본=영어)로 되돌아가는 사고가 났었다.
      const isAdProject = !!adState.analysis || !!currentProject?.conceptId?.startsWith('ad_')
      const dialogueLocale = isAdProject ? adState.config.narrationLocale : language
      const localizedDialogue = await buildLocalizedDialogue(dialogueEntries, persons, dialogueLocale)

      // 선택한 언어로 번역하지 못한 대사가 있으면 조용히 넘어가지 않고 알려준다
      // (번역 실패 시 성우 언어는 원문에 맞춰지므로 발음은 맞지만, 사용자가 고른 언어는 아니다)
      if (localizedDialogue.some(d => d.translationFailed)) {
        addNote(`일부 대사를 "${LOCALE_INFO[dialogueLocale]?.labelKo ?? dialogueLocale}"로 번역하지 못해 원문 그대로 읽혔어요. 키 페이지에서 Gemini 키를 확인해주세요.`)
      }

      // 대사 중복 방지 — 나레이션이 자기 씬 슬롯보다 길면 다음 대사와 겹쳐 두 목소리가 동시에 난다.
      // 씬 경계를 넘어 이어지는 것(오버)은 허용하되, 다음 대사는 앞 대사가 끝난 뒤에 시작하게 밀어낸다.
      let prevEnd = 0
      const timedDialogue: { text: string; start: number; end: number; audioUrl?: string }[] = []
      for (const d of localizedDialogue) {
        // 측정 실패 시 슬롯 길이로 대체하면 "슬롯보다 긴 대사" 상황에서 겹침이 재발하므로,
        // 글자 수 기반 추정치를 쓰고 슬롯 길이와 비교해 더 긴 쪽을 택한다(보수적으로 밀어냄)
        const fallback = Math.max(estimateSpeechSec(d.text), d.end - d.start)
        const measured = d.audioUrl ? await probeMediaDuration(d.audioUrl, 'audio') : null
        const spoken = measured ?? fallback
        const start = Math.max(d.start, prevEnd)
        // 앞 대사가 끝나자마자 다음 대사가 붙으면 숨 쉴 틈 없이 들리고 꼬리가 겹쳐 들릴 수 있어
        // 최소 간격을 둔다
        prevEnd = start + spoken + 0.15
        timedDialogue.push({ text: d.text, start, end: start + spoken, audioUrl: d.audioUrl })
      }

      // 나레이션 총량이 영상보다 길면 뒤쪽 대사가 잘린다 — 조용히 사라지지 않게 로그로 남긴다
      if (prevEnd > totalVideoSec + 0.5) {
        console.warn(
          `나레이션(${prevEnd.toFixed(1)}초)이 영상(${totalVideoSec.toFixed(1)}초)보다 길어 뒷부분이 잘릴 수 있어요 — 대사를 줄이거나 영상 길이를 늘려주세요.`
        )
      }

      // 자막 on/off — 광고 컨셉[3]에서 끄면 자막을 아예 만들지 않는다(음성 나레이션은 그대로 유지).
      // (광고 프로젝트가 아니면 기존 동작대로 항상 자막 생성)
      const subtitlesOn = adState.analysis ? adState.config.subtitles : true
      const subtitles = subtitlesOn
        ? timedDialogue.map(d => ({ text: d.text, start: d.start, end: d.end }))
        : []
      const voiceClips = timedDialogue
        .filter((d): d is typeof d & { audioUrl: string } => !!d.audioUrl)
        .map(d => ({ audioUrl: d.audioUrl, start: d.start }))

      // 무료 슬롯 제작(cost 0)은 무료 마감(워터마크+720p), 포인트 결제·pro는 원본 화질로 마감한다
      const authz = useProjectStore.getState().pointPayment
      const isFreeFinish = useUserStore.getState().accessTier() === 'free' && (authz?.cost ?? 0) === 0
      const bgmUrl = resolveBgmUrl(currentProject?.conceptId, currentProject?.id ?? '')
      const merged = await FFmpegService.mergeVideoClips(
        videoUrls, subtitles, voiceClips, bgmUrl,
        isFreeFinish ? { watermarkText: 'AdStudio', maxWidth: 720 } : undefined,
        // 실제 영상 길이 — BGM이 더 길어도 여기서 함께 끊어 "정지화면 + 음악만" 상태를 막는다
        hardStopSec
      )
      if (!merged.url) {
        throw new Error('영상 병합에 실패했어요. 잠시 후 다시 시도해주세요.')
      }

      // 대사가 있는 씬이 있었는데도 최종 영상에 음성이 하나도 안 들어갔다면(TTS 전체 실패 또는
      // 병합 단계 강등) 사용자에게 그대로 알려준다 — 조용히 무음 영상만 나오는 걸 방지.
      // 이때 "왜" 실패했는지(월 한도 초과 등)를 함께 알려야 사용자가 조치할 수 있다.
      if (dialogueEntries.length > 0 && !merged.hasVoice) {
        const firstError = localizedDialogue.find(d => d.voiceError)?.voiceError ?? ''
        const isQuota = /429|한도/.test(firstError)
        addNote(
          isQuota
            ? '이번 달 음성 생성 한도를 모두 써서 대사 음성이 들어가지 못했어요. 다음 달에 초기화돼요.'
            : merged.hasSubtitles
              ? '이번 영상은 대사 음성이 빠지고 자막으로만 표시돼요.'
              : '이번 영상은 대사 음성과 자막 없이 완성됐어요.'
        )
      } else if (localizedDialogue.some(d => d.voiceError)) {
        // 일부 씬만 실패한 경우 — 영상은 나왔지만 몇 씬은 무음이라는 사실을 알려준다
        const failed = localizedDialogue.filter(d => d.voiceError).length
        const isQuota = localizedDialogue.some(d => /429|한도/.test(d.voiceError ?? ''))
        addNote(
          isQuota
            ? `이번 달 음성 생성 한도에 걸려 ${failed}개 씬은 음성 없이 완성됐어요.`
            : `${failed}개 씬은 음성 합성에 실패해 자막만 표시돼요.`
        )
      }
      // BGM은 항상 시도하므로(resolveBgmUrl), 병합 단계가 강등돼 빠졌다면 이것도 알려준다
      if (!merged.hasBgm) {
        addNote('이번 영상은 배경음악 없이 완성됐어요.')
      }

      const render: RenderResult = {
        id: crypto.randomUUID(),
        projectId: currentProject?.id ?? '',
        lane: selectedLane,
        videoUrl: merged.url,
        durationSec: orderedScenes.reduce((sum, s) => sum + s.duration, 0),
        createdAt: new Date(),
      }
      addRender(render)

      if (user) {
        try { await saveCurrentProject(user.uid) } catch (e) { console.error('Failed to save project:', e) }
      }

      // 결제가 정상 소비됐으므로 이후 재시도·새 제작에서 재사용되지 않도록 비운다
      useProjectStore.getState().setPointPayment(null)

      setPhase('done')
      setTimeout(() => navigate('/result'), 1200)
    } catch (e) {
      console.error('Scene rendering pipeline failed:', e)

      // 완성된 씬이 하나도 없이 실패했다면 인가를 되돌린다 — 포인트 결제는 전액 자동 환급,
      // 무료 슬롯은 오늘의 카운트를 되살린다.
      // (일부 씬이 완성된 부분 실패는 사용자 API 호출이 실제 소비됐으므로 되돌리지 않고 재시도 유도)
      const { pointPayment, scenes: liveScenes, setPointPayment } = useProjectStore.getState()
      const completedCount = liveScenes.filter(s => s.status === 'video_done' || s.status === 'done').length
      if (pointPayment && completedCount === 0 && !(e instanceof InsufficientPointsError)) {
        try {
          await releaseRenderAuthorization(pointPayment)
          setPointPayment(null)
          if (pointPayment.cost > 0) {
            addNote(`제작이 시작되지 못해 P ${pointPayment.cost}을 자동 환급했어요. 다시 시도하면 재차감돼요.`)
          }
        } catch (refundErr) {
          console.error('자동 환급 실패 — 결제 기록은 유지됩니다(재시도 시 추가 차감 없음):', refundErr)
        }
      }

      setErrorMessage(e instanceof Error ? e.message : '영상 제작 중 오류가 발생했어요.')
      setErrorProvider(e instanceof QuotaExhaustedError ? e.provider : null)
      setErrorKind(
        e instanceof InsufficientPointsError ? 'points' :
        e instanceof QuotaExhaustedError ? 'quota' :
        e instanceof LoginRequiredError ? 'login' :
        e instanceof DailyLimitError ? 'daily_limit' :
        'generic'
      )
      setPhase('error')
    } finally {
      runningRef.current = false
    }
  }

  useEffect(() => {
    if (scenes.length > 0) runPipeline(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const total = scenes.length
  const doneCount = scenes.filter(s => s.status === 'video_done' || s.status === 'done').length
  const overallProgress = total === 0
    ? 0
    : phase === 'done'
    ? 100
    : Math.min(95, Math.round((doneCount / total) * 90) + (phase === 'merging' ? 5 : 0))

  const orderedScenes = [...scenes].sort((a, b) => a.seq - b.seq)

  return (
    <div style={{ padding: '20px 16px', minHeight: '80vh', display: 'flex', flexDirection: 'column', gap: 24 }}>

      {/* 상단 상태 */}
      <div style={{ textAlign: 'center' }}>
        <motion.div
          style={{
            width: 80, height: 80, borderRadius: '50%', margin: '0 auto 16px',
            background: phase === 'error' ? 'var(--color-error)' : 'var(--gradient-brand)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: 'var(--shadow-brand)',
          }}
          animate={phase === 'done'
            ? { scale: [1, 1.2, 1], rotate: [0, 10, -10, 0] }
            : phase === 'error' ? {}
            : { scale: [1, 1.05, 1] }
          }
          transition={{ duration: phase === 'done' ? 0.5 : 2, repeat: (phase === 'done' || phase === 'error') ? 0 : Infinity }}
        >
          {phase === 'done' ? <Sparkles size={36} color="#fff" />
            : phase === 'error' ? <AlertCircle size={36} color="#fff" />
            : <Film size={36} color="#fff" />}
        </motion.div>

        <h1 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: 6 }}>
          {phase === 'done' ? '완성됐어요! 🎬'
            : phase === 'error' ? '문제가 발생했어요'
            : phase === 'merging' ? '영상을 합치는 중이에요'
            : '제작 중이에요'}
        </h1>

        {phase !== 'error' && (
          <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
            경과 시간 {formatElapsed(elapsedSec)}
          </p>
        )}
      </div>

      {/* 오류 배너 */}
      {phase === 'error' && errorMessage && errorKind === 'generic' && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          className="card"
          style={{ borderColor: 'rgba(239,68,68,0.4)', background: 'rgba(239,68,68,0.06)' }}
        >
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 12 }}>
            <AlertCircle size={18} color="var(--color-error)" style={{ flexShrink: 0, marginTop: 2 }} />
            <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
              {errorMessage}
            </div>
          </div>
          <button className="btn btn-primary btn-full" onClick={() => runPipeline(false)}>
            <RefreshCw size={16} /> 다시 시도
          </button>
        </motion.div>
      )}

      {/* 포인트 부족 배너 — headjim.com 충전 페이지로 안내 */}
      {phase === 'error' && errorKind === 'points' && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          className="card"
          style={{ borderColor: 'rgba(124,58,255,0.4)', background: 'rgba(124,58,255,0.06)' }}
        >
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 14 }}>
            <AlertCircle size={18} color="var(--color-brand-400)" style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <div style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: 4 }}>
                포인트가 부족해요
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                {errorMessage}
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <button
              className="btn btn-primary btn-full"
              onClick={() => useChargeModal.getState().open()}
            >
              <ExternalLink size={16} /> 포인트 충전하기
            </button>
            <button className="btn btn-outline btn-full" onClick={() => runPipeline(false)}>
              <RefreshCw size={16} /> 충전 후 다시 시도
            </button>
          </div>
        </motion.div>
      )}

      {/* 비로그인 배너 — 생성은 계정 기준(무료 한도·지갑)이라 로그인으로 안내 */}
      {phase === 'error' && errorKind === 'login' && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          className="card"
          style={{ borderColor: 'rgba(124,58,255,0.4)', background: 'rgba(124,58,255,0.06)' }}
        >
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 14 }}>
            <AlertCircle size={18} color="var(--color-brand-400)" style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <div style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: 4 }}>
                로그인이 필요해요
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                {errorMessage}
              </div>
            </div>
          </div>
          <button className="btn btn-primary btn-full" onClick={() => navigate('/profile')}>
            <Zap size={16} /> 로그인하러 가기
          </button>
        </motion.div>
      )}

      {/* 하루 무료 한도 초과 배너 — 내일 다시 시도하거나 포인트로 계속 */}
      {phase === 'error' && errorKind === 'daily_limit' && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          className="card"
          style={{ borderColor: 'rgba(245,158,11,0.4)', background: 'rgba(245,158,11,0.06)' }}
        >
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 14 }}>
            <AlertCircle size={18} color="var(--color-warning)" style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <div style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: 4 }}>
                오늘의 무료 제작을 다 썼어요
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                {errorMessage} 내일 무료 슬롯이 다시 채워지고, 포인트로는 지금 바로 계속 만들 수 있어요.
              </div>
            </div>
          </div>
          <button
            className="btn btn-primary btn-full"
            onClick={() => useChargeModal.getState().open()}
          >
            <ExternalLink size={16} /> 포인트 충전하러 가기
          </button>
        </motion.div>
      )}

      {/* 알리바바 무료 쿼터 소진 배너 — 영상 제작을 정지하고, 유료 전환 시의 경고문과 대안을 함께 안내 */}
      {phase === 'error' && errorKind === 'quota' && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          className="card"
          style={{ borderColor: 'rgba(245,158,11,0.4)', background: 'rgba(245,158,11,0.06)' }}
        >
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', marginBottom: 12 }}>
            <AlertCircle size={18} color="var(--color-warning)" style={{ flexShrink: 0, marginTop: 2 }} />
            <div>
              <div style={{ fontSize: '0.9rem', fontWeight: 700, marginBottom: 4 }}>
                {QUOTA_BANNER[errorProvider ?? '']?.title ?? '사용 한도에 걸려 영상 제작이 정지됐어요'}
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
                {errorMessage}
              </div>
            </div>
          </div>

          {/* 알리바바만 "무료 쿼터만 사용" 해제 시 실요금이 자동 청구되므로 이 경고가 필요하다.
              다른 제공자에 띄우면 무관한 콘솔로 잘못 유도하게 되므로 알리바바에서만 보여준다. */}
          {QUOTA_BANNER[errorProvider ?? '']?.alibabaWarning && (
            <div style={{
              display: 'flex', gap: 8, alignItems: 'flex-start',
              background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
              borderRadius: 8, padding: '10px 12px', marginBottom: 14,
            }}>
              <span style={{ fontSize: '0.85rem' }}>⚠️</span>
              <p style={{ fontSize: '0.78rem', color: 'var(--color-text-secondary)', lineHeight: 1.5, margin: 0 }}>
                <strong>경고:</strong> 알리바바 콘솔에서 "무료 쿼터만 사용" 옵션을 직접 해제하면, 그 순간부터의 모든 생성에
                등록된 결제 수단으로 실제 요금이 자동 청구돼요. 해제 여부는 반드시 본인이 직접 알리바바 콘솔에서
                결정해주세요 — 이 앱은 결제 정보를 대신 등록하거나 자동으로 해제하지 않아요.
              </p>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {QUOTA_BANNER[errorProvider ?? ''] && (
              <a
                href={QUOTA_BANNER[errorProvider as string].ctaUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-outline btn-full"
                style={{ textDecoration: 'none' }}
              >
                <ExternalLink size={16} /> {QUOTA_BANNER[errorProvider as string].ctaLabel}
              </a>
            )}
            {/* 알리바바(무료 레인)만 "프리미엄으로 전환해 재시도"가 의미 있다.
                유료 제공자에서 막힌 경우엔 같은 레인으로 재시도해도 또 막히므로 모델을 바꾸게 보낸다. */}
            {errorProvider === 'alibaba' ? (
              <button
                className="btn btn-gold btn-full"
                onClick={() => { setSelectedLane('premium'); runPipeline(false) }}
              >
                <Zap size={16} /> 프리미엄 공급자로 전환하고 다시 시도
              </button>
            ) : (
              <button className="btn btn-gold btn-full" onClick={() => navigate('/storyboard')}>
                <Zap size={16} /> 다른 영상 모델 선택하러 가기
              </button>
            )}
          </div>
        </motion.div>
      )}

      {/* 안내 메시지 (일부 씬이 목업으로 대체된 경우) */}
      {noteMessage && phase !== 'error' && (
        <div style={{
          fontSize: '0.75rem', color: 'var(--color-text-muted)', textAlign: 'center',
          padding: '8px 12px', background: 'var(--color-bg-base)', borderRadius: 8,
        }}>
          ℹ️ {noteMessage}
        </div>
      )}

      {/* 전체 진행 바 */}
      <div>
        <div className="flex-between" style={{ marginBottom: 8 }}>
          <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>전체 진행률</span>
          <span style={{ fontSize: '0.875rem', color: 'var(--color-brand-400)', fontWeight: 700 }}>
            {overallProgress}%
          </span>
        </div>
        <div className="progress-bar" style={{ height: 8 }}>
          <motion.div
            className="progress-bar__fill"
            style={{ width: `${overallProgress}%` }}
            animate={{ width: `${overallProgress}%` }}
            transition={{ duration: 0.5 }}
          />
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', marginTop: 6, textAlign: 'right' }}>
          {doneCount}/{total} 씬 완료
        </div>
      </div>

      {/* 씬별 상태 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {orderedScenes.map(scene => (
          <motion.div
            key={scene.id}
            className="card"
            layout
            style={{
              display: 'flex', gap: 12, alignItems: 'center',
              borderColor: (scene.status === 'video_done' || scene.status === 'done') ? 'rgba(16,185,129,0.2)'
                : scene.status === 'failed' ? 'rgba(239,68,68,0.3)'
                : 'var(--color-border)',
            }}
          >
            <SceneStatusIcon status={scene.status} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: '0.8rem', fontWeight: 600, marginBottom: 4,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                color: (scene.status === 'video_done' || scene.status === 'done') ? 'var(--color-success)' : 'var(--color-text-primary)',
              }}>
                씬 {scene.seq} — {scene.descKo}
              </div>
              {scene.status === 'generating_video' && (
                <div style={{ height: 4, background: 'var(--color-bg-base)', borderRadius: 2, overflow: 'hidden' }}>
                  <motion.div
                    style={{ height: '100%', width: '40%', background: 'var(--gradient-brand)', borderRadius: 2 }}
                    animate={{ x: ['-100%', '250%'] }}
                    transition={{ duration: 1.2, repeat: Infinity, ease: 'linear' }}
                  />
                </div>
              )}
              <div style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', marginTop: 2 }}>
                {statusLabel(scene.status)}
              </div>
            </div>
            {(scene.status === 'video_done' || scene.status === 'done') && (
              <CheckCircle size={16} color="var(--color-success)" />
            )}
          </motion.div>
        ))}
      </div>

      {/* FFmpeg 병합 단계 */}
      <AnimatePresence>
        {phase === 'merging' && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            className="card"
            style={{
              display: 'flex', gap: 12, alignItems: 'center',
              borderColor: 'rgba(124,58,255,0.3)',
              background: 'rgba(124,58,255,0.05)',
            }}
          >
            <Loader size={18} className="animate-spin" color="var(--color-brand-400)" />
            <div>
              <div style={{ fontSize: '0.875rem', fontWeight: 600 }}>최종 영상 합치는 중...</div>
              <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                자막 · BGM 믹싱 중
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 완료 → 결과 보기 버튼 */}
      <AnimatePresence>
        {phase === 'done' && (
          <motion.button
            className="btn btn-primary btn-full btn-lg"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            onClick={() => navigate('/result')}
          >
            <ChevronRight size={18} />
            완성 영상 보러 가기
          </motion.button>
        )}
      </AnimatePresence>

    </div>
  )
}
