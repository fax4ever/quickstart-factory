---
name: phoenix
description: Arize Phoenix LLM observability and tracing server deployed as a Helm subchart on OpenShift
summary: "Arize Phoenix provides LLM observability by collecting OpenTelemetry traces from LangChain pipelines via OTLP HTTP on port 6006, deployed as a local Helm subchart (bundled under charts/phoenix/, not a Chart.yaml dependency) on OpenShift with Route exposure (ingress disabled) and busybox/wget Helm test for connectivity verification. Use when LangChain-based backends need trace visualization and debugging — the backend instruments via phoenix.otel.register with LangChainInstrumentor (from arize-phoenix-otel and openinference-instrumentation-langchain), registered at module-import time before FastAPI routes load, with COLLECTOR_ENDPOINT pointing to http://<release>-phoenix:6006/v1/traces and an init container using oc rollout status to block until Phoenix is ready. Trace storage uses PostgreSQL via PHOENIX_SQL_DATABASE_URL sourced from the pgvector Kubernetes Secret (requires postgresql+asyncpg:// async driver), PHOENIX_WORKING_DIR=/tmp/phoenix, and the arizephoenix/phoenix container image configured through Helm values image.repository/image.tag. Common gotchas: Phoenix shares the same PostgreSQL instance and pgvector Secret as the application, default resources: {} risks unbounded memory on busy clusters, and gRPC collection (port 4317) is only available in Docker Compose — the Helm chart exposes only HTTP port 6006."
metadata:
  type: component
tags:
  tech_stack: [phoenix, arize, opentelemetry, python, langchain]
  ai_pattern: [evaluation, agents]
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Phoenix deployed as Helm subchart for LangChain tracing with PostgreSQL backend storage"
    approach: "A"
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
