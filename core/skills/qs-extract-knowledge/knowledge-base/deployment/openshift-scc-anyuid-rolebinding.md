---
name: openshift-scc-anyuid-rolebinding
description: SCC anyuid granted via RoleBinding to default and NV-Ingest service accounts for third-party containers
summary: "Enables third-party containers (NV-Ingest, Milvus, Redis, Loki, Grafana, pgAdmin) that hardcode UIDs or require root to run under OpenShift's restricted SCC by granting anyuid or privileged SCC to service accounts via three approaches. Approach A (dedicated RoleBinding templates in custom subcharts, Helm-lifecycle-managed) suits charts you control, binding default SA and {{ .Release.Name }}-nv-ingest SA to system:openshift:scc:anyuid with a separate ingestor-server-rbac.yaml for OBC SA anyuid; Approach B (extraObjects in values.yaml) suits third-party charts, using namespace-scoped Role for Loki anyuid (loki/loki-canary/minio-sa SAs) and direct ClusterRole RoleBinding for Grafana privileged SCC; Approach C (imperative oc adm policy add-scc-to-user privileged -z pgadmin in Makefile before helm install) suits optional components needing a simple pre-step outside Helm lifecycle with a dedicated pre-created SA. Approach A references system:openshift:scc:anyuid ClusterRole unconditionally with no values toggle; Approach B embeds inconsistent patterns -- namespace-scoped Role with use verb on securitycontextconstraints (Loki) vs ClusterRole reference (Grafana) -- in extraObjects; Approach C requires fsGroup: 5050 and allowPrivilegeEscalation: true in the deployment spec and is the only non-restricted-SCC component in its quickstart. Helm release name changes break the {{ .Release.Name }}-nv-ingest SA reference, default SA grants elevate SCC namespace-wide, Loki's extraObjects mixes RBAC with Route definitions (minio-sa refers to Loki's built-in MinIO not a separate subchart), Approach C grants survive helm uninstall requiring manual cleanup with 2>/dev/null silently swallowing genuine errors, and Grafana requires privileged SCC despite initChownData being disabled."
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
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Privileged SCC via imperative oc CLI command in Makefile before helm install for pgAdmin"
    approach: "C"
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

---

## Approach C: Imperative CLI SCC Grant in Makefile (from data-governance-co-pilot)

### When to Use

When deploying a third-party container image (e.g., pgAdmin) that requires privileged SCC and you want a simple, explicit pre-step before `helm install` rather than encoding RBAC into Helm templates or values. This approach suits optional components with dedicated service accounts where the SCC grant is a one-time prerequisite.

### Differences from Approaches A and B

- SCC grant is imperative (`oc adm policy add-scc-to-user`) rather than declarative (Helm-managed RBAC resources)
- The grant happens outside Helm's lifecycle -- `helm uninstall` does not remove the SCC binding
- Uses a pre-created dedicated service account rather than the namespace `default` SA

### Makefile Pre-Create Pattern

The pgadmin-install target creates the service account and grants privileged SCC before running `helm install`:

```makefile
# helm/Makefile (pgadmin-install target)
pgadmin-install:
	@echo "Pre-creating pgadmin service account and granting privileged SCC..."
	@oc create serviceaccount pgadmin -n $(NAMESPACE) 2>/dev/null || echo "ServiceAccount already exists"
	@oc adm policy add-scc-to-user privileged -z pgadmin -n $(NAMESPACE) 2>/dev/null || echo "SCC already granted"
	@helm -n $(NAMESPACE) upgrade --install pgadmin $(PGADMIN_CHART) \
		--set pgadmin.email=$(pgadmin.email) \
		--set pgadmin.password=$(pgadmin.password) \
		--timeout 5m
```

### pgAdmin Deployment Using the Service Account

The Helm chart references the pre-created service account and requires both `fsGroup` and `allowPrivilegeEscalation`:

```yaml
# helm/pgadmin/templates/deployment.yaml
spec:
  template:
    spec:
      serviceAccountName: pgadmin
      securityContext:
        fsGroup: 5050
      containers:
        - name: pgadmin
          image: dpage/pgadmin4:latest
          securityContext:
            allowPrivilegeEscalation: true
            runAsUser: 5050
```

### Gotchas (Approach C)

- The SCC grant survives `helm uninstall` -- the service account and its SCC binding must be manually cleaned up or handled by a separate uninstall step (the uninstall target does not remove the SCC binding, see `helm/Makefile` pgadmin-uninstall target)
- The `2>/dev/null || echo "already exists"` pattern makes the commands idempotent but also silently swallows genuine errors
- pgAdmin requires `privileged` SCC (not just `anyuid`) because the upstream `dpage/pgadmin4` image needs both `fsGroup: 5050` and `runAsUser: 5050` with `allowPrivilegeEscalation: true` for its Python virtual environment (see `helm/pgadmin/templates/deployment.yaml`)
- This is the only component in the quickstart that does not use the restricted SCC -- all other custom components (copilot-backend, copilot-ui, pg-airman-mcp) explicitly set `runAsNonRoot: true` and `allowPrivilegeEscalation: false`

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B | Approach C |
|----------|-----------|-----------|-----------|
| SCC grant location | Dedicated RoleBinding template in chart | `extraObjects` in values.yaml | Imperative `oc adm policy` in Makefile |
| When to use | Custom subcharts where you control templates | Third-party charts configured via values | Simple pre-step for optional components |
| SCC level used | anyuid only | anyuid and privileged | privileged |
| Role indirection | Direct ClusterRole reference | Mix of Role (Loki) and ClusterRole (Grafana) | None (direct oc adm policy) |
| Visibility | Separate template file, easy to find | Buried in values.yaml among other config | Visible in Makefile target |
| Lifecycle management | Managed by Helm (created/deleted with release) | Managed by Helm via extraObjects | Imperative -- survives helm uninstall |
| Service account scope | default SA + chart-specific SA | Chart-specific SAs (loki, grafana) | Dedicated pre-created SA |
