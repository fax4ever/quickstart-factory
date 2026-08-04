# Pipeline File Convention

This document defines how factory skills store and pass structured artifacts between pipeline stages, and where each quickstart's actual code lives. Everything for a given quickstart — pipeline specs, PRD, design doc, blog drafts, reports, **and its application code** — lives together in one place inside the **`quickstart-factory`** repo, namespaced by quickstart slug. This ensures a full audit trail that survives reboots and is deleted only when the user chooses.

## Why Everything Lives Under `.rhoai-qs/<slug>/`

Every skill's bookkeeping — specs, manifests, PRDs, designs, blog drafts, reports — and the quickstart's scaffolded application code (created by `rh-qs-scaffold`) live together under one folder: `quickstart-factory/.rhoai-qs/<slug>/`. One canonical location per quickstart means every skill can always find everything it needs without hopping between repos or guessing where things are on disk.

Because `.rhoai-qs/` now holds data for **every** quickstart ever worked on, every skill must first determine *which* quickstart the current session applies to. See [Resolving the Quickstart Slug](#resolving-the-quickstart-slug).

## Directory Structure

All quickstart-scoped files — bookkeeping and code alike — live under:

```
quickstart-factory/.rhoai-qs/<slug>/
```

**Example:** `quickstart-factory/.rhoai-qs/mortgage-processor/`

Two things that are **not** about any single quickstart live directly under `.rhoai-qs/` itself, as siblings of the slug folders — see [Cross-Cutting Locations](#cross-cutting-locations):

```
quickstart-factory/.rhoai-qs/reports/
quickstart-factory/.rhoai-qs/blog-drafts/
```

The `.rhoai-qs/` directory is gitignored by the factory repo, so none of this ever ends up in the factory's own commits. (The quickstart's own code, however, is committed to its own separate repo — see [Nested Quickstart Repos](#nested-quickstart-repos).)

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
│   ├── reports/
│   │   └── verify-deploy-2026-07-29.md
│   │
│   ├── packages/api/                            # ─┐
│   ├── packages/ui/                              #  │  the quickstart's own
│   ├── deploy/helm/                              #  │  application code —
│   ├── .github/workflows/                        #  │  a separate git repo,
│   ├── .git/                                     #  │  set up here by
│   ├── Makefile                                  #  │  rh-qs-scaffold
│   └── README.md                                 # ─┘
│
├── spending-transaction-monitor/
│   └── ... (same shape — pipeline + prd + design + code, all together)
│
├── reports/                                       ← cross-cutting, not tied to one quickstart
│   ├── gap-analysis-2026-07-29.md
│   └── grooming-report-2026-07-29.md
│
└── blog-drafts/                                   ← fallback for quickstarts predating this convention
    └── vllm-cpu-2025-03-11.md
```

There is no separate sibling folder for the code anymore — `.rhoai-qs/<slug>/` **is** the quickstart's repo root, with the factory's bookkeeping folders (`pipeline/`, `prds/`, `designs/`, `blog-drafts/`, `reports/`) sitting alongside the application code (`packages/`, `deploy/`, etc.) inside it.

## Nested Quickstart Repos

`rh-qs-scaffold` creates each quickstart as its own GitHub repository (`rh-ai-quickstart/<slug>`) and turns `quickstart-factory/.rhoai-qs/<slug>/` into that repo's working directory. This folder has its own `.git/`, its own remote, its own commit history and CI, independent of the factory repo.

**Important:** this folder already contains `pipeline/`, `prds/`, `designs/` from earlier phases by the time scaffold runs, so it is never empty — `git clone` (and `gh repo create ... --clone`) would refuse to clone into it. `rh-qs-scaffold` instead creates the GitHub repo separately, then runs `git init` + `git remote add` directly inside the existing folder (see `rh-qs-scaffold/SKILL.md` for the exact steps, including the template-repo variant).

### The bookkeeping folders are tracked, not gitignored

`pipeline/`, `prds/`, `designs/`, `blog-drafts/`, `reports/` live inside this same repo and are **committed and pushed like everything else** throughout development — they are deliberately **not** added to the quickstart's own `.gitignore`. This is intentional: it lets the team collaborate on the PRD, design doc, and pipeline state through normal pull requests (reviewing a design doc together, discussing an open question in the PRD, etc.), not just on whichever engineer's machine happened to run the factory pipeline.

`pipeline/`, `prds/`, `designs/`, and `reports/` get removed as a **final cleanup step in `rh-qs-ship`**, right before the quickstart is considered done — so the finished, published repo doesn't carry this internal bookkeeping, but the team had full visibility into it while the work was in progress. `blog-drafts/` is deliberately excluded from that same cleanup pass, since the draft is generated by `rh-qs-ship` itself and still needs human review before publication — it's left for the user to remove once the post actually goes out. See `rh-qs-ship/SKILL.md` for the exact steps.

This is a **separate concern** from the factory's own `.gitignore`, which simply ignores `.rhoai-qs/` as one blanket rule (see the factory's `.gitignore`) — git never looks inside an ignored directory, so it never notices there's another repo nested inside it, and the two repos' git histories don't interact.

See `rh-qs-scaffold/SKILL.md` for the exact repo-creation steps.

## Where Skills Run (and Why It Matters for Paths)

Skills fall into two groups, based on whether the quickstart's code repo exists yet:

**Before scaffolding** (`rh-qs-discovery`, `rh-qs-architect`, `rh-qs-scaffold` itself, plus factory-level skills like `pipeline-grooming`, `blog-writer`): run with their working directory at the **`quickstart-factory` root**. Paths are written in full: `.rhoai-qs/<slug>/prds/prd.md`.

**After scaffolding** (`rh-qs-implement`, `rh-qs-deploy`, `rh-qs-verify-deploy`, `rh-qs-document`, `rh-qs-test-suite`, `rh-qs-ship`): run with their working directory **inside** `.rhoai-qs/<slug>/` itself, since that's where the application code lives and where `make`/`helm`/etc. need to run. From there:
- Reading/writing the quickstart's own bookkeeping files uses **plain relative paths, no prefix**: `prds/prd.md`, `designs/design.md`, `pipeline/deploy-spec.yaml`, `reports/...`
- Listing *other* quickstarts (for slug resolution) requires going up one level: `ls ../` lists every slug folder plus the two cross-cutting folders (`reports/`, `blog-drafts/`) as siblings.

## Resolving the Quickstart Slug

Because `.rhoai-qs/` can hold multiple quickstarts at once, and each skill typically runs in its own separate chat session (no shared conversational memory to rely on), every skill delegates slug resolution to a dedicated subagent, **`validation-skill`**, as **Phase 0** — before any other work.

See [validation-skill-template.md](validation-skill-template.md) for the full resolution logic, inputs/outputs, and required `subagents/validation-skill-prompt.md` file every skill must have.

In short:

1. If the user named the quickstart in their message → use it.
2. Otherwise, list existing slugs under `.rhoai-qs/` (excluding the two cross-cutting folders, `reports/` and `blog-drafts/`):
   - Exactly one → confirm with the user, then proceed.
   - Multiple → ask the user which one.
   - None → only valid if this is `rh-qs-discovery` starting a brand-new idea; otherwise, stop and report the error.

**Never guess silently when more than one quickstart exists.** A wrong guess means writing into the wrong quickstart's files.

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

Two more categories live under `.rhoai-qs/<slug>/`, alongside `pipeline/` and the application code, but are human-readable deliverables rather than skill-to-skill contracts:

| Directory | File | Producing Skill | Purpose |
|-----------|------|------------------|---------|
| `prds/` | `prd.md` | rh-qs-discovery | The PRD — the actual handoff artifact to rh-qs-architect |
| `designs/` | `design.md` | rh-qs-architect | The design doc — handoff artifact to rh-qs-scaffold |
| `blog-drafts/` | `<date>.md` | rh-qs-ship / blog-writer | Draft announcement, requires human review |
| `reports/` | `verify-deploy-<date>.md`, etc. | rh-qs-verify-deploy | Per-quickstart reports |

The slug isn't repeated in these filenames — the parent `.rhoai-qs/<slug>/` folder already disambiguates which quickstart a file belongs to. Filenames only need to name the *type* of artifact (`prd`, `design`) or add a date when multiple versions can exist over time (`blog-drafts/`, `reports/`).

## Cross-Cutting Locations

Two folders sit directly under `.rhoai-qs/`, as siblings of the slug folders — not inside any of them, since they're not about one specific quickstart:

```
.rhoai-qs/
├── mortgage-processor/       ← a slug folder
├── spending-transaction-monitor/  ← another slug folder
├── reports/                  ← cross-cutting reports
└── blog-drafts/              ← fallback blog drafts
```

**`.rhoai-qs/reports/`** — reports that survey the whole backlog, not one quickstart:
- `gap-analysis-<date>.md` from `rh-qs-discovery`'s gap analysis mode — this runs *before* any slug exists (it's proposing new quickstart ideas), so there's no slug folder to put it in.
- `grooming-report-<date>.md` from `pipeline-grooming` — scores and prioritizes every backlog issue at once.

Neither filename includes a slug, since there isn't one to include.

**`.rhoai-qs/blog-drafts/`** — a fallback for `blog-writer` when asked to draft a post for a quickstart that predates this whole convention (no `.rhoai-qs/<slug>/` folder exists for it, because it was built before the factory adopted this pipeline). This case genuinely **is** about one specific quickstart — the file just can't live in a slug folder that was never created. Its filename **does** include the slug (`vllm-cpu-2025-03-11.md`) to disambiguate itself, since this folder mixes fallback drafts from multiple old quickstarts together.

> **Open question, not yet resolved:** it isn't certain how often either of these two paths will actually see use in practice — gap analysis and grooming reports may end up being requested rarely, and most quickstarts going forward should have their own slug folder from the start (making the `blog-drafts/` fallback increasingly rare too). Revisit whether this dedicated structure is still earning its complexity once real usage data exists.

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

Pipeline files persist until the user explicitly deletes them. To reset a single quickstart's pipeline state without touching its code:

```bash
rm -rf .rhoai-qs/mortgage-processor/pipeline/
```

To remove everything for that quickstart, **including its cloned code repo**:

```bash
rm -rf .rhoai-qs/mortgage-processor/
```

This is safe — it only removes that one quickstart's folder, not other quickstarts' data or the cross-cutting `reports/`/`blog-drafts/` folders. The user decides when cleanup happens — after shipping, after review, or never. Note the code itself still exists on GitHub (`rh-ai-quickstart/<slug>`) even after deleting the local clone.

This is a different, complementary concern from the **ship-time cleanup** in `rh-qs-ship` (see [Nested Quickstart Repos](#nested-quickstart-repos)): that one removes the bookkeeping folders from the quickstart's own git history as a standard, non-optional step before shipping, so the published repo doesn't carry them. This section is about the *local* `.rhoai-qs/<slug>/` folder in the factory — always user-controlled, never automatic.

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
