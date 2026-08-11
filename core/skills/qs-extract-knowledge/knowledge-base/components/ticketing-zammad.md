---
name: ticketing-zammad
description: Zammad ticketing system wrapper chart with bootstrap Job, edge proxy, and webhook integration
summary: "Deploys Zammad v16.0.4 as a Helm wrapper subchart (ticketingZammad) providing a fully automated ticketing backend for AI agents managed via MCP tooling, adding a bootstrap Job, nginx edge proxy, OpenShift Route, and NetworkPolicy resources to the upstream chart. Use when an AI agent needs a ticketing system with zero manual setup — the post-install bootstrap Job (hook-weight 100, waits for zammad-init completion) seeds admin via autoWizard, creates custom attributes with ObjectManager migrations, provisions groups/users, wires webhooks+triggers to integration-dispatcher, and optionally self-provisions API tokens by patching K8s Secrets (read+replace not PATCH due to OpenShift RBAC issues) then restarting dependent deployments. Critical configuration: `edgeProxy.disableAttachments: true` blocks `/api/v1/upload_caches` with 403 and injects CSS via nginx `sub_filter` to hide attachment UI; RBAC for secrets/deployments is conditionally granted only when `bootstrap.createToken: true`; Route timeout is 3600s for WebSocket/ActionCable; edge proxy can optionally reverse-proxy a demo site under a path prefix for same-origin access. Key gotchas: MCP server chart key must differ from \"zammad\" to avoid pod selector collision causing connection refused, ObjectManager migrations cause transient 502s mitigated by `ZAMMAD_OM_POST_COOLDOWN_SEC` (default 20s) and `ZAMMAD_OM_POST_MIGRATION_SETTLE_SEC` (default 8s), trigger `ticket.tags` conditions require comma-separated strings not JSON arrays because Zammad `Selector::Sql` calls `.split(',')`, and `customer_ticket_create_group_ids` must be restricted after bootstrap creates internal queues to prevent customers filing tickets into agent-only groups."
metadata:
  type: component
tags:
  tech_stack: [zammad, helm, python, nginx, kubernetes, openshift]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Zammad deployed as Helm subchart with bootstrap Job for user/group/webhook seeding and edge proxy for attachment control"
    approach: "A"
---

# Ticketing Zammad

## Overview

Zammad is an open-source ticketing system deployed as a Helm subchart wrapper (`ticketingZammad`) within the parent quickstart chart. The wrapper chart adds a post-install/post-upgrade bootstrap Job that seeds groups, users, custom attributes, webhooks, and triggers via the Zammad REST API, plus an optional nginx edge proxy that blocks file attachments and injects CSS to hide attachment UI controls. It is used in the IT Self-Service Agent quickstart to provide a ticketing backend that an AI agent manages through MCP tooling.

## Tech Stack & Dependencies
- **Runtime:** Python 3.12 (bootstrap Job), nginx 1.27-alpine (edge proxy)
- **Container image:** `quay.io/rh-ai-quickstart/self-service-agent-zammad-bootstrap` (UBI9-based), `nginxinc/nginx-unprivileged:1.27-alpine` (edge proxy)
- **Key dependencies:** `requests`, `kubernetes` Python client, `mock-employee-data` (internal package for seeding test users)
- **Helm subchart:** `zammad` v16.0.4 from `https://zammad.github.io/zammad-helm`

## Key Patterns

### Wrapper Chart Over Upstream Subchart

The component is a Helm wrapper chart (`helm/zammad/`) that declares the upstream `zammad` chart as a dependency. All upstream values pass through under the `zammad:` key, while the wrapper adds bootstrap, edge proxy, and OpenShift Route resources.

```yaml
# helm/zammad/Chart.yaml
dependencies:
  - name: zammad
    version: "16.0.4"
    repository: https://zammad.github.io/zammad-helm
```

The parent quickstart chart references this wrapper as a local file dependency with a condition toggle:

```yaml
# helm/Chart.yaml (parent)
- name: ticketingZammad
  version: 0.1.0
  repository: "file://./zammad"
  condition: ticketingZammad.enabled
```

### Bootstrap Job as Helm Post-Install Hook

A Kubernetes Job runs after chart install/upgrade (`helm.sh/hook: post-install,post-upgrade`) to configure Zammad via its REST API. The Job uses hook-weight 100 to run after other hooks, giving Zammad workloads time to schedule. It first waits for the upstream `zammad-init` Job (DB migrations/seeds) to complete by polling the Kubernetes Batch API.

```yaml
# helm/zammad/templates/bootstrap-job.yaml
annotations:
  "helm.sh/hook": post-install,post-upgrade
  "helm.sh/hook-delete-policy": before-hook-creation
  "helm.sh/hook-weight": "100"
```

The bootstrap sequence (from `bootstrap.py`) is:
1. Wait for `zammad-init` Job completion (K8s API polling)
2. Wait for Zammad health endpoint (`/api/v1/getting_started`)
3. Trigger autoWizard to seed admin user
4. Self-issue a temporary API token via admin basic auth
5. Create custom user attributes (`manager_email`, `current_laptop`) and run ObjectManager migrations
6. Create groups (`Users`, `human_managed_tickets`, `escalated_laptop_refresh_tickets`)
7. Seed agent, manager, and employee users with role assignments
8. Create integration webhook and trigger (Zammad -> integration-dispatcher)
9. Set websocket backend to `websocket` mode
10. Create admin overview dashboards for AI agent statistics

### Token Self-Provisioning and K8s Secret Update

When `bootstrap.createToken: true`, the Job creates a Zammad API token for the MCP agent, patches a Kubernetes Secret with the token, then restarts dependent deployments (MCP server, integration-dispatcher, request-manager) via the Apps API. This avoids any manual token step after install.

```python
# zammad-bootstrap/bootstrap.py — token creation
r = requests.post(
    f"{API_URL}/user_access_token",
    auth=(ADMIN_EMAIL, ADMIN_PASSWORD),
    json={"name": "mcp-agent", "permission": ["admin", "ticket.agent"]},
    timeout=10,
)
```

The RBAC template conditionally grants `secrets` (get/patch/update) and `deployments` (get/patch/update) only when `createToken` is enabled:

```yaml
# helm/zammad/templates/bootstrap-rbac.yaml
{{- if $createToken }}
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "patch", "update"]
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "patch", "update"]
{{- end }}
```

### Edge Proxy for Attachment Control

An optional nginx reverse proxy sits in front of the stock Zammad nginx service. When `edgeProxy.disableAttachments: true`, it blocks the upload API with a 403 and injects CSS to hide attachment controls in the UI, all without modifying the Zammad image or chart.

```yaml
# helm/zammad/templates/edge-proxy-configmap.yaml (key rules)
location ~ ^/api/v1/upload_caches {
    return 403;
}
```

CSS injection uses nginx `sub_filter` to inject a `<style>` tag before `</head>` on HTML responses:

```
# from _helpers.tpl
.article-attachment,.attachmentPlaceholder,...{display:none!important;pointer-events:none!important}
```

The edge proxy also routes WebSocket (`/ws`) directly to `zammad-websocket:6042` and ActionCable (`/cable`) directly to `zammad-railsserver:3000`, avoiding double-hop through the stock nginx.

### Demo Site Reverse Proxy

The edge proxy can optionally reverse-proxy a demo site under a path prefix (e.g., `/demo-portal`) so that both the demo UI and Zammad share the same origin. This enables port-forward access where one-click sign-in works without cross-origin issues.

```yaml
# values.yaml
edgeProxy:
  demoSiteProxy:
    enabled: false
    service: zammad-demo-site
    port: 80
    pathPrefix: /demo-portal
```

### Integration Webhook and Trigger

The bootstrap creates a Zammad Webhook and Trigger that POST customer ticket articles to the integration-dispatcher service. Trigger conditions are configurable via environment variables for group filtering, tag filtering (any/all/exclude), and state filtering (new + open only).

```yaml
# helm/values-ticketing.yaml
bootstrap:
  integrationWebhook:
    enabled: true
    mainChartReleaseName: "self-service-agent"
    triggerGroupNames: "Users"
    triggerTagsExclude: "pending-manager-review"
```

### Network Policies

When the edge proxy or external route is enabled, the chart creates granular NetworkPolicy resources:
- OpenShift router ingress to edge proxy (or nginx if no edge proxy)
- Edge proxy to zammad-nginx (port 8080)
- Edge proxy to zammad-websocket (port 6042)
- Edge proxy to zammad-railsserver (port 3000)
- Edge proxy to demo site (port 8080, conditional)

## Configuration
- **Environment variables:** The bootstrap Job accepts extensive configuration via env vars: `ZAMMAD_BASE_URL`, `ZAMMAD_ADMIN_EMAIL`, `ZAMMAD_ADMIN_PASSWORD`, `ZAMMAD_AUTOWIZARD_TOKEN`, `ZAMMAD_CREATE_TOKEN`, `ZAMMAD_INTEGRATION_WEBHOOK_URL`, `ZAMMAD_WEBHOOK_SECRET`, `ZAMMAD_TRIGGER_GROUP_NAMES`, `ZAMMAD_TRIGGER_TAGS_EXCLUDE`, `TEST_USERS`, plus tuning variables for retry/timeout behavior (`ZAMMAD_API_RETRY_ATTEMPTS`, `ZAMMAD_OM_POST_COOLDOWN_SEC`, etc.)
- **Config files:** Edge proxy nginx config generated from Helm template into a ConfigMap
- **Helm values:** Key overrides under `ticketingZammad.bootstrap.*` (token creation, webhook config), `ticketingZammad.edgeProxy.*` (attachment blocking, demo site proxy), `ticketingZammad.externalRoute.*` (OpenShift Route), and `ticketingZammad.zammad.*` (upstream chart passthrough including `autoWizard` JSON config and `fullnameOverride`)

## Known Gotchas
- **Service name collision:** The MCP server chart key must differ from `"zammad"` because that label collides with ticketingZammad subchart pod selectors, causing MCP to connect to random Zammad components and get connection refused (documented in `helm/values.yaml` comment: "Key must differ from 'zammad'").
- **ObjectManager migration instability:** After creating custom attributes, Zammad Rails/nginx may briefly return 502 during migrations. The bootstrap adds configurable cooldown periods (`ZAMMAD_OM_POST_COOLDOWN_SEC` default 20s, `ZAMMAD_OM_POST_MIGRATION_SETTLE_SEC` default 8s) to handle this.
- **API resilience on cold start:** Zammad nginx/Rails may return 502/503/504 during worker warm-up. The bootstrap `api()` helper retries transient HTTP errors with linear backoff (default 10 attempts, 2s base interval).
- **Zammad tag value format:** Trigger `ticket.tags` conditions must use comma-separated strings, not JSON arrays. Zammad's `Selector::Sql` calls `.split(',')` on the value; JSON arrays cause validation failures (422). This is documented in `bootstrap.py` comments.
- **OpenShift Route timeout:** The Zammad Route sets `haproxy.router.openshift.io/timeout: "3600s"` because WebSocket/ActionCable and long-poll endpoints need longer-lived connections.
- **K8s Secret update uses read+replace:** The bootstrap uses `read_namespaced_secret` then `replace_namespaced_secret` instead of PATCH because some OpenShift clusters return 401 on strategic-merge PATCH for Secrets even when RBAC allows it (documented in `bootstrap.py` comment).
- **Post-user-create settle time:** A 3-second default sleep after each `POST /users` avoids 502 errors on subsequent `GET /users` calls used for idempotent lookups (Elasticsearch lag on fresh deploys).
- **Customer group picker:** When `customer_ticket_create_group_ids` is not set, Zammad allows customers to create tickets in all groups. After bootstrap adds internal queues (`human_managed_tickets`, `escalated_laptop_refresh_tickets`), the setting must be restricted to prevent customers from filing tickets directly into internal queues.

## Testing Notes
- Verify bootstrap Job completes: check Job status and logs for "Zammad bootstrap complete."
- Confirm custom attributes exist: Zammad Admin UI -> Objects -> User should show `manager_email` and `current_laptop`
- Test edge proxy attachment blocking: POST to `/api/v1/upload_caches` should return 403; attachment UI elements should be hidden
- Verify webhook integration: create a customer ticket and confirm the integration-dispatcher receives the webhook POST
- Check NetworkPolicy: ensure Zammad is accessible via the OpenShift Route but internal services are properly isolated

## Related Patterns
- MCP server integration (zammad-mcp) for AI agent tooling
- Integration-dispatcher for webhook event processing
- Helm subchart wiring patterns for conditional deployment
