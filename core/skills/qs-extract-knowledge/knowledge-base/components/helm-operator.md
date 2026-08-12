---
name: helm-operator
description: "Helm-based Kubernetes operator wrapping Helm charts via operator-sdk, with OLM lifecycle and CRD-driven deployment"
summary: "Wraps existing Helm charts into an OLM-managed Kubernetes operator without custom Go code using operator-sdk v1.37.0 Helm plugin, providing a singleton AIObservabilitySummarizer CR that deploys a multi-component AI observability stack across four namespaces (ai-observability, observability-hub, openshift-logging, openshift-cluster-observability-operator). Use when you need CRD-driven lifecycle management for a Helm-based stack with OLM dependency resolution (auto-installs five operators via semver constraints in bundle/metadata/dependencies.yaml) and OperatorHub UI integration via CSV specDescriptors with x-descriptors for password fields, dropdown selects, and field groups -- watches.yaml maps CRD to chart path, and the CRD uses x-kubernetes-preserve-unknown-fields: true for pass-through Helm values. Critical pattern: Makefile prepare-build target copies charts from deploy/helm/ into helm-charts/ (must be real files, not symlinks for Dockerfile COPY) with sed -i.bak for macOS portability before helm dependency update; kube-rbac-proxy sidecar protects /metrics on port 8443 with TLS and SubjectAccessReview authorization. Common gotchas: manager container requires 2Gi memory limit to avoid OOMKilled, CatalogSource must use priority -500 (below redhat-operators at -100) to resolve dependencies from the Red Hat catalog first, RHOAI must be installed separately for RAG/KServe features, and Tempo dependency is pinned to >=0.19.0 <0.20.0 due to a crash bug in 0.18.x."
metadata:
  type: component
tags:
  tech_stack: [operator-sdk, helm, kustomize, olm, podman]
  ai_pattern: [rag, observability, model-serving]
  platform: [openshift, kubernetes, kserve, vllm, rhoai]
  data_layer: [pgvector, minio]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "Helm-based operator deploying a multi-component AI observability stack with OLM dependency management and multi-namespace orchestration"
    approach: "A"
---

# Helm Operator

## Overview

A Helm-based Kubernetes operator built with operator-sdk v1.37.0 that wraps existing Helm charts into an OLM-managed operator without custom Go code. It provides a single Custom Resource (`AIObservabilitySummarizer`) to deploy a complete multi-component AI-powered observability stack on OpenShift, leveraging OLM for dependency operator installation, Helm hooks for cluster configuration, and a singleton CR pattern.

## Tech Stack & Dependencies

- **Runtime:** `quay.io/operator-framework/helm-operator:v1.37.0` (no custom Go code)
- **Container image:** `quay.io/ecosystem-appeng/aiobs-operator:v<VERSION>`
- **Key dependencies:** operator-sdk v1.37.0, kustomize v5.3.0, OPM v1.65.0, kube-rbac-proxy
- **Helm subchart:** Wraps an `aiobs-stack` umbrella chart containing multiple subcharts (mcp-server, openshift-console-plugin, alerting, rag, minio, observability)
- **Container tool:** Prefers `podman`, falls back to `docker`

## Key Patterns

### Helm Operator Pattern (No Custom Go Code)

The operator uses operator-sdk's Helm plugin layout. The `watches.yaml` maps a CRD to a Helm chart; the operator-sdk Helm reconciler renders and applies the chart whenever the CR changes.

```yaml
# watches.yaml
- group: aiobs.rh-ai-quickstart.io
  version: v1alpha1
  kind: AIObservabilitySummarizer
  chart: helm-charts/aiobs-stack
```

The Dockerfile is minimal -- it copies watches.yaml and the Helm charts into the operator-framework base image:

```dockerfile
FROM quay.io/operator-framework/helm-operator:v1.37.0
ENV HOME=/opt/helm
COPY watches.yaml ${HOME}/watches.yaml
COPY helm-charts ${HOME}/helm-charts
WORKDIR ${HOME}
```

### OLM Dependency Management

The operator declares required dependency operators in `bundle/metadata/dependencies.yaml` with semver version constraints. OLM automatically installs these before the operator starts.

```yaml
# bundle/metadata/dependencies.yaml (excerpt)
dependencies:
  - type: olm.package
    value:
      packageName: cluster-observability-operator
      version: ">=1.0.0 <2.0.0"
  - type: olm.package
    value:
      packageName: tempo-product
      version: ">=0.19.0 <0.20.0"
  - type: olm.package
    value:
      packageName: cluster-logging
      version: ">=6.3.0 <6.5.0"
```

Five dependency operators are auto-installed: Cluster Observability Operator, OpenTelemetry Operator, Tempo Operator, Cluster Logging Operator, and Loki Operator.

### CRD with x-kubernetes-preserve-unknown-fields

The CRD uses `x-kubernetes-preserve-unknown-fields: true` on both spec and status, allowing the Helm values to pass through without strict OpenAPI validation. This is the standard approach for Helm operators where the chart's `values.yaml` defines the schema.

```yaml
# config/crd/bases/aiobs.rh-ai-quickstart.io_aiobservabilitysummarizers.yaml
spec:
  group: aiobs.rh-ai-quickstart.io
  names:
    kind: AIObservabilitySummarizer
    shortNames:
      - aiobs
  scope: Namespaced
  versions:
    - name: v1alpha1
      schema:
        openAPIV3Schema:
          properties:
            spec:
              type: object
              x-kubernetes-preserve-unknown-fields: true
```

### Singleton CR Pattern

Only one `AIObservabilitySummarizer` CR is allowed per cluster. Infrastructure components (Tempo, Loki, OTEL, MinIO, Korrel8r) are shared cluster-wide across fixed namespaces.

### Multi-Namespace Deployment

The operator deploys resources to four different namespaces from a single CR:

| Namespace | Components |
|-----------|-----------|
| `ai-observability` | MCP Server, Console Plugin, RAG stack, Alert CronJob |
| `observability-hub` | TempoStack, OTEL Collector, MinIO |
| `openshift-logging` | LokiStack |
| `openshift-cluster-observability-operator` | Korrel8r |

### CSV spec/status Descriptors for OperatorHub UI

The ClusterServiceVersion uses `specDescriptors` with `x-descriptors` to render a user-friendly form in the OpenShift Console when creating the CR. This includes field groups, boolean switches, password fields, and dropdown selects.

```yaml
# config/manifests/bases/aiobs-operator.clusterserviceversion.yaml (excerpt)
specDescriptors:
- description: "REQUIRED (if RAG enabled): Your HuggingFace API token"
  displayName: HuggingFace Token
  path: rag.llm-service.secret.hf_token
  x-descriptors:
  - urn:alm:descriptor:com.tectonic.ui:fieldGroup:LLM Configuration
  - urn:alm:descriptor:com.tectonic.ui:password
- description: Hardware type for LLM deployment
  displayName: Device Type
  path: rag.llm-service.device
  x-descriptors:
  - urn:alm:descriptor:com.tectonic.ui:select:gpu
  - urn:alm:descriptor:com.tectonic.ui:select:hpu
  - urn:alm:descriptor:com.tectonic.ui:select:cpu
```

### Prepare-Build Chart Copy Pattern

The Makefile `prepare-build` target copies Helm charts from a shared `deploy/helm/` directory into the operator's `helm-charts/` directory, updating image repositories and tags via `sed` before building. This keeps the operator charts in sync with standalone Helm chart development.

```makefile
# Makefile (excerpt)
prepare-build:
	@sed -i.bak '/repository:.*mcp-server/s|repository: .*|repository: $(MCP_SERVER_IMAGE)|' \
	  ../helm/aiobs-stack/values.yaml && rm -f ../helm/aiobs-stack/values.yaml.bak
	@cp -r ../helm/aiobs-stack helm-charts/
	@cd helm-charts/aiobs-stack && helm dependency update >/dev/null
```

### CatalogSource with Priority

The CatalogSource uses a low priority (`-500`) so OLM resolves dependencies from the default `redhat-operators` catalog (`-100`) first, preventing version conflicts with Red Hat-provided operators.

```yaml
# catalog-source.yaml
apiVersion: operators.coreos.com/v1alpha1
kind: CatalogSource
metadata:
  name: aiobs-operator-catalog
  namespace: openshift-marketplace
spec:
  sourceType: grpc
  image: quay.io/ecosystem-appeng/aiobs-operator-catalog:v3.2.0
  priority: -500
  updateStrategy:
    registryPoll:
      interval: 10m
```

### kube-rbac-proxy Sidecar

The operator deployment includes a kube-rbac-proxy sidecar container that protects the `/metrics` endpoint with Kubernetes RBAC authorization via SubjectAccessReviews. The manager binds metrics to `127.0.0.1:8080` (localhost only) and the proxy exposes them on port `8443` with TLS.

```yaml
# config/default/manager_auth_proxy_patch.yaml (excerpt)
- name: kube-rbac-proxy
  image: registry.redhat.io/openshift4/ose-kube-rbac-proxy-rhel9@sha256:883be...
  args:
  - "--secure-listen-address=0.0.0.0:8443"
  - "--upstream=http://127.0.0.1:8080/"
- name: manager
  args:
  - "--metrics-bind-address=127.0.0.1:8080"
  - "--leader-elect"
  - "--leader-election-id=aiobs-operator"
```

## Configuration

- **Environment variables:** None directly on the operator; all configuration flows through the CR spec into Helm values
- **Config files:**
  - `watches.yaml` - Maps CRD group/version/kind to Helm chart path
  - `helm-charts/model-config.json` - External LLM provider configuration (OpenAI, Google, Anthropic) with pricing info
  - `config/samples/aiobs_v1alpha1_aiobservabilitysummarizer.yaml` - Example CR with all configurable fields
- **Helm values (via CR spec):**
  - `rag.enabled` - Toggle RAG/LLM stack (default: `true`)
  - `rag.llm-service.device` - Hardware type: `gpu`, `hpu`, `gpu-amd`, `cpu`
  - `rag.llm-service.secret.hf_token` - HuggingFace API token (required when RAG enabled)
  - `rag.global.models.<model-name>.enabled` - Model selection (enable only one)
  - `rag.llama-stack.managedByOperator` - Use LlamaStack operator CRD (requires RHOAI 3.x)
  - `alerting.enabled` - Toggle alert analysis CronJob (default: `false`)
  - `mcpServer.enabled` - MCP Server (default: `true`)
  - `consolePlugin.enabled` - OpenShift Console plugin (default: `true`)
  - `global.devMode` - Development mode with browser-cached API keys (default: `false`)
  - `loki.lokiStack.storageClassName` - Storage class for Loki PVCs (empty for cluster default)

## Known Gotchas

- **Operator requires 2Gi memory:** The manager container has resource limits of `cpu: 1000m, memory: 2Gi` with requests of `cpu: 100m, memory: 512Mi`. The README explicitly warns about OOMKilled if resources are insufficient (from `config/manager/manager.yaml`).
- **CatalogSource priority matters:** The CatalogSource uses `priority: -500` (lower than the default `redhat-operators` at `-100`) with a comment: "Lower priority than redhat-operators (-100) so OLM resolves dependencies from there." Without this, OLM might pull dependency operators from the custom catalog instead of the official Red Hat catalog.
- **Prepare-build uses sed with .bak for macOS compatibility:** The `prepare-build` Makefile target uses `sed -i.bak` followed by `rm -f *.bak` to work on both GNU and BSD sed (macOS). This is a portability pattern for Makefiles that modify files in-place.
- **Helm charts must be copied, not symlinked:** The Dockerfile uses `COPY helm-charts` and a comment says "use tar to resolve symlinks," though the actual copy is direct. The `prepare-build` target copies charts from `../helm/` into `helm-charts/` and runs `helm dependency update` to regenerate `.tgz` archives.
- **FBC catalog file not yet used:** The `catalog/aiobs-operator.yaml` contains a File-Based Catalog entry but a comment notes: "NOTE: This file is NOT currently used in the build process. The current catalog build uses SQLite-based index (opm index add). This file is maintained for future migration to File-Based Catalogs."
- **Tempo operator version constraint is tight:** The dependencies pin Tempo to `>=0.19.0 <0.20.0` with the comment: "crash bug from v0.18.x is fixed in v0.19.x". This narrow range requires manual updates when newer Tempo versions are released.
- **RHOAI not auto-installed by OLM:** Unlike the five dependency operators, OpenShift AI (RHOAI) must be installed separately before using RAG features. The README states: "OpenShift AI (RHOAI) for KServe/InferenceService is NOT auto-installed and must be installed separately."

## Testing Notes

- **Verify operator is running:** `oc get pods -n openshift-operators -l control-plane=controller-manager`
- **Check CSV status:** `oc get csv -n openshift-operators | grep aiobs-operator` -- should show `Succeeded`
- **Verify all dependency operators installed:** `oc get csv -n openshift-operators | grep -E "cluster-observability|tempo|loki|logging|opentelemetry"`
- **Check operator logs:** `oc logs -n ai-observability -l control-plane=controller-manager -f`
- **Run locally for development:** `cd deploy/operator && make install && make run`
- **Scorecard tests:** Bundle includes OLM scorecard test configuration in `bundle/tests/scorecard/`

## Related Patterns

- `dependency-operators.md` - OLM dependency operator installation patterns
- `observability-stack.md` - The observability infrastructure this operator deploys
- `minio.md` - MinIO object storage component
- `otel-collector.md` - OpenTelemetry collector component
- `tempo.md` - Tempo distributed tracing component
- `llm-service.md` - LLM serving via KServe/vLLM
