
## 07:49 | feat/adstudio-youtube-homage
Debugged Tistory image upload: extended login timeout 6→15 min by parameterizing `tistory_poster.py` and `publish_generic.py`; identified root cause (file inputs appear only after clicking image button) and secondary issue (missing AI category); started DOM investigation — fix pending.
## 08:21 | feat/adstudio-youtube-homage
Completed Tistory editor investigation (0 file inputs found anywhere); switched from DOM injection to file-chooser dialog interception approach; wrote `_final_publish.py` consolidating login/upload/publish; pending user-present login to test.