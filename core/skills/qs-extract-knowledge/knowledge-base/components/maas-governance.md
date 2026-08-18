---
name: maas-governance
description: MaaS governance layer providing auth policies, subscriptions with token rate limits, and usage telemetry via Kuadrant and Keycloak
summary: "MaaS governance layer is a Helm-only component (no container image) that enforces authentication, authorization, token-based rate limiting, and per-subscription usage telemetry on LLM inference endpoints in RHOAI using MaaSSubscription, MaaSAuthPolicy, and MaaSModelRef CRs in the models-as-a-service namespace with Kuadrant policy enforcement on the maas-default-gateway. Use when multi-tenant LLM access requires group-based subscriptions with per-model tokenRateLimits (limit+window), dual telemetry (Istio Telemetry for x-maas-subscription header extraction plus Kuadrant TelemetryPolicy for user/subscription/organization_id/cost_center billing labels), optional Keycloak OIDC identity with realm-role-to-group-claim mapping, and CloudNativePG for backend state. Configuration is driven by Helm values subscriptions.<name>.tokenRateLimits.<model>[] and subscriptions.<name>.groups[] for CR generation, keycloak.enabled for OIDC, and the gateway requires opendatahub.io/managed: \"false\" label+annotation plus security.opendatahub.io/authorino-tls-bootstrap: \"true\" for enforcement to work. Gotchas: Kuadrant often needs a post-install restart (conditional Job via kuadrant.restart), Authorino CR must be manually patched for TLS (listener.tls.enabled: true with serving-cert-secret-name annotation), RHCL must be pinned to v1.3.4 and Cluster Observability Operator to v1.4.0 due to v1.5.0 incompatibilities, and the Keycloak OAuth patch job requires cluster-admin ClusterRoleBinding."
metadata:
  type: component
tags:
  tech_stack: [helm, keycloak, postgresql, istio]
  ai_pattern: [model-serving, guardrails]
  platform: [rhoai, openshift, kserve, kuadrant, gateway-api]
  data_layer: []
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "Multi-tenant LLM governance with MaaS auth policies, subscriptions, token rate limits, and per-subscription telemetry via Kuadrant"
    approach: "A"
---

# MaaS Governance

## Overview

The MaaS governance layer is a proxy component that sits between consumers and LLM inference endpoints on Red Hat OpenShift AI, providing authentication, authorization, token-based rate limiting, and usage telemetry. It leverages OpenShift AI's Models-as-a-Service (MaaS) custom resources (`MaaSAuthPolicy`, `MaaSSubscription`, `MaaSModelRef`) together with Red Hat Connectivity Link (Kuadrant) for policy enforcement and Istio/Gateway API telemetry for per-subscription usage tracking. An optional Keycloak subchart provisions identity and group-based access control.

## Tech Stack & Dependencies

- **Runtime:** Helm chart (no application runtime -- pure Kubernetes/OpenShift resource orchestration)
- **Container image:** N/A (governance is enforced by platform operators, not a standalone container)
- **Key dependencies:**
  - Red Hat OpenShift AI 3.4+ with MaaS `managementState: Managed`
  - Red Hat Connectivity Link (Kuadrant) for auth policy enforcement
  - Gateway API (`maas-default-gateway` in `openshift-ingress` namespace)
  - Keycloak (optional subchart) for OIDC-based identity provisioning
  - CloudNativePG (PostgreSQL) for MaaS backend state
- **Helm subchart:** `keycloak` subchart (conditional on `keycloak.enabled`)

## Key Patterns

### MaaS Subscriptions with Token Rate Limits

Subscriptions map OpenShift groups to models with per-model token rate limits. Each subscription is a `MaaSSubscription` CR in the `models-as-a-service` namespace, iterated from the `subscriptions` values map.

```yaml
# From charts/maas-code-assistant/values.yaml
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

The template iterates this map to produce CRs with `spec.modelRefs[].tokenRateLimits` and `spec.owner.groups`:

```yaml
# From charts/maas-code-assistant/templates/maassubscription.yaml
apiVersion: maas.opendatahub.io/v1alpha1
kind: MaaSSubscription
spec:
  modelRefs:
  {{- range $model, $rateLimit := $sub.tokenRateLimits }}
  - name: {{ $model }}
    namespace: {{ $.Values.modelsNamespace }}
    {{- with $rateLimit }}
    tokenRateLimits:
      {{- toYaml . | nindent 6 }}
    {{- end }}
  {{- end }}
  priority: {{ $sub.priority | default 0 }}
```

### MaaS Auth Policies

Auth policies bind subscriptions to groups. A `MaaSAuthPolicy` is created only when a subscription has `groups` defined:

```yaml
# From charts/maas-code-assistant/templates/maasauthpolicy.yaml
{{- range $name, $sub := .Values.subscriptions }}
{{- if $sub.groups }}
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
      {{- toYaml . | nindent 6 }}
{{- end }}
{{- end }}
```

### MaaS Model References

Each model served via MaaS needs a `MaaSModelRef` CR that bridges `LLMInferenceService` to the governance layer:

```yaml
# From charts/maas-code-assistant/templates/models/maasmodelref.yaml
apiVersion: maas.opendatahub.io/v1alpha1
kind: MaaSModelRef
spec:
  modelRef:
    kind: LLMInferenceService
    name: {{ .name }}
```

### Per-Subscription Usage Telemetry

Two complementary telemetry mechanisms track usage per subscription. An Istio `Telemetry` resource extracts the subscription header from requests passing through the MaaS gateway:

```yaml
# From charts/maas-code-assistant/templates/telemetry.yaml
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
  - overrides:
    - match:
        metric: REQUEST_DURATION
        mode: CLIENT_AND_SERVER
      tagOverrides:
        subscription:
          operation: UPSERT
          value: request.headers["x-maas-subscription"]
```

A Kuadrant `TelemetryPolicy` extracts identity-based labels (user, subscription, organization, cost center) from auth context for billing and chargeback:

```yaml
# From charts/maas-code-assistant/templates/telemetrypolicy.yaml
apiVersion: extensions.kuadrant.io/v1alpha1
kind: TelemetryPolicy
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

### Gateway API with Authorino TLS Bootstrap

The MaaS gateway requires specific labels and annotations for policy enforcement to work:

```yaml
# From charts/dependency-operators/files/openshift-ai/gateway.yaml
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
```

### Keycloak OIDC Integration (Optional)

When `keycloak.enabled: true`, the subchart deploys Red Hat Build of Keycloak with a realm that provisions users, groups (`admins`, `users`), and roles (`admin`, `user`), then patches the cluster OAuth to add a `rhbk` OIDC identity provider. The realm includes a `groups` client scope that maps realm roles to token claims.

```yaml
# From charts/maas-code-assistant/charts/keycloak/files/oauth.yaml
identityProviders:
  - name: rhbk
    type: OpenID
    mappingMethod: claim
    openID:
      claims:
        groups:
          - groups
      clientID: {{ .Values.realm.openshiftClientId }}
      issuer: >-
        https://{{ .Values.name }}.{{ .Values.global.wildcardDomain }}/realms/{{ .Values.realm.name }}
```

## Configuration

- **Environment variables:** None (pure Kubernetes resource orchestration)
- **Config files:**
  - `charts/maas-code-assistant/values.yaml` -- `subscriptions` map controls auth policies, rate limits, and group bindings
  - `charts/dependency-operators/values.yaml` -- operator installations including `rhcl-operator` (Kuadrant) and `rhbk-operator` (Keycloak)
- **Helm values:**
  - `subscriptions.<name>.tokenRateLimits.<model>[]` -- token rate limit per model per subscription (limit + window)
  - `subscriptions.<name>.groups[]` -- OpenShift groups bound to the subscription
  - `subscriptions.<name>.priority` -- subscription priority (default 0)
  - `modelsNamespace` -- namespace where model CRs live (default `llm`)
  - `keycloak.enabled` -- toggles Keycloak subchart deployment
  - `keycloak.realm.openshiftClientId` / `openshiftClientSecret` -- OIDC client credentials
  - `dashboardConfig.modelAsService` / `maasAuthPolicies` -- enables MaaS features in OpenShift AI dashboard

## Known Gotchas

- The gateway must have `opendatahub.io/managed: "false"` as both a label and annotation, plus `security.opendatahub.io/authorino-tls-bootstrap: "true"` annotation; without these, policy enforcement does not work as expected (documented in README advanced deployment prerequisites).
- Kuadrant sometimes misbehaves after install, requiring a forced restart. The chart includes a conditional post-install/post-upgrade Job (`kuadrant.restart: false` by default) that restarts the Kuadrant deployment in `kuadrant-system` to work around this (comment in `values.yaml`: "Kuadrant sometimes misbehaves. Force a job to restart it after a delay post-apply").
- The Authorino resource created by Kuadrant must be manually patched to enable TLS on its endpoint before MaaS policies can enforce correctly. This requires annotating the service with `service.beta.openshift.io/serving-cert-secret-name=authorino-server-cert` and patching the Authorino CR with `listener.tls.enabled: true` (documented in README advanced deployment).
- Red Hat Connectivity Link must be pinned to version 1.3.4 or earlier with Manual upgrade mode; version 1.5.0 has incompatibilities (noted in README prerequisites and `values.yaml` with `startingCSV: rhcl-operator.v1.3.4`).
- The Cluster Observability Operator must be pinned to version 1.4.0; version 1.5.0 has incompatibilities (noted in README: "You need to pin this to version 1.4.0 during the installation").
- The OAuth patch job for Keycloak requires `cluster-admin` ClusterRoleBinding because it patches the cluster-level OAuth resource (from `charts/maas-code-assistant/charts/keycloak/templates/job-patch-oauth.yaml`).

## Testing Notes

- Verify that `MaaSSubscription` and `MaaSAuthPolicy` CRs are created in the `models-as-a-service` namespace with `oc get maassubscriptions,maasauthpolicies -n models-as-a-service`.
- Verify the `maas-default-gateway` Gateway shows as `Programmed` in `openshift-ingress` namespace.
- Test rate limiting by sending requests that exceed the configured `tokenRateLimits` window and confirming they are throttled.
- Verify telemetry labels appear in Prometheus metrics by checking for the `subscription`, `organization_id`, and `cost_center` labels on request metrics.
- If Keycloak is enabled, verify the `rhbk` identity provider appears in the OpenShift login page and that users can authenticate and receive group claims.

## Related Patterns

- Model serving via `LLMInferenceService` (the inference endpoints that governance protects)
- Observability stack for surfacing per-subscription usage metrics in Perses dashboards
- Gateway API configuration for traffic routing to model endpoints
