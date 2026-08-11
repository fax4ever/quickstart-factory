---
name: helm-llama-stack-operator-direct-crd-helm-deploy
description: Helm chart deploying a Kubernetes operator directly (CRD, Deployment, RBAC) without OLM Subscription
summary: "Deploys the Llama Stack Operator (v0.3.0, managing LlamaStackDistribution/llsd v1alpha1 CRs) directly via Helm chart without OLM, since unlike the co-deployed OTel/Grafana/Tempo/Cluster Observability operators it has no OLM catalog entry. Use this non-OLM direct-deploy pattern when the target operator lacks a catalog Subscription and you need direct control over image version pinning (image.repository/tag) and CRD lifecycle; the chart templates 8 files covering CRD with OpenAPI v3 schema, Deployment, split RBAC (ClusterRole for cross-namespace CRD management, namespace Role for leader election), ConfigMap, ServiceAccount, Service, and Namespace (default llama-stack-k8s-operator-system). Key values: crd.create toggles CRD installation, resources.requests default to 10m CPU/64Mi memory, health probes at :8081/healthz and /readyz, metrics at :8443, and kubectl.kubernetes.io/default-container: manager annotation ensures oc logs targets the operator container. Critical gotcha: helm uninstall deletes the CRD and all LlamaStackDistribution CRs (unlike OLM-managed CRDs which persist after operator removal); the operator image is from quay.io/eformat/ (personal/community namespace, not official Red Hat or Meta); all 5 operators install in parallel via install-operators.sh."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, llama-stack]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "Llama Stack Operator deployed via Helm with full CRD, Deployment, RBAC, ConfigMap, ServiceAccount -- no OLM"
    approach: "A"
---

# Llama Stack Operator Direct Helm Deployment (Non-OLM)

## Overview

This pattern deploys a Kubernetes operator directly via a Helm chart that templates the CRD, Deployment, RBAC resources (ClusterRole, ClusterRoleBinding, Role, RoleBinding), ConfigMap, ServiceAccount, Service, and Namespace. Unlike the OLM Subscription pattern used by other operators in the same repo, this chart installs the operator without OLM, giving direct control over the operator image version and configuration.

## Pattern Description

The Llama Stack Operator manages `LlamaStackDistribution` custom resources, which describe how to deploy Llama Stack server instances. Since this operator is not available via a Red Hat or community OLM catalog, it is deployed as a standard Kubernetes Deployment with its CRD defined inline in the Helm chart. The chart templates 7 resource types across 8 template files, including the full OpenAPI v3 schema for the CRD. This contrasts with the other 4 operators in the same repo (OTel, Grafana, Tempo, Cluster Observability) which all use the OLM Subscription pattern.

## Implementation

### Chart Structure

```
helm/01-operators/llama-stack-operator/
  Chart.yaml          # apiVersion: v2, appVersion: "v0.3.0"
  values.yaml
  templates/
    _helpers.tpl
    namespace.yaml
    serviceaccount.yaml
    configmap.yaml
    deployment.yaml
    service.yaml
    rbac.yaml           # Namespaced Role + RoleBinding
    cluster-rbac.yaml   # ClusterRole + ClusterRoleBinding
    crd.yaml            # Full CRD with OpenAPI v3 schema
```

### CRD Templated in Helm

The CRD is conditionally created via `crd.create` and includes the full OpenAPI v3 schema:

```yaml
# helm/01-operators/llama-stack-operator/templates/crd.yaml
{{- if .Values.crd.create }}
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: llamastackdistributions.llamastack.io
  annotations:
    controller-gen.kubebuilder.io/version: v0.17.2
spec:
  group: llamastack.io
  names:
    kind: LlamaStackDistribution
    shortNames: [llsd]
  scope: Namespaced
  versions:
  - name: v1alpha1
    additionalPrinterColumns:
    - jsonPath: .status.phase
      name: Phase
      type: string
    - jsonPath: .status.availableReplicas
      name: Available
      type: integer
{{- end }}
```

### Operator Deployment

```yaml
# helm/01-operators/llama-stack-operator/templates/deployment.yaml
spec:
  template:
    metadata:
      annotations:
        kubectl.kubernetes.io/default-container: manager
    spec:
      securityContext:
        {{- toYaml .Values.podSecurityContext | nindent 8 }}
      containers:
      - name: manager
        image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
        env:
        - name: OPERATOR_VERSION
          value: {{ .Values.env.operatorVersion }}
        - name: LLAMASTACK_VERSION
          value: {{ .Values.env.llamaStackVersion }}
        ports:
        - containerPort: 8443
          name: https
        - containerPort: 8081
          name: health
```

### Split RBAC (Cluster + Namespace)

The operator uses both cluster-scoped and namespace-scoped RBAC:

```yaml
# helm/01-operators/llama-stack-operator/templates/cluster-rbac.yaml
# ClusterRole for managing LlamaStackDistribution CRDs across all namespaces
# ClusterRoleBinding binding operator SA to the ClusterRole

# helm/01-operators/llama-stack-operator/templates/rbac.yaml
# Role for leader election and configmap management within operator namespace
# RoleBinding for namespace-scoped permissions
```

### Operator Values

```yaml
# helm/01-operators/llama-stack-operator/values.yaml
namespace:
  name: llama-stack-k8s-operator-system
  create: true

image:
  repository: quay.io/eformat/llama-stack-k8s-operator
  tag: v0.3.0

crd:
  create: true

resources:
  requests:
    cpu: 10m
    memory: 64Mi
```

## Configuration

- **Key settings:** `image.repository` and `image.tag` control the operator version directly (no OLM channel); `crd.create` toggles CRD installation; `namespace.name` controls the operator namespace (default `llama-stack-k8s-operator-system`)
- **Defaults:** Operator requests 10m CPU / 64Mi memory; health probes on port 8081 at /healthz and /readyz; service on port 8443 for metrics
- **Dependencies:** No OLM required; Kubernetes cluster with CRD support; the operator image must be accessible from the cluster

## Gotchas

- The CRD is installed as part of the Helm release, meaning `helm uninstall` will also remove the CRD and all LlamaStackDistribution custom resources -- this differs from OLM-managed CRDs which persist after operator removal (see `templates/crd.yaml` with `crd.create` flag)
- The operator image comes from `quay.io/eformat/` (a personal Quay namespace), not an official Red Hat or Meta registry, indicating a community/experimental operator build (see `values.yaml`)
- The `kubectl.kubernetes.io/default-container: manager` annotation on the pod template ensures `oc logs` defaults to the manager container if sidecars are injected (see `templates/deployment.yaml`)
- This chart is installed in the same parallel batch as the 4 OLM-based operator charts via `scripts/install-operators.sh`, so all 5 operators start installing simultaneously (see `scripts/install-operators.sh`)

## Related Patterns

- `observability-olm-operator-helm-install.md` -- the OLM-based operator install pattern used by the other 4 operators in the same repo
- `helm-llamastack-crd-mcp-remote-providers.md` -- the LlamaStackDistribution CR instances that this operator manages
