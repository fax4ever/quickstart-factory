---
name: helm-nemo-guardrails-trustyai-crd-nginx-maas-proxy
description: TrustyAI NemoGuardrails CRD with nginx HTTP-to-HTTPS proxy for MaaS LLM and vLLM content safety detector
summary: "Deploys NVIDIA NeMo Guardrails via TrustyAI operator's NemoGuardrails CRD with ConfigMap-based config for regex detection (SSN, credit cards), sensitive data entities, and content safety flows to guard LLM application inputs/outputs on OpenShift AI. Approach A (multi-agent-loan-origination) adds an nginx proxy (UBI nginx, ports 8081/8085) for HTTP-to-HTTPS MaaS bridging with proxy_ssl_server_name and path rewriting plus a vLLM KServe RawDeployment content safety detector (NemoGuard 8B, MIG GPU, --gpu-memory-utilization=0.95 --max-model-len=4096 --enforce-eager), RBAC, and enable-auth: false; Approach B (portfolio-manager-agent) is standalone with Colang flows, Python topic-check action, no proxy/GPU/RBAC, enable-auth: true, and a manual guardrails-internal Service. Critical config: the NemoGuardrails CR references a ConfigMap with models pointing to proxy ports (openai_api_base: http://nemo-guardrails-proxy:8081/v1 for main LLM, base_url on :8085 for content_safety) in Approach A, while Approach B embeds config.yaml, rails.co, and actions.py as separate ConfigMap data keys; Helm values toggle the stack via nemoGuardrails.enabled, contentSafety.deploy, and proxy.enabled, and a Secret auto-populates NEMO_GUARDRAILS_ENDPOINT to http://nemo-guardrails-internal:8000. Gotchas: nginx hardcodes OpenShift DNS resolver 172.30.0.10 (fails on non-OpenShift K8s), RawDeployment predictor DNS is content-safety-detector-predictor not Knative revision format, Helm templates must use {{ \"{{\" }} escaping for Jinja2 variables in content safety prompts, nginx writes to /tmp for non-root restricted SCC compliance, and OPENAI_API_KEY env var must be set even when unused in Approach B."
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
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Standalone NemoGuardrails CRD with ConfigMap containing Colang flows, Python topic-check action, regex/sensitive-data rails -- no nginx proxy, no content safety model, no RBAC"
    approach: "B"
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

---

## Approach B: Standalone NemoGuardrails CRD without Proxy or Content Safety Model (from portfolio-manager-agent)

### When to Use

When the application only needs input/output guardrails (regex, sensitive data detection, topic filtering) without external LLM proxy or GPU-based content safety models. Suited for simpler deployments where the guardrails run locally alongside the application.

### Differences from Approach A

- No nginx proxy -- the NemoGuardrails instance is accessed directly via an internal Service
- No content safety detector model or InferenceService -- guardrails rely on regex patterns, sensitive data entities, and a custom Python action for topic checking
- No RBAC (ServiceAccount/Role/RoleBinding) -- the CRD uses minimal configuration
- The ConfigMap includes a Colang flow definition (`.co` file) and a Python action file (`actions.py`) embedded directly as ConfigMap data keys
- `security.opendatahub.io/enable-auth: "true"` annotation enabled (Approach A uses `"false"`)
- A manual internal Service is created alongside the CRD to provide a stable endpoint for the orchestrator

### Implementation

#### NemoGuardrails CRD with Manual Service

```yaml
# deploy/helm/templates/nemoguardrails-cr.yaml
{{- if .Values.guardrails.enabled }}
apiVersion: trustyai.opendatahub.io/v1alpha1
kind: NemoGuardrails
metadata:
  name: guardrails
  namespace: {{ .Values.namespace }}
  annotations:
    security.opendatahub.io/enable-auth: "true"
spec:
  nemoConfigs:
    - name: guardrails-config
      configMaps:
        - guardrails-config
  env:
    - name: OPENAI_API_KEY
      value: not-used
---
apiVersion: v1
kind: Service
metadata:
  name: guardrails-internal
  namespace: {{ .Values.namespace }}
spec:
  selector:
    app: guardrails
  ports:
    - name: http
      protocol: TCP
      port: 8000
      targetPort: 8000
  type: ClusterIP
{{- end }}
```

#### ConfigMap with Colang Flows and Python Actions

The ConfigMap embeds three files: `config.yaml` (rails config), `rails.co` (Colang flow definitions), and `actions.py` (custom Python action):

```yaml
# deploy/helm/templates/configmap-guardrails.yaml (excerpt)
data:
  config.yaml: |
    rails:
      config:
        sensitive_data_detection:
          input:
            entities:
              - CREDIT_CARD
              - US_SSN
              - PHONE_NUMBER
        regex_detection:
          input:
            patterns:
              - "\\b(password|secret|api[_-]?key|token)\\b"
              - "\\d{3}-\\d{2}-\\d{4}"
            case_insensitive: true
      input:
        flows:
          - detect sensitive data on input
          - regex check input
          - check financial topic
      output:
        flows:
          - detect sensitive data on output
  rails.co: |
    define flow check financial topic
      $result = execute check_financial_topic
      if $result == "blocked"
        bot inform off topic
        stop

    define bot inform off topic
      "I can only help with investment and portfolio-related questions."
  actions.py: |
    from nemoguardrails.actions import action

    OFF_TOPIC_KEYWORDS = [
        "recipe", "cooking", "weather forecast", "sports score",
        "write me a poem", "tell me a joke", "song lyrics",
    ]

    @action(is_system_action=True)
    async def check_financial_topic(context=None):
        user_message = (context or {}).get("user_message", "").lower()
        for keyword in OFF_TOPIC_KEYWORDS:
            if keyword in user_message:
                return "blocked"
        return "allowed"
```

### Gotchas

- The `OPENAI_API_KEY` env var is set to `"not-used"` because the NeMo Guardrails runtime requires it to be present even when no LLM-based guardrails are configured (see `deploy/helm/templates/nemoguardrails-cr.yaml`)
- A manual Service `guardrails-internal` is created alongside the CRD to provide a stable endpoint -- the orchestrator references this via `GUARDRAILS_URL: "http://guardrails-internal:8000"` (see `deploy/helm/templates/deployment-orchestrator.yaml`)
- The `guardrails.enabled` toggle in values.yaml gates both the NemoGuardrails CRD/Service/ConfigMap and the `GUARDRAILS_URL` env var in the orchestrator deployment (see `deploy/helm/templates/deployment-orchestrator.yaml` conditional block)
- The ConfigMap uses multiple data keys (`config.yaml`, `rails.co`, `actions.py`) that NeMo Guardrails expects as separate files in its config directory -- the TrustyAI operator mounts the ConfigMap accordingly (see `deploy/helm/templates/configmap-guardrails.yaml`)

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| LLM proxy | nginx HTTP-to-HTTPS proxy for MaaS | No proxy, direct internal Service |
| Content safety | vLLM InferenceService (MIG GPU) | None -- regex + sensitive data + custom Python action only |
| Auth annotation | `enable-auth: "false"` | `enable-auth: "true"` |
| RBAC | ServiceAccount + Role + RoleBinding | None |
| ConfigMap contents | models, regex, content safety flows | Regex, sensitive data, Colang flows, Python action |
| GPU requirement | Yes (for content safety detector) | No |

## Related Patterns

- `helm-trustyai-orchestrator-configmap-detector-wiring.md` -- alternative TrustyAI pattern using GuardrailsOrchestrator CRD
- `kserve-rawdeployment-detector-fleet-gpu-toggle.md` -- similar KServe RawDeployment pattern for model serving
