---
name: alerting
description: "CronJob-based alert receiver that polls Alertmanager for vLLM alerts, generates LLM descriptions, and notifies Slack"
summary: "CronJob-based Python 3.11 alert receiver that polls OpenShift user-workload Alertmanager v2 API for vLLM model-serving alerts, generates human-readable descriptions via llama-stack-client chat_completion with auto-discovered LLM model, and posts formatted notifications to a Slack webhook. Use when bridging Prometheus/Alertmanager observability with LLM-powered incident communication on RHOAI -- the single approach (Helm chart \"alerts\" at deploy/helm/alerting/) deploys a CronJob with concurrencyPolicy: Forbid, six PrometheusRule vLLM alert rules (P95 latency, GPU cache, abort/success rates, inference time, queue time), and cross-namespace RBAC in openshift-user-workload-monitoring. Time-window filtering (TIME_WINDOW default 60s) prevents re-notification, SA token auth reads from mounted secret path or literal env var, CA bundle injected via service.beta.openshift.io/inject-cabundle: \"true\" annotation, and LLAMA_STACK_URL auto-derives as http://llamastack.<namespace>.svc.cluster.local:8321 when Helm value is empty. Auto-discovery via client.models.list() raises StopIteration if no LLM model is registered in Llama Stack, expr/for fields are duplicated as PrometheusRule labels so the LLM prompt can access rule expressions, the cross-namespace RoleBinding requires cluster permissions, and common.pylogger must be available at the Dockerfile build context level."
metadata:
  type: component
tags:
  tech_stack: [python, llama-stack-client, requests, structlog]
  ai_pattern: [model-serving, prompt-chaining]
  platform: [openshift, vllm, rhoai]
  data_layer: []
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "CronJob polling Alertmanager for vLLM alerts with LLM-powered Slack notifications via Llama Stack"
    approach: "A"
---

# Alerting

## Overview

The alerting component is a CronJob-based alert receiver that polls OpenShift's user-workload Alertmanager API for vLLM model-serving alerts, uses Llama Stack to generate human-readable alert descriptions via an LLM, and sends formatted notifications to a Slack webhook. It bridges Prometheus/Alertmanager observability with LLM-powered incident communication, making it a key component in AI-aware observability quickstarts on RHOAI.

## Tech Stack & Dependencies
- **Runtime:** Python 3.11 on UBI9 (`registry.access.redhat.com/ubi9/python-311:latest`)
- **Container image:** `quay.io/ecosystem-appeng/aiobs-metrics-alerting:3.2.0`
- **Key dependencies:** `requests==2.32.5`, `llama-stack-client==0.2.12`, shared `common.pylogger` module (structlog-based)
- **Helm subchart:** Standalone chart at `deploy/helm/alerting/` (chart name: `alerts`, version `0.1.0`)

## Key Patterns

### CronJob-Based Alert Polling

The component runs as a Kubernetes CronJob (default: every minute) rather than a long-running service. It polls the Alertmanager v2 API, filters for new vLLM alerts within a configurable time window, and exits. `concurrencyPolicy: Forbid` prevents overlapping runs.

```yaml
# deploy/helm/alerting/templates/cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: {{ include "alerts.fullname" . }}
spec:
  schedule: {{ .Values.schedule | quote }}
  concurrencyPolicy: Forbid
  suspend: false
```

### Time-Window Alert Filtering

Only alerts that started within a configurable time window (default 60 seconds) are processed. Test alerts (labeled `test_alert: "true"`) and non-vLLM alerts are skipped. This prevents re-notifying on already-handled alerts.

```python
# src/alerting/alert_receiver.py
def is_new_vllm_alert(alert, time_window=TIME_WINDOW):
    alertname = alert['labels'].get('alertname', '')
    if not alertname.startswith("VLLM") or test_alert_label == 'true':
        return False
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    time_threshold = now_utc - datetime.timedelta(seconds=time_window)
    alert_start_time_utc = datetime.datetime.fromisoformat(
        starts_at_iso.replace('Z', '+00:00'))
    return alert_start_time_utc >= time_threshold
```

### LLM-Powered Alert Description Generation via Llama Stack

The component uses `llama-stack-client` to connect to a Llama Stack instance, auto-discovers the first available LLM model, and generates a Slack-ready description from alert labels. The prompt instructs the LLM to interpret Prometheus expressions in plain English and list affected components. A static fallback message is used if the LLM call fails.

```python
# src/alerting/alert_receiver.py
client = LlamaStackClient(base_url=LLAMA_STACK_URL)
llm = next(m for m in client.models.list() if m.model_type == "llm")
response = client.inference.chat_completion(
    model_id=llm.identifier,
    messages=[
        {"role": "system", "content": prompt},
        {"role": "user", "content": labels},
    ],
    stream=False
)
```

### Service Account Token Auth for Alertmanager

The component authenticates to the user-workload Alertmanager using a Kubernetes service account token. The token is read from a mounted secret volume or falls back to a literal env var value.

```python
# src/alerting/alert_receiver.py
token_input = os.getenv("AUTH_TOKEN",
    "/var/run/secrets/kubernetes.io/serviceaccount/token")
if os.path.exists(token_input):
    with open(token_input, "r") as f:
        AUTH_TOKEN = f.read().strip()
else:
    AUTH_TOKEN = token_input
```

### CA Bundle Injection via OpenShift Annotation

TLS verification against the internal Alertmanager endpoint uses a CA bundle injected by OpenShift's service-ca operator through a ConfigMap annotation.

```yaml
# deploy/helm/alerting/templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: trusted-ca-bundle-alerts
  annotations:
    service.beta.openshift.io/inject-cabundle: "true"
```

### PrometheusRule for vLLM Metrics

The Helm chart deploys a `PrometheusRule` resource with six vLLM-specific alert rules covering aborted request rate, P95 latency, success rate, average inference time, P95 queue time, and GPU cache usage. The rules use `openshift.io/user-monitoring: "true"` and `openshift.io/prometheus-rule-evaluation-scope: "leaf-prometheus"` labels for user-workload monitoring.

```yaml
# deploy/helm/alerting/templates/prometheusrule.yaml (excerpt)
- alert: VLLMHighP95Latency
  expr: |
    histogram_quantile(0.95, sum by (instance, job, namespace,
      service, model_name, pod, le)
      (rate(vllm:e2e_request_latency_seconds_bucket[5m]))) > 5
  for: 5m
  labels:
    severity: critical
```

### RBAC for Cross-Namespace Alertmanager Access

The chart creates a ServiceAccount, a service-account-token Secret, and a RoleBinding in the `openshift-user-workload-monitoring` namespace granting `monitoring-alertmanager-api-reader` access.

```yaml
# deploy/helm/alerting/templates/rolebinding.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: alertmanager-user-workload-api-read-binding-{{ .Release.Namespace }}
  namespace: openshift-user-workload-monitoring
subjects:
- kind: ServiceAccount
  name: {{ .Values.serviceAccountName }}
  namespace: {{ .Release.Namespace }}
roleRef:
  kind: Role
  name: monitoring-alertmanager-api-reader
  apiGroup: rbac.authorization.k8s.io
```

## Configuration
- **Environment variables:**
  - `ALERTMANAGER_URL` -- Alertmanager API endpoint (default: internal user-workload monitoring service at port 9095)
  - `SLACK_WEBHOOK_URL` -- Slack incoming webhook URL (sourced from a Kubernetes Secret)
  - `LLAMA_STACK_URL` -- Llama Stack inference endpoint (defaults to in-namespace service `http://llamastack.<namespace>.svc.cluster.local:8321`)
  - `TIME_WINDOW` -- seconds to look back for new alerts (default: `60`)
  - `AUTH_TOKEN` -- service account token path or literal value
- **Config files:** None beyond environment variables
- **Helm values:**
  - `schedule` -- CronJob schedule expression (default: `"*/1 * * * *"`)
  - `image.repository` / `image.tag` -- container image coordinates
  - `slackWebhook.secretName` / `slackWebhook.secretKey` / `slackWebhook.url` -- Slack webhook secret wiring
  - `config.alertmanagerUrl` -- Alertmanager endpoint
  - `config.llamaStackUrl` -- Llama Stack endpoint (auto-derived from namespace if empty)
  - `config.timeWindow` -- alert recency window in seconds

## Known Gotchas
- The `expr` and `for` fields are duplicated as labels in each PrometheusRule alert rule so the LLM prompt can access them when generating descriptions from alert labels (visible in `prometheusrule.yaml`).
- The RoleBinding is created in the `openshift-user-workload-monitoring` namespace, not the release namespace -- this requires cluster permissions to create RoleBindings cross-namespace.
- The `LLAMA_STACK_URL` Helm value defaults to an empty string; the CronJob template uses a Go template expression to auto-derive `http://llamastack.<namespace>.svc.cluster.local:8321` when unset.
- The Dockerfile copies from `alerting/` (relative to the build context at `src/`), and only installs `requests` and `llama-stack-client` -- the `common.pylogger` module must be available at build context level or via a multi-stage build.
- The LLM model is auto-discovered at runtime with `next(m for m in client.models.list() if m.model_type == "llm")` -- this will fail with `StopIteration` if no LLM model is registered in Llama Stack.

## Testing Notes
- Deploy with a test PrometheusRule (the chart includes `VLLMDummyAlwaysFiring` and `VLLMDummyServiceInfo` dummy alerts labeled `test_alert: "true"` for validation without triggering Slack notifications)
- Verify CronJob runs via `oc get jobs` and check pod logs for "Alerts successfully retrieved from Alertmanager" or "No new alerts found"
- Set `SLACK_WEBHOOK_URL` to empty string to suppress Slack delivery during testing (logs "No Slack URL found" as a warning)

## Related Patterns
- Llama Stack inference integration (see `llamastack.md`)
- OpenShift user-workload monitoring (`uwm.md`)
- Observability stack patterns (`observability-stack.md`)
