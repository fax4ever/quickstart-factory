---
name: tavern-integration-tests-openshift-route-env-driven
description: Tavern YAML-based HTTP integration tests driven by environment variables pointing to OpenShift Route URLs
summary: "Solves HTTP integration testing of OpenShift-deployed services using pytest-tavern declarative YAML test files that target Route URLs discovered at runtime via `oc get routes` with jq URL extraction. Use when validating multi-stage API flows (health checks, auth signup/login, CRUD, recommendations, search) against live OpenShift Routes with concurrent-safe timestamped test data (`test{TEST_TIMESTAMP}@test.com`) to avoid cross-run collisions. Shell script exports TEST_FRONTEND_URL and TEST_FEAST_URL from `oc get routes` (NAMESPACE falls back to `oc project -q`), validates URLs for empty/\"null\" values, then runs pytest; test stages chain responses via `save.json` and validate dynamic fields with Tavern's `!anystr` tag. Tests create real database records (users, cart items) with no cleanup -- relies on ephemeral namespace deletion by tester CronJob; URL discovery silently returns \"null\" strings on missing Routes so the validate_url check is essential before pytest runs."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python]
  ai_pattern: [recommendation]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "10 Tavern test files covering health, auth, cart, recommendations, and search; URLs from oc get routes; timestamped test data"
    approach: "A"
---

# Tavern YAML Integration Tests with OpenShift Route URLs

## Overview

Uses pytest-tavern to define HTTP integration tests in YAML format that run against OpenShift Routes discovered at runtime via `oc get routes`. Tests cover health checks, authentication flows, CRUD operations, and API edge cases, using timestamped data to avoid conflicts across concurrent test runs.

## Pattern Description

A shell script discovers Route URLs for the frontend and Feast services via `oc get routes`, exports them as environment variables, and runs `pytest` against Tavern YAML test files. Each test file defines multi-stage HTTP request/response sequences using Tavern's declarative YAML syntax. Test data uses `{tavern.env_vars.TEST_TIMESTAMP}` for unique email addresses and user names, enabling concurrent test runs without data collisions.

## Implementation

### Route URL Discovery Script

```bash
# tests/integration/run_integration_tests.sh
if [ -z "$NAMESPACE" ]; then
    NAMESPACE=$(oc project -q 2>/dev/null)
fi
export TEST_FRONTEND_URL=$(oc get routes product-recommender-system-frontend -n "$NAMESPACE" -o json | jq -r '"https://" + .spec.host')
export TEST_FEAST_URL=$(oc get routes feast-feast-recommendation-ui -n "$NAMESPACE" -o json | jq -r '"https://" + .spec.host')
export TEST_TIMESTAMP=$(date +%s)

# Validate URLs before running tests
validate_url "$TEST_FRONTEND_URL" "Frontend"
validate_url "$TEST_FEAST_URL" "Feast"

PYTHONPATH=. pytest "$TEST_TARGET" -v
```

### Health Check Tavern Test

```yaml
# tests/integration/test_endpoints.tavern.yaml
test_name: Backend Health Ready Check
stages:
  - name: Test Backend Health Ready
    request:
      url: "{tavern.env_vars.TEST_FRONTEND_URL}/health/ready"
      method: GET
    response:
      status_code: 200
      json:
        status: "ready"
```

### Multi-Stage Auth Flow with Response Chaining

```yaml
# tests/integration/test_user_signup_and_signin.tavern.yaml
test_name: Signup a user and login
stages:
  - name: Test Signup a user
    request:
      url: "{tavern.env_vars.TEST_FRONTEND_URL}/auth/signup"
      method: POST
      json:
        email: "test{tavern.env_vars.TEST_TIMESTAMP}@test.com"
        password: "mypass"
        display_name: "Test User {tavern.env_vars.TEST_TIMESTAMP}"
        age: 25
        gender: "Male"
    response:
      status_code: 201
      json:
        user:
          user_id: !anystr
        token: !anystr
      save:
        json:
          user_id: "user.user_id"
          token: "token"
  - name: Test Login with same user
    request:
      url: "{tavern.env_vars.TEST_FRONTEND_URL}/auth/login"
      method: POST
      json:
        email: "test{tavern.env_vars.TEST_TIMESTAMP}@test.com"
        password: "mypass"
    response:
      status_code: 200
```

## Configuration

- **Key settings:** `TEST_FRONTEND_URL` and `TEST_FEAST_URL` from OpenShift Routes, `TEST_TIMESTAMP` for test data uniqueness
- **Defaults:** `NAMESPACE` falls back to current `oc project` if not set
- **Dependencies:** `pytest`, `tavern` Python packages; `oc` CLI with cluster access; frontend and Feast Routes must be ready

## Gotchas

- The test runner script validates URLs before running tests, checking for empty or "null"-containing values from failed `oc get routes` commands.
- Tavern's `!anystr` YAML tag validates that a field exists and is a string without checking its value, used for dynamic fields like `user_id` and `token`.
- Response values are saved across stages via `save.json` and referenced with `{variable_name}` syntax, enabling auth token propagation from signup through subsequent API calls.
- The test suite creates real data in the database (users, cart items) that is not cleaned up after tests -- cleanup relies on the ephemeral namespace being deleted by the tester CronJob.
- The script exits with pytest's actual exit code and includes documentation of all pytest exit codes (0-5) for debugging.

## Related Patterns

- `tester-cronjob-skopeo-digest-poll-ephemeral-ns-e2e-slack.md` — the CronJob that runs these integration tests in an ephemeral namespace
