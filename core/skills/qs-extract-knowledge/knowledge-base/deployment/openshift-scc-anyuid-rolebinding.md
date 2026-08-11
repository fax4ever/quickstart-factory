---
name: openshift-scc-anyuid-rolebinding
description: SCC anyuid granted via RoleBinding to default and NV-Ingest service accounts for third-party containers
summary: "Enables third-party containers (NV-Ingest, Milvus, Redis, Loki, Grafana) that hardcode UIDs or require root to run under OpenShift's restricted SCC by granting anyuid or privileged SCC to service accounts via Helm-managed RoleBindings. Approach A (dedicated RoleBinding templates in charts/ingest/templates/) suits custom subcharts you control, binding default SA and {{ .Release.Name }}-nv-ingest SA to system:openshift:scc:anyuid with a separate ingestor-server-rbac.yaml for OBC RBAC; Approach B (extraObjects in values.yaml) suits third-party charts, using Role+RoleBinding for Loki anyuid (loki/loki-canary/minio-sa SAs) and direct ClusterRole RoleBinding for Grafana privileged SCC. Approach A references system:openshift:scc:anyuid ClusterRole with SA name {{ .Release.Name }}-nv-ingest and is unconditionally created with no values toggle; Approach B embeds RBAC in extraObjects arrays using inconsistent patterns -- namespace-scoped Role for Loki vs ClusterRole reference for Grafana. Helm release name changes break the NV-Ingest SA reference in Approach A, default SA grants elevate SCC namespace-wide for all pods, Loki's extraObjects mixes RBAC with Route definitions, minio-sa refers to Loki's built-in MinIO not a separate subchart, and Grafana requires privileged SCC despite initChownData being disabled."
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
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Anyuid and privileged SCC via extraObjects in third-party chart values (Loki, Grafana)"
    approach: "B"
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

---

## Approach B: SCC via Third-Party Chart extraObjects (from ansible-log-analysis)

### When to Use

When the SCC-requiring service accounts are managed by third-party Helm charts (e.g., Grafana, Loki) and you configure them through the parent chart's `values.yaml` rather than writing custom chart templates. This approach keeps SCC grants alongside other chart configuration in values.

### Differences from Approach A

- SCC grants are defined in `values.yaml` under each third-party chart's `extraObjects` key, not as dedicated RoleBinding templates
- Uses both `anyuid` (for Loki) and `privileged` (for Grafana) SCC levels
- Loki uses a Role + RoleBinding pair (granting the SCC `use` verb via a Role), while Grafana uses a direct ClusterRole RoleBinding

### Loki Anyuid via Role + RoleBinding in extraObjects

Loki creates a Role that grants `use` on the `anyuid` SCC resource, then binds it to three service accounts (loki, loki-canary, minio-sa):

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (loki.extraObjects)
loki:
  extraObjects:
    - apiVersion: rbac.authorization.k8s.io/v1
      kind: Role
      metadata:
        name: loki-anyuid-scc
      rules:
        - apiGroups:
            - security.openshift.io
          resources:
            - securitycontextconstraints
          verbs:
            - use
          resourceNames:
            - anyuid
    - apiVersion: rbac.authorization.k8s.io/v1
      kind: RoleBinding
      metadata:
        name: loki-anyuid-scc
      subjects:
        - kind: ServiceAccount
          name: loki
        - kind: ServiceAccount
          name: loki-canary
        - kind: ServiceAccount
          name: minio-sa
      roleRef:
        kind: Role
        name: loki-anyuid-scc
        apiGroup: rbac.authorization.k8s.io
```

### Grafana Privileged via Direct ClusterRole RoleBinding

Grafana uses a direct RoleBinding to the `system:openshift:scc:privileged` ClusterRole:

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (grafana.extraObjects)
grafana:
  extraObjects:
    - apiVersion: rbac.authorization.k8s.io/v1
      kind: RoleBinding
      metadata:
        name: grafana-privileged-scc
      subjects:
        - kind: ServiceAccount
          name: grafana
      roleRef:
        kind: ClusterRole
        name: system:openshift:scc:privileged
        apiGroup: rbac.authorization.k8s.io
```

### Gotchas (Approach B)

- Loki's extraObjects also creates an OpenShift Route in the same array, mixing RBAC and networking concerns in one list
- The Loki approach creates a namespace-scoped Role (more restrictive) while the Grafana approach references a ClusterRole (less restrictive) -- two different patterns in the same chart
- The `minio-sa` service account in the Loki RoleBinding refers to Loki's built-in MinIO (for chunk storage), not the separate MinIO subchart from ai-architecture-charts
- Grafana requires `privileged` SCC (not just `anyuid`) even though `initChownData` is disabled -- this may be due to the Grafana chart's default security requirements

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| SCC grant location | Dedicated RoleBinding template in chart | `extraObjects` in values.yaml |
| When to use | Custom subcharts where you control templates | Third-party charts configured via values |
| SCC level used | anyuid only | anyuid and privileged |
| Role indirection | Direct ClusterRole reference | Mix of Role (Loki) and ClusterRole (Grafana) |
| Visibility | Separate template file, easy to find | Buried in values.yaml among other config |
