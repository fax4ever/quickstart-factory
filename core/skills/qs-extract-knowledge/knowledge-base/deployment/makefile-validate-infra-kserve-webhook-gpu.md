---
name: makefile-validate-infra-kserve-webhook-gpu
description: Makefile preflight target validating oc login, KServe CRDs, webhook endpoints, Helm version, and GPU availability
summary: "Implements a Makefile validate-infra preflight target that sequentially checks oc login, OpenShift ingress domain, KServe CRDs (inferenceservices.serving.kserve.io, servingruntimes.serving.kserve.io), webhook endpoint readiness via polling, Helm 3.13+ compatibility, GPU node availability, and F5 values file before deploying a KServe-based quickstart. Use as a prerequisite gate before helm install on RHOAI/OpenShift clusters where KServe admission webhooks may not be ready despite CRDs being registered; skip via SKIP_INFRA_CHECK=1 for known-good clusters, set REQUIRE_GPU=1 to make GPU checks fatal, or set SKIP_F5_GUARDRAILS for RAG-only deployments without F5 configuration. Key configurables: KSERVE_WEBHOOK_NAMESPACE (default redhat-ods-applications), KSERVE_WEBHOOK_SERVICE (default kserve-webhook-server-service), KSERVE_WEBHOOK_WAIT_SECONDS (default 300, 0 for single check); Helm version probed via --take-ownership flag in help output; GPU checked via oc get nodes jsonpath on nvidia.com/gpu allocatable. Webhook endpoint polling is essential because KServe CRDs registered via OperatorHub before controller pods are ready cause Helm to fail with \"connection refused\" or \"no endpoints available\" on the admission webhook; the ingress domain uses OpenShift-specific ingress.config API unavailable on vanilla Kubernetes, and webhook namespace/service defaults are RHOAI-specific."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [model-serving]
  platform: [kserve, vllm, rhoai, openshift]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "validate-infra target checks oc login, ingress domain, KServe CRDs, webhook endpoint polling, Helm 3.13+, GPU nodes, F5 values file"
    approach: "A"
---

# Makefile Preflight Validation for KServe, Webhooks, and GPU

## Overview

This pattern implements a comprehensive cluster preflight validation target (`validate-infra`) in a Makefile that checks multiple infrastructure prerequisites before deploying a quickstart. The validation covers OpenShift authentication, ingress domain, KServe CRD presence, webhook endpoint readiness (with polling), Helm version compatibility, GPU node availability, and values file existence.

## Pattern Description

The `validate-infra` target runs before `install` (unless `SKIP_INFRA_CHECK=1`) and performs a sequential chain of checks, each with specific error handling. The most distinctive aspect is the KServe webhook endpoint polling loop: KServe CRDs may exist but the webhook Service may have no backing pods yet, causing `helm install` to fail when the admission webhook rejects InferenceService or ServingRuntime resources with "no endpoints available." The target polls the webhook service's endpoints until they appear or a timeout is reached.

## Implementation

### KServe CRD and Webhook Endpoint Validation

```makefile
# deploy/helm/Makefile (validate-infra, lines 289-316)
for crd in inferenceservices.serving.kserve.io \
           servingruntimes.serving.kserve.io; do \
    if ! oc get crd "$$crd" >/dev/null 2>&1; then \
        echo "Missing CRD $$crd (install OpenShift AI / model serving / KServe first)."; \
        exit 1; \
    fi; \
done; \
KWMAX=$(KSERVE_WEBHOOK_WAIT_SECONDS); KWSTEP=10; KWELAPSED=0; \
while true; do \
    EP=$$(oc get endpoints "$$KWSVC" -n "$$KWNNS" \
        -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null || true); \
    if [ -n "$$EP" ]; then \
        echo "KServe webhook service has endpoints"; \
        break; \
    fi; \
    if [ "$$KWELAPSED" -ge "$$KWMAX" ]; then \
        echo "No endpoints for $$KWNNS/$$KWSVC after $$KWMAX s"; \
        exit 1; \
    fi; \
    sleep $$KWSTEP; \
    KWELAPSED=$$((KWELAPSED + KWSTEP)); \
done;
```

### Helm Version Check

```makefile
# deploy/helm/Makefile (validate-infra, lines 317-320)
if ! helm upgrade --help 2>/dev/null | grep -q -- '--take-ownership'; then \
    echo "Helm does not support --take-ownership (need Helm 3.13+)."; \
    exit 1; \
fi;
```

### GPU Availability Check

The GPU check is configurable: warning only by default, fatal if `REQUIRE_GPU=1`:

```makefile
# deploy/helm/Makefile (validate-infra, lines 322-331)
GPU_LINES=$$(oc get nodes -o jsonpath=\
  '{range .items[*]}{.status.allocatable.nvidia\.com/gpu}{"\n"}{end}' \
  2>/dev/null | grep -E '^[1-9]' || true); \
if [ -z "$$GPU_LINES" ]; then \
    if [ "$(REQUIRE_GPU)" = "1" ]; then \
        echo "No node with allocatable nvidia.com/gpu"; \
        exit 1; \
    else \
        echo "No allocatable nvidia.com/gpu yet — GPU model pods may stay Pending"; \
    fi; \
fi;
```

## Configuration

- **Key settings:** `KSERVE_WEBHOOK_NAMESPACE` (default `redhat-ods-applications`), `KSERVE_WEBHOOK_SERVICE` (default `kserve-webhook-server-service`), `KSERVE_WEBHOOK_WAIT_SECONDS` (default 300; 0 = one check only)
- **Defaults:** `REQUIRE_GPU=0` (warn only); `SKIP_INFRA_CHECK=0` (validate-infra runs before install)
- **Dependencies:** Requires `oc` and `helm` CLI tools; user must be logged in to OpenShift

## Gotchas

- The KServe webhook check targets the `kserve-webhook-server-service` in `redhat-ods-applications` namespace, which is RHOAI-specific -- vanilla KServe installations may use a different namespace/service name
- The webhook endpoint polling is necessary because KServe CRDs can be registered (via OperatorHub) before the KServe controller pods are ready, causing Helm to succeed at rendering InferenceService YAML but fail when the admission webhook rejects it with "connection refused" or "no endpoints available"
- The F5 values file check is skipped when `SKIP_F5_GUARDRAILS` is set, allowing RAG-only deployment without F5 configuration
- The ingress domain is extracted via `oc get ingress.config cluster -o jsonpath='{.spec.domain}'` -- this is an OpenShift-specific API path that does not exist on vanilla Kubernetes

## Related Patterns

- `makefile-two-phase-helm-crd-wait-scc-preapply.md` -- the install target that depends on validate-infra passing
- `helm-dual-chart-rag-umbrella-vendor-operator.md` -- the deployment architecture this preflight validates
