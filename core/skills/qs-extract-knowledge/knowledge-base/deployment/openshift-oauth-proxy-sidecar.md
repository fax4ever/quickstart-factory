---
name: openshift-oauth-proxy-sidecar
description: OAuth proxy sidecar with TLS re-encryption, session secrets, and auth-delegator RBAC
summary: "Adds an origin-oauth-proxy sidecar (quay.io/openshift/origin-oauth-proxy:4.17) to a Deployment for platform-native OpenShift OAuth authentication with TLS termination (HTTPS 8888, HTTP 8887), cookie-based sessions, and token validation through a TLS re-encryption Route, without modifying application code. Approach A targets Deployments using --openshift-delegate-urls for token delegation with --pass-user-headers=true and configurable --skip-auth-regex to forward identity to a backend on localhost:8000; Approach B conditionally includes a Red Hat ose-oauth-proxy (pinned by digest) in a Kubeflow Notebook, using inject-auth annotation on RHOAI v2+ via .Capabilities.APIVersions.Has detection and manual sidecar with --openshift-sar on older versions, requiring no Route or ClusterRoleBinding since the Notebook controller handles routing. Requires Service annotated with service.alpha.openshift.io/serving-cert-secret-name for auto-provisioned TLS, ServiceAccount with oauth-redirectreference annotation pointing to the Route name, system:auth-delegator ClusterRoleBinding (name includes Release.Namespace to avoid cross-namespace conflicts), and session secret auto-generated via randAlphaNum 32 if not overridden. The /validate endpoint must be in --skip-auth-regex because LlamaStack's auth provider calls back on HTTP port 8887 for token validation creating a circular auth dependency if protected; Approach B's .Capabilities.APIVersions.Has requires a live cluster connection -- helm template always returns false, including the sidecar regardless of RHOAI version; TLS and session-secret volumes must be defined in values.yaml under volumes: rather than inline in the deployment template."
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
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Conditional OAuth proxy in Kubeflow Notebook -- uses inject-auth annotation on RHOAI v2+, manual ose-oauth-proxy sidecar on older versions"
    approach: "B"
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

---

## Approach B: Conditional OAuth Proxy in Kubeflow Notebook with RHOAI Version Detection (from llm-cpu-serving)

### When to Use

When deploying a Kubeflow Notebook workbench that must work across both newer RHOAI versions (v2+, which handle auth injection natively) and older RHOAI versions (which require a manual OAuth proxy sidecar). This approach avoids maintaining two separate chart versions.

### Differences from Approach A

- Uses `.Capabilities.APIVersions.Has "datasciencecluster.opendatahub.io/v2"` to detect RHOAI version at template time, conditionally including the sidecar only on older versions
- On newer RHOAI: uses `notebooks.opendatahub.io/inject-auth: 'true'` annotation (operator handles auth injection)
- On older RHOAI: uses `notebooks.opendatahub.io/inject-oauth: 'true'` annotation plus a manual `ose-oauth-proxy` sidecar
- The sidecar targets a Kubeflow Notebook (not a Deployment), using `--openshift-sar` for notebook-specific authorization
- Uses the Red Hat `ose-oauth-proxy` image pinned by digest rather than the upstream `origin-oauth-proxy` image
- No Route or ClusterRoleBinding is needed -- the Notebook controller handles service creation and routing

### Implementation

```yaml
# helm/templates/workbench.yaml (excerpt)
apiVersion: kubeflow.org/v1
kind: Notebook
metadata:
  annotations:
    {{- if .Capabilities.APIVersions.Has "datasciencecluster.opendatahub.io/v2" }}
    notebooks.opendatahub.io/inject-auth: 'true'
    {{- else }}
    notebooks.opendatahub.io/inject-oauth: 'true'
    {{- end }}
spec:
  template:
    spec:
      containers:
        - name: anythingllm
          # ... main workbench container ...
        {{- if not (.Capabilities.APIVersions.Has "datasciencecluster.opendatahub.io/v2") }}
        - name: oauth-proxy
          image: 'registry.redhat.io/openshift4/ose-oauth-proxy@sha256:4bef31eb...'
          args:
            - '--provider=openshift'
            - '--https-address=:8443'
            - '--http-address='
            - '--openshift-service-account=anythingllm'
            - '--cookie-secret-file=/etc/oauth/config/cookie_secret'
            - '--cookie-expire=24h0m0s'
            - '--tls-cert=/etc/tls/private/tls.crt'
            - '--tls-key=/etc/tls/private/tls.key'
            - '--upstream=http://localhost:8888'
            - '--upstream-ca=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
            - '--skip-provider-button'
            - '--openshift-sar={"verb":"get","resource":"notebooks","resourceAPIGroup":"kubeflow.org","resourceName":"anythingllm","namespace":"{{ .Release.Namespace }}"}'
          ports:
            - containerPort: 8443
              name: oauth-proxy
          volumeMounts:
            - mountPath: /etc/oauth/config
              name: oauth-config
            - mountPath: /etc/tls/private
              name: tls-certificates
        {{- end }}
```

### Gotchas

- The `.Capabilities.APIVersions.Has` check requires a live cluster connection -- `helm template` (dry-run) will always return false, causing the sidecar to be included in template output regardless of RHOAI version (see `helm/templates/workbench.yaml`)
- The `--openshift-sar` flag uses a Notebook-specific SubjectAccessReview (`"resource":"notebooks","resourceAPIGroup":"kubeflow.org"`) rather than a generic secret-based check as in Approach A (see `helm/templates/workbench.yaml`)
- The OAuth proxy upstream is `http://localhost:8888` (Jupyter port) rather than `http://localhost:8000` (FastAPI) as in Approach A (see `helm/templates/workbench.yaml`)

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Target resource | Deployment | Kubeflow Notebook |
| Version compatibility | Always includes sidecar | Conditional: inject-auth on v2+, sidecar on older |
| OAuth proxy image | `origin-oauth-proxy:4.17` (upstream) | `ose-oauth-proxy` (Red Hat, pinned by digest) |
| Auth check method | `--openshift-delegate-urls` (token delegation) | `--openshift-sar` (notebook-level RBAC) |
| Route creation | Explicit Route resource in chart | Notebook controller handles routing |
| ClusterRoleBinding | Required for `system:auth-delegator` | Not needed |

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the umbrella chart this sidecar is part of (Approach A)
- `helm-rbac-toolhive-mcp-discovery.md` -- additional RBAC rules in the same Role (Approach A)
- `helm-workbench-sqlite-sidecar-api-key-injection.md` -- the SQLite sidecar that runs alongside this OAuth proxy in Approach B
- `helm-workbench-notebook-job-exec-git-clone.md` -- alternative workbench pattern that also uses inject-oauth annotation
