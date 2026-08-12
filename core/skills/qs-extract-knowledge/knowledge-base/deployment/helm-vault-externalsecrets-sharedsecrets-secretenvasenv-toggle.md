---
name: helm-vault-externalsecrets-sharedsecrets-secretenvasenv-toggle
description: Helm secrets with External Secrets Operator for Vault, shared secrets autoMount, and secretEnvAsEnv local toggle
summary: "Three-tier Helm secrets pattern for production (Vault via ESO with JWT auth using vault-service-account, SecretStore/ExternalSecret with refreshInterval and v2 KV), staging (sharedSecrets with autoMount injecting {project.name}-credentials via envFrom on all pods), and local/Kind (secretEnvAsEnv toggle switching per-app secretEnv from valueFrom.secretKeyRef to plain value: strings). Use when a single chart must target Vault-backed production, shared-secret staging, and Kind/local environments -- select tier via externalSecrets.enabled, sharedSecrets.enabled + autoMount, and the secretEnvAsEnv boolean; sourced from rh-research AI-Q Blueprint. Critical config: per-app secretEnv maps env var names to shared secret keys plus a global secretEnv block for cross-app secrets; ESO auto-creates vault-service-account SA with JWT audiences and expirationSeconds 600. Gotchas: secretEnvAsEnv true leaks values as plaintext in helm template/debug output (local-only); sharedSecrets autoMount exposes all secrets to all pods with no per-app filtering; targetSecretName defaults to {project.name}-credentials which must be created externally or by ESO before pods start."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [kubernetes]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "AI-Q Blueprint with three-tier secrets: Vault ESO, shared secrets envFrom, and secretEnvAsEnv for Kind/local dev"
    approach: "A"
---

# Helm Vault External Secrets with Shared Secrets and secretEnvAsEnv Toggle

## Overview

A three-tier secrets management pattern in Helm that supports production (Vault via External Secrets Operator), staging (shared Kubernetes secrets mounted via `envFrom`), and local development (secrets inlined as plain env vars) from the same chart. A single `secretEnvAsEnv` boolean toggle switches between secure `secretKeyRef` injection and plain environment variable injection for local/Kind clusters.

## Pattern Description

The chart supports three layers of secret management: (1) External Secrets Operator (ESO) integration for pulling secrets from HashiCorp Vault, (2) a `sharedSecrets` mechanism that creates a single Kubernetes Secret mounted on all pods via `envFrom`, and (3) per-app `secretEnv` mappings that reference keys from the shared secret. The `secretEnvAsEnv` toggle changes how per-app `secretEnv` is rendered -- as `valueFrom.secretKeyRef` references (production) or as plain `value:` environment variables (local dev).

## Implementation

### External Secrets Operator Configuration

The chart supports ESO with Vault backend for production environments. The SecretStore and ExternalSecret resources are created when `externalSecrets.enabled` is true.

```yaml
externalSecrets:
  enabled: false
  createSecretStore: true
  secretStoreRef:
    name: ""  # Auto-generated: {project.name}-secret-store
    kind: SecretStore
  refreshInterval: "60m"
  vault:
    server: ""
    namespace: ""
    path: ""
    version: "v2"
    auth:
      jwt:
        path: ""
        role: ""  # Format: {project.name}-{deploymentEnv}
        serviceAccountName: "vault-service-account"
        audiences:
          - "https://kubernetes.default.svc"
        expirationSeconds: 600
```

### Shared Secrets with autoMount

When enabled, a single shared secret is mounted on all pods via `envFrom`, eliminating per-app secret configuration.

```yaml
sharedSecrets:
  enabled: true
  autoMount: true
  refreshInterval: 5m
  targetSecretName: ""  # Auto-generated: {project.name}-credentials
```

The deployment template auto-injects the shared secret as `envFrom`:

```yaml
{{- if or $appConfig.envFrom (and $.Values.sharedSecrets.enabled $.Values.sharedSecrets.autoMount) }}
envFrom:
{{- if and $.Values.sharedSecrets.enabled $.Values.sharedSecrets.autoMount }}
- secretRef:
    name: {{ $.Values.sharedSecrets.targetSecretName | default (printf "%s-credentials" $.Values.project.name) }}
{{- end }}
{{- end }}
```

### secretEnvAsEnv Toggle

The critical toggle that changes per-app `secretEnv` rendering. When `secretEnvAsEnv: false` (production), secrets render as `secretKeyRef`:

```yaml
# Per-app secretEnv definition in values:
postgres:
  secretEnv:
    POSTGRES_USER: DB_USER_NAME
    POSTGRES_PASSWORD: DB_USER_PASSWORD

# Renders as (secretEnvAsEnv: false):
- name: POSTGRES_USER
  valueFrom:
    secretKeyRef:
      name: aiq-credentials
      key: DB_USER_NAME
```

When `secretEnvAsEnv: true` (Kind/local dev), the same values render as plain env vars:

```yaml
# Renders as (secretEnvAsEnv: true):
- name: POSTGRES_USER
  value: "DB_USER_NAME"
```

### Global secretEnv

In addition to per-app `secretEnv`, a global `secretEnv` block provides secrets to all apps:

```yaml
secretEnvAsEnv: false

secretEnv:
  SERPER_API_KEY: ""
```

## Configuration

- **Key settings:** `externalSecrets.enabled` for Vault integration; `sharedSecrets.enabled` + `sharedSecrets.autoMount` for shared secret mounting; `secretEnvAsEnv` for dev/prod toggle
- **Defaults:** External secrets disabled; shared secrets disabled; secretEnvAsEnv false (production mode)
- **Dependencies:** External Secrets Operator CRDs must be installed for Vault integration; Kubernetes Secret with name `{project.name}-credentials` must exist for shared secrets

## Gotchas

- The `secretEnvAsEnv: true` mode injects the secret VALUES as raw strings in the rendered manifest, which means `helm template` output or any Helm debug output will contain secret values in plaintext -- only use for local/Kind development
- When `sharedSecrets.autoMount` is true, ALL apps in the chart receive all shared secrets via `envFrom` -- there is no per-app filtering, so every pod sees every secret
- The `targetSecretName` auto-generates as `{project.name}-credentials` if not specified -- the Kubernetes Secret with this name must be created externally (or by ESO) before the chart's pods can start
- A dedicated `vault-service-account` ServiceAccount is auto-created in the `serviceaccount.yaml` template when `externalSecrets.enabled` is true

## Related Patterns

- `helm-data-driven-app-map-appdefaults-deep-merge.md` -- the app map pattern that consumes these secret configurations
