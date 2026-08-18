---
name: helm-keycloak-rhbk-crd-subchart-oidc-autoconfig
description: RHBK Keycloak subchart deploying Keycloak CR + KeycloakRealmImport with auto-generated OIDC redirect URIs from cluster domain
summary: "Deploys RHBK as a namespace-scoped Helm subchart via Keycloak Operator CRDs (Keycloak CR + KeycloakRealmImport) with its own PostgreSQL StatefulSet (postgresql-15-pgvector-c9s, 10Gi PVC), auto-detecting the cluster domain from the openshift-console Route to generate OIDC redirect URIs without manual URL configuration. Use when deploying a standalone identity provider scoped to the quickstart namespace rather than patching cluster-wide OAuth (see helm-keycloak-openshift-oauth-patch-realmimport); requires RHBK Keycloak Operator pre-installed; set proxy.headers: xforwarded and ingress.enabled: false since an OpenShift Route replaces Keycloak ingress. The client-secret Secret must be a regular resource (not a hook) so other templates can lookup its values during Helm rendering; realm.client.clientSecret is required on first install but preserved via lookup on upgrade; the db-secret uses helm.sh/hook: pre-install,pre-upgrade with hook-weight -10; OIDC client uses publicClient: false with standardFlowEnabled: true. The regexReplaceAll \"^console-openshift-console\\\\.\" cluster domain detection fails on custom console hostnames, fallback domain apps.cluster.local allows helm template dry-runs but produces non-functional URLs, wildcarded redirect URIs are less secure than auto-generated specific ones, and realm security settings (bruteForceProtected, ssoSessionIdleTimeout: 1800) are hardcoded rather than configurable via values.yaml."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, postgresql]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Local keycloak subchart deploying RHBK via Keycloak CR with own PostgreSQL StatefulSet, KeycloakRealmImport with OIDC client auto-configured redirect URIs from cluster domain lookup, client-secret Secret for cross-chart sharing"
    approach: "A"
---

# Keycloak RHBK CRD Subchart with OIDC Auto-Configuration

## Overview

This pattern deploys Red Hat Build of Keycloak (RHBK) as a local Helm subchart using the Keycloak Operator CRDs (`Keycloak` and `KeycloakRealmImport`), with auto-generated OIDC redirect URIs derived from the OpenShift cluster domain. It deploys its own PostgreSQL StatefulSet for the Keycloak database and publishes the client secret as a standalone Secret for cross-chart consumption.

## Pattern Description

Unlike the `helm-keycloak-openshift-oauth-patch-realmimport` pattern which patches the cluster-wide OAuth configuration, this pattern deploys Keycloak as a standalone identity provider scoped to the quickstart namespace. The OIDC client redirect URIs are auto-generated from the cluster domain (via console route lookup) combined with the release namespace, so no manual URL configuration is needed. A client-secret Secret is created as a regular (non-hook) resource so that other subcharts can look it up during templating.

## Implementation

### Keycloak CR with Own PostgreSQL

```yaml
# charts/keycloak/templates/keycloak-cr.yaml
apiVersion: k8s.keycloak.org/v2alpha1
kind: Keycloak
metadata:
  name: {{ .Values.applicationName }}
spec:
  instances: {{ .Values.keycloak.instances }}
  db:
    vendor: postgres
    host: {{ .Values.postgres.service.name }}
    usernameSecret:
      name: {{ .Values.applicationName }}-db-secret
      key: username
    passwordSecret:
      name: {{ .Values.applicationName }}-db-secret
      key: password
  hostname:
    strict: false
    strictBackchannel: false
  proxy:
    headers: {{ .Values.keycloak.proxy.headers }}
  ingress:
    enabled: {{ .Values.keycloak.ingress.enabled }}
```

### Cluster Domain Auto-Detection via Console Route

```yaml
# charts/keycloak/templates/_helpers.tpl
{{- define "keycloak.clusterDomain" -}}
{{- $console := lookup "route.openshift.io/v1" "Route" "openshift-console" "console" }}
{{- if $console }}
{{- $host := $console.spec.host }}
{{- regexReplaceAll "^console-openshift-console\\." $host "" }}
{{- else }}
apps.cluster.local
{{- end }}
{{- end }}

{{- define "keycloak.peoplemeshRedirectUri" -}}
{{- $clusterDomain := include "keycloak.clusterDomain" . }}
{{- printf "https://peoplemesh-%s.%s/api/v1/auth/callback/keycloak" .Release.Namespace $clusterDomain }}
{{- end }}
```

### KeycloakRealmImport with Auto-Generated Redirect URIs

The realm import appends the auto-generated redirect URI to the user-provided static URIs:

```yaml
# charts/keycloak/templates/realm-import.yaml (excerpt)
apiVersion: k8s.keycloak.org/v2alpha1
kind: KeycloakRealmImport
spec:
  keycloakCRName: {{ .Values.applicationName }}
  realm:
    realm: {{ .Values.realm.name }}
    clients:
      - clientId: {{ .Values.realm.client.clientId | quote }}
        secret: {{ include "keycloak.clientSecret" . | quote }}
        publicClient: false
        standardFlowEnabled: true
        redirectUris:
        {{- range .Values.realm.client.redirectUris }}
          - {{ . | quote }}
        {{- end }}
          - {{ include "keycloak.peoplemeshRedirectUri" . | quote }}
        webOrigins:
        {{- range .Values.realm.client.webOrigins }}
          - {{ . | quote }}
        {{- end }}
          - {{ include "keycloak.peoplemeshWebOrigin" . | quote }}
```

### Client Secret Published for Cross-Chart Consumption

```yaml
# charts/keycloak/templates/client-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: keycloak-client-secret
  # No hook - created as regular resource so realm-import can lookup during templating
type: Opaque
stringData:
  clientSecret: {{ include "keycloak.clientSecret" . | quote }}
  issuerUrl: {{ include "keycloak.issuerUrl" . | quote }}
```

### PostgreSQL Database Secret with Pre-Install Hook

```yaml
# charts/keycloak/templates/postgres-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ .Values.applicationName }}-db-secret
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "-10"
    "helm.sh/hook-delete-policy": before-hook-creation
type: Opaque
stringData:
  username: {{ .Values.postgres.user | quote }}
  password: {{ include "keycloak.postgresPassword" . | quote }}
```

## Configuration

- **Key settings:** `realm.client.clientSecret` (required on first install, preserved via lookup on upgrade); `proxy.headers: xforwarded` for OpenShift Routes; `ingress.enabled: false` because an OpenShift Route is created instead
- **Defaults:** 1 Keycloak instance; HTTP enabled for development; test user enabled with configurable credentials; wildcard redirect URIs (`https://peoplemesh-*.apps.*`) plus auto-generated specific URI; PostgreSQL StatefulSet with 10Gi PVC
- **Dependencies:** RHBK Keycloak Operator must be installed in the namespace (handled by the installer); the PostgreSQL StatefulSet uses `quay.io/rh-aiservices-bu/postgresql-15-pgvector-c9s` image

## Gotchas

- The client-secret Secret is created as a regular resource (not a hook) specifically so that other templates can use `lookup` to read its values during Helm templating -- hook resources would not yet exist when templates are rendered (see `charts/keycloak/templates/client-secret.yaml` comment on line 12)
- The `regexReplaceAll "^console-openshift-console\\."` pattern assumes the standard OpenShift console route hostname format; clusters with custom console hostnames would produce incorrect cluster domains (see `charts/keycloak/templates/_helpers.tpl`)
- The fallback domain `apps.cluster.local` is used when the console route is not accessible (e.g., during `helm template` dry-run); this produces non-functional URLs but allows template rendering to complete (see `charts/keycloak/templates/_helpers.tpl`)
- The OIDC configuration includes both wildcarded URIs (for any cluster) and specific auto-generated URIs (for the current cluster); the wildcarded URIs provide flexibility but are less secure than the specific ones (see `charts/keycloak/values.yaml` lines 89-94)
- The realm import includes `bruteForceProtected: true` and `ssoSessionIdleTimeout: 1800` security settings directly in the template, not configurable via values.yaml (see `charts/keycloak/templates/realm-import.yaml` lines 31-36)

## Related Patterns

- `helm-keycloak-openshift-oauth-patch-realmimport.md` -- RHBK Keycloak with cluster OAuth integration (different: patches cluster-wide OAuth, uses CloudNative-PG)
- `helm-keycloak-realm-files-get-configmap-dev-mode.md` -- Keycloak dev-mode with Files.Get realm (different: no operator, no CRD)
- `helm-post-install-secret-sync-cross-chart-oidc.md` -- the post-install Job that syncs this secret to the app subchart
- `helm-lookup-secret-idempotency-random-fallback.md` -- the secret preservation pattern used for client and database secrets
