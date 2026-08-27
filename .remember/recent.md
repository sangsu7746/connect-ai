# Recent

## 2026-08-27
Session keepalive + auto token renewal deployed for Naver/Instagram (daily 07:30); multi-blog/multi-IG routing by category + batching enabled. 2x-daily auto-pub live; ThreadsReply tests +7.7pp to 91.7%. Instagram 3/3, blogs 2/3 published; Tistory auth blocked, Kakao login pending.

## 2026-08-26
Instagram integration shipped (Meta API tokens, Firebase Hosting, posts live via Dcf4hNHCX6j); Naver refactored (section images, 75→34 chars); fixed 4 CardNews bugs (SD timeout/idle/favicon/cascade, preheat logic). AI time budgets added (45s verify), 189 tests pass, thread-reply humanized (21 tests). Blockers: account consolidation, deploy mismatch.

## 2026-08-25
Built Playwright-based Naver publisher replacing Selenium+pyautogui; fixed image-attach timing by awaiting per-image editor confirmation (4s global → dynamic). Published posts with 6 images confirmed; fixed Gemini \n escaping in body. Designed Instagram Meta API integration.

## Identity Candidates
- IDENTITY CANDIDATE: Full-stack AI ad platform engineer—ships multi-channel integrations (LLM copy + img gen + Firebase) with production rigor (test coverage, mutation validation, race-condition fixes, encoding safety).
- IDENTITY CANDIDATE: Production session-management infra for multi-platform automation (keepalive, token renewal, profile isolation, scheduled execution).