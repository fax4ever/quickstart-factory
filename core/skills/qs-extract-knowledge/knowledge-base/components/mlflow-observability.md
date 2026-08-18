---
name: mlflow-observability
description: MLflow v3 tracing and evaluation integration for LangGraph agents on RHOAI with Kubernetes auth
summary: "MLflow v3 provides automatic LangGraph/LangChain agent tracing via mlflow.langchain.autolog() and agent-level evaluation via mlflow.genai.evaluate() with deterministic and LLM-as-a-judge scorers (RelevanceToQuery, Safety, ToolCallCorrectness) on RHOAI. Use standalone deployment (local filesystem backend, S3 artifacts via MinIO) for dev/testing and RHOAI 3.4+ managed MLflow for production; enable Kagenti auto-management (kagenti.mlflow.autoManaged=true) to auto-discover the MLflow CR, inject env vars, create experiments, and handle RBAC -- which disables manual Helm RBAC and env var templates via conditional guards. Three auth modes in priority order: Kubernetes auth plugin (MLFLOW_TRACKING_AUTH=kubernetes) using SubjectAccessReview against mlflow.kubeflow.org CRDs via ClusterRole, explicit MLFLOW_TRACKING_TOKEN, or mounted SA token; initialization runs in a background daemon thread for graceful degradation with _autolog_enabled briefly false after startup, and a trace-to-observation converter maps traces to LangFuse-compatible format with 60s TTL cache. Standalone pip-installs boto3/psycopg2-binary at runtime (requires internet, 60s readiness delay), uses ephemeral /tmp/mlflow-data lost on pod restart, and has a version discrepancy (compose v2.21.3 vs standalone v3.10.1 vs SDK pin >=3.1.0,<3.11); EvalHub needs its own ClusterRoleBindings for MLflow kubernetes-auth or gets 403 PERMISSION_DENIED."
metadata:
  type: component
tags:
  tech_stack: [mlflow, python, fastapi, langchain, langgraph]
  ai_pattern: [agents, evaluation]
  platform: [rhoai, openshift, kubernetes, kserve]
  data_layer: [postgresql, minio]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "MLflow v3 autolog for LangGraph agent tracing with three auth modes and dual deployment (standalone + RHOAI-managed)"
    approach: "A"
---

# MLflow Observability

## Overview

MLflow provides automatic tracing for LangGraph/LangChain agents and LLM-as-a-judge evaluation on RHOAI. The integration uses `mlflow.langchain.autolog()` to capture all agent interactions without explicit callbacks. It supports two deployment models: a standalone container for local dev and RHOAI 3.4+ managed MLflow for production, with three authentication modes including the Kubernetes auth plugin.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11+, `mlflow>=3.1.0,<3.11`
- **Container image (local dev):** `ghcr.io/mlflow/mlflow:v2.21.3` (compose) / `ghcr.io/mlflow/mlflow:v3.10.1` (standalone YAML)
- **Key dependencies:** `boto3`, `psycopg2-binary` (for S3 artifact storage and PostgreSQL backend store)
- **Helm subchart:** None -- uses standalone deployment YAML or RHOAI-managed MLflow operator

## Key Patterns

### Autolog Initialization at Startup

MLflow tracing is initialized once at FastAPI startup via a background thread to avoid blocking the application if the MLflow server is slow or unreachable. Graceful degradation is a design principle -- tracing never blocks the conversation.

```python
# packages/api/src/observability.py
def _do_mlflow_init() -> None:
    global _autolog_enabled
    try:
        import mlflow
        import mlflow.langchain
        from .core.config import settings

        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
        mlflow.set_experiment(settings.MLFLOW_EXPERIMENT_NAME)
        mlflow.langchain.autolog()
        _autolog_enabled = True
    except Exception:
        logger.warning("Failed to initialize MLFlow tracing", exc_info=True)
```

### Three-Tier Authentication

The integration supports three authentication modes in priority order, configured through environment variables and auto-detected ServiceAccount tokens.

```python
# packages/api/src/observability.py -- _configure_auth()
# Mode 1: MLFLOW_TRACKING_AUTH=kubernetes (RHOAI 3.4+ plugin)
#   Reads mounted SA token and derives workspace from pod namespace automatically.
# Mode 2: Explicit MLFLOW_TRACKING_TOKEN from settings or env var.
# Mode 3: Mounted SA token at /run/secrets/kubernetes.io/serviceaccount/token (legacy).
```

### Trace-to-Observation Conversion (MLflow to LangFuse-compatible format)

A purpose-built client converts MLflow traces to a LangFuse-compatible observation format, enabling a shared monitoring dashboard that works with either backend. Includes a 60-second in-memory TTL cache to avoid repeated API calls on dashboard refreshes.

```python
# packages/api/src/services/mlflow_client.py
def _trace_to_observation(trace: Any) -> dict[str, Any]:
    # Extract token counts from span attributes
    for span in trace.data.spans:
        attrs = getattr(span, "attributes", {}) or {}
        if "llm.token_count.prompt" in attrs:
            input_tokens += int(attrs.get("llm.token_count.prompt", 0))
        if "llm.model" in attrs and not model_name:
            model_name = attrs.get("llm.model")
    return {
        "startTime": start_time, "endTime": end_time,
        "model": model_name, "level": level,
        "usage": {"input": input_tokens, "output": output_tokens},
    }
```

### RBAC for RHOAI 3.4+ Kubernetes Auth

MLflow on RHOAI uses `--app-name=kubernetes-auth` which authorizes via Kubernetes SubjectAccessReview. The Helm chart creates a ClusterRole granting access to MLflow CRDs (`mlflow.kubeflow.org`), a dedicated ServiceAccount, and ClusterRoleBindings.

```yaml
# deploy/helm/mortgage-ai/templates/mlflow-rbac.yaml
rules:
  - apiGroups: [mlflow.kubeflow.org]
    resources: [datasets, experiments, registeredmodels]
    verbs: [get, list, create, update]
  - apiGroups: [mlflow.kubeflow.org]
    resources: [gatewayendpoints]
    verbs: [get, list]
  - apiGroups: [mlflow.kubeflow.org]
    resources: [gatewayendpoints/use]
    verbs: [create]
```

### Kagenti Auto-Managed MLflow

When `kagenti.mlflow.autoManaged=true`, the Kagenti Operator MLflow controller handles MLflow lifecycle automatically: auto-discovers the MLflow instance from the `mlflows.mlflow.opendatahub.io` CR, creates experiments, injects env vars, and configures RBAC. Helm templates conditionally skip manual RBAC and env var injection.

```yaml
# deploy/helm/mortgage-ai/templates/api-deployment.yaml
{{- if not (dig "mlflow" "autoManaged" false .Values.kagenti) }}
- name: MLFLOW_TRACKING_URI
  valueFrom:
    secretKeyRef:
      name: {{ include "mortgage-ai.fullname" . }}-secret
      key: MLFLOW_TRACKING_URI
{{- end }}
```

### Standalone Deployment for Development/Testing

A standalone MLflow v3 YAML exists outside the Helm chart as a temporary bridge until RHOAI ships MLflow v3 natively. It uses local file-backed storage with S3 artifact destination via MinIO.

```yaml
# deploy/mlflow-standalone.yaml
command:
  - /bin/sh
  - -c
  - |
    pip install --no-cache-dir --target /tmp/pylibs boto3 psycopg2-binary &&
    export PYTHONPATH="/tmp/pylibs:$PYTHONPATH" &&
    mlflow server \
      --host 0.0.0.0 --port 5000 \
      --backend-store-uri /tmp/mlflow-data \
      --artifacts-destination s3://mlflow \
      --serve-artifacts
```

### Agent Evaluation with MLflow Genai

MLflow's `mlflow.genai.evaluate()` runs agent-level evaluation using both deterministic custom scorers and LLM-as-a-judge scorers. Supports two modes: `simple` (fast, no LLM calls) and `llm-judge` (full evaluation using MLflow built-in scorers like `RelevanceToQuery`, `Safety`, `ToolCallCorrectness`).

```python
# evaluations/run_agent_eval.py
result = mlflow.genai.evaluate(
    data=eval_data,
    predict_fn=predict_fn,
    scorers=scorers,
)
```

## Configuration

- **Environment variables:**
  - `MLFLOW_TRACKING_URI` -- MLflow server URL; when set, tracing is active; leave blank to disable
  - `MLFLOW_EXPERIMENT_NAME` -- experiment name for grouping traces (default: `mortgage-ai`)
  - `MLFLOW_TRACKING_AUTH` -- set to `kubernetes` on RHOAI 3.4+ for the Kubernetes auth plugin
  - `MLFLOW_TRACKING_TOKEN` -- bearer token for authentication (not needed with `kubernetes` auth)
  - `MLFLOW_WORKSPACE` -- workspace name for multi-tenant deployments; auto-detected from pod namespace when using Kubernetes auth
  - `MLFLOW_TRACKING_INSECURE_TLS` -- skip TLS verification (default: `false`)
  - `MLFLOW_S3_ENDPOINT_URL` -- S3-compatible endpoint for artifact storage (MinIO)
  - `MLFLOW_SERVER_DISABLE_SECURITY_MIDDLEWARE` -- set to `true` in standalone dev deployment
- **Config files:** Settings defined in `packages/api/src/core/config.py` via Pydantic `BaseSettings`
- **Helm values:** Under `secrets.MLFLOW_*` for env vars and `mlflow.rbac.*` for RBAC configuration

## Known Gotchas

- The standalone YAML (`deploy/mlflow-standalone.yaml`) installs `boto3` and `psycopg2-binary` at runtime via `pip install` in the container command because the base `ghcr.io/mlflow/mlflow` image does not include them. This means the container requires internet access on first start.
- The standalone deployment uses `/tmp/mlflow-data` as its backend store (local filesystem, not PostgreSQL), so data is lost on pod restart. The compose deployment uses a PostgreSQL backend store for persistence.
- MLflow initialization runs in a background daemon thread (`threading.Thread(target=_do_mlflow_init, daemon=True)`) -- the `_autolog_enabled` flag may be `False` for a brief window after startup while the thread completes.
- The Helm template for MLflow env vars is wrapped in `{{- if not (dig "mlflow" "autoManaged" false .Values.kagenti) }}`, so when Kagenti auto-management is enabled, the manual env vars are skipped entirely.
- The mlflow-rbac template is also guarded with `{{- if and .Values.mlflow.rbac.enabled (not (dig "mlflow" "autoManaged" false .Values.kagenti)) }}` -- enabling Kagenti auto-management disables both RBAC and env var injection from the Helm chart.
- EvalHub requires its own ClusterRoleBindings to MLflow (`evaluations/evalhub/04-rbac-mlflow.yaml`) because MLflow's `kubernetes-auth` performs SubjectAccessReview -- without these, EvalHub gets 403 PERMISSION_DENIED.
- There is a version discrepancy: compose uses MLflow v2.21.3 while standalone YAML uses v3.10.1 and the Python SDK pins `>=3.1.0,<3.11`. The compose image lags behind.
- The `mlflow_client.py` trace fetcher uses `experiment_ids=[]` (empty list) in `search_traces()` to search across all experiments rather than targeting a specific one.

## Testing Notes

- The `mlflow_client.py` module has comprehensive pytest coverage in `packages/api/tests/test_mlflow_client.py` -- tests mock `mlflow.MlflowClient` and verify trace conversion, caching, model filtering, and error handling.
- To verify MLflow is active: check startup logs for `"MLFlow autolog initialized successfully"` or `"MLFlow tracing: ACTIVE"`.
- For local dev with compose: `podman-compose --profile observability up -d` enables the mlflow service. The API connects via `MLFLOW_TRACKING_URI=http://mlflow:5000`.
- For standalone deployment: `oc apply -f deploy/mlflow-standalone.yaml -n mortgage-ai`. The readiness probe has a 60-second initial delay to allow pip install to complete.
- Agent evaluation requires `MLFLOW_TRACKING_TOKEN=$(oc whoami --show-token)` when running outside the cluster.

## Related Patterns

- `evaluations.md` -- agent evaluation framework that uses MLflow as its tracking backend
- `langfuse.md` -- alternative observability backend; the `_trace_to_observation` converter maps MLflow traces to LangFuse-compatible format
- `minio.md` -- S3-compatible storage used for MLflow artifact persistence
- `keycloak.md` -- identity provider; MLflow Kubernetes auth is separate from Keycloak OIDC
