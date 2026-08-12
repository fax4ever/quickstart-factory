---
name: smoke-test-compose-health-wait-endpoint-matrix
description: Shell smoke test script starting compose, waiting for service health via JSON status parsing, and verifying endpoint matrix with pass/fail reporting
summary: "Shell smoke test that starts a compose stack, polls each service's health by parsing `docker compose ps --format json` with inline Python3 (newline-delimited JSON, one object per line), then verifies an HTTP endpoint matrix with expected status codes and colored pass/fail counters. Use for pre-demo or CI validation of compose-based quickstarts -- auto-detects docker-compose vs podman-compose (or accepts `COMPOSE` env var from Makefile), tests authenticated endpoints via `AUTH_DISABLED=true`, and exits status 1 if any check fails, making it CI-pipeline-ready. Key settings: `TIMEOUT=120` health wait, `API_URL=http://localhost:8000`, `UI_URL=http://localhost:3000`; `check_endpoint` supports expected non-200 codes (e.g., 422 for validation routes confirming liveness without test data); `check_json_field` extracts nested response values via dot-notation; trap ensures `$COMPOSE down --remove-orphans` on exit. Python3 is required instead of jq for JSON parsing; `docker compose ps --format json` outputs newline-delimited JSON (not a JSON array) so each line must be parsed separately; compose auto-detection mirrors Makefile logic but the Makefile explicitly passes `COMPOSE=\"$(COMPOSE)\"` via `make smoke` for consistency."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [fastapi, react]
  ai_pattern: []
  platform: []
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Smoke test script with compose health status parsing via Python JSON, curl endpoint matrix, expected status code support (422 for validation), and pass/fail summary"
    approach: "A"
---

# Smoke Test with Compose Health Wait and Endpoint Matrix

## Overview

This pattern implements a pre-demo smoke test that starts the compose stack, waits for each service to become healthy by parsing compose JSON health status, then systematically tests a matrix of HTTP endpoints with expected status codes. It provides colored pass/fail reporting and automatic teardown via trap.

## Pattern Description

The script starts the minimal compose stack, then polls each critical service's health status by parsing `docker compose ps --format json` output with inline Python. Once services are healthy, it runs an endpoint matrix covering API health, public endpoints, authenticated endpoints (relying on `AUTH_DISABLED=true` in compose), and the UI. Endpoints can specify expected non-200 status codes (e.g., 422 for validation endpoints). The script uses a trap to ensure containers are torn down even on failure.

## Implementation

### Health Status Wait via JSON Parsing

```bash
# scripts/smoke-test.sh (excerpt)
wait_for_healthy() {
    local service="$1"
    local elapsed=0
    while [ $elapsed -lt $TIMEOUT ]; do
        local health
        health=$($COMPOSE ps --format json 2>/dev/null \
            | python3 -c "
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    svc = json.loads(line)
    if svc.get('Service') == '$service' or svc.get('Name','').startswith('$service'):
        print(svc.get('Health','unknown'))
        break
" 2>/dev/null || echo "unknown")
        if [ "$health" = "healthy" ]; then
            return 0
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    return 1
}
```

### Endpoint Matrix with Expected Status Codes

```bash
# scripts/smoke-test.sh (excerpt)
check_endpoint() {
    local label="$1" url="$2" expect_status="${3:-200}"
    local status
    status=$(curl -sf -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    if [ "$status" = "$expect_status" ]; then
        pass "$label -> $status"
    else
        fail "$label -> $status (expected $expect_status)"
    fi
}

# API health
check_endpoint "GET /health/" "$API_URL/health/"

# Public endpoints (no auth)
check_endpoint "GET /api/public/products" "$API_URL/api/public/products"

# 422 expected: no body sent, validation error confirms route is live
check_endpoint "POST /api/public/calculate-affordability" \
    "$API_URL/api/public/calculate-affordability" "422"

# Applications (AUTH_DISABLED=true in compose, so dev-user admin)
check_endpoint "GET /api/applications/" "$API_URL/api/applications/"
```

### JSON Field Extraction

```bash
# scripts/smoke-test.sh (excerpt)
check_json_field() {
    local label="$1" url="$2" jq_expr="$3"
    local result
    result=$(curl -sf "$url" 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
val = data
for key in '$jq_expr'.split('.'):
    if key == '': continue
    if isinstance(val, list): val = val[int(key)]
    else: val = val[key]
print(val)
" 2>/dev/null || echo "ERROR")
    if [ "$result" != "ERROR" ] && [ -n "$result" ]; then
        pass "$label -> $result"
    else
        fail "$label (could not extract $jq_expr)"
    fi
}
```

### Automatic Teardown

```bash
# scripts/smoke-test.sh (excerpt)
cleanup() {
    log "Tearing down containers..."
    $COMPOSE down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT
```

## Configuration

- **Key settings:** `TIMEOUT=120` seconds for health wait; `API_URL=http://localhost:8000`; `UI_URL=http://localhost:3000`; compose command auto-detected at script start
- **Defaults:** The script uses `$COMPOSE` passed from the Makefile environment or auto-detects docker compose vs podman-compose
- **Dependencies:** `python3` for JSON parsing (used instead of `jq` to avoid an extra dependency); `curl` for HTTP endpoint testing; compose-compatible CLI

## Gotchas

- The JSON health parsing uses Python inline because `docker compose ps --format json` outputs one JSON object per line (newline-delimited JSON), not a JSON array -- each line must be parsed separately (see `scripts/smoke-test.sh` lines 42-52)
- The script tests a 422 status code for the affordability calculator endpoint with an empty POST -- this intentionally triggers a validation error to confirm the route is live without needing valid test data (see `scripts/smoke-test.sh` lines 140-141)
- The `pass` and `fail` helper functions update `PASSED` and `FAILED` counters using arithmetic expansion, and the script exits with status 1 if any test fails -- this makes it suitable for CI pipeline integration (see `scripts/smoke-test.sh` lines 152-155)
- The compose auto-detection at the top of the script mirrors the Makefile detection but also accepts the `COMPOSE` env var -- when called via `make smoke`, the Makefile explicitly passes `COMPOSE="$(COMPOSE)"` to ensure consistency (see `scripts/smoke-test.sh` line 15)

## Related Patterns

- `makefile-autodetect-podman-docker-profile-compose.md` -- the Makefile that invokes this smoke test
- `compose-profile-layered-optional-services.md` -- the compose stack that gets smoke-tested
