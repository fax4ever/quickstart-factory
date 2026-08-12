---
name: deploy-script-conditional-env-helm-set-cluster-autodiscovery
description: Deploy shell script with add_if_set() conditional env-to-Helm-set injection, cluster domain autodiscovery, and values.local.yaml override
summary: "Solves conditional injection of 40+ environment variables as Helm --set arguments during helm upgrade --install, preventing empty env vars from overriding chart values.yaml defaults while auto-discovering the OpenShift cluster domain for Route hostname computation. Use when a Helm chart has many secrets and configuration values that may or may not be set at deploy time and empty strings would break defaults; related patterns include makefile-split-cluster-local-interactive-env for interactive env setup and shell-script-two-phase-helm-cluster-autodetect for multi-phase deploys. Core mechanism is add_if_set() using bash indirect expansion ${!env_var:-} to conditionally append to a SET_ARGS array, cluster domain extracted via oc whoami --show-server | sed -E converting api.* to apps.*, gitignored values.local.yaml for cluster overrides, feature toggle defaults like KEYCLOAK_ENABLED=true, --wait --wait-for-jobs with 15m timeout, and env file sourced only when explicitly changed from default via set -a/set +a. The .env file is deliberately NOT auto-sourced because it contains localhost URLs (e.g. http://localhost:1234/v1) that override cluster-internal defaults; ${!env_var:-} indirect expansion is bash-only (not POSIX); the api-to-apps sed conversion assumes standard OpenShift naming convention; and failed deploys print a \"make debug\" guidance message."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "deploy.sh with add_if_set() for 40+ conditional --set args, oc whoami cluster domain discovery, values.local.yaml support, feature toggles with safe defaults"
    approach: "A"
---

# Deploy Script with Conditional Env Var Injection and Cluster Autodiscovery

## Overview

This pattern wraps `helm upgrade --install` in a shell script that conditionally maps environment variables to Helm `--set` arguments only when they are non-empty. It prevents empty env vars from overriding the chart's `values.yaml` defaults, auto-discovers the OpenShift cluster domain for Route hostnames, and supports a gitignored `values.local.yaml` for cluster-specific overrides.

## Pattern Description

The deploy script uses an `add_if_set` helper function that checks whether an environment variable has a non-empty value before adding it as a `--set` argument. This is critical for charts with many secrets and configuration values where empty strings would override meaningful defaults. The script discovers the cluster domain from `oc whoami --show-server`, computes the Route hostname, and assembles all arguments into a single `helm upgrade --install` call.

## Implementation

### Conditional Environment Variable Injection

```bash
# scripts/deploy.sh (excerpt)
SET_ARGS=()

add_if_set() {
    local helm_key="$1"
    local env_var="$2"
    local value="${!env_var:-}"
    if [ -n "$value" ]; then
        SET_ARGS+=(--set "$helm_key=$value")
    fi
}

# Always set (have explicit values)
SET_ARGS+=(--set "global.imageRegistry=$REGISTRY")
SET_ARGS+=(--set "global.imageRepository=$REGISTRY_NS")
SET_ARGS+=(--set "global.imageTag=$IMAGE_TAG")
SET_ARGS+=(--set "routes.sharedHost=$PROJECT_NAME-$NAMESPACE.$CLUSTER_DOMAIN")

# Conditionally set secrets (only override when env var is present)
add_if_set secrets.LLM_BASE_URL LLM_BASE_URL
add_if_set secrets.LLM_API_KEY LLM_API_KEY
add_if_set secrets.LLM_MODEL LLM_MODEL
# ... 40+ more add_if_set calls
```

### Cluster Domain Autodiscovery

```bash
# scripts/deploy.sh (excerpt)
CLUSTER_DOMAIN="${CLUSTER_DOMAIN:-}"
if [ -z "$CLUSTER_DOMAIN" ]; then
    CLUSTER_DOMAIN=$(oc whoami --show-server 2>/dev/null \
        | sed -E 's|https://api\.([^:]+).*|apps.\1|' || echo "")
fi
```

### Feature Toggle Defaults

```bash
# scripts/deploy.sh (excerpt)
# Feature toggles (these have safe defaults so always pass)
SET_ARGS+=(--set "keycloak.enabled=${KEYCLOAK_ENABLED:-true}")
SET_ARGS+=(--set "llamastack.enabled=${LLAMASTACK_ENABLED:-false}")
SET_ARGS+=(--set "seed.enabled=${SEED_ENABLED:-true}")
```

### Values.local.yaml Override

```bash
# scripts/deploy.sh (excerpt)
VALUES_LOCAL="./deploy/helm/$PROJECT_NAME/values.local.yaml"
VALUES_FILE_ARGS=()
if [ -f "$VALUES_LOCAL" ]; then
    echo "Loading local values from: $VALUES_LOCAL"
    VALUES_FILE_ARGS+=(-f "$VALUES_LOCAL")
fi
```

### Safe Env File Handling

```bash
# scripts/deploy.sh (excerpt)
# Load env file only when explicitly specified via ENV_FILE.
# The default .env contains local dev values (localhost URLs) that override
# the Helm chart's cluster-internal defaults -- never source it automatically.
if [ "$ENV_FILE" != ".env" ] && [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi
```

### Helm Invocation with Error Guidance

```bash
# scripts/deploy.sh (excerpt)
helm upgrade --install "$PROJECT_NAME" "./deploy/helm/$PROJECT_NAME" \
    --namespace "$NAMESPACE" \
    --timeout "$HELM_TIMEOUT" \
    --wait --wait-for-jobs \
    "${VALUES_FILE_ARGS[@]}" \
    "${SET_ARGS[@]}" \
    "$@" $HELM_EXTRA_ARGS \
    || { echo "Run 'make debug' for diagnostics"; exit 1; }
```

## Configuration

- **Key settings:** All env vars are exported by the Makefile; `HELM_TIMEOUT` (default: 15m); `HELM_EXTRA_ARGS` for additional helm arguments; `ENV_FILE` (default: `.env` but only sourced when explicitly changed)
- **Defaults:** `KEYCLOAK_ENABLED=true`, `LLAMASTACK_ENABLED=false`, `SEED_ENABLED=true`; images from `quay.io/rh-ai-quickstart`; `--wait --wait-for-jobs` ensures the command blocks until deployment is ready
- **Dependencies:** `oc` CLI for cluster domain discovery; the deploy target in the Makefile chains `create-project`, `push-images`, and `helm-dep-update` before calling this script

## Gotchas

- The `.env` file is deliberately NOT sourced by default -- the comment explains that `.env` contains localhost URLs (like `http://localhost:1234/v1`) that would override the chart's cluster-internal defaults (like `http://vllm:8000/v1`) with broken values (see `scripts/deploy.sh` lines 29-37)
- The `${!env_var:-}` indirect expansion (`bash` feature) reads the value of the variable whose name is stored in `env_var` -- this is not POSIX-compatible and requires bash (see `scripts/deploy.sh` line 55)
- The `"$@"` at the end of the helm command passes any extra arguments from `scripts/deploy.sh` invocation -- the Makefile does not use this, but users can call `make deploy HELM_EXTRA_ARGS="--set ..."` or call the script directly (see `scripts/deploy.sh` line 137)
- The cluster domain extraction `sed -E 's|https://api\.([^:]+).*|apps.\1|'` converts `https://api.cluster.example.com:6443` to `apps.cluster.example.com` -- this assumes the standard OpenShift naming convention where `api.*` maps to `apps.*` (see `scripts/deploy.sh` lines 42-43)

## Related Patterns

- `makefile-split-cluster-local-interactive-env.md` -- alternative Makefile pattern with interactive env setup
- `shell-script-two-phase-helm-cluster-autodetect.md` -- similar cluster autodiscovery in a multi-phase deploy
