
## 07:49 | feat/adstudio-youtube-homage
Debugged Tistory image upload: extended login timeout 6→15 min by parameterizing `tistory_poster.py` and `publish_generic.py`; identified root cause (file inputs appear only after clicking image button) and secondary issue (missing AI category); started DOM investigation — fix pending.