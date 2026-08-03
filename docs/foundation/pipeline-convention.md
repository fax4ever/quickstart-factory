# Pipeline File Convention

This document defines how factory skills store and pass structured artifacts between pipeline stages. All pipeline files — plus PRDs, design docs, blog drafts, and reports — live in a persistent directory inside the **`quickstart-factory`** repo itself, namespaced by quickstart slug. This ensures a full audit trail that survives reboots and is deleted only when the user chooses.

## Why Everything Lives in `quickstart-factory`

Quickstart *code* (the scaffolded application) is created as its own separate GitHub repo by `rh-qs-scaffold`, then cloned as a folder at the `quickstart-factory` root — see [Nested Quickstart Repos](#nested-quickstart-repos) below. But every skill's bookkeeping — specs, manifests, PRDs, designs, blog drafts, reports — stays centralized in `quickstart-factory/.rhoai-qs/`, regardless of which stage of the pipeline is running or which repo the agent's shell happens to be sitting in. One canonical location means every skill can always find its inputs without needing to know where the quickstart's code repo lives on disk.

Because `.rhoai-qs/` now holds data for **every** quickstart ever worked on, every skill must first determine *which* quickstart the current session applies to. See [Resolving the Quickstart Slug](#resolving-the-quickstart-slug).

## Directory Structure

All quickstart-scoped files live under:

```
quickstart-factory/.rhoai-qs/<slug>/
```

**Example:** `quickstart-factory/.rhoai-qs/mortgage-processor/`

Cross-cutting artifacts that aren't about one specific quickstart (grooming reports, gap-analysis-style coverage reports) live under:

```
quickstart-factory/.rhoai-qs/_shared/
```

The `.rhoai-qs/` directory is gitignored, so none of this ever ends up in commits.

### Full Layout

```
quickstart-factory/.rhoai-qs/
├── mortgage-processor/
│   ├── pipeline/
│   │   ├── discovery-spec.yaml
│   │   ├── architecture-spec.yaml              # Also the handoff to scaffold
│   │   ├── architecture-spec-refined.yaml
│   │   ├── scaffold-spec.yaml
│   │   ├── scaffold-manifest.yaml              # Handoff to implement
│   │   ├── implementation-spec.yaml
│   │   ├── implementation-manifest.yaml        # Handoff to deploy
│   │   ├── deploy-spec.yaml
│   │   ├── deploy-manifest.yaml                # Handoff to security
│   │   ├── security-report.yaml                # Handoff to debug-and-deploy
│   │   ├── deploy-state.yaml                    # Handoff to document
│   │   └── doc-manifest.yaml                    # Handoff to ship
│   ├── prds/
│   │   └── prd.md
│   ├── designs/
│   │   └── design.md
│   ├── blog-drafts/
│   │   └── 2026-07-29.md
│   └── reports/
│       └── verify-deploy-2026-07-29.md
│
├── spending-transaction-monitor/
│   ├── pipeline/
│   │   └── ... (same shape)
│   ├── prds/
│   ├── designs/
│   └── blog-drafts/
│
└── _shared/
    └── reports/
        ├── grooming-report-2026-07-29.md         # Backlog grooming — not tied to one quickstart
        └── gap-analysis-2026-07-29.md            # Coverage gaps across the whole backlog — written
                                                     # before any slug exists; if the user picks one of
                                                     # the proposed ideas, discovery starts a new slug
                                                     # and can reference this report, no copy needed
```

Quickstart code lives as a sibling, not nested under `.rhoai-qs/`:

```
quickstart-factory/
├── .rhoai-qs/                     # bookkeeping — see above
├── mortgage-processor/            # separate GitHub repo, cloned here by rh-qs-scaffold
│   ├── .git/                      # remote: rh-ai-quickstart/mortgage-processor
│   ├── packages/api/
│   └── deploy/helm/
└── spending-transaction-monitor/  # separate GitHub repo, cloned here by rh-qs-scaffold
    ├── .git/
    └── packages/api/
```

## Constructing the Path

Once a skill has resolved the slug (see below), it constructs paths relative to the factory root:

```bash
SLUG="mortgage-processor"          # resolved via validation-skill
QS_PIPELINE=".rhoai-qs/${SLUG}/pipeline"
mkdir -p "$QS_PIPELINE"
```

Every skill that reads or writes pipeline files must use this path. Hardcoding paths outside `.rhoai-qs/<slug>/` — or forgetting the slug segment entirely — is a bug.

## Resolving the Quickstart Slug

Because `.rhoai-qs/` can hold multiple quickstarts at once, and each skill typically runs in its own separate chat session (no shared conversational memory to rely on), every skill delegates slug resolution to a dedicated subagent, **`validation-skill`**, as **Phase 0** — before any other work.

See [validation-skill-template.md](validation-skill-template.md) for the full resolution logic, inputs/outputs, and required `subagents/validation-skill-prompt.md` file every skill must have.

In short:

1. If the user named the quickstart in their message → use it.
2. Otherwise, list existing slugs under `.rhoai-qs/` (excluding `_shared`):
   - Exactly one → confirm with the user, then proceed.
   - Multiple → ask the user which one.
   - None → only valid if this is `rh-qs-discovery` starting a brand-new idea; otherwise, stop and report the error.

**Never guess silently when more than one quickstart exists.** A wrong guess means writing into the wrong quickstart's files.

## Nested Quickstart Repos

`rh-qs-scaffold` creates each quickstart as its own GitHub repository (`rh-ai-quickstart/<slug>`) and clones it as a folder at the `quickstart-factory` root — a sibling of `.rhoai-qs/`, `core/`, `docs/`, etc. Each is a fully independent git repository with its own remote, history, and CI.

Because these are separate repos physically nested inside the factory's directory tree, `rh-qs-scaffold` must:

1. `cd` to the `quickstart-factory` root before running `gh repo create <slug> --clone`, so the new repo lands as a direct child folder.
2. Add a single `/<slug>/` line to `quickstart-factory/.gitignore` for that quickstart, so the factory's own git never tries to track the nested repo's contents.

See `rh-qs-scaffold/SKILL.md` for the exact steps.

## File Categories

Four categories of pipeline files exist within `.rhoai-qs/<slug>/pipeline/`:

### 1. Spec files

Generated during the Analyze phase, consumed by validators and implementers.

| File | Producing Skill | Purpose |
|------|----------------|---------|
| `discovery-spec.yaml` | rh-qs-discovery | Interview plan |
| `architecture-spec.yaml` | rh-qs-architect | Component bill of materials |
| `scaffold-spec.yaml` | rh-qs-scaffold | Repo structure plan |
| `implementation-spec.yaml` | rh-qs-implement | Endpoints, schemas, services |
| `deploy-spec.yaml` | rh-qs-deploy | Chart deps, values, Containerfiles |
| `security-spec.yaml` | rh-qs-security | Scan targets, severity thresholds |
| `update-spec.yaml` | rh-qs-update | Change type, affected files |

After validation, a refined variant is written:

```
<skill>-spec.yaml          → initial spec
<skill>-spec-refined.yaml  → after validator feedback
```

### 2. Handoff manifests

Output artifacts that the next pipeline stage consumes. These are the inter-skill contracts.

| File | Producer | Consumer |
|------|----------|----------|
| `architecture-spec.yaml` | rh-qs-architect | rh-qs-scaffold |
| `scaffold-manifest.yaml` | rh-qs-scaffold | rh-qs-implement |
| `implementation-manifest.yaml` | rh-qs-implement | rh-qs-deploy |
| `deploy-manifest.yaml` | rh-qs-deploy | rh-qs-security |
| `security-report.yaml` | rh-qs-security | rh-qs-debug-and-deploy |
| `deploy-state.yaml` | rh-qs-debug-and-deploy | rh-qs-document |
| `doc-manifest.yaml` | rh-qs-document | rh-qs-ship |

See [pipeline-contracts.md](pipeline-contracts.md) for the YAML schema of each handoff file.

Note: `architecture-spec.yaml` serves double duty — it is both the architect's spec file and the handoff manifest to scaffold.

### 3. Internal working files

Files used within a single skill's execution, not consumed by other skills.

| File Pattern | Skill | Purpose |
|-------------|-------|---------|
| `test-spec.yaml` | rh-qs-implement | Test inventory from test-writer |
| `test-results.yaml` | rh-qs-implement | Test run outcomes |
| `deploy-validation.yaml` | rh-qs-deploy | Deploy reviewer results |
| `qs-security-code.yaml` | rh-qs-security | Code scanner findings |
| `qs-security-containers.yaml` | rh-qs-security | Container scanner findings |
| `qs-security-helm.yaml` | rh-qs-security | Helm scanner findings |
| `qs-security-deps.yaml` | rh-qs-security | Dependency scanner findings |
| `qs-deploy-analysis.yaml` | rh-qs-debug-and-deploy | Deploy command analysis |
| `qs-e2e-results.yaml` | rh-qs-debug-and-deploy | E2E test results |
| `qs-update-analysis.yaml` | rh-qs-update | Change analysis |
| `qs-update-impact.yaml` | rh-qs-update | Impact assessment |
| `qs-handoff-state.yaml` | rh-qs-handoff | Pipeline state detection |
| `qs-handoff-gaps.yaml` | rh-qs-handoff | Gap analysis |
| `qs-kb-components.yaml` | rh-qs-extract-knowledge | Component pattern extraction |
| `qs-kb-deployment.yaml` | rh-qs-extract-knowledge | Deployment pattern extraction |
| `qs-kb-industry.yaml` | rh-qs-extract-knowledge | Industry pattern extraction |
| `qs-kb-security.yaml` | rh-qs-extract-knowledge | Security pattern extraction |
| `qs-kb-update-plan.yaml` | rh-qs-extract-knowledge | KB dedup/update plan |
| `qs-kb-extraction-report.yaml` | rh-qs-extract-knowledge | Extraction summary |

### 4. Debug and fix files

Per-resource debug artifacts that accumulate during the debug loop.

| File Pattern | Skill | Purpose |
|-------------|-------|---------|
| `qs-debug-{resource}.yaml` | rh-qs-debug-and-deploy | Root-cause analysis per resource |
| `qs-fix-{resource}.yaml` | rh-qs-debug-and-deploy | Fix attempt records per resource |

Debug and fix files append `attempt_N` keys — they never overwrite previous attempts. This lets the debugger review what was already tried before proposing a new fix.

## Non-Pipeline Categories (also namespaced by slug)

Two more categories live under `.rhoai-qs/<slug>/`, alongside `pipeline/`, but are human-readable deliverables rather than skill-to-skill contracts:

| Directory | File | Producing Skill | Purpose |
|-----------|------|------------------|---------|
| `prds/` | `prd.md` | rh-qs-discovery | The PRD — the actual handoff artifact to rh-qs-architect |
| `designs/` | `design.md` | rh-qs-architect | The design doc — handoff artifact to rh-qs-scaffold |
| `blog-drafts/` | `<date>.md` | rh-qs-ship / blog-writer | Draft announcement, requires human review |
| `reports/` | `verify-deploy-<date>.md`, etc. | rh-qs-verify-deploy | Per-quickstart reports |

The slug isn't repeated in these filenames — the parent `.rhoai-qs/<slug>/` folder already disambiguates which quickstart a file belongs to. Filenames only need to name the *type* of artifact (`prd`, `design`) or add a date when multiple versions can exist over time (`blog-drafts/`, `reports/`).

Reports that are **not** about one specific quickstart — backlog grooming, gap analysis across the whole backlog — go in `.rhoai-qs/_shared/reports/` instead. Gap analysis in particular runs *before* any slug exists (it's surveying the whole backlog for ideas), so it's always written to `_shared/reports/gap-analysis-<date>.md`, never to a per-slug folder.

**Fallback for pre-existing quickstarts:** `blog-writer` can be asked to write about an already-completed quickstart that predates this convention (no `.rhoai-qs/<slug>/` folder exists for it). In that case, fall back to `.rhoai-qs/_shared/blog-drafts/<slug>-<date>.md` rather than creating a new slug folder just for a blog draft. Note the slug **is** included in the filename here, unlike the per-slug case above — `_shared/` mixes files from every quickstart, so the filename itself must disambiguate since the folder no longer does.

## Directory Layout Example

A fully populated pipeline directory mid-pipeline, for a single quickstart, looks like:

```
.rhoai-qs/mortgage-processor/pipeline/
├── discovery-spec.yaml
├── architecture-spec.yaml              # Also the handoff to scaffold
├── architecture-spec-refined.yaml
├── scaffold-spec.yaml
├── scaffold-manifest.yaml              # Handoff to implement
├── implementation-spec.yaml
├── implementation-spec-refined.yaml
├── test-spec.yaml                      # Internal: test inventory
├── test-results.yaml                   # Internal: test outcomes
├── implementation-manifest.yaml        # Handoff to deploy
├── deploy-spec.yaml
├── deploy-validation.yaml              # Internal: reviewer results
├── deploy-manifest.yaml                # Handoff to security
├── qs-security-code.yaml               # Internal: scanner output
├── qs-security-containers.yaml
├── qs-security-helm.yaml
├── qs-security-deps.yaml
├── security-report.yaml                # Handoff to debug-and-deploy
├── qs-deploy-analysis.yaml             # Internal: deploy analysis
├── deploy-state.yaml                   # Handoff to document
├── qs-debug-redis.yaml                 # Internal: per-resource debug
├── qs-fix-redis.yaml
├── qs-e2e-results.yaml                 # Internal: E2E results
├── doc-manifest.yaml                   # Handoff to ship
└── qs-kb-extraction-report.yaml        # Internal: KB extraction
```

## Cleanup Policy

### During execution

Skills do NOT clean up pipeline files during execution. Files accumulate throughout the pipeline run. This is intentional — it creates a full audit trail and supports resumability.

### User-controlled cleanup

Pipeline files persist until the user explicitly deletes them. To reset a single quickstart's pipeline state:

```bash
rm -rf .rhoai-qs/mortgage-processor/pipeline/
```

Or to remove everything for that quickstart (pipeline, PRD, design, blog drafts, reports):

```bash
rm -rf .rhoai-qs/mortgage-processor/
```

This is safe — it only removes that one quickstart's artifacts, not other quickstarts' data or `_shared/`. The user decides when cleanup happens — after shipping, after review, or never.

## Concurrency

### Different quickstarts

Different quickstarts share the same `quickstart-factory` repo, but each has its own namespaced folder under `.rhoai-qs/<slug>/` — so running skills for two different quickstarts (in separate sessions) is always safe, as long as each session correctly resolves its own slug (see [Resolving the Quickstart Slug](#resolving-the-quickstart-slug)).

### Same quickstart

Running the same quickstart concurrently (e.g., two agents both running `rh-qs-deploy` for `mortgage-processor` at the same time) is NOT safe. Both would write to the same `.rhoai-qs/mortgage-processor/pipeline/deploy-spec.yaml`, causing race conditions.

This is a known constraint. The factory is designed for one pipeline execution per quickstart at a time.

## Resumability

Since pipeline files are persistent, resumability works naturally. When a skill starts, after resolving its slug via `validation-skill`, it checks whether `.rhoai-qs/<slug>/pipeline/` already contains artifacts from a previous run:

```
1. Resolve the slug (validation-skill)
2. Check if .rhoai-qs/<slug>/pipeline/ exists
3. If it exists, check for artifacts from this skill and upstream skills
4. If upstream handoff manifests exist:
   → Check content_hash against the current upstream file (see below)
   → If hashes match: offer to resume from current stage
   → If hashes differ: warn that upstream has changed, offer to re-run
   → Or start fresh (rm -rf .rhoai-qs/<slug>/pipeline/)
5. If this skill's own spec exists:
   → Offer to reuse the existing spec
   → Or regenerate
```

### Staleness detection via content hash

Every spec and manifest records a `content_hash` of the upstream files it was built from (see [spec-as-contract.md](spec-as-contract.md)). When resuming, a skill hashes the current upstream file and compares it to the recorded hash. If they differ, the downstream artifact is stale — the upstream skill was re-run with different results.

This catches the common case where a user re-runs an early stage (e.g., `rh-qs-architect`) but forgets to re-run the stages that depend on it.

This enables the "pick up where you left off" pattern, especially useful when a skill fails mid-execution and the user restarts it.

## Relationship to Other Foundation Docs

- **[validation-skill-template.md](validation-skill-template.md)** — defines the required `validation-skill` subagent every skill uses for Phase 0 slug resolution
- **[pipeline-contracts.md](pipeline-contracts.md)** — defines the YAML schema for each handoff manifest
- **[spec-as-contract.md](spec-as-contract.md)** — defines the spec file format (category 1 above)
- **[skill-directory-structure.md](skill-directory-structure.md)** — each skill's `output-templates.md` defines the format of its temp file outputs; also lists `validation-skill-prompt.md` as a required subagent
