---
name: github-actions-e2e-compose-playwright-service-lifecycle
description: GitHub Actions E2E workflow spinning up Postgres, Keycloak, API, UI via podman-compose.yml with Docker Compose, running Playwright tests and uploading reports
summary: "Runs full-stack E2E Playwright browser tests in GitHub Actions by incrementally starting Postgres, Keycloak, smtp4dev, migrations (one-shot `docker compose run --rm`), API, UI, and nginx via `docker compose -p <project> -f podman-compose.yml` — the podman-compose.yml works with docker compose because it uses standard Compose v3 syntax. Use when CI needs the complete application stack with database, auth provider, and multi-service dependencies for browser-based E2E testing with phased startup and health gating rather than starting all services simultaneously. Two CI env files are generated at runtime (`.env.development` for service config with `BYPASS_AUTH=true` and `USE_ML_RECOMMENDATIONS=false`, `.env` for compose variable substitution); services start in phases with `timeout 60`-guarded health waits (`pg_isready` inside the container via `exec -T` for Postgres, `curl -f` for API:8000/health and UI:3000, `sleep 30` for Keycloak); Playwright runs via `pnpm --filter` against `E2E_BASE_URL=http://localhost:3000`. Keycloak uses `sleep 30` instead of a health check due to unreliable compose health checks in CI, `|| true` on timeout commands makes health waits soft failures so tests proceed with better diagnostics rather than aborting, `pg_isready` runs inside the container to avoid needing PostgreSQL client tools on the runner, and reports upload via `actions/upload-artifact@v4` with `if: always()` and 30-day retention before `down -v` cleanup."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [nodejs, python, playwright]
  ai_pattern: []
  platform: []
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "E2E workflow starts Postgres+Keycloak+smtp4dev, runs migration container, builds and starts API+UI+nginx, runs Playwright with uploaded report artifacts"
    approach: "A"
---

# GitHub Actions E2E Tests with Compose Service Lifecycle and Playwright

## Overview

This pattern runs end-to-end tests in GitHub Actions by spinning up the full application stack using Docker Compose with the project's `podman-compose.yml` file. Services are brought up incrementally (database first, then Keycloak, then migrations, then API, then UI+nginx), with explicit health wait loops between each phase. Playwright browser tests run against the fully operational stack, with test reports and results uploaded as artifacts.

## Pattern Description

The workflow creates CI-specific environment files at runtime, starts infrastructure services first (Postgres, Keycloak, smtp4dev), waits for database health via `pg_isready`, runs the migration container via `docker compose run --rm`, then builds and starts the API and UI with nginx. Each service has a `timeout`-guarded health wait loop. Playwright tests execute against `http://localhost:3000` (nginx-proxied), and reports are uploaded regardless of test outcome via `if: always()`.

## Implementation

### CI Environment File Generation

```yaml
- name: Create environment files for CI
  run: |
    cat > .env.development << 'EOF'
    POSTGRES_DB=spending-monitor
    POSTGRES_USER=user
    POSTGRES_PASSWORD=password
    DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/spending-monitor
    ENVIRONMENT=ci
    BYPASS_AUTH=true
    USE_ML_RECOMMENDATIONS=false
    VITE_BYPASS_AUTH=true
    VITE_ENVIRONMENT=ci
    EOF

    cat > .env << 'EOF'
    IMAGE_TAG=latest
    VITE_BYPASS_AUTH=true
    VITE_ENVIRONMENT=ci
    EOF
```

Source: `.github/workflows/coverage-e2e.yml`. Two files are needed: `.env.development` for service configuration, `.env` for Docker Compose variable substitution.

### Incremental Service Startup

```yaml
- name: Start services with Docker Compose
  run: |
    docker compose -p spending-transaction-monitor -f podman-compose.yml up -d postgres keycloak smtp4dev
    
    echo "Waiting for PostgreSQL to be ready..."
    timeout 60 bash -c 'until docker compose -p spending-transaction-monitor -f podman-compose.yml exec -T postgres pg_isready -U user -d spending-monitor; do sleep 2; done'
    
    echo "Waiting for Keycloak to be ready..."
    sleep 30

- name: Run database migrations
  run: |
    docker compose -p spending-transaction-monitor -f podman-compose.yml run --rm migrations

- name: Build and start API
  run: |
    docker compose -p spending-transaction-monitor -f podman-compose.yml up -d --build api
    timeout 60 bash -c 'until curl -f http://localhost:8000/health 2>/dev/null; do sleep 2; done' || true

- name: Build and start UI
  run: |
    docker compose -p spending-transaction-monitor -f podman-compose.yml up -d --build ui nginx
    timeout 60 bash -c 'until curl -f http://localhost:3000 2>/dev/null; do sleep 2; done' || true
```

Source: `.github/workflows/coverage-e2e.yml`

### Playwright Test Execution and Artifact Upload

```yaml
- name: Run E2E tests
  run: pnpm --filter @spending-monitor/ui e2e
  env:
    E2E_BASE_URL: http://localhost:3000

- name: Upload Playwright report
  uses: actions/upload-artifact@v4
  if: always()
  with:
    name: playwright-report
    path: packages/ui/playwright-report/
    retention-days: 30

- name: Stop services
  if: always()
  run: docker compose -p spending-transaction-monitor -f podman-compose.yml down -v
```

Source: `.github/workflows/coverage-e2e.yml`

## Configuration

- **Compose file:** `podman-compose.yml` used with `docker compose` (not podman-compose) in CI
- **Project name:** `-p spending-transaction-monitor` ensures consistent container naming
- **Auth:** `BYPASS_AUTH=true` disables Keycloak authentication for E2E tests
- **ML features:** `USE_ML_RECOMMENDATIONS=false` disables ML inference to avoid model dependencies
- **API build:** `--build` flag rebuilds API and UI images in CI from source
- **Cleanup:** `down -v` removes containers and volumes

## Gotchas

- The workflow uses `docker compose` (Docker's built-in compose) with the `podman-compose.yml` file, which is designed for Podman -- this works because the compose file uses standard Docker Compose v3 syntax
- `pg_isready` runs inside the container (`exec -T postgres pg_isready`) rather than from the host, avoiding the need for PostgreSQL client tools on the runner
- The Keycloak wait is a `sleep 30` rather than a health check, indicating the health check in the compose file is not reliable enough for CI timing
- `timeout 60 bash -c '...' || true` makes health waits soft failures -- the workflow continues even if services don't respond, potentially causing test failures with better diagnostics
- Migrations run via `docker compose run --rm migrations` (a separate one-shot container) rather than as part of the API startup, matching the production pattern where migrations are a separate Job

## Related Patterns

- `github-actions-kind-e2e-llm-eval-suite.md` - Kind-based E2E with LLM evaluation
- `smoke-test-compose-health-wait-endpoint-matrix.md` - Compose health wait patterns
- `compose-ci-overlay-gha-cache-coverage.md` - CI compose overlay pattern
