# Verification — standalone sync and existing lecture captions

## Offline checks

Executed on native Windows with Python 3.11 and 3.12:

```text
python -B -m unittest discover -s tests -q
Ran 85 tests
OK (skipped=1)
```

The skip is an actual-symlink creation test where Windows did not grant the needed
privilege. Mocked link/junction rejection tests ran. The suite covers config
precedence, origin-scoped transport and pagination, incremental storage, local
edits/conflicts, source traversal, assessment visibility, CLI entrypoints, captions,
scanner traversal and extraction failures, and independent-review regressions.

Also executed: compileall, CLI help smoke checks, non-secret setup/sync/report
fixtures, and `git diff --check`. A Windows/Linux Python 3.11/3.12 CI workflow is
included. GitHub CI status must be checked on the exact published commit before merging.

## Real authenticated acceptance (private evidence outside Git)

- Verified the current Canvas profile and enrolled courses through the implemented
  browser transport. No cookies or login response were included in this report.
- Ran the actual core sync twice against a resumed QA library for one enrolled unit.
  The first final pass returned 205 unchanged, 3 added and 2 updated artifacts.
  The next pass returned **210 unchanged**, with no duplicate/new/updated artifacts.
- Both passes reported **incomplete library coverage**, not false success: Pages
  listing 404, Files listing 403, a malformed linked page returning an error, and
  one file above the configured size limit. Assessment reads were independently
  verified on both passes and retained in findings.
- The final core check skipped **48 audio/video resources** under the new opt-in
  policy. This avoids attempting gigabyte MP4 downloads during a document sync.
- Checked **293 local relative unit/module index links: zero broken links**.
- Discovery was checked across four enrolled units. The bounded discovery observed
  1 / 1 / 16 / 1 recording source pages respectively, with explicit module-only
  coverage where the Pages listing was disabled. Source pages are not equivalent
  to lecture counts: an Echo library can contain many lessons.
- Exported an embedded Echo recording with **446 cues** and a course-library lesson
  with **774 cues**. Counts, first/last text, and start/end boundary timings matched
  the observed provider captions: **1,220 cues verified**.
- Re-exporting each of those recordings reported five unchanged files. The latest
  single-page CLI check returned exit 2 as designed for bounded coverage, while
  preserving its successful 446-cue export and unchanged-file status.
- Private output stayed under a separate home-folder QA library. Owned test browser
  and test runs were stopped afterward; no attached user browser was closed.

These are real checks, not synthetic provider responses. They do **not** establish
that a complete semester archive exists, that inaccessible captions can be fetched,
or that Panopto/Kaltura/other platforms are supported.

## Fresh setup and bulk-use follow-up

- An independent fresh-folder check exported the committed tree and created clean
  Python 3.11/3.12 environments. The then-current 81-test suite, documented setup,
  CLI help checks and dependency-free synthetic scanner passed on both versions.
- Subsequent live bulk use exposed delayed LTI/library readiness, legitimate
  teaching HTML containing password inputs, and slide decks being counted as
  caption-bearing media. Added bounded readiness waits, precise login markers and
  exclusion of explicit Presentation media, with three regression tests.
- The updated 85-test suite passes on both Python versions (one permission skip).
- Initial Linux CI caught a non-directory path-parent exception during invalid
  source validation. Source validation now precedes output validation, with
  consistent configuration errors and a dedicated POSIX-error regression.
- A four-course private bulk run exported 50 unique existing-caption transcripts;
  53,393 normalized cues were checked against their saved source text/timings and
  metadata hashes. No lecture text or private evidence is included here.
- Module-only discovery limitations remain explicit even when every discovered
  recording exports successfully. This is not proof that hidden or unlinked
  resources do not exist.

## Independent review disposition

A read-only reviewer identified root-link escapes, module-only recording discovery,
empty-attempt completion, login HTML downloads, incomplete privacy rules, linked
page traversal, transcript navigation and missing optional notes export. Important
findings were fixed and covered by executable regression tests. Several findings
were against earlier snapshots already corrected by the integrating parent.

The temporary expectation that notes export was unsupported was explicitly
superseded: opt-in namespaced export is now implemented and preserves local edits.
An overall incomplete library never advances its complete-success checkpoint;
separately verified assessment snapshots are checkpointed independently.

## Privacy / publication boundary

Inspected Git-visible source and verified ignore rules for auth caches, browser
profiles, findings, reports and lecture stores. The real observed lecture and
institution identifiers were absent from the audited source files. Broken abandoned
worker scaffolds were archived outside the repo, not shipped. No real lecture text,
student marks, provider access URLs, credentials or browser traffic are test fixtures.

No paid API or audio transcription was invoked. No teaching material was published.
Personal integration scripts and teaching material remain outside this repository.
Publication covers toolkit code, documentation and synthetic tests only.

## Known limitations

- QUT access restrictions and caption availability remain provider-controlled.
- HTML5 track capture depends on the browser requesting the track; parsers support
  VTT/SRT, but arbitrary provider-specific extraction is not implemented.
- Resource size limits use advertised metadata, not a hard network byte quota.
- Do not run concurrent sync writers against one output folder.
- Content-hashed originals, working copies, conflicts and optional notes mirrors
  consume extra disk space. Interrupted QA files were preserved, not deleted.
- macOS/Linux execution and the GitHub CI matrix have not been verified here.
