# Skill Directory Structure Standard

This document defines the canonical directory layout that every upgraded factory skill must follow. It is the foundation for all skill EPICs in ADR-001.

## Canonical Layout

```
rh-qs-<name>/
├── SKILL.md                    # Orchestrator instructions (agentskills.io compliant)
├── reasoning-guardrails.md     # Concern areas for organic self-checking
├── spec-template.md            # YAML spec structure definition
├── output-templates.md         # Output format definitions (or output-templates/ directory)
├── subagents/
│   ├── README.md                    # Subagent index: roles, inputs, outputs
│   ├── validation-skill-prompt.md   # Required — Phase 0 quickstart slug resolution
│   └── <role>-prompt.md             # One self-contained prompt per subagent
├── knowledge-base/             # Optional — scored pattern retrieval
│   ├── README.md
│   └── <category>/
│       └── <pattern>.md
└── references/                 # Optional — static reference material
    └── <topic>.md
```

## File Descriptions

### SKILL.md (required)

The skill entry point and orchestrator. Must comply with the [agentskills.io](https://agentskills.io) open standard and pass `skill-validator --strict --allow-extra-frontmatter`.

**YAML frontmatter** (required):

```yaml
---
name: rh-qs-<name>
description: One-line description (max 1024 chars)
argument-hint: <usage hint for the user>
allowed-tools: Bash, Read, Write, Edit, Agent, ...
---
```

**Body structure:**

- **Goal** — what the skill achieves
- **Input** — what the user or previous skill provides
- **Supporting Documents** — split into what the main agent reads vs what subagents read
- **Workflow** — numbered phases, each delegating heavy work to subagents
- **Guidelines** — DO/DON'T rules, error handling, success criteria

**The orchestrator role:** SKILL.md coordinates the workflow — it spawns subagents, reads their outputs, routes failures, manages feedback loops, and interacts with the user. It does NOT perform the heavy analytical or generative work itself.

### reasoning-guardrails.md (required)

Concern areas the agent should reason about organically during execution. These are NOT checklists — they are a mental framework to ensure critical aspects are not overlooked while thinking freely.

See [reasoning-guardrails-template.md](reasoning-guardrails-template.md) for the template and conventions.

### spec-template.md (required)

Defines the YAML structure for the skill's spec file. The spec is the contract between analysis and implementation — it describes *what* the skill will do before any files are modified.

See [spec-as-contract.md](spec-as-contract.md) for the spec-as-contract workflow and field conventions.

### output-templates.md (required)

Defines the format of artifacts the skill produces. Two variants are acceptable:

1. **Single file** (`output-templates.md`) — when the skill produces a small number of output types. Contains all templates in one document with clear section separators.

2. **Directory** (`output-templates/`) — when the skill produces many structured outputs (e.g., `bp-deploy-and-debug` uses 6 separate template files). Each file defines one output schema.

Both variants serve the same purpose: subagents and the main agent read the relevant template before generating output to ensure format consistency.

### subagents/ (required)

Contains the prompts that drive delegated work. Every skill has this directory, at minimum for `validation-skill-prompt.md`.

#### subagents/validation-skill-prompt.md (required, every skill)

Resolves which quickstart (by slug) the current session applies to, as **Phase 0** before any other work. Required because `.rhoai-qs/` now holds pipeline state for every quickstart ever worked on, namespaced by slug — no skill can safely assume "the quickstart" without checking first. See [validation-skill-template.md](validation-skill-template.md) for the full resolution logic and required inputs/outputs.

#### subagents/README.md (required)

An index of all subagent roles. For each subagent, document:

| Field | Description |
|-------|-------------|
| **Name** | File name (e.g., `blueprint-analyzer-prompt.md`) |
| **Purpose** | What this subagent does |
| **Input** | What the main agent passes to it |
| **Output** | What it returns (format and schema) |
| **When used** | Which workflow phase invokes it |
| **Why subagent** | Why this work is delegated (context savings, parallelism, focus) |

#### subagents/\<role\>-prompt.md

Each subagent prompt is a self-contained document. The subagent receives this file path and reads it independently — it must contain everything the subagent needs without relying on the main agent's context.

**Naming convention:** `<role>-prompt.md` — lowercase, hyphenated, descriptive of the role. Examples: `test-writer-prompt.md`, `helm-wiring-prompt.md`, `security-scanner-prompt.md`.

**Standard structure:**

```markdown
---
description: One-line description of the subagent's role
---

# <Role Name>

## Your Role
[2-3 paragraphs: what you are, why this matters, how your output is used]

## Instructions

**Input Parameters:**
- `{param_1}`: description
- `{param_2}`: description

### Step 1: ...
### Step 2: ...

## Output
[JSON schema, YAML schema, or markdown format specification]
[Include a concrete example]
```

### knowledge-base/ (optional)

A directory of tagged, scored knowledge files used for pattern retrieval. Only skills that need KB-driven decision-making include this directory (e.g., `rh-qs-architect`, `rh-qs-extract-knowledge`).

Each KB file uses YAML frontmatter for retrieval scoring. See the Knowledge Base Specification in ADR-001 for the frontmatter schema.

### references/ (optional)

Static reference material the skill or its subagents may consult. Unlike knowledge-base files, references are not scored or retrieved dynamically — they are read directly when needed.

Existing skills already use this pattern (e.g., `rh-qs-deploy/references/helm-llamastack.md`, `rh-qs-architect/references/ai-architecture-charts.md`).

## Critical Design Rule: Subagent Delegation

**The main agent must NOT read subagent prompt files.** It passes them by file path to the Task/Agent tool. This saves 60-70% of context window.

**Correct — main agent passes file path:**

```python
Agent(
    description="Analyze blueprint structure",
    prompt=f"""
Read and follow instructions from:
core/skills/architecture/rh-qs-architect/subagents/architecture-analyzer-prompt.md

PRD path: {prd_path}
"""
)
```

**Wrong — main agent loads subagent instructions into its own context:**

```python
instructions = Read("subagents/architecture-analyzer-prompt.md")
Agent(prompt=f"{instructions}\n\nPRD path: {prd_path}")
```

**What the main agent reads directly:**

| File | When |
|------|------|
| `SKILL.md` | Always (it IS the main agent's instructions) |
| `reasoning-guardrails.md` | During reasoning phases |
| `spec-template.md` | When generating or validating specs |
| `output-templates.md` | When generating final outputs |
| `knowledge-base/README.md` | When setting up KB retrieval |
| `references/*.md` | When specific reference data is needed |

**What only subagents read:**

| File | Read by |
|------|---------|
| `subagents/<role>-prompt.md` | The spawned subagent only |

## Fully Populated Example: rh-qs-implement

This shows what a skill directory looks like when fully populated, using `rh-qs-implement` as the example (the most complex pipeline skill with 4 subagents and a test feedback loop).

```
core/skills/implementation/rh-qs-implement/
├── SKILL.md
│   # Orchestrates the test loop:
│   #   1. Spawn test-writer → generates tests
│   #   2. Run `make test`
│   #   3. Route failures to backend-implementer or frontend-implementer
│   #   4. Re-run tests
│   #   5. If still failing, resume test-writer to review
│   #   Max 3 full loops
│
├── reasoning-guardrails.md
│   # Concern areas: vertical slice, hardcoded values,
│   # error handling, async consistency, security basics
│
├── spec-template.md
│   # Defines .rhoai-qs/<slug>/pipeline/implementation-spec.yaml:
│   #   endpoints, schemas, services, DB models, UI routes
│
├── output-templates.md
│   # Defines implementation-manifest.yaml format:
│   #   endpoints list, DB models, packages, test coverage
│
├── subagents/
│   ├── README.md
│   │   # Index of 5 subagents with roles, I/O, phases
│   │
│   ├── validation-skill-prompt.md
│   │   # Phase 0 — resolves which quickstart slug this session is for
│   │
│   ├── test-writer-prompt.md
│   │   # Generates tests from PRD + architecture + scaffold manifest
│   │   # On resume: reads test-results.yaml, adjusts tests only
│   │   # if over-specified or wrong
│   │
│   ├── backend-implementer-prompt.md
│   │   # Implements FastAPI backend from spec
│   │   # Receives test failure context for targeted fixes
│   │
│   ├── frontend-implementer-prompt.md
│   │   # Implements React frontend from spec
│   │   # Runs in parallel with backend-implementer
│   │
│   └── db-schema-prompt.md
│       # Generates SQLAlchemy models + Alembic migration
│       # Runs first (dependency for backend/frontend)
│
└── references/
    ├── design-checklist.md      # Existing reference
    └── template-layout.md       # Existing reference
```

**Workflow summary for this skill:**

```
Phase 0: Resolve quickstart slug (validation-skill)
Phase 1: Read scaffold-manifest.yaml + architecture-spec.yaml from .rhoai-qs/<slug>/pipeline/
Phase 2: Generate implementation-spec.yaml → user approval
Phase 3: Spawn db-schema subagent (dependency)
Phase 4: Spawn backend-implementer + frontend-implementer in parallel
Phase 5: Spawn test-writer → generates tests
Phase 6: Run `make test` → route failures → fix loop (max 3)
Phase 7: Write implementation-manifest.yaml to .rhoai-qs/<slug>/pipeline/
```

## Minimal Example: rh-qs-discovery

Not every skill needs the full set. Discovery is a lighter skill with 2 subagents and no knowledge base:

```
core/skills/inception/rh-qs-discovery/
├── SKILL.md
├── reasoning-guardrails.md
├── spec-template.md
├── output-templates.md
├── subagents/
│   ├── README.md
│   ├── validation-skill-prompt.md
│   ├── prd-structurer-prompt.md
│   └── backlog-matcher-prompt.md
└── references/
```

## agentskills.io Compliance

Every skill's `SKILL.md` must pass validation:

```bash
skill-validator --strict --allow-extra-frontmatter core/skills/<category>/<skill-name>/SKILL.md
```

Subagent prompts in `subagents/` are NOT standalone skills and are NOT required to follow the agentskills.io spec. They are internal implementation details of their parent skill.

The existing CI target `make skills-check` validates all skills:

1. `validate-skills.sh` — layout: `core/skills/<category>/<skill-name>/SKILL.md`
2. `validate-skills-spec.sh` — agentskills.io via `skill-validator --strict --allow-extra-frontmatter`
3. `sync-clients.sh` — symlink into `.cursor/`, `.claude/`, `.codex/`, `.gemini/`
4. Symlink count check — all skills discoverable by all clients

## Migration Path for Existing Skills

Current skills are flat `SKILL.md` files with optional `references/` and `scripts/` directories. To upgrade a skill:

1. Keep `SKILL.md` but rewrite it as an orchestrator
2. Add `reasoning-guardrails.md` with skill-specific concern areas
3. Add `spec-template.md` defining the skill's spec YAML, using `.rhoai-qs/<slug>/pipeline/` paths per [pipeline-convention.md](pipeline-convention.md)
4. Add `output-templates.md` defining output formats
5. Create `subagents/` with `README.md`, `validation-skill-prompt.md` (Phase 0 slug resolution, see [validation-skill-template.md](validation-skill-template.md)), and one `<role>-prompt.md` per delegated task
6. Move heavy logic from `SKILL.md` into subagent prompts
7. Add `knowledge-base/` only if the skill needs scored retrieval
8. Preserve existing `references/` and `scripts/` directories
9. Run `skill-validator --strict` to verify compliance

## Relationship to Other Foundation Docs

- **[pipeline-convention.md](pipeline-convention.md)** — defines the `.rhoai-qs/<slug>/` directory that `spec-template.md` and `output-templates.md` write into
- **[validation-skill-template.md](validation-skill-template.md)** — the required `subagents/validation-skill-prompt.md` every skill must have
- **[reasoning-guardrails-template.md](reasoning-guardrails-template.md)** — template for `reasoning-guardrails.md`
- **[spec-as-contract.md](spec-as-contract.md)** — the spec → validate → implement workflow that `spec-template.md` feeds into
