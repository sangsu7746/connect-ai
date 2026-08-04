import {
  SHOT_TYPES, CAMERA_MOVES, SUBJECT_ROLES, TRANSITIONS, PACINGS,
  EMOTION_BEAT_MAX, OVERALL_ARC_MAX,
} from '../types/homage'
import type { HomageScene, HomageStructure } from '../types/homage'

/** 최소 씬 수 — 이보다 적으면 광고 서사가 성립하지 않는다 */
const MIN_SCENES = 3
/** 최대 씬 수 — LLM 이 폭주했을 때의 상한 */
const MAX_SCENES = 24
const DEFAULT_SCENE_SEC = 3

function pickEnum<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : fallback
}

function clampText(value: unknown, max: number): string {
  if (typeof value !== 'string') return ''
  return value.trim().slice(0, max)
}

/**
 * LLM 이 돌려준 원시 응답을 신뢰할 수 있는 HomageStructure 로 정제한다.
 *
 * ⚠️ 저작권 가드레일 2단계: 여기서 **스키마에 없는 필드를 전부 버린다**.
 *    타입 정의만으로는 런타임에 아무것도 막지 못한다 — LLM 이 dialogue·brandName 같은
 *    필드를 끼워 넣으면 그대로 저장되고 프롬프트로 흘러간다. 화이트리스트 방식으로
 *    필요한 키만 새 객체에 옮겨 담아 원본 표현이 새어나갈 경로를 끊는다.
 */
export function sanitizeHomageStructure(raw: unknown): HomageStructure {
  if (!raw || typeof raw !== 'object') {
    throw new Error('오마주 구조를 읽지 못했어요. 다시 시도해주세요.')
  }
  const obj = raw as Record<string, unknown>

  if (!Array.isArray(obj.scenes)) {
    throw new Error('오마주 구조를 읽지 못했어요 (씬 목록 없음).')
  }

  const scenes: HomageScene[] = obj.scenes
    .slice(0, MAX_SCENES)
    .filter(s => s && typeof s === 'object')
    .map((s, i) => {
      const src = s as Record<string, unknown>
      const dur = Number(src.durationSec)
      // 화이트리스트 — 여기 없는 키는 전부 버려진다
      return {
        seq: i + 1,
        durationSec: Number.isFinite(dur) && dur > 0 ? Math.round(dur * 10) / 10 : DEFAULT_SCENE_SEC,
        shotType: pickEnum(src.shotType, SHOT_TYPES, 'medium'),
        cameraMove: pickEnum(src.cameraMove, CAMERA_MOVES, 'static'),
        subjectRole: pickEnum(src.subjectRole, SUBJECT_ROLES, 'product'),
        emotionBeat: clampText(src.emotionBeat, EMOTION_BEAT_MAX),
        transition: pickEnum(src.transition, TRANSITIONS, 'cut'),
      }
    })

  if (scenes.length < MIN_SCENES) {
    throw new Error(`오마주 구조의 씬이 너무 적어요 (${scenes.length}개). 다른 영상을 골라주세요.`)
  }

  return {
    scenes,
    pacing: pickEnum(obj.pacing, PACINGS, 'medium'),
    overallArc: clampText(obj.overallArc, OVERALL_ARC_MAX),
  }
}

/**
 * Gemini 에 넘길 스키마 설명. 응답 형식을 고정해 파싱 실패를 줄인다.
 * 마지막 문장이 저작권 가드레일 1단계(프롬프트 수준)다 — 실제 차단은
 * sanitizeHomageStructure 가 하지만, 애초에 안 뱉게 하는 편이 낫다.
 */
export const HOMAGE_JSON_SCHEMA_HINT = `
Return ONLY valid JSON with this exact shape:
{
  "scenes": [
    {
      "seq": 1,
      "durationSec": 2.5,
      "shotType": "wide|medium|close|extreme_close|insert|text_card",
      "cameraMove": "static|pan|tilt|push_in|pull_out|handheld|orbit",
      "subjectRole": "product|person|environment|text|abstract",
      "emotionBeat": "short Korean phrase describing the emotional beat, max 40 chars",
      "transition": "cut|dissolve|wipe|match_cut"
    }
  ],
  "pacing": "slow|medium|fast|accelerating",
  "overallArc": "one-line Korean summary of the narrative arc, max 80 chars"
}

CRITICAL: Describe STRUCTURE ONLY — shot grammar, pacing, emotional progression.
Do NOT transcribe or paraphrase any spoken dialogue, on-screen text, subtitles,
brand names, product names, slogans, or logos. Those fields do not exist in the
schema and any such content will be discarded.
`.trim()
