import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Sparkles, AlertCircle } from 'lucide-react'
import { clsx } from 'clsx'
import { useAdStore } from '../stores/adStore'
import { useProjectStore } from '../stores/projectStore'
import { useUserStore } from '../stores/userStore'
import { generateStoryboardScenes } from '../utils/storyboardGenerator'
import { presentableErrorMessage } from '../utils/errorMessage'
import {
  AD_CATEGORIES, AD_EMPHASIS_GROUPS, AD_STRUCTURES, AD_TONES, AD_VISUAL_STYLES,
  CATEGORY_DEFAULT_STRUCTURE, ANALYSIS_TONE_MAP,
} from '../utils/adConcepts'

// [5] 광고 컨셉 선택 — 4축(카테고리 → 강조 포인트 → 스토리 구성 → 톤&무드).
// 선택한 스토리 구성 id(ad_*)가 project.conceptId로 저장되고, "스토리보드 만들기"를 누르면
// 제품 분석 결과 + 4축 선택이 반영된 광고 씬들이 생성된다 (storyboardGenerator).
export default function A5_Concept() {
  const navigate = useNavigate()
  const { analysis, config, adConcept, setAdConcept } = useAdStore()
  const { currentProject, persons, updateProject, setScenes, saveCurrentProject } = useProjectStore()
  const user = useUserStore(s => s.user)

  const [isGenerating, setIsGenerating] = useState(false)
  const [error, setError] = useState('')

  // 새로고침 등으로 흐름 상태가 없으면 이전 단계로
  useEffect(() => {
    if (!analysis) navigate('/source', { replace: true })
    else if (!currentProject) navigate('/actor', { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Gemini 분석 톤 → 광고 톤 기본값 (아직 톤을 고르지 않았을 때 1회)
  useEffect(() => {
    if (analysis && !adConcept.tone) {
      setAdConcept({ tone: ANALYSIS_TONE_MAP[analysis.tone] || 'energetic' })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!analysis || !currentProject) return null

  const selectedCategory = AD_CATEGORIES.find(c => c.id === adConcept.categoryMain)

  const pickCategory = (id: string) => {
    setAdConcept({
      categoryMain: id,
      categorySub: '',
      // 카테고리에 맞는 기본 스토리 구성 추천 (아직 직접 고르지 않았을 때만)
      ...(adConcept.structureId ? {} : { structureId: CATEGORY_DEFAULT_STRUCTURE[id] || 'ad_problem' }),
    })
  }

  const toggleEmphasis = (id: string) => {
    const has = adConcept.emphasis.includes(id)
    if (has) {
      setAdConcept({ emphasis: adConcept.emphasis.filter(e => e !== id) })
    } else if (adConcept.emphasis.length < 2) {
      setAdConcept({ emphasis: [...adConcept.emphasis, id] })
    }
  }

  const canProceed = adConcept.structureId !== '' && adConcept.categoryMain !== ''

  const handleBuildStoryboard = async () => {
    if (!canProceed) {
      setError('카테고리와 스토리 구성을 선택해주세요.')
      return
    }
    setError('')
    setIsGenerating(true)
    try {
      const isHomage = adConcept.structureSource === 'homage'
      const updated = {
        ...currentProject,
        conceptId: adConcept.structureId,
        durationSec: config.duration,
        dialogueMode: 'auto' as const,
        // 설계 §8 "참고 영상 링크 기록" — 완성된 프로젝트에 참고 영상 id를 남겨 저작권 이의 발생 시
        // 추적 가능하게 한다. 템플릿 모드거나 설명 입력(source:'description')으로 만든 오마주는
        // 실제 영상이 없으므로 undefined로 명시해 이전에 남아있던 값(모드 전환 이전)도 정리한다.
        homageVideoId: isHomage ? adConcept.homage?.videoId : undefined,
      }
      updateProject(updated)

      // 제품 분석 + 4축 컨셉이 반영된 광고 씬 생성 (Gemini 키 있으면 창작, 없으면 템플릿 폴백)
      const scenes = await generateStoryboardScenes(updated, persons)
      setScenes(scenes)

      if (user) {
        try {
          await saveCurrentProject(user.uid)
        } catch (e) {
          console.error('프로젝트 저장 실패 (진행은 계속):', e)
        }
      }
      navigate('/storyboard')
    } catch (e) {
      console.error('스토리보드 생성 실패:', e)
      // generateStoryboardScenes가 오마주 모드에서 명시적으로 던지는 안내 메시지(예: "Gemini API
      // 키가 있어야 합니다")는 다음 행동을 알려주므로 그대로 보여준다. 그 외의 원인 불명 예외(런타임
      // 버그·raw 네트워크 오류 등)까지 그대로 노출하면 기술적인 문구가 화면에 뜰 수 있으니, 사용자에게
      // 보여줄 만한 형태(짧고 한국어 문장)일 때만 통과시키고 아니면 기존 범용 문구로 폴백한다.
      // 템플릿 모드는 대부분의 실패를 이 함수 내부에서 이미 조용히 템플릿 폴백으로 처리하므로
      // (Gemini 실패 시 콘솔 경고만 남기고 계속 진행) 이 catch까지 도달하는 경우가 드물어
      // 기존 동작(범용 문구)이 그대로 유지된다.
      setError(presentableErrorMessage(e, '스토리보드 생성에 실패했어요. 잠시 후 다시 시도해주세요.'))
    } finally {
      setIsGenerating(false)
    }
  }

  const sectionLabel: React.CSSProperties = {
    fontWeight: 800, fontSize: '0.95rem', marginBottom: 10, display: 'block',
  }

  return (
    <div style={{ padding: '20px 16px', paddingBottom: 100 }}>
      {/* 진행 중인 광고 요약 */}
      <div style={{
        padding: '10px 14px', borderRadius: 10, marginBottom: 18,
        background: 'rgba(124,58,255,0.10)', border: '1px solid var(--color-border)',
        fontSize: '0.8rem', color: 'var(--color-text-muted)',
      }}>
        광고 대상: <strong style={{ color: 'var(--color-text-primary)' }}>{analysis.productName}</strong>
        {' · '}{config.duration}초
      </div>

      {/* 축 1. 카테고리 */}
      <label style={sectionLabel}>1. 광고 카테고리</label>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        {AD_CATEGORIES.map(c => (
          <button
            key={c.id}
            className={clsx('btn btn-sm', adConcept.categoryMain === c.id ? 'btn-primary' : 'btn-outline')}
            onClick={() => pickCategory(c.id)}
          >
            {c.emoji} {c.label}
          </button>
        ))}
      </div>
      {selectedCategory && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 20 }}>
          {selectedCategory.subs.map(s => (
            <button
              key={s.id}
              className={clsx('btn btn-sm', adConcept.categorySub === s.id ? 'btn-primary' : 'btn-ghost')}
              style={{ fontSize: '0.75rem' }}
              onClick={() => setAdConcept({ categorySub: s.id })}
            >
              {s.label}
            </button>
          ))}
        </div>
      )}

      {/* 축 2. 강조 포인트 */}
      <label style={sectionLabel}>
        2. 강조 포인트 <span style={{ fontWeight: 400, fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>(최대 2개)</span>
      </label>
      <div style={{ marginBottom: 20 }}>
        {AD_EMPHASIS_GROUPS.map(g => (
          <div key={g.label} style={{ marginBottom: 8 }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', marginBottom: 4 }}>{g.label}</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {g.items.map(item => {
                const selected = adConcept.emphasis.includes(item.id)
                const disabled = !selected && adConcept.emphasis.length >= 2
                return (
                  <button
                    key={item.id}
                    className={clsx('btn btn-sm', selected ? 'btn-primary' : 'btn-outline')}
                    style={{ fontSize: '0.75rem', opacity: disabled ? 0.45 : 1 }}
                    onClick={() => toggleEmphasis(item.id)}
                  >
                    {item.label}
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {/* 축 3. 스토리 구성 */}
      <label style={sectionLabel}>3. 스토리 구성</label>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <button
          className={clsx('btn btn-sm', adConcept.structureSource !== 'homage' ? 'btn-primary' : 'btn-outline')}
          onClick={() => setAdConcept(
            // 오마주 → 템플릿으로 실제로 전환할 때만 이전 선택(homage/structureId)을 지운다.
            // 이미 템플릿 모드인데 이 버튼(이미 활성 상태로 보임)을 다시 눌러도 사용자가 고른
            // structureId가 조용히 지워져 canProceed가 꺼지는 일이 없어야 한다.
            adConcept.structureSource === 'homage'
              ? { structureSource: 'template', homage: undefined, structureId: '' }
              : { structureSource: 'template' }
          )}
        >
          템플릿에서 고르기
        </button>
        <button
          className={clsx('btn btn-sm', adConcept.structureSource === 'homage' ? 'btn-primary' : 'btn-outline')}
          onClick={() => navigate('/reference')}
        >
          유튜브 오마주
        </button>
      </div>

      {adConcept.structureSource === 'homage' && adConcept.homage && (
        <div style={{ padding: 12, borderRadius: 8, background: 'rgba(124,58,255,0.10)', marginBottom: 12 }}>
          <strong style={{ fontSize: 13 }}>
            {adConcept.homage.title || (adConcept.homage.source === 'description' ? '내가 설명한 느낌' : '선택한 영상')}
          </strong>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '4px 0 0' }}>
            {adConcept.homage.structure.scenes.length}씬 · {adConcept.homage.structure.pacing} 페이싱
            {adConcept.homage.structure.overallArc ? ` · ${adConcept.homage.structure.overallArc}` : ''}
          </p>
          <button className="btn btn-sm btn-outline" style={{ marginTop: 8 }} onClick={() => navigate('/reference')}>
            레퍼런스 바꾸기
          </button>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
        {adConcept.structureSource !== 'homage' && AD_STRUCTURES.map(s => (
          <button
            key={s.id}
            onClick={() => setAdConcept({ structureId: s.id })}
            style={{
              textAlign: 'left', padding: '12px 14px', borderRadius: 12, cursor: 'pointer',
              background: adConcept.structureId === s.id ? 'rgba(124,58,255,0.15)' : 'var(--color-bg-card)',
              border: adConcept.structureId === s.id
                ? '1px solid var(--color-brand-400, #c084fc)'
                : '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            <div style={{ fontWeight: 700, fontSize: '0.88rem', marginBottom: 3 }}>
              {s.emoji} {s.label}
              <span style={{ fontWeight: 400, fontSize: '0.7rem', color: 'var(--color-text-muted)', marginLeft: 8 }}>
                {s.goodFor}
              </span>
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>{s.flow}</div>
          </button>
        ))}
      </div>

      {/* 축 4. 톤 & 무드 */}
      <label style={sectionLabel}>4. 톤 & 무드</label>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 20 }}>
        {AD_TONES.map(t => (
          <button
            key={t.id}
            className={clsx('btn btn-sm', adConcept.tone === t.id ? 'btn-primary' : 'btn-outline')}
            onClick={() => setAdConcept({ tone: t.id })}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 축 5. 비주얼 스타일 — 조명·질감의 방향. 어두운 룩도 여기서 "선택"으로 고를 수 있다 */}
      <label style={sectionLabel}>5. 비주얼 스타일</label>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
        {AD_VISUAL_STYLES.map(v => (
          <button
            key={v.id}
            onClick={() => setAdConcept({ visualStyle: v.id })}
            style={{
              textAlign: 'left', padding: '10px 14px', borderRadius: 12, cursor: 'pointer',
              background: adConcept.visualStyle === v.id ? 'rgba(124,58,255,0.15)' : 'var(--color-bg-card)',
              border: adConcept.visualStyle === v.id
                ? '1px solid var(--color-brand-400, #c084fc)'
                : '1px solid var(--color-border)',
              color: 'var(--color-text-primary)',
            }}
          >
            <span style={{ fontWeight: 700, fontSize: '0.85rem' }}>{v.label}</span>
            <span style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', marginLeft: 8 }}>
              {v.desc}
            </span>
          </button>
        ))}
      </div>
      <p style={{ fontSize: '0.72rem', color: 'var(--color-text-muted)', marginBottom: 24 }}>
        어떤 룩을 골라도 제품·로고는 또렷하게 보이도록 제작돼요.
      </p>

      {error && (
        <div style={{
          marginBottom: 14, padding: '10px 12px', borderRadius: 10, display: 'flex', gap: 8,
          alignItems: 'flex-start', background: 'rgba(255,90,90,0.08)',
          border: '1px solid rgba(255,90,90,0.35)', fontSize: '0.82rem',
        }}>
          <AlertCircle size={15} color="#ff5a5a" style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{error}</span>
        </div>
      )}

      <button
        className="btn btn-primary btn-lg"
        style={{ width: '100%' }}
        disabled={!canProceed || isGenerating}
        onClick={handleBuildStoryboard}
      >
        <Sparkles size={17} /> {isGenerating ? '광고 스토리보드 창작 중…' : '스토리보드 만들기'}
      </button>
      {isGenerating && (
        <p style={{ marginTop: 10, fontSize: '0.78rem', color: 'var(--color-text-muted)', textAlign: 'center' }}>
          제품 분석과 선택한 컨셉을 반영해 기승전결 씬을 창작하고 있어요 (약 10초)
        </p>
      )}
    </div>
  )
}
