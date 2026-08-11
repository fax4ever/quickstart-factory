---
name: observability-olm-operator-helm-install
description: Individual Helm charts wrapping OLM Subscription and OperatorGroup for OpenShift operator installation
summary: "Solves declarative, reproducible installation of four OpenShift observability operators (OpenTelemetry, Grafana, Tempo, Cluster Observability) by wrapping OLM Namespace, OperatorGroup, and Subscription resources in individual Helm charts with independent lifecycle management. Use when operators must be installed via `helm install` with configurable channels, catalog sources, and approval modes rather than manual `oc apply` or console-based Subscription creation -- single approach using a three-template-per-chart structure (namespace, operatorgroup, subscription). Critical config: `subscription.channel` (stable for most, v5 for Grafana), `subscription.source` (redhat-operators vs community-operators), `installPlanApproval: Automatic`, namespace label `openshift.io/cluster-monitoring: 'true'` for metrics scraping, and empty `targetNamespaces: []` for AllNamespaces install mode required by Tempo. Gotchas: Grafana Operator uses `community-operators` catalog (not `redhat-operators`) affecting support posture and update cadence; operator charts install only the operator itself -- instances like TempoStack require a separate chart; OLM and catalog sources in `openshift-marketplace` must already be present."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, opentelemetry, grafana]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "4 operators (OTel, Grafana, Tempo, Cluster Observability) installed via separate Helm charts with OLM Subscriptions"
    approach: "A"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "Same 4 OLM operators (OTel, Grafana, Tempo, Cluster Observability) with identical Namespace+OperatorGroup+Subscription structure, installed in parallel via bash script"
    approach: "A"
---

# Observability OLM Operator Installation via Helm Charts

## Overview

This pattern installs OpenShift operators through Helm charts that template OLM (Operator Lifecycle Manager) resources: Namespace, OperatorGroup, and Subscription. Each operator gets its own dedicated Helm chart, enabling independent lifecycle management while keeping operator installation declarative and reproducible.

## Pattern Description

Rather than manually creating OLM Subscriptions via the OpenShift console or `oc apply`, each operator is wrapped in a small Helm chart that templates the Namespace, OperatorGroup, and Subscription resources. This approach enables operators to be installed as part of a `helm install` workflow with configurable channels, sources, and approval modes. Four operators follow this pattern: OpenTelemetry, Grafana, Tempo, and Cluster Observability.

## Implementation

### Common Chart Structure

Each operator chart follows the same three-template structure. Example for the OpenTelemetry Operator:

```yaml
# charts/observability/helm/otel-operator/templates/namespace.yaml (pattern)
apiVersion: v1
kind: Namespace
metadata:
  name: {{ .Values.namespace.name }}
  annotations:
    {{- toYaml .Values.namespace.annotations | nindent 4 }}
  labels:
    {{- toYaml .Values.namespace.labels | nindent 4 }}
```

```yaml
# charts/observability/helm/otel-operator/templates/operatorgroup.yaml (pattern)
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: {{ .Values.operatorGroup.name }}
  namespace: {{ .Values.namespace.name }}
spec:
  targetNamespaces: {{ .Values.operatorGroup.targetNamespaces | toYaml | nindent 4 }}
```

```yaml
# charts/observability/helm/otel-operator/templates/subscription.yaml (pattern)
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ .Values.subscription.name }}
  namespace: {{ .Values.namespace.name }}
spec:
  channel: {{ .Values.subscription.channel }}
  installPlanApproval: {{ .Values.subscription.installPlanApproval }}
  name: {{ .Values.subscription.packageName }}
  source: {{ .Values.subscription.source }}
  sourceNamespace: {{ .Values.subscription.sourceNamespace }}
```

### Values per Operator

Each operator has its own namespace, channel, and catalog source:

```yaml
# charts/observability/helm/otel-operator/values.yaml
namespace:
  name: openshift-opentelemetry-operator
  labels:
    openshift.io/cluster-monitoring: 'true'
subscription:
  name: opentelemetry-product
  packageName: opentelemetry-product
  channel: stable
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

```yaml
# charts/observability/helm/grafana-operator/values.yaml
namespace:
  name: openshift-grafana-operator
subscription:
  name: grafana
  packageName: grafana-operator
  channel: v5
  source: community-operators     # Note: community, not redhat-operators
```

### All Four Operator Charts

| Chart | Namespace | Source | Channel |
|-------|-----------|--------|---------|
| `otel-operator` | `openshift-opentelemetry-operator` | `redhat-operators` | `stable` |
| `grafana-operator` | `openshift-grafana-operator` | `community-operators` | `v5` |
| `tempo-operator` | `openshift-tempo-operator` | `redhat-operators` | `stable` |
| `cluster-observability-operator` | `openshift-cluster-observability-operator` | `redhat-operators` | `stable` |

## Configuration

- **Key settings:** `subscription.channel` determines the operator version stream; `subscription.source` selects the catalog (redhat-operators vs community-operators); `installPlanApproval: Automatic` enables auto-upgrades
- **Defaults:** All operators default to `Automatic` install plan approval and empty `targetNamespaces` (cluster-wide scope)
- **Dependencies:** OLM must be available (standard on OpenShift); catalog sources (`redhat-operators`, `community-operators`) must be present in `openshift-marketplace`

## Gotchas

- Grafana Operator comes from `community-operators` while all other operators come from `redhat-operators`; this affects support posture and update cadence
- The `openshift.io/cluster-monitoring: 'true'` label on operator namespaces enables cluster monitoring to scrape metrics from the operator pods
- The Tempo Operator chart's values.yaml comments note that TempoStack instances should be created separately using the `tempo` chart -- the operator chart only installs the operator itself
- Empty `targetNamespaces: []` in OperatorGroup means cluster-wide scope (AllNamespaces install mode); the Tempo operator specifically requires this since it does not support OwnNamespace mode

## Related Patterns

- `otel-sidecar-inject-vllm-model-metrics.md` -- the OTel Collector sidecars that depend on the OTel Operator installed by this pattern
- `helm-uwm-podmonitor-vllm.md` -- the UWM configuration that works alongside these observability operators
