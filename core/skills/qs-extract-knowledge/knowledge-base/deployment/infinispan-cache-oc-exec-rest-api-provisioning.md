---
name: infinispan-cache-oc-exec-rest-api-provisioning
description: Creating Infinispan distributed caches via oc exec curl to the REST API with JSON definitions and readiness polling
summary: "Provisions Infinispan distributed caches (events/10min TTL, events-to-process/20s TTL, ai-messages/no expiration) at install time by `oc exec`'ing into the pod (selected via `app=infinispan` label) and POSTing JSON definitions from `deploy/resources/infinispan/caches/*.json` to the REST API at localhost:11222 with digest authentication, running as Step 5 in the parent shell-script-phased deploy chain. Use for standalone Infinispan deployments (quay.io/infinispan/server:16.0, no operator) where cache configs need version control as JSON files — the script polls readiness (30 attempts, 2s intervals) then iterates files, creating each cache via `curl -X POST` with `Content-Type: application/json`. All caches use distributed-cache mode with SYNC replication and `text/plain` encoding; credentials come from the `infra-accounts` secret (DATAGRID_USERNAME/DATAGRID_PASSWORD env vars) for the server but are hardcoded (`admin:password --digest`) in the create script's curl commands. Polling timeout (60s) fails silently without creating caches, cache creation is not idempotent (existing caches error silently via curl `-sf` flag), and `$(cat \"${CACHE_FILE}\")` shell expansion could break with large payloads or special characters."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [infinispan]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Shell script exec'ing into Infinispan pod to create three distributed caches (events, events-to-process, ai-messages) via REST API with digest auth, readiness polling, and JSON cache definitions from files"
    approach: "A"
---

# Infinispan Cache Provisioning via oc exec REST API

## Overview

A deployment pattern that creates Infinispan caches at install time by exec'ing into the Infinispan pod and using `curl` to call the Infinispan REST management API. Cache definitions are stored as JSON files in the repo and iterated by the install script. A readiness polling loop ensures the REST API is available before attempting cache creation.

## Pattern Description

Instead of using the Infinispan Operator's Cache CR or configuring caches in the Infinispan server XML, this pattern uses imperative `oc exec` calls during installation. The script finds the Infinispan pod by label, polls the REST API until it responds (up to 30 attempts with 2-second intervals), then iterates over JSON cache definition files and creates each cache via HTTP POST. This approach works with a standalone Infinispan deployment (no operator) and allows cache definitions to be version-controlled as simple JSON files.

## Implementation

### REST API Readiness Polling

The script polls the Infinispan REST API before creating caches:

```bash
# create.sh - Step 5: Wait for REST API
ISPN_POD=$(oc get pod -l app=infinispan -o jsonpath='{.items[0].metadata.name}')

for i in $(seq 1 30); do
  if oc exec "${ISPN_POD}" -- curl -sf -u admin:password --digest http://localhost:11222/rest/v2/caches >/dev/null 2>&1; then
    break
  fi
  echo "Waiting for Infinispan REST API..."
  sleep 2
done
```

### Cache Creation from JSON Files

Caches are created by iterating JSON definition files and POSTing to the REST API:

```bash
# create.sh - Step 5: Create caches
for CACHE_FILE in deploy/resources/infinispan/caches/*.json; do
  CACHE_NAME=$(basename "${CACHE_FILE}" .json)
  echo "Creating cache '${CACHE_NAME}'..."
  oc exec "${ISPN_POD}" -- curl -sf \
    -u admin:password --digest \
    -X POST "http://localhost:11222/rest/v2/caches/${CACHE_NAME}" \
    -H 'Content-Type: application/json' \
    -d "$(cat "${CACHE_FILE}")"
done
```

### Cache JSON Definitions

Each cache is defined as a JSON file with distributed-cache configuration:

```json
// deploy/resources/infinispan/caches/events.json
{
  "events": {
    "distributed-cache": {
      "mode": "SYNC",
      "statistics": true,
      "encoding": {
        "media-type": "text/plain"
      },
      "expiration": {
        "lifespan": "600000"
      }
    }
  }
}
```

Three caches are defined:
- `events` -- distributed cache with 10-minute TTL for correlated telemetry events
- `events-to-process` -- distributed cache with 20-second TTL for pending analysis queue
- `ai-messages` -- distributed cache with no expiration for LLM analysis results

### Infinispan Deployment

The Infinispan server runs as a simple single-replica Deployment (not the Infinispan Operator):

```yaml
# deploy/resources/infinispan/infinispan-sandbox.yaml
containers:
  - name: infinispan
    image: quay.io/infinispan/server:16.0
    ports:
      - containerPort: 11222
    env:
      - name: USER
        valueFrom:
          secretKeyRef:
            name: infra-accounts
            key: DATAGRID_USERNAME
      - name: PASS
        valueFrom:
          secretKeyRef:
            name: infra-accounts
            key: DATAGRID_PASSWORD
```

## Configuration

- **Key settings:** Authentication uses digest authentication (`--digest`) with credentials from the `infra-accounts` secret (default: admin/password); REST API endpoint is `http://localhost:11222/rest/v2/caches`
- **Defaults:** All caches use `distributed-cache` mode with `SYNC` replication and `text/plain` encoding; TTL varies per cache (none, 20s, 600s)
- **Dependencies:** The Infinispan pod must be running and the REST API responsive before cache creation; the `infra-accounts` secret must exist with `DATAGRID_USERNAME` and `DATAGRID_PASSWORD` keys

## Gotchas

- The readiness polling has a maximum of 30 attempts with 2-second sleeps (60 seconds total) -- if the Infinispan REST API takes longer to start, the script will proceed without caches being created (no explicit failure on polling timeout)
- The `$(cat "${CACHE_FILE}")` in the `oc exec` curl command passes the JSON via shell expansion to the container -- this works because the cache JSON files are small, but could fail with large payloads or special characters
- Credentials (`admin:password`) are hardcoded in the curl commands in `create.sh` -- the `infra-accounts` secret provides the same values to the Infinispan container via environment variables, but the script does not read from the secret
- The cache creation is not idempotent -- creating a cache that already exists returns an error, which is ignored by the `-sf` (silent, fail) curl flag

## Related Patterns

- `shell-script-phased-infra-helm-tekton-deploy-chain.md` -- the parent orchestration script that runs this cache provisioning as Step 5
