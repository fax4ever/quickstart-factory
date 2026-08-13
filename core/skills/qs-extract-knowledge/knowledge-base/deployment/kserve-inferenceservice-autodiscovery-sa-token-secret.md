---
name: kserve-inferenceservice-autodiscovery-sa-token-secret
description: Shell script discovering KServe Granite model from shared namespace and generating OpenAI-compatible secret with SA token authentication
summary: "Autodiscovers a KServe/vLLM InferenceService by name pattern (`grep granite | head -1`) in a shared namespace and generates an OpenAI-compatible Kubernetes secret with ephemeral SA token authentication, avoiding hardcoded model endpoints and long-lived credentials. Use when applications need to connect to shared model serving in `sandbox-shared-models` without manual endpoint configuration -- runs as Step 8 in the phased deploy chain, overwriting the static placeholder secret from Step 1 via idempotent `--dry-run=client -o yaml | oc apply -f -`. Critical implementation: `oc create token default --duration=120h` provides the SA token as OPENAI_API_KEY, cluster-internal URL pattern `https://<model>-predictor.<namespace>.svc.cluster.local:8443/v1` as OPENAI_BASE_URL, and the discovered model name as OPENAI_MODEL. Gotchas: token expires after 120 hours (5 days) requiring secret regeneration, `head -1` arbitrarily selects among multiple Granite models, `default` SA must have token-create permission, and HTTPS port 8443 requires the OpenShift service CA truststore configured in calling components."
metadata:
  type: deployment-pattern
tags:
  tech_stack: []
  ai_pattern: [model-serving]
  platform: [openshift, kserve, vllm]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "create.sh Step 8 discovers a Granite InferenceService in sandbox-shared-models namespace, creates a 120h SA token, and generates an openai secret with cluster-internal HTTPS URL"
    approach: "A"
---

# KServe InferenceService Autodiscovery with SA Token Secret

## Overview

A deployment pattern where the install script dynamically discovers a KServe InferenceService by name pattern in a shared namespace, extracts the model name, creates a short-lived service account token, and generates a Kubernetes Secret with OpenAI-compatible credentials. This allows the application to connect to a shared model serving endpoint without hardcoding model names or managing long-lived credentials.

## Pattern Description

The quickstart's application components need to call a Granite LLM served via KServe/vLLM in a shared namespace (`sandbox-shared-models`). Rather than requiring the user to manually configure the model endpoint, the install script discovers the InferenceService by querying for resources whose name contains "granite", constructs the cluster-internal HTTPS URL using the predictor service DNS name, and generates an ephemeral service account token for authentication. The resulting secret follows the OpenAI API convention (API key, base URL, model name).

## Implementation

### Model Discovery via oc get inferenceservice

```bash
# create.sh - Step 8: Configure OpenAI credentials
MODEL_NAME=$(oc get inferenceservice -n sandbox-shared-models \
  -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | grep granite | head -1)
if [ -z "${MODEL_NAME}" ]; then
  echo "ERROR: No Granite model found in sandbox-shared-models namespace"
  exit 1
fi
echo "Using model: ${MODEL_NAME}"
```

### SA Token Generation

A service account token with a 120-hour (5-day) duration is created for authentication:

```bash
# create.sh - Step 8
SA_TOKEN=$(oc create token default --duration=120h)
```

### OpenAI-Compatible Secret Generation

The secret is created with cluster-internal HTTPS URL following the `<model>-predictor.<namespace>.svc.cluster.local:8443/v1` pattern:

```bash
# create.sh - Step 8
oc create secret generic openai \
  --from-literal=OPENAI_API_KEY="${SA_TOKEN}" \
  --from-literal=OPENAI_BASE_URL="https://${MODEL_NAME}-predictor.sandbox-shared-models.svc.cluster.local:8443/v1" \
  --from-literal=OPENAI_MODEL="${MODEL_NAME}" \
  --dry-run=client -o yaml | oc apply -f -
```

### Fallback Static Secret

A static placeholder secret also exists in the repo for reference, with the expected structure:

```yaml
# deploy/resources/secrets/openai.yaml
apiVersion: v1
kind: Secret
metadata:
  name: openai
type: Opaque
stringData:
  OPENAI_API_KEY: "dummy"
  OPENAI_BASE_URL: https://isvc-granite-31-8b-fp8-predictor.sandbox-shared-models.svc.cluster.local:8443/v1
  OPENAI_MODEL: isvc-granite-31-8b-fp8
```

## Configuration

- **Key settings:** The shared namespace is hardcoded as `sandbox-shared-models`; the model name is filtered by `grep granite`; the SA token duration is 120 hours; the predictor port is 8443 (HTTPS)
- **Defaults:** The static secret in `deploy/resources/secrets/openai.yaml` provides fallback values pointing to `isvc-granite-31-8b-fp8`
- **Dependencies:** A KServe InferenceService with "granite" in its name must exist in the `sandbox-shared-models` namespace; the `default` service account must have permission to create tokens; the service CA truststore pattern must be in place for HTTPS calls

## Gotchas

- The `grep granite | head -1` approach selects the first Granite model found -- if multiple Granite models exist in the shared namespace, it picks arbitrarily; the install script does not let the user choose
- The SA token expires after 120 hours -- the application will stop being able to authenticate to the model endpoint after 5 days unless the secret is regenerated
- The static secret file (`deploy/resources/secrets/openai.yaml`) is applied in Step 1 of `create.sh` but then overwritten by the dynamic secret generation in Step 8 -- the static file serves only as a structural reference and first-pass placeholder
- The cluster-internal URL uses HTTPS on port 8443, which requires the OpenShift service CA truststore to be configured in the calling component -- see the `helm-initcontainer-openshift-service-ca-jks-truststore.md` pattern

## Related Patterns

- `helm-initcontainer-openshift-service-ca-jks-truststore.md` -- enables the TLS connection to the model endpoint
- `shell-script-phased-infra-helm-tekton-deploy-chain.md` -- the parent orchestration running this as Step 8
