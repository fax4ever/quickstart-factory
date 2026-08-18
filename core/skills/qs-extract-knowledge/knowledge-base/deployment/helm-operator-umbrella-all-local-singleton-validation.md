---
name: helm-operator-umbrella-all-local-singleton-validation
description: Helm Operator consuming umbrella chart of all-local file:// subcharts with CRD singleton and namespace validation
summary: "Wraps a multi-component umbrella Helm chart (aiobs-stack) in a Helm Operator (operator-framework v1.37.0 via watches.yaml CRD-to-chart mapping) to manage 10 local file:// subcharts plus one nested subchart (rag) with remote ai-architecture-charts deps (llm-service, llama-stack, pgvector) under operator reconciliation lifecycle. Use when deploying complex stacks requiring operator lifecycle with singleton CRD enforcement and fixed-namespace validation -- infrastructure subcharts (minio, tempo, loki, otel-collector, korrel8r) always install to fixed namespaces while application subcharts are condition-toggled, with cross-namespace RBAC handled by Helm hook Jobs. Template _helpers.tpl uses fail with lookup on the CRD type to enforce singleton and ne .Release.Namespace \"ai-observability\" for namespace validation; local deps use version \">=0.0.0\" with repository \"file://../<chart>\" and the operator Dockerfile copies all charts from quay.io/operator-framework/helm-operator:v1.37.0 base. The lookup function is unreliable during Helm Operator reconciliation (use hook Jobs for namespace creation instead), file:// paths require the Dockerfile to COPY all subchart directories intact (use tar to resolve symlinks), and infrastructure vs application subcharts split across fixed namespaces vs CR namespace requires cross-namespace RBAC hook Jobs."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python, react, typescript]
  ai_pattern: [rag, agents]
  platform: [openshift, rhoai, vllm, kserve]
  data_layer: [pgvector, minio]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "Helm Operator (v1.37.0) consuming aiobs-stack umbrella with 10 local file:// subcharts + 1 RAG subchart containing remote ai-architecture-charts deps, singleton + namespace CRD validation"
    approach: "A"
---

# Helm Operator Umbrella with All-Local Subcharts and Singleton CRD Validation

## Overview

This pattern uses a Helm Operator (operator-framework) to manage an umbrella Helm chart where all dependencies are local file:// references to sibling chart directories. The umbrella chart includes CRD-level validation enforcing singleton deployment and a fixed namespace, plus a chain of Helm hook Jobs for cross-namespace infrastructure setup. This combines the simplicity of local-only chart management with the operational benefits of Kubernetes Operator lifecycle.

## Pattern Description

The `aiobs-stack` umbrella chart declares 10 dependencies all using `repository: "file://../<chart>"` to reference sibling directories. One dependency (`rag`) itself contains remote ai-architecture-charts dependencies (llm-service, llama-stack, pgvector). The umbrella is consumed by a Helm Operator via `watches.yaml`, mapping a custom CRD (`AIObservabilitySummarizer`) to the chart. Template-level validation helpers use `fail` to enforce singleton instances and a fixed namespace.

## Implementation

### Umbrella Chart with All-Local Dependencies

```yaml
# deploy/helm/aiobs-stack/Chart.yaml
dependencies:
  # Infrastructure (deployed to fixed namespaces, no conditions)
  - name: minio-observability-storage
    version: ">=0.0.0"
    repository: "file://../minio"
    alias: minio
  - name: tempo-stack
    version: ">=0.0.0"
    repository: "file://../observability/tempo"
    alias: tempo
  - name: loki-stack
    version: ">=0.0.0"
    repository: "file://../observability/loki"
    alias: loki
  - name: otel-collector
    version: ">=0.0.0"
    repository: "file://../observability/otel-collector"
    alias: otelCollector
  - name: korrel8r
    version: ">=0.0.0"
    repository: "file://../observability/korrel8r"
  # Application (deployed in CR namespace, with conditions)
  - name: mcp-server
    version: ">=0.0.0"
    repository: "file://../mcp-server"
    condition: mcpServer.enabled
    alias: mcpServer
  - name: openshift-console-plugin
    version: ">=0.0.0"
    repository: "file://../openshift-console-plugin"
    condition: consolePlugin.enabled
    alias: consolePlugin
  - name: rag
    version: ">=0.0.0"
    repository: "file://../rag"
    condition: rag.enabled
```

### Helm Operator watches.yaml

```yaml
# deploy/operator/watches.yaml
- group: aiobs.rh-ai-quickstart.io
  version: v1alpha1
  kind: AIObservabilitySummarizer
  chart: helm-charts/aiobs-stack
```

### Operator Dockerfile

```dockerfile
# deploy/operator/Dockerfile
FROM quay.io/operator-framework/helm-operator:v1.37.0
ENV HOME=/opt/helm
COPY watches.yaml ${HOME}/watches.yaml
COPY helm-charts ${HOME}/helm-charts
WORKDIR ${HOME}
```

### Singleton and Namespace Validation

The `_helpers.tpl` enforces that only one CR exists cluster-wide and that it is created in the `ai-observability` namespace:

```yaml
# deploy/helm/aiobs-stack/templates/_helpers.tpl
{{- define "aiobs-stack.validateNamespace" -}}
{{- $allowedNamespace := "ai-observability" }}
{{- if ne .Release.Namespace $allowedNamespace }}
  {{- fail (printf "\n\nERROR: AIObservabilitySummarizer must be created in the '%s' namespace.\nCurrent namespace: '%s'\n" $allowedNamespace .Release.Namespace $allowedNamespace) }}
{{- end }}
{{- end }}

{{- define "aiobs-stack.validateSingleton" -}}
{{- $existingCRs := (lookup "aiobs.rh-ai-quickstart.io/v1alpha1" "AIObservabilitySummarizer" "" "").items }}
{{- if $existingCRs }}
  {{- range $existingCRs }}
    {{- if or (ne .metadata.name $.Release.Name) (ne .metadata.namespace $.Release.Namespace) }}
      {{- fail (printf "\n\nERROR: Only one AIObservabilitySummarizer is allowed per cluster.\nAn instance '%s' already exists in namespace '%s'.\n" .metadata.name .metadata.namespace) }}
    {{- end }}
  {{- end }}
{{- end }}
{{- end }}
```

### RAG Subchart with Remote ai-architecture-charts

The `rag` local subchart itself declares remote dependencies:

```yaml
# deploy/helm/rag/Chart.yaml
dependencies:
  - name: llm-service
    version: 0.5.9
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: llama-stack
    version: 0.8.6
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
    condition: llama-stack.enabled
  - name: pgvector
    version: 0.5.5
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
```

## Configuration

- **Key settings:** `version: ">=0.0.0"` on local deps lets the umbrella always use whatever version the local chart declares; `condition` fields on application subcharts enable toggling via the CR spec
- **Defaults:** Infrastructure subcharts (minio, tempo, loki, otel-collector, korrel8r) have no `condition` field -- they always install. Application subcharts (mcpServer, consolePlugin, alerting) have condition toggles.
- **Dependencies:** The Helm Operator base image (`quay.io/operator-framework/helm-operator:v1.37.0`) provides the reconciliation loop; the umbrella chart is copied into the operator image at build time

## Gotchas

- The `lookup` function used in `validateSingleton` does not work reliably in Helm Operator reconciliation (noted in code comments for `namespace-hook-job.yaml`), which is why namespace creation uses a pre-install hook Job instead of `lookup`-based conditional templates
- The `file://..` repository paths require the operator's Dockerfile to `COPY helm-charts` with all subchart directories intact -- the comment in the Dockerfile notes "use tar to resolve symlinks"
- Infrastructure subcharts target fixed namespaces (observability-hub, openshift-logging, openshift-cluster-observability-operator) while application subcharts deploy into the CR's namespace, requiring cross-namespace RBAC hook Jobs

## Related Patterns

- `helm-umbrella-mixed-remote-local-committed-deps.md` -- umbrella charts with mixed remote and local deps (without operator wrapper)
- `helm-hook-chain-weighted-namespace-uwm-rbac-instrumentation.md` -- the hook job chain used within this umbrella
