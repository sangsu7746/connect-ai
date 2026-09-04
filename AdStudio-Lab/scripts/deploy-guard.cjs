#!/usr/bin/env node
/**
 * AdStudio-Lab 오배포 가드 (firebase.json 의 predeploy 훅에서 호출된다).
 *
 * 왜 필요한가:
 * 이 저장소는 firebase.json 의 functions 블록에 codebase 를 지정하지 않아
 * headjim-ai 프로젝트의 공용 'default' 코드베이스를 점유한다. 여기서
 * `firebase deploy --only functions` 를 실행하면 라이브 함수 5개
 * (onUserCreate / corsProxy / edgeTTS / analyzeProduct / generateAd)가
 * 즉시 덮어써지며, 다음이 함께 터진다:
 *   - functions/.env 의 GEMINI_API_KEY 가 비어 있으면 라이브 키가 지워진다
 *   - onUserCreate 의 웰컴 코인 값이 랩 사본 값으로 바뀐다
 *   - corsProxy 의 Bearer 검증이 토큰을 안 보내는 오마주·MemoryFilm
 *     라이브 프론트를 401 로 끊는다
 *
 * 그래서 이 저장소에서 운영 프로젝트로 나가는 모든 배포를 차단한다.
 * 운영 배포는 D:\광고영상-AdStudio 에서만 수행한다.
 *
 * fail-closed: 프로젝트를 판별하지 못하면 통과가 아니라 차단이다.
 * (predeploy 훅이 0이 아닌 코드로 끝나면 firebase-tools 는 배포를 중단한다.)
 */
const target = process.argv[2] || '(unknown)'

const project =
  process.env.GCLOUD_PROJECT ||
  process.env.PROJECT_ID ||
  process.env.FIREBASE_PROJECT ||
  ''

/** 이 저장소에서 절대 배포하면 안 되는 프로젝트 */
const FORBIDDEN = ['headjim-ai']

const line = '='.repeat(66)

if (!project) {
  console.error(`\n${line}`)
  console.error(`[deploy-guard] 프로젝트 ID를 판별할 수 없습니다 (target=${target}).`)
  console.error(`[deploy-guard] 안전을 위해 배포를 중단합니다. --project 를 명시하세요.`)
  console.error(`${line}\n`)
  process.exit(1)
}

if (FORBIDDEN.includes(project)) {
  console.error(`\n${line}`)
  console.error(`[deploy-guard] 차단: '${project}' 는 운영 프로젝트입니다. (target=${target})`)
  console.error(`[deploy-guard] AdStudio-Lab 은 개발 사본이며 운영 배포 권한이 없습니다.`)
  console.error(`[deploy-guard]`)
  console.error(`[deploy-guard]   운영 배포는 D:\\광고영상-AdStudio 에서만 수행하세요.`)
  console.error(`[deploy-guard]   이 저장소의 functions 는 라이브 5개 함수를 덮어씁니다.`)
  console.error(`${line}\n`)
  process.exit(1)
}

console.log(`[deploy-guard] OK — project='${project}', target='${target}'`)
