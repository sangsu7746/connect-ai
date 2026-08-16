# 블로그 리뉴얼 릴스 제작기 — 설계서

날짜: 2026-08-15
상태: 사용자 설계 승인 완료 (섹션 1~3 개별 승인)
경로: `D:\블로그 리뉴얼 릴스 제작기`

## 1. 개요

네이버 블로그 검색 상위 글을 카테고리별로 수집·분석하고, 그 내용을 종합 재구성한 대본과
Stable Diffusion(ComfyUI) 생성 이미지로 릴스(9:16)와 롱폼 모션영상(16:9, 1/3/5/10분)을
자동 제작하는 로컬 웹앱. 전 구간이 이 PC에서 무료로 동작한다(네이버 API·ComfyUI·Edge-TTS·네이티브 ffmpeg).

대본에는 보랏빛소(Purple Cow) 진단·지침과 GEO(생성형 검색 최적화) 방식을 적용한다.

## 2. 확정 요구사항

| 항목 | 결정 |
|---|---|
| 블로그 소스 | 네이버 블로그 검색 상위 글 + 구글 검색 상위 블로그 글(티스토리·브런치 등) |
| 카테고리 | DataLab 트렌드 자동 (시드 키워드 풀 + 상승률 순위화, UI에서 시드 편집 가능) |
| 리스트 뷰 | 카테고리별 탭으로 보기 + 글마다 보랏빛 점수 배지(0~4) |
| 산출물 | 릴스 9:16 (30/60초) + 롱폼 16:9 (1/3/5/10분) |
| 대본 방식 | 상위 3~5개 글 종합 재구성 (원문 문장 복사 금지, 저작권 안전) |
| 나레이션 | TTS(Edge-TTS) + 자막. 릴스·롱폼 공통 |
| 이미지 | 로컬 SD WebUI(A1111, DreamShaper 8 — 2026-08-16 실환경 확정), 스타일팩 6종, 라이브러리 캐시 |
| 기본 구도 | EstateReels-v2 위저드·씬 구조·자막 스타일 이식 |
| 추가 기능 | 보랏빛 점수 배지, 대본 날조 게이트, GEO 확장(설명란+챕터), 이미지 캐시 — 전부 포함 |
| 배포 | 개인 PC 전용, 배포 안 함 |

## 3. 아키텍처 (승인: A안)

```
[React 웹 UI (Vite, 포트 5175)]
        │ REST + 잡 폴링
[FastAPI 서버 (Python, 포트 8792)]
   ├─ 수집: 네이버 검색 API + DataLab + 구글 CSE(폴백: Playwright)
   ├─ 크롤링: httpx·trafilatura 본문 수집 (jina 폴백)
   ├─ 진단: purple_cow 블로그판 (4문항 → 보랏빛 점수)
   ├─ 대본: Gemini (보랏빛소 지침 + GEO) → guardrails 숫자 대조
   ├─ 이미지: SD WebUI API (기본 127.0.0.1:7860)
   ├─ 음성: Edge-TTS (ko-KR)
   └─ 렌더: 네이티브 ffmpeg
        │
   SQLite (글 리스트·진단·잡 상태·이미지 캐시 인덱스)
```

- 서버가 몸통인 이유: 10분 롱폼(72씬)은 브라우저 ffmpeg.wasm(720p 단일스레드)으로 불가.
  네이티브 ffmpeg + 로컬 ComfyUI + Python 자산(purple_cow, guardrails) 재사용이 전제.
- B안(EstateReels-v2 포크 SPA), C안(HyperFrames)은 검토 후 기각 — 사유: wasm 한계, 이식 비용.

### 프로젝트 구조

```
D:\블로그 리뉴얼 릴스 제작기\
  server\
    main.py               FastAPI 엔트리
    api\                  라우터: categories, discover, posts, analyze,
                          script, images, tts, render, jobs
    core\
      naver.py            검색 API + DataLab 순위화
      crawler.py          모바일 변환·trafilatura·jina 폴백 체인
      purple_cow_blog.py  보랏빛소 블로그판 (원본 이식·각색)
      guardrails.py       숫자 대조 날조 게이트 (원본 이식)
      banned_words.py     금지어 공용 모듈 (단일 출처)
      geo.py              GEO 요약박스·챕터·설명란 생성
      script_gen.py       Gemini 대본 생성 (scene_level 구조)
      sd_webui.py         SD WebUI(A1111) API 클라이언트
      style_packs.json    이미지 스타일팩 정의
      cache.py            이미지 라이브러리 캐시
      tts.py              Edge-TTS 래퍼
      captions.py         Pillow 자막 PNG 렌더
      storyboard.py       씬 테이블·길이 배분
      renderer.py         ffmpeg 2단계 합성
      jobs.py             SQLite 잡 큐
    data\                 SQLite DB, 생성물(images/, audio/, out/)
    tests\
  web\                    React 19 + TS + Vite (EstateReels-v2 구도 이식)
    src\pages\            Dashboard, PostList, Review, Concept,
                          Storyboard, Generate, Result
  .env                    NAVER_CLIENT_ID/SECRET, GOOGLE_CSE_KEY/ID,
                          GEMINI_API_KEY, SD_WEBUI_URL, PUBLISHER_DIR, 포트 설정
```

## 4. 화면 흐름 (7단계 위저드)

1. **카테고리 대시보드** — 기본 6종(부동산·재테크·건강·요리·여행·IT), 추가/편집 가능.
   카테고리마다 DataLab 상승률 기준 "지금 뜨는 키워드 TOP 5" 표시.
2. **블로그 리스트** — 카테고리별 탭. 키워드로 네이버·구글 검색 상위 글 수집,
   글마다 보랏빛 점수 배지 + 소스 배지(N/G) + 제목/요약/원문 링크. 소스 필터
   (전체/네이버/구글) 제공. 영상화할 글 3~5개 선택.
3. **분석 리뷰** — 추출된 핵심 정보(숫자·사실·구조) 확인·편집.
4. **컨셉·형식** — 카피 컨셉 + 이미지 스타일팩 + 형식(릴스/롱폼, 길이) 선택.
5. **스토리보드** — 씬별 자막/나레이션/이미지 프롬프트 편집.
6. **생성·렌더** — SD 이미지 → TTS → ffmpeg. 잡 큐 + 진행률 폴링.
   한 번의 분석으로 여러 형식을 연속 큐잉 가능.
7. **결과** — 미리보기·다운로드 + GEO 설명란(요약 박스+챕터 타임스탬프) 복사 버튼.

### DataLab 제약과 보완

DataLab API는 인기 키워드 "목록"을 주지 않고 지정 키워드의 트렌드 지수만 반환한다.
따라서 카테고리마다 시드 키워드 풀(20~30개)을 두고, datalab 검색어 트렌드로 주간 상승률을
계산해 정렬한다(호출당 키워드 그룹 5개 제한 → 배치 호출). 시드 풀은 UI에서 관리한다.

## 5. 수집 계층

- 네이버 검색 API(블로그)로 키워드당 상위 N건 목록 수집(제목·링크·요약·작성일).
- 구글: Custom Search JSON API(공식, 무료 100쿼리/일 — 일일 사용량으로 충분) 우선,
  키 미설정 시 Playwright 검색 크롤링 폴백. 블로그 도메인(티스토리·브런치·네이버 등)만
  필터링해 리스트에 편입. 사전 준비물: GOOGLE_CSE_KEY + GOOGLE_CSE_ID 발급(무료).
- 본문 크롤링 폴백 체인(M1 구현 확정): 네이버는 모바일 변환(m.blog) 후 httpx 직접
  추출(se-main-container/postViewArea), 일반 URL은 trafilatura, 실패·80자 미만이면
  jina 리더. 네이버 블로그 구형 PostView 쿼리 URL도 지원.
- 수집 결과는 SQLite에 저장(source 필드: naver/google). 리스트 화면은 저장분 우선,
  새로고침 시 재수집.
- 진단 가점: 같은 주제가 네이버·구글 양쪽 상위에 모두 노출되면 no_discount(검증된 수요)
  판정에 가점.

## 6. 보랏빛소 진단 — 블로그판

원본: `D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807\purple_cow.py`
(CHECKLIST 4문항, diagnose, _pick_principles, build_reels_guide 구조 이식)

상품 데이터(할인율·구매자수) 기반 판정을 콘텐츠 데이터 기반으로 각색:

| key | 원본 (상품) | 블로그판 판정 근거 (수집 데이터만 사용) |
|---|---|---|
| one_second | 1초 차별성 | 핵심 숫자/사실 중 한 줄 훅 후보 존재 (구체 숫자 유무) |
| what_is_that | "이건 뭐야?" | 통념 반대 주장·의외 사실 존재 (글 간 상충 정보 = 후보) |
| sneezer | 자랑거리 | 실행 가능한 구체 팁(체크리스트·금액·단계) 존재 |
| no_discount | 할인 없이도 가치 | 상위 노출 글 다수가 공통으로 다루는 검증된 수요 주제 |

- 점수(0~4)·verdict·hooks[]·weak[]를 반환. 점수는 리스트 배지에 표시.
- 실패 문항 → 대본 지침 자동 주입(_pick_principles 매핑 유지, 3점 이상이면 "덜어내기 모드").
- 원본의 교훈 유지: 판정은 모델 추론이 아니라 수집 데이터에서만. BORING_KEY류 블록리스트 적용.

## 7. 대본 엔진

### 영상 진행 순서 (글 내용 + 보랏빛소 + GEO)

```
① 훅 (1~2씬)      진단 hooks[0], 충격 숫자/질문형
② GEO 두괄식 요약  결론 먼저. 릴스 1씬, 롱폼 인트로 30초
③ 본문 챕터        수집 글들의 핵심 포인트. 씬마다 주어 재기입(씬 자립성)
④ 반전/단점 고백   보랏빛소 원칙 — 이 방법이 안 맞는 사람 지목
⑤ CTA             저장·팔로우 유도 + 다음 영상 예고
```

- Gemini 모델 폴백 체인(gemini-3.5-flash → 2.5-flash → 1.5-flash), 자막 18자/서브 22자 제한,
  "나레이션이 자막을 그대로 읽지 말 것" 규칙 등 EstateReels 프롬프트 규칙 이식.
- `scene_level` 플래그 구조 이식: 씬 단위 재생성 프롬프트는 "정확히 두 줄만 출력" 스코프로 제한
  (전체 스토리보드를 다시 만들어 파싱이 깨지는 실증된 실패 방지).

### 안전장치

1. **날조 게이트** — 원본 `guardrails.py` 이식: 대본의 모든 숫자는 수집 글에 존재해야 통과
   (뺄셈·나눗셈 파생값 허용, '최 저 가' 공백 우회 차단, 부정·유보 문맥 통과).
   실패 씬은 재생성, 3회 실패 시 숫자 없는 안전 문구로 대체.
2. **금지어 공용 모듈** — `banned_words.py` 단일 출처(원본의 3중복 문제 해결).
   상투어·최상급·순위 표현 + 표시광고법 위반 소지 표현.
3. **저작권** — 여러 글 종합 재구성 원칙. 원문 문장 n-gram 유사도 검사로 문장 복사 차단.

### GEO 적용 (3층)

- **씬 자립성**: 씬마다 주제어 재기입, 지시대명사 금지 — 문단 단독 인용 가능 원칙의 영상판.
- **두괄식**: ② 요약 씬 + 롱폼 인트로 30초에 결론 배치.
- **설명란 자동 생성**: 두괄식 요약 박스(객관 단정문 3줄) + 챕터 타임스탬프(h2 구조 대응)
  → 결과 화면에서 복사. 유튜브 검색·생성형 검색 인용 최적화.

## 8. 이미지 파이프라인 (SD WebUI — 2026-08-16 실환경 확정 개정)

2026-08-16 확인: 이 PC에는 ComfyUI가 없고 `D:\sd-webui`(A1111 계열)가 API 모드(7860)로
운용 중이며 체크포인트는 DreamShaper 8(SD1.5). 백엔드를 SD WebUI로 확정한다(사용자 승인).

- 대본 생성 시 씬별 영문 이미지 프롬프트 동시 생성(M2 완료) → 스타일팩 프리픽스/네거티브
  결합 → `/sdapi/v1/txt2img` 호출(steps 25, DPM++ 2M Karras, CFG 7).
- 스타일팩은 `style_packs.json` 정의(프리픽스·네거티브·씬롤/카테고리 매핑) — 코드 수정 없이 추가 가능.
- 오버레이 자막과 겹치지 않도록 공통 네거티브에 text·watermark·letters 계열 고정.

### 스타일팩 6종

| id | 스타일 | 잘 맞는 카테고리 | 모션 |
|---|---|---|---|
| flat_vector | 플랫 벡터 인포그래픽 | 재테크·IT·정보성 | 팬 + 슬라이드 |
| pastel_anime | 파스텔 애니 일러스트 | 여행·라이프·요리 | Ken Burns 줌 |
| isometric | 아이소메트릭 3D | 부동산·공간·프로세스 | 대각 팬 |
| cinematic | 시네마틱 실사 | 훅 씬 전용 | 강한 줌인 |
| papercut | 페이퍼컷 콜라주 | 차별화 씬(보랏빛소) | 2.5D 패럴랙스(옵션) |
| neon_abstract | 네온 그라디언트 추상 | 숫자·차트 강조 | 펄스/글로우 |

- 씬 롤 자동 매핑: hook=cinematic, summary·cta=neon_abstract, twist=papercut,
  point·chapter=카테고리 기본(부동산=isometric, 재테크·IT=flat_vector,
  건강·요리·여행=pastel_anime, 그 외=flat_vector).
- 해상도(SD1.5 조정): 릴스 576×1024, 롱폼 1024×576 (→ ffmpeg 1080 스케일).
- **캐시**: 프롬프트+스타일+해상도 해시 → SQLite 인덱스, 동일 프롬프트 재사용.
  10분(72씬) 기준 신규 생성 30~40장 목표.
- 생성은 잡(job)으로 백그라운드 실행, UI는 진행률 폴링(§3의 잡 큐 최소형을 M3에서 도입).
- 옵션(1차 릴리즈 이후): AnimateDiff 훅 씬 2~4초 루프, depth 기반 2.5D 패럴랙스.
- SD WebUI 다운 시: 스타일 색상 그라디언트 카드 폴백(Pillow) — 진행은 멈추지 않는다.

## 9. 렌더링

### 씬 테이블

| 형식 | 길이 | 씬 수 | 평균 컷 |
|---|---|---|---|
| 릴스 9:16 | 30 / 60초 | 7 / 13 | 4.3~4.6초 |
| 롱폼 16:9 | 60 / 180 / 300 / 600초 | 10 / 24 / 38 / 72 | 6~8.3초 |

- 길이 배분: EstateReels 로직 이식 (hook ×1.35, cta ×1.45, 최소 컷 2.2초).
- 롱폼은 챕터마다 챕터 타이틀 씬 1개 추가. 구조는 항상 hook → 요약 → 챕터들 → 반전 → cta.

### 합성 (네이티브 ffmpeg)

- 2단계 구조 이식: ① 씬 클립 생성(zoompan Ken Burns + 자막 PNG overlay + 무음 트랙)
  ② concat `-c:v copy` (자막이 구워져 있어 재인코딩 불필요).
- 자막: 서버에서 Pillow로 프레임 크기 투명 PNG 렌더. hook/cta 중앙 강조, point 하단
  로어서드, 하단 스크림 그라디언트 — EstateReels 스타일 유지. 한글 폰트는 시스템 폰트 사용.
- 해상도 1080p(릴스 1080×1920, 롱폼 1920×1080), `libx264 -preset veryfast`.
- 오디오: Edge-TTS 씬별 **병렬** 생성(원본 직렬 병목 해소) → adelay + amix, BGM 볼륨 0.28.
  BGM은 무드별 로컬 파일(EstateReels bgmService 무드 4종 구조 이식).
- 폴백 4단(copy+오디오 → 재인코딩+오디오 → 재인코딩+BGM → 기본) 이식.
  단, copy 경로에도 길이 클램프를 적용해 원본의 "폴백 단계별 길이 불일치" 버그는 수정한다.
- 잡 큐: 이미지·TTS·렌더는 SQLite 잡으로 백그라운드 실행, UI 폴링. 동시 렌더 1개 제한
  (720급 성능 주의 교훈 — GPU는 ComfyUI와 공유되므로 렌더 중 이미지 생성 큐는 대기).

## 10. 에러 처리 (멈추지 않고 폴백)

| 실패 지점 | 처리 |
|---|---|
| 본문 크롤링 차단 | 폴백 체인(모바일 변환 httpx → trafilatura → jina), 전부 실패 시 검색 요약문으로 진단만 수행 |
| Gemini 실패 | 모델 폴백 + 재시도, 최종 실패 시 명확한 오류(퇴화 대본을 저장하지 않음 — §7 복사 차단 원칙상 원문 기반 규칙 대본은 만들지 않는다) |
| ComfyUI 다운/타임아웃 | 그라디언트 카드 폴백 |
| TTS 실패 | 해당 씬 자막+BGM만 |
| 날조 게이트 3회 실패 | 숫자 없는 안전 문구 |
| concat copy 실패 | 재인코딩 폴백 (길이 클램프 유지) |

## 11. 테스트

- 단위: 진단 채점(고정 입력→고정 점수), 날조 게이트(날조 차단·파생값 통과·우회 차단),
  씬 배분(합계=목표 길이±오차), 금지어 필터, GEO 설명란 포맷.
- 통합: 저장된 블로그 HTML 픽스처로 수집→분석→대본을 오프라인 실행(외부 API 없이 CI 가능).
- 스모크: 5초 샘플 렌더로 ffmpeg 파이프 검증. 실제 E2E(검색→10분 렌더) 1건은 수동 확인.

## 12-A. 블로그 글 생성·발행 (M2.5 — 2026-08-16 승인 추가)

같은 수집·분석·진단 위에서 릴스 대본과 나란히 **블로그 글**을 생성하고
네이버·티스토리에 자동 발행한다. 글 선택 → "블로그 글 만들기" 독립 버튼.

### 글 생성 (article_gen)
- 원본 쿠팡 `build_blog_guide`의 블로그판 지침: 진단·약점·원칙 주입 + 제목 32자 이내
  + 단점 먼저 + GEO 문단 자립성(문단마다 주제어 재기입, 숫자마다 확인 시점) + 금지어.
- 산출: 네이버·티스토리 공용 원고 1개 — 제목 + 마크다운 본문 1,200~1,800자,
  구조 `■ 핵심 요약(3줄) → h2 소제목 3~4개(각각 단독 인용 가능) → 단점/주의 → 마무리`.
- 게이트: 대본과 동일 원칙을 **문단 단위**로(숫자 대조·금지어·원문 15자 복사) →
  위반 문단 재생성(요청당 예산 10회) → 최종 실패 문단은 삭제하고 경고 목록에 기록.
- Gemini 부재 시 503 (대본과 동일 정책).

### 저장·API
- `articles` 테이블: id, category_id, post_ids_json, title, body_md, warnings_json,
  status(`draft`/`published`), published_urls_json, created_at.
- REST: POST /api/articles {category_id, post_ids} · GET /api/articles/{id} ·
  GET /api/categories/{cid}/articles · PATCH(제목·본문 편집 → 재게이트 warnings 동봉) ·
  POST /api/articles/{id}/publish {platform: naver|tistory, force?: bool}.

### 발행 연동 (외부 프로세스 — B안 승인)
- `core/publisher_bridge.py`: handoff JSON(platform·title·body_md·category) 작성 →
  `.env`의 `PUBLISHER_DIR`(쿠팡 블로그 프로젝트 경로)의 `publish_generic.py`를
  subprocess로 실행(타임아웃 5분) → result JSON(ok·url·error) 파싱 → URL·상태 저장.
- `publish_generic.py`는 쿠팡 프로젝트에 추가하는 얇은 CLI 1개 — 기존 검증 자산 재사용:
  티스토리는 기존 `tistory_poster.py post <원고.md>` 흐름(**기본 비공개 발행,
  공개 전환은 사람이** — 원본 설계 철학 유지), 네이버는 `NaverBlogPoster.write_post`.
  쿠팡 특화(제휴링크·대가성 고지·상품 위젯) 경로는 호출하지 않는다.
- 로그인 세션은 그쪽 프로젝트의 persistent 세션·쿠키 그대로 — 이 앱은 크리덴셜을
  다루지 않는다. 세션 만료 시 브라우저 창에서 직접 로그인.
- 발행 직전 게이트 재검사 — 경고가 있으면 409 거부, `force: true`로만 무시 발행.
- 실패·타임아웃 → draft 유지 + 에러 표시. PUBLISHER_DIR 미설정 → 발행 버튼 비활성.

### UI
- PostList make-bar에 `📝 블로그 글 만들기` 버튼(대본 버튼과 나란히).
- `/article/:id`: 제목 input·본문 textarea·게이트 경고 패널·플랫폼별 발행 버튼·발행 URL.

### 테스트
- article_gen 게이트·문단 삭제·예산은 Gemini mock으로, 브릿지는 subprocess mock으로
  오프라인 CI. publish_generic 자체는 쿠팡 프로젝트에서 수동 스모크 1회.

## 12. 마일스톤

1. 수집 + 카테고리 대시보드 + 블로그 리스트(보랏빛 배지) — 여기까지로 "카테고리별 리스트" 요구 충족
2. 분석 + 대본 엔진(보랏빛소·GEO·날조 게이트) — 완료
2-5. 블로그 글 생성·발행(§12-A) — 대본과 독립 산출물, 네이버·티스토리 자동 발행
3. ComfyUI 이미지 + 스타일팩 + 캐시
4. 릴스 렌더(30/60초) — 첫 영상 산출
5. 롱폼(1/3/5/10분) + TTS 병렬 + GEO 설명란
6. UI 마감 + 폴백·에러 처리 보강

## 13. 참조 (이식 원본)

- `D:\부동산릴스-EstateReels-v2\src\utils\storyboard.ts` — 씬 테이블·길이 배분
- `D:\부동산릴스-EstateReels-v2\src\services\ffmpegService.ts` — 2단계 합성·4단 폴백
- `D:\부동산릴스-EstateReels-v2\src\services\captionCanvas.ts` — 자막 스타일
- `D:\부동산릴스-EstateReels-v2\src\services\blogImport.ts` — 수집 폴백 체인
- `D:\부동산릴스-EstateReels-v2\src\utils\estateConcepts.ts` — 컨셉 엔진 구조
- `D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807\purple_cow.py` — 진단·지침
- `D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807\guardrails.py` — 날조 게이트
- `D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807\daily_tistory.py` — GEO 채널 전략
