---
name: phoenix
description: Arize Phoenix LLM observability and tracing server deployed as a Helm subchart on OpenShift
summary: "Arize Phoenix provides LLM observability by collecting OpenTelemetry traces from LangChain/LangGraph pipelines via the arizephoenix/phoenix container, using phoenix.otel.register with arize-phoenix-otel and openinference-instrumentation-langchain client libraries registered at module-import time before FastAPI/Flask routes load. Approach A (OpenShift) deploys as a local Helm subchart (bundled under charts/phoenix/, not a Chart.yaml dependency) with OTLP HTTP port 6006, PostgreSQL storage via PHOENIX_SQL_DATABASE_URL from shared pgvector Secret (postgresql+asyncpg:// required), Route exposure (ingress disabled), busybox/wget Helm test, oc rollout status init container, and always-on tracing; Approach B (local dev) uses podman-compose with gRPC OTLP port 4317, file-based storage via named volume (PHOENIX_WORKING_DIR=/mnt/data), auto_instrument=True for zero-config Flask/LangGraph instrumentation, and opt-in tracing via PHOENIX_COLLECTOR_ENDPOINT with conditional import guard for zero overhead. Critical config: COLLECTOR_ENDPOINT=http://<release>-phoenix:6006/v1/traces with explicit LangChainInstrumentor and version-pinned deps (A) vs PHOENIX_COLLECTOR_ENDPOINT=http://phoenix:4317 with unpinned auto-discovery (B); Helm values image.repository/image.tag configure the container image and autoscaling.enabled controls HPA. Common gotchas: Phoenix shares the same PostgreSQL instance and pgvector Secret as the application (A), default resources: {} risks unbounded memory, gRPC port 4317 is only available in compose (Helm exposes only HTTP 6006), test stubbing needed for module-level init_tracing() (B), and SHA256 digest pin in compose requires manual updates for upgrades."
metadata:
  type: component
tags:
  tech_stack: [phoenix, arize, opentelemetry, python, langchain, langgraph, flask]
  ai_pattern: [evaluation, agents, multimodal]
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Phoenix deployed as Helm subchart for LangChain tracing with PostgreSQL backend storage"
    approach: "A"
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Phoenix as podman-compose service with gRPC OTLP collection and auto-instrumentation for LangChain/LangGraph tracing"
    approach: "B"
---

# Phoenix

## Overview

Arize Phoenix is an open-source LLM observability platform used in AI Quickstarts to collect and visualize OpenTelemetry traces from LangChain-based pipelines. It runs as a standalone server (via the `arizephoenix/phoenix` container image) and receives OTLP trace data from application backends. In the ansible-log-analysis quickstart it is deployed as a local Helm subchart within the parent umbrella chart, backed by the same PostgreSQL instance used by the application.

## Tech Stack & Dependencies

- **Runtime:** Python-based server (`arizephoenix/phoenix:latest`)
- **Container image:** `arizephoenix/phoenix`
- **Key dependencies:**
  - PostgreSQL database for trace storage (connects via `PHOENIX_SQL_DATABASE_URL`)
  - `arize-phoenix-otel>=0.13.1` (client-side Python library)
  - `openinference-instrumentation-langchain>=0.1.33` (LangChain auto-instrumentation)
- **Helm subchart:** Local subchart at `deploy/helm/ansible-log-monitor/charts/phoenix/` (chart version 0.1.0)

## Key Patterns

### OTLP Trace Collection via OpenTelemetry

Phoenix acts as an OTLP HTTP collector endpoint. The backend registers a tracer provider using `phoenix.otel.register` and instruments LangChain with OpenInference, sending traces to Phoenix's `/v1/traces` endpoint.

```python
# src/alm/utils/phoenix.py
from openinference.instrumentation.langchain import LangChainInstrumentor
from phoenix.otel import register

def register_phoenix():
    phoenix_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    tracer_provider = register(
        project_name="ansible-log-monitor",
        endpoint=phoenix_endpoint,
    )
    LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
    return tracer_provider.get_tracer(__name__)
```

### Early Registration at Module Level

Phoenix tracing is registered at module-import time in the FastAPI entrypoint, before routes are loaded, ensuring all LangChain calls are instrumented from the start.

```python
# src/alm/main_fastapi.py
from alm.utils.phoenix import register_phoenix
load_dotenv()
register_phoenix()
```

The same registration is called in the batch init pipeline (`backend_init_pipeline.py`) before `asyncio.run(main())`.

### PostgreSQL-Backed Storage via Secret Reference

Phoenix stores trace data in PostgreSQL using an async connection string. The Helm chart sources the database URL from a Kubernetes Secret rather than hardcoding credentials.

```yaml
# values.yaml (phoenix subchart)
env:
  - name: PHOENIX_SQL_DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: pgvector
        key: uri
  - name: PHOENIX_WORKING_DIR
    value: "/tmp/phoenix"
```

### OpenShift Route Exposure

The chart enables an OpenShift Route by default (ingress disabled), exposing the Phoenix UI on port 6006 so developers can browse traces from a browser.

```yaml
# values.yaml (phoenix subchart)
route:
  enabled: true
service:
  type: ClusterIP
  port: 6006
  targetPort: 6006
```

### Init Container Dependency Wait

The backend init job uses an init container with `oc rollout status` to block until the Phoenix deployment is ready before starting the pipeline that sends traces.

```yaml
# backend/templates/init-job.yaml
- name: wait-for-phoenix
  image: quay.io/openshift/origin-cli:4.15
  command:
    - sh
    - -c
    - |
      echo "Waiting for Phoenix deployment to be ready..."
      until oc rollout status deployment/{{ .Release.Name }}-phoenix \
        -n {{ .Release.Namespace }} --timeout=10s; do
        sleep 3
      done
```

## Configuration

- **Environment variables:**
  - `PHOENIX_SQL_DATABASE_URL` -- PostgreSQL async connection string for trace storage (sourced from `pgvector` Secret)
  - `PHOENIX_WORKING_DIR` -- Temporary working directory inside the container (`/tmp/phoenix`)
  - `COLLECTOR_ENDPOINT` -- Set on the *backend* side, pointing to `http://alm-phoenix:6006/v1/traces`
- **Config files:** None (configuration is entirely via environment variables)
- **Helm values:**
  - `image.repository` / `image.tag` -- Container image (`arizephoenix/phoenix:latest`)
  - `route.enabled` -- OpenShift Route (default `true`)
  - `service.port` / `service.targetPort` -- Both default to `6006`
  - `autoscaling.enabled` -- HPA support (default `false`)

## Known Gotchas

- **Shared PostgreSQL instance:** Phoenix reuses the same `pgvector` Secret/database as the application. The compose.yaml includes a comment noting this: `"we dont use DATABASE_URL becuase it point to localhost, and the backend server isnt in the same network as phoenix."` The async driver URL (`postgresql+asyncpg://`) is required.
- **Phoenix is a local subchart, not a dependency entry:** Unlike `pgvector` and `minio` which are pulled from the `ai-architecture-charts` remote repository, phoenix is a local subchart under `charts/phoenix/` and is not listed in the parent `Chart.yaml` dependencies. It is bundled directly.
- **No resource limits set by default:** The `resources` field is an empty object `{}` in values.yaml, which could lead to unbounded memory use on clusters with many traces.
- **Docker-compose exposes two collector ports:** In local dev (`compose.yaml`), Phoenix exposes both `6006` (OTLP HTTP) and `4317` (OTLP gRPC), but the Helm chart only exposes port 6006; gRPC collection is not available in the OpenShift deployment.

## Testing Notes

- Helm test template uses a busybox pod with `wget` to verify connectivity to the Phoenix service on port 6006
- After deployment, the Phoenix UI should be accessible via the OpenShift Route; verify traces appear after triggering a LangChain pipeline run
- The backend init job's `wait-for-phoenix` init container confirms the deployment is ready before sending traces

## Related Patterns

- `pgvector.md` -- Database backing Phoenix trace storage
- `fastapi-backend.md` -- Backend that registers the Phoenix tracer
- `observability-stack.md` -- General observability patterns in quickstarts

---

## Approach B: Podman-Compose with gRPC OTLP and Auto-Instrumentation (from multimodal-compliance-monitor)

### When to Use

When Phoenix is needed for local development only (no OpenShift/Helm deployment), the application uses Flask (not FastAPI), and you want zero-config auto-instrumentation of LangChain/LangGraph calls via gRPC OTLP.

### Differences from Approach A

- **Deployment:** Podman-compose service only -- no Helm subchart, no OpenShift Route
- **OTLP protocol:** gRPC on port 4317 (Approach A uses HTTP on port 6006)
- **Instrumentation:** `auto_instrument=True` with auto-discovery (Approach A explicitly instantiates `LangChainInstrumentor`)
- **Storage:** File-based via named volume (`phoenix_data:/mnt/data`) with `PHOENIX_WORKING_DIR` (Approach A uses PostgreSQL via Secret)
- **Backend framework:** Flask (Approach A uses FastAPI)
- **Env var naming:** `PHOENIX_COLLECTOR_ENDPOINT` (Approach A uses `COLLECTOR_ENDPOINT`)

### Podman-Compose Service Definition

Phoenix runs as a pre-built container with no custom Dockerfile, exposing both the UI (6006) and gRPC collector (4317).

```yaml
# deploy/local/podman-compose.yaml
phoenix:
  image: docker.io/arizephoenix/phoenix@sha256:21d06ca...
  container_name: phoenix
  ports:
    - "6006:6006"
    - "4317:4317"
  environment:
    PHOENIX_WORKING_DIR: /mnt/data
  volumes:
    - phoenix_data:/mnt/data
  pull_policy: missing
```

### Auto-Instrumentation Pattern

The `init_tracing()` function is a zero-overhead wrapper: when `PHOENIX_COLLECTOR_ENDPOINT` is not set, it returns immediately with no imports. When set, `phoenix.otel.register` auto-discovers the installed `openinference-instrumentation-langchain` package and instruments all LangChain/LangGraph calls without explicit instrumentor setup.

```python
# app/backend/tracing.py
def init_tracing() -> None:
    endpoint = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
    if not endpoint:
        return
    from phoenix.otel import register

    register(
        project_name="ppe-compliance-monitor",
        auto_instrument=True,
    )
    log.info("Phoenix tracing enabled -> %s", endpoint)
```

### Flask Entrypoint Registration

Called at module level (before Flask routes), mirroring the same early-registration pattern as Approach A but in a Flask context.

```python
# app/backend/app.py
from tracing import init_tracing
init_tracing()

app = Flask(__name__)
```

### Client-Side Dependencies

The backend declares two Phoenix-related packages. Note `arize-phoenix-otel` (no version pin) and `openinference-instrumentation-langchain` (no version pin), compared to Approach A which pins minimum versions.

```toml
# app/backend/pyproject.toml
dependencies = [
    "arize-phoenix-otel",
    "openinference-instrumentation-langchain",
    # ...
]
```

## Configuration (Approach B)

- **Environment variables:**
  - `PHOENIX_COLLECTOR_ENDPOINT` -- Set on the *backend* service, pointing to `http://phoenix:4317` (gRPC); when absent, tracing is completely disabled
  - `PHOENIX_WORKING_DIR` -- Working directory inside the Phoenix container (`/mnt/data`)
- **Config files:** None
- **Helm values:** Not applicable (local-only deployment)

## Known Gotchas (Approach B)

- **Conditional import for zero overhead:** The `phoenix.otel` import is deferred inside the `if not endpoint: return` guard, so the `arize-phoenix-otel` package is never loaded when tracing is disabled. This is important because the package pulls in heavy OpenTelemetry dependencies.
- **Test stubbing required:** Unit tests must stub out `tracing.init_tracing` because it is called at module import time. The test suite does this with `tracing_mod.init_tracing = lambda: None` inserted into `sys.modules` (see `tests/unit/test_alert_endpoints.py`).
- **No Helm chart for OpenShift:** Unlike Approach A, Phoenix has no Helm chart in this quickstart. If deploying to OpenShift, a chart would need to be created or the Approach A pattern adopted.
- **Pinned image digest:** The compose file uses a SHA256 digest pin (`@sha256:21d06ca...`) rather than a tag, ensuring reproducible builds but requiring manual updates for Phoenix upgrades.

---

## Choosing Between Approaches

| Criteria | Approach A (Helm subchart) | Approach B (Podman-compose) |
|----------|---------------------------|----------------------------|
| Deployment target | OpenShift / Kubernetes | Local dev (Podman/Docker) |
| OTLP protocol | HTTP (port 6006) | gRPC (port 4317) |
| Trace storage | PostgreSQL (via Secret) | File-based (named volume) |
| Instrumentation style | Explicit `LangChainInstrumentor` | `auto_instrument=True` |
| Backend framework | FastAPI | Flask |
| OpenShift Route | Yes | N/A |
| Helm test | busybox/wget connectivity check | N/A |
| Opt-in/opt-out | Always enabled in Helm deploy | Disabled when env var absent |
