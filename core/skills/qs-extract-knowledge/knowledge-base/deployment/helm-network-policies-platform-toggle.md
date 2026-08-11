---
name: helm-network-policies-platform-toggle
description: Helm-managed NetworkPolicies with platform toggle for OpenShift vs Kind ingress controller namespaces
summary: "Deploys four Helm-templated NetworkPolicies (default-deny-ingress, allow-same-namespace, Knative eventing cross-namespace, platform-specific ingress controller) implementing a default-deny-then-allow model that adapts ingress rules via a platform toggle for OpenShift, Kind, or none. Use when deploying quickstarts with Knative eventing and cross-platform requirements -- `requestManagement.networkPolicies.platform` selects `network.openshift.io/policy-group: ingress` for OpenShift or `kubernetes.io/metadata.name: ingress-nginx` for Kind; set to `none` to disable platform-specific rules. Policies are enabled by default with platform defaulting to `openshift`; the Knative eventing policy restricts cross-namespace ingress to `kafka-broker-dispatcher` pods on ports 8080/80; `additionalIngressRules` extends rules via values; requires a NetworkPolicy-capable CNI (OVN-Kubernetes or Calico). Kind E2E tests must pass `--set requestManagement.networkPolicies.platform=kind` to switch namespace selectors, the Knative eventing policy includes a fallback `name: knative-eventing` selector for older Kubernetes versions without `kubernetes.io/metadata.name`, and enabling Langfuse adds port 3000 to the ingress controller policy for UI access."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "4 NetworkPolicies with openshift/kind/none platform toggle, Knative eventing and ingress controller awareness"
    approach: "A"
---

# Helm Network Policies with Platform Toggle

## Overview

This pattern deploys Kubernetes NetworkPolicies via Helm templates that adapt their ingress rules based on a platform toggle (`openshift`, `kind`, or `none`). The policies implement a default-deny-then-allow model across same-namespace communication, Knative eventing cross-namespace access, and platform-specific ingress controller rules.

## Pattern Description

Four NetworkPolicy resources are templated: a default deny-all ingress, a same-namespace allow-all, a Knative eventing cross-namespace allow (restricted to `kafka-broker-dispatcher` pods), and a platform-specific ingress controller allow. The platform toggle (`requestManagement.networkPolicies.platform`) selects the correct namespace selector for the ingress controller -- `network.openshift.io/policy-group: ingress` for OpenShift or `kubernetes.io/metadata.name: ingress-nginx` for Kind.

## Implementation

### Default Deny with Same-Namespace Allow

```yaml
# helm/templates/network-policies.yaml (excerpt)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "self-service-agent.fullname" . }}-default-deny-ingress
spec:
  podSelector: {}
  policyTypes:
  - Ingress
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ include "self-service-agent.fullname" . }}-allow-same-namespace
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector: {}
```

### Knative Eventing Cross-Namespace Access

Restricts cross-namespace traffic to only Kafka broker dispatcher pods:

```yaml
# helm/templates/network-policies.yaml (excerpt)
spec:
  podSelector:
    matchLabels:
      {{- include "self-service-agent.selectorLabels" . | nindent 6 }}
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: knative-eventing
      podSelector:
        matchLabels:
          app: kafka-broker-dispatcher
    ports:
    - protocol: TCP
      port: 8080
    - protocol: TCP
      port: 80
```

### Platform-Specific Ingress Controller

The platform toggle selects the correct namespace labels:

```yaml
# helm/templates/network-policies.yaml (excerpt)
{{- if eq .Values.requestManagement.networkPolicies.platform "openshift" }}
  - from:
    - namespaceSelector:
        matchLabels:
          network.openshift.io/policy-group: ingress
{{- else if eq .Values.requestManagement.networkPolicies.platform "kind" }}
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
{{- end }}
```

## Configuration

- **Key settings:** `requestManagement.networkPolicies.enabled` toggles all policies; `requestManagement.networkPolicies.platform` accepts `openshift`, `kind`, or `none`; `requestManagement.networkPolicies.additionalIngressRules` allows custom rules via values
- **Defaults:** Network policies are enabled by default; platform defaults to `openshift`
- **Dependencies:** Requires a network plugin that supports NetworkPolicy enforcement (OVN-Kubernetes on OpenShift, Calico on Kind)

## Gotchas

- The Kind E2E composite action passes `--set requestManagement.networkPolicies.platform=kind` to switch from the default OpenShift policy to Kind-compatible namespace selectors (see `.github/actions/kind/action.yaml`)
- The Knative eventing policy includes a fallback selector (`name: knative-eventing`) for compatibility with older Kubernetes versions that may not have the `kubernetes.io/metadata.name` label (see `helm/templates/network-policies.yaml`)
- When Langfuse is enabled, the ingress controller policy adds port 3000 to the allowed ports list to enable external access to the Langfuse UI (see `helm/templates/network-policies.yaml`)

## Related Patterns

- `helm-knative-kafka-cloudevents-triggers.md` -- the eventing layer that requires the cross-namespace network policy
