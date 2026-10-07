import { db } from './firebase'
import { doc, setDoc, getDoc, collection, query, where, getDocs, orderBy, writeBatch } from 'firebase/firestore'
import type { Project, Scene, Photo } from '../types'

/** 사진의 base64 원본을 "내 작업" 목록 썸네일용 소형(약 200px) 이미지로 축소한다. 실패해도 치명적이지 않으므로 조용히 빈 문자열을 반환한다. */
function buildThumbnail(dataUrl: string, maxPx = 200): Promise<string> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const ratio = Math.min(1, maxPx / Math.max(img.width, img.height))
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(img.width * ratio))
      canvas.height = Math.max(1, Math.round(img.height * ratio))
      canvas.getContext('2d')!.drawImage(img, 0, 0, canvas.width, canvas.height)
      resolve(canvas.toDataURL('image/jpeg', 0.6))
    }
    img.onerror = () => resolve('')
    img.src = dataUrl
  })
}

export const projectService = {
  /**
   * 프로젝트 메타데이터와 씬 리스트를 저장합니다. 사진 원본(base64 데이터)은 프로젝트 문서에
   * 함께 담지 않는다 — Firestore 문서 하나의 1MB 한도를 사진 몇 장만으로도 넘기기 쉽기 때문에,
   * 원본은 사진별 서브컬렉션 문서(`projects/{id}/photos/{photoId}`)로 분리해 한도가 "사진
   * 개수"가 아니라 "사진 1장" 기준이 되게 한다. 목록 화면 썸네일은 별도의 작은 이미지로 만들어
   * 프로젝트 문서에 직접 남겨, 목록 조회 시 서브컬렉션을 추가로 읽지 않아도 되게 한다.
   */
  async saveProject(userId: string, project: Project, scenes: Scene[], photos: Photo[]): Promise<void> {
    if (!userId) return
    const docRef = doc(db, 'projects', project.id)

    // File 객체·원본 이미지 데이터를 제외하고 가벼운 메타데이터만 저장
    const photoMeta = photos.map(p => ({
      id: p.id,
      width: p.width,
      height: p.height,
      faces: p.faces ?? []
    }))

    const thumbUrl = photos[0]?.previewUrl ? await buildThumbnail(photos[0].previewUrl) : project.thumbUrl

    // Firestore에 저장 가능한 형태로 직렬화 (undefined 제거)
    const docData = JSON.parse(JSON.stringify({
      ...project,
      userId,
      photos: photoMeta,
      thumbUrl,
      scenes,
    }))

    // Date 객체 복원 및 타임스탬프 저장
    docData.updatedAt = new Date()
    if (project.createdAt) {
      docData.createdAt = project.createdAt instanceof Date ? project.createdAt : new Date(project.createdAt)
    }

    await setDoc(docRef, docData, { merge: true })

    if (photos.length > 0) {
      const batch = writeBatch(db)
      for (const p of photos) {
        batch.set(doc(db, 'projects', project.id, 'photos', p.id), { userId, previewUrl: p.previewUrl }, { merge: true })
      }
      await batch.commit()
    }
  },

  /**
   * 사용자의 모든 프로젝트 목록을 불러옵니다.
   */
  async loadProjects(userId: string): Promise<Project[]> {
    if (!userId) return []
    const q = query(
      collection(db, 'projects'),
      where('userId', '==', userId),
      orderBy('createdAt', 'desc')
    )

    try {
      const snap = await getDocs(q)
      const list: Project[] = []
      snap.forEach(doc => {
        const data = doc.data()
        list.push({
          ...data,
          id: doc.id,
          createdAt: data.createdAt?.toDate ? data.createdAt.toDate() : new Date(data.createdAt),
          updatedAt: data.updatedAt?.toDate ? data.updatedAt.toDate() : undefined,
        } as any as Project)
      })
      return list
    } catch (e) {
      console.error('Failed to load projects from Firestore:', e)
      // 만약 인덱스 생성이 덜 되었거나 오류가 나면 단일 필드 쿼리 후 메모리 정렬 폴백
      try {
        const fallbackQ = query(
          collection(db, 'projects'),
          where('userId', '==', userId)
        )
        const fallbackSnap = await getDocs(fallbackQ)
        const list: Project[] = []
        fallbackSnap.forEach(doc => {
          const data = doc.data()
          list.push({
            ...data,
            id: doc.id,
            createdAt: data.createdAt?.toDate ? data.createdAt.toDate() : new Date(data.createdAt),
            updatedAt: data.updatedAt?.toDate ? data.updatedAt.toDate() : undefined,
          } as any as Project)
        })
        return list.sort((a, b) => b.createdAt.getTime() - a.createdAt.getTime())
      } catch (err) {
        console.error('Firestore fallback query failed:', err)
        return []
      }
    }
  },

  /**
   * 특정 프로젝트의 상세 내용(씬, 사진 포함)을 불러옵니다.
   */
  async getProjectDetails(projectId: string): Promise<{ project: Project; scenes: Scene[]; photos: Photo[] } | null> {
    const docRef = doc(db, 'projects', projectId)
    const snap = await getDoc(docRef)
    if (!snap.exists()) return null

    const data = snap.data()
    const project = {
      ...data,
      id: snap.id,
      createdAt: data.createdAt?.toDate ? data.createdAt.toDate() : new Date(data.createdAt),
      updatedAt: data.updatedAt?.toDate ? data.updatedAt.toDate() : undefined,
    } as any as Project

    const scenes = (data.scenes ?? []) as Scene[]
    const photoMeta = (data.photos ?? []) as Photo[]

    // 사진 원본(previewUrl)은 서브컬렉션에서 따로 읽어와 메타데이터와 합친다
    let photos = photoMeta
    if (photoMeta.length > 0) {
      const photosSnap = await getDocs(collection(db, 'projects', projectId, 'photos'))
      const previewUrlById = new Map<string, string>()
      photosSnap.forEach(d => previewUrlById.set(d.id, (d.data() as { previewUrl?: string }).previewUrl ?? ''))
      photos = photoMeta.map(p => ({ ...p, previewUrl: previewUrlById.get(p.id) ?? '' }))
    }

    return { project, scenes, photos }
  }
}
