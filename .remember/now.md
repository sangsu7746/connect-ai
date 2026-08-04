
## 19:02 | feat/adstudio-youtube-homage
Fixed interval calc to exclude posting status (prevented timer resets), refactored thread approval from blocking to scheduler-based queuing, corrected dry_run condition logic in `approval.py`.
## 19:20 | feat/adstudio-youtube-homage
Fixed test slowdown (8m → 31.7s) by treating `POST_INTERVAL_MAX <= 0` globally as no-interval flag in `orchestrator.py`; 146 tests pass.