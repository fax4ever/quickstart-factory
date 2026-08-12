---
name: keycloak
description: Keycloak OIDC identity provider deployed via operator CR or raw container with realm import and JWT validation
summary: "Keycloak provides SSO and identity management for OpenShift quickstarts via two approaches: Approach A deploys via Red Hat Build of Keycloak Operator (k8s.keycloak.org/v2alpha1 CR) with CNPG PostgreSQL (XA-enabled), automated OAuth patching via cluster-admin Helm post-install Job, bulk user provisioning with oidc-usermodel-realm-role-mapper mapping realm roles to OpenShift groups claims, and ClusterRoleBinding granting admin role full cluster-admin; Approach B uses raw quay.io/keycloak/keycloak:26.0 in dev mode (embedded H2) for application-level OIDC with domain-specific roles (borrower/loan_officer/underwriter/ceo), PyJWT JWKS-cached validation with kid-mismatch cache-bust retry, keycloak-js PKCE S256 frontend, AUTH_DISABLED dev bypass with X-Dev-Role simulation, and DataScope-driven per-role data scoping. Use Approach A for cluster-wide SSO requiring OpenShift OAuth integration and RBAC via ClusterRoleBinding; use Approach B for per-application persona-based auth without cluster privileges -- chart is disabled by default (keycloak.enabled: false) in both approaches and must be explicitly enabled. Approach A creates openid-client-secret in openshift-config namespace (not Keycloak namespace), connects to CNPG Postgres via convention-based secret (<cluster-name>-app), uses TLS re-encryption at Route <name>.<wildcardDomain> with serving certs, and supports ingressCA for custom CA injection; Approach B constructs JWT issuer as {KEYCLOAK_ISSUER or KEYCLOAK_URL}/realms/{realm} with accessTokenLifespan 900s and frontend token refresh 60s pre-expiry. Approach A's removeKubeAdmin (default false) permanently deletes kubeadmin secret, external Postgres requires overriding both postgresCluster.host and credentialsSecret together, and OAuth patching requires cluster-admin in openshift-authentication namespace; Approach B's directAccessGrantsEnabled enables deprecated ROPC flow (OAuth 2.1), demo passwords are hardcoded in realm JSON (not env-driven), and Keycloak only starts with compose --profile auth or --profile full."
metadata:
  type: component
tags:
  tech_stack: [keycloak, postgresql, helm, fastapi, react, python, nodejs]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "Keycloak as OpenShift OAuth identity provider with operator CR, CNPG postgres, realm import, and automated OAuth patching"
    approach: "A"
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Keycloak as application-level OIDC provider with raw container Deployment, realm JSON import, domain-specific RBAC roles, PyJWT validation, and keycloak-js frontend SDK"
    approach: "B"
---

# Keycloak

## Overview

Keycloak provides SSO and identity management for OpenShift quickstarts, deployed via the Red Hat Build of Keycloak Operator using the `k8s.keycloak.org/v2alpha1` Keycloak CR. In maas-code-assistant, it serves as an OpenShift OAuth identity provider, configuring user authentication with a pre-provisioned realm, bulk demo users, and automated cluster OAuth patching via Helm post-install hooks.

## Tech Stack & Dependencies

- **Runtime:** Red Hat Build of Keycloak (operator-managed)
- **Container image:** Managed by the Keycloak Operator (no direct image reference in the chart)
- **Key dependencies:** Red Hat Build of Keycloak Operator, CloudNativePG Operator (for Postgres backend), OpenShift OAuth (cluster-level patching)
- **Helm subchart:** Custom subchart at `charts/maas-code-assistant/charts/keycloak/` (v0.1.0)
- **Tools image:** `image-registry.openshift-image-registry.svc:5000/openshift/tools:latest` (used for OAuth patching and kubeadmin removal jobs)

## Key Patterns

### Operator-Managed Keycloak via CR

The chart deploys Keycloak using the `k8s.keycloak.org/v2alpha1` Keycloak CR rather than a raw Deployment. The CR configures the Postgres backend, TLS via OpenShift serving certs, and XA transaction recovery.

```yaml
# templates/keycloak.yaml
apiVersion: k8s.keycloak.org/v2alpha1
kind: Keycloak
metadata:
  name: {{ .Values.name }}
spec:
  db:
    vendor: postgres
    host: {{ .Values.postgresCluster.host | default (printf "%s-rw" .Values.postgresCluster.name) }}
    usernameSecret:
      name: {{ .Values.postgresCluster.credentialsSecret | default (printf "%s-app" .Values.postgresCluster.name) }}
      key: username
  http:
    httpEnabled: False
    tlsSecret: {{ .Values.name }}-internal-tls
    annotations:
      service.beta.openshift.io/serving-cert-secret-name: {{ .Values.name }}-internal-tls
  ingress:
    enabled: false
  transaction:
    xaEnabled: true
```

### CNPG PostgreSQL Backend

Keycloak's database is provisioned as a CloudNativePG `Cluster` CR. Credentials are automatically generated by the CNPG operator and consumed by the Keycloak CR using convention-based secret naming (`<cluster-name>-app`).

```yaml
# templates/cluster.yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: {{ $cluster.name }}
spec:
  instances: {{ $cluster.instances | default 1 }}
  storage:
    {{- toYaml ($cluster.storage | default ("{\"size\": \"2Gi\"}" | fromJson)) | nindent 4 }}
  bootstrap:
    initdb:
      database: {{ $cluster.name }}
      owner: {{ $cluster.name }}
```

### Realm Import with Bulk User Provisioning

The chart uses `KeycloakRealmImport` CR to declaratively create a realm with an OpenID Connect client for OpenShift, role mappings, and templated bulk demo users.

```yaml
# templates/realmimport.yaml (users section)
users:
  {{- range $i := until (int .Values.realm.user.count) }}
  {{- $username := printf "%s%s" $.Values.realm.user.prefix (toString (add 1 $i)) }}
  - username: {{ $username }}
    enabled: true
    email: {{ $username }}@demo.redhat.com
    credentials:
      - type: password
        value: {{ $.Values.realm.user.password }}
        temporary: false
    realmRoles:
      - user
  {{- end }}
```

User count and prefix are configurable via `realm.user.count` (default 5) and `realm.user.prefix` (default "user"), generating usernames like `user1`, `user2`, etc.

### Automated OpenShift OAuth Patching

A Helm post-install/post-upgrade Job patches the cluster-level OAuth configuration to register Keycloak as an OpenID identity provider. The Job uses a ServiceAccount with `cluster-admin`, runs in the `openshift-authentication` namespace, and applies a templated OAuth merge patch.

```yaml
# templates/job-patch-oauth.yaml (Job spec)
annotations:
  helm.sh/hook: post-install,post-upgrade
  helm.sh/hook-delete-policy: before-hook-creation
spec:
  containers:
  - name: patch-oauth
    image: {{ .Values.global.toolsImage }}
    command: ["/app/patch-oauth.sh"]
```

```bash
# files/patch-oauth.sh
#!/bin/bash
set -ex
oc patch oauth cluster --patch-file=oauth.yaml --type=merge
```

The OAuth patch configures Keycloak as an OpenID provider with claim mappings for email, name, preferred_username, and groups.

### OpenShift Route with TLS Re-encryption

Keycloak is exposed via an OpenShift Route with TLS re-encryption. The Route terminates TLS at the router and re-encrypts to the Keycloak service using the internal serving cert.

```yaml
# templates/route.yaml
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

### Optional Kubeadmin Removal

The chart includes an optional post-install Job to remove the `kubeadmin` secret, controlled by `removeKubeAdmin: false` (default disabled). When enabled, it deletes the kubeadmin secret from `kube-system`, forcing all authentication through Keycloak.

```yaml
# templates/job-remove-kubeadmin.yaml
{{- if .Values.removeKubeAdmin }}
# ...Job runs:
command: ["/bin/bash"]
args:
  - -xc
  - |-
    oc delete secret kubeadmin ||:
{{- end }}
```

### Custom Ingress CA Support

When the cluster uses a custom ingress certificate, the `ingressCA` value injects a CA bundle ConfigMap into `openshift-config` for OAuth trust.

```yaml
# templates/router-ca.yaml
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

- **Environment variables:** None directly set; all configuration is via the Keycloak CR and realm import
- **Config files:** `files/oauth.yaml` (templated OAuth patch for OpenShift cluster), `files/patch-oauth.sh` (script executed by the patching Job)
- **Helm values:**
  - `global.wildcardDomain` -- OpenShift apps domain (e.g., `apps.cluster.example.com`)
  - `global.toolsImage` -- Image with `oc` CLI for patching jobs
  - `namespace` -- Target namespace for Keycloak (default: `keycloak`)
  - `replicas` -- Keycloak instance count (default: `1`)
  - `realm.create` -- Whether to create the SSO realm (default: `true`)
  - `realm.name` -- Realm name (default: `sso`)
  - `realm.openshiftClientId` / `realm.openshiftClientSecret` -- OpenID client credentials for OpenShift OAuth
  - `realm.user.prefix` / `realm.user.count` / `realm.user.password` -- Bulk demo user configuration
  - `realm.admin.username` / `realm.admin.password` -- Admin user credentials
  - `removeKubeAdmin` -- Delete kubeadmin secret after install (default: `false`)
  - `postgresCluster.create` -- Whether to create the CNPG cluster (default: `true`)
  - `postgresCluster.name` -- Postgres cluster name (default: `keycloak-postgres`)
  - `postgresCluster.host` / `postgresCluster.credentialsSecret` -- Override for external Postgres
  - `ingressCA` -- Custom CA certificate PEM for ingress trust

## Known Gotchas

- The chart is disabled by default in the parent chart (`keycloak.enabled: false` in `charts/maas-code-assistant/values.yaml`), so it must be explicitly enabled for deployments that need SSO.
- The OAuth patching Job runs in the `openshift-authentication` namespace with `cluster-admin` privileges, which requires elevated permissions at install time.
- The CNPG Postgres host defaults to the convention `<cluster-name>-rw` (the read-write service) -- if using an external Postgres, both `postgresCluster.host` and `postgresCluster.credentialsSecret` must be overridden together.
- The `openid-client-secret` Secret is created in `openshift-config` namespace (not the Keycloak namespace), as required by the OpenShift OAuth configuration.
- The `ClusterRoleBinding` in `clusterrolebinding.yaml` grants `cluster-admin` to the `admin` group -- this maps the Keycloak "admin" realm role to full cluster access.
- The realm import includes a `groups` client scope with `oidc-usermodel-realm-role-mapper` that maps realm roles to a `groups` claim, which is then consumed by the OpenShift OAuth `groups` claim mapping. This enables Keycloak realm roles to drive OpenShift RBAC.

## Testing Notes

- Verify the Keycloak CR reaches `Ready` status: the operator must be installed and the CNPG Postgres cluster must be healthy first
- Check that the `patch-oauth` Job completes successfully in the `openshift-authentication` namespace
- Test login flow by navigating to the OpenShift console -- the "rhbk" identity provider should appear on the login page
- Confirm demo users (`user1` through `user5` by default) can log in with the configured password
- Verify the Route is accessible at `https://<name>.<wildcardDomain>` with valid TLS

## Related Patterns

- CNPG PostgreSQL operator pattern (see `pgvector.md` for another CNPG usage)
- OpenShift OAuth integration
- Helm post-install hooks for cluster-level configuration

---

## Approach B: Application-Level OIDC with Raw Container (from multi-agent-loan-origination)

### When to Use

When the quickstart needs application-level authentication (not cluster-level OpenShift OAuth) with domain-specific roles, where Keycloak provides OIDC tokens consumed directly by a FastAPI backend and React frontend. Suitable for multi-persona applications where different users have different capabilities (e.g., borrower vs loan officer vs underwriter).

### Differences from Approach A

- **Deployment:** Raw `quay.io/keycloak/keycloak:26.0` container as a Kubernetes Deployment (not operator CR)
- **Database:** Uses Keycloak's embedded H2 in dev mode (`start-dev`), no external Postgres for Keycloak itself
- **Auth integration:** Application-level JWT validation via JWKS endpoint, not OpenShift OAuth patching
- **Realm config:** Static JSON file mounted as a volume, not `KeycloakRealmImport` CR
- **Roles:** Domain-specific realm roles (borrower, loan_officer, underwriter, ceo, admin), not generic SSO roles
- **Dev bypass:** `AUTH_DISABLED=true` environment variable to skip JWT validation entirely for local dev

### Tech Stack & Dependencies

- **Runtime:** Keycloak 26.0 in dev mode (`start-dev --import-realm`)
- **Container image:** `quay.io/keycloak/keycloak:26.0`
- **Key dependencies:** PyJWT (backend JWT validation), keycloak-js 26.x (frontend SDK), httpx (JWKS fetching)
- **Helm subchart:** Inline in parent chart at `deploy/helm/mortgage-ai/templates/keycloak.yaml`

### Key Patterns

#### Realm JSON Import via Volume Mount

The realm definition is a static JSON file mounted into the Keycloak container at `/opt/keycloak/data/import/`. The `--import-realm` flag imports it on startup. This avoids the need for the Keycloak Operator or `KeycloakRealmImport` CRs.

```yaml
# compose.yml -- keycloak service
keycloak:
  image: quay.io/keycloak/keycloak:26.0
  command: start-dev --import-realm
  environment:
    KC_BOOTSTRAP_ADMIN_USERNAME: admin
    KC_BOOTSTRAP_ADMIN_PASSWORD: admin
    KC_HEALTH_ENABLED: "true"
  volumes:
    - ./config/keycloak/mortgage-ai-realm.json:/opt/keycloak/data/import/mortgage-ai-realm.json:ro
```

#### Domain-Specific Realm Roles with PKCE Client

The realm defines application-specific roles and a public OIDC client with PKCE (S256) enabled. A separate bearer-only client validates API tokens.

```json
{
  "realm": "mortgage-ai",
  "roles": {
    "realm": [
      { "name": "admin" },
      { "name": "borrower" },
      { "name": "loan_officer" },
      { "name": "underwriter" },
      { "name": "ceo" }
    ]
  },
  "clients": [
    {
      "clientId": "mortgage-ai-ui",
      "publicClient": true,
      "directAccessGrantsEnabled": true,
      "attributes": { "pkce.code.challenge.method": "S256" }
    },
    { "clientId": "mortgage-ai-api", "bearerOnly": true }
  ]
}
```

#### Backend JWT Validation with JWKS Caching

The FastAPI backend validates JWTs directly against Keycloak's JWKS endpoint using PyJWT. JWKS keys are cached with a configurable TTL and automatically refreshed on key rotation (kid mismatch).

```python
# packages/api/src/middleware/auth.py
async def _fetch_jwks() -> dict:
    url = f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=5)
    response.raise_for_status()
    return response.json()

async def _decode_token(token: str) -> TokenPayload:
    signing_key = await _get_signing_key(token)
    base = settings.KEYCLOAK_ISSUER or settings.KEYCLOAK_URL
    issuer = f"{base}/realms/{settings.KEYCLOAK_REALM}"
    payload = jwt.decode(
        token, signing_key.key, algorithms=["RS256"],
        issuer=issuer, audience=settings.KEYCLOAK_CLIENT_ID,
        options={"verify_aud": True},
    )
    return TokenPayload(**payload)
```

#### AUTH_DISABLED Dev Bypass with Role Simulation

When `AUTH_DISABLED=true`, the middleware returns a synthetic dev user without any JWT validation. The role can be overridden via the `X-Dev-Role` header, enabling per-role testing without Keycloak.

```python
# packages/api/src/middleware/auth.py
async def get_current_user(request: Request) -> UserContext:
    if settings.AUTH_DISABLED:
        role_header = request.headers.get("x-dev-role")
        role = _DEV_ROLE_MAP.get(role_header.lower()) if role_header else None
        dev_user = _build_dev_user(
            role or UserRole.ADMIN,
            user_id=request.headers.get("x-dev-user-id", "dev-user"),
            email=request.headers.get("x-dev-user-email", "dev@example.com"),
        )
        return dev_user
```

#### Frontend keycloak-js Integration with Dual Auth Modes

The React frontend uses the `keycloak-js` SDK for SSO when `KEYCLOAK_URL` is configured, or falls back to a dev mode with simulated users. Runtime config (from Nginx-injected `__RUNTIME_CONFIG__`) takes precedence over Vite env vars.

```typescript
// packages/ui/src/contexts/auth-context.tsx
const KEYCLOAK_URL = _rtc?.KEYCLOAK_URL
    || import.meta.env.VITE_KEYCLOAK_URL || undefined;
const IS_KEYCLOAK_ENABLED = !!KEYCLOAK_URL;

// Keycloak SSO init with PKCE
kc.init({
    onLoad: 'check-sso',
    silentCheckSsoRedirectUri: `${window.location.origin}/silent-check-sso.html`,
    pkceMethod: 'S256',
});
```

#### Role-Based Data Scoping from JWT Claims

Realm roles from the JWT `realm_access.roles` claim drive a `DataScope` that controls data visibility per persona. This is enforced server-side in the auth middleware.

```python
# packages/api/src/core/auth.py
def build_data_scope(role: UserRole, user_id: str) -> DataScope:
    if role == UserRole.BORROWER:
        return DataScope(own_data_only=True, user_id=user_id)
    if role == UserRole.LOAN_OFFICER:
        return DataScope(assigned_to=user_id)
    if role == UserRole.CEO:
        return DataScope(pii_mask=True, document_metadata_only=True)
    if role == UserRole.UNDERWRITER:
        return DataScope(full_pipeline=True)
    return DataScope()
```

#### Helm Deployment with Optional Toggle

On OpenShift, Keycloak deploys as a standard Deployment with admin credentials from a Secret, the realm JSON from a ConfigMap, and proxy header support for OpenShift Routes.

```yaml
# deploy/helm/mortgage-ai/templates/keycloak.yaml
{{- if .Values.keycloak.enabled }}
# ConfigMap with realm JSON, Deployment, Service
containers:
  - name: keycloak
    image: "{{ .Values.keycloak.image.repository }}:{{ .Values.keycloak.image.tag }}"
    args: ["start-dev", "--import-realm"]
    env:
      - name: KC_PROXY_HEADERS
        value: "xforwarded"
      - name: KC_HTTP_ENABLED
        value: "true"
{{- end }}
```

### Configuration

- **Environment variables:**
  - `KEYCLOAK_URL` -- Keycloak server URL (default: `http://localhost:8080`)
  - `KEYCLOAK_ISSUER` -- JWT issuer URL if different from KEYCLOAK_URL (e.g., external Route)
  - `KEYCLOAK_REALM` -- Realm name (default: `mortgage-ai`)
  - `KEYCLOAK_CLIENT_ID` -- OIDC client ID (default: `mortgage-ai-ui`)
  - `JWKS_CACHE_TTL` -- JWKS cache lifetime in seconds (default: `300`)
  - `AUTH_DISABLED` -- Bypass JWT validation for dev (default: `false`)
  - `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD` -- Keycloak admin credentials
- **Config files:** `config/keycloak/mortgage-ai-realm.json` -- full realm definition with roles, clients, protocol mappers, and demo users
- **Helm values:**
  - `keycloak.enabled` -- Deploy Keycloak (default: `true`)
  - `keycloak.image.repository` / `keycloak.image.tag` -- Container image (default: `quay.io/keycloak/keycloak:26.0`)
  - `keycloak.resources` -- Resource requests/limits (512Mi-1536Mi memory)
  - `secrets.AUTH_DISABLED` -- Auth bypass flag (default: `false`)

### Known Gotchas

- The `KEYCLOAK_ISSUER` setting exists because the issuer in the JWT may differ from the internal `KEYCLOAK_URL` when Keycloak is behind an OpenShift Route. The backend constructs the expected issuer as `{KEYCLOAK_ISSUER or KEYCLOAK_URL}/realms/{realm}` and validates against it. Mismatched issuers cause `InvalidTokenError`.
- The JWKS key rotation handling in `_get_signing_key` does a cache-bust retry when a `kid` is not found. This prevents authentication failures during Keycloak key rotation, but means a single bad token can force a JWKS refresh for all coroutines.
- The realm JSON has `directAccessGrantsEnabled: true` on the public client, which enables the ROPC (Resource Owner Password Credentials) flow used by the sign-in page. This is explicitly noted as deprecated in OAuth 2.1 in a code comment: "ROPC is deprecated in OAuth 2.1. For production, switch to Authorization Code + PKCE flow (already configured on the client)."
- Demo user passwords are set to `"demo"` (and admin to `"admin"`) in the realm JSON. These are not environment-variable driven and must be changed for non-demo deployments.
- The compose profile system means Keycloak only starts with `--profile auth` or `--profile full`. Without it, `AUTH_DISABLED` defaults to `true` and auth is bypassed entirely.
- The `accessTokenLifespan` is set to 900 seconds (15 minutes) and `ssoSessionMaxLifespan` to 28800 seconds (8 hours) in the realm JSON. The frontend schedules token refresh 60 seconds before expiry.

### Testing Notes

- Run API tests with `AUTH_DISABLED=true` to bypass Keycloak: `cd packages/api && AUTH_DISABLED=true uv run pytest -v`
- Test auth behavior with `AUTH_DISABLED=false` and mock JWKS using monkeypatch (see `packages/api/tests/test_auth.py`)
- Verify role-based access by setting `X-Dev-Role` header in dev mode
- For full-stack auth testing, start Keycloak with `podman-compose --profile auth up -d` and set `AUTH_DISABLED=false`

### Related Patterns

- FastAPI dependency injection for auth (`CurrentUser = Annotated[UserContext, Depends(get_current_user)]`)
- Role-based route guards (`require_roles(*allowed_roles)` dependency factory)
- keycloak-js with runtime config injection for containerized frontends

---

## Choosing Between Approaches

| Criteria | Approach A (Operator CR) | Approach B (Raw Container) |
|----------|--------------------------|----------------------------|
| Deployment method | Keycloak Operator CR (`k8s.keycloak.org/v2alpha1`) | Raw container Deployment |
| Database | CNPG PostgreSQL cluster | Embedded H2 (dev mode) |
| Auth integration | OpenShift OAuth (cluster-level SSO) | Application-level OIDC (JWT validation) |
| Realm provisioning | `KeycloakRealmImport` CR with templated users | Static JSON file via volume mount |
| Role model | Generic SSO roles mapped to OpenShift groups | Domain-specific roles (borrower, underwriter, etc.) |
| User provisioning | Bulk templated users (user1..userN) | Named demo personas with fixed UUIDs |
| TLS | OpenShift serving certs with Route re-encryption | Keycloak dev mode (HTTP), TLS at Route/proxy level |
| Dev experience | Requires Keycloak Operator installed | `AUTH_DISABLED=true` bypass, no Keycloak needed |
| Cluster privileges | Requires `cluster-admin` for OAuth patching | No cluster-level changes needed |
| Best for | Cluster-wide SSO for all OpenShift users | Per-application auth with persona-based RBAC |
