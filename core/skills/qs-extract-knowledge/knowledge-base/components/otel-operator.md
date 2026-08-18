---
name: otel-operator
description: "Helm chart deploying the Red Hat OpenTelemetry Operator via OLM on OpenShift for telemetry collection"
summary: "Installs the Red Hat OpenTelemetry Operator on OpenShift via OLM using a Helm chart (at helm/01-operators/otel-operator/) that deploys a Namespace, OperatorGroup with AllNamespaces scope (empty targetNamespaces), and Subscription to the opentelemetry-product package from the redhat-operators CatalogSource. Use as a Phase 1 operator prerequisite in observability stacks -- otel-collector depends on this operator's CRDs for OpenTelemetryCollector instances; deployed in parallel alongside tempo-operator, grafana-operator, and cluster-observability-operator before Phase 2 infrastructure and Phase 3 AI services, requires cluster-admin privileges. Critical config: namespace.name (default openshift-opentelemetry-operator) with openshift.io/cluster-monitoring: \"true\" label for Prometheus scraping, subscription.channel (default stable), subscription.installPlanApproval (Automatic/Manual), and subscription.startingCSV to pin a specific CSV version (empty default installs latest). Parallel operator installs require a 30-second post-Helm sleep for OLM reconciliation plus a CRD polling loop (12 retries at 5s for uiplugins.observability.openshift.io) before Phase 2 proceeds; readiness verified via oc wait with label app.kubernetes.io/name=opentelemetry-operator."
metadata:
  type: component
tags:
  tech_stack: [helm, openshift, olm]
  ai_pattern: []
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "OLM-based operator install for OpenTelemetry in a Llama Stack observability stack"
    approach: "A"
---

# OpenTelemetry Operator

## Overview

The OpenTelemetry Operator Helm chart installs the Red Hat build of the OpenTelemetry Operator on OpenShift via OLM (Operator Lifecycle Manager). It provides Kubernetes-native management of OpenTelemetry Collector instances and auto-instrumentation. In the lls-observability quickstart, it is deployed as a Phase 1 (operators) prerequisite before the observability infrastructure (otel-collector, Tempo, Grafana) and AI services.

## Tech Stack & Dependencies
- **Runtime:** Helm chart (no application code -- deploys OLM resources)
- **Container image:** Managed by OLM Subscription (Red Hat `opentelemetry-product` from `redhat-operators` catalog)
- **Key dependencies:** OpenShift 4.x with OLM, cluster-admin privileges, `redhat-operators` CatalogSource
- **Helm subchart:** Standalone chart at `helm/01-operators/otel-operator/`, Chart version 1.0.0, appVersion 0.93.0-3

## Key Patterns

### OLM Subscription via Helm

The chart deploys three OLM resources via Helm templates: a dedicated Namespace, an OperatorGroup, and a Subscription. This pattern allows operator lifecycle management to be fully declarative and versioned alongside application charts.

```yaml
# templates/subscription.yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ include "otel-operator.subscriptionName" . }}
  namespace: {{ include "otel-operator.namespace" . }}
spec:
  channel: {{ .Values.subscription.channel }}
  installPlanApproval: {{ .Values.subscription.installPlanApproval }}
  name: {{ .Values.subscription.packageName }}
  source: {{ .Values.subscription.source }}
  sourceNamespace: {{ .Values.subscription.sourceNamespace }}
```

### Cluster-Wide OperatorGroup Scope

The OperatorGroup uses an empty `targetNamespaces` array to achieve AllNamespaces install mode. This allows the operator to deploy OpenTelemetry Collectors and apply auto-instrumentation across all namespaces on the cluster.

```yaml
# templates/operatorgroup.yaml
spec:
  upgradeStrategy: Default
  {{- if .Values.operatorGroup.targetNamespaces }}
  targetNamespaces:
    {{- toYaml .Values.operatorGroup.targetNamespaces | nindent 4 }}
  {{- end }}
```

### Namespace with Cluster Monitoring Label

The operator namespace is created with the `openshift.io/cluster-monitoring: 'true'` label, which enables OpenShift's built-in Prometheus to scrape metrics from pods in this namespace.

```yaml
# values.yaml
namespace:
  name: openshift-opentelemetry-operator
  create: true
  labels:
    openshift.io/cluster-monitoring: 'true'
```

### Parallel Operator Installation

The `install-operators.sh` script installs all five operators (including otel-operator) in parallel using background Helm installs, then waits for all pods to be ready. The otel-operator readiness check uses a specific pod label selector.

```bash
# scripts/install-operators.sh
oc wait --for=condition=Ready pod \
  -l app.kubernetes.io/name=opentelemetry-operator \
  -n openshift-opentelemetry-operator --timeout=300s
```

## Configuration
- **Environment variables:** None (OLM-managed operator)
- **Config files:** `values.yaml` controls namespace, subscription channel, source catalog, and OperatorGroup scope
- **Helm values:**
  - `namespace.name` -- Operator namespace (default: `openshift-opentelemetry-operator`)
  - `namespace.create` -- Whether to create the namespace (default: `true`)
  - `subscription.channel` -- OLM channel (default: `stable`)
  - `subscription.packageName` -- OLM package (default: `opentelemetry-product`)
  - `subscription.source` -- CatalogSource (default: `redhat-operators`)
  - `subscription.installPlanApproval` -- `Automatic` or `Manual` (default: `Automatic`)
  - `subscription.startingCSV` -- Pin to a specific CSV version (default: empty for latest)
  - `operatorGroup.targetNamespaces` -- Scope; empty array means AllNamespaces

## Known Gotchas
- The install script adds a 30-second sleep after parallel Helm installs before checking operator readiness, indicating operators need time to reconcile OLM resources before CRDs become available (`scripts/install-operators.sh`).
- After the operator pods are ready, a second 30-second sleep and a CRD polling loop (up to 12 retries at 5-second intervals) wait for the `uiplugins.observability.openshift.io` CRD. While this CRD belongs to the cluster-observability-operator, the shared wait script means all operators must be ready before Phase 2 proceeds.
- The `startingCSV` field is empty by default, which means OLM installs the latest available CSV. To pin to a specific version for reproducibility, set `subscription.startingCSV` to the desired CSV name.

## Testing Notes
- Verify the operator pod is running: `oc get pods -n openshift-opentelemetry-operator`
- Check subscription status: `oc get subscription -n openshift-opentelemetry-operator`
- Confirm CRDs are registered: `oc get crd | grep opentelemetry`
- Confirm the CSV is successfully installed: `oc get csv -n openshift-opentelemetry-operator`
- Use `helm lint` and `helm template --dry-run` against the chart directory for pre-deploy validation

## Related Patterns
- The otel-collector component (`helm/02-observability/otel-collector/`) depends on this operator being installed first and uses its CRDs to create OpenTelemetryCollector instances
- Deployed alongside tempo-operator, grafana-operator, and cluster-observability-operator as Phase 1 operators
- Part of a three-phase deployment: operators (Phase 1), observability infrastructure (Phase 2), AI services (Phase 3)
