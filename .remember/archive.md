# Archive

## Week of 2026-08-25
Deployed Naver publisher and IG Meta API integration (Firebase live); shipped multi-account blog posting (8 posts, 3 accts, 5 cats); added CarReels BGM, finalized Threads API spec (6 field changes, 60-day refresh critical). Fixed 4 CardNews, optimized Naver images (75→34 chars); Context-guard validation 49→1, Threads-reply funnel 8%. Enhanced session monitoring; surfaced auth blockers (IG token err 190, Tistory 2-stage Kakao). Threads-reply scale regressed (matching-layer temp); pending token refresh, matching fix, consolidation.

## Week of 2026-08-17
YouTube homage integration: fixed session-expiration bug in publish flow plus 3 related issues (category/selector/escaping). Text published to Tistory but image upload failed; added diagnostics. Login timeout blocked progress, pivoted to publish-only testing.

## Week of 2026-08-03
Estate-reels shipped (76 files); SNS section covers 5 platforms (YT/IG/TikTok/Threads/X) with auto-caption + tracking; Threads reply ads (5-module). Car-reels: 16-concept engine, 75 TS fixes, 21/31 defects; 8/10 FB ads. YouTube homage (21 commits, 115 tests) + SD auto-gen; evaluated 266 FB groups, optimized grid cost (32→16). Classified 406 channels, rebuilt approval/click-tracking pipelines; deployed 151 mutation tests; fixed prod bugs (daemon, emoji, encoding, timezone); 3 posts live.

## Week of 2026-07-27
₩100k GCP crisis resolved (v2.5 pinning 42% savings, dev-key sep, App Check); AutoAd P0–P1 shipped (14 templates, Gemini copy, 3 adapters, Firebase form, multi-industry profiles); infra: service.py 4→1, 6 crit regressions fixed (exit handlers, health-checks). Regression hunting: 3 failures via idempotency+backoff, loanIntake 27.8→1.0s. Audio/voice/4 video adapters merged; flux-2-klein-4b recommended (35–60× cheaper).