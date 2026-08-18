---
name: maas-governance-gateway
description: Multi-tenant governed model access via Red Hat AI MaaS with rate-limited subscriptions, auth policies, and usage telemetry
summary: "Wraps LLM serving with multi-tenant governance via Red Hat AI MaaS, routing OpenAI-compatible inference through a Gateway API gateway with Kuadrant/Authorino policy enforcement to provide group-based authentication, per-subscription token rate limiting, and per-request usage telemetry for chargeback attribution by cost center. Use instead of direct KServe InferenceService model serving (see model-serving-gateway) when centralized IT teams need Keycloak group-based auth (MaaSAuthPolicy), tiered token budgets (MaaSSubscription with admin 100K tokens/min vs user 50K/min), and usage attribution via TelemetryPolicy and Istio metrics; the gateway auto-detects LoadBalancer vs Route backends for cloud/bare-metal clusters. Deploys via LLMInferenceService (llm-d CRD, serving.kserve.io/v1alpha1) with MaaSModelRef registration, vLLM serving NVIDIA Nemotron with --enable-auto-tool-choice and --reasoning-parser=nano_v3, Keycloak backed by CloudNative-PG PostgreSQL with realm-role-to-group OIDC mapping via a \"groups\" client scope, Continue.dev in DevSpaces as the IDE consumer, and OdhDashboardConfig enabling GenAI Studio and MaaS UI features. LLMInferenceService requires kserve.modelsAsService.managementState: Managed plus the LWS operator; Gateway must have opendatahub.io/managed: \"false\" label and security.opendatahub.io/authorino-tls-bootstrap: \"true\" annotation; Authorino needs manual TLS cert enablement post-install; pin Cluster Observability Operator to v1.4.0, RHCL to v1.3.4, and RHODS to v3.4.0; subscriptions namespace is hardcoded to models-as-a-service; Kuadrant may need post-install pod restart (kuadrant.restart: true)."
metadata:
  type: architecture
tags:
  tech_stack: [vllm, llm-d, keycloak, continue-dev, python]
  ai_pattern: [model-serving]
  platform: [rhoai, openshift, kserve, vllm, kuadrant, gateway-api]
  data_layer: [postgresql]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "MaaS governance gateway with LLMInferenceService (llm-d) serving NVIDIA Nemotron, Kuadrant rate-limited subscriptions, Keycloak auth, Continue.dev IDE consumption via DevSpaces, and per-subscription usage telemetry"
    approach: "A"
---

# MaaS Governance Gateway

## Overview

This architecture deploys a large language model through Red Hat AI's integrated Models-as-a-Service (MaaS) offering, wrapping model serving with multi-tenant governance including group-based authentication, per-subscription token rate limiting, and usage telemetry for chargeback. Unlike direct model serving (see [model-serving-gateway](model-serving-gateway.md)) where downstream services connect to a cluster-internal KServe endpoint, MaaS routes all inference requests through a Gateway API gateway with Kuadrant/Authorino policy enforcement, providing centralized IT teams control over who can access models, how much they can consume, and attribution of usage to cost centers. Developers consume the governed model endpoint from IDE extensions (Continue.dev) running in per-user DevSpaces workspaces.

## Data Flow

1. Developer opens a DevWorkspace in OpenShift DevSpaces, which provisions a per-user namespace (`wksp-<username>`) with a VS Code-based IDE container
2. The IDE has Continue.dev extension recommended, configured to point at the MaaS route (`maas.<wildcardDomain>/v1`) with the user's API key
3. Continue.dev sends OpenAI-compatible requests (chat completions, code completions) to the MaaS gateway endpoint
4. The `maas-default-gateway` Gateway (in `openshift-ingress` namespace) receives the request and routes it through Kuadrant/Authorino policy enforcement
5. MaaSAuthPolicy validates the user's identity against group membership (admin, user) and MaaSSubscription determines the applicable token rate limits
6. TelemetryPolicy extracts per-request labels (model name, user ID, subscription name, organization ID, cost center) from the auth identity and response body for Istio metrics
7. If rate limits are not exceeded, the request is forwarded to the LLMInferenceService (llm-d), which routes to the vLLM pod serving the model
8. vLLM runs inference on the NVIDIA Nemotron model with GPU acceleration and returns the completion
9. Response flows back through the gateway to Continue.dev in the IDE

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Continue.dev (IDE extension) | MaaS Gateway (`maas-default-gateway`) | HTTPS (OpenAI-compatible REST) | Code completion and chat requests with API key auth |
| MaaS Gateway | Kuadrant/Authorino | Internal (sidecar) | Authenticate user, enforce MaaSAuthPolicy group membership |
| MaaS Gateway | Kuadrant rate limiter | Internal (sidecar) | Enforce MaaSSubscription token rate limits per group |
| MaaS Gateway | LLMInferenceService (llm-d) | HTTPS (port 8000, TLS) | Forward approved requests to model serving infrastructure |
| LLMInferenceService (llm-d) | vLLM container | Internal | Route inference to model serving pod |
| vLLM container | OCI registry (quay.io) | HTTPS | Pull modelcar image containing model weights |
| Keycloak | OpenShift OAuth | OIDC | Provide identity provider with realm roles mapping to MaaS groups |
| DevWorkspace | DevSpaces Dashboard | HTTP | Fetch IDE editor devfile for VS Code-based workspace |
| Istio (gateway sidecar) | Prometheus | Prometheus metrics | Emit per-subscription latency metrics via TelemetryPolicy |
| TelemetryPolicy (Kuadrant) | Prometheus | Prometheus metrics | Emit per-request usage metrics with model/user/subscription/org/cost-center labels |

## Key Integration Points

### LLMInferenceService with vLLM and llm-d

The model is deployed using `LLMInferenceService` (llm-d CRD) instead of the standard KServe `InferenceService` + `ServingRuntime` pair. The LLMInferenceService bundles the serving runtime definition inline and routes through the MaaS gateway. SSL is enabled on the container with cert paths for the KServe-provided TLS secret.

```yaml
# charts/maas-code-assistant/templates/models/llminferenceservice.yaml (lines 1-55)
apiVersion: serving.kserve.io/v1alpha1
kind: LLMInferenceService
metadata:
  name: {{ .name }}
  namespace: {{ $.Values.modelsNamespace }}
  annotations:
    opendatahub.io/genai-use-case: {{ .useCase | default "code-assistant" }}
spec:
  model:
    name: {{ .name }}
    uri: {{ .uri }}
  router:
    gateway:
      refs:
        - name: maas-default-gateway
          namespace: openshift-ingress
  template:
    containers:
      - name: main
        command:
          - python
          - -m
          - vllm.entrypoints.openai.api_server
        args:
          - "--served-model-name={{ `{{.Name}}` }}"
          - --model=/mnt/models
          - --enable-ssl-refresh
          - --ssl-certfile=/var/run/kserve/tls/tls.crt
          - --ssl-keyfile=/var/run/kserve/tls/tls.key
```

The default model configuration in values.yaml specifies the NVIDIA Nemotron model with reasoning parser support and tool calling:

```yaml
# charts/maas-code-assistant/values.yaml (lines 33-56)
models:
  - name: nemotron-3-nano-30b-a3b
    uri: oci://quay.io/jharmison/models:redhatai--nvidia-nemotron-3-nano-30b-a3b-fp8-modelcar
    resources:
      limits:
        cpu: "4"
        memory: 24Gi
        nvidia.com/gpu: "1"
    extraArgs:
      - --max-model-len=131072
      - --enable-auto-tool-choice
      - --tool-call-parser=qwen3_coder
      - --trust-remote-code
      - --enable-force-include-usage
      - --reasoning-parser-plugin=/mnt/models/nano_v3_reasoning_parser.py
      - --reasoning-parser=nano_v3
```

### MaaSModelRef Linking Models to MaaS Layer

Each model deployed via LLMInferenceService requires a corresponding `MaaSModelRef` in the `models-as-a-service` API group. This registers the model with the MaaS governance layer so subscriptions and auth policies can reference it.

```yaml
# charts/maas-code-assistant/templates/models/maasmodelref.yaml (lines 1-14)
apiVersion: maas.opendatahub.io/v1alpha1
kind: MaaSModelRef
metadata:
  name: {{ .name }}
  namespace: {{ $.Values.modelsNamespace }}
spec:
  modelRef:
    kind: LLMInferenceService
    name: {{ .name }}
```

### MaaSSubscription with Per-Group Token Rate Limits

Subscriptions define which user groups can access which models and at what token rate. Each subscription creates a rate-limiting policy enforced at the gateway. Multiple rate limit windows can be specified per model (e.g., per-minute and per-hour) to allow burst control.

```yaml
# charts/maas-code-assistant/templates/maassubscription.yaml (lines 1-28)
apiVersion: maas.opendatahub.io/v1alpha1
kind: MaaSSubscription
metadata:
  name: {{ $name }}
  namespace: models-as-a-service
spec:
  modelRefs:
  {{- range $model, $rateLimit := $sub.tokenRateLimits }}
  - name: {{ $model }}
    namespace: {{ $.Values.modelsNamespace }}
    tokenRateLimits:
      {{- toYaml . | nindent 6 }}
  {{- end }}
  owner:
    groups:
      {{- toYaml $sub.groups | nindent 6 }}
  priority: {{ $sub.priority | default 0 }}
```

The default values configure two subscription tiers with different token allowances:

```yaml
# charts/maas-code-assistant/values.yaml (lines 13-29)
subscriptions:
  admin:
    displayName: MaaS Admins
    groups:
      - name: admin
    tokenRateLimits:
      nemotron-3-nano-30b-a3b:
        - limit: 100000
          window: 1m
  user:
    displayName: MaaS Users
    groups:
      - name: user
    tokenRateLimits:
      nemotron-3-nano-30b-a3b:
        - limit: 50000
          window: 1m
```

### MaaSAuthPolicy for Group-Based Access Control

Auth policies bind model access to user groups. The policy references the same models and groups as the subscription, ensuring only authenticated members of the specified groups can reach the model endpoints.

```yaml
# charts/maas-code-assistant/templates/maasauthpolicy.yaml (lines 1-25)
apiVersion: maas.opendatahub.io/v1alpha1
kind: MaaSAuthPolicy
metadata:
  name: {{ $name }}-policy
  namespace: models-as-a-service
spec:
  modelRefs:
  {{- range $model, $rateLimits := $sub.tokenRateLimits }}
  - name: {{ $model }}
    namespace: {{ $.Values.modelsNamespace }}
  {{- end }}
  subjects:
    groups:
      {{- toYaml $sub.groups | nindent 6 }}
```

### TelemetryPolicy for Per-Subscription Usage Metrics

The Kuadrant TelemetryPolicy attaches to the MaaS gateway and enriches Istio metrics with per-request labels extracted from the auth identity and response body. This enables usage attribution and chargeback per subscription, user, organization, and cost center.

```yaml
# charts/maas-code-assistant/templates/telemetrypolicy.yaml (lines 1-23)
apiVersion: extensions.kuadrant.io/v1alpha1
kind: TelemetryPolicy
metadata:
  name: maas-telemetry
  namespace: openshift-ingress
spec:
  metrics:
    default:
      labels:
        model: responseBodyJSON("/model")
        user: auth.identity.userid
        subscription: auth.identity.selected_subscription
        organization_id: auth.identity.subscription_info.organizationId
        cost_center: auth.identity.subscription_info.costCenter
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: maas-default-gateway
```

An additional Istio Telemetry resource adds the subscription name to request duration metrics via the `x-maas-subscription` header:

```yaml
# charts/maas-code-assistant/templates/telemetry.yaml (lines 1-22)
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: latency-per-subscription
  namespace: openshift-ingress
spec:
  selector:
    matchLabels:
      gateway.networking.k8s.io/gateway-name: maas-default-gateway
  metrics:
  - providers:
    - name: prometheus
    overrides:
    - match:
        metric: REQUEST_DURATION
        mode: CLIENT_AND_SERVER
      tagOverrides:
        subscription:
          operation: UPSERT
          value: request.headers["x-maas-subscription"]
```

### Gateway API with Route or LoadBalancer Backends

The MaaS default gateway uses the `openshift-default` GatewayClass. The deployment script auto-detects whether the cluster supports LoadBalancer services or falls back to an OpenShift Route-backed gateway for bare-metal/non-cloud environments.

```yaml
# charts/dependency-operators/files/openshift-ai/gateway.yaml (lines 44-58)
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: maas-default-gateway
  namespace: openshift-ingress
  labels:
    opendatahub.io/managed: "false"
  annotations:
    opendatahub.io/managed: "false"
    security.opendatahub.io/authorino-tls-bootstrap: "true"
spec:
  gatewayClassName: openshift-default
  listeners:
    - name: https
      port: 443
      protocol: HTTPS
      hostname: {{ .hostname | default (printf "maas.%s" $.Values.global.wildcardDomain) }}
```

### Keycloak OIDC Identity Provider with Group-to-Role Mapping

Keycloak is deployed as the identity provider, backed by its own CloudNative-PG PostgreSQL cluster. The realm import creates users with realm roles (`admin`, `user`) that map to groups (`admins`, `users`). A `groups` client scope ensures group membership is included in OIDC tokens, which MaaS uses to match against MaaSAuthPolicy subjects.

```yaml
# charts/maas-code-assistant/charts/keycloak/templates/realmimport.yaml (lines 541-582)
    roles:
      realm:
        - name: user
          description: "Default user role"
        - name: admin
          description: "Administrator role"
    users:
      - username: {{ $username }}
        realmRoles:
          - user
        groups:
          - users
      - username: {{ .Values.realm.admin.username }}
        realmRoles:
          - admin
        groups:
          - admins
    groups:
      - name: admins
      - name: users
```

The `groups` client scope maps realm roles into OIDC tokens so Authorino can enforce MaaSAuthPolicy:

```yaml
# charts/maas-code-assistant/charts/keycloak/templates/realmimport.yaml (lines 56-68)
      - name: groups
        protocol: openid-connect
        protocolMappers:
        - config:
            access.token.claim: 'true'
            claim.name: groups
            id.token.claim: 'true'
            multivalued: 'true'
            user.attribute: foo
          name: groups
          protocolMapper: oidc-usermodel-realm-role-mapper
```

### Continue.dev IDE Configuration via DevWorkspace

Each user gets a DevWorkspace in their dedicated namespace with the Continue.dev extension recommended. The Continue.dev config template points to the MaaS endpoint via an OpenAI-compatible provider.

```yaml
# .vscode/config.yaml (lines 1-17)
name: Local Assistant
version: 1.0.0
schema: v1
models:
  - name: NVIDIA Nemotron 3 Nano 30B-A3B
    provider: openai
    model: "nemotron-3-nano-30b-a3b"
    apiBase: "YOUR_MAAS_ROUTE/v1"
    apiKey: "YOUR_API_KEY"
context:
  - provider: code
  - provider: docs
  - provider: diff
  - provider: terminal
  - provider: problems
  - provider: folder
  - provider: codebase
```

The DevWorkspace clones the quickstart repo and provides IDE tooling:

```yaml
# charts/maas-code-assistant/templates/workspace/devworkspace.yaml (lines 14-32)
  template:
    projects:
    - name: {{ $.Values.workspace.devworkspace.name }}
      git:
        remotes:
          origin: {{ $.Values.workspace.devworkspace.projects.repoUrl }}
    components:
      - name: tooling-container
        container:
          image: {{ $.Values.workspace.devworkspace.image }}
          sourceMapping: /projects
```

### OdhDashboardConfig for MaaS UI Features

A post-install Helm hook patches the OpenShift AI Dashboard configuration to enable MaaS-specific UI features: the GenAI Studio, Model-as-a-Service views, MaaS auth policy management, and the observability dashboard.

```yaml
# charts/maas-code-assistant/values.yaml (lines 85-89)
dashboardConfig:
  genAiStudio: true
  modelAsService: true
  maasAuthPolicies: true
  observabilityDashboard: true
```

## Prompt / Chain Patterns

The MaaS governance gateway itself has no prompt logic -- it exposes the raw model as a governed OpenAI-compatible API. The model serves requests with `--enable-auto-tool-choice` and `--tool-call-parser=qwen3_coder` enabled, supporting function calling for agentic code assistance tasks. The `--reasoning-parser-plugin=/mnt/models/nano_v3_reasoning_parser.py` and `--reasoning-parser=nano_v3` args enable the Nemotron model's built-in reasoning capabilities, parsing structured reasoning output from model responses. Prompt structure is entirely defined by the Continue.dev client, which provides code context (current file, diff, terminal, problems, codebase index) as part of its requests.

## Gotchas

- The `LLMInferenceService` CRD is part of llm-d (serving.kserve.io/v1alpha1) and is distinct from the standard KServe `InferenceService` (serving.kserve.io/v1beta1). It requires the `kserve.modelsAsService.managementState: Managed` setting in the DataScienceCluster, plus the Leader Worker Set (LWS) operator as a prerequisite (`charts/dependency-operators/values.yaml` lines 57-58).
- The MaaS Gateway requires the `opendatahub.io/managed: "false"` label AND the `security.opendatahub.io/authorino-tls-bootstrap: "true"` annotation on the Gateway object. Without these, policy enforcement will not work as expected (README lines 247-248). The README also documents a typo in the annotation name (`opendadatahub.io/managed` with a double "da") which must be set alongside the correct label.
- The Authorino resource created by the Kuadrant CR requires manual TLS enablement after installation: `oc annotate service -n kuadrant-system authorino-authorino-authorization service.beta.openshift.io/serving-cert-secret-name=authorino-server-cert --overwrite` and `oc patch authorino -n kuadrant-system authorino --type=merge --patch '{"spec": {"listener": {"tls": {"enabled": true, "certSecretRef": {"name": "authorino-server-cert"}}}}}'` (README lines 229-234).
- The Cluster Observability Operator must be pinned to version 1.4.0 -- version 1.5.0 has incompatibilities that will be resolved in a later release (README lines 198-199, `dependency-operators/values.yaml` line 121: `startingCSV: cluster-observability-operator.v1.4.0`).
- Red Hat Connectivity Link (RHCL) must be pinned to version 1.3.4 or earlier with Manual upgrade mode. The operator may also need to be installed in a different namespace than the default to avoid conflicting with OpenShift Service Mesh versions managed by the Ingress ClusterOperator's Gateway API installation (README lines 222-226).
- The all-in-one.sh script auto-detects already-installed operators and disables them in environment.yaml to avoid conflicts (`all-in-one.sh` lines 126-129). It also detects whether the cluster router uses a LoadBalancer service type and falls back to a Route-backed gateway for non-cloud environments (`all-in-one.sh` lines 79-97).
- The MaaS subscriptions namespace is hardcoded to `models-as-a-service` in maassubscription.yaml and maasauthpolicy.yaml (line 8 in both templates), while the model namespace is configurable via `modelsNamespace` (default `llm`). These must be in separate namespaces.
- Kuadrant sometimes misbehaves after initial deployment. The chart includes a configurable post-install Job (`kuadrant.restart: true`) that restarts Kuadrant pods after chart installation (`charts/maas-code-assistant/values.yaml` lines 113-115, `templates/job-restart-kuadrant.yaml`).
- The Continue.dev config.yaml in `.vscode/config.yaml` contains placeholder values (`YOUR_MAAS_ROUTE/v1` and `YOUR_API_KEY`) that must be replaced by each user with their actual MaaS route URL and API key obtained from the OpenShift AI dashboard.
- The RHODS operator is pinned to `rhods-operator.3.4.0` with Manual install plan approval (`dependency-operators/values.yaml` lines 86-88). The README recommends staying on this specific version to match the tested codebase.

## Related Architectures

- [model-serving-gateway](model-serving-gateway.md) -- Direct model serving via KServe InferenceService + ServingRuntime without governance; MaaS governance gateway wraps this pattern with multi-tenant access control, rate limiting, and usage telemetry
- [api-security-gateway](api-security-gateway.md) -- Network-level API security (WAF, OpenAPI spec enforcement) via external gateway; MaaS governance operates at the application/identity layer with token-based rate limiting rather than HTTP transport-level protection
- [llm-observability-pipeline](llm-observability-pipeline.md) -- The TelemetryPolicy and Istio Telemetry resources in this pattern emit per-subscription metrics that feed into Prometheus monitoring, complementing full distributed tracing pipelines
