---
name: helm-keycloak-openshift-oauth-patch-realmimport
description: RHBK Keycloak subchart with KeycloakRealmImport, OAuth cluster patch Job, and optional kubeadmin removal
summary: "Deploys RHBK Keycloak as a local Helm subchart backed by CloudNative-PG PostgreSQL (credentials auto-derived from `<cluster>-app` secret convention), imports a realm via KeycloakRealmImport CR provisioning N users (realm.user.count/prefix), admins/users groups, admin/user roles, and an OpenID Connect client (redirectUris: [\"*\"], scopes: acr/email/groups/profile/roles), then patches cluster-scoped OAuth via post-install hook Job (`oc patch oauth cluster --type=merge`) to add Keycloak as identity provider. Use when deploying Keycloak-based SSO for OpenShift clusters in quickstarts -- requires RHBK operator, CloudNative-PG operator, and cert-manager; optional removeKubeAdmin flag (idempotent via `||:`) deletes kubeadmin secret, and a ClusterRoleBinding grants Keycloak admin group cluster-admin access. Route uses reencrypt TLS termination with service serving certificates (`service.beta.openshift.io/serving-cert-secret-name`) internally; ingressCA (populated by all-in-one.sh for default ingress certs only) creates a router-ca ConfigMap in openshift-config for self-signed certificate trust, while clusters with custom certificates skip it entirely. Critical gotcha: `--type=merge` on OAuth duplicates identityProviders entries on re-runs; openid-client-secret Secret must exist in openshift-config namespace before the OAuth patch references it; the cluster-admin ClusterRoleBinding for the admin group grants Keycloak-managed admins full cluster access."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, postgresql]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "Local keycloak subchart deploying RHBK with CloudNative-PG PostgreSQL, KeycloakRealmImport for users/groups/roles, OAuth cluster patch via post-install Job, optional kubeadmin removal"
    approach: "A"
---

# Keycloak RHBK Subchart with OAuth Integration and Realm Import

## Overview

This pattern deploys Red Hat Build of Keycloak (RHBK) as a Helm subchart with full OpenShift OAuth integration. It creates a Keycloak instance backed by CloudNative-PG PostgreSQL, imports a realm with users/groups/roles/clients via the `KeycloakRealmImport` CR, patches the OpenShift cluster OAuth configuration to add Keycloak as an identity provider via a post-install hook Job, and optionally removes the kubeadmin user.

## Pattern Description

OpenShift clusters typically use the built-in kubeadmin account or external identity providers. This subchart replaces or augments cluster authentication by deploying a Keycloak instance, creating a realm with pre-provisioned users (user1-user5 and admin), configuring an OpenID Connect identity provider on the cluster OAuth, and optionally deleting the kubeadmin secret. The subchart is a local dependency (not from a remote registry) with its own templates, files, and values.

## Implementation

### Keycloak CR with PostgreSQL Backend

```yaml
# charts/maas-code-assistant/charts/keycloak/templates/keycloak.yaml
apiVersion: k8s.keycloak.org/v2alpha1
kind: Keycloak
metadata:
  name: {{ .Values.name }}
spec:
  db:
    vendor: postgres
    database: {{ .Values.postgresCluster.name }}
    host: {{ .Values.postgresCluster.host | default (printf "%s-rw" .Values.postgresCluster.name) }}
    usernameSecret:
      name: {{ .Values.postgresCluster.credentialsSecret | default (printf "%s-app" .Values.postgresCluster.name) }}
      key: username
    passwordSecret:
      name: {{ .Values.postgresCluster.credentialsSecret | default (printf "%s-app" .Values.postgresCluster.name) }}
      key: password
  hostname:
    hostname: {{ .Values.name }}.{{ .Values.global.wildcardDomain }}
  http:
    httpEnabled: False
    tlsSecret: {{ .Values.name }}-internal-tls
    annotations:
      service.beta.openshift.io/serving-cert-secret-name: {{ .Values.name }}-internal-tls
  ingress:
    enabled: false
  instances: {{ .Values.replicas }}
  additionalOptions:
    - name: enable-recovery
      value: 'true'
```

### KeycloakRealmImport with Users, Groups, and Roles

The realm import creates a full OpenID Connect configuration with user provisioning:

```yaml
# charts/maas-code-assistant/charts/keycloak/templates/realmimport.yaml (abbreviated)
apiVersion: k8s.keycloak.org/v2alpha1
kind: KeycloakRealmImport
metadata:
  name: {{ .Values.realm.name }}
spec:
  keycloakCRName: {{ .Values.name }}
  realm:
    realm: {{ .Values.realm.name }}
    enabled: true
    clients:
      - clientId: {{ .Values.realm.openshiftClientId }}
        secret: {{ .Values.realm.openshiftClientSecret }}
        publicClient: false
        redirectUris: ["*"]
        defaultClientScopes: [acr, basic, email, groups, profile, roles, service_account, web-origins]
    roles:
      realm:
        - name: user
        - name: admin
    users:
      {{- range $i := until (int .Values.realm.user.count) }}
      - username: {{ printf "%s%s" $.Values.realm.user.prefix (toString (add 1 $i)) }}
        credentials:
          - type: password
            value: {{ $.Values.realm.user.password }}
        realmRoles: [user]
        groups: [users]
      {{- end }}
      - username: {{ .Values.realm.admin.username }}
        credentials:
          - type: password
            value: {{ .Values.realm.admin.password }}
        realmRoles: [admin]
        groups: [admins]
    groups:
      - name: admins
      - name: users
```

### OAuth Cluster Patch via Post-Install Job

A post-install Job patches the cluster-scoped OAuth resource to add the Keycloak OpenID Connect identity provider:

```yaml
# charts/maas-code-assistant/charts/keycloak/files/oauth.yaml (templated)
apiVersion: config.openshift.io/v1
kind: OAuth
metadata:
  name: cluster
spec:
  identityProviders:
    - name: rhbk
      type: OpenID
      mappingMethod: claim
      openID:
        {{- if .Values.ingressCA }}
        ca:
          name: router-ca
        {{- end }}
        claims:
          email: [email]
          name: [name]
          preferredUsername: [preferred_username, email, name]
          groups: [groups]
        clientID: {{ .Values.realm.openshiftClientId }}
        clientSecret:
          name: openid-client-secret
        issuer: >-
          https://{{ .Values.name }}.{{ .Values.global.wildcardDomain }}/realms/{{ .Values.realm.name }}
```

The patch is applied imperatively by a Job because it modifies the cluster-scoped `OAuth` resource:

```bash
# charts/maas-code-assistant/charts/keycloak/files/patch-oauth.sh
#!/bin/bash
set -ex
oc patch oauth cluster --patch-file=oauth.yaml --type=merge
```

### Optional kubeadmin Removal

```yaml
# charts/maas-code-assistant/charts/keycloak/templates/job-remove-kubeadmin.yaml
{{- if .Values.removeKubeAdmin }}
apiVersion: batch/v1
kind: Job
metadata:
  name: remove-kubeadmin
  namespace: kube-system
  annotations:
    helm.sh/hook: post-install,post-upgrade
    helm.sh/hook-delete-policy: before-hook-creation
spec:
  template:
    spec:
      containers:
      - name: remove-kubeadmin
        image: {{ .Values.global.toolsImage }}
        command: ["/bin/bash"]
        args:
          - -xc
          - |-
            oc delete secret kubeadmin ||:
{{- end }}
```

### Keycloak Route with Reencrypt TLS

```yaml
# charts/maas-code-assistant/charts/keycloak/templates/route.yaml
kind: Route
apiVersion: route.openshift.io/v1
metadata:
  name: {{ .Values.name }}
spec:
  host: {{ .Values.name }}.{{ .Values.global.wildcardDomain }}
  to:
    kind: Service
    name: {{ .Values.name }}-service
  port:
    targetPort: https
  tls:
    termination: reencrypt
    insecureEdgeTerminationPolicy: Redirect
```

### Ingress CA for Self-Signed Certificates

When the cluster uses non-default ingress certificates, the CA is injected into a ConfigMap for Keycloak's OpenID provider:

```yaml
# charts/maas-code-assistant/charts/keycloak/templates/router-ca.yaml
{{- with .Values.ingressCA }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: router-ca
  namespace: openshift-config
data:
  ca.crt: |-
    {{- . | nindent 4 }}
{{- end }}
```

## Configuration

- **Key settings:** `realm.openshiftClientId` (default: `ocp-idp`), `realm.openshiftClientSecret` (generated per deploy), `realm.user.count` (default: 5), `realm.user.prefix` (default: `user`), `removeKubeAdmin` (default: false), `postgresCluster.name` (default: `keycloak-postgres`)
- **Defaults:** 1 Keycloak replica, 5 users (user1-user5) plus 1 admin, passwords set interactively, SSO realm name, PostgreSQL credentials auto-derived from CloudNative-PG secret naming convention (`<cluster>-app`)
- **Dependencies:** RHBK operator (installed via install-operators subchart), CloudNative-PG operator for PostgreSQL, cert-manager for TLS certificates

## Gotchas

- The OAuth patch uses `--type=merge` which appends to the `identityProviders` array rather than replacing it -- re-running may duplicate the identity provider entry
- The `openid-client-secret` Secret must be created in `openshift-config` namespace (handled by `secret.yaml` template) before the OAuth patch references it
- Keycloak uses OpenShift's service serving certificate (`service.beta.openshift.io/serving-cert-secret-name`) for internal TLS, while external access uses a Route with `reencrypt` termination
- The `ingressCA` value is populated by the `all-in-one.sh` script only when the cluster uses default (non-custom) ingress certificates; clusters with custom certificates leave it empty and skip the `router-ca` ConfigMap
- The `||:` in `oc delete secret kubeadmin ||:` ensures the Job succeeds even if kubeadmin was already removed
- The `cluster-admin` ClusterRoleBinding for the `admin` group in `clusterrolebinding.yaml` grants Keycloak-managed admin users full cluster access

## Related Patterns

- `helm-devworkspace-per-user-namespace-rbac.md` -- creates per-user workspaces matching the users provisioned in the Keycloak realm
- `helm-hook-configmap-mounted-script-jobs.md` -- the patch-oauth and remove-kubeadmin Jobs follow the same SA+RBAC+ConfigMap+Job pattern
- `shell-script-two-phase-helm-cluster-autodetect.md` -- the orchestrator that generates the Keycloak client secret and ingress CA values
