---
name: compose-ci-overlay-gha-cache-coverage
description: Compose CI overlay with GHA build cache and HTTP-based coverage extraction from running backend
summary: "Extends a local dev compose file with a compose.ci.yaml overlay adding GitHub Actions build cache (type=gha,mode=max) with scoped keys per service (scope=backend, scope=frontend), enabling both unit and integration test coverage collection in a single CI run. Use when CI needs combined unit and integration coverage from compose-based services — the test runner collects unit coverage via pytest-cov (--cov-branch) with pytest-xdist (--dist auto), extracts integration coverage by curling the backend's /admin/coverage endpoint for .coverage.integration, then merges via coverage combine; integration tests use --dist loadfile and TAVERN_UNIQUE for resource isolation. ENABLE_COVERAGE=true and ENABLE_ATTACHMENTS=false are set in CI; the backend startup switches from uvicorn --reload to coverage run --source=backend --data-file=/app/.coverage.integration -m uvicorn since hot reload interferes with coverage collection. The backend must implement a custom /admin/coverage HTTP endpoint to dump coverage data (not a standard FastAPI feature), .coveragerc must be COPY'd into the dev container at build time, and compose files must remain compatible with both Docker (CI) and Podman (local dev) runtimes."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [fastapi, python]
  ai_pattern: []
  platform: []
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "compose.ci.yaml overlay adds GHA build cache; tests extract integration coverage via HTTP endpoint"
    approach: "A"
---

# Compose CI Overlay with GHA Cache and Coverage Extraction

## Overview

This pattern extends the local development compose file with a CI-specific overlay that adds GitHub Actions build caching. Combined with a test runner script that extracts code coverage from a running backend container via HTTP, it enables both unit and integration test coverage to be collected and combined in a single CI run.

## Pattern Description

A `compose.ci.yaml` file is layered on top of the main `compose.yaml` using docker compose's multi-file feature (`-f compose.yaml -f compose.ci.yaml`). The overlay adds GitHub Actions-specific build cache configuration. The test runner script (`tests/run_tests.sh`) supports separate unit and integration test execution, with coverage data collected differently for each: unit tests use pytest-cov directly, while integration test coverage is extracted from the running backend container by curling an admin endpoint that dumps the `.coverage` file.

## Implementation

### CI Compose Overlay

The overlay adds GHA-type build cache to the backend and frontend services:

```yaml
# deploy/local/compose.ci.yaml
services:
  backend:
    build:
      cache_from:
        - type=gha,scope=backend
      cache_to:
        - type=gha,mode=max,scope=backend

  frontend:
    build:
      cache_from:
        - type=gha,scope=frontend
      cache_to:
        - type=gha,mode=max,scope=frontend
```

### CI Workflow Usage

The CI workflow starts services with both compose files, runs tests, then tears down:

```yaml
# .github/workflows/ci.yml (excerpt)
- name: Build and start services
  run: docker compose -f compose.yaml -f compose.ci.yaml up -d --wait
  env:
    ENABLE_ATTACHMENTS: false
    LOCAL_DEV_ENV_MODE: true
    ENABLE_COVERAGE: true

- name: Show logs on failure
  if: failure()
  run: |
    docker compose -f compose.yaml -f compose.ci.yaml ps
    docker compose -f compose.yaml -f compose.ci.yaml logs backend

- name: Tear down
  if: always()
  run: docker compose -f compose.yaml -f compose.ci.yaml down -v
```

### Backend Dev Script with Coverage Mode

When `ENABLE_COVERAGE=true`, the backend dev startup script runs uvicorn under `coverage run` instead of with `--reload`, since hot reload interferes with coverage collection:

```bash
# deploy/local/scripts/start-backend-dev.sh (excerpt)
if [ "${ENABLE_COVERAGE:-false}" = "true" ]; then
    echo "Coverage collection enabled (reload disabled for accurate coverage)"
    exec coverage run --source=backend --data-file=/app/.coverage.integration \
        -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
else
    echo "Hot reload enabled for development"
    exec uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
fi
```

### Test Runner with Coverage Extraction

The test script runs unit and integration tests separately, collecting coverage for each. Integration coverage is extracted from the running backend via an HTTP endpoint:

```bash
# tests/run_tests.sh (excerpt)
# Unit tests with coverage
COVERAGE_FILE=.coverage.unit $pytest_cmd tests/unit -ra --cov=backend --cov-report= --cov-branch

# Integration tests
$pytest_cmd tests/integration/ -v

# Extract coverage from running backend container
if curl -s -f "$BACKEND_URL/admin/coverage" -o .coverage.integration; then
    echo "Coverage extracted"
fi

# Combine both coverage files
if [ -f ".coverage.unit" ] || [ -f ".coverage.integration" ]; then
    coverage combine .coverage.unit .coverage.integration
    coverage report
fi
```

### Test Runner Features

The test script supports targeted test execution with auto-detection of test type, parallel execution via `pytest-xdist`, and separate pytest configurations for unit vs integration tests:

```bash
# tests/run_tests.sh (excerpt)
PYTEST_CMD="pytest -n auto"
PYTEST_INTEG_CMD="pytest -n auto --dist loadfile"
export TAVERN_UNIQUE="test${RANDOM}"
```

## Configuration

- **Key settings:** `ENABLE_COVERAGE` toggles coverage mode (disables hot reload); `ENABLE_ATTACHMENTS=false` in CI skips MinIO; GHA cache uses scoped keys (`scope=backend`, `scope=frontend`)
- **Defaults:** Coverage disabled by default; unit tests use `pytest-xdist` with `--dist auto`; integration tests use `--dist loadfile` to keep file-level ordering
- **Dependencies:** Backend must expose `/admin/coverage` endpoint when `ENABLE_COVERAGE=true`; requires `pytest-cov`, `coverage[toml]`, `pytest-xdist`; the backend dev Containerfile pre-installs coverage tools

## Gotchas

- Coverage extraction via `curl -s -f "$BACKEND_URL/admin/coverage"` requires the backend to expose a coverage dump endpoint. This is application-level code, not a standard FastAPI feature (see `run_tests.sh` line 124)
- The CI overlay uses `docker compose` (Docker) while local dev uses `podman compose` (Podman). The compose files are compatible with both runtimes
- The `.coveragerc` file is copied into the backend dev container at build time (`COPY .coveragerc /app/.coveragerc` in `Containerfile.backend.dev` line 22) to ensure coverage configuration is available inside the container
- The `TAVERN_UNIQUE` variable generates a random test prefix to avoid naming collisions when integration tests create resources (see `run_tests.sh` line 7)

## Related Patterns

- `compose-local-dev-ollama-llamastack-mcp.md` -- the base compose file this overlay extends
- `github-actions-multi-image-release-pipeline.md` -- the CI workflow that uses this overlay
