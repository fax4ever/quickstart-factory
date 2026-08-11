---
name: f5-ai-security
description: "Helm chart deploying F5 AI Security Operator via OLM, SecurityOperator CR, SCC bindings, and Moderator routes on OpenShift"
summary: "Deploys CalypsoAI (F5 AI Security Operator) on OpenShift via OLM Subscription (pinned startingCSV) as a standalone Helm chart at deploy/helm/f5-ai-security/, reconciling Moderator UI/API + PostgreSQL, Prefect orchestration, and KubeAI inference for guardrail scanning across four namespaces (f5-ai-sec, cai-moderator, prefect, f5-ai-sec-inference), deployable via single make install-f5-ai-security with Harbor registry auth and F5_LICENSE in f5-ai-security-values.yaml. Use when deploying F5 AI Security on OpenShift where the operator cannot manage SCC bindings, cluster-scoped RBAC, OpenShift Routes, or pre-applied inference SCCs -- the chart wraps all OpenShift-specific concerns and requires a two-pass helm upgrade --install (first pass creates OLM Subscription, Makefile waits for CSV Succeeded, second pass renders SecurityOperator CR via lookup CRD detection rather than .Capabilities.APIVersions). Critical patterns: SCC anyuid bindings for 7 namespace/SA pairs, pre-applied inference SCC with matching meta.helm.sh/release-name and release-namespace annotations, nvidia.com/gpu tolerations merge (operator: Exists) into KubeAI resource profiles, controller-manager RBAC escalation (pods/status, batch, SCC patch), and dual auto-derived Routes from cluster ingress domain (root port 5500 UI, /auth port 8080 Keycloak). Gotchas: controller-manager OOMKilled at default 128Mi (patch to 512Mi), inference SCC annotation mismatch causes Helm import error, invalid license after reinstall requires clearing encrypted DB tables (setting/secret/secret_config) while stale DB license overrides YAML CAI_MODERATOR_DEFAULT_LICENSE, missing /auth route produces blank Moderator UI, and KServe webhook service must have backing pod endpoints or Helm rejects InferenceService resources."
metadata:
  type: component
tags:
  tech_stack: [helm, openshift, olm, scc, rbac, postgresql, keycloak]
  ai_pattern: [guardrails]
  platform: [openshift, kubeai, kserve]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "OLM-managed F5 AI Security Operator with multi-namespace deployment, SCC anyuid bindings, and inference GPU tolerations"
    approach: "A"
---

# F5 AI Security

## Overview

F5 AI Security is a Helm chart that installs the F5 AI Security Operator (CalypsoAI) on OpenShift via OLM, then creates a `SecurityOperator` custom resource that reconciles the full product stack: Moderator UI/API with PostgreSQL, Prefect workflow orchestration, and a KubeAI-based inference layer for guardrail scanning and red-team model serving. The chart handles the OpenShift-specific concerns that the operator itself cannot manage -- SCC bindings, cluster-scoped RBAC, OpenShift Routes, and a pre-applied inference SCC -- making it deployable via a single `make install-f5-ai-security` target.

## Tech Stack & Dependencies

- **Runtime:** Helm chart (v0.1.0) wrapping OLM Subscription + SecurityOperator CR
- **Container image:** Operator and product images pulled from `harbor.calypsoai.app` (authenticated registry)
- **Key dependencies:** OLM (Operator Lifecycle Manager), KServe CRDs (InferenceService, ServingRuntime), NVIDIA GPU Operator, Node Feature Discovery Operator
- **Helm subchart:** Standalone chart at `deploy/helm/f5-ai-security/` (not an ai-architecture-charts subchart)
- **Product namespaces:** `f5-ai-sec` (operator), `cai-moderator` (Moderator + PostgreSQL), `prefect` (workflow orchestration), `f5-ai-sec-inference` (GPU inference)

## Key Patterns

### OLM Subscription via Helm

The chart creates an OLM `Subscription` for the F5 AI Security Operator from the `certified-operators` catalog. The operator requires `AllNamespaces` install mode, so the `OperatorGroup` spec is left empty.

```yaml
# templates/10-operator-group.yaml
{{- if .Values.operator.operatorGroupAllNamespaces }}
spec: {}
{{- else }}
spec:
  targetNamespaces:
    - {{ .Values.productNamespaces.operator }}
{{- end }}
```

The `startingCSV` pins the operator version (e.g., `f5-ai-security-operator.v0.8.1`). The Makefile waits for the CSV to reach `Succeeded` status after the Helm install.

### Two-Pass Helm Install for CRD Availability

The `SecurityOperator` CR depends on a CRD that only exists after the OLM operator installs successfully. The chart uses a live `lookup` function instead of `.Capabilities.APIVersions` because Helm often omits newly registered API groups on upgrade.

```yaml
# templates/40-security-operator.yaml
{{- $crdName := "securityoperators.ai.security.f5.com" }}
{{- $crd := lookup "apiextensions.k8s.io/v1" "CustomResourceDefinition" "" $crdName }}
{{- if or (not .Values.securityOperator.waitForCrd) $crd }}
```

The Makefile handles this with a two-pass install: first pass creates the Subscription (CRD not yet available, so the SecurityOperator manifest is skipped), waits for the CSV to succeed, then re-runs `helm upgrade --install` so the SecurityOperator CR is now rendered.

### Multi-Namespace SCC anyuid Bindings

The operator's product pods (Moderator, Prefect, inference) require `anyuid` SCC on OpenShift. The chart iterates over a list of namespace/service-account pairs, creating `RoleBinding` resources to `system:openshift:scc:anyuid`.

```yaml
# templates/50-scc-anyuid-bindings.yaml
{{- $pairs := list
  (dict "namespace" $m "serviceAccount" "cai-moderator-sa")
  (dict "namespace" $m "serviceAccount" "default")
  (dict "namespace" $p "serviceAccount" "default")
  (dict "namespace" $p "serviceAccount" "prefect-server")
  (dict "namespace" $p "serviceAccount" "prefect-worker")
  (dict "namespace" $i "serviceAccount" "f5-ai-sec-inference")
  (dict "namespace" $i "serviceAccount" "f5-ai-sec-inference-models")
}}
```

### Pre-Applied Inference SCC for KubeAI Model Pods

KubeAI model pods run as root, which `restricted-v2` blocks. The F5 inference Helm chart normally creates a custom SCC, but the operator ServiceAccount cannot create `SecurityContextConstraints`. The Makefile pre-applies the SCC with placeholder substitution before the SecurityOperator reconciles inference.

```yaml
# extras/openshift-inference-models-scc.yaml
kind: SecurityContextConstraints
metadata:
  name: f5-ai-sec-inference-models
  annotations:
    meta.helm.sh/release-name: __F5_INFERENCE_HELM_RELEASE_NAME__
    meta.helm.sh/release-namespace: __F5_INFERENCE_HELM_RELEASE_NAMESPACE__
runAsUser:
  type: RunAsAny
requiredDropCapabilities:
  - ALL
```

The Helm ownership annotations must match the operator-managed release name, or Helm fails with "exists and cannot be imported into the current release".

### KubeAI GPU Tolerations Merge

OpenShift GPU nodes often use taint `nvidia.com/gpu=true`, but some F5 KubeAI resource profiles omit tolerations or use `value=present`. The chart merges correct tolerations into the inference Helm values.

```yaml
# templates/40-security-operator.yaml (inference section)
{{- if .Values.securityOperator.inference.kubeaiGpuTolerations.enabled }}
kubeai:
  resourceProfiles:
    nvidia-gpu-a10g:
      tolerations:
        - effect: NoSchedule
          key: nvidia.com/gpu
          operator: Exists
    nvidia-gpu-l40s:
      tolerations:
        - effect: NoSchedule
          key: nvidia.com/gpu
          operator: Exists
{{- end }}
```

### Controller-Manager RBAC Escalation

The operator SA needs permissions beyond what the OLM CSV grants: `pods/status` for delegated Role escalation, `batch` resources for jobManager Helm, and patch/update on the pre-created inference SCC.

```yaml
# templates/56-controller-manager-rbac.yaml
rules:
  - apiGroups: [""]
    resources: ["pods/status"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["batch"]
    resources: ["cronjobs", "jobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["security.openshift.io"]
    resources: ["securitycontextconstraints"]
    resourceNames:
      - {{ .Values.controllerManagerRbac.inferenceModelsSccName | quote }}
    verbs: ["patch", "update"]
```

### Moderator Route Auto-Discovery

The Makefile auto-derives the Moderator public URL from the cluster ingress domain using a configurable prefix (default `aisec`):

```makefile
# deploy/helm/Makefile
HOST="$$PREFIX.$$DOMAIN";
AUTO_HOST="--set-string routes.hostname=$$HOST \
  --set-string securityOperator.moderator.baseUrl=https://$$HOST";
```

Two OpenShift Routes are created: `/` (port 5500 for the UI) and `/auth` (port 8080 for Keycloak). Missing the `/auth` route causes a blank/black Moderator UI page.

## Configuration

- **Environment variables:** `DOCKER_USERNAME`, `DOCKER_PASSWORD`, `DOCKER_EMAIL` (Harbor registry creds), `F5_LICENSE` (base64 license blob), `MODERATOR_BASE_URL`, `ROUTES_HOSTNAME` -- all passable via Makefile environment or `--set-string` overrides
- **Config files:** `f5-ai-security-values.yaml` (user overlay, gitignored; created from `f5-ai-security-values.yaml.example`). Requires registry credentials and F5 license at minimum
- **Helm values:** `productNamespaces.{operator,moderator,prefect,inference}` for namespace placement; `operator.startingCSV` for version pinning; `securityOperator.waitForCrd` for CRD gating; `routes.hostname` and `securityOperator.moderator.baseUrl` for public access; `securityOperator.inference.kubeaiGpuTolerations.enabled` for GPU scheduling fixes

## Known Gotchas

- **Two-pass Helm install is required:** The SecurityOperator CRD is not available until the OLM operator CSV reaches `Succeeded`. A single `helm install` silently skips the SecurityOperator manifest. The Makefile addresses this by running `helm upgrade --install` twice with a CRD wait loop in between (comment in `templates/40-security-operator.yaml`).
- **Helm `lookup` vs `.Capabilities.APIVersions`:** The chart uses `lookup` for CRD detection because `.Capabilities.APIVersions` often omits newly registered API groups on `helm upgrade` (comment in `templates/40-security-operator.yaml`).
- **Inference SCC ownership mismatch:** The pre-applied SCC must have `meta.helm.sh/release-name` and `meta.helm.sh/release-namespace` matching the operator's inference Helm release, or Helm fails with an import error (comment in `extras/openshift-inference-models-scc.yaml`).
- **controller-manager OOMKilled:** Default 128Mi memory limit is insufficient; patching to 512Mi/256Mi is a documented workaround (`docs/troubleshooting.md` Fix 5).
- **"Invalid License" after reinstall:** Encrypted tables (`setting`, `secret`, `secret_config`) hold data encrypted with the old `CAI_MODERATOR_ENCRYPTION_KEY`. Clearing them and restarting the Moderator is required (`docs/troubleshooting.md` Fix 6).
- **"Invalid License" with stale license in DB:** Once a license value exists in the DB, it takes precedence over the YAML `CAI_MODERATOR_DEFAULT_LICENSE` default. Must be updated via API or direct DB update (`docs/troubleshooting.md` Fix 9).
- **Helm retry loop for namespace/API races:** First install on cold clusters can race between namespace creation and resource creation. The Makefile retries up to `F5_HELM_MAX_ATTEMPTS` (default 8) with `F5_HELM_RETRY_SLEEP` (default 6s) between attempts.
- **KServe webhook endpoints required:** CRDs alone are not enough; the KServe webhook service must have backing pod endpoints, otherwise `helm install` rejects InferenceService/ServingRuntime resources. The Makefile waits up to `KSERVE_WEBHOOK_WAIT_SECONDS` (default 300s).
- **Missing `/auth` route causes blank UI:** The Moderator UI requires both the root route (port 5500) and the `/auth` route (port 8080 for Keycloak) to function (`docs/troubleshooting.md` symptom 3).

## Testing Notes

- Validate both charts before install: `make validate` runs `helm lint` and `helm template --dry-run` for both the RAG chart and the F5 AI Security chart
- Run `make validate-infra` on fresh clusters to check oc login, ingress domain, KServe CRDs + webhook endpoints, Helm `--take-ownership` support, and optional GPU node presence
- After install, verify: `oc get csv -n f5-ai-sec | grep f5-ai-security` shows `Succeeded`; `oc get securityoperator -n cai-moderator` shows the CR; pods in all four product namespaces are Running
- Check `make print-moderator-host` to confirm the auto-derived Moderator URL before install

## Related Patterns

- `components/gpu-operator.md` -- NVIDIA GPU Operator prerequisite for inference nodes
- `components/llamastack.md` -- LlamaStack integration endpoint for guardrails proxy
