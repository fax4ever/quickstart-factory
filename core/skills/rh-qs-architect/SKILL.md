---
name: rh-qs-architect
description: Architecture phase for AI Quickstarts. Reads the PRD, maps requirements to OpenShift AI 3.4 and ai-architecture-charts, presents a bill of materials, generates a Mermaid diagram, and produces a design document. Use when a PRD exists under .rhoai-qs/<slug>/prds/.
---

# rh-qs-architect

**Category:** `architecture/`  

## Trigger

PRD exists from `rh-qs-discovery` at `.rhoai-qs/<slug>/prds/prd.md`

## What it does

0. Resolves which quickstart this session is for (see Phase 0 in Workflow) before touching any files
1. Reads the PRD and maps requirements to **Red Hat OpenShift AI 3.4** features
2. Maps requirements to **ai-architecture-charts** components (see [references/ai-architecture-charts.md](./references/ai-architecture-charts.md))
3. Presents a clear **bill of materials**, e.g.:
   > I will create: React frontend, FastAPI backend, PostgreSQL with pgvector, Llama Stack for orchestration, llm-service for model serving
4. Asks decision points: Llama Stack? Local model or remote endpoint? MinIO?
5. Generates a **Mermaid architecture diagram** (see [references/diagram-guide.md](./references/diagram-guide.md))
6. Documents which ai-architecture-charts will be used as Helm subchart dependencies
7. Specifies **testing strategy** (unit/integration/e2e) based on components

## Workflow

### Phase 0: Resolve Quickstart Context

Before reading any files, resolve which quickstart this session is for. Run `ls .rhoai-qs/ 2>/dev/null` (excluding `reports` and `blog-drafts`) and spawn the **validation-skill subagent**:

```python
Agent(
    description="Resolve which quickstart this architecture session is for",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-architect/subagents/validation-skill-prompt.md

User message: {user_message}
Existing slugs: {existing_slugs}
Is entry point: false
Calling skill: rh-qs-architect
"""
)
```

Handle the result per [validation-skill-template.md](../../../docs/foundation/validation-skill-template.md#main-agent-handling). If `resolution: error` (no slugs exist), tell the user to run `rh-qs-discovery` first and stop.

### Remaining phases

```
- [ ] 1. Read PRD from .rhoai-qs/<slug>/prds/prd.md
- [ ] 2. Map to OpenShift AI 3.4 features
- [ ] 3. Select ai-architecture-charts (include/exclude matrix)
- [ ] 4. Present bill of materials — get user approval
- [ ] 5. Generate Mermaid architecture diagram
- [ ] 6. Define testing strategy per component
- [ ] 7. Write design document
- [ ] 8. Run **`rh-qs-secure`** — record Security considerations (cluster access + application security)
```

## Component include/exclude matrix

| Component | Include when |
|-----------|--------------|
| `packages/api` | Always (unless pure static demo) |
| `packages/ui` | User-facing browser experience |
| `packages/db` | Persistent or relational data |
| `packages/ingestion` | RAG: documents loaded into vector store |
| llama-stack | Agents, multi-provider LLM, safety |
| llm-service | On-cluster vLLM inference |
| pgvector | RAG or semantic search |
| minio | Document upload, file storage |
| mcp-servers | External tool access for agents |
| ingestion-pipeline | Automated document chunking/embedding |

## Technology defaults

Present as defaults; override only when PRD requires it.

| Layer | Default |
|-------|---------|
| Frontend | React 19, TypeScript, Vite, TanStack Router/Query |
| Backend | UV, Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 async |
| Database | PostgreSQL |
| Vector DB | pgvector |
| LLM orchestration | Llama Stack (optional — confirm) |
| Model serving | vLLM via llm-service chart |
| Object storage | MinIO (when needed) |
| Local runtime | podman-compose |
| Monorepo | Turborepo, pnpm, uv |
| Deploy platform | Red Hat OpenShift AI 3.4 |

## Testing strategy

| Level | Tool | Scope | Runs when |
|-------|------|-------|-----------|
| Unit (Python) | pytest | Routes, schemas, services | Every PR (`pr-checks` / `ci.yaml`) |
| Unit (TypeScript) | vitest | Components, hooks | Every PR |
| Integration | pytest + Kind/compose | API + DB + in-cluster services | PR E2E workflow (`rh-qs-test-suite`) |
| E2E / LLM evals | evaluations harness | Agent quality, RAG responses | `pull_request_target` or nightly |
| Helm | helm lint + kubeconform | Exported manifests valid | Every PR |

Document which profile (minimal / standard / agent+evals / release train) applies—see **`rh-qs-test-suite`** references.

## Output

**`.rhoai-qs/<slug>/designs/design.md`** containing:

```markdown
# <Title> — Design
## Component list (include/exclude matrix)
## ai-architecture-charts selections (with versions)
## Red Hat AI feature mapping
## Mermaid architecture diagram
## Technology decisions (defaults or overrides)
## Testing strategy per component
## Repository structure notes
## Security considerations (from rh-qs-secure)
```

Get user approval before `rh-qs-scaffold`.

## Next skill

When design is approved → **`rh-qs-scaffold`**

## References

- [ai-architecture-charts mapping](./references/ai-architecture-charts.md)
- [Architecture diagram guide](./references/diagram-guide.md)
- [Security: rh-qs-secure](../rh-qs-secure/SKILL.md)
- [GitHub workflow catalog](../rh-qs-test-suite/references/workflow-catalog.md)
- [subagents/validation-skill-prompt.md](./subagents/validation-skill-prompt.md) — pass by file path only, do NOT read directly
