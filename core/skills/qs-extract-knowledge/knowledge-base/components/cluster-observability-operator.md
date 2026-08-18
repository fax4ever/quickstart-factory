---
name: cluster-observability-operator
description: "OpenShift Cluster Observability Operator providing PodMonitor/ServiceMonitor CRDs and UI plugins via OLM"
summary: "Provides PodMonitor/ServiceMonitor CRDs and console UI plugins as a Phase 1 foundation for OpenShift observability stacks, deployed via standalone Helm chart (helm/01-operators/cluster-observability-operator/) creating OLM Namespace, OperatorGroup, and Subscription from the redhat-operators CatalogSource. Use as the first operator installed in any observability architecture -- must precede Phase 2 components (Tempo, OpenTelemetry, Grafana, UWM); single approach via OLM Subscription Helm chart with channel=stable and installPlanApproval=Automatic defaults. Critical config: dedicated namespace openshift-cluster-observability-operator with openshift.io/cluster-monitoring: 'true' label, all-namespaces OperatorGroup via empty targetNamespaces array, Subscription pinned via startingCSV to cluster-observability-operator.v1.2.0 and tracked by operators.coreos.com label. Two separate pod readiness checks required post-install (app.kubernetes.io/name=cluster-observability-operator and app.kubernetes.io/name=observability-operator); startingCSV must be updated or cleared for version upgrades; Phase 2 component READMEs explicitly list this operator as a helm install prerequisite."
metadata:
  type: component
tags:
  tech_stack: [helm, openshift]
  ai_pattern: []
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "OLM-based operator install via Helm chart for observability CRDs and UI plugins"
    approach: "A"
---

# Cluster Observability Operator

## Overview

The Cluster Observability Operator is an OpenShift operator that provides PodMonitor and ServiceMonitor CRDs along with console UI plugins for observability. In AI Quickstart architectures it serves as a Phase 1 foundation dependency, installed before any observability infrastructure (Tempo, OpenTelemetry, Grafana) or AI workloads. It is deployed via OLM Subscription managed by a standalone Helm chart.

## Tech Stack & Dependencies

- **Runtime:** OpenShift OLM-managed operator (appVersion 1.2.0)
- **Container image:** Managed by OLM from `redhat-operators` catalog
- **Key dependencies:** OpenShift OLM, `redhat-operators` CatalogSource in `openshift-marketplace`
- **Helm subchart:** Standalone chart (`helm/01-operators/cluster-observability-operator/`), not a subchart of ai-architecture-charts

## Key Patterns

### OLM Subscription via Helm

The operator is installed through a Helm chart that creates three OLM resources: a dedicated Namespace, an OperatorGroup, and a Subscription. This pattern enables declarative, repeatable operator installation without manual OperatorHub clicks.

```yaml
# templates/subscription.yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ include "cluster-observability-operator.subscriptionName" . }}
  namespace: {{ include "cluster-observability-operator.namespace" . }}
spec:
  channel: {{ .Values.subscription.channel }}
  installPlanApproval: {{ .Values.subscription.installPlanApproval }}
  name: {{ .Values.subscription.packageName }}
  source: {{ .Values.subscription.source }}
  sourceNamespace: {{ .Values.subscription.sourceNamespace }}
```

### Dedicated Namespace with Cluster Monitoring Label

The operator runs in its own namespace (`openshift-cluster-observability-operator`) with the `openshift.io/cluster-monitoring: 'true'` label, which enables Prometheus to scrape the operator's own metrics.

```yaml
# values.yaml — namespace section
namespace:
  name: openshift-cluster-observability-operator
  create: true
  labels:
    openshift.io/cluster-monitoring: 'true'
```

### All-Namespaces OperatorGroup

The OperatorGroup is configured with empty `targetNamespaces`, giving the operator cluster-wide scope to watch for PodMonitor/ServiceMonitor resources across all namespaces.

```yaml
# templates/operatorgroup.yaml
spec:
  upgradeStrategy: Default
  {{- if .Values.operatorGroup.targetNamespaces }}
  targetNamespaces:
    {{- toYaml .Values.operatorGroup.targetNamespaces | nindent 4 }}
  {{- end }}
```

### Subscription Metadata Label for OLM Tracking

The Subscription carries a specific label (`operators.coreos.com/cluster-observability-operator.openshift-cluster-observability`) used by OLM to track operator ownership, configured via `metadataLabels.subscription` in values.

```yaml
# values.yaml — metadataLabels section
metadataLabels:
  subscription:
    operators.coreos.com/cluster-observability-operator.openshift-cluster-observability: ''
```

## Configuration

- **Environment variables:** None at the chart level; operator configuration is managed by OLM post-install
- **Config files:** `values.yaml` controls namespace name, subscription channel, install plan approval, and starting CSV
- **Helm values:**
  - `namespace.name` -- target namespace (default: `openshift-cluster-observability-operator`)
  - `namespace.create` -- whether to create the namespace (default: `true`)
  - `subscription.channel` -- OLM channel (default: `stable`)
  - `subscription.source` -- catalog source (default: `redhat-operators`)
  - `subscription.installPlanApproval` -- approval mode (default: `Automatic`)
  - `subscription.startingCSV` -- pin to specific version (default: `cluster-observability-operator.v1.2.0`)
  - `operatorGroup.targetNamespaces` -- scope; empty array for all-namespaces watch

## Known Gotchas

- **Two pod readiness checks required:** The README shows two separate `oc wait` commands after install -- one for `app.kubernetes.io/name=cluster-observability-operator` and another for `app.kubernetes.io/name=observability-operator`. Both pods must be ready before Phase 2 components (Tempo, OTel Collector, Grafana, UWM) can be deployed.
- **startingCSV pins the version:** The default `startingCSV: "cluster-observability-operator.v1.2.0"` pins to a specific operator version. When upgrading, this value must be updated or cleared to allow OLM to pick the latest CSV from the channel.
- **Phase ordering matters:** This operator must be installed in Phase 1 before Phase 2 observability infrastructure. The UWM README explicitly lists it as a prerequisite (`helm install cluster-observability-operator ../cluster-observability-operator`).

## Testing Notes

- After `helm install`, verify both operator pods are running in the dedicated namespace:
  ```
  oc wait --for=condition=Ready pod -l app.kubernetes.io/name=cluster-observability-operator -n openshift-cluster-observability-operator --timeout=300s
  oc wait --for=condition=Ready pod -l app.kubernetes.io/name=observability-operator -n openshift-cluster-observability-operator --timeout=300s
  ```
- Confirm the operator appears in the Makefile validation output:
  ```
  oc get pods -n openshift-operators | grep cluster-observability
  ```

## Related Patterns

- `observability-stack.md` -- overall observability architecture this operator enables
- `tracing-config.md` -- distributed tracing configuration that depends on this operator's CRDs
