import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'
import {
  GripVertical, RefreshCw, ChevronDown, ChevronUp,
  AlertCircle, AlertTriangle, CheckCircle, XCircle,
  Zap, Clock, Camera, Play, Plus, Trash2, Sparkles, Search, Download
} from 'lucide-react'
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor,
  useSensor, useSensors, type DragEndEvent
} from '@dnd-kit/core'
import {
  arrayMove, SortableContext, sortableKeyboardCoordinates,
  useSortable, verticalListSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useProjectStore } from '../stores/projectStore'
import { useUserStore, type AccessTier, LoginRequiredError } from '../stores/userStore'
import { KeyVault, isAlibabaBlocked } from '../stores/keysStore'
import type { Scene, Lane, GateLevel, GateCheckItem, Person, VoiceStyle, ProviderKey } from '../types'
import { runGate0, runGate1 } from '../utils/qualityGates'
import { clsx } from 'clsx'
import { generateSceneKeyframe, resolvePremiumProvider } from '../services/sceneRenderer'
import {
  ensureRenderAuthorization, InsufficientPointsError, FREE_DAILY_MOVING_PHOTO_LIMIT,
  ensureKeyframeDownloadAuthorization, FREE_DAILY_KEYFRAME_DOWNLOAD_LIMIT, KEYFRAME_DOWNLOAD_PRICE,
} from '../services/walletService'
import { useChargeModal } from '../stores/chargeModalStore'
import { checkPoseAnomaly, warmupPoseLandmarker } from '../extraction/poseDetector'
import { GeminiAdapter } from '../services/aiAdapters'

// 씬 편집(설명·대사·길이·씬 추가) 권한 — 로그인만 하면 전면 개방 ("무료 영구 + 포인트" 모델에서
// 편집은 무료 기능이고, 과금은 제작 시작 시점의 무료 슬롯/포인트 차감이 담당한다)
const canEditStoryboard = (tier: AccessTier) => tier !== 'guest'

// 스타일 강도 퀵버튼 — 클릭 시 프롬프트 draft에 문구만 덧붙이고, 기존 "적용" 버튼으로 재생성한다
const STYLE_INTENSITY_PRESETS = [
  { label: '은은하게', phrase: 'subtle, understated stylization' },
  { label: '강하게', phrase: 'strong, dramatic, highly stylized' },
  { label: '매우 강하게', phrase: 'extreme, hyper-stylized, exaggerated aesthetic' },
]

// ── 목업 씬 데이터 ────────────────────────────────────────────
const MOCK_SCENES: Scene[] = [
  {
    id: 's1', seq: 1, duration: 4, status: 'keyframe_done', regenCount: 0,
    descKo: '노을 지는 해변, 두 사람이 마주 보고 걷는다',
    keyframePromptEn: 'cinematic photo of couple walking face to face on a beach at golden hour, warm rim light',
    motionPromptEn: 'slow dolly-in, hair gently moving in the wind, subtle smiles',
    dialogueKo: '그때 우리, 기억나?',
    subjectRefs: ['person_1', 'person_2'],
    gateResults: [
      { gate: 1, sceneId: 's1', verdict: 'pass', checks: [
        { code: 'G1-02', level: 'pass', messageKo: '주인공이 모든 장면에 포함됐어요' }
      ]},
      { gate: 2, sceneId: 's1', verdict: 'pass', checks: [
        { code: 'G2-01', level: 'pass', messageKo: '얼굴 감지 완료' }
      ]},
    ],
  },
  {
    id: 's2', seq: 2, duration: 3, status: 'keyframe_done', regenCount: 1,
    descKo: '카페 창가, 두 사람이 커피잔을 들고 눈을 마주친다',
    keyframePromptEn: 'cinematic photo of couple holding coffee cups at window seat, warm afternoon light',
    motionPromptEn: 'gentle push-in, steam from coffee, eye contact, soft bokeh background',
    dialogueKo: '항상 여기서 만나자.',
    subjectRefs: ['person_1', 'person_2'],
    gateResults: [
      { gate: 1, sceneId: 's2', verdict: 'pass', checks: [
        { code: 'G1-09', level: 'warn', messageKo: '음료 들기 동작은 손 왜곡이 생길 수 있어요', suggestionKo: '커피잔 대신 창밖을 바라보는 구도로 바꿔보시겠어요?' }
      ]},
    ],
  },
  {
    id: 's3', seq: 3, duration: 4, status: 'pending', regenCount: 0,
    descKo: '빗속, 우산을 함께 쓰고 달리는 두 사람',
    keyframePromptEn: 'cinematic photo of couple sharing umbrella running in rain, dramatic lighting, puddles',
    motionPromptEn: 'tracking shot following couple, rain drops visible, umbrella tilting, laughter',
    dialogueKo: '이 비가 그치지 않으면 좋겠어.',
    subjectRefs: ['person_1', 'person_2'],
    gateResults: [],
  },
]

// 씬별 "이 씬만 톤 다르게" 음성 override 옵션 (미지정 항목은 화자 인물의 기본값을 그대로 쓴다)
const VOICE_GENDER_OPTIONS: { id: 'male' | 'female'; label: string }[] = [
  { id: 'female', label: '여성' },
  { id: 'male',   label: '남성' },
]
const VOICE_AGE_OPTIONS: { id: NonNullable<Person['ageBand']>; label: string }[] = [
  { id: 'child',  label: '아동' },
  { id: 'teen',   label: '청소년' },
  { id: 'adult',  label: '성인' },
  { id: 'senior', label: '중장년' },
]
const VOICE_STYLE_OPTIONS: { id: VoiceStyle; label: string }[] = [
  { id: 'calm',       label: '차분한' },
  { id: 'bright',     label: '밝고 발랄한' },
  { id: 'husky_deep', label: '허스키·중저음' },
  { id: 'warm_soft',  label: '부드러운' },
]

// ── 게이트 뱃지 ───────────────────────────────────────────────
function GateBadge({ level }: { level: GateLevel | string }) {
  const config: Record<string, { icon: React.ReactNode; className: string; label: string }> = {
    pass:    { icon: <CheckCircle size={11} />,  className: 'gate-pass',    label: '통과' },
    warn:    { icon: <AlertTriangle size={11} />, className: 'gate-warn',   label: '경고' },
    fail:    { icon: <XCircle size={11} />,       className: 'gate-fail',   label: '수정 필요' },
    blocked: { icon: <AlertCircle size={11} />,   className: 'gate-blocked',label: '차단' },
  }
  const c = config[level] ?? config.pass
  return (
    <div className={clsx('gate-badge', c.className)}>
      {c.icon} {c.label}
    </div>
  )
}

// ── 씬 전체 게이트 요약 ───────────────────────────────────────
function sceneOverallGate(scene: Scene): GateLevel {
  if (!scene.gateResults?.length) return 'pass'
  const allChecks = scene.gateResults.flatMap(r => r.checks)
  if (allChecks.some(c => c.level === 'blocked')) return 'blocked'
  if (allChecks.some(c => c.level === 'fail')) return 'fail'
  if (allChecks.some(c => c.level === 'warn')) return 'warn'
  return 'pass'
}

// ── 이미지 생성 진행 바 ───────────────────────────────────────
// 실제 진행률을 API가 알려주지 않아서, 경과 시간을 예상 소요시간(체감치) 대비 비율로 근사한다.
// 예상보다 오래 걸려도 92%에서 멈춰 대기하다가, 실제 완료되는 순간 100%로 채워지고 카드가 완료 상태로 바뀐다.
const GENERATION_ESTIMATED_SEC = 12

function GenerationTimer({ startedAt }: { startedAt: number }) {
  const [elapsed, setElapsed] = useState(() => Math.floor((Date.now() - startedAt) / 1000))
  useEffect(() => {
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000)
    return () => clearInterval(id)
  }, [startedAt])

  const progress = Math.min(92, Math.round((elapsed / GENERATION_ESTIMATED_SEC) * 100))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width: '100%' }}>
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3, fontSize: 10, color: 'var(--color-brand-400)' }}>
        <Clock size={10} className="animate-spin" /> 이미지 생성 중 · {elapsed}초
      </span>
      <div style={{ width: '100%', maxWidth: 160, height: 4, borderRadius: 2, background: 'var(--color-bg-base)', overflow: 'hidden' }}>
        <motion.div
          style={{ height: '100%', borderRadius: 2, background: 'var(--gradient-brand)' }}
          animate={{ width: `${progress}%` }}
          transition={{ ease: 'linear', duration: 0.3 }}
        />
      </div>
    </div>
  )
}

// ── 드래그 가능한 씬 카드 ─────────────────────────────────────
function SortableSceneCard({
  scene, index, genState, onUpdate, onRegen, onApplyPrompt, onDelete, onPreviewClick, onPrecisionCheck, onDownload, tier
}: {
  scene: Scene
  index: number
  genState?: { startedAt?: number; error?: string; errorKind?: 'download'; note?: string }
  onUpdate: (id: string, patch: Partial<Scene>) => void
  onRegen: (id: string) => void
  onApplyPrompt: (id: string, newPrompt: string) => void
  onDelete: (id: string) => void
  onPreviewClick: (url: string) => void
  onPrecisionCheck: (id: string) => void
  onDownload: (id: string) => void
  tier: AccessTier
}) {
  // 비로그인만 씬 설명/대사/길이 편집이 막힌다 — 로그인하면 AI 프롬프트 고급 수정까지 전면 개방
  const canEditScene = canEditStoryboard(tier)
  const canEditPrompt = tier !== 'guest'

  const [expanded, setExpanded] = useState(false)
  const [showGates, setShowGates] = useState(false)
  const [voiceOverrideOpen, setVoiceOverrideOpen] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)
  const [promptDraft, setPromptDraft] = useState(scene.keyframePromptEn)
  useEffect(() => { setPromptDraft(scene.keyframePromptEn) }, [scene.keyframePromptEn])
  const [motionDraft, setMotionDraft] = useState(scene.motionPromptEn)
  useEffect(() => { setMotionDraft(scene.motionPromptEn) }, [scene.motionPromptEn])
  const overall = sceneOverallGate(scene)

  const { photos, persons, currentProject } = useProjectStore()

  // 1. 씬에 매핑된 인물 컷 또는 첫 번째 원본 이미지 찾기
  let previewImage = scene.keyframeUrl
  if (!previewImage && scene.subjectRefs && scene.subjectRefs.length > 0) {
    const refId = scene.subjectRefs[0]
    const person = persons.find(p => p.id === refId || p.label === refId)
    if (person && person.cropUrl) {
      previewImage = person.cropUrl
    }
  }
  if (!previewImage && photos && photos.length > 0) {
    previewImage = photos[0].previewUrl
  }

  // 2. 선택된 비주얼 컨셉 스타일에 따른 필터 정의
  const styleId = currentProject?.styleId || 'cinematic'
  const getStyleOverlay = (style: string) => {
    switch (style) {
      case 'bw':
        return {
          filter: 'grayscale(100%) contrast(125%) brightness(95%)',
          overlayBackground: 'linear-gradient(to top, rgba(0,0,0,0.9), rgba(0,0,0,0.1))',
          vhsLine: false
        }
      case 'cyberpunk':
        return {
          filter: 'saturate(160%) contrast(110%) hue-rotate(320deg)',
          overlayBackground: 'linear-gradient(to top, rgba(15,0,30,0.95), rgba(124,58,255,0.25) 50%, rgba(255,0,128,0.15))',
          vhsLine: false
        }
      case 'retro_vhs':
        return {
          filter: 'sepia(25%) saturate(130%) contrast(90%) brightness(105%) blur(0.3px)',
          overlayBackground: 'linear-gradient(to top, rgba(20,10,0,0.9), rgba(124,58,255,0.1))',
          vhsLine: true
        }
      case 'anime_jp':
        return {
          filter: 'saturate(150%) contrast(105%) brightness(110%) sepia(5%)',
          overlayBackground: 'linear-gradient(to top, rgba(0,20,40,0.85), rgba(245,158,11,0.05))',
          vhsLine: false
        }
      case 'toon_3d':
        return {
          filter: 'saturate(170%) contrast(115%) brightness(100%) blur(0.2px)',
          overlayBackground: 'linear-gradient(to top, rgba(10,10,20,0.9), rgba(255,255,255,0.05))',
          vhsLine: false
        }
      case 'watercolor':
        return {
          filter: 'saturate(85%) contrast(90%) brightness(108%) blur(0.6px)',
          overlayBackground: 'linear-gradient(to top, rgba(40,40,40,0.8), rgba(255,255,255,0.1))',
          vhsLine: false
        }
      case 'film_grain':
        return {
          filter: 'brightness(92%) contrast(95%) sepia(8%)',
          overlayBackground: 'linear-gradient(to top, rgba(0,0,0,0.85), rgba(10,5,0,0.2))',
          vhsLine: false
        }
      case 'hifashion':
        return {
          filter: 'contrast(135%) saturate(85%) brightness(95%)',
          overlayBackground: 'linear-gradient(to top, rgba(0,0,0,0.9), rgba(0,0,0,0.2))',
          vhsLine: false
        }
      case 'cinematic':
      default:
        return {
          filter: 'contrast(115%) saturate(110%) brightness(90%) hue-rotate(350deg)',
          overlayBackground: 'linear-gradient(to top, rgba(0,5,15,0.9), rgba(0,128,128,0.05))',
          vhsLine: false
        }
    }
  }

  const effect = getStyleOverlay(styleId)

  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: scene.id })
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 10 : 1,
  }

  const allChecks = (scene.gateResults ?? []).flatMap(r => r.checks)
  const warnings = allChecks.filter(c => c.level === 'warn')
  const fails = allChecks.filter(c => c.level === 'fail' || c.level === 'blocked')

  return (
    <div ref={setNodeRef} style={style}>
      <motion.div
        layout
        className="scene-card"
        style={{
          borderColor: overall === 'fail' || overall === 'blocked'
            ? 'rgba(239,68,68,0.4)'
            : overall === 'warn'
            ? 'rgba(245,158,11,0.3)'
            : 'var(--color-border)',
        }}
      >
        {/* 헤더 */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '12px 12px 10px', borderBottom: '1px solid var(--color-border)',
        }}>
          {/* 드래그 핸들 */}
          <div {...attributes} {...listeners} style={{ cursor: 'grab', color: 'var(--color-text-muted)', flexShrink: 0 }}>
            <GripVertical size={16} />
          </div>

          {/* 키프레임 썸네일 */}
          <div 
            onClick={() => previewImage && onPreviewClick(previewImage)}
            style={{
              width: 40, height: 56, borderRadius: 6, overflow: 'hidden', flexShrink: 0,
              background: 'var(--color-bg-base)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              position: 'relative',
              border: '1px solid var(--color-border)',
              cursor: previewImage ? 'zoom-in' : 'default'
            }}
          >
            {previewImage ? (
              <img
                src={previewImage}
                alt=""
                style={{
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                  filter: effect.filter
                }}
              />
            ) : (
              <Camera size={16} color="var(--color-text-muted)" opacity={0.5} />
            )}
            {/* 미니 스타일 오버레이 그라데이션 */}
            {previewImage && (
              <div style={{
                position: 'absolute',
                inset: 0,
                background: effect.overlayBackground,
                opacity: 0.4,
                pointerEvents: 'none'
              }} />
            )}
          </div>

          {/* 씬 정보 */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
              <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--color-brand-400)' }}>
                씬 {scene.seq}
              </span>
              <span className="badge badge-muted" style={{ fontSize: 10, padding: '2px 7px' }}>
                {scene.duration}초
              </span>
              <GateBadge level={overall} />
            </div>
            {scene.status === 'generating_keyframe' && genState?.startedAt ? (
              <GenerationTimer startedAt={genState.startedAt} />
            ) : (
              <p style={{
                fontSize: '0.8rem', color: 'var(--color-text-secondary)', lineHeight: 1.4,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {scene.descKo}
              </p>
            )}
          </div>

          {/* 액션 버튼들 */}
          <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
            <button
              className="btn btn-ghost btn-icon btn-sm"
              onClick={() => onRegen(scene.id)}
              title="키프레임 재생성"
              disabled={scene.status === 'generating_keyframe'}
              style={{ width: 32, height: 32 }}
            >
              <RefreshCw size={14} className={scene.status === 'generating_keyframe' ? 'animate-spin' : undefined} />
            </button>
            {tier !== 'guest' && scene.keyframeUrl && (
              <button
                className="btn btn-ghost btn-icon btn-sm"
                onClick={() => onPrecisionCheck(scene.id)}
                title="정밀 검수 — Gemini Vision으로 해부학적 이상 여부 확인 (내 Gemini 키 사용)"
                disabled={scene.status === 'generating_keyframe'}
                style={{ width: 32, height: 32 }}
              >
                <Search size={14} color="var(--color-gold-400)" />
              </button>
            )}
            {scene.keyframeUrl && (
              <button
                className="btn btn-ghost btn-icon btn-sm"
                onClick={() => onDownload(scene.id)}
                title={`이미지 다운로드 (하루 ${FREE_DAILY_KEYFRAME_DOWNLOAD_LIMIT}장 무료, 초과 시 P ${KEYFRAME_DOWNLOAD_PRICE})`}
                disabled={scene.status === 'generating_keyframe'}
                style={{ width: 32, height: 32 }}
              >
                <Download size={14} />
              </button>
            )}
            <button
              className="btn btn-ghost btn-icon btn-sm"
              onClick={() => setExpanded(!expanded)}
              style={{ width: 32, height: 32 }}
            >
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          </div>
        </div>

        {/* 이미지 생성/다운로드 실패 알림 */}
        {genState?.error && (
          <div style={{
            display: 'flex', alignItems: 'flex-start', gap: 8,
            margin: '0 12px 10px', padding: '10px 12px', borderRadius: 8,
            background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)',
          }}>
            <AlertCircle size={15} color="var(--color-error)" style={{ flexShrink: 0, marginTop: 1 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--color-error)', marginBottom: 2 }}>
                {genState.errorKind === 'download' ? '다운로드 실패' : '이미지 생성 실패'}
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', lineHeight: 1.4, wordBreak: 'break-word' }}>
                {genState.error}
              </div>
            </div>
            <button
              className="btn btn-outline btn-sm"
              onClick={() => genState.errorKind === 'download' ? onDownload(scene.id) : onRegen(scene.id)}
              style={{ flexShrink: 0, fontSize: '0.72rem', padding: '4px 10px' }}
            >
              다시 시도
            </button>
          </div>
        )}

        {/* 인물 일관성 저하 알림 (생성은 성공했지만 참조 이미지 없이 텍스트만으로 그려진 경우) */}
        {!genState?.error && genState?.note && (
          <div style={{
            display: 'flex', alignItems: 'flex-start', gap: 8,
            margin: '0 12px 10px', padding: '10px 12px', borderRadius: 8,
            background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.3)',
          }}>
            <AlertCircle size={15} color="var(--color-warning)" style={{ flexShrink: 0, marginTop: 1 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--color-warning)', marginBottom: 2 }}>
                인물 일관성 저하
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)', lineHeight: 1.4, wordBreak: 'break-word' }}>
                {genState.note}
              </div>
            </div>
            <button
              className="btn btn-outline btn-sm"
              onClick={() => onRegen(scene.id)}
              style={{ flexShrink: 0, fontSize: '0.72rem', padding: '4px 10px' }}
            >
              재시도
            </button>
          </div>
        )}

        {/* 확장된 편집 영역 */}
        <AnimatePresence>
          {expanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              style={{ overflow: 'hidden' }}
            >
              <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 12 }}>
                
                {/* 16:9 시작 이미지 시네마틱 프리뷰 */}
                <div 
                  onClick={() => previewImage && onPreviewClick(previewImage)}
                  style={{
                    width: '100%',
                    aspectRatio: '16/9',
                    borderRadius: 10,
                    overflow: 'hidden',
                    position: 'relative',
                    background: '#0B071E',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    boxShadow: '0 6px 20px rgba(0, 0, 0, 0.5), inset 0 0 20px rgba(0, 0, 0, 0.9)',
                    cursor: previewImage ? 'zoom-in' : 'default'
                  }}
                >
                  {previewImage ? (
                    <img
                      src={previewImage}
                      alt="장면 시작 이미지 프리뷰"
                      style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'cover',
                        filter: effect.filter,
                      }}
                    />
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--color-text-muted)' }}>
                      <Camera size={24} style={{ marginBottom: 6, opacity: 0.5 }} />
                      <span style={{ fontSize: '0.75rem' }}>등록된 원본 이미지 없음</span>
                    </div>
                  )}

                  {/* 스타일 오버레이 그라데이션 */}
                  <div style={{
                    position: 'absolute',
                    inset: 0,
                    background: effect.overlayBackground,
                    pointerEvents: 'none'
                  }} />

                  {/* VHS 레트로 스캔라인 효과 (옵션) */}
                  {effect.vhsLine && (
                    <div style={{
                      position: 'absolute',
                      inset: 0,
                      background: 'linear-gradient(rgba(18,16,16,0) 50%, rgba(0,0,0,0.12) 50%), linear-gradient(90deg, rgba(255,0,0,0.03), rgba(0,255,0,0.01), rgba(0,0,255,0.03))',
                      backgroundSize: '100% 4px, 6px 100%',
                      pointerEvents: 'none'
                    }} />
                  )}

                  {/* 좌측 하단 영화 자막 번인 오버레이 */}
                  {scene.dialogueKo && (
                    <div style={{
                      position: 'absolute',
                      bottom: 12,
                      left: '50%',
                      transform: 'translateX(-50%)',
                      background: 'rgba(0,0,0,0.7)',
                      padding: '4px 14px',
                      borderRadius: 4,
                      border: '1px solid rgba(255,255,255,0.15)',
                      color: '#FFFDF0', // 자막 특유의 연한 노란빛 감도는 아이보리색
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      textAlign: 'center',
                      whiteSpace: 'nowrap',
                      maxWidth: '90%',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      boxShadow: '0 2px 8px rgba(0,0,0,0.5)',
                      letterSpacing: '0.2px'
                    }}>
                      "{scene.dialogueKo}"
                    </div>
                  )}

                  {/* 우측 상단 장르 뱃지 */}
                  <div style={{
                    position: 'absolute',
                    top: 10,
                    right: 10,
                    background: 'rgba(124, 58, 255, 0.85)',
                    backdropFilter: 'blur(4px)',
                    color: '#fff',
                    padding: '3px 8px',
                    borderRadius: 6,
                    fontSize: '0.65rem',
                    fontWeight: 700,
                    border: '1px solid rgba(255,255,255,0.1)'
                  }}>
                    {styleId.toUpperCase()} STYLE
                  </div>
                </div>

                {!canEditScene && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 6, marginBottom: 10,
                    padding: '8px 12px', borderRadius: 8,
                    background: 'var(--color-bg-base)', fontSize: '0.73rem', color: 'var(--color-text-muted)',
                  }}>
                    🔒 로그인하면 설명·대사·길이를 직접 수정할 수 있어요
                  </div>
                )}

                {/* 장면 설명 */}
                <div className="input-group">
                  <label className="input-label">장면 설명</label>
                  <textarea
                    className="input"
                    value={scene.descKo}
                    onChange={e => onUpdate(scene.id, { descKo: e.target.value })}
                    rows={2}
                    style={{ resize: 'none' }}
                    placeholder="장면을 한국어로 설명해주세요"
                    disabled={!canEditScene}
                  />
                </div>

                {/* 대사 */}
                <div className="input-group">
                  {/* 광고 나레이션은 영상 길이(15·30·60초)에 맞춰 분배되므로 씬마다 필요한 분량이
                      다르다 — 글자수를 고정 제한하면 대본이 잘려 메시지가 끊긴다 */}
                  <label className="input-label">대사 <span style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>(씬 길이에 맞춰 자유롭게)</span></label>
                  <textarea
                    className="input"
                    value={scene.dialogueKo ?? ''}
                    onChange={e => onUpdate(scene.id, { dialogueKo: e.target.value })}
                    rows={2}
                    style={{ resize: 'vertical', minHeight: 44 }}
                    placeholder="대사를 입력하세요 (없으면 비워두세요)"
                    disabled={!canEditScene}
                  />
                </div>

                {/* 대사 음성: 화자 지정(2인 이상 씬) + 이 씬만 톤 다르게 override */}
                {scene.dialogueKo?.trim() && (
                  <div className="input-group">
                    {scene.subjectRefs.length > 1 && (
                      <>
                        <label className="input-label">화자</label>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
                          {scene.subjectRefs.map(ref => {
                            const refPerson = persons.find(pp => pp.id === ref || pp.label === ref)
                            const isSelected = (scene.speakerId ?? scene.subjectRefs[0]) === ref
                            return (
                              <button
                                key={ref}
                                className={clsx('chip', isSelected && 'selected')}
                                onClick={() => onUpdate(scene.id, { speakerId: ref })}
                                style={{ fontSize: '0.75rem' }}
                              >
                                {refPerson?.label ?? ref}
                              </button>
                            )
                          })}
                        </div>
                      </>
                    )}

                    <button
                      style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                      onClick={() => setVoiceOverrideOpen(!voiceOverrideOpen)}
                    >
                      이 씬만 톤 다르게 {voiceOverrideOpen ? '▲' : '▼'}
                    </button>
                    {voiceOverrideOpen && (
                      <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {VOICE_GENDER_OPTIONS.map(g => (
                            <button
                              key={g.id}
                              className={clsx('chip', scene.voiceOverride?.gender === g.id && 'selected')}
                              onClick={() => onUpdate(scene.id, {
                                voiceOverride: { ...scene.voiceOverride, gender: scene.voiceOverride?.gender === g.id ? undefined : g.id }
                              })}
                              style={{ fontSize: '0.7rem', padding: '4px 9px' }}
                            >
                              {g.label}
                            </button>
                          ))}
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {VOICE_AGE_OPTIONS.map(a => (
                            <button
                              key={a.id}
                              className={clsx('chip', scene.voiceOverride?.ageBand === a.id && 'selected')}
                              onClick={() => onUpdate(scene.id, {
                                voiceOverride: { ...scene.voiceOverride, ageBand: scene.voiceOverride?.ageBand === a.id ? undefined : a.id }
                              })}
                              style={{ fontSize: '0.7rem', padding: '4px 9px' }}
                            >
                              {a.label}
                            </button>
                          ))}
                        </div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {VOICE_STYLE_OPTIONS.map(v => (
                            <button
                              key={v.id}
                              className={clsx('chip', scene.voiceOverride?.voiceStyle === v.id && 'selected')}
                              onClick={() => onUpdate(scene.id, {
                                voiceOverride: { ...scene.voiceOverride, voiceStyle: scene.voiceOverride?.voiceStyle === v.id ? undefined : v.id }
                              })}
                              style={{ fontSize: '0.7rem', padding: '4px 9px' }}
                            >
                              {v.label}
                            </button>
                          ))}
                        </div>
                        {scene.voiceOverride && (
                          <button
                            className="btn btn-ghost btn-sm"
                            style={{ alignSelf: 'flex-start', fontSize: '0.7rem' }}
                            onClick={() => onUpdate(scene.id, { voiceOverride: undefined })}
                          >
                            초기화 (인물 기본 목소리 사용)
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* 길이 슬라이더 — 일반/프로는 최대 5초까지 직접 조정 가능(자동 생성은 2~4초라
                    최소값도 2로 열어둬서, 아직 손 안 댄 씬의 슬라이더 위치와 라벨이 어긋나지 않게 한다) */}
                <div className="input-group">
                  <label className="input-label">길이: {scene.duration}초</label>
                  <input
                    type="range" min={2} max={5} step={1}
                    value={scene.duration}
                    onChange={e => onUpdate(scene.id, { duration: Number(e.target.value) })}
                    style={{ width: '100%', accentColor: 'var(--color-brand-500)' }}
                    disabled={!canEditScene}
                  />
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--color-text-muted)' }}>
                    <span>2초</span><span>3초</span><span>4초</span><span>5초</span>
                  </div>
                </div>

                {/* AI 프롬프트 (고급) — 프로 전용 */}
                <div className="input-group">
                  <button
                    style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                    onClick={() => setPromptOpen(!promptOpen)}
                  >
                    AI 프롬프트 (고급){!canEditPrompt && ' 🔒'} {promptOpen ? '▲' : '▼'}
                  </button>
                  {promptOpen && !canEditPrompt && (
                    <div style={{ marginTop: 8, position: 'relative', borderRadius: 8, overflow: 'hidden' }}>
                      <p style={{
                        fontSize: '0.8rem', color: 'var(--color-text-secondary)', lineHeight: 1.5,
                        filter: 'blur(4px)', userSelect: 'none', margin: 0, padding: 12,
                        background: 'var(--color-bg-base)',
                      }}>
                        {scene.keyframePromptEn}
                      </p>
                      <div style={{
                        position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                        alignItems: 'center', justifyContent: 'center', gap: 6,
                        background: 'rgba(0,0,0,0.45)',
                      }}>
                        <span className="badge badge-gold">🔒</span>
                        <span style={{ fontSize: '0.7rem', color: '#fff', textAlign: 'center', padding: '0 12px' }}>
                          로그인하면 이 프롬프트(이미지·모션)를 직접 고치고 즉시 재생성할 수 있어요
                        </span>
                      </div>
                    </div>
                  )}
                  {promptOpen && canEditPrompt && (
                    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                      <p style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', margin: 0 }}>
                        AI 이미지 생성에 쓰이는 영문 프롬프트예요. 자유롭게 수정하고 아래 버튼을 누르면 이 씬 이미지가 새로 생성돼요.
                      </p>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                        <span style={{ fontSize: '0.68rem', color: 'var(--color-text-muted)' }}>스타일 강도:</span>
                        {STYLE_INTENSITY_PRESETS.map(p => (
                          <button
                            key={p.label}
                            className="btn btn-ghost btn-sm"
                            style={{ fontSize: '0.68rem', padding: '3px 8px' }}
                            onClick={() => setPromptDraft(prev => `${prev}, ${p.phrase}`)}
                          >
                            {p.label}
                          </button>
                        ))}
                      </div>
                      <textarea
                        className="input"
                        rows={4}
                        style={{ resize: 'vertical', fontSize: '0.8rem' }}
                        value={promptDraft}
                        onChange={e => setPromptDraft(e.target.value)}
                        onBlur={() => {
                          if (promptDraft.trim() && promptDraft !== scene.keyframePromptEn) {
                            onUpdate(scene.id, { keyframePromptEn: promptDraft })
                          }
                        }}
                        placeholder="예: cinematic photo of couple walking on a beach at golden hour"
                      />
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <button
                          className="btn btn-primary btn-sm"
                          disabled={scene.status === 'generating_keyframe' || !promptDraft.trim()}
                          onClick={() => onApplyPrompt(scene.id, promptDraft)}
                        >
                          적용 (이미지 재생성)
                        </button>
                        {scene.originalKeyframePromptEn && scene.originalKeyframePromptEn !== promptDraft && (
                          <button
                            className="btn btn-ghost btn-sm"
                            style={{ fontSize: '0.7rem' }}
                            onClick={() => onUpdate(scene.id, { keyframePromptEn: scene.originalKeyframePromptEn! })}
                          >
                            원본으로 되돌리기
                          </button>
                        )}
                      </div>
                      <p style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', margin: '10px 0 0' }}>
                        영상 생성에 쓰이는 카메라 모션 프롬프트예요(카메라 움직임·동작 지시). 수정하면 다음 영상 생성부터 반영돼요.
                      </p>
                      <textarea
                        className="input"
                        rows={2}
                        style={{ resize: 'vertical', fontSize: '0.8rem' }}
                        value={motionDraft}
                        onChange={e => setMotionDraft(e.target.value)}
                        onBlur={() => {
                          if (motionDraft.trim() && motionDraft !== scene.motionPromptEn) {
                            onUpdate(scene.id, { motionPromptEn: motionDraft })
                          }
                        }}
                        placeholder="예: slow dolly-in, gentle pan left"
                      />
                    </div>
                  )}
                </div>

                {/* 게이트 결과 */}
                {allChecks.length > 0 && (
                  <div>
                    <button
                      style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                      onClick={() => setShowGates(!showGates)}
                    >
                      품질 검사 결과 {showGates ? '▲' : '▼'}
                    </button>
                    {showGates && (
                      <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                        {allChecks.map((check, i) => (
                          <div key={i} style={{
                            padding: '8px 10px', borderRadius: 8,
                            background: 'var(--color-bg-base)',
                            border: `1px solid ${check.level === 'warn' ? 'rgba(245,158,11,0.2)' : check.level === 'fail' ? 'rgba(239,68,68,0.2)' : 'var(--color-border)'}`,
                            fontSize: '0.75rem',
                          }}>
                            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: check.suggestionKo ? 4 : 0 }}>
                              <GateBadge level={check.level} />
                              <span style={{ color: 'var(--color-text-secondary)' }}>{check.messageKo}</span>
                            </div>
                            {check.suggestionKo && (
                              <div style={{ color: 'var(--color-text-muted)', paddingLeft: 4, lineHeight: 1.4 }}>
                                💡 {check.suggestionKo}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* 씬 삭제 */}
                {canEditScene && (
                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                    <button className="btn btn-danger btn-sm" onClick={() => onDelete(scene.id)}>
                      <Trash2 size={13} /> 씬 삭제
                    </button>
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}

// ── 레인 선택 바 ──────────────────────────────────────────────
function LaneBar({
  selectedLane, onSelect, onStart, hasBlockedScenes, isGeneratingImages, hasMissingImages, startError
}: {
  selectedLane: Lane
  onSelect: (l: Lane) => void
  onStart: () => void
  hasBlockedScenes: boolean
  isGeneratingImages: boolean
  hasMissingImages: boolean
  startError: { message: string; ctaLabel: string; ctaPath: string } | null
}) {
  const navigate = useNavigate()
  const { freeAiProvider, setFreeAiProvider, premiumProvider, setPremiumProvider } = useProjectStore()

  // 고퀄 레인 제공자 목록 — 포인트 단가는 walletService의 premiumPerScene과 같은 값으로 유지할 것
  const PREMIUM_PROVIDERS: { id: ProviderKey; name: string; coins: number; desc: string }[] = [
    { id: 'veo',      name: 'Veo 3.1',      coins: 1500, desc: '대사·립싱크' },
    { id: 'kling',    name: 'Kling 3.0',    coins: 1200, desc: '인물 클로즈업' },
    { id: 'hailuo',   name: 'Hailuo 2.3',   coins: 800,  desc: '동작·스타일' },
    { id: 'seedance', name: 'Seedance 2.0', coins: 500,  desc: '일반 씬' },
  ]

  // 어떤 제공자 키가 이 기기에 실제로 저장돼 있는지 — 계정 등록 기록이 아니라 KeyVault를 직접 확인한다
  const [availableKeys, setAvailableKeys] = useState<Record<string, boolean>>({})
  useEffect(() => {
    if (selectedLane !== 'premium') return
    let cancelled = false
    Promise.all(PREMIUM_PROVIDERS.map(async p => [p.id, await KeyVault.hasKey(p.id)] as const))
      .then(entries => { if (!cancelled) setAvailableKeys(Object.fromEntries(entries)) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedLane])

  const LANES: { id: Lane; name: string; desc: string; badge?: string; isFree: boolean }[] = [
    { id: 'moving_photo', name: '무빙포토', desc: `하루 ${FREE_DAILY_MOVING_PHOTO_LIMIT}개 무료`, badge: 'FREE', isFree: true },
    { id: 'free_ai',      name: 'AI 영상',  desc: '무료~P 1,000 · 대기열', badge: 'AI', isFree: false },
    { id: 'premium',      name: '고퀄 영상', desc: '씬당 포인트 · 즉시', badge: 'POINT', isFree: false },
  ]

  return (
    <div className="lane-bar">
      <h3 style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 8 }}>
        제작 방식 선택
      </h3>
      <div className="lane-options">
        {LANES.map(lane => (
          <motion.button
            key={lane.id}
            className={clsx(
              'lane-option',
              selectedLane === lane.id && 'selected',
              !lane.isFree && 'gold',
            )}
            onClick={() => onSelect(lane.id)}
            whileTap={{ scale: 0.96 }}
          >
            <span className={clsx('badge', lane.isFree ? 'badge-brand' : 'badge-gold')} style={{ marginBottom: 2 }}>
              {lane.badge}
            </span>
            <span className="lane-option__name">{lane.name}</span>
            <span className="lane-option__desc">{lane.desc}</span>
          </motion.button>
        ))}
      </div>

      {selectedLane === 'moving_photo' && (
        <div style={{ fontSize: '0.73rem', color: 'var(--color-text-muted)', textAlign: 'center', marginBottom: 8 }}>
          매일 {FREE_DAILY_MOVING_PHOTO_LIMIT}개 무료(워터마크 포함) · 초과분은 P 500(워터마크 없음·HD)
        </div>
      )}

      {selectedLane === 'premium' && (
        <div style={{ marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)' }}>
              영상 모델 선택 · 본인 API 키 필요
            </span>
            <button className="btn btn-ghost btn-sm" onClick={() => navigate('/keys')} style={{ fontSize: '0.7rem' }}>
              키 설정 →
            </button>
          </div>

          {/* 제공자 4종 — 키가 등록되지 않은 것은 선택 불가 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 6 }}>
            {PREMIUM_PROVIDERS.map(p => {
              const hasKey = availableKeys[p.id] === true
              return (
                <button
                  key={p.id}
                  className={clsx('chip', premiumProvider === p.id && 'selected')}
                  disabled={!hasKey}
                  onClick={() => setPremiumProvider(p.id)}
                  title={hasKey ? `${p.name} · 씬당 P ${p.coins.toLocaleString()}` : '이 제공자의 API 키가 등록되지 않았어요'}
                  style={{
                    justifyContent: 'center', flexDirection: 'column', gap: 2, padding: '8px 6px',
                    opacity: hasKey ? 1 : 0.4, cursor: hasKey ? 'pointer' : 'not-allowed',
                  }}
                >
                  <span style={{ fontWeight: 700, fontSize: '0.76rem' }}>{p.name}</span>
                  <span style={{ fontSize: '0.64rem', color: 'var(--color-text-muted)' }}>
                    {hasKey ? `${p.desc} · P ${p.coins.toLocaleString()}` : '키 없음'}
                  </span>
                </button>
              )
            })}
          </div>

          <div style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', textAlign: 'center' }}>
            {premiumProvider
              ? `선택한 모델로 모든 씬을 생성해요 · 씬당 P ${PREMIUM_PROVIDERS.find(p => p.id === premiumProvider)?.coins.toLocaleString()}`
              : '사용할 영상 모델을 선택해주세요'}
          </div>
        </div>
      )}

      {selectedLane === 'free_ai' && (
        <div style={{ marginBottom: 8 }}>
          {/* 품질 선택 — LTX(내 Kaggle GPU, 무료·느림·워터마크) vs 알리바바(포인트·빠름·워터마크 없음) */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
            <button
              className={clsx('chip', freeAiProvider === 'kaggle_ltx' && 'selected')}
              onClick={() => setFreeAiProvider('kaggle_ltx')}
              style={{ flex: 1, justifyContent: 'center', flexDirection: 'column', gap: 2, padding: '8px 6px' }}
            >
              <span style={{ fontWeight: 700, fontSize: '0.78rem' }}>LTX 저품질 · 무료</span>
              <span style={{ fontSize: '0.65rem', color: 'var(--color-text-muted)' }}>내 Kaggle GPU · 10~30분 · 워터마크</span>
            </button>
            <button
              className={clsx('chip', freeAiProvider === 'alibaba' && 'selected')}
              onClick={() => setFreeAiProvider('alibaba')}
              style={{ flex: 1, justifyContent: 'center', flexDirection: 'column', gap: 2, padding: '8px 6px' }}
            >
              <span style={{ fontWeight: 700, fontSize: '0.78rem' }}>알리바바 중품질 · P 1,000</span>
              <span style={{ fontSize: '0.65rem', color: 'var(--color-text-muted)' }}>내 알리바바 쿼터 · 수 분 · 워터마크 없음</span>
            </button>
          </div>
          <div style={{ fontSize: '0.7rem', color: 'var(--color-text-muted)', textAlign: 'center' }}>
            <Clock size={11} style={{ display: 'inline', marginRight: 3 }} />
            {freeAiProvider === 'kaggle_ltx'
              ? '주 30 GPU시간 무료(매주 갱신) · Kaggle API 토큰 필요'
              : '영상당 P 1,000 · 알리바바 API 키 필요'}
          </div>
        </div>
      )}

      {hasMissingImages && !hasBlockedScenes && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8,
          fontSize: '0.73rem', color: 'var(--color-error)',
        }}>
          <AlertCircle size={12} />
          {isGeneratingImages ? '씬 이미지를 생성하는 중이에요 — 끝나면 시작할 수 있어요' : '이미지 생성에 실패한 씬이 있어요 — 위에서 다시 시도해주세요'}
        </div>
      )}

      {startError && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
          marginBottom: 8, padding: '8px 10px', borderRadius: 8,
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.73rem', color: 'var(--color-error)' }}>
            <AlertCircle size={12} style={{ flexShrink: 0 }} />
            {startError.message}
          </div>
          <button
            className="btn btn-outline btn-sm"
            style={{ flexShrink: 0, fontSize: '0.7rem' }}
            onClick={() => {
              // '#charge'는 인앱 충전 모달, 외부 URL은 새 탭, 앱 내부 경로는 라우터로 이동
              if (startError.ctaPath === '#charge') useChargeModal.getState().open()
              else if (startError.ctaPath.startsWith('http')) window.open(startError.ctaPath, '_blank', 'noopener')
              else navigate(startError.ctaPath)
            }}
          >
            {startError.ctaLabel}
          </button>
        </div>
      )}

      <motion.button
        className={clsx(
          'btn btn-full',
          selectedLane === 'premium' ? 'btn-gold' : 'btn-primary',
        )}
        onClick={onStart}
        disabled={hasBlockedScenes || hasMissingImages}
        whileTap={{ scale: 0.98 }}
      >
        {selectedLane === 'premium' ? <Zap size={16} /> : <Play size={16} />}
        {hasBlockedScenes ? '차단된 씬이 있어요'
          : isGeneratingImages ? '이미지 생성 중...'
          : hasMissingImages ? '이미지 생성 필요'
          : '제작 시작'}
      </motion.button>
    </div>
  )
}

// ── S4 메인 스토리보드 ────────────────────────────────────────
export default function S4Storyboard() {
  const navigate = useNavigate()
  const { scenes, setScenes, updateScene, selectedLane, setSelectedLane, saveCurrentProject, persons, photos } = useProjectStore()
  const { user, accessTier } = useUserStore()
  const tier = accessTier()
  const canEditScenes = canEditStoryboard(tier)
  const [localScenes, setLocalScenes] = useState<Scene[]>(
    scenes.length > 0 ? scenes : MOCK_SCENES
  )
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null)
  // 씬별 이미지 생성 진행 상태(시작 시각) · 실패 사유 — UI에 타이머·오류 알림을 표시하는 데 쓴다
  const [genState, setGenState] = useState<Record<string, { startedAt?: number; error?: string; errorKind?: 'download'; note?: string }>>({})
  // 제작 시작 시 필수 API 키 누락·플랜 부족 등으로 진행할 수 없을 때 표시하는 오류 — S5로 넘어간
  // 뒤에야 알게 되는 대신 여기서 바로 막고, 원인에 맞는 곳(키 설정/업그레이드)으로 안내한다
  const [startError, setStartError] = useState<{ message: string; ctaLabel: string; ctaPath: string } | null>(null)

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  )

  // 마운트 시 자세 검출 모델을 미리 받아둔다 — 사용자가 씬을 훑어보는 동안 워밍업해 실제 검사
  // 시점의 지연을 줄인다(S2 업로드 페이지의 warmupExtraction과 동일한 목적)
  useEffect(() => { warmupPoseLandmarker() }, [])

  // 마운트 시 검사 결과가 없는 모든 씬에 대해 Gate 0/1 즉시 검사 실행
  useEffect(() => {
    let changed = false
    const checked = localScenes.map(s => {
      if (!s.gateResults || s.gateResults.length === 0) {
        changed = true
        const sanitized = runGate0(s)
        const g1 = runGate1(sanitized)
        return { ...sanitized, gateResults: [g1] }
      }
      return s
    })
    if (changed) {
      setLocalScenes(checked)
    }
  }, [])

  /**
   * URL 문자열을 받는 것만으로는 실제 이미지가 뜨는지 보장이 안 돼서(Pollinations 폴백은
   * 네트워크 실패해도 URL 문자열 자체는 항상 만들어짐) Image()로 실제 로드까지 검증한다.
   */
  const loadImage = (url: string): Promise<HTMLImageElement> => new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('이미지 URL은 생성됐지만 실제 로드에 실패했어요 (네트워크 또는 프록시 문제일 수 있어요)'))
    img.src = url
  })

  /**
   * 씬 하나의 키프레임을 생성한다(자동생성·재생성·전체생성이 공유하는 단일 경로).
   * 생성 후 자세 검출(poseDetector.ts)로 인원수·관절 신뢰도를 확인해, 이상하면 seed를 살짝
   * 바꿔 1회만 자동 재시도한다 — 그래도 이상하면 재시도 권장 배너만 띄우고 넘어간다(무한 루프 방지).
   */
  const runKeyframeGeneration = async (sc: Scene) => {
    setGenState(prev => ({ ...prev, [sc.id]: { startedAt: Date.now() } }))
    setLocalScenes(prev => prev.map(s => s.id === sc.id ? { ...s, status: 'generating_keyframe' } : s))
    try {
      let { url: imageUrl, degraded, seed } = await generateSceneKeyframe(sc, persons, photos)
      let img = await loadImage(imageUrl)

      let poseIssue: string | undefined
      const expectedCount = sc.subjectRefs.length
      if (expectedCount > 0) {
        const poseCheck = await checkPoseAnomaly(img, expectedCount)
        if (!poseCheck.ok) {
          const retry = await generateSceneKeyframe(sc, persons, photos, seed + 1)
          const retryImg = await loadImage(retry.url)
          const retryCheck = await checkPoseAnomaly(retryImg, expectedCount)
          if (retryCheck.ok) {
            imageUrl = retry.url; degraded = retry.degraded; img = retryImg
          } else {
            poseIssue = '인체 구조가 부자연스러울 수 있어요(자세 이상 감지). 재시도를 권장해요.'
          }
        }
      }

      setLocalScenes(prev => prev.map(s => s.id === sc.id ? {
        ...s,
        keyframeUrl: imageUrl,
        status: 'keyframe_done'
      } : s))
      setGenState(prev => {
        const next = { ...prev }
        const notes = [
          degraded ? '인물 참조 이미지 생성에 실패해 텍스트 설명만으로 그려졌어요. 인물 외형이 다르게 나올 수 있어요.' : null,
          poseIssue ?? null,
        ].filter((n): n is string => !!n)
        if (notes.length > 0) {
          next[sc.id] = { note: notes.join(' ') }
        } else {
          delete next[sc.id]
        }
        return next
      })
    } catch (e) {
      const message = e instanceof Error ? e.message : '알 수 없는 오류로 이미지 생성에 실패했어요'
      console.error(`Failed to generate image for scene ${sc.seq}:`, e)
      setLocalScenes(prev => prev.map(s => s.id === sc.id ? { ...s, status: 'pending' } : s))
      setGenState(prev => ({ ...prev, [sc.id]: { error: message } }))
    }
  }

  // 마운트 시 아직 생성되지 않은 키프레임 이미지 자동으로 순차적 생성 실행
  useEffect(() => {
    const autoGenerate = async () => {
      const pendingScenes = localScenes.filter(s => s.status === 'pending' && !s.keyframeUrl)
      for (const sc of pendingScenes) {
        await runKeyframeGeneration(sc)
      }
    }
    autoGenerate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const totalDuration = localScenes.reduce((s, sc) => s + sc.duration, 0)
  const hasBlockedScenes = localScenes.some(sc => sceneOverallGate(sc) === 'blocked')
  const isGeneratingImages = localScenes.some(sc => sc.status === 'generating_keyframe')
  const hasMissingImages = localScenes.some(sc => !sc.keyframeUrl)

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return
    const oldIdx = localScenes.findIndex(s => s.id === active.id)
    const newIdx = localScenes.findIndex(s => s.id === over.id)
    const reordered = arrayMove(localScenes, oldIdx, newIdx).map((s, i) => ({ ...s, seq: i + 1 }))
    setLocalScenes(reordered)
  }

  const applyScenePatch = (s: Scene, patch: Partial<Scene>): Scene => {
    let updated = { ...s, ...patch }

    // 만약 설명, 대사, 초, 또는 프롬프트가 수정되었다면 게이트 0/1 다시 실행
    if ('descKo' in patch || 'dialogueKo' in patch || 'duration' in patch || 'keyframePromptEn' in patch || 'motionPromptEn' in patch) {
      // Gate 0: 자동 보강
      updated = runGate0(updated)
      // Gate 1: 프롬프트 검사
      const g1Result = runGate1(updated)

      // 기존 검사 결과 목록 중 Gate 1 결과를 교체
      const otherGates = (s.gateResults ?? []).filter(r => r.gate !== 1)
      updated.gateResults = [g1Result, ...otherGates]
    }

    // 프롬프트가 실제로 바뀌었는데 아직 그 프롬프트로 이미지가 재생성되지 않았다면(예: "적용" 없이
    // 텍스트영역 블러만 한 경우) 기존 keyframeUrl은 옛 프롬프트로 만들어진 이미지라 프롬프트와
    // 어긋난다 — 무효화해서 "이미지 생성 필요" 상태로 되돌리고, S5에서 옛 이미지+새 프롬프트가
    // 함께 영상 생성에 쓰이는 불일치를 막는다("적용" 버튼 클릭 시에는 뒤이어 바로 재생성되므로
    // 이 무효화는 순간적이라 눈에 보이지 않는다).
    if ('keyframePromptEn' in patch && patch.keyframePromptEn !== s.keyframePromptEn) {
      updated.keyframeUrl = undefined
      updated.status = 'pending'
    }

    return updated
  }

  const handleUpdate = (id: string, patch: Partial<Scene>) => {
    setLocalScenes(prev => prev.map(s => s.id === id ? applyScenePatch(s, patch) : s))
  }

  const handleRegen = async (id: string) => {
    const targetScene = localScenes.find(s => s.id === id)
    if (!targetScene) return
    setLocalScenes(prev => prev.map(s => s.id === id ? { ...s, regenCount: s.regenCount + 1 } : s))
    await runKeyframeGeneration(targetScene)
  }

  // 프롬프트 수정 + 재생성을 한 번에 원자적으로 처리 — localScenes 클로저가
  // 갱신되기 전에 handleRegen을 호출하면 이전 프롬프트로 재생성되는 문제를 피한다
  const handleApplyPromptEdit = async (id: string, newPrompt: string) => {
    const target = localScenes.find(s => s.id === id)
    if (!target) return
    // setState의 updater 콜백은 React 렌더 단계에서 지연 실행되므로, 그 안에서
    // 계산한 값을 곧바로 읽을 수 없다 — target을 기준으로 미리 계산해 두 곳에 동일하게 사용한다
    const patchedScene = { ...applyScenePatch(target, { keyframePromptEn: newPrompt }), regenCount: target.regenCount + 1 }
    setLocalScenes(prev => prev.map(s => s.id === id ? patchedScene : s))
    await runKeyframeGeneration(patchedScene)
  }

  // 수동 정밀 검수(로그인 사용자) — Gemini Vision에게 직접 해부학적 이상 여부를 물어본다.
  // poseDetector.ts의 자동 검사보다 정확하지만 API 호출 비용이 있어 버튼을 눌렀을 때만 실행한다.
  const handlePrecisionCheck = async (id: string) => {
    const target = localScenes.find(s => s.id === id)
    if (!target?.keyframeUrl) return
    const geminiKey = await KeyVault.getKey('gemini')
    if (!geminiKey) {
      setGenState(prev => ({ ...prev, [id]: { note: 'Gemini API 키가 없어서 정밀 검수를 할 수 없어요. /keys에서 등록해주세요.' } }))
      return
    }
    setGenState(prev => ({ ...prev, [id]: { startedAt: Date.now() } }))
    try {
      const result = await GeminiAdapter.checkImageAnatomy(target.keyframeUrl, geminiKey)
      setGenState(prev => ({
        ...prev,
        [id]: { note: result.ok ? '✅ 정밀 검수 결과: 이상 없음' : `⚠️ 정밀 검수 결과: ${result.issue}` },
      }))
    } catch (e) {
      const message = e instanceof Error ? e.message : '정밀 검수에 실패했어요'
      setGenState(prev => ({ ...prev, [id]: { error: message } }))
    }
  }

  // 키프레임 이미지 다운로드 — 이미 생성이 끝난 정지 이미지를 로컬 파일로 저장한다. Gemini 경로는
  // blob: URL(같은 페이지 메모리, 항상 다운로드 가능)이지만 Alibaba/Pollinations는 원격 CDN URL이라
  // fetch가 CORS로 막힐 수 있다 — 그 경우 새 탭으로 열어 사용자가 직접 저장하게 한다.
  const handleDownload = async (id: string) => {
    const target = localScenes.find(s => s.id === id)
    if (!target?.keyframeUrl) return

    try {
      await ensureKeyframeDownloadAuthorization()
    } catch (e) {
      const message = e instanceof Error ? e.message : '다운로드 인가에 실패했어요'
      setGenState(prev => ({ ...prev, [id]: { error: message, errorKind: 'download' } }))
      return
    }

    try {
      const res = await fetch(target.keyframeUrl)
      const blob = await res.blob()
      const blobUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = `scene-${target.seq}.png`
      a.click()
      URL.revokeObjectURL(blobUrl)
    } catch {
      window.open(target.keyframeUrl, '_blank')
      setGenState(prev => ({ ...prev, [id]: { note: '새 탭에서 열렸어요 — 이미지를 길게 누르거나 우클릭해서 저장해주세요.' } }))
    }
  }

  const handleGenerateAllImages = async () => {
    const pendingScenes = localScenes.filter(s => s.status !== 'keyframe_done' && s.status !== 'generating_keyframe')
    if (pendingScenes.length === 0) return

    for (const sc of pendingScenes) {
      await runKeyframeGeneration(sc)
    }
  }

  const handleDelete = (id: string) => {
    if (localScenes.length <= 1) return
    setLocalScenes(prev => prev.filter(s => s.id !== id).map((s, i) => ({ ...s, seq: i + 1 })))
  }

  const handleAddScene = () => {
    if (totalDuration >= 30) return
    let newScene: Scene = {
      id: crypto.randomUUID(),
      seq: localScenes.length + 1,
      duration: 3,
      descKo: '새 씬을 편집해주세요',
      keyframePromptEn: 'cinematic photo of people',
      originalKeyframePromptEn: 'cinematic photo of people',
      motionPromptEn: 'slow dolly-in',
      subjectRefs: ['person_1'],
      status: 'pending',
      regenCount: 0,
      gateResults: [],
    }
    
    // 신규 생성 시에도 기본적으로 게이트 실행
    newScene = runGate0(newScene)
    const g1Result = runGate1(newScene)
    newScene.gateResults = [g1Result]

    setLocalScenes(prev => [...prev, newScene])
  }

  const handleStart = async () => {
    setStartError(null)

    // 비로그인은 레인과 무관하게 어떤 제작도 시작할 수 없다 — S5로 넘어가서(renderScene에서)
    // 뒤늦게 막히는 대신 여기서 바로 안내한다
    if (tier === 'guest') {
      setStartError({
        message: '영상을 만들려면 먼저 로그인해주세요. 가입하면 웰컴 포인트 1,000개를 드려요.',
        ctaLabel: '로그인하러 가기', ctaPath: '/profile',
      })
      return
    }

    // 선택한 제작 방식에 필요한 API 키가 없으면, 포인트를 차감하기 전에 여기서 먼저 막고
    // 키 설정으로 안내한다 (차감 후 키 부재로 실패하면 환급 절차가 필요해지므로 순서가 중요)
    if (selectedLane === 'free_ai') {
      const provider = useProjectStore.getState().freeAiProvider
      if (provider === 'kaggle_ltx') {
        if (!(await KeyVault.hasKey('kaggle'))) {
          setStartError({
            message: 'LTX 무료 생성에는 Kaggle API 토큰이 필요해요. "유저명:키" 형식으로 등록해주세요.',
            ctaLabel: '키 설정하러 가기', ctaPath: '/keys',
          })
          return
        }
      } else if (isAlibabaBlocked()) {
        setStartError({
          message: '알리바바 무료 사용 기한이 지나 자동으로 사용이 중단됐어요. 키 설정에서 갱신을 확인하면 다시 쓸 수 있어요.',
          ctaLabel: '갱신 확인하러 가기', ctaPath: '/keys',
        })
        return
      } else if (!(await KeyVault.hasKey('alibaba'))) {
        setStartError({
          message: 'AI 영상 제작에는 알리바바 API 키가 필요해요. 먼저 키를 등록해주세요.',
          ctaLabel: '키 설정하러 가기', ctaPath: '/keys',
        })
        return
      }
    } else if (selectedLane === 'premium') {
      if (!useProjectStore.getState().premiumProvider) {
        setStartError({
          message: '사용할 영상 모델을 먼저 선택해주세요. (키가 등록된 모델만 선택할 수 있어요)',
          ctaLabel: '키 설정하러 가기', ctaPath: '/keys',
        })
        return
      }
      const provider = localScenes[0] ? await resolvePremiumProvider(localScenes[0]) : null
      if (!provider) {
        setStartError({
          message: '선택한 영상 모델의 API 키를 찾을 수 없어요. 키를 다시 등록하거나 다른 모델을 선택해주세요.',
          ctaLabel: '키 설정하러 가기', ctaPath: '/keys',
        })
        return
      }
    }

    // 제작 인가 — 무빙포토는 오늘의 무료 슬롯(하루 5개), 그 외/초과분은 포인트 차감(멱등 refId).
    // 여기서 미리 확보해 두면 S5의 renderScene이 pointPayment를 보고 통과시킨다.
    try {
      await ensureRenderAuthorization(localScenes, selectedLane)
    } catch (e) {
      if (e instanceof InsufficientPointsError) {
        setStartError({
          message: selectedLane === 'moving_photo'
            ? `오늘의 무료 무빙포토를 다 썼어요 — 포인트로 계속 만들 수 있어요. ${e.message}`
            : e.message,
          ctaLabel: '포인트 충전하러 가기', ctaPath: '#charge',
        })
      } else {
        setStartError({
          message: e instanceof Error ? e.message : '결제 처리에 실패했어요. 잠시 후 다시 시도해주세요.',
          ctaLabel: '프로필에서 확인', ctaPath: '/profile',
        })
      }
      return
    }

    setScenes(localScenes)
    // 로컬 스토어 씬 정보를 업데이트한 상태에서 저장
    if (user) {
      try {
        // Zustand set이 동기식이므로 get() 호출 시 반영됨
        await saveCurrentProject(user.uid)
      } catch (e) {
        console.error('Failed to save project:', e)
      }
    }
    navigate('/progress')
  }

  return (
    <div style={{ paddingBottom: 200 }}>
      {/* 헤더 */}
      <div style={{ padding: '20px 16px 16px' }}>
        <div className="flex-between" style={{ marginBottom: 8 }}>
          <h1 style={{ fontSize: '1.375rem', fontWeight: 800 }}>스토리보드</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className={clsx('badge', totalDuration > 30 ? 'badge-error' : 'badge-brand')}>
              총 {totalDuration}초
            </span>
            {totalDuration > 30 && (
              <AlertCircle size={16} color="var(--color-error)" />
            )}
          </div>
        </div>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
          씬을 편집하고 드래그로 순서를 바꿔보세요
        </p>
      </div>

      {/* 씬 목록 */}
      <div style={{ padding: '0 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext items={localScenes.map(s => s.id)} strategy={verticalListSortingStrategy}>
            {localScenes.map((scene, i) => (
              <SortableSceneCard
                key={scene.id}
                scene={scene}
                index={i}
                genState={genState[scene.id]}
                onUpdate={handleUpdate}
                onRegen={handleRegen}
                onApplyPrompt={handleApplyPromptEdit}
                onDelete={handleDelete}
                onPreviewClick={setLightboxUrl}
                onPrecisionCheck={handlePrecisionCheck}
                onDownload={handleDownload}
                tier={tier}
              />
            ))}
          </SortableContext>
        </DndContext>

        {/* 씬 이미지 일괄 생성 버튼 */}
        {localScenes.some(s => s.status !== 'keyframe_done') && (
          <motion.button
            className="btn btn-outline btn-full"
            onClick={handleGenerateAllImages}
            style={{
              borderColor: 'rgba(124,58,255,0.4)',
              color: 'var(--color-brand-300)',
              marginBottom: 8
            }}
            whileTap={{ scale: 0.98 }}
          >
            <Sparkles size={14} style={{ marginRight: 4 }} /> 모든 씬 키프레임 이미지 생성
          </motion.button>
        )}

        {/* 씬 추가 버튼 — 로그인 사용자만 */}
        {totalDuration < 30 && (
          canEditScenes ? (
            <motion.button
              className="btn btn-outline btn-full"
              onClick={handleAddScene}
              whileTap={{ scale: 0.98 }}
            >
              <Plus size={16} /> 씬 추가
            </motion.button>
          ) : (
            <div style={{
              textAlign: 'center', fontSize: '0.73rem', color: 'var(--color-text-muted)',
              padding: '10px 0',
            }}>
              🔒 로그인하면 씬을 추가할 수 있어요
            </div>
          )
        )}
      </div>

      {/* 레인 선택 바 */}
      <LaneBar
        selectedLane={selectedLane}
        onSelect={l => { setSelectedLane(l); setStartError(null) }}
        onStart={handleStart}
        hasBlockedScenes={hasBlockedScenes}
        isGeneratingImages={isGeneratingImages}
        hasMissingImages={hasMissingImages}
        startError={startError}
      />

      {/* 라이트박스 모달 */}
      <AnimatePresence>
        {lightboxUrl && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{
              position: 'fixed',
              inset: 0,
              zIndex: 9999,
              background: 'rgba(0,0,0,0.92)',
              backdropFilter: 'blur(10px)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 20,
              cursor: 'zoom-out'
            }}
            onClick={() => setLightboxUrl(null)}
          >
            <motion.div
              initial={{ scale: 0.93, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.93, opacity: 0 }}
              style={{
                position: 'relative',
                maxWidth: '92%',
                maxHeight: '85%',
                borderRadius: 12,
                overflow: 'hidden',
                boxShadow: '0 20px 50px rgba(0,0,0,0.9)',
                border: '1px solid rgba(255,255,255,0.08)'
              }}
              onClick={(e) => e.stopPropagation()}
            >
              {/* 이미지 */}
              <img
                src={lightboxUrl}
                alt="원본 키프레임 미리보기"
                style={{
                  width: '100%',
                  height: 'auto',
                  maxHeight: '80vh',
                  objectFit: 'contain',
                  display: 'block'
                }}
              />
              
              {/* 닫기 버튼 */}
              <button
                onClick={() => setLightboxUrl(null)}
                style={{
                  position: 'absolute',
                  top: 16,
                  right: 16,
                  width: 36,
                  height: 36,
                  borderRadius: '50%',
                  background: 'rgba(0,0,0,0.7)',
                  border: '1px solid rgba(255,255,255,0.2)',
                  color: '#fff',
                  fontSize: 18,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.3)'
                }}
              >
                ✕
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
