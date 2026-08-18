---
name: anythingllm-seed-job
description: "Kubernetes Job that seeds AnythingLLM workspaces with documents via its REST API using a curl-based init container"
summary: "Automates bootstrapping AnythingLLM workspaces with system prompts and seed documents via REST API in a one-shot Kubernetes Job, enabling a fully automated \"deploy and ready\" RAG experience for RHOAI quickstarts using LanceDB-backed AnythingLLM deployed as a StatefulSet workbench. Use this curl-only Job (quay.io/curl/curl, no SDK or application code) when seeding AnythingLLM workspaces at Helm install time; for seeding the RHOAI playground instead, use the companion rag-seed Job which uses Python and the LlamaStack SDK. The Job polls anythingllm-api-internal.${NAMESPACE}.svc.cluster.local:3001/api/v1/system for readiness, creates workspaces idempotently via POST /workspace/new with sed/awk slug-lookup fallback (no jq available), injects system prompts with Helm double-JSON encoding (toJson piped through toJson), and batch-uploads document URLs from .Values.rag.seedDocuments. Critical gotchas: backoffLimit:0 means no retry if AnythingLLM never becomes healthy, the API key (sk-automation-workspace-setup) is hardcoded in the Secret template rather than dynamically generated, space-delimited URL concatenation breaks on URLs with spaces, and a NetworkPolicy must allow same-namespace traffic on port 3001."
metadata:
  type: component
tags:
  tech_stack: [curl, anythingllm, helm]
  ai_pattern: [rag, data-pipeline]
  platform: [openshift, kubernetes]
  data_layer: [lancedb]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Kubernetes Job that creates an AnythingLLM workspace and uploads seed documents via REST API"
    approach: "A"
---

# AnythingLLM Seed Job

## Overview

A Kubernetes Job that bootstraps an AnythingLLM instance by creating a named workspace, setting its system prompt, and uploading seed documents via the AnythingLLM REST API. It runs as a one-shot init container alongside the main Helm install, using only `curl` to drive the API -- no application code or SDK required. This pattern enables a fully automated "deploy and ready" experience for RHOAI quickstarts that use AnythingLLM as their RAG frontend.

## Tech Stack & Dependencies

- **Runtime:** Shell script executed via `quay.io/curl/curl` container image
- **Container image:** `quay.io/curl/curl` (minimal image with only curl and shell)
- **Key dependencies:** AnythingLLM API (port 3001), a pre-created `anythingllm-api` Secret containing the API key
- **Helm subchart:** None -- defined as a standalone Job template in the parent chart

## Key Patterns

### Health-Check Polling Before Seeding

The Job polls the AnythingLLM `/api/v1/system` endpoint in a loop, waiting for a `200` response before proceeding. This handles the race condition where the Job starts before AnythingLLM is fully ready.

```yaml
# From helm/templates/init_job.yaml
args:
- |
  set -eu
  SVC="anythingllm-api-internal.${NAMESPACE}.svc.cluster.local:3001"
  BASE="http://${SVC}/api/v1"
  AUTH="Authorization: Bearer ${ANYTHINGLLM_API_KEY}"

  ATTEMPT=1
  while true; do
    HEALTH_CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "${AUTH}" "${BASE}/system" 2>/dev/null || echo "000")
    if [ "$HEALTH_CODE" = "200" ]; then
      echo "AnythingLLM is ready! (attempt $ATTEMPT)"
      break
    fi
    ATTEMPT=$((ATTEMPT + 1))
    sleep 10
  done
```

### Idempotent Workspace Creation with Slug Lookup

The Job creates a workspace by name via `POST /workspace/new`. If the workspace already exists, AnythingLLM returns a response without a slug, so the Job falls back to listing all workspaces and parsing the slug with `awk`. This makes the Job safe to re-run.

```yaml
# From helm/templates/init_job.yaml
CREATE_RESP="$(curl -s -X POST "${BASE}/workspace/new" -H "${AUTH}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${WS_NAME}\"}" || true)"

WS_SLUG="$(printf '%s' "$CREATE_RESP" | sed -n 's/.*"slug":"\([^"]*\)".*/\1/p' | head -n1 || true)"
if [ -z "${WS_SLUG}" ]; then
  WS_SLUG="$(curl -s "${BASE}/workspaces" -H "${AUTH}" \
    | awk -v n="$WS_NAME" 'BEGIN{RS="[{}]"} /"name":"[^"]+"/{ ... }')"
fi
[ -n "${WS_SLUG}" ] || { echo "Could not determine workspace slug"; exit 1; }
```

### System Prompt Injection via Helm Templating

The workspace system prompt is set via `POST /workspace/{slug}/update`, with the prompt value pulled from `values.yaml` and double-JSON-encoded using Helm's `toJson` piped through `printf`.

```yaml
# From helm/templates/init_job.yaml
curl -s -X POST "${BASE}/workspace/${WS_SLUG}/update" -H "${AUTH}" \
  -H "Content-Type: application/json" \
  -d {{ printf `{"openAiPrompt": %s}` (.Values.aiLifecoach.workspace.systemPrompt | toJson) | toJson }} >/dev/null || true
```

### Batch Document Upload via Link

Seed document URLs are passed as a space-delimited string from `values.yaml` and iterated in a `for` loop, each uploaded via the `POST /document/upload-link` endpoint with automatic workspace association.

```yaml
# From helm/templates/init_job.yaml (env var)
- name: SEED_URL
  value: "{{ range .Values.rag.seedDocuments }}{{ .url }} {{ end }}"

# From the script body
for URL in ${SEED_URL}; do
  UL_RESP="$(curl -s -X POST "${BASE}/document/upload-link" \
            -H "${AUTH}" -H "Content-Type: application/json" \
            -d "{\"link\":\"${URL}\", \"addToWorkspaces\":\"${WS_SLUG}\"}")"
done
```

## Configuration

- **Environment variables:**
  - `ANYTHINGLLM_API_KEY` -- API key from `anythingllm-api` Secret, used for all API calls
  - `NAMESPACE` -- injected via downward API (`metadata.namespace`), used to construct the internal service DNS name
  - `WORKSPACE_NAME` -- from `.Values.aiLifecoach.workspace.name`, the human-readable workspace name
  - `SEED_URL` -- space-delimited list of document URLs from `.Values.rag.seedDocuments`
- **Config files:** None -- all configuration is inline in the Job spec
- **Helm values:**
  - `.Values.aiLifecoach.workspace.name` -- workspace display name (e.g., `"Assistant to the HR Representative"`)
  - `.Values.aiLifecoach.workspace.systemPrompt` -- multi-line system prompt injected into the workspace
  - `.Values.rag.seedDocuments` -- list of `{filename, url}` objects for seed documents

## Known Gotchas

- **backoffLimit: 0** -- the Job is configured with `backoffLimit: 0`, meaning it will not retry on failure. If AnythingLLM never becomes healthy, the seed Job will fail permanently and must be manually re-created.
- **No jq available** -- the `quay.io/curl/curl` image does not include `jq`, so JSON parsing is done with `sed` and `awk`. The slug-extraction `awk` one-liner is fragile and assumes a specific JSON structure from the AnythingLLM API.
- **Space-delimited URLs** -- seed document URLs are concatenated into a single space-delimited string, which means URLs containing spaces would break. The current `values.yaml` uses only well-formed URLs.
- **API key is hardcoded in Secret** -- the `anythingllm-api` Secret has a base64-encoded key (`sk-automation-workspace-setup`) baked into the template rather than being generated dynamically.
- **NetworkPolicy required** -- the seed Job must be able to reach AnythingLLM on port 3001. The `anythingllm-access` NetworkPolicy explicitly allows same-namespace traffic for this purpose (comment: "Allow access from same namespace (for init jobs and other services)").

## Testing Notes

- Check seed Job completion: `oc logs -n <namespace> -l job-name=anythingllm-seed --tail=5`
- Verify workspace was created: look for "Using workspace slug:" in the Job logs
- Verify documents were uploaded: look for "upload-link response" entries in the Job logs
- The Job runs alongside a second seed Job (`rag-seed`) that seeds the RHOAI playground via LlamaStack -- both should complete within a couple of minutes

## Related Patterns

- The `rag-seed-job` (`rag-seed-job.yaml`) in the same chart follows a similar seeding pattern but uses Python + LlamaStack SDK instead of curl, and seeds into the RHOAI playground rather than AnythingLLM
- AnythingLLM is deployed as a StatefulSet workbench (see `workbench.yaml`) with its own PVC and registered as an RHOAI workbench
- The AnythingLLM connection Secret (`tinyllama-vllm-cpu`) configures LanceDB as the vector store (`VECTOR_DB: lancedb`) and uses the `localai` LLM provider pointing at the vLLM inference endpoint
