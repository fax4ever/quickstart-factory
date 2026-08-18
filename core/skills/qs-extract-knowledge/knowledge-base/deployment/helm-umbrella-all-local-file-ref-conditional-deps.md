---
name: helm-umbrella-all-local-file-ref-conditional-deps
description: Umbrella chart referencing all subcharts via file:// relative paths with condition toggles for optional components
summary: "Deploys multi-component AI/RAG applications (model serving, embeddings, pgvector, auth) on OpenShift using a Helm umbrella chart (apiVersion v2, type: application) where every dependency uses `repository: \"file://../charts/<name>\"` local references with `condition: <name>.enabled` toggles, avoiding remote registries by versioning all charts together in one monorepo. Use for quickstarts needing selective component installation — the umbrella directory sits alongside a charts/ directory of independent subcharts; vllm and ollama are mutually exclusive LLM backends (ollama default, GPU toggleable for ollama/docling), the main app subchart has no condition field so it always deploys, and `helm dependency update` packages file:// paths into tarballs in the umbrella's charts/ output directory. Critical config: install.sh generates secrets via `openssl rand -base64 24` passed as `--set` arguments with `--timeout 15m --wait`, clearing variables after use; see helm-operator-umbrella-all-local-singleton-validation for Operator-wrapped alternative and helm-umbrella-mixed-remote-local-committed-deps for mixed registry sources. Gotchas: file:// relative paths resolve from the chart directory not the working directory so `helm install` must run from inside the umbrella directory; secrets may appear in process listings during install despite variable clearing; uninstall.sh uses `read -p` blocking non-interactive execution."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [rag, embeddings, model-serving]
  platform: [openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Umbrella chart at peoplemesh-umbrella/ referencing 6 local subcharts in charts/ via file://../charts/<name> with condition toggles for keycloak, pgvector, docling, vllm, ollama"
    approach: "A"
---

# Helm Umbrella with All-Local File References and Conditional Dependencies

## Overview

This pattern uses a Helm umbrella chart where every dependency is a local `file://` reference to sibling chart directories, with `condition` fields enabling selective component installation. The umbrella chart lives in its own directory separate from the subcharts, referencing them via relative paths.

## Pattern Description

The umbrella chart (`peoplemesh-umbrella/`) sits alongside a `charts/` directory containing independent subchart directories. Each dependency uses `repository: "file://../charts/<name>"` to reference the local charts. Optional components use a `condition` field so they can be toggled on or off via values. This avoids remote chart registries entirely -- all charts are versioned together in the same repository, and `helm dependency update` resolves local paths into packaged tarballs in the umbrella's `charts/` output directory.

## Implementation

### Umbrella Chart.yaml with Local Dependencies

```yaml
# peoplemesh-umbrella/Chart.yaml
apiVersion: v2
name: peoplemesh-umbrella
description: Umbrella chart for complete peoplemesh deployment with all dependencies
type: application
version: 0.1.0

dependencies:
  - name: keycloak
    version: 0.1.0
    repository: "file://../charts/keycloak"
    condition: keycloak.enabled

  - name: pgvector
    version: 0.1.0
    repository: "file://../charts/pgvector"
    condition: pgvector.enabled

  - name: docling
    version: 0.1.0
    repository: "file://../charts/docling"
    condition: docling.enabled

  - name: vllm
    version: 0.1.0
    repository: "file://../charts/vllm"
    condition: vllm.enabled

  - name: ollama
    version: 0.1.0
    repository: "file://../charts/ollama"
    condition: ollama.enabled

  - name: peoplemesh
    version: 0.1.0
    repository: "file://../charts/peoplemesh"
```

### Directory Layout

```
peoplemesh-umbrella/     # Umbrella chart (separate directory)
  Chart.yaml
  values.yaml
  install.sh
  uninstall.sh
  templates/
charts/                  # All subcharts as siblings
  keycloak/
  pgvector/
  docling/
  ollama/
  vllm/
  peoplemesh/
```

### Conditional Component Toggles in values.yaml

```yaml
# peoplemesh-umbrella/values.yaml (excerpts)
keycloak:
  enabled: true

pgvector:
  enabled: true

docling:
  enabled: true

# Mutually-exclusive LLM backends
vllm:
  enabled: false  # Disabled by default - use Ollama instead

ollama:
  enabled: true   # Set to false to use vLLM or external LLM

# Main app always deploys (no condition field in Chart.yaml)
peoplemesh:
  applicationName: peoplemesh
```

### Install Script with Secret Generation

```bash
# peoplemesh-umbrella/install.sh (excerpt)
# Generate secure secrets (not exported to environment)
KC_DB_PASSWORD=$(openssl rand -base64 24)
PG_DB_PASSWORD=$(openssl rand -base64 24)
CLIENT_SECRET=$(openssl rand -base64 24)

helm install peoplemesh . \
  --namespace "$NAMESPACE" \
  --timeout 15m \
  --wait \
  --set keycloak.postgres.password="$KC_DB_PASSWORD" \
  --set pgvector.postgres.password="$PG_DB_PASSWORD" \
  --set keycloak.realm.client.clientSecret="$CLIENT_SECRET" \
  --set ollama.gpu.enabled="$OLLAMA_GPU" \
  --set docling.gpu.enabled="$DOCLING_GPU" \
  $EXTRA_HELM_ARGS

# Clear sensitive variables from memory
KC_DB_PASSWORD=""
PG_DB_PASSWORD=""
```

## Configuration

- **Key settings:** Each subchart is toggled via `<name>.enabled` in values.yaml; the main app (peoplemesh) has no condition field and always deploys; vllm and ollama are mutually-exclusive LLM backends (vllm disabled by default)
- **Defaults:** keycloak, pgvector, docling, ollama enabled; vllm disabled; GPU acceleration disabled for both ollama and docling
- **Dependencies:** All subcharts must exist at the relative file:// paths; `helm dependency update` must be run before install (the install.sh script handles this in the build flow)

## Gotchas

- The `file://` relative paths (`file://../charts/<name>`) require the umbrella chart to be installed from its own directory -- running `helm install` from the repo root will fail because the relative paths resolve from the chart directory, not the working directory (see `peoplemesh-umbrella/Chart.yaml`)
- The main app subchart (peoplemesh) has no `condition` field in the dependencies, so it always installs -- this is intentional since it is the core application
- The install.sh script generates random secrets via `openssl rand -base64 24` and passes them as `--set` arguments; it clears variables after use but they may still appear in process listings during the helm install (see `peoplemesh-umbrella/install.sh` lines 120-162)
- The uninstall.sh uses an interactive `read -p` confirmation prompt, which prevents non-interactive usage without modification (see `peoplemesh-umbrella/uninstall.sh` line 66)

## Related Patterns

- `helm-operator-umbrella-all-local-singleton-validation.md` -- similar all-local pattern but wrapped in a Helm Operator with CRD validation
- `helm-umbrella-mixed-remote-local-committed-deps.md` -- umbrella charts mixing remote and local deps
- `helm-lookup-secret-idempotency-random-fallback.md` -- the secret preservation pattern used in this umbrella's _helpers.tpl
