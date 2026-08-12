---
name: github-actions-uv-env-verify-optional-local-dep
description: GitHub Actions test workflow using uv for dependency install with optional local package install and environment verification
summary: "Solves CI environment verification for Python monorepo backends using uv where a sibling local package has complex native dependencies (PyTorch, CLIP) that may not install in GitHub Actions. Use when the CI goal is validating dependency resolution and environment setup rather than running a test suite, especially when a sibling package editable install (uv pip install -e) may fail due to missing system libraries — this is a single-approach pattern (no alternatives). Workflow triggers on pull_request and push to main, uses astral-sh/setup-uv@v5 pinned to 0.7.19 with actions/setup-python@v5 reading python-version-file from backend/pyproject.toml (repo-root-relative), installs dev extras via uv sync --extra dev, sets defaults.run.working-directory to backend, installs build-essential cmake pkg-config, and wraps the sibling install in a conditional if block that warns on failure but does not abort. The workflow is named \"Test\" but runs no pytest — only uv pip list for verification; python-version-file resolves relative to repo root while commands run from the backend/ working directory causing a path mismatch to watch for; the optional sibling install if block can silently mask genuine dependency failures beyond the expected native-library issues."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python]
  ai_pattern: [recommendation]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Test workflow using astral-sh/setup-uv with uv sync --extra dev, optional sibling package install via uv pip install -e, and environment verification"
    approach: "A"
---

# GitHub Actions uv Environment Verification with Optional Local Dependency

## Overview

A GitHub Actions test workflow uses `uv` for fast Python dependency installation, attempts to install a sibling local package as an optional dependency, and verifies the environment setup rather than running full test suites.

## Pattern Description

The workflow installs the backend's dev dependencies via `uv sync --extra dev`, then attempts to install the sibling `recommendation-core` package in editable mode. The sibling install is wrapped in a conditional that prints a warning but does not fail the workflow if the package cannot be installed (e.g., due to missing system dependencies like CMake). The workflow then verifies the environment is correctly set up rather than running actual tests.

## Implementation

### Test Workflow with Optional Dependency

```yaml
# .github/workflows/test.yml
name: Test
on:
  pull_request:
  push:
    branches: [main]
jobs:
  tests:
    name: Verify environment setup
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v5
        with:
          python-version-file: "backend/pyproject.toml"
      - name: Install system dependencies
        run: sudo apt-get update && sudo apt-get install -y build-essential cmake pkg-config
      - uses: astral-sh/setup-uv@v5
        with:
          version: "0.7.19"
      - name: Install the project
        run: uv sync --extra dev
      - name: Try to install recommendation-core (optional)
        run: |
          if uv pip install -e ../recommendation-core; then
            echo "recommendation-core installed successfully"
          else
            echo "recommendation-core installation failed, but environment is ready"
          fi
      - name: Verify environment
        run: |
          echo "Python version: $(python --version)"
          echo "uv version: $(uv --version)"
          echo "Installed packages:"
          uv pip list
```

## Configuration

- **Key settings:** `python-version-file: "backend/pyproject.toml"` reads the Python version from `pyproject.toml`, `uv` version pinned to `0.7.19`
- **Defaults:** System dependencies `build-essential cmake pkg-config` installed for any C-extension compilation
- **Dependencies:** `astral-sh/setup-uv@v5` action for uv installation

## Gotchas

- The workflow is named "Test" but does not actually run any tests (no `pytest` invocation); it only verifies the environment can be set up.
- The `recommendation-core` install is wrapped in an `if` block because it may fail due to complex native dependencies (e.g., PyTorch, CLIP) that need additional system packages beyond `build-essential cmake pkg-config`.
- `python-version-file` references `backend/pyproject.toml` but `working-directory` is already `backend`, so the checkout path is relative to repo root while commands run from `backend/`.

## Related Patterns

- `github-actions-pr-multi-language-lint-selective-helm-lint.md` — the PR quality checks that run alongside this test workflow
