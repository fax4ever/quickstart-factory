---
name: grafana-operator
description: OLM-based Grafana Operator install via Helm for dashboard and datasource management on OpenShift
summary: "Grafana Operator provides Kubernetes-native Grafana instance, dashboard, and datasource management on OpenShift, installed as a Phase 1 OLM prerequisite via Helm chart creating Namespace (openshift.io/cluster-monitoring label for Prometheus scraping), cluster-wide OperatorGroup, and Subscription (v5 channel, community-operators catalog, Automatic installPlanApproval) -- shares this OLM pattern with cluster-observability-operator, otel-operator, and tempo-operator. Use when building observability stacks where Phase 2 charts (helm/02-observability/grafana/) provision pre-built dashboards (vLLM metrics, cluster metrics) and datasources (Prometheus, Tempo); only one approach exists (OLM Subscription via Helm). The install script (scripts/install-operators.sh) runs parallel background helm installs for all 01-operators charts, waits with `oc wait --for=condition=Ready` on label control-plane=controller-manager, then sleeps 30 seconds for CRD registration. Critical gotchas: values.yaml defaults namespace to openshift-grafana-operator but install script readiness check targets grafana-operator causing namespace mismatch; Phase 2 deploys fail with unknown resource type errors if CRDs are not yet registered."
metadata:
  type: component
tags:
  tech_stack: [helm, grafana, olm]
  ai_pattern: []
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "OLM Subscription-based install of Grafana Operator v5 for AI workload dashboards and datasource management"
    approach: "A"
---

# Grafana Operator

## Overview

The Grafana Operator provides Kubernetes-native management of Grafana instances, dashboards, and datasources on OpenShift. In AI Quickstart observability stacks it is deployed as a Phase 1 operator prerequisite so that Phase 2 can provision Grafana instances with pre-built dashboards (e.g., vLLM metrics, cluster metrics) and datasources (Prometheus, Tempo). The operator is installed via OLM using a Helm chart that creates the Namespace, OperatorGroup, and Subscription resources.

## Tech Stack & Dependencies

- **Runtime:** Grafana Operator v5.x (community-operators catalog)
- **Container image:** Managed by OLM -- pulled from the community-operators catalog source
- **Key dependencies:** OLM (Operator Lifecycle Manager), OpenShift Marketplace (`openshift-marketplace` namespace)
- **Helm subchart:** Standalone chart at `helm/01-operators/grafana-operator/`

## Key Patterns

### OLM Subscription via Helm

The chart does not deploy the operator pod directly. Instead it creates three OLM resources and lets the Operator Lifecycle Manager handle the actual deployment.

```yaml
# templates/subscription.yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ include "grafana-operator.subscriptionName" . }}
  namespace: {{ include "grafana-operator.namespace" . }}
spec:
  channel: {{ .Values.subscription.channel }}
  installPlanApproval: {{ .Values.subscription.installPlanApproval }}
  name: {{ .Values.subscription.packageName }}
  source: {{ .Values.subscription.source }}
  sourceNamespace: {{ .Values.subscription.sourceNamespace }}
```

The three resources created are: Namespace, OperatorGroup, and Subscription. The OperatorGroup defaults to cluster-wide scope (empty `targetNamespaces`).

### Cluster-Wide Operator Scope

The OperatorGroup is configured with no target namespaces, giving the operator cluster-wide reach. This allows a single Grafana Operator to manage Grafana instances in any namespace (e.g., `observability-hub`).

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

The operator namespace is labeled with `openshift.io/cluster-monitoring: 'true'`, which enables Prometheus scraping of metrics from the operator namespace by the OpenShift built-in monitoring stack.

```yaml
# values.yaml (namespace section)
namespace:
  name: openshift-grafana-operator
  create: true
  labels:
    openshift.io/cluster-monitoring: 'true'
```

### Parallel Operator Installation

The install script (`scripts/install-operators.sh`) installs all Phase 1 operators in parallel using background helm processes, then waits for readiness:

```bash
# scripts/install-operators.sh
for chart_dir in "$HELM_DIR/01-operators"/*; do
    if [ -d "$chart_dir" ] && [ -f "$chart_dir/Chart.yaml" ]; then
        chart_name=$(basename "$chart_dir")
        if release_exists "$chart_name"; then
            print_status "$chart_name already installed, skipping..."
            continue
        fi
        helm install "$chart_name" "$chart_dir" &
        pids+=($!)
    fi
done
```

### Operator Readiness Wait

After installing, the script waits for the Grafana Operator pod using the `control-plane=controller-manager` label selector:

```bash
# scripts/install-operators.sh
oc wait --for=condition=Ready pod -l control-plane=controller-manager \
    -n grafana-operator --timeout=300s || print_status "Grafana operator timeout"
```

## Configuration

- **Environment variables:** None at the operator install level -- the operator itself manages its own config
- **Config files:** `values.yaml` controls namespace, subscription channel, catalog source, and operator scope
- **Helm values:**

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `namespace.name` | `openshift-grafana-operator` | Namespace for operator resources |
| `namespace.create` | `true` | Whether to create the namespace |
| `subscription.channel` | `v5` | OLM subscription channel |
| `subscription.source` | `community-operators` | OLM catalog source |
| `subscription.installPlanApproval` | `Automatic` | Auto-approve operator updates |
| `operatorGroup.targetNamespaces` | `[]` | Empty for cluster-wide scope |

## Known Gotchas

- **Namespace mismatch between values.yaml and install script:** The `values.yaml` sets namespace to `openshift-grafana-operator`, but `scripts/install-operators.sh` waits for the operator pod in the `grafana-operator` namespace (line 70 and 116). This discrepancy means the readiness check may target the wrong namespace if the chart's default namespace value is used as-is.
- **CRD availability lag:** The install script adds a 30-second sleep after operator pods are ready before checking CRDs (`sleep 30` on line 123 of `scripts/install-operators.sh`). Grafana CRDs may not be immediately available after the operator pod reports Ready.
- **Phase dependency:** The Grafana instance chart (`helm/02-observability/grafana/`) depends on the operator being fully ready with CRDs registered. Deploying Phase 2 before Phase 1 operators are ready will fail with unknown resource type errors.

## Testing Notes

- Verify the operator pod is running: `oc get pods -n openshift-grafana-operator` (or `grafana-operator` depending on actual namespace)
- Check subscription status: `oc get subscription -n openshift-grafana-operator`
- Check CSV is installed: `oc get csv -n openshift-grafana-operator`
- Verify CRDs exist: `oc get crd | grep grafana`

## Related Patterns

- Grafana instance and dashboard configuration (deployed in Phase 2 at `helm/02-observability/grafana/`)
- OLM operator installation pattern shared with `cluster-observability-operator`, `otel-operator`, and `tempo-operator`
