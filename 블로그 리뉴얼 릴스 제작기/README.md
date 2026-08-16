# 블로그 리뉴얼 릴스 제작기

네이버·구글 상위 블로그 글 → 보랏빛소 진단 → SD 이미지 → 릴스/롱폼 자동 제작.
설계: docs/superpowers/specs/2026-08-15-blog-reels-maker-design.md

## 실행 (M1)

1. `.env` 작성 (`.env.example` 참고 — 네이버 개발자센터 검색/데이터랩 API 키 필수,
   구글 CSE 키는 선택. CSE 키가 없으면 구글 수집은 설치된 Chrome을 통한
   Playwright 폴백으로 동작)
2. 서버: `server\.venv\Scripts\python -m uvicorn main:app --app-dir server --port 8792`
3. 웹: `cd web; npm run dev` → http://localhost:5175
4. 테스트: `server\.venv\Scripts\python -m pytest server/tests -v`

### M2 — 대본 만들기

.env에 `GEMINI_API_KEY` 추가 필요(대본·챕터 생성). 키가 없으면 수집·진단까지만 동작.
블로그 리스트에서 글을 체크 → 형식 선택 → "대본 만들기" → 스토리보드에서
씬별 자막·나레이션 편집, AI 재생성, GEO 설명란 복사.

### M2.5 — 블로그 글 발행

블로그 리스트에서 글 체크 → "📝 블로그 글 만들기" → /article 페이지에서 제목·본문
검토(게이트 경고 확인) → 네이버/티스토리 발행 버튼.

- `.env`에 `PUBLISHER_DIR` = 쿠팡 블로그 프로젝트 경로 필요(발행 코드 재사용).
- 첫 발행 전 수동 스모크 1회 권장: 해당 프로젝트에서
  `python publish_generic.py --file test.json` (세션 만료 시 창에서 직접 로그인).
- 네이버 발행은 쿠팡 프로젝트에서 네이버 로그인 세션(쿠키)을 미리 만들어 둬야
  합니다(그쪽 naver_poster로 1회 로그인). 세션이 없으면 발행이 실패로 보고됩니다.
- **네이버는 즉시 공개 발행**됩니다(비공개 기능 없음) — 티스토리는 비공개로
  올라감. 공개 전환은 각 블로그 관리에서 직접.

### M3 — 씬 이미지 생성

`.env`의 `SD_WEBUI_URL`(기본 http://127.0.0.1:7860)로 로컬 SD WebUI에 연결
(D:\sd-webui\start-api.bat 로 API 모드 실행). 스토리보드에서 "🎨 이미지 생성"
→ 씬별 스타일팩 자동 매핑 → 진행률 표시. SD가 꺼져 있으면 그라디언트 카드로
대체되고(⚠ 폴백), SD를 켠 뒤 "전부 재생성"으로 채울 수 있다.

### M4 — 릴스 렌더

스토리보드에서 "🎬 렌더" → 씬 이미지+자막(맑은고딕)+Ken Burns를 ffmpeg로 합성해
`server/data/videos/`에 mp4 저장, 완료 시 페이지에서 미리보기·다운로드.
BGM은 `server/data/bgm/`의 mp3를 카테고리 무드로 자동 선택(없으면 무음).
BGM 파일명은 `<무드>-NN.mp3` 규약(documentary_calm/family_warm/emotional_daily (celebration 파일도 있으나 카테고리에
매핑되지 않아 무드 무관 폴백에서만 선택됨))
— 규약 밖 파일은 무드 무관 폴백으로만 선택된다.
이미지가 없는 씬은 스타일 색 카드로 대체됨 — 먼저 "🎨 이미지 생성" 권장.
ffmpeg가 PATH에 있어야 한다(확인: `ffmpeg -version`).
