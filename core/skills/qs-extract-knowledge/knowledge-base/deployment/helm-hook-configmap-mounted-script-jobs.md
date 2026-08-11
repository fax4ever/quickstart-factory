---
name: helm-hook-configmap-mounted-script-jobs
description: Repeated pattern of Helm post-install Jobs mounting scripts from ConfigMaps via .Files.Glob for imperative cluster ops
summary: "Bridges Helm's declarative/imperative gap by running post-install/post-upgrade hook Jobs that mount shell scripts from ConfigMaps for imperative OpenShift cluster mutations such as creating DSCInitialization/DataScienceCluster, patching OAuth and Authorino TLS, approving Manual InstallPlans, restarting Kuadrant, and optionally removing kubeadmin. Use when operations require oc CLI commands, CRD readiness waits, or operator lifecycle management that Helm templates cannot express -- each Job follows a four-resource structure (ServiceAccount + RBAC + ConfigMap via .Files.Glob/.Files.Get with .AsConfig and tpl rendering + Job) demonstrated 7+ times across maas-code-assistant's dependency-operators, install-operators, maas-code-assistant, and keycloak charts. Critical configuration: global.toolsImage supplies the oc CLI container image, defaultMode: 493 (decimal for octal 0755) makes ConfigMap-mounted scripts executable, tpl wrapping is mandatory to render .Values inside files/ scripts, and before-hook-creation delete policy prevents stuck previous Jobs from blocking redeployment. RBAC scope varies from namespace-scoped minimal Roles (patch-odhdashboardconfig) to cluster-admin ClusterRoleBindings (approve-operator, patch-oauth); CRD-dependent resources require retry loops (while ! oc apply; do sleep 5; done) because CRDs may not register immediately after operator install; Kuadrant restart uses a hardcoded sleep 30 for operator settling; and backoffLimit: 4 with restartPolicy: Never means failed scripts retry up to 4 times before permanent failure."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "7+ Jobs across 3 charts using SA+RBAC+ConfigMap(.Files.Glob)+Job pattern for imperative cluster mutations (create DSC, patch OAuth, restart Kuadrant, approve InstallPlans, etc.)"
    approach: "A"
---

# Helm Hook ConfigMap-Mounted Script Jobs

## Overview

This pattern uses Helm post-install/post-upgrade hook Jobs to execute imperative operations that cannot be expressed declaratively in Helm templates. Each Job follows a consistent four-resource structure: ServiceAccount, RBAC bindings, ConfigMap (populated from `.Files.Glob` or `.Files.Get`), and a Job that mounts the ConfigMap and runs the script. The maas-code-assistant quickstart uses this pattern 7+ times across its charts for operations like creating DataScienceClusters, patching OAuth configuration, restarting operators, and approving InstallPlans.

## Pattern Description

Certain OpenShift operations require imperative `oc` commands: patching cluster-scoped resources, waiting for operator readiness, creating resources that depend on other resources being ready, or restarting misbehaving operators. This pattern bridges the imperative/declarative gap by embedding shell scripts as Helm chart files (under `files/`), rendering them into ConfigMaps via `.Files.Glob` with `tpl` for template variable expansion, and mounting them into Jobs that execute as post-install hooks.

## Implementation

### Consistent Four-Resource Structure

Every instance follows this structure (example: `patch-odhdashboardconfig`):

```yaml
# charts/maas-code-assistant/templates/job-patch-odhdashboardconfig.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: patch-odhdashboardconfig
  namespace: redhat-ods-applications
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: patch-odhdashboardconfig
  namespace: redhat-ods-applications
rules:
- apiGroups: ["opendatahub.io"]
  resources: ["odhdashboardconfigs"]
  verbs: [create, get, list, update, patch, delete]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: patch-odhdashboardconfig
  namespace: redhat-ods-applications
roleRef:
  kind: Role
  name: patch-odhdashboardconfig
subjects:
  - kind: ServiceAccount
    name: patch-odhdashboardconfig
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: patch-odhdashboardconfig-script
data:
{{ tpl (.Files.Glob "files/*odhdashboardconfig*").AsConfig $ | indent 2 }}
---
apiVersion: batch/v1
kind: Job
metadata:
  name: patch-odhdashboardconfig
  annotations:
    helm.sh/hook: post-install,post-upgrade
    helm.sh/hook-delete-policy: before-hook-creation
spec:
  backoffLimit: 4
  template:
    spec:
      serviceAccountName: patch-odhdashboardconfig
      restartPolicy: Never
      containers:
      - name: patch-odhdashboardconfig
        image: {{ .Values.global.toolsImage }}
        workingDir: /app
        command: ["/app/patch-odhdashboardconfig.sh"]
        volumeMounts:
          - name: patch-odhdashboardconfig-script
            mountPath: /app
      volumes:
        - name: patch-odhdashboardconfig-script
          configMap:
            name: patch-odhdashboardconfig-script
            defaultMode: 493
```

### Script Files with Template Rendering

Scripts are stored under `files/` in each chart and rendered with `tpl` so they can reference `.Values`:

```bash
# charts/maas-code-assistant/files/patch-odhdashboardconfig.sh
#!/bin/bash
set -ex
oc patch odhdashboardconfig odh-dashboard-config \
  --patch-file=odhdashboardconfig.yaml --type=merge
oc delete pods -l app=rhods-dashboard
sleep 1
oc rollout status deploy/rhods-dashboard
```

```bash
# charts/maas-code-assistant/files/restart-kuadrant.sh
#!/bin/bash
set -e
sleep 30
oc delete pod -l app=kuadrant,control-plane=controller-manager
sleep 1
oc rollout status deployment/kuadrant-operator-controller-manager
```

### ConfigMap Population Variants

Two approaches are used for populating ConfigMaps from files:

```yaml
# Glob pattern for multiple files in a directory
data:
{{ tpl ($.Files.Glob "files/openshift-ai/*").AsConfig . | indent 2 }}

# Glob pattern for specific file match
data:
{{ tpl (.Files.Glob "files/*odhdashboardconfig*").AsConfig $ | indent 2 }}

# Files.Get for single file with tpl rendering
data:
  approve-operator.sh: |
    {{- tpl ($.Files.Get "files/approve-operator.sh") (list $operator $config) | nindent 4 }}
```

### All Jobs in the Deployment

| Chart | Job Name | Purpose | RBAC |
|-------|----------|---------|------|
| dependency-operators | create-datasciencecluster | Create DSCInitialization, DataScienceCluster, Gateway, PostgreSQL Cluster | ClusterRoleBinding (3 admin roles) |
| dependency-operators | create-kuadrant | Wait for RHCL operators, apply Kuadrant CR, patch Authorino TLS | RoleBinding (admin + edit + OLM view) |
| dependency-operators | create-leaderworkerset | Apply LeaderWorkerSetOperator CR | ClusterRoleBinding (LWS admin) |
| install-operators | approve-{operator} | Poll and approve Manual InstallPlans | ClusterRoleBinding (cluster-admin) |
| maas-code-assistant | patch-odhdashboardconfig | Patch OdhDashboardConfig, restart dashboard pods | Role (odhdashboardconfigs CRUD) + edit |
| maas-code-assistant | restart-kuadrant | Delete and restart Kuadrant controller pods | RoleBinding (edit) |
| keycloak | patch-oauth-{name} | Patch cluster OAuth with Keycloak identity provider | ClusterRoleBinding (cluster-admin) |
| keycloak | remove-kubeadmin | Delete kubeadmin secret (optional) | RoleBinding (edit in kube-system) |

## Configuration

- **Key settings:** `global.toolsImage` provides the container image with `oc` CLI for all Jobs; `backoffLimit: 4` for retry; `defaultMode: 493` (octal 0755) on ConfigMap volume for script executability
- **Defaults:** All Jobs use `restartPolicy: Never`, `helm.sh/hook: post-install,post-upgrade`, and `helm.sh/hook-delete-policy: before-hook-creation`
- **Dependencies:** All Jobs require the `oc` CLI in the container image; RBAC must be sufficient for the operations performed

## Gotchas

- The `defaultMode: 493` on ConfigMap volumes is decimal for octal `0755`, making the mounted scripts executable -- this is required because ConfigMap-mounted files default to read-only
- The `tpl` function is used to render `.Values` references inside script files that are stored under `files/` -- without `tpl`, Helm template syntax in those files would be treated as literal text
- The `before-hook-creation` delete policy removes the previous Job before creating the new one -- if a previous Job is stuck in a non-terminal state, this avoids blocking
- The `restart-kuadrant.sh` script has a hardcoded `sleep 30` at the start, giving Kuadrant time to settle after the main chart install before forcing a restart -- the values.yaml comment notes "Kuadrant sometimes misbehaves"
- The `create-datasciencecluster.sh` script uses a retry loop (`while ! oc apply -f datasciencecluster.yaml; do sleep 5; done`) because the DataScienceCluster CRD may not be registered immediately after the RHOAI operator installs
- RBAC scope varies significantly: some Jobs use namespace-scoped Roles with minimal permissions (patch-odhdashboardconfig) while others use `cluster-admin` (patch-oauth, approve-operator)

## Related Patterns

- `helm-olm-generic-operator-subchart-manual-approval.md` -- uses this same pattern specifically for InstallPlan approval
- `shell-script-two-phase-helm-cluster-autodetect.md` -- the orchestrator that triggers these hook Jobs via helm upgrade --install
