import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { projectService } from '../services/projectService'
import { useUserStore } from './userStore'
import type {
  Project, Scene, Photo, Person, StoryboardMeta,
  Relation, Genre, StyleId, DialogueMode,
  Lane, RenderResult, ProjectStatus, FreeAiProvider, ProviderKey
} from '../types'

// 무료 플랜에서 클라우드에 저장할 수 있는 최대 프로젝트 수 — 일반/프로는 무제한
export const FREE_PROJECT_LIMIT = 3

/** 무료 플랜 저장 한도를 넘어 새 프로젝트를 저장하려 할 때 던지는 전용 에러 */
export class ProjectLimitError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ProjectLimitError'
  }
}

interface ProjectState {
  currentProject: Project | null
  projects: Project[]
  photos: Photo[]
  persons: Person[]
  storyboard: StoryboardMeta | null
  scenes: Scene[]
  selectedLane: Lane
  selectedGenre: Genre
  // 무료 AI 영상 레인의 품질 선택 — kaggle_ltx(저품질·느림·무료·워터마크) vs alibaba(중품질·P 1,000)
  freeAiProvider: FreeAiProvider
  // 고퀄(premium) 레인에서 사용자가 직접 고른 영상 제공자. null이면 씬별 자동 라우팅.
  premiumProvider: ProviderKey | null
  // 이번 제작 건의 인가 기록 — cost 0은 무료 슬롯 통과(무빙포토 일일 무료), 양수는 포인트 결제.
  // S5 재시도 시 이중 차감을 막고, 전체 실패 시 되돌릴 대상(환급/무료 슬롯 복원)을 추적하는 데 쓴다.
  pointPayment: { refId: string; cost: number } | null

  // actions
  createProject: () => void
  updateProject: (patch: Partial<Project>) => void
  setPhotos: (photos: Photo[]) => void
  setPersons: (persons: Person[]) => void
  setStoryboard: (sb: StoryboardMeta) => void
  setScenes: (scenes: Scene[]) => void
  updateScene: (id: string, patch: Partial<Scene>) => void
  reorderScenes: (orderedIds: string[]) => void
  setSelectedLane: (lane: Lane) => void
  setSelectedGenre: (genre: Genre) => void
  setFreeAiProvider: (provider: FreeAiProvider) => void
  setPremiumProvider: (provider: ProviderKey | null) => void
  setPointPayment: (payment: { refId: string; cost: number } | null) => void
  addRender: (render: RenderResult) => void
  resetProject: () => void

  // Firestore actions
  saveCurrentProject: (userId: string) => Promise<void>
  loadProjects: (userId: string) => Promise<void>
  loadProjectDetails: (projectId: string) => Promise<boolean>
}

const defaultProject = (): Project => ({
  id: crypto.randomUUID(),
  userId: '',
  status: 'draft',
  relation: 'solo',
  conceptId: '',
  styleId: 'cinematic',
  durationSec: 15,
  dialogueMode: 'auto',
  aspect: '9:16',
  createdAt: new Date(),
})

export const useProjectStore = create<ProjectState>()(
  persist(
    (set, get) => ({
      currentProject: null,
      projects: [],
      photos: [],
      persons: [],
      storyboard: null,
      scenes: [],
      selectedLane: 'moving_photo',
      selectedGenre: 'film',
      freeAiProvider: 'alibaba',
      premiumProvider: null,
      pointPayment: null,

      createProject: () => {
        const project = defaultProject()
        set({ currentProject: project, photos: [], persons: [], storyboard: null, scenes: [], pointPayment: null })
      },

      updateProject: (patch) => set(state => ({
        currentProject: { ...(state.currentProject ?? defaultProject()), ...patch }
      })),

      setPhotos: (photos) => set({ photos }),
      setPersons: (persons) => set({ persons }),
      setStoryboard: (storyboard) => set({ storyboard }),
      setScenes: (scenes) => set({ scenes }),

      updateScene: (id, patch) => set(state => ({
        scenes: state.scenes.map(s => s.id === id ? { ...s, ...patch } : s)
      })),

      reorderScenes: (orderedIds) => set(state => {
        const map = new Map(state.scenes.map(s => [s.id, s]))
        const reordered = orderedIds
          .map((id, i) => ({ ...map.get(id)!, seq: i + 1 }))
          .filter(Boolean)
        return { scenes: reordered }
      }),

      setSelectedLane: (selectedLane) => set({ selectedLane }),
      setSelectedGenre: (selectedGenre) => set({ selectedGenre }),
      setFreeAiProvider: (freeAiProvider) => set({ freeAiProvider }),
      setPremiumProvider: (premiumProvider) => set({ premiumProvider }),
      setPointPayment: (pointPayment) => set({ pointPayment }),

      addRender: (render) => set(state => ({
        currentProject: {
          ...(state.currentProject ?? defaultProject()),
          renders: [...(state.currentProject?.renders ?? []), render],
          status: 'done'
        }
      })),

      resetProject: () => set({
        currentProject: null, photos: [], persons: [],
        storyboard: null, scenes: [], pointPayment: null
      }),

      // ── Firestore 동기화 액션 ──
      saveCurrentProject: async (userId) => {
        const { currentProject, scenes, photos, projects } = get()
        if (!currentProject || !userId) return

        // 이미 한 번이라도 저장된 적 있는 프로젝트(같은 id)의 갱신은 한도와 무관하게 항상 허용한다 —
        // 한도는 "새 프로젝트를 몇 개까지 만들 수 있는가"에만 적용된다
        const isNewProject = !projects.some(p => p.id === currentProject.id)
        if (isNewProject && !useUserStore.getState().hasBasicOrAbove() && projects.length >= FREE_PROJECT_LIMIT) {
          throw new ProjectLimitError(
            `프로젝트는 최대 ${FREE_PROJECT_LIMIT}개까지 저장할 수 있어요. 기존 프로젝트를 정리한 뒤 다시 시도해주세요.`
          )
        }

        await projectService.saveProject(userId, currentProject, scenes, photos)
        // 로컬 리스트 업데이트
        const updatedList = await projectService.loadProjects(userId)
        set({ projects: updatedList })
      },

      loadProjects: async (userId) => {
        if (!userId) return
        const list = await projectService.loadProjects(userId)
        set({ projects: list })
      },

      loadProjectDetails: async (projectId) => {
        const details = await projectService.getProjectDetails(projectId)
        if (!details) return false
        set({
          currentProject: details.project,
          scenes: details.scenes,
          photos: details.photos,
          selectedLane: details.project.selectedLane ?? 'moving_photo',
          selectedGenre: details.project.selectedGenre ?? 'film'
        })
        return true
      }
    }),
    { name: 'memoryframe-project', partialize: (s) => ({ projects: s.projects }) }
  )
)
