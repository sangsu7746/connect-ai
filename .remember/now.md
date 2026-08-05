
## 11:07 | feat/adstudio-youtube-homage
Fixed job-ID prefix bug in orchestrator.py next_free_slot() ('publish:' vs 'pub-'), added mutation-validated tests in test_orchestrator_threads.py, 150 pass, restart pending.
## 11:31 | feat/adstudio-youtube-homage
Root cause found: UnicodeEncodeError (em dash in cp949 envs) in `_space_out()` stuck 6 jobs (#105-110) at "posting"; fixed 4 sites with hyphen + `_cp949_safe()` wrapper in orchestrator.py.
## 11:41 | feat/adstudio-youtube-homage
Found 2 more unsafe prints (orch.py:869,886), cleaned db for stuck jobs, added PYTHONIOENCODING=utf-8 defense, found scheduler.py tz bug (UTC strip vs convert causes 9h offset).
## 11:47 | feat/adstudio-youtube-homage
Fixed race condition: added `_LAST_RESERVED_AT` memory to orch.py tracking reservations, updated `next_free_slot()` to check it, added repro test w/ isolation cleanup.
## 12:42 | feat/adstudio-youtube-homage
Validated race condition fix via mutation tests & full suite (151✓), real-world testing, handled incident (prior server active: 3 posts live, 1 safely failed), confirmed spacing now 6.8–9.7min vs. same-second; commit d0b1c6f96.