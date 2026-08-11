---
name: helm-olm-generic-operator-subchart-manual-approval
description: Reusable Helm subchart installing multiple OLM operators from a values dict with Manual InstallPlan approval Jobs
summary: "Installs multiple OLM operators from a single reusable Helm subchart by iterating a .Values.operators map across four templates (Namespace, OperatorGroup, Subscription, InstallPlan-approval Job), replacing the need for per-operator charts. Use when operators require pinned CSV versions with Manual installPlanApproval and automated approval -- prefer over per-operator charts (see observability-olm-operator-helm-install.md) when installing many operators (e.g., 9 in maas-code-assistant) or when Manual approval is needed; the parent all-in-one.sh auto-detects and disables pre-existing operators. Each operator entry supports enabled, channel, namespace, catalog (default redhat-operators), installPlanApproval (default Automatic), startingCSV (required for Manual, enforced via fail), and operatorGroup with targetNamespaces/upgradeStrategy; Manual approval creates a post-install,post-upgrade hook Job with a ConfigMap-mounted script using oc get installplan -ogo-template Go template query to find and approve the matching InstallPlan. The approval Job requires cluster-admin ClusterRoleBinding, a per-operator ServiceAccount (approve-<operator>), and global.toolsImage providing oc CLI with explicit securityContext (runAsNonRoot, drop ALL capabilities, RuntimeDefault seccomp); the approval script loops indefinitely with sleep 1 and has no timeout -- it relies on Helm --timeout to eventually fail the release."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "install-operators subchart installs 9 operators with range loop, supports Manual approval with automated Job-based InstallPlan approval"
    approach: "A"
---

# Generic OLM Operator Subchart with Manual InstallPlan Approval

## Overview

This pattern uses a single reusable Helm subchart to install any number of OLM operators from a values dictionary. Unlike the per-operator-chart approach (one chart per operator), this subchart templates Namespace, OperatorGroup, and Subscription resources in a range loop over a `.Values.operators` map. For operators with `installPlanApproval: Manual`, it additionally creates a Job that polls for and auto-approves the InstallPlan matching a pinned CSV version.

## Pattern Description

The `install-operators` subchart accepts an `operators` map in values.yaml where each key is an operator name and the value defines channel, namespace, catalog source, and install plan approval mode. Four templates iterate over this map to create the required OLM resources. For operators with Manual approval, the chart requires `startingCSV` to be set (enforced via a `fail` call) and creates a Job with ServiceAccount and ClusterRoleBinding that polls for the matching InstallPlan and approves it.

## Implementation

### Values-Driven Operator Configuration

```yaml
# charts/dependency-operators/values.yaml - 9 operators configured
install-operators:
  enabled: true
  operators:
    rhods-operator:
      enabled: true
      channel: stable-3.4
      namespace: redhat-ods-operator
      installPlanApproval: Manual
      startingCSV: rhods-operator.3.4.0
      operatorGroup:
        enabled: true
    rhcl-operator:
      enabled: true
      channel: stable
      namespace: kuadrant-system
      installPlanApproval: Manual
      startingCSV: rhcl-operator.v1.3.4
      operatorGroup:
        enabled: true
    cloudnative-pg:
      enabled: true
      channel: stable-v1
      catalog: certified-operators
      namespace: cloudnative-pg
      operatorGroup:
        enabled: true
```

### Subscription Template with Range Loop

```yaml
# install-operators/templates/subscriptions.yaml
{{- range $operator, $config := .Values.operators }}
{{- if $config.enabled }}
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ $operator }}
  namespace: {{ $config.namespace | default "openshift-operators" }}
spec:
  channel: {{ $config.channel }}
  installPlanApproval: {{ $config.installPlanApproval | default "Automatic" }}
  name: {{ $operator }}
  source: {{ $config.catalog | default "redhat-operators" }}
  sourceNamespace: openshift-marketplace
  {{- with $config.startingCSV }}
  startingCSV: {{ . }}
  {{- end }}
{{- end }}
{{- end }}
```

### Manual InstallPlan Approval Job

For operators with `installPlanApproval: Manual`, the chart creates a post-install hook Job per operator that polls for the InstallPlan and approves it:

```yaml
# install-operators/templates/install-plan-approvals.yaml (abbreviated)
{{- if eq ($config.installPlanApproval | default "Automatic") "Manual" }}
{{- if not $config.startingCSV }}
{{- fail "Manual approvals require pinning a specific CSV with startingCSV" }}
{{- end }}
---
apiVersion: batch/v1
kind: Job
metadata:
  name: approve-{{ $operator }}
  annotations:
    helm.sh/hook: post-install,post-upgrade
    helm.sh/hook-delete-policy: before-hook-creation
spec:
  template:
    spec:
      serviceAccountName: approve-{{ $operator }}
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: approve-operator
        image: {{ $.Values.global.toolsImage }}
        command: ["/mnt/approve-operator.sh"]
        securityContext:
          capabilities:
            drop: [ALL]
        env:
          - name: CSV
            value: {{ $config.startingCSV }}
{{- end }}
```

### InstallPlan Approval Script

The approval script uses a Go template query to find the InstallPlan matching the pinned CSV and approves it:

```bash
# install-operators/files/approve-operator.sh (templated)
function find_install_plan {
  oc get installplan -ogo-template='
    {{- range $ip := .items }}
      {{- range .spec.clusterServiceVersionNames }}
        {{- if eq . "<startingCSV>" }}
          {{- if $ip.status }}
            {{- if or (eq $ip.status.phase "RequiresApproval") (eq $ip.status.phase "Complete") }}
              {{- $ip.metadata.name }}{{ break }}
            {{- end }}
          {{- end }}
        {{- end }}
      {{- end }}
    {{- end }}' 2>/dev/null
}

while true; do
  install_plan=$(find_install_plan)
  if [ "$install_plan" ]; then
    approve_install_plan "$install_plan"
    break
  fi
  sleep 1
done
```

### OperatorGroup with Target Namespace Support

```yaml
# install-operators/templates/operatorgroups.yaml
{{- if and $config.enabled $config.namespace $config.operatorGroup }}
{{- if $config.operatorGroup.enabled }}
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: {{ $operator }}
  namespace: {{ $config.namespace }}
spec:
  upgradeStrategy: {{ $config.operatorGroup.upgradeStrategy | default "Default" }}
  {{- with $config.targetNamespaces }}
  targetNamespaces:
    {{- toYaml . | nindent 4 }}
  {{- end }}
{{- end }}
{{- end }}
```

## Configuration

- **Key settings:** Each operator entry supports `enabled`, `channel`, `namespace`, `catalog` (defaults to `redhat-operators`), `installPlanApproval` (defaults to `Automatic`), `startingCSV` (required for Manual), `operatorGroup.enabled`, and `targetNamespaces`
- **Defaults:** Operators default to `openshift-operators` namespace, `redhat-operators` catalog, and `Automatic` install plan approval
- **Dependencies:** OLM must be available; the approval Job requires `cluster-admin` ClusterRoleBinding; the `global.toolsImage` must provide `oc` CLI

## Gotchas

- The `fail` function enforces that Manual approval operators must specify `startingCSV` -- without it the approval Job would not know which InstallPlan to approve
- The approval Job uses `cluster-admin` ClusterRoleBinding because InstallPlan approval requires broad permissions across operator namespaces
- The approval Job is the only resource in the chart with explicit pod and container `securityContext` (runAsNonRoot, drop ALL capabilities, RuntimeDefault seccomp) -- other Jobs in the broader deployment do not set these
- The approval script loops indefinitely with `sleep 1` until the InstallPlan appears -- there is no timeout, relying on the Helm `--timeout` to eventually fail the release
- Operators that are already installed can be disabled by setting `enabled: false` -- the parent `all-in-one.sh` script auto-detects and disables pre-existing operators

## Related Patterns

- `observability-olm-operator-helm-install.md` -- an alternative approach using individual Helm charts per operator with Automatic approval only
- `shell-script-two-phase-helm-cluster-autodetect.md` -- the orchestrator that installs this subchart in Phase 1
- `helm-hook-configmap-mounted-script-jobs.md` -- the same ConfigMap-mounted script Job pattern used by the approval Jobs
