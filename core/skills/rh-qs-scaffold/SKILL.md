---
name: rh-qs-scaffold
description: Scaffold a new AI Quickstart GitHub repository with CI/CD, linting, testing frameworks, monorepo structure, branch protection, and Makefile targets. Use when a design document is approved from rh-qs-architect.
---

# rh-qs-scaffold

**Category:** `github/`  
**Replaces:** rh-qs-repo-bootstrap, rh-qs-github-project-management, rh-qs-cicd-automation, rh-qs-testing-validation

## Trigger

Design document approved from `rh-qs-architect` at `.rhoai-qs/<slug>/designs/design.md`

## What it does

1. Creates a local GitHub repository under git users name. 
2. Configures branch protection: require CI passing, require 1 review, no direct push to main
3. Creates directory structure based on the design
4. Sets up GitHub Actions: minimal CI (lint + unit tests on PR); full Kind/E2E/evals → **`rh-qs-test-suite`** after deploy
5. Configures linting: ruff + ruff format (Python), eslint + prettier (TypeScript)
6. Sets up testing: pytest, vitest, playwright (e2e)
7. Configures pre-commit hooks: ruff, eslint, type checking
8. Creates Makefile with standard targets
9. Creates `.env.example` with documented environment variables
10. Initializes `turbo.json` for monorepo orchestration

## Workflow

### Phase 0: Resolve Quickstart Context

Before doing anything, resolve which quickstart this session is for. Run `ls .rhoai-qs/ 2>/dev/null` (excluding `_shared`) and spawn the **validation-skill subagent**:

```python
Agent(
    description="Resolve which quickstart this scaffold session is for",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-scaffold/subagents/validation-skill-prompt.md

User message: {user_message}
Existing slugs: {existing_slugs}
Is entry point: false
Calling skill: rh-qs-scaffold
"""
)
```

Handle the result per [validation-skill-template.md](../../../docs/foundation/validation-skill-template.md#main-agent-handling). If `resolution: error` (no slugs exist), tell the user to run `rh-qs-discovery` and `rh-qs-architect` first and stop.

### Remaining phases

```
- [ ] 1. Create GitHub repo
- [ ] 2. Configure branch protection
- [ ] 3. Scaffold directory structure
- [ ] 4. Add GitHub Actions workflows
- [ ] 5. Configure linting + pre-commit
- [ ] 6. Scaffold test frameworks
- [ ] 7. Add Makefile + turbo.json + .env.example
- [ ] 8. Push initial commit and verify CI
```

### Create repository

The scaffolded repo is cloned as a sibling folder at the `quickstart-factory` root — **not** inside `.rhoai-qs/`. This requires two steps in order:

```bash
# 1. Ensure we're at the quickstart-factory root, so --clone lands the new
#    repo as a direct child folder, not inside whatever subfolder we were in.
cd "$(git rev-parse --show-toplevel)"

# 2. Create and clone the repo
gh repo create rh-ai-quickstart/<slug> --public --description "<from PRD>" --clone
```

Then immediately add a gitignore entry so `quickstart-factory`'s own git never tries to track the nested repo's contents:

```bash
echo "/<slug>/" >> .gitignore
```

See [pipeline-convention.md](../../../docs/foundation/pipeline-convention.md#nested-quickstart-repos) for why this repo lives here instead of somewhere else.

Start from [ai-quickstart-template](https://github.com/rh-ai-quickstart/ai-quickstart-template) when possible. Remove packages not in the design matrix.

### Branch protection

- Require pull request reviews (minimum 1)
- Require status checks (CI workflow) before merge
- Require branches up to date before merging
- Restrict direct pushes to `main`
- Do not allow bypassing the above

## Repository structure

```
<quickstart-name>/
├── .github/
│   ├── workflows/
│   │   ├── ci.yaml              # Lint + unit tests (runs on PR)
│   │   ├── integration.yaml     # Integration tests (runs on merge to main)
│   │   └── deploy.yaml          # Deploy to OpenShift (manual trigger)
│   ├── CODEOWNERS
│   └── pull_request_template.md
├── packages/
│   ├── api/                     # FastAPI application
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Containerfile
│   │   ├── pyproject.toml
│   │   └── ruff.toml
│   ├── ui/                      # React + Vite application
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Containerfile
│   │   ├── package.json
│   │   ├── eslint.config.js
│   │   └── vite.config.ts
│   ├── db/                      # SQLAlchemy + Alembic
│   │   ├── src/
│   │   ├── alembic/
│   │   └── pyproject.toml
│   └── ingestion/               # (if RAG) Document ingestion job
│       ├── src/
│       ├── tests/
│       └── pyproject.toml
├── deploy/
│   └── helm/<slug>/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
├── tests/
│   ├── integration/
│   └── e2e/
│       └── playwright.config.ts
├── docs/
│   └── images/                  # Architecture diagrams
├── compose.yml
├── Makefile
├── turbo.json
├── .env.example
├── .pre-commit-config.yaml
├── .gitignore
└── README.md
```

## GitHub Actions CI (ci.yaml)

**Trigger:** Pull request to main

| Job | Command |
|-----|---------|
| lint-python | `ruff check` + `ruff format --check` |
| lint-typescript | `eslint` |
| type-check | pyright/mypy + `tsc` |
| unit-tests-api | `pytest packages/api/` |
| unit-tests-ui | `vitest packages/ui/` |
| helm-lint | `helm lint deploy/helm/<slug>/` |

All jobs must pass before PR can merge.

## Makefile targets

```makefile
setup              # pnpm install + uv sync
dev                # podman-compose local stack
lint               # ruff + eslint
test               # unit tests
test-integration   # integration tests
test-e2e           # playwright
deploy             # helm upgrade --install (Helm only — no oc/kubectl in docs)
undeploy           # helm uninstall
verify-deploy      # post-install smoke test
```

## Linting configuration

**Python (`ruff.toml`):**

```toml
line-length = 120
target-version = "py312"
select = ["E", "F", "W", "I", "UP", "B", "SIM"]
```

**TypeScript:** ESLint recommended + typescript-eslint strict, Prettier integration, React hooks rules.

## Output

A GitHub repository with CI/CD configured, project structure created, and linting/testing ready to use. No domain logic yet.

## Verification

```bash
make lint
helm lint deploy/helm/<slug>/
```

## Next skill

When scaffold is pushed and CI is green → **`rh-qs-implement`**

## References

- [ai-quickstart-template](https://github.com/rh-ai-quickstart/ai-quickstart-template)
- [it-self-service-agent CI patterns](../rh-qs-test-suite/SKILL.md) — production workflow split (post-deploy)
- Design doc: `.rhoai-qs/<slug>/designs/design.md`
- [subagents/validation-skill-prompt.md](./subagents/validation-skill-prompt.md) — pass by file path only, do NOT read directly
