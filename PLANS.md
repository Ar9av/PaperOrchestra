# PaperOrchestra Web App Upgrade — Codex Execution Plan

This file is intended to be dropped into the repository as `PLANS.md`. It is written as a Codex-facing execution plan in plain Markdown because Codex works well with Markdown planning documents, and OpenAI’s Codex materials specifically use `PLANS.md` for long, multi-step implementation work. `AGENTS.md` should remain short and should point Codex at this file for the PaperOrchestra upgrade.

## Purpose and user-visible outcome

Upgrade the existing local browser GUI at `/Users/jeff/paper-orchestra` from an Atlas-handoff assistant into an autonomous local PaperOrchestra web app with a real orchestration backend. After this work is complete, a user should be able to launch the app locally on macOS, create or open a project, provide either direct inputs or an aggregation source directory, start a full paper-writing run, watch live stage progress, inspect artifacts and logs, retry a failed stage without restarting the whole run, resume a paused run, and open the final PDF from the UI.

The system must preserve the PaperOrchestra pipeline semantics: `ingest -> validate -> outline -> plotting + literature in parallel -> section_writing -> refinement -> compile -> finalize`. Codex is the primary execution engine. Atlas is the default browser-native research and online-actions adapter. PaperBanana is the preferred diagram engine, while deterministic local rendering remains the default for numeric plots.

## Scope

This plan covers the first production-worthy local milestone only. It is intentionally backend-first. The primary deliverable is a durable orchestrator with a thin FastAPI-based local web interface. The implementation target is a single-user, unauthenticated, macOS-local deployment. The existing filesystem workspace layout and JSON-based run persistence remain in scope for v1.

## Non-goals

Do not add multi-user auth, cloud hosting, a database-backed product data model, a native macOS wrapper, or a complete repo reorganization in v1. Do not replace the existing Atlas controller path with a parallel second Atlas system. Do not make PaperBanana a hard dependency. Do not store secrets in repo-tracked files. Do not change the core PaperOrchestra stage semantics just to simplify UI work.

## Repository context and assumptions

Treat `/Users/jeff/paper-orchestra` as the working repository. Use the archive workspace only as reference material. The existing local project already has a browser GUI, an Atlas integration path centered on `gui_app/atlas_controller.py`, a launcher entrypoint `scripts/launch_gui.py`, and at least one existing storage test at `tests.test_gui_storage`. Preserve and extend those paths rather than creating redundant parallel systems when practical.

Use the upstream PaperOrchestra archive only as a reference for skills, prompts, deterministic helper scripts, and expected stage semantics. Important upstream references include the outline, literature review, content refinement, paper orchestration, and input validation assets in the `skills/` tree, plus the minimal example in `examples/minimal/`.

A Semantic Scholar API key is already available to the user and must be injected only through environment configuration. The approved Semantic Scholar throughput is one request per second cumulatively across all endpoints, so the implementation must enforce a global cross-run rate limit and cache rather than only per-run throttling.

## High-level design decisions

The orchestrator is the product. The UI is a thin client of the orchestrator, not the other way around. Build the worker and state model first, then expose it through HTTP routes and server-rendered templates.

The orchestrator must be a persistent state machine, not a one-shot shell wrapper. Every stage transition, artifact write, retry, pause, and failure must be durable and inspectable after process restarts.

Run state must use two layers. `state.json` is the latest materialized view for quick reads. `events.jsonl` is append-only and authoritative for auditability and replay. Each stage attempt gets its own immutable attempt directory. Never overwrite a prior failed attempt.

Atlas, Codex, and PaperBanana must be isolated behind adapters. The orchestrator may call adapters, but adapters must return normalized artifacts and status. Adapter-specific quirks, browser issues, screenshots, and transcripts must not leak into the core stage scheduler.

PaperBanana should be used by default for methodology diagrams and similar conceptual illustrations. Numeric plots should default to deterministic local rendering unless a stage explicitly opts into PaperBanana. Generated figures must pass a lightweight quality gate before they are admitted to the manuscript.

Keep Step 4 as one manuscript-writing stage, not a swarm of micro-sections. Keep Step 5 aligned with PaperOrchestra’s snapshot, score, accept-or-revert behavior. Do not allow refinement to drift into unconstrained rewriting.

## Observable v1 behavior

A successful run should produce a visible run timeline in the browser, stage logs, stage summaries, durable artifacts, a final LaTeX tree, provenance metadata, and a final PDF. If a stage fails, the user should see which stage failed, why it failed, the exact artifact and log paths, and a button to retry just that stage. If a stage needs manual intervention, the run should pause cleanly with a typed `attention_required` reason rather than silently stalling.

## Proposed filesystem layout

Keep the existing repo structure, but add the following runtime layout under the application workspace area:

    runs/<run_id>/
      state.json
      events.jsonl
      inputs/
      outputs/
      stages/
        ingest/attempt-001/
        validate/attempt-001/
        outline/attempt-001/
        plotting/attempt-001/
        literature/attempt-001/
        section_writing/attempt-001/
        refinement/attempt-001/
        compile/attempt-001/
        finalize/attempt-001/
      artifacts/
      logs/

The exact parent directory may follow the current workspace convention if one already exists. The run folder must survive app restarts. Each attempt directory must contain stage-local inputs, outputs, logs, and a machine-readable stage summary.

## Run state schema

At minimum, `state.json` must include `run_id`, `project_id` if applicable, `created_at`, `updated_at`, `status`, `current_stage`, `workspace_path`, `artifacts`, `attention_required`, `attention_reason`, and a `stages` object keyed by stage name.

Each stage entry must include `status`, `attempt`, `started_at`, `finished_at`, `summary`, `log_path`, `artifacts`, and `dependencies`. The allowed stage statuses should be `pending`, `running`, `succeeded`, `failed`, `paused`, `cancelled`, and `skipped`.

`attention_required` must not be a bare boolean. Use an enum-like string reason such as `missing_input`, `manual_review`, `rate_limited`, `adapter_unavailable`, `compile_error`, `secret_missing`, or `figure_qc_failed`.

`events.jsonl` should record timestamped transitions such as run creation, stage scheduled, stage started, artifact written, stage succeeded, stage failed, stage retried, run paused, run resumed, and run cancelled. Events should be append-only.

## Core application modules

If the repository already has close equivalents, extend them in place. Otherwise create modules along these lines:

    gui_app/
      app.py
      atlas_controller.py
      routes/
        runs.py
        health.py
      templates/
        base.html
        index.html
        project_detail.html
        run_detail.html
      static/
        app.js

    orchestrator/
      engine.py
      scheduler.py
      models.py
      events.py
      run_store.py
      artifacts.py
      stages/
        ingest.py
        validate.py
        outline.py
        plotting.py
        literature.py
        section_writing.py
        refinement.py
        compile.py
        finalize.py

    adapters/
      atlas_adapter.py
      codex_executor.py
      paperbanana_adapter.py
      plotting_adapter.py
      semantic_scholar.py

    tests/
      test_gui_storage.py
      test_run_store.py
      test_orchestrator.py
      test_routes.py
      test_atlas_adapter.py
      test_paperbanana_adapter.py
      test_parallel_join.py

The point is not the exact names; the point is a clean separation between HTTP/UI, orchestration, adapters, and tests.

## Adapter contracts

### Atlas adapter

Extend `gui_app/atlas_controller.py` instead of adding a second Atlas path. Wrap its behavior in a reusable adapter contract that can stage prompts, enable or verify Deep Research when needed, submit tasks, collect browser-native outputs, persist screenshots, and return normalized artifacts.

The Atlas adapter should return a structured result with fields similar to `task_id`, `task_type`, `status`, `started_at`, `finished_at`, `prompt_path`, `raw_response_path`, `structured_output_path`, `screenshot_paths`, `transcript_path`, `summary`, and `artifacts`. The orchestrator should not need to know how Atlas internally captured those artifacts.

### Codex executor

Codex remains the primary execution and writing engine. Create a `CodexExecutor` abstraction that can run stage prompts, capture stdout and stderr, store transcripts, and return structured status. This wrapper should be the only place that knows how `codex exec` is invoked in the local environment.

### PaperBanana adapter

PaperBanana should be invoked through a narrow adapter that can answer three questions: whether PaperBanana is available, how to request a diagram render, and where the rendered outputs and logs live. The adapter should also support a clean fallback path to local deterministic renderers.

### Semantic Scholar helper

Create a helper that centralizes lookup, verification, rate limiting, and caching. It must enforce a global token bucket of one request per second across all active runs. The cache can use a small local utility database or equivalent persistent store, but run-state persistence must remain JSON-on-disk.

## Stage-by-stage behavior

### Ingest

Collect user input from either direct text/file uploads or optional aggregation from a source directory. If `idea.md` or `experimental_log.md` is missing and the user selected aggregation mode, call the existing `agent-research-aggregator` flow. Preserve the raw ingested files as run artifacts.

### Validate

Initialize or validate the run workspace, validate required inputs, and check integration health. Validation must confirm that all required template and guidelines files exist, that the write path is available, and that secrets needed for enabled integrations are present.

### Outline

Use Codex with the existing outline-agent assets and validators to generate the JSON outline. Validate it before advancing. Outline output must define the visualization plan, the literature search strategy, the section plan, and citation hints.

### Plotting and literature in parallel

After the outline succeeds, schedule `plotting` and `literature` as siblings. They run independently, and `section_writing` may start only after both succeed.

The plotting stage should use PaperBanana first for diagram-style figures when configured and available. Numeric plots should use deterministic local rendering unless the outline explicitly requests otherwise. Before the stage succeeds, run a figure quality check that at minimum verifies file existence, non-empty output, and any lightweight visual or structural checks that can catch obviously broken figures.

The literature stage should use Atlas by default for browser-native discovery and Deep Research tasks, then use Codex plus deterministic helpers to verify papers, deduplicate candidates, build `refs.bib`, and write `drafts/intro_relwork.tex`. Semantic Scholar verification must be sequential at the global allowed rate, even if candidate discovery is parallel.

### Section writing

Treat this as one manuscript-writing stage. Use Codex plus the current deterministic helpers to fill the remaining sections, integrate generated figures, and build the draft LaTeX manuscript. Do not split the step into many independent section agents in v1.

### Refinement

Use the existing content-refinement logic, including snapshot, score delta, accept-or-revert rules, and halt conditions. Every refinement attempt must snapshot the pre-edit state, write a worklog, and record whether the candidate was accepted or reverted.

### Compile

Run LaTeX compilation and existing sanity gates. This stage should fail with `attention_required = compile_error` if the manuscript cannot be built after allowed automatic retries.

### Finalize

Run anti-leakage, orphan-citation, provenance, and final packaging checks. The final stage should produce the canonical final PDF path and the final source bundle.

## HTTP routes and UI behavior

Use FastAPI with server-rendered templates and minimal JavaScript. The routes should include a health page, run creation, run detail, run retry, run resume, run cancel, and event or log streaming.

At minimum, implement:

    GET  /health
    GET  /
    POST /runs
    GET  /runs/{run_id}
    POST /runs/{run_id}/retry/{stage}
    POST /runs/{run_id}/resume
    POST /runs/{run_id}/cancel
    GET  /runs/{run_id}/events
    GET  /runs/{run_id}/logs/{stage}

Prefer server-sent events for live status updates. Keep the browser JavaScript minimal and use the server-rendered pages as the source of truth.

The run detail page must show current stage, status for every stage, plotting and literature sibling progress, Atlas availability and recent task status, PaperBanana availability, recent artifacts, and the final PDF when present.

## Secrets and configuration

Do not write secrets into repo-tracked YAML or Markdown files. Use environment variables or a macOS-local secret mechanism. At minimum support placeholders such as:

    SEMANTIC_SCHOLAR_API_KEY=
    PAPERBANANA_PATH=
    CODEX_BIN=
    ATLAS_ENABLED=1

If the local repo already has a configuration pattern, reuse it. Any settings file committed to the repo must contain placeholders only.

## Integration checks

The health page and startup checks should report whether Codex is available, Atlas is enabled and reachable through the existing integration path, PaperBanana is available at `PAPERBANANA_PATH`, and the Semantic Scholar key is present. These checks should never expose secret values.

## Error handling and retry rules

Every stage must fail loudly and specifically. Failures should include a machine-readable reason, a human-readable summary, and pointers to logs and artifacts. A failed stage may be retried without rerunning successful siblings. Retrying a stage must create a new attempt directory and append a new event. If a downstream stage depends on the failed stage’s artifacts, it must remain blocked until the retry succeeds.

Cancellation must be cooperative. A cancelled run should stop scheduling new work, mark the run cancelled, and preserve all prior artifacts.

Resume should continue from the earliest blocked stage after a paused or interrupted run. It should never re-run already succeeded stages unless the user explicitly asked to retry them.

## Test strategy

Keep `./.venv/bin/python -m unittest -q tests.test_gui_storage` green throughout the refactor. Expand automated test coverage around the new orchestration and adapter surfaces.

Add tests for run-store persistence, state materialization from events, parallel plotting and literature join behavior, stage retry semantics, paused states, cancellation, and launcher startup. Mock Atlas and Codex at the adapter boundary. Use `examples/minimal/` for backend integration tests that verify workspace scaffold, input validation, stage artifact placement, and final compile-path handling.

The test suite must prove at least one full successful run, one failed stage followed by targeted retry, one paused run that resumes, one plotting fallback from PaperBanana to a local renderer, and one compile failure that surfaces as an actionable paused or failed state.

## Manual acceptance scenario

From the repository root, a developer should be able to launch the local web app with the supported launcher, create a project, provide the minimal example inputs or a real project input set, start a run, watch live progress in the browser, see plotting and literature run in parallel, inspect Atlas-produced research artifacts, retry a deliberately failed stage, and open the final PDF from the UI.

The acceptance walkthrough is complete only when all of the following are true. The app starts cleanly from `scripts/launch_gui.py`. A run survives a server restart without losing state. The final PDF opens from the browser. A targeted stage retry does not rerun unrelated completed stages. No secret values appear in the UI, logs, or repo-tracked files.

## Milestones

### Milestone 1 — establish the durable orchestrator skeleton

Introduce the run store, event log, state materializer, stage model, and scheduler with no UI polish beyond what is required to exercise them. At the end of this milestone, a developer should be able to create a run, see all stages initialized, start a stubbed run, and inspect durable run state on disk.

Acceptance for this milestone is a passing automated test that creates a run, advances a few stub stages, reloads state from disk after process restart, and proves that retries create new attempt directories without overwriting prior artifacts.

### Milestone 2 — wire real stage implementations and adapters

Replace stage stubs with real ingest, validate, outline, literature, plotting, section writing, refinement, compile, and finalize implementations. Extend the existing Atlas controller through an adapter. Add the Semantic Scholar global limiter and cache. Add PaperBanana and deterministic plotting fallback behavior.

Acceptance for this milestone is a backend integration test using `examples/minimal/` and mocked Atlas or Codex boundaries, plus a manual dry run proving that parallel plotting and literature join correctly before section writing.

### Milestone 3 — expose the orchestrator through FastAPI and a thin browser UI

Add routes, templates, event streaming, retry and resume controls, health panels, and artifact links. Keep the UI thin and driven by the orchestrator state. Fix `scripts/launch_gui.py` so it is a stable repo-local entrypoint.

Acceptance for this milestone is a manual browser walkthrough that can start, monitor, retry, resume, and inspect a run locally.

### Milestone 4 — harden compile and finalize behavior

Strengthen deterministic gates around compilation, orphan cites, anti-leakage, provenance, and final artifact surfacing. Make sure failures are actionable rather than silent.

Acceptance for this milestone is a reproducible final PDF flow plus a forced compile error scenario that surfaces correctly in the UI and logs.

## Progress

- [x] Milestone 1 started.
- [x] Run store implemented with `state.json` and `events.jsonl`.
- [x] Stage attempt directories implemented.
- [x] Scheduler implemented with dependency tracking.
- [x] Milestone 2 started.
- [x] Atlas adapter extended from `gui_app/atlas_controller.py`.
- [x] Codex executor wrapper implemented.
- [x] PaperBanana adapter and deterministic fallback implemented.
- [x] Global Semantic Scholar limiter and cache implemented.
- [x] Real stage implementations wired.
- [x] Milestone 3 started.
- [x] FastAPI routes and templates implemented.
- [x] Event streaming implemented.
- [x] Retry, resume, and cancel controls implemented.
- [x] `scripts/launch_gui.py` stabilized.
- [x] Milestone 4 started.
- [x] Compile and finalize gates hardened.
- [x] Manual acceptance walkthrough completed.

## Surprises and discoveries

- The repo-local `.venv/bin/python` is the required validation interpreter for backend tests and acceptance runs. The global `/usr/local/bin/python3` may not have plotting and paper-helper packages such as `matplotlib`, `reportlab`, and `python-Levenshtein` installed.
- Local host integration symlinks under `.agents/`, `.claude/`, `.cursor/`, and `.windsurf/`, plus generated `dist-test/`, `gui-data/`, `tmp/`, `test-results/`, `.superpowers/`, and `.codex/xcode27/` output, are cleanup artifacts rather than source deliverables.

## Decision log

Decision: use Markdown and store this plan as `PLANS.md`. Reason: Codex guidance is Markdown-native, `AGENTS.md` should stay concise, and long-running implementation work benefits from a dedicated planning document.

Decision: keep run persistence as JSON-on-disk for v1, but use an append-only event log and immutable attempt directories. Reason: this preserves the low-friction local deployment model while making retries, restarts, and debugging much safer.

Decision: treat Atlas, Codex, and PaperBanana as adapters. Reason: the upgrade’s main risk is orchestration fragility, not model capability, so boundary isolation is worth more than adapter cleverness.

Decision: keep Step 4 as a single manuscript-writing stage and Step 5 as snapshot-and-revert refinement. Reason: this best preserves PaperOrchestra’s published workflow and avoids over-decomposing the writing path.

Decision: use PaperBanana first for diagrams, but default numeric plots to deterministic rendering. Reason: methodology diagrams benefit from the image-generation workflow, while statistical plots are more reliable when rendered from code.

Decision: implement a global Semantic Scholar limiter and cache. Reason: the approved throughput is one request per second cumulatively across endpoints, so per-run throttling is insufficient.

## Outcomes and retrospective

Shipped in this pass:

- The run store now uses `state.json` plus append-only `events.jsonl`, with immutable `stages/<stage>/attempt-###/` directories for logs, transcripts, and artifacts.
- The orchestrator now persists stage-level status, summaries, retry attempts, pause states, and interruption replay, and it resolves retries through the earliest unsatisfied dependency instead of blindly starting at the requested stage.
- The backend has explicit adapter seams: `gui_app/writer_executor.py` owns `codex exec`, `gui_app/research_adapter.py` owns Atlas literature-task normalization, and `gui_app/figure_adapter.py` owns figure backend selection and QC.
- The literature path now supports a shared Semantic Scholar SQLite cache plus a one-request-per-second cross-run limiter through the `s2_shared.py` helper.
- The FastAPI app now exposes health, run detail, SSE snapshots, stage logs, retry/resume/cancel controls, integration health, and thin server-rendered control-room pages.
- The launcher now waits for `/health` before reporting success and supports an explicit `PAPERORCHESTRA_GUI_DATA_ROOT` override via `--data-root`.
- Automated coverage now includes adapter persistence, dependency-aware retries, event-log replay after interruption, a mocked `examples/minimal/` end-to-end backend run, a compile-failure pause scenario, and launcher startup smoke coverage.
- Closeout validation on 2026-06-21 passed with `.venv/bin/python -m pytest -q` (`167 passed`), `codex-xcode27 proof`, and `codex-xcode27 swift-test fast --repetitions 3`.
- The fixture-backed acceptance walkthrough passed on 2026-06-21 with Chrome and Atlas production adapters disabled:
  `PAPERORCHESTRA_CHROME_ENABLED=0 PAPERORCHESTRA_ATLAS_ENABLED=0 CODEX_BIN=/opt/homebrew/bin/codex .venv/bin/python scripts/acceptance_walkthrough.py --host 127.0.0.1 --port 0 --data-root /tmp/paper-orchestra-acceptance-data.SwBZ4x --output-root /tmp/paper-orchestra-acceptance.0B9ghA --forced-failure-stage compile --keep-artifacts-on-failure`.
  Evidence: `summary.json` reported `final_run_status: succeeded`, the compile failpoint was consumed, retry completed, UI screenshots were written, and `final-paper.pdf` started with `%PDF-1.4`.

Deferred or still manual:

- A real online literature run with live ChatGPT/Atlas interaction remains outside fixture acceptance. The production browser adapters are covered by route and readiness tests, while the closeout walkthrough deliberately disables them for deterministic local acceptance.
