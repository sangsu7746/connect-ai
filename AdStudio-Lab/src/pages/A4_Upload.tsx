import React, { useState, useRef, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, X, AlertCircle, ChevronRight, User, Camera } from 'lucide-react'
import { useProjectStore, ProjectLimitError } from '../stores/projectStore'
import { useUserStore } from '../stores/userStore'
import { useAdStore } from '../stores/adStore'
import type { Photo, Relation, Person, GateCheckItem, VoiceStyle } from '../types'
import { clsx } from 'clsx'
import {
  detectAndScoreAll, buildPerson, releasePhoto, warmupExtraction,
  expectedHeadcountLabel, validatePersonCount,
  type IndexedCandidate,
} from '../extraction'
import { preprocessFile } from '../extraction/normalize'

const MAX_PHOTOS = 4
const ACCEPTED = '.jpg,.jpeg,.png,.heic,.heif'

// capture 속성은 모바일 브라우저에서만 네이티브 카메라 앱을 직접 연다 — 데스크톱은 이 속성을
// 무시하고 그냥 파일 탐색기를 열어 기존 업로드 존과 중복되므로, "카메라로 촬영" 버튼은 모바일에서만 노출한다
function isMobileDevice(): boolean {
  const ua = navigator.userAgent
  return /Android|iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

// 광고 모델 구성 — 오마주의 Relation 값을 재사용해 인원수 검증·파이프라인 호환을 유지한다
const RELATIONS: { id: Relation; emoji: string; labelKo: string; labelEn: string }[] = [
  { id: 'solo',    emoji: '🙋', labelKo: '1인 모델', labelEn: 'Solo model'  },
  { id: 'couple',  emoji: '👥', labelKo: '2인 모델', labelEn: 'Two models'  },
  { id: 'friends', emoji: '👨‍👩‍👧', labelKo: '그룹 모델', labelEn: 'Group models' },
]

// 배우 사용 방식 선택지 — 값 저장은 adStore.actorUsage, 실제 반영은 키프레임 참조 이미지 선택과
// 인물 유지 지시문(aiAdapters)에서 이뤄진다
const USAGE_SCOPES = [
  { id: 'face', emoji: '👤', label: '얼굴만', desc: '체형·포즈·의상은 씬에 맞게 AI 생성' },
  { id: 'half', emoji: '🧍', label: '상반신', desc: '얼굴+체형+의상까지 유지' },
  { id: 'full', emoji: '📷', label: '전신 그대로', desc: '사진 원본 느낌 유지 (무빙포토 중심)' },
] as const
const USAGE_OUTFITS = [
  { id: 'keep', label: '사진 의상 그대로' },
  { id: 'restyle', label: '광고에 맞게 AI 스타일링' },
] as const
const USAGE_BACKGROUNDS = [
  { id: 'remove', label: '배경 제거, 배우만' },
  { id: 'keep', label: '사진 배경 분위기 활용' },
] as const

// 인물별 대사 음성 설정 옵션 (S2 인물 확정 단계에서 지정 → 모든 씬에 일관 적용)
const GENDER_OPTIONS: { id: NonNullable<Person['gender']>; label: string }[] = [
  { id: 'female',  label: '여성' },
  { id: 'male',    label: '남성' },
  { id: 'unknown', label: '지정 안함' },
]
const AGE_BAND_OPTIONS: { id: NonNullable<Person['ageBand']>; label: string }[] = [
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
// 바디·의상 컨셉 — 지정하면 사진 속 실제 모습 대신 이 컨셉으로 그려진다("지정 안함"이면 사진 그대로)
const BODY_CONCEPT_OPTIONS: { id: NonNullable<Person['bodyConcept']>; label: string }[] = [
  { id: 'none',     label: '지정 안함' },
  { id: 'slim',     label: '슬림형' },
  { id: 'athletic', label: '탄탄한 근육형' },
  { id: 'medium',   label: '균형 체형' },
  { id: 'curvy',    label: '볼륨 체형' },
  { id: 'sturdy',   label: '건장한 체형' },
  { id: 'petite',   label: '아담한 체형' },
  { id: 'tall',     label: '장신형' },
]
const OUTFIT_CONCEPT_OPTIONS: { id: NonNullable<Person['outfitConcept']>; label: string }[] = [
  { id: 'none',                  label: '지정 안함' },
  { id: 'noir',                  label: '느와르 슈트' },
  { id: 'hanbok',                label: '한복 전통' },
  { id: 'enlightenment_vintage', label: '개화기 빈티지' },
  { id: 'fantasy_dress',         label: '로맨틱 판타지 드레스' },
  { id: 'youth_casual',          label: '청춘 캐주얼' },
  { id: 'office',                label: '오피스 정장' },
  { id: 'street_performance',    label: '스트릿 퍼포먼스' },
  { id: 'high_fashion',          label: '하이엔드 럭셔리' },
  { id: 'victorian',             label: '빅토리안 시대' },
  { id: 'artdeco_jazz',          label: '아르데코 재즈시대' },
]

// 이미지 리사이즈 유틸 (HEIC은 preprocessFile로 JPEG 변환된 blob이 들어온다)
async function resizeImage(blob: Blob, maxPx = 2048): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    const url = URL.createObjectURL(blob)
    img.onload = () => {
      const ratio = Math.min(1, maxPx / Math.max(img.width, img.height))
      const canvas = document.createElement('canvas')
      canvas.width  = img.width  * ratio
      canvas.height = img.height * ratio
      canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
      URL.revokeObjectURL(url)
      resolve(canvas.toDataURL('image/jpeg', 0.92))
    }
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('이미지를 불러오지 못했어요')) }
    img.src = url
  })
}

// object-fit: cover로 표시되는 정사각 썸네일 위에 정규화 bbox([x,y,w,h])를 정확히 겹치기 위한 좌표 변환
function mapBboxToCoverRect(bbox: [number, number, number, number], imgW: number, imgH: number) {
  if (!imgW || !imgH) return null
  const [bx, by, bw, bh] = bbox
  let cropLeft = 0, cropTop = 0, cropWidth = 1, cropHeight = 1
  if (imgW >= imgH) {
    cropWidth = imgH / imgW
    cropLeft = (1 - cropWidth) / 2
  } else {
    cropHeight = imgW / imgH
    cropTop = (1 - cropHeight) / 2
  }
  return {
    leftPct: ((bx - cropLeft) / cropWidth) * 100,
    topPct: ((by - cropTop) / cropHeight) * 100,
    widthPct: (bw / cropWidth) * 100,
    heightPct: (bh / cropHeight) * 100,
  }
}

// 얼굴 박스 오버레이 (주인공 추출 파이프라인 P1/P2 결과 시각화)
function FaceOverlay({
  photo, faces, showBackground, onToggleStar, onToggleShowBackground,
}: {
  photo: Photo
  faces: IndexedCandidate[]
  showBackground: boolean
  onToggleStar: (id: string) => void
  onToggleShowBackground: () => void
}) {
  const visible = showBackground ? faces : faces.filter(f => f.candidate.m.eligible)
  const hiddenCount = faces.length - visible.length

  return (
    <>
      {visible.map(f => {
        const rect = mapBboxToCoverRect(f.candidate.det.bbox, photo.width, photo.height)
        if (!rect) return null
        return (
          <div
            key={f.id}
            onClick={e => { e.stopPropagation(); onToggleStar(f.id) }}
            style={{
              position: 'absolute',
              left: `${rect.leftPct}%`, top: `${rect.topPct}%`,
              width: `${rect.widthPct}%`, height: `${rect.heightPct}%`,
              border: `2px solid ${f.isStarPick ? 'var(--color-brand-400)' : 'rgba(255,255,255,0.65)'}`,
              borderRadius: 6,
              boxShadow: f.isStarPick ? '0 0 0 2px rgba(124,58,255,0.35)' : 'none',
              cursor: 'pointer',
            }}
          >
            {f.isStarPick && (
              <span style={{ position: 'absolute', top: -11, left: -9, fontSize: 13 }}>⭐</span>
            )}
          </div>
        )
      })}
      {hiddenCount > 0 && !showBackground && (
        <button
          onClick={e => { e.stopPropagation(); onToggleShowBackground() }}
          style={{
            position: 'absolute', bottom: 6, left: 6, fontSize: 10, padding: '3px 7px',
            borderRadius: 6, background: 'rgba(0,0,0,0.65)', color: '#fff', border: 'none', cursor: 'pointer',
          }}
        >
          외 {hiddenCount}명 더 보기
        </button>
      )}
    </>
  )
}

// 업로드 존
function UploadZone({ onFiles, dragOver, setDragOver }: {
  onFiles: (files: File[]) => void
  dragOver: boolean
  setDragOver: (v: boolean) => void
}) {
  const { t } = useTranslation()
  const inputRef = useRef<HTMLInputElement>(null)
  const captureInputRef = useRef<HTMLInputElement>(null)
  const showCameraButton = isMobileDevice()

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/') || /\.hei[cf]$/i.test(f.name))
    onFiles(files)
  }, [onFiles, setDragOver])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) onFiles(Array.from(e.target.files))
    e.target.value = ''
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div
        className={clsx('upload-zone', dragOver && 'drag-over')}
        onClick={() => inputRef.current?.click()}
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          multiple
          style={{ display: 'none' }}
          onChange={handleChange}
        />
        <motion.div
          animate={{ scale: dragOver ? 1.1 : 1 }}
          className="upload-zone__icon"
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <Upload size={40} />
        </motion.div>
        <div>
          <p style={{ fontWeight: 600, marginBottom: 4, color: 'var(--color-text-primary)' }}>
            {dragOver ? '여기에 놓으세요!' : '사진을 탭하거나 끌어다 놓으세요'}
          </p>
          <p style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)' }}>
            JPG · PNG · HEIC / 최대 4장
          </p>
        </div>
      </div>

      {showCameraButton && (
        <button
          type="button"
          className="btn btn-outline btn-full"
          onClick={() => captureInputRef.current?.click()}
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
        >
          <input
            ref={captureInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            style={{ display: 'none' }}
            onChange={handleChange}
          />
          <Camera size={18} />
          카메라로 촬영
        </button>
      )}
    </div>
  )
}

// 동의 게이트
function ConsentGate({ checked, onChange }: {
  checked: [boolean, boolean]
  onChange: (idx: 0 | 1, val: boolean) => void
}) {
  const { t } = useTranslation()
  const items = [
    { key: '0' as const, text: '업로드한 사진 속 모든 인물의 동의를 받았거나, 본인입니다.' },
    { key: '1' as const, text: '유명인·미성년 단독·성적 콘텐츠 제작에 사용하지 않겠습니다.' },
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <h3 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: 4 }}>
        이용 동의 (필수)
      </h3>
      {items.map((item, i) => (
        <label key={item.key} className="checkbox-item">
          <input
            type="checkbox"
            checked={checked[i]}
            onChange={e => onChange(i as 0 | 1, e.target.checked)}
          />
          <span style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>
            {item.text}
          </span>
        </label>
      ))}
      <div style={{
        fontSize: '0.75rem', color: 'var(--color-text-muted)',
        background: 'var(--color-bg-base)', borderRadius: 8,
        padding: '8px 12px', lineHeight: 1.6,
      }}>
        🔒 얼굴 특징은 품질 검사에만 일시 사용되며 서버에 저장되지 않아요
      </div>
    </div>
  )
}

// ── 메인 S2 업로드 페이지 ─────────────────────────────────────
export default function S2Upload() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const { updateProject, setPhotos, photos, setPersons, saveCurrentProject } = useProjectStore()
  const { actorUsage, setActorUsage } = useAdStore()
  const { user } = useUserStore()

  const [dragOver, setDragOver] = useState(false)
  const [selectedRelation, setSelectedRelation] = useState<Relation>('solo')
  const [consent, setConsent] = useState<[boolean, boolean]>([false, false])
  const [isProcessing, setIsProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // 무료 플랜 프로젝트 저장 한도 초과 시 표시 — S3/S4로 넘어간 뒤 실패하는 대신 여기서 바로 막는다
  const [limitError, setLimitError] = useState<string | null>(null)

  // 주인공 추출 파이프라인 상태
  const [facesByPhoto, setFacesByPhoto] = useState<Record<string, IndexedCandidate[]>>({})
  const [expandedBg, setExpandedBg] = useState<Record<string, boolean>>({})
  const [isDetecting, setIsDetecting] = useState(false)
  const [detectError, setDetectError] = useState<string | null>(null)
  const [isBuildingPersons, setIsBuildingPersons] = useState(false)
  const [usedGammaFallback, setUsedGammaFallback] = useState(false)
  const [usedTileFallback, setUsedTileFallback] = useState(false)
  const [gateSummary, setGateSummary] = useState<{ label: string; checks: GateCheckItem[] }[] | null>(null)
  const [pendingPersons, setPendingPersons] = useState<Person[] | null>(null)
  const [voiceConfigPersons, setVoiceConfigPersons] = useState<Person[] | null>(null)
  // 자동 제안(★)이 의도치 않은 인물을 뽑았을 때, 음성 설정 단계에서 한 번 더 명시적으로
  // 제외할 수 있게 하는 체크 — 사진 위 작은 박스 토글만으로는 놓치기 쉬워서 추가한 2차 확인 지점
  const [excludedPersonIds, setExcludedPersonIds] = useState<Set<string>>(new Set())
  // 사진에서 인물이 감지/선택되지 않았을 때 조용히 넘어가지 않고 명시적으로 확인받는다 —
  // 인물 없이 진행하면 이후 씬 생성이 배우를 반영하지 못하고 일반적인 장면으로만 만들어진다
  const [noPersonConfirm, setNoPersonConfirm] = useState(false)

  // 모델 워밍업 (첫 사진 업로드 전에 미리 다운로드 시작)
  useEffect(() => { warmupExtraction() }, [])

  // 사진 구성 또는 관계 프리셋이 바뀔 때마다 P0~P2(+P-11 감마·타일 폴백) 재실행
  useEffect(() => {
    if (photos.length === 0) {
      setFacesByPhoto({})
      return
    }
    let cancelled = false
    setIsDetecting(true)
    setDetectError(null)

    detectAndScoreAll(photos, selectedRelation)
      .then(results => {
        if (cancelled) return
        const map: Record<string, IndexedCandidate[]> = {}
        for (const r of results) map[r.photoId] = r.candidates
        setFacesByPhoto(map)
        setUsedGammaFallback(results.some(r => r.p11Recovered))
        setUsedTileFallback(results.some(r => r.tiledUsed))
      })
      .catch(e => {
        if (cancelled) return
        console.error('주인공 추출 파이프라인 실패:', e)
        setDetectError('얼굴 인식 모델을 불러오지 못했어요. 인물 확인 없이 계속 진행할 수 있어요.')
      })
      .finally(() => { if (!cancelled) setIsDetecting(false) })

    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photos.map(p => p.id).join(','), selectedRelation])

  const canProceed = photos.length > 0 && consent[0] && consent[1]

  const allFaces = Object.values(facesByPhoto).flat()
  const starredCount = allFaces.filter(f => f.isStarPick).length
  const hasFaceData = allFaces.length > 0
  const headcountCheck = hasFaceData ? validatePersonCount(selectedRelation, starredCount) : { ok: true, messageKo: '' }

  const handleFiles = useCallback(async (files: File[]) => {
    setError(null)
    const remaining = MAX_PHOTOS - photos.length
    if (remaining <= 0) {
      setError('사진은 최대 4장까지 업로드할 수 있어요')
      return
    }
    const toProcess = files.slice(0, remaining)
    setIsProcessing(true)
    try {
      const newPhotos: Photo[] = await Promise.all(
        toProcess.map(async (file) => {
          const { blob } = await preprocessFile(file) // HEIC/HEIF → JPEG, 그 외는 그대로
          const previewUrl = await resizeImage(blob)
          const img = new Image()
          await new Promise(r => { img.onload = r; img.src = previewUrl })
          return {
            id: crypto.randomUUID(),
            file,
            previewUrl,
            width: img.naturalWidth,
            height: img.naturalHeight,
            faces: [],
          }
        })
      )
      setPhotos([...photos, ...newPhotos])
    } catch (e) {
      console.error('사진 처리 실패:', e)
      setError('이미지 처리 중 오류가 발생했어요')
    } finally {
      setIsProcessing(false)
    }
  }, [photos, setPhotos])

  const removePhoto = (id: string) => {
    setPhotos(photos.filter(p => p.id !== id))
    setFacesByPhoto(prev => {
      const next = { ...prev }
      delete next[id]
      return next
    })
    releasePhoto(id)
  }

  const toggleStarPick = (id: string) => {
    setFacesByPhoto(prev => {
      const next: Record<string, IndexedCandidate[]> = {}
      for (const [photoId, faces] of Object.entries(prev)) {
        next[photoId] = faces.map(f => f.id === id ? { ...f, isStarPick: !f.isStarPick } : f)
      }
      return next
    })
  }

  const finishAndNavigate = async (personsToSave: Person[]) => {
    setLimitError(null)
    setPersons(personsToSave)
    updateProject({
      relation: selectedRelation,
      consentAt: new Date(),
    })
    if (user) {
      try {
        await saveCurrentProject(user.uid)
      } catch (e) {
        if (e instanceof ProjectLimitError) {
          setLimitError(e.message)
          return
        }
        console.error('Failed to save project:', e)
      }
    }
    navigate('/concept')
  }

  const handleNext = async () => {
    setError(null)

    const starredFaces = allFaces.filter(f => f.isStarPick)
    if (!hasFaceData || starredFaces.length === 0) {
      setNoPersonConfirm(true)
      return
    }

    // 확정된 주인공 얼굴들을 실제 PersonRef(Person)로 조립 (P4 원본 해상도 크롭→P-12→P9)
    setIsBuildingPersons(true)
    let built: Person[]
    try {
      built = await Promise.all(starredFaces.map((face, i) => buildPerson(`person_${i + 1}`, face)))
    } catch (e) {
      console.error('인물 레퍼런스 생성 실패:', e)
      setError('인물 레퍼런스를 만드는 중 문제가 발생했어요. 다시 시도해주세요.')
      setIsBuildingPersons(false)
      return
    }
    setIsBuildingPersons(false)

    const withIssues = built
      .map(p => ({ label: p.label, checks: (p.gateResults ?? []).filter(c => c.level === 'warn' || c.level === 'fail') }))
      .filter(g => g.checks.length > 0)

    if (withIssues.length > 0) {
      setGateSummary(withIssues)
      setPendingPersons(built)
      return
    }

    setExcludedPersonIds(new Set())
    setVoiceConfigPersons(built)
  }

  const confirmProceedAnyway = () => {
    if (!pendingPersons) return
    const toSave = pendingPersons
    setGateSummary(null)
    setPendingPersons(null)
    setExcludedPersonIds(new Set())
    setVoiceConfigPersons(toSave)
  }

  const updateVoicePerson = (id: string, patch: Partial<Pick<Person, 'gender' | 'ageBand' | 'voiceStyle' | 'bodyConcept' | 'outfitConcept'>>) => {
    setVoiceConfigPersons(prev => prev ? prev.map(p => p.id === id ? { ...p, ...patch } : p) : prev)
  }

  const toggleExcludePerson = (id: string) => {
    setExcludedPersonIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const confirmVoiceConfig = async () => {
    if (!voiceConfigPersons) return
    // 씬 템플릿의 subjectRefs는 person_1/person_2 같은 label로 매칭되므로, 제외 후 남은
    // 인물은 순서대로 다시 번호를 매겨줘야 person_1을 찾는 솔로 씬 등이 깨지지 않는다
    const toSave = voiceConfigPersons
      .filter(p => !excludedPersonIds.has(p.id))
      .map((p, i) => ({ ...p, label: `person_${i + 1}` }))
    setVoiceConfigPersons(null)
    if (toSave.length === 0) {
      setNoPersonConfirm(true)
      return
    }
    await finishAndNavigate(toSave)
  }

  const cancelGateSummary = () => {
    setGateSummary(null)
    setPendingPersons(null)
  }

  const confirmNoPerson = async () => {
    setNoPersonConfirm(false)
    await finishAndNavigate([])
  }

  return (
    <div style={{ padding: '20px 16px 100px' }}>

      {/* 섹션 헤더 */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: '1.375rem', fontWeight: 800, marginBottom: 6 }}>
          사진 업로드
        </h1>
        <p style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
          주인공이 잘 보이는 사진을 올려주세요
        </p>
      </div>

      {/* 스텝 인디케이터 */}
      <StepIndicator current={1} total={4} />

      {/* 무료 플랜 프로젝트 저장 한도 초과 안내 */}
      {limitError && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10,
            padding: '10px 14px', borderRadius: 10,
            background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.3)',
            marginBottom: 16,
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>
            <AlertCircle size={16} color="var(--color-warning, #f59e0b)" style={{ flexShrink: 0 }} />
            {limitError}
          </div>
          <button className="btn btn-outline btn-sm" style={{ flexShrink: 0, fontSize: '0.75rem' }} onClick={() => navigate('/profile')}>
            업그레이드
          </button>
        </motion.div>
      )}

      {/* 업로드 존 */}
      {photos.length < MAX_PHOTOS && (
        <motion.div layout style={{ marginBottom: 16 }}>
          <UploadZone onFiles={handleFiles} dragOver={dragOver} setDragOver={setDragOver} />
        </motion.div>
      )}

      {/* 로딩 */}
      {isProcessing && (
        <div style={{ textAlign: 'center', padding: '12px 0', color: 'var(--color-text-muted)', fontSize: '0.875rem' }}>
          처리 중...
        </div>
      )}

      {/* 에러 */}
      {error && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
          style={{
            display: 'flex', gap: 8, padding: '10px 14px',
            background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: 10, marginBottom: 12, fontSize: '0.8rem', color: 'var(--color-error)',
          }}
        >
          <AlertCircle size={16} style={{ flexShrink: 0 }} />
          {error}
        </motion.div>
      )}

      {/* 주인공 인식 안내/에러 */}
      {detectError && (
        <div style={{
          display: 'flex', gap: 8, padding: '10px 14px',
          background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.25)',
          borderRadius: 10, marginBottom: 12, fontSize: '0.8rem', color: 'var(--color-warning, #f59e0b)',
        }}>
          <AlertCircle size={16} style={{ flexShrink: 0 }} />
          {detectError}
        </div>
      )}

      {/* P-11/타일 폴백: 역광·소형 얼굴 등으로 보정 재검출된 경우 안내 */}
      {!detectError && (usedGammaFallback || usedTileFallback) && (
        <div style={{
          padding: '8px 12px', marginBottom: 12, borderRadius: 8,
          background: 'var(--color-bg-base)', fontSize: '0.75rem', color: 'var(--color-text-muted)',
        }}>
          💡 {usedGammaFallback && usedTileFallback
            ? '역광·소형 얼굴 사진을 자동으로 보정해 인식했어요.'
            : usedGammaFallback
            ? '역광 사진은 자동으로 밝기를 보정해 인식했어요.'
            : '얼굴이 작은 사진은 확대해서 인식했어요.'}
        </div>
      )}

      {/* 사진 그리드 */}
      <AnimatePresence>
        {photos.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            style={{ marginBottom: 16 }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
              <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>
                선택된 사진 <span style={{ color: 'var(--color-brand-400)' }}>{photos.length}/{MAX_PHOTOS}</span>
              </span>
            </div>
            <div className="photo-grid">
              {photos.map(photo => {
                const faces = facesByPhoto[photo.id] ?? []
                return (
                  <motion.div
                    key={photo.id}
                    className="photo-item"
                    initial={{ scale: 0.8, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    exit={{ scale: 0.8, opacity: 0 }}
                    layout
                  >
                    <img src={photo.previewUrl} alt="" />

                    <FaceOverlay
                      photo={photo}
                      faces={faces}
                      showBackground={!!expandedBg[photo.id]}
                      onToggleStar={toggleStarPick}
                      onToggleShowBackground={() => setExpandedBg(prev => ({ ...prev, [photo.id]: true }))}
                    />

                    {/* 감지 상태 배지 */}
                    <div style={{
                      position: 'absolute', bottom: 6, right: 6,
                      display: 'flex', alignItems: 'center', gap: 3,
                      background: 'rgba(0,0,0,0.6)', borderRadius: 6,
                      padding: '2px 6px',
                    }}>
                      <User size={11} color="#fff" opacity={0.8} />
                      <span style={{ fontSize: 10, color: '#fff', opacity: 0.8 }}>
                        {isDetecting && faces.length === 0 ? '감지 중' : `${faces.length}명 감지`}
                      </span>
                    </div>

                    <button
                      className="photo-item__remove"
                      onClick={() => removePhoto(photo.id)}
                    >
                      <X size={14} />
                    </button>
                  </motion.div>
                )
              })}

              {/* 추가 플레이스홀더 */}
              {photos.length < MAX_PHOTOS && photos.length > 0 && [...Array(MAX_PHOTOS - photos.length)].map((_, i) => (
                <div
                  key={`ph-${i}`}
                  className="photo-item"
                  style={{
                    border: '2px dashed var(--color-border)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    cursor: 'pointer',
                    aspectRatio: '1',
                  }}
                  onClick={() => document.querySelector<HTMLInputElement>('input[type=file]')?.click()}
                >
                  <Upload size={24} color="var(--color-text-muted)" opacity={0.5} />
                </div>
              ))}
            </div>

            {/* 주인공 확정 요약 + 인원수 검증 안내 */}
            {hasFaceData && (
              <div style={{ marginTop: 10, fontSize: '0.78rem', color: headcountCheck.ok ? 'var(--color-text-muted)' : 'var(--color-error)' }}>
                {headcountCheck.ok
                  ? `⭐ 주인공 ${starredCount}명 선택됨 (${expectedHeadcountLabel(selectedRelation)} 필요) — 박스를 탭해 선택을 바꿀 수 있어요`
                  : headcountCheck.messageKo}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {/* 모델 구성 선택 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: 12, color: 'var(--color-text-secondary)' }}>
          모델 구성을 선택해주세요
        </h2>
        <div className="relation-grid">
          {RELATIONS.map(rel => (
            <motion.div
              key={rel.id}
              className={clsx('relation-item', selectedRelation === rel.id && 'selected')}
              onClick={() => setSelectedRelation(rel.id)}
              whileTap={{ scale: 0.95 }}
            >
              <span className="relation-item__emoji">{rel.emoji}</span>
              <span className="relation-item__label">{rel.labelKo}</span>
            </motion.div>
          ))}
        </div>
      </div>

      {/* 배우 사용 방식 — 사진을 어디까지 참조할지 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: 12, color: 'var(--color-text-secondary)' }}>
          배우 사용 방식
        </h2>

        {/* 반영 범위 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 14 }}>
          {USAGE_SCOPES.map(s => (
            <button
              key={s.id}
              onClick={() => setActorUsage({ scope: s.id })}
              style={{
                textAlign: 'left', padding: '11px 14px', borderRadius: 12, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: 10,
                background: actorUsage.scope === s.id ? 'rgba(124,58,255,0.15)' : 'var(--color-bg-card)',
                border: actorUsage.scope === s.id
                  ? '1px solid var(--color-brand-400, #c084fc)'
                  : '1px solid var(--color-border)',
                color: 'var(--color-text-primary)',
              }}
            >
              <span style={{ fontSize: 20 }}>{s.emoji}</span>
              <span>
                <span style={{ fontWeight: 700, fontSize: '0.85rem', display: 'block' }}>{s.label}</span>
                <span style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)' }}>{s.desc}</span>
              </span>
            </button>
          ))}
        </div>

        {/* 의상 — 얼굴만 모드에서는 사진 의상을 유지할 대상이 없어 비활성 */}
        <div style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', marginBottom: 5 }}>의상</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
          {USAGE_OUTFITS.map(o => (
            <button
              key={o.id}
              className={clsx('btn btn-sm', actorUsage.outfit === o.id ? 'btn-primary' : 'btn-outline')}
              style={{ flex: 1, fontSize: '0.75rem', opacity: actorUsage.scope === 'face' && o.id === 'keep' ? 0.4 : 1 }}
              disabled={actorUsage.scope === 'face' && o.id === 'keep'}
              onClick={() => setActorUsage({ outfit: o.id })}
            >
              {o.label}
            </button>
          ))}
        </div>

        {/* 배경 */}
        <div style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', marginBottom: 5 }}>배경</div>
        <div style={{ display: 'flex', gap: 6 }}>
          {USAGE_BACKGROUNDS.map(b => (
            <button
              key={b.id}
              className={clsx('btn btn-sm', actorUsage.background === b.id ? 'btn-primary' : 'btn-outline')}
              style={{ flex: 1, fontSize: '0.75rem' }}
              onClick={() => setActorUsage({ background: b.id })}
            >
              {b.label}
            </button>
          ))}
        </div>
      </div>

      {/* 동의 게이트 */}
      <div style={{ marginBottom: 28 }}>
        <ConsentGate
          checked={consent}
          onChange={(idx, val) => setConsent(prev => {
            const next = [...prev] as [boolean, boolean]
            next[idx] = val
            return next
          })}
        />
      </div>

      {/* 인물별 대사 음성 설정 (성별/연령대/톤 — 모든 씬에서 이 인물의 목소리로 일관되게 쓰인다) */}
      {voiceConfigPersons ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className="card"
          style={{ marginBottom: 12 }}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
            <span style={{ fontWeight: 700, fontSize: '0.875rem' }}>배우 설정</span>
          </div>
          <p style={{ fontSize: '0.78rem', color: 'var(--color-text-muted)', marginBottom: 14 }}>
            인물별로 대사를 읽어줄 목소리를 골라주세요. 지정 안 하면 기본 목소리로 진행돼요.
            자동으로 잘못 뽑힌 인물이 있다면 "배우 제외"를 체크해 빼주세요.
            바디·의상 컨셉을 고르면 사진 속 실제 모습 대신 그 컨셉으로 그려져요. 지정 안 하면 사진 그대로 사용해요.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {voiceConfigPersons.map(p => {
              const excluded = excludedPersonIds.has(p.id)
              return (
                <div key={p.id} style={{ display: 'flex', flexDirection: 'column', gap: 8, opacity: excluded ? 0.45 : 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      {p.cropUrl && (
                        <img src={p.cropUrl} alt="" style={{ width: 28, height: 28, borderRadius: '50%', objectFit: 'cover' }} />
                      )}
                      <strong style={{ fontSize: '0.8rem', textDecoration: excluded ? 'line-through' : 'none' }}>{p.label}</strong>
                    </div>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', flexShrink: 0 }}>
                      <input
                        type="checkbox"
                        checked={excluded}
                        onChange={() => toggleExcludePerson(p.id)}
                      />
                      <span style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)' }}>배우 제외</span>
                    </label>
                  </div>
                  {!excluded && (
                    <>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {GENDER_OPTIONS.map(g => (
                          <button
                            key={g.id}
                            className={clsx('chip', (p.gender ?? 'unknown') === g.id && 'selected')}
                            onClick={() => updateVoicePerson(p.id, { gender: g.id })}
                            style={{ fontSize: '0.72rem', padding: '5px 10px' }}
                          >
                            {g.label}
                          </button>
                        ))}
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {AGE_BAND_OPTIONS.map(a => (
                          <button
                            key={a.id}
                            className={clsx('chip', (p.ageBand ?? 'adult') === a.id && 'selected')}
                            onClick={() => updateVoicePerson(p.id, { ageBand: a.id })}
                            style={{ fontSize: '0.72rem', padding: '5px 10px' }}
                          >
                            {a.label}
                          </button>
                        ))}
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {VOICE_STYLE_OPTIONS.map(v => (
                          <button
                            key={v.id}
                            className={clsx('chip', (p.voiceStyle ?? 'calm') === v.id && 'selected')}
                            onClick={() => updateVoicePerson(p.id, { voiceStyle: v.id })}
                            style={{ fontSize: '0.72rem', padding: '5px 10px' }}
                          >
                            {v.label}
                          </button>
                        ))}
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {BODY_CONCEPT_OPTIONS.map(b => (
                          <button
                            key={b.id}
                            className={clsx('chip', (p.bodyConcept ?? 'none') === b.id && 'selected')}
                            onClick={() => updateVoicePerson(p.id, { bodyConcept: b.id })}
                            style={{ fontSize: '0.72rem', padding: '5px 10px' }}
                          >
                            {b.label}
                          </button>
                        ))}
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {OUTFIT_CONCEPT_OPTIONS.map(o => (
                          <button
                            key={o.id}
                            className={clsx('chip', (p.outfitConcept ?? 'none') === o.id && 'selected')}
                            onClick={() => updateVoicePerson(p.id, { outfitConcept: o.id })}
                            style={{ fontSize: '0.72rem', padding: '5px 10px' }}
                          >
                            {o.label}
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              )
            })}
          </div>
          <button className="btn btn-primary btn-full" style={{ marginTop: 16 }} onClick={confirmVoiceConfig}>
            다음
            <ChevronRight size={18} />
          </button>
        </motion.div>
      ) : gateSummary ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className="card"
          style={{ borderColor: 'rgba(245,158,11,0.35)', background: 'rgba(245,158,11,0.06)', marginBottom: 12 }}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
            <AlertCircle size={16} color="var(--color-warning, #f59e0b)" />
            <span style={{ fontWeight: 700, fontSize: '0.875rem' }}>사진 품질을 확인해주세요</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 14 }}>
            {gateSummary.map(g => (
              <div key={g.label} style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)' }}>
                <strong>{g.label}</strong>
                {g.checks.map((c, i) => (
                  <div key={i} style={{ paddingLeft: 8, color: 'var(--color-text-muted)' }}>
                    · {c.messageKo}{c.suggestionKo ? ` ${c.suggestionKo}` : ''}
                  </div>
                ))}
              </div>
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <button className="btn btn-outline" onClick={cancelGateSummary}>사진 다시 선택</button>
            <button className="btn btn-primary" onClick={confirmProceedAnyway}>계속 진행</button>
          </div>
        </motion.div>
      ) : noPersonConfirm ? (
        <motion.div
          initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className="card"
          style={{ borderColor: 'rgba(239,68,68,0.35)', background: 'rgba(239,68,68,0.06)', marginBottom: 12 }}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
            <AlertCircle size={16} color="var(--color-error)" />
            <span style={{ fontWeight: 700, fontSize: '0.875rem' }}>사진에서 주인공을 찾지 못했어요</span>
          </div>
          <p style={{ fontSize: '0.8rem', color: 'var(--color-text-secondary)', lineHeight: 1.5, marginBottom: 14 }}>
            사진에서 인물이 감지되지 않았거나, 박스를 탭해 주인공으로 선택한 인물이 없어요.
            이대로 진행하면 이 사진 속 사람이 반영되지 않고 일반적인 장면으로만 영상이 만들어져요.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <button className="btn btn-outline" onClick={() => setNoPersonConfirm(false)}>사진 다시 선택</button>
            <button className="btn btn-primary" onClick={confirmNoPerson}>인물 없이 계속</button>
          </div>
        </motion.div>
      ) : (
        <motion.button
          className="btn btn-primary btn-full btn-lg"
          disabled={!canProceed || !headcountCheck.ok || isBuildingPersons}
          onClick={handleNext}
          whileTap={{ scale: 0.98 }}
        >
          {isBuildingPersons ? (
            <>
              <div className="animate-spin" style={{ width: 16, height: 16, border: '2px solid rgba(255,255,255,0.3)', borderTopColor: '#fff', borderRadius: '50%' }} />
              인물 정보 만드는 중...
            </>
          ) : (
            <>
              컨셉 선택하기
              <ChevronRight size={18} />
            </>
          )}
        </motion.button>
      )}

    </div>
  )
}

// 스텝 인디케이터
function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 24 }}>
      {[...Array(total)].map((_, i) => (
        <div
          key={i}
          style={{
            height: 3, flex: 1, borderRadius: 2,
            background: i < current
              ? 'var(--gradient-brand)'
              : i === current
              ? 'linear-gradient(90deg, var(--color-brand-500), var(--color-border-strong))'
              : 'var(--color-border)',
            transition: 'all 0.3s',
          }}
        />
      ))}
    </div>
  )
}
