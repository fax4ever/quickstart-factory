---
name: helm-lookup-secret-idempotency-random-fallback
description: Helm lookup function preserves existing secrets on upgrade, falls back to user-provided or auto-generated values on first install
summary: "Prevents Helm secrets (database passwords, OIDC client secrets) from rotating on every helm upgrade by using lookup \"v1\" \"Secret\" .Release.Namespace in _helpers.tpl named templates to reuse existing cluster values via b64dec, falling back to user-provided values or randAlphaNum 24 generation. Umbrella charts use three-tier fallback (lookup/value/random) generating 24-char alphanumeric strings on first install across six templates for keycloak-postgres, pgvector-database, keycloak-client-secret, and peoplemesh-security secrets, while subcharts use two-tier (lookup/required with error message) forcing explicit user-provided values -- choose umbrella pattern for turnkey deploys and subchart pattern when operators must control initial credentials. Secrets are deployed as pre-install/pre-upgrade hooks with hook-weight \"-20\" and before-hook-creation delete policy; values.yaml defaults all secret fields to empty string so lookup or generation handles them, overridable via --set flags. lookup returns nil during helm template dry-runs (subchart required variant fails), before-hook-creation deletes and recreates the Secret each cycle but lookup captures the value before deletion, and umbrella vs subchart templates for the same secret (e.g. pgvector password) differ in fallback behavior when subcharts are installed standalone."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Six named templates in umbrella _helpers.tpl use lookup to preserve keycloak-postgres, pgvector-database, keycloak-client-secret, and peoplemesh-security secrets across upgrades; falls back to required values or randAlphaNum 24"
    approach: "A"
---

# Helm Lookup Secret Idempotency with Random Fallback

## Overview

This pattern uses the Helm `lookup` function in named templates to check whether a Secret already exists in the cluster. If it does, the existing value is reused (preserving it across upgrades). If not, it falls back to a user-provided value (via `required`) or generates a random string. This prevents secrets from rotating on every `helm upgrade` while ensuring they are created on first install.

## Pattern Description

Helm templates normally regenerate values on every install/upgrade. For database passwords and OIDC client secrets, this causes breakage because the database retains the old password while the deployment receives a new one. The solution is a three-tier fallback: (1) lookup existing secret from cluster, (2) use user-provided value, (3) generate random value. The umbrella chart's `_helpers.tpl` defines one named template per secret, each following the same lookup-first pattern.

## Implementation

### Named Template with Lookup-First Pattern

```yaml
# peoplemesh-umbrella/templates/_helpers.tpl
{{- define "peoplemesh-umbrella.keycloakPostgresPassword" -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace "keycloak-postgres" -}}
{{- if $secret -}}
  {{- index $secret.data "POSTGRES_PASSWORD" | b64dec -}}
{{- else if .Values.keycloak.postgres.password -}}
  {{- .Values.keycloak.postgres.password -}}
{{- else -}}
  {{- randAlphaNum 24 -}}
{{- end -}}
{{- end -}}
```

### Multiple Secrets Using the Same Pattern

The umbrella chart defines six templates following this pattern, each for a different secret:

```yaml
# peoplemesh-umbrella/templates/_helpers.tpl (additional templates)
{{- define "peoplemesh-umbrella.pgvectorPostgresPassword" -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace "pgvector-database" -}}
{{- if $secret -}}
  {{- index $secret.data "DATABASE_PASSWORD" | b64dec -}}
{{- else if .Values.pgvector.postgres.password -}}
  {{- .Values.pgvector.postgres.password -}}
{{- else -}}
  {{- randAlphaNum 24 -}}
{{- end -}}
{{- end -}}

{{- define "peoplemesh-umbrella.sessionSecret" -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace "peoplemesh-security" -}}
{{- if $secret -}}
  {{- index $secret.data "SESSION_SECRET" | b64dec -}}
{{- else if .Values.peoplemesh.security.sessionSecret -}}
  {{- .Values.peoplemesh.security.sessionSecret -}}
{{- else -}}
  {{- randAlphaNum 24 -}}
{{- end -}}
{{- end -}}
```

### Subchart Variant with required Instead of Random Fallback

Subcharts use the same lookup-first pattern but use `required` instead of `randAlphaNum` to force the user to provide a value on first install:

```yaml
# charts/pgvector/templates/_helpers.tpl
{{- define "pgvector.postgresPassword" -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace "pgvector-database" -}}
{{- if $secret -}}
  {{- index $secret.data "DATABASE_PASSWORD" | b64dec -}}
{{- else -}}
  {{- required "pgvector.postgres.password is required. Generate with: openssl rand -base64 24" .Values.postgres.password -}}
{{- end -}}
{{- end }}
```

### Secret Consumed by Hook-Created Resources

The secrets are consumed in pre-install hook resources to ensure consistent passwords:

```yaml
# charts/pgvector/templates/secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ .Values.applicationName }}-database
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "-20"
    "helm.sh/hook-delete-policy": before-hook-creation
type: Opaque
stringData:
  DATABASE_PASSWORD: {{ include "pgvector.postgresPassword" . | quote }}
```

## Configuration

- **Key settings:** Each secret field in values.yaml defaults to empty string `""`, meaning the lookup or generation will handle it; users can provide explicit values via `--set` flags
- **Defaults:** All secrets default to empty string in values.yaml; the umbrella chart generates random 24-character alphanumeric strings if no value is provided and no existing secret is found; subcharts require explicit values
- **Dependencies:** Requires Helm to be running against a live cluster (the `lookup` function returns empty during `helm template` dry-run, which would cause the subchart `required` variant to fail)

## Gotchas

- The `lookup` function does not work during `helm template` (dry-run) -- it always returns nil, so the template falls through to the provided value or generates a new random one; this is expected and safe for `helm template` use (see `peoplemesh-umbrella/templates/_helpers.tpl`)
- The umbrella chart and subcharts both define templates for the same secrets (e.g., pgvector password) -- the umbrella uses the three-tier fallback (lookup/value/random) while the subchart uses two-tier (lookup/required), creating a difference in behavior when subcharts are installed standalone vs via umbrella (see `charts/pgvector/templates/_helpers.tpl` vs `peoplemesh-umbrella/templates/_helpers.tpl`)
- The `b64dec` function is used to decode the existing secret value because Kubernetes stores Secret data as base64-encoded -- the lookup returns the raw Secret object with `.data` fields (see `peoplemesh-umbrella/templates/_helpers.tpl`)
- The `before-hook-creation` delete policy on the Secret hooks means the Secret is deleted and recreated on each install/upgrade cycle, but the lookup happens before deletion so the value is preserved (see `charts/pgvector/templates/secrets.yaml` annotation)

## Related Patterns

- `helm-umbrella-all-local-file-ref-conditional-deps.md` -- the umbrella chart structure that uses these secret templates
- `helm-lookup-openshift-ingress-autodiscovery.md` -- another use of Helm lookup for runtime cluster introspection
