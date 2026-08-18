---
name: makefile-two-phase-helm-crd-wait-scc-preapply
description: Two-phase Helm install with retry loops, CRD registration polling, and sed-based SCC pre-application
summary: "Solves the OLM operator chicken-and-egg problem where Helm cannot render a custom resource until the operator registers its CRD, using a two-phase Makefile target that first installs Subscription/OperatorGroup/RBAC with retry loops (the chart's `lookup` guard skips CR templates when the CRD is absent), then re-applies after CRD registration to render the CR. Use when deploying an OLM-managed operator (e.g., SecurityOperator) whose CR depends on CRD existence and the operator SA lacks permission to create cluster-scoped SCCs — the pattern handles CRD polling, sed-based SCC pre-application with namespace/release placeholders, auto-derived route hostnames from cluster ingress domain, and CI-driven env vars (DOCKER_USERNAME, F5_LICENSE) in a single target. Critical config: `F5_HELM_MAX_ATTEMPTS` (default 8) and `F5_HELM_RETRY_SLEEP` (default 6s) control first-pass retries, CRD poll runs 60x2s=120s, `--take-ownership` requires Helm 3.13+ (validated by `validate-infra` target), sed substitutes `__F5_INFERENCE_NAMESPACE__`/`__F5_INFERENCE_HELM_RELEASE_NAME__` in the SCC YAML before `oc apply` (requires cluster-admin and checks for `restricted-v2` SCC existence). CRD poll uses a soft 120s warning (not hard failure) since the second Helm install re-skips the CR if CRD is absent; `SKIP_F5_INFERENCE_SCC` and `SKIP_F5_OPERATOR_WAIT` bypass SCC/CSV steps; `F5_INFERENCE_PENDING_POD_DELETE` optionally deletes Pending KubeAI pods from GPU scheduling races."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [guardrails]
  platform: [openshift]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "install-f5-ai-security target with retry loop, CSV wait, CRD polling, SCC pre-apply, second Helm apply"
    approach: "A"
---

# Two-Phase Helm Install with CRD Wait and SCC Pre-Apply

## Overview

This pattern addresses the chicken-and-egg problem of deploying an OLM operator via Helm when the operator's custom resource cannot be rendered until the operator registers its CRD. The Makefile target performs a first Helm install (to deploy Subscription and OperatorGroup), waits for the CRD to appear, pre-applies a cluster-scoped SCC, then performs a second Helm install to render the custom resource.

## Pattern Description

The `install-f5-ai-security` Makefile target orchestrates a multi-step deployment with error recovery: (1) first Helm install with retry loop for namespace/API races on cold clusters, (2) optional `oc wait` for CSV Succeeded, (3) polling loop until the SecurityOperator CRD is registered, (4) `sed`-based substitution and `oc apply` of a pre-created SCC file, (5) second Helm install to render the SecurityOperator CR now that the CRD exists. Each Helm install phase has its own retry mechanism.

## Implementation

### First Helm Install with Retry

The first install deploys namespaces, Subscription, OperatorGroup, SCC bindings, and RBAC. Retries handle namespace and API races on fresh clusters:

```makefile
# deploy/helm/Makefile (install-f5-ai-security, lines 653-668)
ATTEMPT=1; \
while [ $$ATTEMPT -le $(F5_HELM_MAX_ATTEMPTS) ]; do \
    if helm upgrade --install $(F5_AI_SECURITY_RELEASE) $(F5_AI_SECURITY_CHART) \
        -n $(F5_AI_SECURITY_NAMESPACE) --create-namespace \
        $(F5_HELM_FLAGS) \
        -f "$(F5_AI_SECURITY_VALUES)" $$HELM_EXTRAS; then \
        break; \
    fi; \
    if [ $$ATTEMPT -eq $(F5_HELM_MAX_ATTEMPTS) ]; then \
        echo "Helm install failed after $(F5_HELM_MAX_ATTEMPTS) attempts."; \
        exit 1; \
    fi; \
    ATTEMPT=$$((ATTEMPT + 1)); \
    sleep $(F5_HELM_RETRY_SLEEP); \
done;
```

### CSV Wait and CRD Polling

After the first install, the target waits for the OLM CSV to reach Succeeded (best-effort, not fatal), then polls for the CRD:

```makefile
# deploy/helm/Makefile (CRD polling, lines 676-688)
oc wait "csv/$(OPERATOR_CSV)" -n "$(F5_AI_SECURITY_NAMESPACE)" \
    --for=jsonpath='{.status.phase}'=Succeeded --timeout=600s 2>/dev/null \
    || echo "CSV not Succeeded yet; check: oc get csv -n $(F5_AI_SECURITY_NAMESPACE)"; \
W=0; \
while [ $$W -lt 60 ]; do \
    if oc get crd securityoperators.ai.security.f5.com >/dev/null 2>&1; then \
        echo "CRD securityoperators.ai.security.f5.com is present"; \
        break; \
    fi; \
    W=$$((W+1)); \
    sleep 2; \
done;
```

### SCC Pre-Application with sed Substitution

The operator SA cannot create SecurityContextConstraints, so the Makefile pre-applies the SCC with Helm ownership annotations (using sed placeholders) before the second Helm install:

```makefile
# deploy/helm/Makefile (SCC pre-apply, lines 689-699)
if [ "$(SKIP_F5_INFERENCE_SCC)" != "1" ] && oc get scc restricted-v2 >/dev/null 2>&1; then \
    INFER_SCC="$(CURDIR)/$(F5_AI_SECURITY_CHART)/extras/openshift-inference-models-scc.yaml"; \
    sed -e "s|__F5_INFERENCE_NAMESPACE__|$(F5_INFERENCE_NS)|g" \
        -e "s|__F5_INFERENCE_HELM_RELEASE_NAME__|$(F5_INFERENCE_HELM_RELEASE)|g" \
        -e "s|__F5_INFERENCE_HELM_RELEASE_NAMESPACE__|$(F5_INFERENCE_NS)|g" \
        "$$INFER_SCC" | oc apply -f -; \
fi;
```

### Second Helm Install

Re-applies the chart so the SecurityOperator CR template is rendered now that the CRD is registered:

```makefile
# deploy/helm/Makefile (second Helm apply, lines 701-717)
R2=1; \
while [ $$R2 -le 5 ]; do \
    if helm upgrade --install $(F5_AI_SECURITY_RELEASE) $(F5_AI_SECURITY_CHART) \
        -n $(F5_AI_SECURITY_NAMESPACE) --create-namespace \
        $(F5_HELM_FLAGS) \
        -f "$(F5_AI_SECURITY_VALUES)" $$HELM_EXTRAS; then \
        break; \
    fi; \
    R2=$$((R2 + 1)); \
    sleep $(F5_HELM_RETRY_SLEEP); \
done;
```

### Auto-Derived Moderator URL

The target auto-derives the Moderator hostname from the cluster's ingress domain if `MODERATOR_HOST_AUTO` is true:

```makefile
# deploy/helm/Makefile (auto-host, lines 630-643)
DOMAIN=$$(oc get ingress.config cluster -o jsonpath='{.spec.domain}' 2>/dev/null); \
HOST="$$PREFIX.$$DOMAIN"; \
AUTO_HOST="--set-string routes.hostname=$$HOST \
           --set-string securityOperator.moderator.baseUrl=https://$$HOST";
```

## Configuration

- **Key settings:** `F5_HELM_MAX_ATTEMPTS` (default 8) and `F5_HELM_RETRY_SLEEP` (default 6s) control first-pass retries; `SKIP_F5_INFERENCE_SCC` skips the SCC pre-apply; `SKIP_F5_OPERATOR_WAIT` skips CSV wait; `F5_HELM_FLAGS` defaults to `--take-ownership` (Helm 3.13+)
- **Defaults:** CRD poll runs up to 120s (60 iterations x 2s); CSV wait timeout is 600s; second Helm apply retries up to 5 times
- **Dependencies:** Requires Helm 3.13+ for `--take-ownership`; cluster-admin for `oc apply` on SCC; OLM must be installed

## Gotchas

- The `--take-ownership` flag (Helm 3.13+) is needed because `--create-namespace` plus chart Namespace manifests can race; the Makefile's `validate-infra` target explicitly checks for this Helm version support (see `deploy/helm/Makefile` lines 317-320)
- The first Helm install intentionally skips the SecurityOperator CR (via the chart's `lookup` guard) -- this is by design, not an error
- The CRD poll has a hard 120s timeout with a soft warning ("CRD not visible after 120s; continuing") rather than a hard failure, because the second Helm install will simply skip the CR template again if the CRD still is not registered
- The `F5_INFERENCE_PENDING_POD_DELETE` flag (default 0) provides an optional post-install step that deletes Pending KubeAI model pods after a configurable wait, working around transient "Insufficient cpu/gpu" scheduling races (see `deploy/helm/Makefile` lines 718-728)
- Environment variables (`DOCKER_USERNAME`, `DOCKER_PASSWORD`, `F5_LICENSE`, etc.) are conditionally assembled into `--set-string` flags, enabling both interactive and CI-driven installation flows

## Related Patterns

- `helm-olm-subscription-crd-lookup-securityoperator.md` -- the Helm chart that uses the `lookup` function this Makefile orchestrates around
- `helm-scc-pre-apply-sed-placeholder-adoption.md` -- the SCC file with placeholders that this target substitutes and applies
- `helm-dual-chart-rag-umbrella-vendor-operator.md` -- the dual-chart architecture this Makefile sequences
