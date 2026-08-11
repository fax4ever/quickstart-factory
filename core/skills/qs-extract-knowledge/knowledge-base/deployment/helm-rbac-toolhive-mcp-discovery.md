---
name: helm-rbac-toolhive-mcp-discovery
description: Helm RBAC Role granting access to ToolHive MCPServer CRD for Kubernetes-native MCP server discovery
summary: "Enables Kubernetes-native dynamic discovery of MCP servers by granting a ServiceAccount RBAC access to ToolHive's MCPServer CRD (toolhive.stacklok.dev API group), avoiding hardcoded MCP server endpoints in AI agent applications. Use when deploying an application (like ai-virtual-agent) that needs runtime MCP server discovery via the Kubernetes API rather than static configuration; requires ToolHive operator (Stacklok) pre-installed on the cluster. The namespace-scoped Role defines four rule blocks -- secrets/endpoints/services (get/list), configmaps (get/list/patch/update), deployments (get/list/patch/update), and toolhive.stacklok.dev/mcpservers (get/list) -- with a RoleBinding connecting to the application's ServiceAccount. ToolHive CRD permissions are unconditionally included with no values.yaml toggle -- RBAC rules are harmless if the CRD is absent but discovery silently returns nothing; configmaps/deployments include patch/update because the app self-modifies at runtime; this Role is separate from the ClusterRoleBinding for OAuth proxy's system:auth-delegator in the same rbac.yaml."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Role with toolhive.stacklok.dev/mcpservers get/list for K8s-native MCP server discovery alongside standard resource access"
    approach: "A"
---

# Helm RBAC with ToolHive MCP Discovery

## Overview

This pattern defines a Kubernetes Role that grants the application's ServiceAccount access to the ToolHive `mcpservers` custom resource, enabling Kubernetes-native discovery of MCP (Model Context Protocol) servers. The Role combines standard resource permissions (secrets, endpoints, services, configmaps, deployments) with the ToolHive CRD permission in a single RBAC definition.

## Pattern Description

The application needs to dynamically discover MCP servers running in the same namespace. Rather than hardcoding MCP server endpoints, it queries the Kubernetes API for `MCPServer` custom resources from the `toolhive.stacklok.dev` API group. The Helm chart creates a Role with `get` and `list` permissions on this CRD, bound to the application's ServiceAccount. This sits alongside conventional RBAC rules for reading secrets/endpoints/services and patching configmaps/deployments.

## Implementation

### Role Definition

The Role template combines standard and CRD-based rules:

```yaml
# deploy/cluster/helm/templates/rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ include "ai-virtual-agent.fullname" . }}
rules:
- apiGroups:
  - ""
  resources:
  - secrets
  - endpoints
  - services
  verbs:
  - get
  - list
- apiGroups:
  - ""
  resources:
  - configmaps
  verbs:
  - get
  - list
  - patch
  - update
- apiGroups:
  - apps
  resources:
  - deployments
  verbs:
  - get
  - list
  - patch
  - update
- apiGroups:
  - toolhive.stacklok.dev
  resources:
  - mcpservers
  verbs:
  - get
  - list
```

### RoleBinding

The RoleBinding connects the Role to the application's ServiceAccount:

```yaml
# deploy/cluster/helm/templates/rbac.yaml (continued)
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ include "ai-virtual-agent.fullname" . }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ include "ai-virtual-agent.fullname" . }}
subjects:
- kind: ServiceAccount
  name: {{ include "ai-virtual-agent.serviceAccountName" . }}
```

## Configuration

- **Key settings:** The Role is namespace-scoped (not ClusterRole), so MCP server discovery is limited to the application's own namespace
- **Defaults:** The ToolHive permissions are always included in the Role; there is no condition to disable them
- **Dependencies:** Requires the ToolHive operator and its `MCPServer` CRD to be installed on the cluster for the MCP discovery to function. The RBAC rules will apply regardless, but they have no effect without the CRD

## Gotchas

- The `configmaps` and `deployments` resources have `patch` and `update` verbs in addition to `get` and `list`, suggesting the application modifies its own configuration and deployment at runtime (see `rbac.yaml` lines 19-33)
- The `toolhive.stacklok.dev` API group is from the ToolHive project (by Stacklok). If ToolHive is not installed on the cluster, the CRD won't exist but the RBAC rules are harmless -- they simply won't match any resources
- This Role is separate from the ClusterRoleBinding for `system:auth-delegator` used by the OAuth proxy, which is also defined in the same `rbac.yaml` file

## Related Patterns

- `openshift-oauth-proxy-sidecar.md` -- the ClusterRoleBinding for OAuth proxy in the same RBAC template
- `helm-umbrella-all-remote-ai-arch-deps.md` -- the umbrella chart this RBAC template is part of
