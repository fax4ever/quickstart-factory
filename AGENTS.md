# Quickstart Factory — Project Context

## AI Quickstarts vs AI Examples

| Aspect | AI Quickstarts | AI Examples |
|--------|----------------|-------------|
| **Purpose** | Production-ready reference implementations for Red Hat AI/ML platforms | Educational, experimental demos (Jehlum's domain) |
| **Audience** | Enterprises adopting Red Hat OpenShift AI, RHOAI | Developers exploring AI patterns |
| **Lifecycle** | Idea → Groomed → In Progress → Done | Outside scope |

## Greenfield pipeline

For building a new quickstart end-to-end, see [docs/NEW_QUICKSTART_SKILLS.md](docs/NEW_QUICKSTART_SKILLS.md). Key rule: Agents do not run `oc`/`kubectl` — use Helm/Makefile targets per **`rh-qs-secure`**.

Everything for a quickstart — pipeline state, PRD, design, blog drafts, reports, **and its scaffolded application code** — lives together under `.rhoai-qs/<slug>/` inside this repo. The code is still its own separate GitHub repo (cloned there by `rh-qs-scaffold`), just nested inside this folder rather than sitting next to it. See [pipeline-convention.md](docs/foundation/pipeline-convention.md). Every skill resolves which quickstart it's working on via the `validation-skill` subagent before doing anything else — see [validation-skill-template.md](docs/foundation/validation-skill-template.md).

## Foundation Docs (for skill implementation)

When implementing or upgrading skills (EPICs 04+), consult these convention docs in `docs/foundation/`:

| Doc | What it defines | When to use |
|-----|----------------|-------------|
| `skill-directory-structure.md` | Canonical layout: SKILL.md, subagents/, reasoning-guardrails.md, spec-template.md | Creating or restructuring a skill directory |
| `spec-as-contract.md` | YAML spec format, validation flow, refinement loop, staleness detection | Writing a spec-template.md or implementing the spec → validate → implement workflow |
| `pipeline-convention.md` | `.rhoai-qs/<slug>/` directory (bookkeeping + the quickstart's own code, together), file categories, top-level `reports/`/`blog-drafts/` for cross-cutting cases, cleanup, resumability | Reading/writing any pipeline, PRD, design, or report file |
| `validation-skill-template.md` | Required `subagents/validation-skill-prompt.md` — Phase 0 slug resolution | Every skill, before touching any `.rhoai-qs/` file |
| `pipeline-contracts.md` | YAML schemas for all 7 handoff files (architecture-spec through doc-manifest) | Producing or consuming a handoff manifest between skills |
| `reasoning-guardrails-template.md` | Template for reasoning-guardrails.md — concern areas, not checklists | Writing a skill's reasoning-guardrails.md |
| `acceptance-criteria.md` | User-approved acceptance criteria in specs, approval matrix, post-validation | Adding acceptance_criteria to a spec or implementing post-validation |

## Resource Sync

After creating or editing skills:

```bash
bash core/scripts/sync-clients.sh
```

## Core Principles

- **Simplicity first:** Make each change as simple as possible.
- **No laziness:** Find root causes; no temporary fixes; senior standards.
- **Minimal impact:** Changes should only touch what is necessary.
- **Verify before done:** Never mark a task complete without running real validation and reviewing output.
