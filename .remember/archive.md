# Archive

## Week of 2026-08-25
Deployed Naver publisher (Playwright, dynamic image timing) and IG Meta API integration (Firebase live). Added CarReels BGM (auto/4 moods), ported EstateReels, deployed carreels-ai. Fixed 4 CardNews bugs, optimized Naver images (75→34 chars). Context-guard improved validation 49→1, ThreadsReply funnel to 8%. 189 tests, 21 humanization; blockers: Tistory session, consolidation, deploy mismatch.

## Week of 2026-08-17
YouTube homage integration: fixed session-expiration bug in publish flow plus 3 related issues (category/selector/escaping). Text published to Tistory but image upload failed; added diagnostics. Login timeout blocked progress, pivoted to publish-only testing.

## Week of 2026-08-03
Estate-reels shipped (76 files); SNS section covers 5 platforms (YT/IG/TikTok/Threads/X) with auto-caption + tracking; Threads reply ads (5-module). Car-reels: 16-concept engine, 75 TS fixes, 21/31 defects; 8/10 FB ads. YouTube homage (21 commits, 115 tests) + SD auto-gen; evaluated 266 FB groups, optimized grid cost (32→16). Classified 406 channels, rebuilt approval/click-tracking pipelines; deployed 151 mutation tests; fixed prod bugs (daemon, emoji, encoding, timezone); 3 posts live.

## Week of 2026-07-27
₩100k GCP crisis resolved (v2.5 pinning 42% savings, dev-key sep, App Check); AutoAd P0–P1 shipped (14 templates, Gemini copy, 3 adapters, Firebase form, multi-industry profiles); infra: service.py 4→1, 6 crit regressions fixed (exit handlers, health-checks). Regression hunting: 3 failures via idempotency+backoff, loanIntake 27.8→1.0s. Audio/voice/4 video adapters merged; flux-2-klein-4b recommended (35–60× cheaper).