---
name: rh-qs-implement
description: Implement a working AI Quickstart vertical slice from an approved design and scaffold. Builds FastAPI backend, React UI, database, RAG ingestion, and tests. Use when the scaffold repo exists from rh-qs-scaffold.
---

# rh-qs-implement

**Category:** `implementation/`

## Trigger

Scaffold exists from `rh-qs-scaffold`

## Where This Runs

This skill works inside the scaffolded quickstart's own repo (e.g. `mortgage-processor/`, a sibling folder of `quickstart-factory`), since that's where the application code lives. Pipeline files (PRD, design doc, specs, manifests) stay in the parent `quickstart-factory/.rhoai-qs/<slug>/` — reference them as `../.rhoai-qs/<slug>/...` relative to the quickstart repo root. See [pipeline-convention.md](../../../docs/foundation/pipeline-convention.md#nested-quickstart-repos).

## What it does

Builds the **minimal vertical slice** that proves the use case end-to-end:

| Layer | Deliverables |
|-------|-------------|
| **Backend (FastAPI)** | Health route, domain routes from PRD user flows, Pydantic schemas, async SQLAlchemy, pytest tests |
| **Frontend (React)** | Primary user journey, TanStack Router/Query, `VITE_API_BASE_URL`, vitest tests |
| **Database** | SQLAlchemy models in `packages/db`, Alembic migration, `DATABASE_URL` connection |
| **RAG (if applicable)** | Ingestion job/CLI, embedding pipeline, pgvector schema |
| **Chat (if applicable)** | WebSocket or SSE streaming, message history |

**Conventions:** No feature creep beyond PRD scope. No tutorial comments in code. Run `make lint && make test` before declaring done.

## Workflow

### Phase 0: Resolve Quickstart Context

Before reading any files, resolve which quickstart this session is for. Run `ls ../.rhoai-qs/ 2>/dev/null` (excluding `_shared`) and spawn the **validation-skill subagent**:

```python
Agent(
    description="Resolve which quickstart this implementation session is for",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-implement/subagents/validation-skill-prompt.md

User message: {user_message}
Existing slugs: {existing_slugs}
Is entry point: false
Calling skill: rh-qs-implement
"""
)
```

Handle the result per [validation-skill-template.md](../../../docs/foundation/validation-skill-template.md#main-agent-handling). If `resolution: error`, tell the user the scaffold step must run first and stop.

### Remaining phases

```
- [ ] 1. Read PRD + design doc
- [ ] 2. Implement backend vertical slice
- [ ] 3. Implement frontend vertical slice
- [ ] 4. Implement database + migrations
- [ ] 5. Implement RAG ingestion (if in design)
- [ ] 6. Implement chat interface (if in design)
- [ ] 7. Run quality gates
```

### Backend

- `/health` first, then domain routes
- Pydantic schemas in `src/schemas/`
- Async SQLAlchemy via `packages/db`
- pytest happy-path coverage

### Frontend

- One primary route calling API via `VITE_API_BASE_URL`
- Loading and error states
- Vitest for critical hooks/components

### Database

- Models in `packages/db`
- Alembic migration(s)
- No duplicate models in API package

### RAG ingestion

- Idempotent job or CLI in `packages/ingestion/`
- Chunk → embed → write to pgvector

## Technology defaults

| Layer | Default stack |
|-------|---------------|
| Frontend | React 19, TypeScript, Vite, TanStack Router/Query, Vitest, ESLint + Prettier |
| Backend | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 async, pytest |
| Database | PostgreSQL (via `packages/db` + Alembic) |
| Vector DB | pgvector — unless user specifies otherwise |
| LLM orchestration | Llama Stack (optional, chosen in architect phase) |
| Model serving | vLLM via llm-service chart (if on-cluster models needed) |
| Monorepo | Turborepo, pnpm (Node), uv (Python) |
| Local runtime | compose.yml + podman-compose |
| Containers | Containerfile per package (multi-stage, non-root) |

## Quality gates

```bash
make lint
make test
```

Also verify:

- No committed `venv/`, `node_modules/`, `__pycache__/`, or `.env`
- Health endpoints respond locally (`make dev` + curl)
- No leftover `ai-quickstart-template` strings except upstream links

## What not to include

- Storybook, extra CRUD, admin UIs unless in PRD
- Helm subchart wiring (that is `rh-qs-deploy`)
- Real secrets or production credentials

## Output

Working application code with `make lint && make test` succeeding.

## Next skill

When vertical slice works locally → **`rh-qs-verify-build`**

## References

- [Monorepo layout](./references/template-layout.md)
- [Design checklist](./references/design-checklist.md)
- PRD: `../.rhoai-qs/<slug>/prds/prd.md`
- Design: `../.rhoai-qs/<slug>/designs/design.md`
- [subagents/validation-skill-prompt.md](./subagents/validation-skill-prompt.md) — pass by file path only, do NOT read directly
