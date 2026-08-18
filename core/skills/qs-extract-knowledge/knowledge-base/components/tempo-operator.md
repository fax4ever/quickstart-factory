---
name: tempo-operator
description: "Tempo Operator OLM installation via Helm with cluster-wide OperatorGroup on OpenShift"
summary: "Installs the Grafana Tempo Operator on OpenShift via OLM as a standalone Helm chart (helm/01-operators/tempo-operator/) that creates namespace, OperatorGroup, and Subscription but explicitly no TempoStack instances -- part of a two-phase operator-then-instance pattern where instances are deployed separately via helm/02-observability/tempo/. Use this operator-only chart when deploying the observability stack alongside peer operator charts (OTEL, Cluster Observability, Grafana); converted from Kustomize to Helm and configured via values keys operator.subscription.* (tempo-product package, stable channel, redhat-operators catalog, Automatic approval), operator.operatorGroup.*, and namespace.*. Critical config: OperatorGroup must use cluster-wide AllNamespaces scope via `targetNamespaces: []` with `upgradeStrategy: Default` (Tempo Operator does not support OwnNamespace mode), and namespace `openshift-tempo-operator` requires label `openshift.io/cluster-monitoring: 'true'` for Prometheus scraping. Gotchas: setting targetNamespaces to anything other than [] causes operator failure; uninstall does not remove CRDs requiring manual deletion of Subscription and OperatorGroup; the tempostack.yaml placeholder template is kept to avoid breaking existing deployments that reference it but creates no resources."
metadata:
  type: component
tags:
  tech_stack: [tempo, helm, openshift]
  ai_pattern: [observability, tracing]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Operator-only Helm chart installing Tempo via OLM Subscription with cluster-wide scope"
    approach: "A"
---

# Tempo Operator

## Overview

The Tempo Operator component installs the Grafana Tempo Operator on OpenShift via OLM (Operator Lifecycle Manager). It is deployed as an operator-only Helm chart that creates the namespace, OperatorGroup, and Subscription -- but explicitly does not create TempoStack instances. Those are handled by a separate chart (`helm/02-observability/tempo/`), enforcing a two-phase operator-then-instance deployment pattern used across the observability stack in this quickstart.

## Tech Stack & Dependencies

- **Runtime:** Tempo Operator (managed by OLM)
- **Container image:** Operator image pulled automatically by OLM from the `redhat-operators` catalog
- **Key dependencies:** OpenShift OLM, `redhat-operators` CatalogSource in `openshift-marketplace`
- **Helm subchart:** Standalone chart at `helm/01-operators/tempo-operator/` (not a subchart of another chart)

## Key Patterns

### Operator-Only Chart (No CR Instances)

The chart installs only the operator itself. The `tempostack.yaml` template is a deliberate placeholder containing no resources. The `_helpers.tpl` includes a removed comment for the TempoStack name helper.

From `helm/01-operators/tempo-operator/templates/tempostack.yaml`:

```yaml
# TempoStack instances are no longer created by this chart
# Use the separate tempo kustomize configuration to create TempoStack instances
# This file is kept as a placeholder to avoid breaking existing deployments
# that might reference it. It can be safely deleted if not referenced.
```

From `helm/01-operators/tempo-operator/templates/_helpers.tpl`:

```yaml
{{/*
Create the name of the tempo stack - REMOVED
TempoStack instances are no longer created by this chart
*/}}
```

### Cluster-Wide OperatorGroup Scope

The Tempo Operator does not support OwnNamespace install mode. The OperatorGroup must use an empty `targetNamespaces` array to enable AllNamespaces scope. The `upgradeStrategy: Default` is explicitly set.

From `helm/01-operators/tempo-operator/templates/operatorgroup.yaml`:

```yaml
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: {{ include "tempo-operator.operatorGroupName" . }}
  namespace: {{ include "tempo-operator.namespace" . }}
spec:
  upgradeStrategy: Default
  {{- if .Values.operator.operatorGroup.targetNamespaces }}
  targetNamespaces:
    {{- toYaml .Values.operator.operatorGroup.targetNamespaces | nindent 4 }}
  {{- end }}
```

The values.yaml documents why this is necessary:

```yaml
operatorGroup:
  name: openshift-tempo-operator
  # Target namespaces for the operator group
  # Empty array [] enables cluster-wide scope (AllNamespaces install mode)
  # This is required for Tempo operator as it doesn't support OwnNamespace mode
  targetNamespaces: []
```

### OLM Subscription via Red Hat Catalog

The operator is installed from the `redhat-operators` catalog using the `tempo-product` package on the `stable` channel with automatic install plan approval.

From `helm/01-operators/tempo-operator/templates/subscription.yaml`:

```yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ include "tempo-operator.subscriptionName" . }}
  namespace: {{ include "tempo-operator.namespace" . }}
spec:
  channel: {{ .Values.operator.subscription.channel }}
  installPlanApproval: {{ .Values.operator.subscription.installPlanApproval }}
  name: {{ .Values.operator.subscription.name }}
  source: {{ .Values.operator.subscription.source }}
  sourceNamespace: {{ .Values.operator.subscription.sourceNamespace }}
```

### Namespace with Cluster Monitoring Label

The operator namespace is created with the `openshift.io/cluster-monitoring: 'true'` label, which enables Prometheus scraping of the operator's metrics by the in-cluster monitoring stack.

From `helm/01-operators/tempo-operator/values.yaml`:

```yaml
namespace:
  create: true
  name: openshift-tempo-operator
  annotations:
    openshift.io/display-name: "Tempo Operator"
  labels:
    openshift.io/cluster-monitoring: 'true'
```

## Configuration

- **Environment variables:** None directly; the operator container is fully managed by OLM
- **Config files:** No additional config files; all configuration is via Helm values
- **Helm values:**
  - `operator.namespace` -- namespace for the operator (default: `openshift-tempo-operator`)
  - `operator.subscription.name` -- OLM package name (default: `tempo-product`)
  - `operator.subscription.channel` -- subscription channel (default: `stable`)
  - `operator.subscription.installPlanApproval` -- approval mode (default: `Automatic`)
  - `operator.subscription.source` -- catalog source (default: `redhat-operators`)
  - `operator.subscription.sourceNamespace` -- catalog namespace (default: `openshift-marketplace`)
  - `operator.operatorGroup.name` -- OperatorGroup name (default: `openshift-tempo-operator`)
  - `operator.operatorGroup.targetNamespaces` -- scope control; empty `[]` for cluster-wide (default: `[]`)
  - `namespace.create` -- whether to create the namespace (default: `true`)
  - `namespace.labels` -- labels applied to namespace (default includes cluster-monitoring label)

## Known Gotchas

- **Operator scope must be cluster-wide:** The Tempo Operator does not support OwnNamespace install mode. Setting `targetNamespaces` to anything other than `[]` will cause the operator to fail. The values.yaml comment states: "Empty array [] enables cluster-wide scope (AllNamespaces install mode). This is required for Tempo operator as it doesn't support OwnNamespace mode."
- **TempoStack instances must be created separately:** The chart originally included TempoStack creation but this was removed. The placeholder `tempostack.yaml` template is kept to avoid breaking deployments that reference it. The README states: "This chart deploys only the Tempo Operator on OpenShift. It does not create TempoStack instances."
- **Uninstall does not remove CRDs:** The README notes: "This will not remove the CRDs or the operator itself. To completely remove the operator, you may need to manually delete the subscription and operator group."
- **Chart was converted from Kustomize:** Per the README: "This chart was converted from Kustomize configuration and follows the same structure and patterns as other Helm charts in this repository."

## Testing Notes

- Check operator pod is running: `oc get pods -n openshift-tempo-operator`
- Verify subscription status: `oc get subscription tempo-product -n openshift-tempo-operator`
- Confirm OperatorGroup exists with cluster-wide scope: `oc get operatorgroup -n openshift-tempo-operator -o yaml`
- Verify CRDs are registered: `oc get crd tempostacks.tempo.grafana.com`
- After operator is running, deploy TempoStack instances using the separate `helm/02-observability/tempo/` chart

## Related Patterns

- Tempo (TempoStack instance with MinIO storage)
- OTEL Operator (follows same operator-only chart pattern)
- Cluster Observability Operator (peer operator in the observability stack)
- Grafana Operator (peer operator in the observability stack)
