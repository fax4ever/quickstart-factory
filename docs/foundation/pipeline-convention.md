# Pipeline File Convention

This document defines how factory skills store and pass structured artifacts between pipeline stages. All pipeline files live in a persistent, project-scoped directory inside the quickstart repo — ensuring a full audit trail that survives reboots and is deleted only when the user chooses.

## Directory Structure

All pipeline files live under:

```
{project}/.rhoai-qs/pipeline/
```

**Example:** `spending-transaction-monitor/.rhoai-qs/pipeline/`

The `.rhoai-qs/` directory is gitignored by default, so pipeline files never end up in commits.

## Constructing the Path

Skills construct the pipeline path relative to the project root:

```bash
QS_PIPELINE=".rhoai-qs/pipeline"
mkdir -p "$QS_PIPELINE"
```

Every skill that reads or writes pipeline files must use this path. Hardcoding paths outside `.rhoai-qs/pipeline/` is a bug.

## File Categories

Four categories of pipeline files exist within `.rhoai-qs/pipeline/`:

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

## Directory Layout Example

A fully populated pipeline directory mid-pipeline looks like:

```
.rhoai-qs/pipeline/
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

Pipeline files persist until the user explicitly deletes them. To reset a project's pipeline state:

```bash
rm -rf .rhoai-qs/pipeline/
```

This is safe — it only removes pipeline artifacts, not other `.rhoai-qs/` contents. The user decides when cleanup happens — after shipping, after review, or never.

## Concurrency

### Different quickstarts

Different quickstarts are different repos, so they each have their own `.rhoai-qs/pipeline/`. Running skills for two quickstarts simultaneously is always safe.

**Exception — `rh-qs-discovery`:** Discovery runs in the factory repo before a quickstart repo exists, so multiple ideas may coexist in the same workspace. To avoid collisions, discovery namespaces its spec by slug: `.rhoai-qs/<slug>/pipeline/discovery-spec.yaml`. All other skills run inside the quickstart's own repo and use the flat `.rhoai-qs/pipeline/` path.

### Same quickstart

Running the same quickstart concurrently (e.g., two agents both running `rh-qs-deploy` for `spending-transaction-monitor`) is NOT safe. Both would write to the same `.rhoai-qs/pipeline/deploy-spec.yaml`, causing race conditions.

This is a known constraint. The factory is designed for one pipeline execution per quickstart at a time.

## Resumability

Since pipeline files are persistent, resumability works naturally. When a skill starts, it checks whether `.rhoai-qs/pipeline/` already contains artifacts from a previous run:

```
1. Check if .rhoai-qs/pipeline/ exists
2. If it exists, check for artifacts from this skill and upstream skills
3. If upstream handoff manifests exist:
   → Check content_hash against the current upstream file (see below)
   → If hashes match: offer to resume from current stage
   → If hashes differ: warn that upstream has changed, offer to re-run
   → Or start fresh (rm -rf .rhoai-qs/pipeline/)
4. If this skill's own spec exists:
   → Offer to reuse the existing spec
   → Or regenerate
```

### Staleness detection via content hash

Every spec and manifest records a `content_hash` of the upstream files it was built from (see [spec-as-contract.md](spec-as-contract.md)). When resuming, a skill hashes the current upstream file and compares it to the recorded hash. If they differ, the downstream artifact is stale — the upstream skill was re-run with different results.

This catches the common case where a user re-runs an early stage (e.g., `rh-qs-architect`) but forgets to re-run the stages that depend on it.

This enables the "pick up where you left off" pattern, especially useful when a skill fails mid-execution and the user restarts it.

## Relationship to Other Foundation Docs

- **[pipeline-contracts.md](pipeline-contracts.md)** — defines the YAML schema for each handoff manifest
- **[spec-as-contract.md](spec-as-contract.md)** — defines the spec file format (category 1 above)
- **[skill-directory-structure.md](skill-directory-structure.md)** — each skill's `output-templates.md` defines the format of its temp file outputs
