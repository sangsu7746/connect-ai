
## 19:02 | feat/adstudio-youtube-homage
Fixed interval calc to exclude posting status (prevented timer resets), refactored thread approval from blocking to scheduler-based queuing, corrected dry_run condition logic in `approval.py`.
## 19:20 | feat/adstudio-youtube-homage
Fixed test slowdown (8m → 31.7s) by treating `POST_INTERVAL_MAX <= 0` globally as no-interval flag in `orchestrator.py`; 146 tests pass.
## 19:23 | feat/adstudio-youtube-homage
Tasks 1-4 complete (vitest, types/store, schema, URL parsing); Task 4: added regression tests for `parseYoutubeVideoId` edge-case safety; Task 5 started.
## 19:43 | feat/adstudio-youtube-homage
Task 5: validated `buildSceneDurations` regression tests; discovered plan bugs (missed `SCENE_SEC_HARD_MAX` absorption step, wrong expected vals), implementer corrected both.