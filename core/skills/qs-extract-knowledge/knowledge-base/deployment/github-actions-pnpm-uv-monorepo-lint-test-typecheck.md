---
name: github-actions-pnpm-uv-monorepo-lint-test-typecheck
description: GitHub Actions PR workflow installing pnpm+uv for monorepo with Node+Python packages, running lint, type-check, format-check, and tests via pnpm scripts
summary: "Solves CI quality gates for monorepos combining pnpm-workspace Node.js and uv-managed Python packages by running lint, type-check, test, and format-check across both languages in a single-job GitHub Actions PR workflow triggered on PRs to main. Use when a repo mixes Node (pnpm workspaces) and Python (uv) packages needing unified PR checks — sets up Node 20 + pnpm 9.0.0 via pnpm/action-setup@v4, Python 3.12 + curl-installed uv via actions/setup-python@v5, and orchestrates cross-language checks through root pnpm scripts. Critical pattern: pnpm install handles Node deps, then each Python package (api, db, auth — each with own pyproject.toml/uv.lock) needs a separate uv sync --group dev step with working-directory since uv lacks workspace-wide sync; type-check is filtered to UI only via --filter @spending-monitor/ui. Gotchas: uv installs to .cargo/bin requiring echo \"$HOME/.cargo/bin\" >> $GITHUB_PATH, adding a new Python package means adding a new workflow step for its uv sync, and root package.json scripts must correctly delegate to both vitest/jest and pytest runners."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [nodejs, python]
  ai_pattern: []
  platform: []
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "PR workflow installing pnpm 9 + uv for 3 Python packages (api, db, auth) with uv sync --group dev, then pnpm lint/type-check/test/format:check across monorepo"
    approach: "A"
---

# GitHub Actions: pnpm + uv Monorepo Lint, Test, and Type-Check

## Overview

This pattern runs a single-job PR check workflow for a monorepo containing both Node.js (pnpm workspace) and Python (uv-managed) packages. The workflow installs both package managers, syncs development dependencies for each Python package separately, then runs pnpm-orchestrated lint, type-check, test, and format-check steps that span both Node and Python codebases.

## Pattern Description

The monorepo uses pnpm workspaces for the Node.js UI package and uv for Python API, DB, and auth packages. The GitHub Actions workflow sets up Node 20 with pnpm 9, Python 3.12 with uv, installs all Node deps via `pnpm install`, then installs each Python package's dev dependencies individually via `uv sync --group dev` from each package directory. Root-level pnpm scripts orchestrate cross-language testing.

## Implementation

### Dual Package Manager Setup

```yaml
steps:
- uses: actions/setup-node@v4
  with:
    node-version: '20'
- uses: pnpm/action-setup@v4
  with:
    version: 9.0.0
- uses: actions/setup-python@v5
  with:
    python-version: '3.12'
- name: Install uv
  run: curl -LsSf https://astral.sh/uv/install.sh | sh
- name: Add uv to PATH
  run: echo "$HOME/.cargo/bin" >> $GITHUB_PATH
```

Source: `.github/workflows/test.yml`

### Per-Package Python Dependency Installation

```yaml
- name: Install dependencies
  run: pnpm install
- name: Install API Python dependencies
  run: uv sync --group dev
  working-directory: packages/api
- name: Install DB Python dependencies
  run: uv sync --group dev
  working-directory: packages/db
- name: Install Auth Python dependencies
  run: uv sync --group dev
  working-directory: packages/auth
```

Source: `.github/workflows/test.yml`

### Cross-Language Quality Checks

```yaml
- name: Run linting
  run: pnpm lint
- name: Run type checking
  run: pnpm --filter @spending-monitor/ui type-check
- name: Run tests
  run: pnpm test
- name: Check formatting
  run: pnpm format:check
```

Source: `.github/workflows/test.yml`. Root pnpm scripts delegate to per-package scripts including Python pytest.

## Configuration

- **Trigger:** Pull requests targeting `main`
- **Node version:** 20
- **Python version:** 3.12
- **pnpm version:** 9.0.0
- **uv installation:** Curl-based, added to PATH via `$HOME/.cargo/bin`
- **Python packages:** 3 separate packages (api, db, auth) each with their own `pyproject.toml` and `uv.lock`

## Gotchas

- Each Python package requires a separate `uv sync --group dev` with `working-directory` because uv does not support workspace-wide sync like pnpm; adding a new Python package requires adding a new step
- The `echo "$HOME/.cargo/bin" >> $GITHUB_PATH` step is needed because uv installs to `.cargo/bin` and this directory is not on PATH by default in GitHub Actions
- `pnpm lint` and `pnpm test` delegate to all workspace packages including Python packages, meaning root `package.json` scripts must correctly invoke both vitest/jest and pytest
- Type checking is filtered to only the UI package (`--filter @spending-monitor/ui type-check`) because Python type checking is handled separately if at all

## Related Patterns

- `github-actions-uv-env-verify-optional-local-dep.md` - uv-only CI verification
- `github-actions-pr-multi-language-lint-selective-helm-lint.md` - Multi-language lint with Helm
