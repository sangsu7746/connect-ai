
## 07:45 | feat/adstudio-youtube-homage
Completed bobaedreamParser.ts (price/specs/images extraction w/ dual URL formats), integrated to blogImport.ts, E2E tested w/ real listings (Orlando 339만원/18 imgs, Maybach/34 imgs), deployed—auto-recognizes 3 car marketplaces.
## 07:47 | feat/adstudio-youtube-homage
Fixed publish_campaign.py for per-platform login independence—Band session expiry no longer blocks Facebook; tested w/ 5 tattoo ads (FB sent, Band queued pending login). Also fixed cooldown check, variant numbering, flyer allocation.
## 07:53 | feat/adstudio-youtube-homage
Built build-in-public engine: scan.py (git classify), post.py (Threads/X publish), replies.py (comment auto-respond) w/ daily 21:00 schedule + git post-commit hooks + cost opt (Sonnet model $0.15/run, 95% reduction); tested on InkCraft commits generating teaser/promo posts.
## 07:57 | feat/adstudio-youtube-homage
Deployed Windows Task Scheduler daily + git hooks; verified $0.15/run cost (95% reduction via Sonnet); confirmed InkCraft at headjim-ink.web.app, updated config; initiated Threads token issuance.
## 13:17 | feat/adstudio-youtube-homage
Built setup_token.py script + .env template for Threads API token generation w/ secure local handling; provided 6-step manual app registration guide for app ID/secret retrieval.