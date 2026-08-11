---
name: helm-lookup-openshift-ingress-autodiscovery
description: Helm lookup function querying IngressController to auto-detect cluster domain at template time
summary: "Solves automatic cluster application domain discovery in OpenShift Helm charts by querying the IngressController via Helm's `lookup` function in a named `app_domain` helper template, eliminating manual domain entry in `values.yaml`. Use when the chart needs the cluster's app domain (e.g., `apps.cluster.example.com`) at install time without user input; not suitable for `helm template` dry-run since `lookup` requires a live cluster connection and always falls back to `example.com`. The helper queries `operator.openshift.io/v1 IngressController/default` in `openshift-ingress-operator` namespace via `(lookup ...).status.domain`, falling back to `example.com`; the Helm service account must have read access to IngressController resources in that namespace. The `lookup` call appears twice (if-check and print) because Helm `define` blocks lack variable assignment in this pattern, and the chart may have a separate `clusterdomainurl` value for workbench/tornado settings that diverges from the auto-detected domain."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Helper template uses lookup on IngressController to auto-detect app domain, falls back to example.com"
    approach: "A"
---

# Helm Lookup for OpenShift Ingress Domain Auto-Discovery

## Overview

This pattern uses the Helm `lookup` function in a helper template to query the OpenShift IngressController resource at install time, automatically extracting the cluster's application domain (e.g., `apps.cluster.example.com`). This eliminates the need for users to manually provide the cluster domain as a Helm value.

## Pattern Description

A named template in `_helpers.tpl` performs a Helm `lookup` against the `operator.openshift.io/v1 IngressController` resource named `default` in the `openshift-ingress-operator` namespace. If the resource exists (i.e., `helm install` is running against a live cluster), it extracts `.status.domain`. If the resource is not found (e.g., during `helm template` dry-run), it falls back to `example.com`.

## Implementation

### Helper Template with Lookup

```yaml
# helm/templates/_helpers.tpl
{{- define "app_domain" -}}
{{- if (lookup "operator.openshift.io/v1" "IngressController" "openshift-ingress-operator" "default") -}}
{{- print (lookup "operator.openshift.io/v1" "IngressController" "openshift-ingress-operator" "default").status.domain -}}
{{- else -}}
{{- print "example.com" -}}
{{- end -}}
{{- end -}}
```

## Configuration

- **Key settings:** No configuration required -- the domain is auto-detected from the cluster
- **Defaults:** Falls back to `example.com` when the IngressController is not accessible
- **Dependencies:** Requires the Helm service account (or the user running `helm install`) to have read access to `IngressController` resources in the `openshift-ingress-operator` namespace

## Gotchas

- The `lookup` function returns an empty result during `helm template` (dry-run) since there is no live cluster connection, so the template will always fall back to `example.com` in template-only mode (see `helm/templates/_helpers.tpl`)
- The lookup is performed twice in the template -- once for the `if` check and once for the `print` -- because Helm's `lookup` does not support variable assignment within the same `define` block in this pattern (see `helm/templates/_helpers.tpl`)
- This helper is defined but the chart also has a separate `clusterdomainurl` value in `values.yaml` (defaulting to `cluster.example.com`) used for the workbench tornado settings -- these two domain resolution mechanisms are independent and could produce different results (see `helm/values.yaml` vs `helm/templates/_helpers.tpl`)

## Related Patterns

- `helm-flat-chart-direct-crd-templating.md` -- the chart structure using this helper
- `kserve-multi-model-mig-gpu-slicing.md` -- another use of Helm `lookup` for ConfigMap existence guarding (different use case)
