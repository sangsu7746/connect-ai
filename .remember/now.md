
## 11:07 | feat/adstudio-youtube-homage
Fixed job-ID prefix bug in orchestrator.py next_free_slot() ('publish:' vs 'pub-'), added mutation-validated tests in test_orchestrator_threads.py, 150 pass, restart pending.
## 11:31 | feat/adstudio-youtube-homage
Root cause found: UnicodeEncodeError (em dash in cp949 envs) in `_space_out()` stuck 6 jobs (#105-110) at "posting"; fixed 4 sites with hyphen + `_cp949_safe()` wrapper in orchestrator.py.