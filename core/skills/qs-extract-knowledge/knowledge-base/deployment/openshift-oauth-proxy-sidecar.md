---
name: openshift-oauth-proxy-sidecar
description: OAuth proxy sidecar with TLS re-encryption, session secrets, and auth-delegator RBAC
summary: "Adds an origin-oauth-proxy sidecar (quay.io/openshift/origin-oauth-proxy:4.17) to a Deployment for platform-native OpenShift OAuth authentication with TLS termination (HTTPS 8888, HTTP 8887), cookie-based sessions, and token validation through a TLS re-encryption Route, without modifying application code. Use when OpenShift-deployed applications need transparent OAuth with configurable path exclusions (--skip-auth-regex), token delegation (--openshift-delegate-urls), and user identity forwarding (--pass-user-headers=true) to a backend on localhost:8000. Requires Service annotated with service.alpha.openshift.io/serving-cert-secret-name for auto-provisioned TLS, ServiceAccount with oauth-redirectreference annotation pointing to the Route name, system:auth-delegator ClusterRoleBinding (name includes Release.Namespace to avoid cross-namespace conflicts), and session secret auto-generated via randAlphaNum 32 if not overridden. The /validate endpoint must be in --skip-auth-regex because LlamaStack's auth provider calls back on HTTP port 8887 for token validation creating a circular auth dependency if protected; TLS and session-secret volumes must be defined in values.yaml under volumes: rather than inline in the deployment template."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, openshift]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "OAuth proxy sidecar fronting FastAPI backend with TLS re-encryption Route and skip-auth for /validate"
    approach: "A"
---

# OpenShift OAuth Proxy Sidecar

## Overview

This pattern adds an `origin-oauth-proxy` sidecar container to the application Deployment, enabling OpenShift OAuth authentication. The proxy handles TLS termination, cookie-based sessions, and token validation, while exposing both HTTPS (8888) and HTTP (8887) ports. A Route with TLS re-encryption forwards external traffic through the proxy.

## Pattern Description

The Deployment runs two containers side by side: the oauth-proxy sidecar and the application container. The proxy intercepts all incoming traffic, authenticates users via OpenShift OAuth, and forwards authenticated requests to `localhost:8000` (the application port). Specific paths can be excluded from authentication via `--skip-auth-regex`. The proxy uses OpenShift's built-in serving certificate mechanism for TLS.

## Implementation

### Sidecar Container Definition

The oauth-proxy sidecar is defined as a second container in the Deployment template:

```yaml
# deploy/cluster/helm/templates/deployment.yaml (excerpt)
containers:
  - name: oauth-proxy
    args:
      - -provider=openshift
      - -https-address=:8888
      - -http-address=:8887
      - -email-domain=*
      - -upstream=http://localhost:8000
      - -pass-user-headers=true
      - -openshift-delegate-urls={"/validate-token":{"resource":"secrets","namespace":"{{ .Release.Namespace }}","verb":"get"}}
      - -tls-cert=/etc/tls/private/tls.crt
      - -tls-key=/etc/tls/private/tls.key
      - -cookie-secret-file=/etc/proxy/secrets/session_secret
      - -openshift-service-account={{ include "ai-virtual-agent.serviceAccountName" . }}
      - -openshift-ca=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
      - -skip-auth-regex=^/metrics
      - -skip-auth-regex=^/validate$
      - -skip-auth-regex=^/validate/$
    image: quay.io/openshift/origin-oauth-proxy:4.17
    ports:
      - name: oauth-proxy
        containerPort: 8888
      - name: proxy-http
        containerPort: 8887
    volumeMounts:
      - mountPath: /etc/tls/private
        name: secret-ai-virtual-agent-tls
      - mountPath: /etc/proxy/secrets
        name: secret-ai-virtual-agent-proxy
```

### Service with Proxy Ports

The Service exposes three ports: the HTTPS proxy port (8888), the HTTP proxy port (8887), and the direct application port (8000). The TLS serving certificate is auto-provisioned via the `service.alpha.openshift.io/serving-cert-secret-name` annotation:

```yaml
# deploy/cluster/helm/templates/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: {{ include "ai-virtual-agent.fullname" . }}
  annotations:
    service.alpha.openshift.io/serving-cert-secret-name: ai-virtual-agent-tls
spec:
  ports:
    - name: proxy
      port: 8888
      targetPort: oauth-proxy
    - name: proxy-http
      port: 8887
      targetPort: proxy-http
    - port: {{ .Values.service.port }}
      targetPort: http
      name: http
```

### Route with TLS Re-encryption

The Route targets the proxy port and uses `reencrypt` TLS termination:

```yaml
# deploy/cluster/helm/templates/route.yaml
spec:
  to:
    kind: Service
    name: {{ include "ai-virtual-agent.fullname" . }}-authenticated
  port:
    targetPort: proxy
  tls:
    termination: reencrypt
    insecureEdgeTerminationPolicy: Redirect
```

### ServiceAccount with OAuth Redirect Annotation

The ServiceAccount carries an `oauth-redirectreference` annotation that tells OpenShift where to redirect after authentication:

```yaml
# deploy/cluster/helm/values.yaml (excerpt)
serviceAccount:
  create: true
  automount: true
  annotations:
    serviceaccounts.openshift.io/oauth-redirectreference.ai-virtual-agent: '{"kind":"OAuthRedirectReference","apiVersion":"v1","reference":{"kind":"Route","name":"ai-virtual-agent-authenticated"}}'
  name: "ai-virtual-agent-proxy-sa"
```

### RBAC for Token Review Delegation

A ClusterRoleBinding grants the ServiceAccount the `system:auth-delegator` role, enabling the proxy to validate tokens:

```yaml
# deploy/cluster/helm/templates/rbac.yaml (excerpt)
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: proxy-can-create-token-reviews-{{ .Release.Namespace }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:auth-delegator
subjects:
- kind: ServiceAccount
  name: {{ include "ai-virtual-agent.serviceAccountName" . }}
  namespace: {{ .Release.Namespace }}
```

### Session Secret

A random 32-character session secret is generated at install time unless overridden:

```yaml
# deploy/cluster/helm/templates/sessionsecret.yaml
stringData:
  session_secret: {{ .Values.sessionSecret.value | default (randAlphaNum 32) | quote }}
```

## Configuration

- **Key settings:** `--skip-auth-regex` patterns for unauthenticated endpoints; `--openshift-delegate-urls` for token validation; `--pass-user-headers=true` to forward user identity headers to the backend
- **Defaults:** Session secret auto-generated if not provided via `sessionSecret.value`; proxy image pinned to `origin-oauth-proxy:4.17`
- **Dependencies:** OpenShift cluster with OAuth configured; serving certificate controller enabled; the Route name in the OAuth redirect annotation must match the Route resource name

## Gotchas

- The `--skip-auth-regex` flags in `deployment.yaml` exclude `/validate` and `/metrics` from auth. The `/validate` endpoint is specifically needed because LlamaStack's auth provider calls back to this endpoint (port 8887, the HTTP proxy port) for token validation, creating a circular dependency if it were behind auth
- The ClusterRoleBinding name includes `{{ .Release.Namespace }}` to avoid conflicts across namespaces (see `rbac.yaml` line 57)
- Both TLS and session secret Volumes are defined in `values.yaml` under `volumes:` rather than inline in the deployment template (see `values.yaml` lines 92-101)

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the umbrella chart this sidecar is part of
- `helm-rbac-toolhive-mcp-discovery.md` -- additional RBAC rules in the same Role
