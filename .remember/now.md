
## 12:06 | feat/adstudio-youtube-homage
Created Playwright Naver publisher (`naver_playwright.py`) replacing Selenium+pyautogui, using `expect_file_chooser` per Tistory's working approach; published posts — pending verification images actually attached.
## 12:14 | feat/adstudio-youtube-homage
Fixed `naver_playwright.py` — Naver publisher selectors (`.publish_btn__m9KHH`, `.confirm_btn__WEaBq`) and verification (URL nav); executed — pending image/content verification.
## 13:07 | feat/adstudio-youtube-homage
Diagnosed Naver image loss as timing issue (4s insufficient for 6-image attach, DOM needs 3s+ per image); fixed `naver_playwright.py` to await per-image editor confirmation; executed — pending post verification.