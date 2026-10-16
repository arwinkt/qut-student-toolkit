# Standalone course sync and lecture transcripts Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Give any QUT student an organised local course library, timestamped lecture transcripts, source-linked findings, assessment changes and truthful sync status without Obsidian or a paid AI subscription.

**Architecture:** Add a stdlib-first standalone Python package behind a new CLI entrypoint; retain legacy commands. One configured output root holds ID-stable unit/module directories, originals, Markdown and reports. A manifest records upstream identities/content hashes, local hashes, source metadata and sync failures. Caption extraction uses the authenticated recording provider's existing caption tracks, not audio transcription.

**Tech Stack:** Python 3.11+, urllib, html.parser, unittest; Playwright optional authenticated browser integration; existing extractors reused only with explicit safe paths.

## Prerequisites and boundaries
- Public repository freshly cloned on local branch feat/standalone-sync-transcripts. No push/publish approval: all work local.
- Existing personal vault scripts and downloaded work must remain untouched.
- Never commit cookies, tokens, student marks, lecture transcripts, signed media URLs or personal output. Test fixtures must be synthetic, explicitly labelled.
- Browser/Canvas APIs and lecture provider must be probed live before claiming provider support. An auth blocker is explicit, not fabricated successful extraction.
- No dashboard, audio download/paid transcription, AI-authored summaries, submission automation, GPA predictions or destructive migration.

## Task 1: Standalone config, authenticated API and safe storage
Files: scripts/qut_sync.py, scripts/qut_toolkit/{__init__,config,client,storage}.py, tests/test_core.py.
1. Write failing unittest tests for output root CLI > config > env > home default, optional vault/notes root, safe portable paths, IDs preventing collisions.
2. Implement timeout-bounded Canvas requests and same-origin pagination with typed auth/access/partial failures. Support supplied cookie-cache path or configured cache; do not print credentials or cookies. Distinguish forbidden optional listings from no data.
3. Write tests first for atomic manifest-backed changed/unchanged/new/local-edit conflicts and collisions. Hash content and metadata; do not silently overwrite local edits, delete user files, trust size alone, or advance success checkpoints after incomplete sync.
4. Implement minimal matching behavior, run unit tests.

## Task 2: Module library and reports
Files: scripts/qut_toolkit/sync.py, reports.py and CLI, tests/test_sync.py.
1. Test then implement course/module/page/assignment/file enumeration, full module-item pagination, HTML links and nested Canvas asset discovery.
2. Save source-linked page and assignment Markdown; download resources without forwarding Canvas cookies to untrusted hosts/redirects; reject traversal and executable network schemes. Handle duplicated resources and module references.
3. Build relative-link unit and module INDEX.md, unit findings.md and reports/latest-sync.md plus machine-readable report. Record source timestamps, last successful check, explicit incomplete/errors and added/updated/unchanged/conflicts. Do not copy paragraphs into every index.
4. Implement assessment/marks snapshot and diffs, UTC + local configured timezone, undated items, submitted vs graded/unreleased, numerical score zero, explicit cohort announcements as sources rather than invented per-student demands. Do not infer grace periods or GPA.
5. CLI setup/init, courses, sync COURSE_ID / --all, report and help. Config optional and safe defaults. Existing legacy commands remain usable.
6. Run regression unittest and offline end-to-end fixture exercising two sync passes + local edits + failures; verify real files/links.

## Task 3: Transcripts
Files: scripts/qut_toolkit/transcripts.py, recording-provider adapter as observed, tests/test_transcripts.py.
1. Inspect live course recording links and actual transcript panel/network before selecting provider-specific endpoints. Save private evidence only outside Git.
2. Test generic VTT/SRT parsing, multiline cues, timestamps, speaker preservation, HTML entities, malformed/no captions and language alternatives. No invented transcript content.
3. Implement recording discovery from modules/pages, supported existing caption fetching with correct origin-scoped auth and explicit unavailable/unsupported status. Do not bypass controls or send Canvas cookies to recording hosts.
4. Save transcript.md, original captions, metadata.json per lecture and link from module/unit indexes. Persist source provider/id/title/date/language/caption-type if known and retrieval time. Do not persist signed caption access URLs in public/log output.
5. Live acceptance: run implemented path against one accessible real lecture, verify cue counts and output first/last text against actual track. Then bounded scan across active units to prove discovery/organisation, reporting coverage, unsupported and unavailable separately.

## Task 4: Docs, privacy and clean-machine verification
Files: README.md, .gitignore, scripts/scan_school.py and legacy canvas.py config glue, tests, optional CI.
1. Document standalone outputs, optional vault mode, actual commands, auth expiry without guarantees, transcript support matrix, privacy and limitations.
2. Correct contradictory scanner documentation and make defaults cross-platform. No scan step should auto-spend API credits or assume Obsidian.
3. Ignore personal output/config/session/report/caption stores. Keep tests synthetic. Preserve legacy scan behavior when explicit legacy env is set.
4. Run full suite, compile/help/setup/sync/report smoke tests and secret/path checks. Independently review spec first, then security/quality. Fix important findings and rerun tests.

## Acceptance
- No-vault clean setup writes all results under chosen root; optional notes export documented and tested.
- A real Canvas unit sync runs twice without duplicate clutter, with source-linked indexes and assessment report.
- Local edits survive upstream changes; failed auth/download does not report clean success; pagination covered.
- Real caption extraction demonstrated where available; no claim of all-provider support without evidence.
- Complete tests and read-only review evidence recorded in .plan/progress.md. Local branch ready for user review; not pushed.
