---
name: zammad-bootstrap
description: Kubernetes Job that seeds Zammad with groups, users, custom attributes, webhooks, and API tokens via REST
summary: "Seeds a fresh Zammad ticketing instance with groups, custom user attributes, agent/customer users, integration webhooks/triggers (firing on customer article creation to an integration-dispatcher), and optionally an MCP agent API token — running as a Python Kubernetes Job via Helm post-install/post-upgrade hook (weight 100) that waits for Zammad's init Job completion before driving the REST API. Single approach — use when deploying an AI self-service agent quickstart needing a fully bootstrapped Zammad with automated token provisioning; RBAC is conditionally scoped (batch/jobs only by default, secrets/deployments verbs added when bootstrap.createToken=true) following least-privilege. Critical config: Object Manager migration cooldowns (ZAMMAD_OM_POST_COOLDOWN_SEC=20, ZAMMAD_OM_POST_MIGRATION_SETTLE_SEC=8) prevent Rails-reload 502s; API retry (10 attempts, linear backoff capped at 90s) with 429 Retry-After handles cold workers; token creation patches the Kubernetes Secret via read+replace (not PATCH) and triggers rolling restarts of dependent Deployments. Common gotchas: OpenShift returns 401 on strategic-merge PATCH for Secrets even with correct RBAC; tag conditions must be comma-separated strings not JSON arrays (Ruby .split(',') fails with 422); user lookups use paginated GET /users to avoid Elasticsearch indexing lag; customer_ticket_create_group_ids PUT format varies by Zammad version (state_current.value vs state); and the multi-stage Containerfile must copy mock-employee-data/ at repo root context for workspace path dependency resolution."
metadata:
  type: component
tags:
  tech_stack: [python, requests, kubernetes-client, zammad]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Helm post-install/post-upgrade Job that bootstraps a Zammad ticketing instance with groups, custom user attributes, test users, integration webhooks/triggers, and optionally creates an MCP agent API token"
    approach: "A"
---

# Zammad Bootstrap

## Overview

Zammad Bootstrap is a Python-based Kubernetes Job that provisions a fresh Zammad ticketing instance with the groups, custom user attributes, agent/customer users, integration webhooks, and triggers required by an AI self-service agent quickstart. It runs as a Helm post-install/post-upgrade hook, waits for Zammad's init Job and health endpoint, then drives the Zammad REST API to seed all configuration. When `createToken` is enabled, it also self-issues an MCP agent API token and patches a Kubernetes Secret so downstream deployments (MCP server, integration dispatcher, request manager) can authenticate without manual intervention.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 on `registry.access.redhat.com/ubi9/python-312-minimal:9.7`
- **Container image:** `quay.io/rh-ai-quickstart/self-service-agent-zammad-bootstrap:<version>`
- **Key dependencies:** `requests>=2.31.0`, `kubernetes>=31.0.0`, local `mock-employee-data` package (workspace path dependency via uv)
- **Helm subchart:** Deployed as part of `ticketingZammad` wrapper chart (wraps upstream `zammad` chart v16.0.4 from `https://zammad.github.io/zammad-helm`)

## Key Patterns

### Helm Post-Install Hook with Weighted Ordering

The bootstrap Job uses Helm hook annotations with a high weight so it runs after Zammad's own workloads have had time to schedule.

```yaml
# helm/zammad/templates/bootstrap-job.yaml
annotations:
  "helm.sh/hook": post-install,post-upgrade
  "helm.sh/hook-delete-policy": before-hook-creation
  # Run after other post-* hooks (lower weight = earlier).
  # Gives Zammad workloads time to schedule.
  "helm.sh/hook-weight": "100"
spec:
  backoffLimit: 10
  ttlSecondsAfterFinished: 86400
```

### Wait for Zammad Init Job Before HTTP Bootstrap

Before making any API calls, the script polls the Kubernetes Batch API for the `zammad-init` Job (DB migrations/seeds) to complete. This avoids racing against Zammad's own database setup.

```python
# bootstrap.py — wait_for_zammad_init_job()
sel = (
    "app.kubernetes.io/component=zammad-init,"
    f"app.kubernetes.io/instance={instance}"
)
# Polls batch.list_namespaced_job until .status.succeeded
# or .status.conditions contains Failed
```

The RBAC template grants the bootstrap ServiceAccount `get`, `list`, `watch` on `batch/jobs` to enable this polling.

### Self-Issued API Token via Admin Basic Auth

The script authenticates with admin basic auth (credentials from a Kubernetes Secret) to create a short-lived API token, avoiding any dependency on externally provisioned tokens.

```python
# bootstrap.py — acquire_token()
r = requests.post(
    url,
    auth=(ADMIN_EMAIL, ADMIN_PASSWORD),
    json={
        "name": "zammad-bootstrap",
        "permission": ["admin", "admin.channel_web"],
    },
    timeout=10,
)
token = r.json().get("token")
SESSION.headers["Authorization"] = f"Token token={token}"
```

### API Retry with Linear Backoff on Transient Errors

All Zammad REST calls go through an `api()` helper that retries on 502/503/504/429 and connection failures with configurable attempts and linear backoff. This handles nginx/Rails restarts and cold workers during bootstrap.

```python
# bootstrap.py
_TRANSIENT_HTTP = frozenset({502, 503, 504, 429})

def api(method, path, **kwargs):
    # Retries up to ZAMMAD_API_RETRY_ATTEMPTS (default 10)
    # Base delay ZAMMAD_API_RETRY_INTERVAL_SEC (default 2) scales
    # linearly: min(90, base_interval * attempt)
    # Respects Retry-After header on 429
```

### Object Manager Migration Cooldowns

Creating custom Zammad user attributes triggers Rails model reloads that can cause transient 502s. The script adds configurable cooldown periods before and after running `execute_migrations`.

```python
# bootstrap.py — execute_object_manager_migrations()
cooldown = _float_env("ZAMMAD_OM_POST_COOLDOWN_SEC", 20.0)
# Wait before migrations (Rails may be reloading after attribute create)
time.sleep(cooldown)

api("POST", "object_manager_attributes_execute_migrations",
    timeout=max(30.0, mig_timeout))

settle = _float_env("ZAMMAD_OM_POST_MIGRATION_SETTLE_SEC", 8.0)
# Wait after migrations (nginx/Rails may briefly 502)
time.sleep(settle)
```

### Integration Webhook and Trigger Provisioning

The script creates a Zammad Webhook and Trigger that fire on customer article creation, sending ticket data to the integration-dispatcher for AI agent processing. Trigger conditions are highly configurable via environment variables (group filtering, tag filtering, state filtering).

```python
# bootstrap.py — _integration_trigger_condition()
condition = {
    "article.action": {"operator": "is", "value": "create"},
    "article.sender_id": {"operator": "is", "value": sender_id},
    "ticket.customer_id": {
        "operator": "is",
        "pre_condition": "current_user.id",
        "value": "", "value_completion": "",
    },
}
# + optional ticket.group_id, ticket.tags, ticket.state_id filters
```

### Token Creation with Kubernetes Secret Patching

When `ZAMMAD_CREATE_TOKEN=true`, the script creates an MCP agent API token, updates a Kubernetes Secret with the token and Zammad URL, then triggers rolling restarts of dependent Deployments by patching their `restartedAt` annotation.

```python
# bootstrap.py — create_mcp_token_and_update_k8s()
# Uses read + replace instead of PATCH: some clusters (notably
# OpenShift) return 401 on strategic-merge PATCH for Secrets
existing = core_v1.read_namespaced_secret(name=credentials_secret, ...)
data["zammad-http-token"] = _b64(token)
existing.data = data
core_v1.replace_namespaced_secret(name=credentials_secret, ..., body=existing)
```

## Configuration

- **Environment variables (required):**
  - `ZAMMAD_BASE_URL` — Zammad instance URL (e.g., `http://zammad-nginx:8080`)
  - `ZAMMAD_ADMIN_EMAIL` / `ZAMMAD_ADMIN_PASSWORD` — admin credentials (from Secret)
  - `ZAMMAD_AUTOWIZARD_TOKEN` — token to trigger Zammad's autoWizard initial setup
- **Environment variables (token creation):**
  - `ZAMMAD_CREATE_TOKEN` — set to `true` to create MCP agent token and patch k8s Secret
  - `ZAMMAD_CREDENTIALS_SECRET` — name of the k8s Secret to update with the token
  - `ZAMMAD_MCP_DEPLOYMENT` / `ZAMMAD_INTEGRATION_DISPATCHER_DEPLOYMENT` / `ZAMMAD_REQUEST_MANAGER_DEPLOYMENT` — Deployment names to restart after token creation
- **Environment variables (integration webhook):**
  - `ZAMMAD_INTEGRATION_WEBHOOK_URL` — dispatcher endpoint; omit to skip webhook setup
  - `ZAMMAD_WEBHOOK_SECRET` — HMAC token for webhook verification
  - `ZAMMAD_TRIGGER_GROUP_NAMES` / `ZAMMAD_TRIGGER_GROUP_IDS` — limit trigger to specific groups
  - `ZAMMAD_TRIGGER_TAGS_ANY` / `ZAMMAD_TRIGGER_TAGS_ALL` / `ZAMMAD_TRIGGER_TAGS_EXCLUDE` — tag-based trigger filtering (mutually exclusive)
- **Environment variables (resilience tuning):**
  - `ZAMMAD_API_RETRY_ATTEMPTS` (default 10) / `ZAMMAD_API_RETRY_INTERVAL_SEC` (default 2)
  - `ZAMMAD_OM_POST_COOLDOWN_SEC` (default 20) / `ZAMMAD_OM_MIGRATION_TIMEOUT_SEC` (default 300) / `ZAMMAD_OM_POST_MIGRATION_SETTLE_SEC` (default 8)
  - `ZAMMAD_POST_USER_CREATE_SETTLE_SEC` (default 3)
  - `ZAMMAD_INIT_JOB_WAIT_TIMEOUT_SEC` (default 3600)
- **Helm values:** All above env vars are wired through `bootstrap.*` and `bootstrap.integrationWebhook.*` in `helm/zammad/values.yaml`

## Known Gotchas

- **OpenShift Secret patching:** The script uses `read_namespaced_secret` + `replace_namespaced_secret` instead of `PATCH` because some OpenShift clusters return 401 on strategic-merge PATCH for Secrets even when RBAC allows patch/update (see comment in `create_mcp_token_and_update_k8s()`).
- **Object manager migration 502s:** Creating custom Zammad user attributes triggers Rails model reloads. Without the configurable cooldown periods (`ZAMMAD_OM_POST_COOLDOWN_SEC`, `ZAMMAD_OM_POST_MIGRATION_SETTLE_SEC`), follow-up API calls frequently hit nginx 502. The defaults (20s pre, 8s post) are tuned for production but can be raised via env vars.
- **Post-user-create settle:** Each `POST /users` is followed by a configurable sleep (`ZAMMAD_POST_USER_CREATE_SETTLE_SEC`, default 3) because rapid consecutive creates cause 502 on the next `GET /users` used for idempotent lookups.
- **Zammad ticket.tags value format:** Tag conditions must be sent as comma-separated strings, not JSON arrays. Zammad's `Selector::Sql` calls `.split(',')` on the value; sending an Array makes Ruby validation fail with 422 (see `_zammad_ticket_tags_value()` docstring).
- **customer_ticket_create_group_ids PUT format:** Zammad persists settings in `state_current.value`. The script tries `{"state_current": {"value": target_ids}}` first, falling back to `{"state": target_ids}` if the first fails (API varies by Zammad version).
- **RBAC conditional scope:** The RBAC Role only grants `secrets` and `deployments` verbs when `bootstrap.createToken` is true; when false, only `batch/jobs` verbs are granted. This follows least-privilege for the default case (see `bootstrap-rbac.yaml`).
- **Elasticsearch lag on fresh deploy:** User lookup uses paginated `GET /users?page=N&per_page=100` instead of search API to avoid Elasticsearch indexing lag on freshly created users (see `find_user_by_email()` comment).
- **Container build with local workspace dep:** The Containerfile uses a multi-stage build and copies `mock-employee-data/` alongside `zammad-bootstrap/` at the repo root context level, because `pyproject.toml` references it as `{ path = "../mock-employee-data" }`. The Makefile build target enforces lockfile checks on both packages before building.

## Testing Notes

- Verify the bootstrap Job completed: `kubectl get jobs -l app.kubernetes.io/component=zammad-bootstrap`
- Check bootstrap logs: `kubectl logs -l app.kubernetes.io/component=zammad-bootstrap --all-containers`
- Confirm groups exist: `curl -H "Authorization: Token token=..." http://zammad-nginx:8080/api/v1/groups`
- Confirm custom attributes: `curl ... /api/v1/object_manager_attributes` and look for `manager_email` and `current_laptop`
- Confirm webhook/trigger: check Zammad Admin UI under Manage > Webhooks and Manage > Triggers

## Related Patterns

- `mcp-servers.md` — MCP server that uses the API token created by this bootstrap
- `mock-employee-data.md` — shared test data package consumed by bootstrap for user seeding
