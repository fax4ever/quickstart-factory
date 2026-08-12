---
name: helm-nemo-guardrails-trustyai-crd-nginx-maas-proxy
description: TrustyAI NemoGuardrails CRD with nginx HTTP-to-HTTPS proxy for MaaS LLM and vLLM content safety detector
summary: "Deploys NVIDIA NeMo Guardrails via TrustyAI operator's NemoGuardrails CRD with a ConfigMap defining regex detection (SSN, credit cards), sensitive data entities, and content safety flows backed by a NemoGuard 8B model on KServe RawDeployment (MIG GPU, vLLM args --gpu-memory-utilization=0.95 --max-model-len=4096 --enforce-eager). Use when LLM applications need input guardrails against a MaaS HTTPS endpoint that NeMo Guardrails cannot reach directly -- the nginx proxy (UBI nginx, ports 8081/8085) bridges HTTP-to-HTTPS with proxy_ssl_server_name and path rewriting for MaaS, routes content safety to the vLLM InferenceService; Helm values toggle the stack via nemoGuardrails.enabled, content safety deployment, and MaaS upstream/pathPrefix. Critical config: the NemoGuardrails CR references a ConfigMap with models pointing to proxy ports (openai_api_base: http://nemo-guardrails-proxy:8081/v1 for main LLM, base_url: http://nemo-guardrails-proxy:8085/v1 for content_safety detector), and a Secret auto-populates NEMO_GUARDRAILS_ENDPOINT to http://nemo-guardrails-internal:8000 keeping the API layer unaware of guardrails. Gotchas: nginx hardcodes OpenShift DNS resolver 172.30.0.10 (fails on non-OpenShift K8s), RawDeployment mode means predictor DNS is content-safety-detector-predictor not Knative revision format, Helm templates must use {{ \"{{\" }} escaping for Jinja2 variables in content safety prompts, and nginx writes to /tmp/*_temp for non-root OpenShift restricted SCC compliance."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, nginx, vllm]
  ai_pattern: [guardrails, model-serving]
  platform: [openshift, rhoai, kserve]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "TrustyAI NemoGuardrails CRD + content safety vLLM InferenceService + nginx proxy for MaaS HTTP->HTTPS bridge and content safety routing"
    approach: "A"
---

# NeMo Guardrails via TrustyAI CRD with Nginx MaaS Proxy

## Overview

This pattern deploys NVIDIA NeMo Guardrails using the TrustyAI operator's `NemoGuardrails` CRD, with an nginx reverse proxy to bridge HTTP-only NeMo Guardrails to HTTPS MaaS LLM endpoints and route traffic to a vLLM-served content safety detector model. It solves the problem of NeMo Guardrails requiring HTTP endpoints while production LLM services (like MaaS) only expose HTTPS.

## Pattern Description

The deployment consists of three coordinated resources: (1) a `NemoGuardrails` CR that creates the guardrails server with a ConfigMap-based config defining regex patterns, sensitive data detection, and content safety flows; (2) an optional `InferenceService` deploying a NemoGuard 8B content safety detector model via vLLM with MIG GPU support; and (3) an nginx proxy deployment that sits between NeMo Guardrails and the upstream LLM services, performing HTTP-to-HTTPS bridging with path rewriting for MaaS endpoints and routing content safety requests to the vLLM InferenceService.

## Implementation

### NemoGuardrails CRD with ConfigMap

The TrustyAI operator manages the NeMo Guardrails instance. Configuration is supplied via a ConfigMap referenced in the CR:

```yaml
# deploy/helm/mortgage-ai/templates/nemo-guardrails.yaml
apiVersion: trustyai.opendatahub.io/v1alpha1
kind: NemoGuardrails
metadata:
  name: nemo-guardrails
  annotations:
    security.opendatahub.io/enable-auth: 'false'
spec:
  nemoConfigs:
    - name: nemo-guardrails-config
      configMaps:
        - nemo-guardrails-config
  env:
    - name: "OPENAI_API_KEY"
      valueFrom:
        secretKeyRef:
          name: "nemo-guardrails-api-key"
          key: "token"
```

### ConfigMap with Regex and Content Safety Rails

The config defines both regex-based pattern detection and model-based content safety flows:

```yaml
# deploy/helm/mortgage-ai/templates/nemo-guardrails-config.yaml (data excerpt)
models:
  - type: main
    engine: openai
    parameters:
      openai_api_base: "http://nemo-guardrails-proxy:8081/v1"
      model_name: {{ .Values.nemoGuardrails.llm.modelName }}
  - type: "content_safety"
    engine: nim
    parameters:
      base_url: "http://nemo-guardrails-proxy:8085/v1"
      model_name: "content-safety-detector"
rails:
  config:
    regex_detection:
      input:
        patterns:
          - "\\d{3}-\\d{2}-\\d{4}"        # SSN
          - "\\d{4}[- ]?\\d{4}[- ]?\\d{4}[- ]?\\d{4}"  # Credit card
        case_insensitive: true
    sensitive_data_detection:
      input:
        entities: [CREDIT_CARD, US_SSN, EMAIL_ADDRESS, PHONE_NUMBER]
  input:
    flows:
      - detect sensitive data on input
      - regex check input
      - content safety check input $model=content_safety
```

### Nginx Proxy for HTTP-to-HTTPS Bridging

The proxy provides two virtual servers -- one for the MaaS LLM endpoint (port 8081) and one for the content safety detector (port 8085):

```yaml
# deploy/helm/mortgage-ai/templates/nemo-guardrails-proxy.yaml (ConfigMap excerpt)
http {
  resolver 172.30.0.10 valid=30s;
  # HTTP->HTTPS proxy for MaaS LLM endpoint
  server {
    listen 8081;
    location / {
      set $upstream {{ .Values.nemoGuardrails.proxy.maas.upstream }};
      rewrite ^/v1/(.*)$ /{{ .Values.nemoGuardrails.proxy.maas.pathPrefix }}/v1/$1 break;
      proxy_pass $upstream;
      proxy_ssl_server_name on;
      proxy_ssl_protocols TLSv1.2 TLSv1.3;
    }
  }
  # HTTP proxy for content safety detector
  server {
    listen 8085;
    location / {
      set $nemoguard http://content-safety-detector-predictor.{{ .Release.Namespace }}.svc.cluster.local:8080;
      proxy_pass $nemoguard;
    }
  }
}
```

### Content Safety Detector InferenceService

The content safety model is deployed as a KServe InferenceService with vLLM ServingRuntime using MIG GPU:

```yaml
# deploy/helm/mortgage-ai/templates/nemo-guardrails-model.yaml (excerpt)
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: content-safety-detector
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
spec:
  predictor:
    model:
      modelFormat:
        name: vLLM
      resources:
        limits:
          {{ .Values.nemoGuardrails.contentSafety.gpu.resourceType }}: {{ .Values.nemoGuardrails.contentSafety.gpu.count }}
      runtime: vllm-nemoguard-runtime
      storage:
        key: nemo-model-storage
        path: {{ .Values.nemoGuardrails.contentSafety.modelPath }}
```

### RBAC for NeMo Guardrails API Access

A dedicated ServiceAccount, Role, and RoleBinding grant the NeMo Guardrails pod permission to read services:

```yaml
# deploy/helm/mortgage-ai/templates/nemo-guardrails-rbac.yaml (excerpt)
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: nemo-guardrails-api-access
rules:
  - apiGroups: [""]
    resources: ["services"]
    verbs: ["get"]
```

## Configuration

- **Key settings:** `nemoGuardrails.enabled` toggles entire stack; `nemoGuardrails.contentSafety.deploy` controls vLLM model deployment; `nemoGuardrails.proxy.enabled` controls nginx proxy; `nemoGuardrails.proxy.maas.upstream` and `nemoGuardrails.proxy.maas.pathPrefix` configure MaaS endpoint routing
- **Defaults:** Content safety model uses `nvidia.com/mig-2g.35gb` GPU type with 1 GPU; vLLM args include `--gpu-memory-utilization=0.95`, `--max-model-len=4096`, `--enforce-eager`; proxy uses UBI nginx image `registry.redhat.io/ubi10/nginx-126:10.1`
- **Dependencies:** TrustyAI operator must be installed; KServe for the content safety InferenceService; S3-compatible storage for model weights; the nginx proxy hardcodes the OpenShift DNS resolver `172.30.0.10`

## Gotchas

- The nginx proxy hardcodes the OpenShift internal DNS resolver IP `172.30.0.10` -- this works on standard OpenShift clusters but would fail on non-OpenShift Kubernetes (see `deploy/helm/mortgage-ai/templates/nemo-guardrails-proxy.yaml`)
- The Secret template auto-populates `NEMO_GUARDRAILS_ENDPOINT` to `http://nemo-guardrails-internal:8000` when `nemoGuardrails.enabled=true` and no explicit endpoint is set, keeping the API deployment unaware of the guardrails architecture (see `deploy/helm/mortgage-ai/templates/secret.yaml` lines 59-63)
- The content safety detector InferenceService uses `serving.kserve.io/deploymentMode: RawDeployment` to avoid Knative/Istio requirements -- this means the predictor service DNS is `content-safety-detector-predictor` not the Knative revision format (see `deploy/helm/mortgage-ai/templates/nemo-guardrails-model.yaml`)
- The nginx proxy writes temp files to `/tmp/*_temp` paths to run as non-root under OpenShift restricted SCC (see `nemo-guardrails-proxy.yaml` ConfigMap)
- NeMo Guardrails config uses Helm's `{{ "{{" }}` escaping for Jinja2-style template variables (`{{ user_input }}`, `{{ bot_response }}`) used in content safety prompts (see `deploy/helm/mortgage-ai/templates/nemo-guardrails-config.yaml`)

## Related Patterns

- `helm-trustyai-orchestrator-configmap-detector-wiring.md` -- alternative TrustyAI pattern using GuardrailsOrchestrator CRD
- `kserve-rawdeployment-detector-fleet-gpu-toggle.md` -- similar KServe RawDeployment pattern for model serving
