---
name: github-actions-pr-multi-language-lint-selective-helm-lint
description: PR quality checks with Python/Node.js linting, pre-commit hooks, and Helm lint only on modified chart directories
summary: "Enforces PR code quality across polyglot Python/Node.js repos with Helm charts by running flake8 (--max-line-length=99 --extend-ignore=E203,W503), black, and isort on backend/; npx prettier on frontend/; pre-commit hooks (trailing-whitespace, end-of-file-fixer) on git-diff-identified modified files; and selective Helm lint on changed chart directories — all in a single GitHub Actions job triggered on PR open/synchronize/reopen and push to main. Use when a repo has both Python and Node.js code with Helm charts and you want non-blocking lint warnings (all steps use continue-on-error: true producing ::warning:: annotations rather than failing the PR); remove continue-on-error if blocking checks are needed. Modified Helm chart directories are detected via `git diff --name-only | grep '^helm/' | sed 's|helm/\\([^/]*\\).*|helm/\\1|' | sort -u` and linted only if Chart.yaml exists; Python 3.12, Node.js 20, and Helm v3.14.0 (manual curl install) are required. Pre-commit hooks use `github.event.pull_request.base.sha` which is empty on push-to-main events causing silent git diff failure; the sed extraction pattern only resolves charts directly under helm/ (no nested subdirectories); and since all steps are continue-on-error the workflow always reports as passing regardless of violations."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, nodejs, helm]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "PR checks with flake8/black/isort for Python, Prettier for Node.js, pre-commit for whitespace, and Helm lint only on modified helm/ directories"
    approach: "A"
---

# PR Multi-Language Lint with Selective Helm Lint

## Overview

A GitHub Actions PR quality check workflow runs language-specific linters for both Python and Node.js code, pre-commit hooks on modified files only, and Helm lint selectively on chart directories that were changed in the PR.

## Pattern Description

The workflow triggers on PR open/sync/reopen and push to main, running all checks in a single job. All lint steps use `continue-on-error: true`, meaning lint failures produce warnings but do not block the PR. Helm lint is only run on chart directories that have modified files (detected via `git diff` and `sed` extraction), avoiding unnecessary linting of unchanged charts.

## Implementation

### Multi-Language Lint Steps

```yaml
# .github/workflows/pr-checks.yml
name: PR Quality Checks
on:
  pull_request:
    types: [opened, synchronize, reopened]
  push:
    branches: [main]
jobs:
  code-quality-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: "3.12"
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - run: pip install flake8 black isort
      - name: Run flake8
        continue-on-error: true
        run: cd backend && flake8 --max-line-length=99 --extend-ignore=E203,W503 .
      - name: Check code formatting
        continue-on-error: true
        run: cd backend && black --check --diff .
      - name: Check import sorting
        continue-on-error: true
        run: cd backend && isort --check-only --diff .
      - name: Check Prettier formatting (frontend)
        continue-on-error: true
        run: cd frontend && npx prettier --check .
```

### Pre-Commit on Modified Files Only

```yaml
      - run: pip install pre-commit
      - name: Check trailing whitespace
        continue-on-error: true
        run: |
          git diff --name-only ${{ github.event.pull_request.base.sha }} ${{ github.event.pull_request.head.sha }} | \
            xargs -r pre-commit run trailing-whitespace --files
      - name: Check end-of-file fixer
        continue-on-error: true
        run: |
          git diff --name-only ${{ github.event.pull_request.base.sha }} ${{ github.event.pull_request.head.sha }} | \
            xargs -r pre-commit run end-of-file-fixer --files
```

### Selective Helm Lint on Modified Charts

```yaml
      - name: Install Helm
        run: |
          curl https://get.helm.sh/helm-v3.14.0-linux-amd64.tar.gz | tar xz
          sudo mv linux-amd64/helm /usr/local/bin/helm
      - name: Check Helm lint
        continue-on-error: true
        run: |
          MODIFIED_HELM_DIRS=$(git diff --name-only ${{ github.event.pull_request.base.sha }} ${{ github.event.pull_request.head.sha }} | \
            grep '^helm/' | sed 's|helm/\([^/]*\).*|helm/\1|' | sort -u)
          if [ -n "$MODIFIED_HELM_DIRS" ]; then
            for dir in $MODIFIED_HELM_DIRS; do
              if [ -f "$dir/Chart.yaml" ]; then
                helm lint "$dir"
              fi
            done
          else
            echo "No Helm charts modified"
          fi
```

## Configuration

- **Key settings:** `flake8 --max-line-length=99 --extend-ignore=E203,W503` for Python linting, Helm v3.14.0 installed manually
- **Defaults:** All lint steps set `continue-on-error: true` so no check blocks the PR
- **Dependencies:** Python 3.12, Node.js 20, `npx prettier` (runs without pre-install via npx)

## Gotchas

- All lint steps use `continue-on-error: true`, meaning the workflow always reports as passing regardless of lint violations. Violations are only surfaced as `::warning::` annotations in the GitHub UI.
- Pre-commit hooks use `${{ github.event.pull_request.base.sha }}` which is empty on `push` events to `main`, so the `git diff` command will fail silently on pushes.
- Helm is installed manually via `curl` rather than using an action, pinned to v3.14.0.
- The `sed` extraction pattern `s|helm/\([^/]*\).*|helm/\1|` correctly maps any file under `helm/<chart>/` to the chart directory, but only works for charts directly under `helm/` (no nested subdirectories).

## Related Patterns

- `github-actions-workflow-run-cascade-build-chain.md` — the build workflows that run after these PR checks pass
