# Recent

## 2026-08-26
Instagram integration shipped (Meta API tokens, Firebase Hosting, posts live via Dcf4hNHCX6j); Naver refactored (section images, 75→34 chars); fixed 4 CardNews bugs (SD timeout/idle/favicon/cascade, preheat logic). AI time budgets added (45s verify), 189 tests pass, thread-reply humanized (21 tests). Blockers: account consolidation, deploy mismatch.

## 2026-08-25
Built Playwright-based Naver publisher replacing Selenium+pyautogui; fixed image-attach timing by awaiting per-image editor confirmation (4s global → dynamic). Published posts with 6 images confirmed; fixed Gemini \n escaping in body. Designed Instagram Meta API integration.

## 2026-08-24
Completed blog automation pipeline (news→cards with draft UI, keyword pass-through, Naver images; 2,162-char + 6-image staging). Fixed Band headless login, added 49 channels (45 writable) for 2nd account; post limits account-level (Band 50, Facebook 80). All 4 platforms E2E tested; awaiting Tistory login confirmation, install approval, config migration to new PC.

## Identity Candidates
- IDENTITY CANDIDATE: Full-stack AI ad platform engineer—ships multi-channel integrations (LLM copy + img gen + Firebase) with production rigor (test coverage, mutation validation, race-condition fixes, encoding safety).