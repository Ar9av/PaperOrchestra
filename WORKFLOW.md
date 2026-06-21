# PaperOrchestra Workflow

This repository tracks PaperOrchestra-specific closeout gates here so local
development, pull requests, and scheduled acceptance runs use the same checks.

## Active Closeout Scope

- Branch: `native-swiftui-control-room-replacement-v3`
- Target: merge the native SwiftUI launcher/control-room replacement into
  `main` after review and CI.
- Supported UI surface: native SwiftUI launcher plus the local FastAPI
  control-room path exercised through `scripts/launch_gui.py`.
- Legacy compatibility surfaces remain in-repo for reference, but new
  acceptance work should target `gui_app.web` and `scripts/launch_gui.py`.

## Required Local Checks

Run these before publishing or merging a PaperOrchestra control-room change:

```bash
.venv/bin/python -m pytest -q
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer /Users/jeff/.codex/bin/codex-xcode27 proof
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer /Users/jeff/.codex/bin/codex-xcode27 swift-test fast --repetitions 3
```

For end-to-end local acceptance, run:

```bash
OUT="$(mktemp -d /tmp/paper-orchestra-acceptance.XXXXXX)"
DATA="$(mktemp -d /tmp/paper-orchestra-acceptance-data.XXXXXX)"
.venv/bin/python scripts/acceptance_walkthrough.py \
  --local-only \
  --host 127.0.0.1 \
  --port 0 \
  --data-root "$DATA" \
  --output-root "$OUT" \
  --forced-failure-stage compile \
  --keep-artifacts-on-failure
```

Pass criteria:

- `summary.json` reports `status: succeeded`.
- `final_run_status` is `succeeded`.
- `forced_failure_stage` is `compile`.
- `local_only` is `true`.
- `final_pdf_path` exists and starts with `%PDF-1.4`.
- Browser screenshots exist for setup, inputs, review, run start, retry, and
  final PDF link states.

## Pull Request Checklist

- [ ] Branch is pushed to GitHub.
- [ ] PR description includes the validation evidence from the latest local
      run.
- [ ] GitHub Actions `Local-only acceptance` completes successfully.
- [ ] No unrelated dirty worktree files are included.
- [ ] README acceptance instructions stay aligned with the harness flags.
- [ ] Any CI failure is either fixed before merge or recorded as a bounded
      follow-up with an owner and reproduction command.

## Scheduled Acceptance

`.github/workflows/local-only-acceptance.yml` runs the local-only walkthrough on
pull requests, manual dispatch, and a nightly cron. The job deliberately avoids
Chrome DevTools MCP, signed-in Chrome sessions, Atlas, external Semantic
Scholar fetches, and Codex-backed network work. It installs Python dependencies,
installs Playwright's bundled Chromium, runs the deterministic local harness,
and uploads the acceptance output directory on every run.

## Secrets

Do not commit API keys or local credentials. The local-only acceptance path must
not require `SEMANTIC_SCHOLAR_API_KEY`, `EXA_API_KEY`, `OPENAI_API_KEY`,
`LINEAR_API_KEY`, Chrome profile state, Atlas login state, or a configured Codex
binary.
