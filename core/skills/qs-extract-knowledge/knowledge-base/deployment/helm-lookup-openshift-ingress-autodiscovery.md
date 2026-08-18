---
name: helm-lookup-openshift-ingress-autodiscovery
description: Helm lookup function querying IngressController to auto-detect cluster domain at template time
summary: "Solves automatic cluster application domain discovery in OpenShift Helm charts by querying cluster resources via Helm's `lookup` function in named helper templates, eliminating manual domain entry in `values.yaml`. Approach A (`app_domain`) queries `IngressController/default` in `openshift-ingress-operator` for `.status.domain` and works with custom console hostnames; Approach B (`keycloak.clusterDomain`) queries `Route/console` in `openshift-console` and strips the `console-openshift-console.` prefix via `regexReplaceAll` — choose B when RBAC restricts IngressController access or when constructing Route-based service URLs (issuerUrl, redirectUri). Both approaches require no chart configuration but need read RBAC on their respective namespaces (`openshift-ingress-operator` for A, `openshift-console` for B), and both fail during `helm template` dry-run since `lookup` returns empty, triggering fallbacks (`example.com` for A, `apps.cluster.local` for B). Approach A calls `lookup` twice in its `define` block because variable assignment is unavailable in this pattern and may diverge from a separate `clusterdomainurl` value; Approach B assumes standard `console-openshift-console.` hostname prefix (breaks with custom console hostnames) and duplicates the helper across multiple subcharts independently."
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
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Identical app_domain helper template using lookup on IngressController, same fallback to example.com"
    approach: "A"
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Lookups the openshift-console Route instead of IngressController, extracts cluster domain via regexReplaceAll stripping console-openshift-console prefix, falls back to apps.cluster.local"
    approach: "B"
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

---

## Approach B: Console Route Lookup with Regex Domain Extraction (from peoplemesh)

### When to Use

Use this approach when the Helm service account does not have read access to `IngressController` resources in `openshift-ingress-operator` namespace, or when you need the cluster domain for constructing Route-based URLs (where the console route hostname reliably encodes the apps domain).

### Differences from Approach A

Approach A queries `operator.openshift.io/v1 IngressController` in `openshift-ingress-operator` and reads `.status.domain`. Approach B queries `route.openshift.io/v1 Route` in `openshift-console` namespace and strips the `console-openshift-console.` prefix from the hostname using regex. Both produce the same domain (e.g., `apps.cluster.example.com`) but from different source resources with different RBAC requirements.

### Implementation

```yaml
# charts/keycloak/templates/_helpers.tpl (and peoplemesh-umbrella/templates/_helpers.tpl)
{{- define "keycloak.clusterDomain" -}}
{{- $console := lookup "route.openshift.io/v1" "Route" "openshift-console" "console" }}
{{- if $console }}
{{- $host := $console.spec.host }}
{{- regexReplaceAll "^console-openshift-console\\." $host "" }}
{{- else }}
apps.cluster.local
{{- end }}
{{- end }}
```

The extracted domain is used to construct service URLs dynamically:

```yaml
# charts/keycloak/templates/_helpers.tpl
{{- define "keycloak.issuerUrl" -}}
{{- $clusterDomain := include "keycloak.clusterDomain" . }}
{{- $namespace := include "keycloak.namespace" . }}
{{- printf "https://%s-%s.%s/realms/%s" .Values.applicationName $namespace $clusterDomain .Values.realm.name }}
{{- end }}

{{- define "keycloak.peoplemeshRedirectUri" -}}
{{- $clusterDomain := include "keycloak.clusterDomain" . }}
{{- printf "https://peoplemesh-%s.%s/api/v1/auth/callback/keycloak" .Release.Namespace $clusterDomain }}
{{- end }}
```

### Gotchas

- The `regexReplaceAll "^console-openshift-console\\."` pattern assumes the standard OpenShift console route hostname format (`console-openshift-console.<apps-domain>`); clusters that customize the console hostname will produce incorrect cluster domains (see `charts/keycloak/templates/_helpers.tpl`)
- The fallback domain is `apps.cluster.local` (compared to `example.com` in Approach A); this produces resolvable-looking but non-functional URLs during `helm template` dry-run (see `charts/keycloak/templates/_helpers.tpl`)
- This pattern requires read access to Route resources in the `openshift-console` namespace, while Approach A requires read access to IngressController resources in `openshift-ingress-operator` -- the RBAC requirements are different (see the respective template files)
- The same clusterDomain helper is defined in multiple places (keycloak subchart, peoplemesh subchart, umbrella chart) -- each is independent and could produce different results if the lookup fails in some but not others (see `charts/keycloak/templates/_helpers.tpl`, `charts/peoplemesh/templates/_helpers.tpl`, `peoplemesh-umbrella/templates/_helpers.tpl`)

---

## Choosing Between Approaches

| Criteria | Approach A (IngressController) | Approach B (Console Route) |
|----------|-------------------------------|---------------------------|
| Source resource | `IngressController/default` in `openshift-ingress-operator` | `Route/console` in `openshift-console` |
| Data field | `.status.domain` | `.spec.host` with regex strip |
| Fallback | `example.com` | `apps.cluster.local` |
| RBAC needed | Read IngressController in `openshift-ingress-operator` | Read Route in `openshift-console` |
| Works with custom console hostname | Yes (reads actual domain, not derived) | No (assumes `console-openshift-console.` prefix) |
