---
name: openshift-scc-anyuid-rolebinding
description: SCC anyuid granted via RoleBinding to default and NV-Ingest service accounts for third-party containers
summary: "Grants OpenShift's anyuid SCC to service accounts via Helm-managed RoleBinding templates, enabling third-party containers like NV-Ingest that hardcode UIDs or require root to run under OpenShift's restricted SCC policy. Use dedicated RoleBinding templates in charts/ingest/templates/ (Approach A) when subchart-generated service accounts need SCC grants independently of workload definitions -- contrast with the extraObjects approach where SCC grants live alongside the workload. RoleBinding references system:openshift:scc:anyuid ClusterRole with subjects for the namespace default SA (covers Milvus/Redis sub-dependencies), the NV-Ingest SA ({{ .Release.Name }}-nv-ingest), and a separate ingestor-server-rbac.yaml RoleBinding for the ingestor server SA (OBC RBAC). Changing the Helm release name breaks the NV-Ingest SA reference in the RoleBinding; the default SA grant is namespace-wide (all pods using it get elevated SCC); the RoleBinding has no values toggle and is unconditionally created."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  platform: [openshift]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Anyuid SCC for default SA and nv-ingest SA via RoleBinding in ingest chart"
    approach: "A"
---

# OpenShift SCC Anyuid via RoleBinding

## Overview

This pattern grants the `anyuid` Security Context Constraint to specific service accounts through a Helm-managed RoleBinding, enabling third-party containers that require running as a specific UID to function on OpenShift. Unlike the `extraObjects` approach where SCC grants live alongside the workload definition, this uses a dedicated RoleBinding template in the chart.

## Pattern Description

Third-party container images like NV-Ingest often hardcode user IDs or expect to run as root, which conflicts with OpenShift's default restricted SCC. This pattern creates a RoleBinding that maps service accounts to the `system:openshift:scc:anyuid` ClusterRole, allowing pods under those accounts to run with any UID. The RoleBinding is a standalone template in the Helm chart, granting access to both the namespace's `default` service account and the NV-Ingest subchart's generated service account.

## Implementation

### SCC RoleBinding Template

```yaml
# charts/ingest/templates/scc-rolebinding.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ .Release.Name }}-anyuid
  namespace: {{ .Release.Namespace }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:openshift:scc:anyuid
subjects:
  - kind: ServiceAccount
    name: default
    namespace: {{ .Release.Namespace }}
  - kind: ServiceAccount
    name: {{ .Release.Name }}-nv-ingest
    namespace: {{ .Release.Namespace }}
```

### Additional Anyuid for Ingestor Server SA

The ingestor server has its own ServiceAccount (for OBC RBAC), which also needs the anyuid SCC:

```yaml
# charts/ingest/templates/ingestor-server-rbac.yaml (excerpt)
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ $cfg.appName }}-anyuid
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:openshift:scc:anyuid
subjects:
  - kind: ServiceAccount
    name: {{ $cfg.appName }}
    namespace: {{ .Release.Namespace }}
```

## Configuration

- **Key settings:** The NV-Ingest SA name follows the subchart's naming convention: `{{ .Release.Name }}-nv-ingest`
- **Defaults:** The SCC RoleBinding is always created (no toggle) since NV-Ingest cannot function under restricted SCC
- **Dependencies:** The `system:openshift:scc:anyuid` ClusterRole exists by default on OpenShift

## Gotchas

- The NV-Ingest subchart service account name is constructed as `{{ .Release.Name }}-nv-ingest` -- if the Helm release name changes, the RoleBinding must reference the updated SA name
- Both the namespace `default` SA and the `nv-ingest` SA are granted anyuid because Milvus and Redis (sub-dependencies of NV-Ingest) also run under the default SA
- There is no values toggle to disable this RoleBinding; it is unconditionally created whenever the ingest chart is installed
- This grants the entire namespace's `default` service account anyuid, which is broader than necessary -- all pods using the default SA in the namespace will benefit from the elevated SCC

## Related Patterns

- `helm-nv-ingest-ngc-remote-subchart.md` -- the NV-Ingest subchart whose containers require anyuid
- `odf-obc-init-container-wait.md` -- the ingestor server SA that also gets anyuid via a separate RoleBinding
