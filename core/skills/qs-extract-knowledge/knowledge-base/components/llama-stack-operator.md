---
name: llama-stack-operator
description: "Kubernetes operator managing LlamaStackDistribution CRDs for deploying Llama Stack inference instances"
summary: "The Llama Stack Operator (Go /manager, quay.io/eformat/llama-stack-k8s-operator:v0.3.0) provides a namespace-scoped LlamaStackDistribution CRD (llamastack.io/v1alpha1, short name llsd) for CRD-driven deployment and lifecycle management of Llama Stack inference instances, reconciling custom resources into Deployments, Services, ConfigMaps, PVCs, and NetworkPolicies via kubebuilder/controller-runtime. Use when Kubernetes/OpenShift CRD-based lifecycle management of Llama Stack is needed — the CRD enforces mutual exclusivity between distribution.name and distribution.image via x-kubernetes-validations, tracks five status phases (Pending/Initializing/Ready/Failed/Terminating) with per-provider health, and the Helm chart at helm/01-operators/ creates layered RBAC (namespaced leader-election Role, ClusterRoles for manager CRUD, metrics-reader, and auth-proxy tokenreviews/subjectaccessreviews). Helm values control image, namespace.name/create, crd.create, leaderElection.enabled, rbac.create, and resource requests (10m CPU/64Mi memory), with OPERATOR_VERSION and LLAMA_STACK_VERSION env vars; controller-manager ConfigMap mounts at /controller_manager_config.yaml binding health:8081, metrics:127.0.0.1:8080, webhook:9443. Namespace template redirects to llama-stack-k8s-operator-system when release namespace is \"default\"; chart uninstall does NOT delete the CRD or existing CRs (manual kubectl delete crd llamastackdistributions.llamastack.io required); metrics Service targets port 8443 via name \"https\" not container port 8080 so service.targetPort must match a named container port; leaderElectionReleaseOnCancel intentionally disabled due to unsafe post-stop cleanup."
metadata:
  type: component
tags:
  tech_stack: [helm, kubernetes-operator]
  ai_pattern: [model-serving]
  platform: [kubernetes, openshift]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Helm chart deploying Llama Stack Operator with CRD, RBAC, and leader election for managing LlamaStackDistribution resources"
    approach: "A"
---

# Llama Stack Operator

## Overview

The Llama Stack Operator is a Kubernetes operator that provides a CRD-based interface (`LlamaStackDistribution`) for deploying and managing Llama Stack inference instances. It is deployed via a standalone Helm chart under `helm/01-operators/` and runs as a controller-manager Deployment that watches `LlamaStackDistribution` custom resources, reconciling them into Deployments, Services, ConfigMaps, PVCs, and NetworkPolicies. The operator is built with `controller-gen` (kubebuilder scaffold) and uses `controller-runtime` for its manager configuration.

## Tech Stack & Dependencies

- **Runtime:** Go binary (`/manager` entrypoint)
- **Container image:** `quay.io/eformat/llama-stack-k8s-operator:v0.3.0`
- **Key dependencies:** controller-runtime v1alpha1 ControllerManagerConfig, `controller-gen` v0.17.2 for CRD generation
- **Helm chart:** Standalone chart at `helm/01-operators/llama-stack-operator/` (chart version 1.0.0, appVersion v0.3.0)
- **Upstream source:** [meta-llama/llama-stack](https://github.com/meta-llama/llama-stack)

## Key Patterns

### CRD: LlamaStackDistribution

The operator introduces a `LlamaStackDistribution` CRD (`llamastack.io/v1alpha1`) that is namespace-scoped. The CRD defines a `server` spec with distribution selection (by name or by direct image reference), container overrides, and pod-level overrides including custom volumes and service accounts.

```yaml
apiVersion: llamastack.io/v1alpha1
kind: LlamaStackDistribution
metadata:
  name: my-llama-stack
spec:
  replicas: 1
  server:
    distribution:
      image: meta-llama/llama-stack:latest  # or use name: for supported distros
    containerSpec:
      name: llama-stack
      env:
      - name: LLAMA_STACK_PORT
        value: "5000"
```

A CRD validation rule enforces mutual exclusivity between `distribution.name` and `distribution.image`:

```yaml
x-kubernetes-validations:
- message: Only one of name or image can be specified
  rule: '!(has(self.name) && has(self.image))'
```

### Status Lifecycle Phases

The CRD status tracks a `phase` enum with five lifecycle states: `Pending`, `Initializing`, `Ready`, `Failed`, `Terminating`. Additional printer columns surface phase, operator version, server version, and available replicas directly in `kubectl get` output:

```yaml
additionalPrinterColumns:
- jsonPath: .status.phase
  name: Phase
  type: string
- jsonPath: .status.availableReplicas
  name: Available
  type: integer
```

The status also exposes a `distributionConfig` block containing per-provider health information (`api`, `provider_id`, `provider_type`, `health.status`, `health.message`).

### Controller Manager ConfigMap

The operator mounts its configuration via a ConfigMap at `/controller_manager_config.yaml`. This configures health probes, metrics binding, webhook port, and leader election:

```yaml
data:
  controller_manager_config.yaml: |
    apiVersion: controller-runtime.sigs.k8s.io/v1alpha1
    kind: ControllerManagerConfig
    health:
      healthProbeBindAddress: :8081
    metrics:
      bindAddress: 127.0.0.1:8080
    webhook:
      port: 9443
    leaderElection:
      leaderElect: true
      resourceName: 54e06e98.llamastack.io
```

### Namespace Handling

The Helm chart uses a custom namespace helper that falls back to the `values.yaml` namespace name when the Helm release namespace is `default`. This allows the operator to always deploy into its own dedicated namespace (`llama-stack-k8s-operator-system`) even when installed without `--namespace`:

```yaml
{{- define "llama-stack-operator.namespace" -}}
{{- if eq .Release.Namespace "default" }}
{{- .Values.namespace.name }}
{{- else }}
{{- .Release.Namespace }}
{{- end }}
{{- end }}
```

### RBAC Structure

The chart creates a layered RBAC model:
- **Namespaced Role/RoleBinding:** Leader election access (configmaps, leases, events) in the operator namespace
- **ClusterRole (manager):** Full CRUD on `llamastackdistributions`, deployments, services, configmaps, PVCs, and networkpolicies
- **ClusterRole (metrics-reader):** Read-only access to `/metrics` non-resource URL
- **ClusterRole (proxy):** `tokenreviews` and `subjectaccessreviews` for authentication proxy

## Configuration

- **Environment variables:**
  - `OPERATOR_VERSION` -- operator version identifier (default: `latest`)
  - `LLAMA_STACK_VERSION` -- Llama Stack version identifier (default: `latest`)
- **Helm values:**
  - `image.repository` / `image.tag` -- operator container image (`quay.io/eformat/llama-stack-k8s-operator:v0.3.0`)
  - `namespace.name` -- target namespace (`llama-stack-k8s-operator-system`)
  - `namespace.create` -- whether to create the namespace (`true`)
  - `crd.create` -- whether to install the CRD (`true`)
  - `leaderElection.enabled` -- enable leader election (`true`)
  - `rbac.create` -- create RBAC resources (`true`)
  - `resources.requests.cpu` / `resources.requests.memory` -- operator resource requests (`10m` / `64Mi`)

## Known Gotchas

- The `namespace` template helper overrides the Helm release namespace only when it equals `"default"` -- if you install with `--namespace default` intentionally, the operator will deploy into `llama-stack-k8s-operator-system` instead. Use an explicit `--namespace <name>` to control placement.
- The CRD is installed by the same Helm chart as the operator. Uninstalling the chart does NOT delete the CRD or existing `LlamaStackDistribution` resources, as noted in the chart README. Manual cleanup is required: `kubectl delete crd llamastackdistributions.llamastack.io`.
- The ConfigMap comment notes that `leaderElectionReleaseOnCancel` is intentionally left disabled because it is unsafe if the manager performs cleanup after stopping.
- The operator container exposes three ports (8081 health, 8080 metrics, 9443 webhook) but the metrics Service targets port 8443 via name `https`, not port 8080 directly -- the `service.targetPort: https` value must match a named port on the container.
- Pod security is set to `runAsNonRoot: true` with `allowPrivilegeEscalation: false` and all capabilities dropped, suitable for OpenShift restricted SCC.

## Testing Notes

- Verify operator pod is running: `kubectl get pods -n llama-stack-k8s-operator-system -l control-plane=controller-manager`
- Verify CRD is registered: `kubectl get crd llamastackdistributions.llamastack.io`
- Create a test `LlamaStackDistribution` and confirm it reaches `Ready` phase: `kubectl get llamastackdistributions -A`
- Short name `llsd` is available for the CRD: `kubectl get llsd -A`

## Related Patterns

- See `llamastack.md` for the Llama Stack server component that this operator manages
- See `observability-stack.md` for metrics and tracing integration with the operator's metrics endpoint
