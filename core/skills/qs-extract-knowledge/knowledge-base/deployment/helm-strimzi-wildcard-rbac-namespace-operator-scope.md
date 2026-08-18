---
name: helm-strimzi-wildcard-rbac-namespace-operator-scope
description: Wildcard Role and RoleBinding granting Strimzi Kafka operator full namespace access with createGlobalResources disabled
summary: "Solves namespace-scoped Strimzi Kafka operator deployment by granting full namespace-level RBAC via wildcard Role/RoleBinding instead of requiring cluster-wide ClusterRoles. Use when deploying Strimzi as a Helm subchart dependency within a quickstart namespace where cluster-admin permissions are unavailable -- the createGlobalResources=false flag (passed via Makefile --set) prevents ClusterRole creation, constraining the operator to a single namespace. The Helm template (templates/rbac-strimzi.yaml) creates a Role with [\"*\"] on all apiGroups/resources/verbs bound to the strimzi-cluster-operator ServiceAccount via {{ .Release.Namespace }}, while STRIMZI_USE_FINALIZERS=false is set in values.yaml extraEnvs to prevent finalizer-blocked namespace deletion. Wildcard [\"*\"] grants far more permissions than needed (production should enumerate Kafka/Strimzi CRD API groups), and the hardcoded ServiceAccount name strimzi-cluster-operator creates tight coupling to Strimzi chart internals."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, kafka]
  ai_pattern: [data-pipeline]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Wildcard Role/RoleBinding for strimzi-cluster-operator SA with createGlobalResources=false for namespace-scoped Kafka deployment"
    approach: "A"
---

# Strimzi Kafka Wildcard RBAC for Namespace-Scoped Operator

## Overview

Grants the Strimzi Kafka cluster operator full namespace-level access via a wildcard Role and RoleBinding, paired with `createGlobalResources=false` in Helm values to constrain the operator to the deployment namespace rather than requiring cluster-wide permissions.

## Pattern Description

When deploying the Strimzi Kafka operator as a Helm dependency within a quickstart namespace (rather than cluster-wide), the operator's ServiceAccount needs permissions to manage Kafka-related resources. Rather than enumerating specific API groups and resources, this pattern grants `["*"]` across all API groups, resources, and verbs at the namespace level. The `createGlobalResources=false` Helm value prevents the operator from attempting to create ClusterRoles and other cluster-scoped resources.

## Implementation

### Wildcard Role and RoleBinding

```yaml
# helm/product-recommender-system/templates/rbac-strimzi.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: strimzi-local-role
rules:
  - apiGroups: ["*"]
    resources: ["*"]
    verbs: ["*"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: strimzi-local-rolebinding
subjects:
  - kind: ServiceAccount
    name: strimzi-cluster-operator
    namespace: {{ .Release.Namespace }}
roleRef:
  kind: Role
  name: strimzi-local-role
  apiGroup: rbac.authorization.k8s.io
```

### Strimzi Helm Values Configuration

```yaml
# helm/product-recommender-system/values.yaml
strimzi-kafka-operator:
  extraEnvs:
    - name: STRIMZI_USE_FINALIZERS
      value: "false"
```

The `createGlobalResources=false` flag is passed at install time via the Makefile:

```makefile
# helm/Makefile (product-recommender-install target)
@helm -n $(NAMESPACE) upgrade --install $(PRODUCT_RECOMMENDER_CHART) $(PRODUCT_RECOMMENDER_CHART) \
    --set strimzi-kafka-operator.createGlobalResources=false
```

## Configuration

- **Key settings:** `strimzi-kafka-operator.createGlobalResources=false` (passed via `--set` in Makefile), `STRIMZI_USE_FINALIZERS=false` (prevents finalizer-based cleanup that can block namespace deletion)
- **Defaults:** Strimzi is deployed as a dependency of the main product-recommender-system chart
- **Dependencies:** Strimzi Kafka operator chart as a Helm dependency (not explicitly listed in Chart.yaml dependencies -- assumes operator is available)

## Gotchas

- The wildcard `["*"]` on all API groups and resources grants the operator far more permissions than needed; a tighter Role would enumerate only the Kafka/Strimzi CRD API groups.
- `STRIMZI_USE_FINALIZERS=false` is set to prevent the operator from adding finalizers to Kafka resources, which would otherwise block namespace deletion if the operator is removed first.
- The Role is namespace-scoped (not a ClusterRole), so the operator can only manage resources within the release namespace.
- The ServiceAccount name `strimzi-cluster-operator` is hardcoded, creating a tight coupling to the Strimzi chart's internal naming.

## Related Patterns

- `openshift-scc-anyuid-rolebinding.md` — SCC grants for other operator service accounts in the same ecosystem
