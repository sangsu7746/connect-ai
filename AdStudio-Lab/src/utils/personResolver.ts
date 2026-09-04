import type { Scene, Person, Photo } from '../types'

/**
 * scene.subjectRefs(스토리보드 템플릿의 'person_1' 같은 라벨 문자열)를 실제 Person 객체로 해석한다.
 * id 매칭을 우선하고, 없으면 label로 대체 매칭한다(현재 subjectRefs는 label 규칙을 그대로 쓴다).
 */
export function resolveSceneSubjects(scene: Scene, persons: Person[]): Person[] {
  return scene.subjectRefs
    .map(ref => persons.find(p => p.id === ref) ?? persons.find(p => p.label === ref))
    .filter((p): p is Person => !!p)
}

/**
 * 두 명 이상의 인물이 같은 원본 사진에서 추출됐다면 그 원본 사진을 반환한다.
 * (커플·단체 씬에서 개별 인물 크롭 하나만 쓰면 나머지 인물이 화면에서 사라지므로,
 * 가능하면 실제 구도가 담긴 원본 사진을 우선한다.)
 */
export function findSharedSourcePhoto(subjects: Person[], photos: Photo[]): Photo | null {
  if (subjects.length < 2) return null
  const first = subjects[0].sourcePhotoId
  if (!first) return null
  const allSame = subjects.every(p => p.sourcePhotoId === first)
  if (!allSame) return null
  return photos.find(ph => ph.id === first) ?? null
}
