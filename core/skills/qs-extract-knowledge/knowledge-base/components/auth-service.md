---
name: auth-service
description: Keycloak management CLI and JWT middleware for programmatic realm setup, user sync, and OIDC token validation
summary: "Python package (hatchling/uv) providing programmatic Keycloak realm/client/role setup via Admin REST API and FastAPI JWT middleware — replaces static realm JSON or KeycloakRealmImport CRs with a RealmManager that creates PKCE S256 OIDC clients with configurable redirect URIs/web origins. Use when AI quickstarts need Keycloak auth with database user sync (UserManager syncs PostgreSQL users via psycopg2, using DB id as username, stripping +asyncpg driver suffix) and dual-URL JWT validation — KEYCLOAK_URL (internal, 3-env priority: K8s service/container network/localhost) for OIDC discovery and JWKS fetching vs KEYCLOAK_FRONTEND_URL (external) for issuer matching, with hardcoded endpoint fallback when discovery fails and flexible audience validation accepting both client ID and \"account\". Critical config: BYPASS_AUTH auto-enables in development with X-Test-User-Email header for per-user testing; middleware links tokens to DB users via keycloak_id (JWT sub claim) with email fallback and backfill; Helm secrets passed via --set flags (no subchart); JWT_CLOCK_SKEW_LEEWAY_SECONDS defaults to 120. Gotchas: time.sleep(1) required between realm and client creation or client creation fails, 8-hour access token lifespan (vs 15-min default) widens revoked-token window, JWKS cached 1 hour with no manual invalidation so key rotation propagates slowly, and test passwords (password123/admin123) are hardcoded in source."
metadata:
  type: component
tags:
  tech_stack: [python, keycloak, fastapi, requests, python-jose, sqlalchemy, asyncpg, psycopg2]
  ai_pattern: []
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Python CLI for programmatic Keycloak realm/client/user setup via REST API, database user sync, and python-jose JWT middleware with OIDC discovery and dual-URL issuer handling"
    approach: "A"
---

# Auth Service

## Overview

A Python package providing programmatic Keycloak management and JWT authentication middleware for AI Quickstarts. Instead of declarative realm JSON imports or KeycloakRealmImport CRs, this component uses the Keycloak Admin REST API to create realms, configure OIDC clients, provision roles, and sync users from a PostgreSQL database. A companion FastAPI middleware validates JWTs using python-jose with OIDC discovery, dual-URL issuer handling (internal vs external), and a development bypass mode.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 (hatchling build system, uv package manager)
- **Container image:** No dedicated container; runs as a CLI tool against the Keycloak container (`quay.io/keycloak/keycloak:latest`)
- **Key dependencies:** `requests` (Keycloak Admin API calls), `python-jose` (JWT validation in middleware), `sqlalchemy` + `asyncpg` (database user sync), `psycopg2-binary` (synchronous DB queries for user sync)
- **Helm subchart:** None; Keycloak secrets are passed via Helm `--set secrets.*` flags in the Makefile

## Key Patterns

### Programmatic Realm Setup via REST API

Rather than importing a static realm JSON or using a `KeycloakRealmImport` CR, the auth-service creates realms, clients, and roles through the Keycloak Admin REST API. The `RealmManager` class authenticates as the master realm admin and sequentially creates the realm, configures token lifespans, creates the OIDC client, and provisions roles.

```python
# packages/auth/src/keycloak/realm.py
def setup(self) -> bool:
    if not self.get_admin_token():
        return False
    if not self.create_realm():
        return False
    time.sleep(1)  # Brief pause for realm to be ready
    if not self.configure_realm_access_token_lifespan():
        return False
    if not self.create_client():
        return False
    if not self.create_roles():
        return False
    return True
```

### OIDC Client with PKCE S256

The OIDC client is configured as a public client with PKCE S256 enabled, standard flow, and direct access grants. Redirect URIs and web origins are configurable via environment variables with localhost defaults.

```python
# packages/auth/src/keycloak/realm.py
client_data = {
    'clientId': self.client_id,
    'publicClient': True,
    'standardFlowEnabled': True,
    'directAccessGrantsEnabled': True,
    'attributes': {'pkce.code.challenge.method': 'S256'},
    'redirectUris': self._get_redirect_uris(),
    'webOrigins': self._get_web_origins(),
}
```

### Database-to-Keycloak User Sync

The `UserManager` syncs users from a PostgreSQL `users` table into Keycloak, using the database `id` column as the Keycloak username. It handles both `postgresql://` and `postgresql+asyncpg://` URL formats by stripping the driver suffix before connecting with `psycopg2`.

```python
# packages/auth/src/keycloak/users.py
database_url = database_url.replace(
    'postgresql+asyncpg://', 'postgresql://'
)
cursor.execute('SELECT id, email, first_name, last_name FROM users')
for user_id, email, first_name, last_name in db_users:
    username = user_id  # Using 'id' column as username
    self.create_user(username=username, email=email, ...)
```

### Dual-URL Issuer Handling in JWT Middleware

The FastAPI middleware uses two Keycloak URLs: `KEYCLOAK_URL` (internal, for API-to-Keycloak communication) and `KEYCLOAK_FRONTEND_URL` (external, matching the JWT issuer). After OIDC discovery via the internal URL, the issuer is overridden to use the frontend URL so token validation succeeds.

```python
# packages/api/src/auth/middleware.py
# IMPORTANT: Override the issuer to use KEYCLOAK_FRONTEND_URL
# Keycloak returns the issuer based on the URL used to access it
# But tokens are issued with KEYCLOAK_FRONTEND_URL (browser access)
_oidc_config_cache['issuer'] = f'{KEYCLOAK_FRONTEND_URL}/realms/{REALM}'
```

The JWKS URI is similarly rewritten from the discovered (frontend) URL to the internal URL for API-side fetching.

### OIDC Discovery with Hardcoded Fallback

When OIDC discovery fails (Keycloak not yet ready, network issues), the middleware falls back to hardcoded endpoints constructed from the known URL pattern. The fallback uses `KEYCLOAK_FRONTEND_URL` for browser-facing endpoints and `KEYCLOAK_URL` for API-facing endpoints.

```python
# packages/api/src/auth/middleware.py
_oidc_config_cache = {
    'issuer': f'{KEYCLOAK_FRONTEND_URL}/realms/{REALM}',
    'jwks_uri': f'{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/certs',
    'authorization_endpoint': f'{KEYCLOAK_FRONTEND_URL}/realms/{REALM}/protocol/openid-connect/auth',
    'token_endpoint': f'{KEYCLOAK_FRONTEND_URL}/realms/{REALM}/protocol/openid-connect/token',
}
```

### Flexible Audience Validation

The middleware disables `python-jose`'s built-in audience check and performs manual validation, accepting both the application client ID and the Keycloak `account` audience. This accommodates Keycloak's behavior of including multiple audiences in tokens for public clients.

```python
# packages/api/src/auth/middleware.py
claims = jwt.decode(
    token, jwks, algorithms=['RS256'],
    issuer=oidc_config['issuer'],
    options={'verify_exp': True, 'verify_aud': False,
             'leeway': settings.JWT_CLOCK_SKEW_LEEWAY_SECONDS},
)
valid_audiences = [CLIENT_ID, 'account']
audience_list = [audience] if isinstance(audience, str) else audience
if not any(aud in valid_audiences for aud in audience_list):
    raise JWTError('Invalid audience')
```

### BYPASS_AUTH Dev Mode with Test User Header

In development, `BYPASS_AUTH=True` (auto-enabled when `ENVIRONMENT=development`) skips JWT validation entirely. An `X-Test-User-Email` header allows selecting a specific database user for per-user testing without Keycloak running.

```python
# packages/api/src/auth/middleware.py
if settings.BYPASS_AUTH:
    if request is not None:
        test_user_email = request.headers.get('X-Test-User-Email')
        if test_user_email:
            return await get_test_user(test_user_email, session)
    return await get_dev_fallback_user(session)
```

### Keycloak-to-Database User Linking

On production token validation, the middleware looks up the database user by `keycloak_id` (the JWT `sub` claim). If not found, it falls back to email lookup and backfills the `keycloak_id` column for future fast lookups.

```python
# packages/api/src/auth/middleware.py
result = await session.execute(
    select(User).where(User.keycloak_id == keycloak_id)
)
db_user = result.scalar_one_or_none()
if not db_user and user_email:
    result = await session.execute(
        select(User).where(User.email == user_email)
    )
    db_user = result.scalar_one_or_none()
    if db_user:
        db_user.keycloak_id = keycloak_id
        await session.commit()
```

## Configuration

- **Environment variables:**
  - `KEYCLOAK_URL` -- Internal Keycloak URL for API communication (default: `http://spending-monitor-keycloak:8080`)
  - `KEYCLOAK_FRONTEND_URL` -- External Keycloak URL matching JWT issuer (default: `http://localhost:8080`)
  - `KEYCLOAK_REALM` -- Realm name (default: `spending-monitor`)
  - `KEYCLOAK_CLIENT_ID` -- OIDC client ID (default: `spending-monitor`)
  - `KEYCLOAK_ADMIN` -- Admin username (default: `admin`)
  - `KEYCLOAK_ADMIN_PASSWORD` -- Admin password (required for management CLI)
  - `KEYCLOAK_REDIRECT_URIS` -- Comma-separated redirect URIs (default: `http://localhost:3000/*`)
  - `KEYCLOAK_WEB_ORIGINS` -- Comma-separated web origins (default: `http://localhost:3000`)
  - `DATABASE_URL` -- PostgreSQL connection URL (required for `sync-users` command)
  - `KEYCLOAK_DEFAULT_PASSWORD` -- Default password for synced users (default: `password123`)
  - `BYPASS_AUTH` -- Skip JWT validation (default: `false`, auto-enabled in development)
  - `JWT_CLOCK_SKEW_LEEWAY_SECONDS` -- Clock skew tolerance for token validation (default: `120`)
- **Config files:** None; all configuration is via environment variables
- **Helm values:** Keycloak secrets passed via `--set secrets.KEYCLOAK_*` flags in Makefile deploy targets; `KEYCLOAK_FRONTEND_URL` dynamically constructed from namespace and cluster domain

## Known Gotchas

- The `RealmManager.setup()` method includes a `time.sleep(1)` pause between realm creation and client creation. The comment says "Brief pause for realm to be ready" -- removing this can cause client creation to fail if the realm is not fully initialized.
- The `KeycloakClient` uses a dual-URL priority system: `KEYCLOAK_URL` takes precedence when set, falling back to `KEYCLOAK_FRONTEND_URL`. The comment in `client.py` explains this handles three environments: Kubernetes (internal service URL), local containers (container network name), and host scripts (localhost).
- The database user sync uses `psycopg2` (synchronous) even though the rest of the app uses `asyncpg`, because the sync runs as a standalone CLI command outside the async FastAPI context. The `DATABASE_URL` driver suffix (`+asyncpg`, `+psycopg2`) is stripped before connecting.
- The access token lifespan is set to 8 hours (`_DEFAULT_ACCESS_TOKEN_LIFESPAN_SECONDS = 8 * 60 * 60`) in `realm.py`. This is significantly longer than the 15-minute default, reducing token refresh frequency but increasing the window for revoked tokens.
- The `JWT_CLOCK_SKEW_LEEWAY_SECONDS` defaults to `120` (2 minutes) in `config.py`, which is generous. This exists to handle clock drift between Keycloak and the API server.
- Test users have hardcoded passwords (`password123` for testuser, `admin123` for admin) in the `UserManager` class. These are for development only but are committed to the source code.
- The OIDC config and JWKS are cached globally (module-level variables) with a 1-hour TTL. There is no cache invalidation mechanism other than time expiry, so key rotation takes up to 1 hour to propagate.
- The JWKS URI rewriting in `get_jwks()` rewrites the discovered JWKS URI to use `KEYCLOAK_URL` instead of the external URL. This is necessary because the OIDC discovery endpoint returns URLs based on how it was accessed, but the API needs to fetch JWKS via the internal network.

## Testing Notes

- Auth middleware tests live in `packages/auth/tests/test_auth_core.py` but import from `packages/api/src/auth/middleware.py` by adding the API package to `sys.path`
- Tests use `unittest.mock` to mock OIDC config and JWKS responses, and `pytest-asyncio` for async test methods
- The `reset_caches` fixture clears global OIDC/JWKS caches between tests by setting `_oidc_config_cache`, `_jwks_cache`, and `_cache_expiry` to `None`
- Makefile targets for Keycloak management: `make keycloak-users` (list synced users), `make keycloak-users-all` (include test users), `make keycloak-sync-users` (sync DB users), `make seed-keycloak-with-users` (full setup + sync)

## Related Patterns

- Keycloak component (`keycloak.md`) -- the Keycloak server itself and its deployment approaches
- FastAPI backend (`fastapi-backend.md`) -- the API that consumes the JWT middleware
- PostgreSQL (`postgresql.md`) -- the database from which users are synced
