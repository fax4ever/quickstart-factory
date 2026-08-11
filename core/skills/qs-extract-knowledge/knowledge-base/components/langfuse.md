---
name: langfuse
description: "Langfuse v3 session-level LLM observability platform with ClickHouse, Redis, MinIO on OpenShift"
summary: "Langfuse v3 provides session-level LLM observability for multi-turn agentic conversations, offering a purpose-built UI for conversation sessions, traces, and user analytics that complements OpenTelemetry per-request tracing. Deploy as feature-flagged raw Helm templates (no subchart, gated by langfuse.enabled default false, activated via ENABLE_LANGFUSE=true) when you need conversation-level trace grouping by session/user beyond what OpenTelemetry provides — architecture splits into web (Next.js UI/API, NODE_OPTIONS=--max-old-space-size=1536) and worker (Redis queue, ClickHouse migrations) Deployments backed by ClickHouse 24.3, Redis 7.2, MinIO (three buckets: events/exports/media), and shared PostgreSQL with separate langfuse database. Critical patterns: headless auto-initialization via LANGFUSE_INIT_* env vars creates org/project/admin/API keys on first startup; Helm lookup preserves API key Secrets across upgrades preventing authentication mismatch; Python integration uses langfuse.langchain.CallbackHandler (SDK >=3.0.0) injected into LangGraph thread config with session_id/user_id/agent metadata; three sequential init containers (init-db, init-minio, wait-for-clickhouse) prepare infrastructure before web starts. Gotchas: ClickHouse migrations run from the web container requiring wait-for-clickhouse init container; MinIO mc client needs MC_CONFIG_DIR=/tmp/.mc under OpenShift restricted SCC and LANGFUSE_S3_*_FORCE_PATH_STYLE=true for all three bucket categories; both CLICKHOUSE_DATABASE and CLICKHOUSE_DB must be set to the same value; ClickHouse exposes HTTP:8123 for queries and native:9000 for migrations (both required in Service); Helm upgrade without lookup-based Secret reuse regenerates API keys causing auth failures."
metadata:
  type: component
tags:
  tech_stack: [langfuse, clickhouse, redis, minio, postgresql, python, langchain]
  ai_pattern: [agents, evaluation]
  platform: [openshift, kubernetes]
  data_layer: [clickhouse, postgresql]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Full Langfuse v3 stack for multi-turn agentic conversation observability with LangGraph integration"
    approach: "A"
---

# Langfuse

## Overview

Langfuse is deployed as a session-level observability platform for multi-turn LLM agent conversations. It complements OpenTelemetry-based per-request tracing by providing a purpose-built UI for viewing complete conversation sessions, individual traces, and user-level analytics. In this quickstart it is feature-flagged and opt-in, requiring `ENABLE_LANGFUSE=true` before Helm install.

## Tech Stack & Dependencies

- **Runtime:** Langfuse v3 (Next.js-based web UI + separate worker process)
- **Container images:** `ghcr.io/langfuse/langfuse:3` (web), `ghcr.io/langfuse/langfuse-worker` (worker)
- **Key dependencies:** ClickHouse 24.3 (trace storage), Redis 7.2 (async queue), MinIO (S3-compatible object storage for events/exports/media), PostgreSQL (shared instance, separate `langfuse` database)
- **Python SDK:** `langfuse>=3.0.0` (pinned at 3.12.1 in lockfile) via `langfuse.langchain.CallbackHandler`
- **Helm subchart:** None -- deployed as raw templates within the parent chart, gated by `langfuse.enabled`

## Key Patterns

### Feature-Flagged Deployment

All Langfuse templates are wrapped in `{{- if .Values.langfuse.enabled }}`. The flag defaults to `false` in values.yaml and is activated via an environment variable before Helm install.

```bash
# Enable Langfuse observability
export ENABLE_LANGFUSE=true
make helm-uninstall NAMESPACE=$NAMESPACE
make helm-install-test NAMESPACE=$NAMESPACE
```

The Makefile translates this into `--set langfuse.enabled=true` for Helm.

### Multi-Component Architecture (Web + Worker Split)

Langfuse v3 splits into a web Deployment (UI, API, schema migrations) and a worker Deployment (Redis queue processing, ClickHouse migrations). Both share identical database and Redis credentials but use different container images.

```yaml
# Web container (from langfuse-deployment.yaml)
containers:
- name: langfuse
  image: "{{ .Values.langfuse.image.repository }}:{{ .Values.langfuse.image.tag }}"
  env:
  - name: NODE_OPTIONS
    value: "--max-old-space-size=1536"
```

```yaml
# Worker container (from langfuse-worker-deployment.yaml)
containers:
- name: langfuse-worker
  image: {{ .Values.langfuse.worker.image.repository | default "langfuse/langfuse-worker" }}:{{ .Values.langfuse.worker.image.tag | default .Values.langfuse.image.tag }}
  # Worker processes Redis queue and runs ClickHouse migrations on startup
```

### Init Container Chain

The web Deployment uses three sequential init containers to prepare infrastructure before the main container starts:

1. **init-db** -- Creates the `langfuse` database in the shared PostgreSQL instance if it does not exist
2. **init-minio** -- Creates three S3 buckets (`langfuse-events`, `langfuse-exports`, `langfuse-media`) with public download policies
3. **wait-for-clickhouse** -- Polls ClickHouse `/ping` endpoint until ready (critical because schema migrations run from the web container on startup)

```yaml
# init-db: Create langfuse database if it doesn't exist (from langfuse-deployment.yaml)
command:
- /bin/bash
- -c
- |
  until psql -c '\q' 2>/dev/null; do
    echo "Waiting for PostgreSQL..."
    sleep 2
  done
  psql -v ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname=postgres <<-EOSQL
      SELECT 'CREATE DATABASE {{ .Values.langfuse.database.name }}'
      WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '{{ .Values.langfuse.database.name }}')\gexec
  EOSQL
```

### Headless Initialization (Auto-Setup)

Langfuse is configured for headless initialization, automatically creating the organization, project, admin user, and API keys on first startup via `LANGFUSE_INIT_*` environment variables.

```yaml
# From values.yaml -- auto-initialization config
config:
  initOrgId: "self-service-agent-org"
  initOrgName: "Self Service Agent"
  initProjectId: "self-service-agent-project"
  initUserEmail: "admin@example.com"
  initUserName: "Admin User"
  initUserPassword: "langgraph_password"  # Change for production!
```

### API Key Persistence Across Helm Upgrades

A `lookup` function checks for an existing Secret before generating new API keys, preventing key/database mismatch after Helm upgrades.

```yaml
# From langfuse-deployment.yaml -- reuse existing keys
{{- $existingSecret := lookup "v1" "Secret" .Release.Namespace (printf "%s-langfuse-api-keys" (include "self-service-agent.fullname" .)) }}
{{- if $existingSecret }}
data:
  # Reuse existing keys from previous installation to avoid mismatch with LangFuse database
  public-key: {{ index $existingSecret.data "public-key" }}
  secret-key: {{ index $existingSecret.data "secret-key" }}
{{- else }}
stringData:
  public-key: {{ .Values.langfuse.config.initApiPublicKey | default (printf "pk-lf-%s" (randAlphaNum 32)) | quote }}
  secret-key: {{ .Values.langfuse.config.initApiSecretKey | default (printf "sk-lf-%s" (randAlphaNum 64)) | quote }}
{{- end }}
```

### LangGraph Callback Integration

The agent service integrates Langfuse via the `langfuse.langchain.CallbackHandler`, injected into LangGraph's thread config. Session ID, user ID, and agent name are passed as metadata for filtering in the Langfuse UI.

```python
# From lg_flow_state_machine.py -- get_langfuse_handler()
def get_langfuse_handler() -> Optional[Any]:
    enabled = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
    if not enabled:
        return None
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    host = os.getenv("LANGFUSE_HOST", "http://langfuse:3000")
    if not public_key or not secret_key:
        return None
    handler = CallbackHandler()
    return handler
```

```python
# From lg_flow_state_machine.py -- ConversationSession.__init__()
langfuse_handler = get_langfuse_handler()
if langfuse_handler:
    self.thread_config["callbacks"] = [langfuse_handler]
    metadata = {
        "langfuse_session_id": self.thread_id,
        "langfuse_tags": ["langgraph", agent_name],
    }
    if self.authoritative_user_id:
        metadata["langfuse_user_id"] = self.authoritative_user_id
    self.thread_config["metadata"] = metadata
```

### S3/MinIO Integration with Force Path Style

Langfuse v3 uses S3-compatible storage for three separate concerns (events, batch exports, media). When using MinIO, `FORCE_PATH_STYLE` must be set to `true` for each bucket category.

```yaml
# From langfuse-deployment.yaml -- S3 event upload config
- name: LANGFUSE_S3_EVENT_UPLOAD_ENABLED
  value: "true"
- name: LANGFUSE_S3_EVENT_UPLOAD_BUCKET
  value: "langfuse-events"
- name: LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT
  value: http://{{ include "self-service-agent.fullname" . }}-minio:9000
- name: LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE
  value: "true"
```

## Configuration

- **Environment variables (agent-service side):**
  - `LANGFUSE_ENABLED` -- Toggle tracing on/off (injected via _env-helpers.tpl)
  - `LANGFUSE_PUBLIC_KEY` -- Project public key (from langfuse-api-keys Secret)
  - `LANGFUSE_SECRET_KEY` -- Project secret key (from langfuse-api-keys Secret)
  - `LANGFUSE_HOST` -- Internal service URL (defaults to `http://<release>-langfuse:3000`)

- **Environment variables (Langfuse server side):**
  - `DATABASE_URL` -- PostgreSQL connection string for the `langfuse` database
  - `CLICKHOUSE_URL` -- HTTP connection to ClickHouse
  - `CLICKHOUSE_MIGRATION_URL` -- Native protocol URL for ClickHouse migrations (port 9000)
  - `CLICKHOUSE_CLUSTER_ENABLED` -- Set to `false` for single-node deployment
  - `REDIS_CONNECTION_STRING` -- Redis connection for async queue
  - `NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY` -- Auto-generated security secrets
  - `LANGFUSE_S3_*` -- Three sets (EVENT_UPLOAD, BATCH_EXPORT, MEDIA_UPLOAD) for MinIO buckets
  - `TELEMETRY_ENABLED` -- Set to `false` to disable Langfuse telemetry
  - `NODE_OPTIONS` -- `--max-old-space-size=1536` for the web container

- **Helm values (key overrides):**
  - `langfuse.enabled` -- Master toggle (default: false)
  - `langfuse.image.tag` -- Langfuse version (default: "3")
  - `langfuse.clickhouse.version` -- ClickHouse version (default: "24.3")
  - `langfuse.redis.version` -- Redis version (default: "7.2")
  - `langfuse.minio.version` -- MinIO version
  - `langfuse.externalAccess.enabled` -- Create OpenShift Route (default: true)
  - `langfuse.config.initOrgId` -- Headless init org ID
  - `langfuse.service.port` -- Web UI port (default: 3000)

## Known Gotchas

- **ClickHouse migrations run from the WEB container on startup** (per code comment in langfuse-deployment.yaml). The `wait-for-clickhouse` init container is critical to prevent migration failures. The worker also runs ClickHouse migrations -- the comment in langfuse-worker-deployment.yaml explicitly warns: "Do NOT set LANGFUSE_AUTO_CLICKHOUSE_MIGRATION_DISABLED to true".
- **MinIO mc client needs writable config directory on OpenShift** -- The init-minio container sets `MC_CONFIG_DIR=/tmp/.mc` because the default config path is not writable under restricted SCC (`# Set config directory to /tmp (writable in OpenShift)`).
- **API key mismatch after Helm upgrade** -- Without the `lookup`-based Secret reuse pattern, Helm would regenerate API keys on every upgrade, causing authentication failures against the existing Langfuse database.
- **ClickHouse uses two protocols** -- HTTP on port 8123 (for queries and health checks) and native protocol on port 9000 (for migrations via `CLICKHOUSE_MIGRATION_URL`). Both ports must be exposed in the ClickHouse Service.
- **LANGFUSE_S3_*_FORCE_PATH_STYLE must be "true" for MinIO** -- MinIO uses path-style S3 URLs rather than virtual-hosted-style. This must be set for all three bucket categories (events, exports, media).
- **Dual ClickHouse env vars required** -- Both `CLICKHOUSE_DATABASE` and `CLICKHOUSE_DB` must be set to the same value (seen in both web and worker deployment templates).

## Testing Notes

- Deploy with `ENABLE_LANGFUSE=true` and run `make generate-two-sessions` to populate traces
- Verify web UI accessible via OpenShift Route (login: admin@example.com / langgraph_password)
- Check that traces appear under Tracing in the Langfuse UI after generating conversations
- Verify sessions group multi-turn traces by thread ID and show associated user IDs
- To clean up: set `ENABLE_LANGFUSE=false` and re-run `make helm-uninstall`

## Related Patterns

- `pgvector.md` -- Shared PostgreSQL instance used for Langfuse metadata
- `redis.md` -- Separate Redis StatefulSet for Langfuse async queue (not shared with application Redis)
- `minio.md` -- Shared MinIO pattern for S3-compatible object storage
- `observability-stack.md` -- OpenTelemetry-based per-request tracing (complementary to Langfuse session-level view)
