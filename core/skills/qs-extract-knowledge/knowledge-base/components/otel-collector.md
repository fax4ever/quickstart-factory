---
name: otel-collector
description: OpenTelemetry Collector deployed via OTel Operator CRD with central deployment and sidecar injection for LLM observability
summary: "Provides centralized LLM and application telemetry on RHOAI via the OTel Operator's OpenTelemetryCollector CRD (mode: deployment, upgradeStrategy: automatic) in a hub-and-spoke architecture -- a central collector in observability-hub receives OTLP from workload-level collectors, routing traces to Tempo dev tenant (X-Scope-OrgID header) and exposing metrics. Approach A (sidecar injection) suits model-serving observability -- vLLM sidecars scrape Prometheus on localhost:8000 alongside OTLP traces, LlamaStack sidecars forward traces only, each toggled via sidecars.*.enabled Helm values with per-pod sidecar.opentelemetry.io/inject annotation and k8sattributes processor; Approach B (Instrumentation CR) suits Python application tracing (FastAPI, RAG) with namespace-level instrumentation.opentelemetry.io/inject-python annotation, no sidecar containers, simpler pipeline (batch + memory_limiter only), and OpenShift Route passthrough TLS for external ingestion. Helm _helpers.tpl constructs centralCollectorEndpoint and tempoGatewayEndpoint dynamically; bearertokenauth authenticates to Tempo gateway using SA token with ca_file: service-ca.crt and insecure: false; namespace-prefixed ClusterRoles grant tempo.grafana.com/dev trace writes and pod/namespace/replicaset access for k8sattributes (requires KUBE_NODE_NAME via fieldRef spec.nodeName); Approach B's Instrumentation CR deploys as Helm pre-install hook (hook-weight: \"-10\") with OTEL_PYTHON_PLATFORM set to glibc or musl matching the base image. OTel Operator appends \"-collector\" to CR name creating doubled \"otel-collector-collector\" service name that sidecars must target, sidecar CR metadata.name must exactly match the injection annotation value, Instrumentation CR must exist before application pods start (enforced by Helm hook), namespace annotation requires pod restart for existing pods, k8sattributes processor exists only in Helm-templated config not base manifests, and two paths exist to apply the Instrumentation CR (Helm template vs envsubst Makefile script)."
metadata:
  type: component
tags:
  tech_stack: [opentelemetry, helm, opentelemetry-operator]
  ai_pattern: [model-serving, observability]
  platform: [openshift, rhoai, kserve, vllm]
  data_layer: []
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Central OTel Collector deployment with vLLM and LlamaStack sidecar injection, Tempo trace export, Prometheus scraping"
    approach: "A"
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "Central OTel Collector with Python auto-instrumentation via Instrumentation CR, namespace-level injection, Tempo distributor export"
    approach: "B"
---

# OpenTelemetry Collector

## Overview

The OpenTelemetry Collector is deployed using the OpenTelemetry Operator's `OpenTelemetryCollector` CRD, providing a hub-and-spoke telemetry architecture for LLM serving workloads on RHOAI. A central collector runs as a Deployment in the `observability-hub` namespace, receiving metrics and traces from model-serving pods via per-workload sidecar collectors that are auto-injected by the OTel Operator. This pattern avoids manual instrumentation plumbing and centralizes export configuration for backends like Tempo and Prometheus.

## Tech Stack & Dependencies

- **Runtime:** OpenTelemetry Collector v0.115.0 (managed by the OTel Operator)
- **Container image:** Managed by the OpenTelemetry Operator (no explicit image reference in the chart)
- **Key dependencies:** Red Hat Build of OpenTelemetry Operator, Tempo TempoStack (trace backend), Kubernetes service-account token auth
- **Helm subchart:** Standalone chart at `helm/02-observability/otel-collector/` (Chart.yaml `apiVersion: v2`, `version: 0.1.0`)

## Key Patterns

### Hub-and-Spoke Collector Architecture

A central collector runs as a `Deployment` and receives OTLP data from sidecar collectors injected into model-serving pods. The sidecars forward everything to the central collector over HTTP, which then routes traces to Tempo and exposes metrics.

```yaml
# Central collector - deployment mode
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: otel-collector
spec:
  mode: deployment
  serviceAccount: otel-collector
  upgradeStrategy: automatic
  managementState: managed
```

### Sidecar Injection via OTel Operator

Sidecar collectors are defined as `OpenTelemetryCollector` CRs with `mode: sidecar`. The OTel Operator injects them into any pod carrying the matching annotation. Each AI service type gets its own sidecar definition.

```yaml
# Sidecar definition - OTel Operator auto-injects into annotated pods
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: vllm-otelsidecar
spec:
  mode: sidecar
  config:
    exporters:
      otlphttp:
        endpoint: 'http://otel-collector-collector.observability-hub.svc.cluster.local:4318'
        tls:
          insecure: true
```

Pods opt in via annotation on the pod template:

```yaml
# In the workload Deployment template
metadata:
  annotations:
    sidecar.opentelemetry.io/inject: llamastack-otelsidecar
```

### vLLM Sidecar with Prometheus Scraping

The vLLM sidecar differs from the LlamaStack sidecar: it includes a `prometheus` receiver that scrapes vLLM's built-in metrics endpoint on `localhost:8000`, in addition to receiving OTLP traces. This creates both a metrics and traces pipeline in a single sidecar.

```yaml
# vLLM sidecar receivers - scrapes vLLM metrics locally
receivers:
  otlp:
    protocols:
      grpc: {}
      http: {}
  prometheus:
    config:
      scrape_configs:
        - job_name: vllm-sidecar
          scrape_interval: 15s
          static_configs:
            - targets: ['localhost:8000']
```

### LlamaStack Sidecar (Traces Only)

The LlamaStack sidecar is simpler -- it only receives OTLP traces (no Prometheus scraping) and forwards them to the central collector. LlamaStack's built-in OpenTelemetry instrumentation sends traces directly via OTLP.

```yaml
# LlamaStack sidecar - traces only, no Prometheus receiver
service:
  pipelines:
    traces:
      exporters: [debug, otlphttp]
      receivers: [otlp]
```

### Bearer Token Auth to Tempo Gateway

The central collector authenticates to the Tempo gateway using the Kubernetes service-account token, mounted at the standard path. The `bearertokenauth` extension is wired into the OTLP HTTP exporter.

```yaml
extensions:
  bearertokenauth:
    filename: "/var/run/secrets/kubernetes.io/serviceaccount/token"
exporters:
  otlphttp/dev:
    endpoint: "https://tempo-tempostack-gateway.observability-hub.svc.cluster.local:8080/api/traces/v1/dev"
    headers:
      X-Scope-OrgID: dev
    tls:
      insecure: false
      ca_file: /var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt
    auth:
      authenticator: bearertokenauth
```

### Templated Endpoint Construction

The Helm chart constructs the Tempo gateway and central collector endpoints using helper templates, making the namespace and service names configurable:

```go
// _helpers.tpl - Tempo gateway endpoint
{{- define "otel-collector.tempoGatewayEndpoint" -}}
{{- with .Values.tempo.gateway }}
{{- printf "%s://%s.%s.svc.cluster.local:%s%s" .protocol .endpoint .namespace .port .path }}
{{- end }}
{{- end }}

// _helpers.tpl - Central collector endpoint for sidecars
{{- define "otel-collector.centralCollectorEndpoint" -}}
{{- printf "http://%s-collector.%s.svc.cluster.local:4318" .Values.collector.name .Values.global.namespace }}
{{- end }}
```

### Cluster-Scoped RBAC for Tempo and K8s Attributes

The collector requires a ClusterRole to write traces to the Tempo `dev` tenant and to list/watch pods, namespaces, and replicasets for the `k8sattributes` processor. The ClusterRole name includes the namespace to avoid conflicts across releases.

```yaml
rules:
  - apiGroups: ['tempo.grafana.com']
    resources: [dev]
    resourceNames: [traces]
    verbs: ['create']
  - apiGroups: ['']
    resources: ['pods', 'namespaces']
    verbs: ['get', 'watch', 'list']
  - apiGroups: ['apps']
    resources: ['replicasets']
    verbs: ['get', 'watch', 'list']
```

## Configuration

- **Environment variables:**
  - `KUBE_NODE_NAME` (via fieldRef `spec.nodeName`) -- used by the `k8sattributes` processor to filter by node
- **Config files:** Collector config is embedded in the `OpenTelemetryCollector` CR spec, not a separate ConfigMap
- **Helm values:**
  - `global.namespace` -- target namespace (default: `observability-hub`)
  - `collector.enabled` -- toggle main collector (default: `true`)
  - `collector.mode` -- deployment mode: `deployment`, `daemonset`, `sidecar`, `statefulset` (default: `deployment`)
  - `sidecars.llamastack.enabled` / `sidecars.vllm.enabled` -- toggle per-workload sidecars
  - `sidecars.*.injectAnnotation` -- annotation value pods use to opt-in to injection
  - `tempo.gateway.*` -- Tempo gateway endpoint components (protocol, endpoint, port, path, namespace)
  - `tempo.auth.orgID` -- Tempo tenant org ID (default: `dev`)
  - `prometheus.scrapeConfigs` -- map of Prometheus scrape targets for the central collector
  - `rbac.create` -- toggle ClusterRole/ClusterRoleBinding creation

## Known Gotchas

- **Sidecar collector name must match injection annotation:** The `metadata.name` of the sidecar `OpenTelemetryCollector` CR must match the value used in `sidecar.opentelemetry.io/inject` on the pod template. The chart uses `sidecars.*.injectAnnotation` for this, but the raw manifest and the Helm template must stay in sync.
- **Central collector service name follows OTel Operator convention:** The OTel Operator appends `-collector` to the CR name when creating the Service, so the sidecar endpoint is `otel-collector-collector.observability-hub.svc.cluster.local:4318` (note the doubled "collector"). This is encoded in the `otel-collector.centralCollectorEndpoint` helper template.
- **ClusterRole name includes namespace to avoid conflicts:** The `otel-collector.clusterResourceName` helper prepends the namespace to the fullname, preventing collisions when multiple Helm releases exist in different namespaces (see `_helpers.tpl`).
- **TLS to Tempo uses OpenShift service-ca:** The exporter sets `ca_file: /var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt` rather than disabling TLS, relying on OpenShift's service CA certificate injection. The `insecure: false` setting is explicit.
- **Kustomization only includes base manifests, not sidecars:** The `kustomization.yaml` only references `sa.yaml`, `clusterrole.yaml`, and `otel-collector.yaml` -- the sidecar manifests are not in the kustomization resource list, suggesting they are deployed separately or only via Helm.
- **k8sattributes processor in Helm values but not in base manifest:** The `values.yaml` includes `k8sattributes` in the processors config and pipelines, but the raw `otel-collector.yaml` base manifest omits it. The Helm-templated version is the authoritative one.

## Testing Notes

- Verify collector is running: `kubectl get opentelemetrycollector otel-collector -n observability-hub`
- Check collector logs: `kubectl logs -n observability-hub deployment/otel-collector-collector`
- OTLP endpoints: gRPC at `:4317`, HTTP at `:4318`, metrics at `:8888`
- Test trace ingestion with curl: `curl -X POST otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/traces -H "Content-Type: application/json" -d '{"resourceSpans": []}'`
- Verify RBAC: `kubectl auth can-i create dev --as=system:serviceaccount:observability-hub:otel-collector`
- Verify sidecar injection: check that pods with the `sidecar.opentelemetry.io/inject` annotation have an extra container

## Related Patterns

- `observability-stack.md` -- broader observability stack including Tempo, Grafana, and operator setup
- `tracing-config.md` -- application-level tracing configuration patterns
- `llamastack.md` -- LlamaStack deployment with OTel sidecar integration

---

## Approach B: Python Auto-Instrumentation via Instrumentation CR (from openshift-ai-observability-summarizer)

### When to Use

Use this approach when observing Python application services (e.g., FastAPI backends, RAG pipelines) rather than model-serving infrastructure. The OTel Operator's `Instrumentation` CR injects Python auto-instrumentation libraries at pod admission time -- no sidecar container needed. This is lighter-weight than Approach A's sidecar pattern and requires no per-pod annotation on Deployment templates; instead, a single namespace-level annotation enables tracing for all Python pods.

### Differences from Approach A

- **No sidecar collectors** -- instrumentation is injected into the application container itself via the OTel Operator's mutating webhook, not via a separate sidecar `OpenTelemetryCollector` CR
- **Namespace-level injection** -- the namespace is annotated with `instrumentation.opentelemetry.io/inject-python="true"` rather than requiring each pod template to carry `sidecar.opentelemetry.io/inject`
- **Instrumentation CR** -- uses `opentelemetry.io/v1alpha1 Instrumentation` CRD instead of additional `OpenTelemetryCollector` CRDs in sidecar mode
- **Application tracing focus** -- targets Python application code (FastAPI, etc.) rather than model-server metrics/traces
- **Simpler collector config** -- no Prometheus receivers or k8sattributes processor; just OTLP receivers with batch and memory_limiter processors
- **Helm pre-install hook** -- the Instrumentation CR is deployed as a Helm `pre-install,pre-upgrade` hook with `hook-weight: "-10"` to ensure the webhook is ready before application pods start

### Python Auto-Instrumentation via Instrumentation CR

The `Instrumentation` CR tells the OTel Operator to inject Python auto-instrumentation libraries into pods at admission time. The CR specifies the collector endpoint, context propagators, and the Python instrumentation image.

```yaml
# Instrumentation CR - deployed as Helm pre-install hook
apiVersion: opentelemetry.io/v1alpha1
kind: Instrumentation
metadata:
  name: python-instrumentation
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "-10"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  exporter:
    endpoint: http://otel-collector-collector.observability-hub.svc.cluster.local:4318
  propagators:
    - tracecontext
    - baggage
    - b3
  python:
    image: "ghcr.io/open-telemetry/opentelemetry-operator/autoinstrumentation-python:latest"
    env:
      - name: OTEL_PYTHON_PLATFORM
        value: "glibc"
```

### Namespace-Level Injection via Makefile

The `setup-tracing` Makefile target applies the Instrumentation CR and annotates the namespace. It uses `envsubst` to inject the Python instrumentation image version from `values.yaml` into the raw script manifest.

```makefile
setup-tracing: namespace
	@export INSTRUMENTATION_PYTHON_IMAGE=$$(yq eval \
	  '.instrumentation.python.image' \
	  deploy/helm/observability/otel-collector/values.yaml); \
	envsubst < deploy/helm/$(INSTRUMENTATION_PATH) \
	  | oc apply -f - -n $(NAMESPACE)
	@oc annotate namespace $(NAMESPACE) \
	  instrumentation.opentelemetry.io/inject-python="true" --overwrite
```

### Simplified Central Collector Pipelines

Without sidecars, the central collector receives OTLP directly from auto-instrumented application pods. The pipeline includes batch and memory_limiter processors but omits the k8sattributes processor and Prometheus receivers found in Approach A.

```yaml
# Collector pipelines - traces to Tempo, metrics to debug
service:
  extensions:
    - bearertokenauth
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch, memory_limiter]
      exporters: [debug, otlphttp/dev]
    metrics:
      receivers: [otlp]
      processors: [batch, memory_limiter]
      exporters: [debug]
```

### OpenShift Route Ingress

The collector exposes an OpenShift Route with passthrough TLS termination, enabling external trace ingestion from outside the cluster.

```yaml
# Collector ingress via OpenShift Route
ingress:
  enabled: true
  type: route
  route:
    termination: passthrough
```

### Configuration

- **Environment variables:**
  - `OTEL_PYTHON_PLATFORM` -- set to `glibc` or `musl` depending on the container base image (set in the Instrumentation CR spec)
- **Helm values:**
  - `instrumentation.enabled` -- toggle Instrumentation CR creation (default: `true`)
  - `instrumentation.name` -- CR name (default: `python-instrumentation`)
  - `instrumentation.exporter.endpoint` -- collector endpoint for auto-instrumented traces
  - `instrumentation.python.image` -- Python auto-instrumentation image version
  - `instrumentation.propagators` -- context propagation formats (default: `tracecontext`, `baggage`, `b3`)
  - `collector.ingress.enabled` / `collector.ingress.type` -- OpenShift Route configuration

### Known Gotchas

- **Instrumentation CR must exist before application pods:** The Helm chart uses `helm.sh/hook: pre-install,pre-upgrade` with `hook-weight: "-10"` to deploy the Instrumentation CR early. Without this, pods starting before the CR exists will not be auto-instrumented.
- **Two paths to apply the Instrumentation CR:** The chart has both a Helm template (`aiobs-stack/templates/instrumentation.yaml`) and a raw script (`otel-collector/scripts/instrumentation.yaml`) that uses `envsubst` for the image. The Makefile `setup-tracing` target uses the raw script path, while Helm install uses the template.
- **OTEL_PYTHON_PLATFORM must match the base image:** The `instrumentation.yaml` script comments note the env var must be `glibc` or `musl` depending on the container base image. The default in `values.yaml` is `glibc`.
- **Namespace annotation is idempotent but pods need restart:** Annotating the namespace with `instrumentation.opentelemetry.io/inject-python="true"` affects pods at admission time only. Existing pods must be restarted to pick up auto-instrumentation.

---

## Choosing Between Approaches

| Criteria | Approach A (Sidecar Injection) | Approach B (Auto-Instrumentation CR) |
|----------|-------------------------------|--------------------------------------|
| **Use case** | Model-serving observability (vLLM, LlamaStack) | Python application tracing (FastAPI, RAG) |
| **Instrumentation method** | Sidecar container per pod via `OpenTelemetryCollector` CR (mode: sidecar) | Library injection via `Instrumentation` CR mutating webhook |
| **Injection scope** | Per-pod annotation (`sidecar.opentelemetry.io/inject`) | Per-namespace annotation (`instrumentation.opentelemetry.io/inject-python`) |
| **Prometheus scraping** | Yes (sidecar scrapes model-server metrics on localhost) | No (OTLP only) |
| **Resource overhead** | Extra container per pod | No extra containers; injected libraries run in-process |
| **Collector complexity** | k8sattributes processor, Prometheus receiver, multiple sidecar CRs | Batch + memory_limiter only, single collector CR |
| **Source quickstart** | lls-observability | openshift-ai-observability-summarizer |
