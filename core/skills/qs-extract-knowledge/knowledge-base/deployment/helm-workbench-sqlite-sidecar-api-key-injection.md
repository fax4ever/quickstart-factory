---
name: helm-workbench-sqlite-sidecar-api-key-injection
description: Kubeflow Notebook with SQLite sidecar container that waits for AnythingLLM database then injects API key
summary: "Automates API key provisioning in AnythingLLM's SQLite database by adding a keinos/sqlite3 sidecar to a Kubeflow Notebook (workbench) pod, where it shares a PVC with the main container and an optional OAuth proxy sidecar (older RHOAI), polls for the DB file, and injects a known key via SQL so downstream seed jobs can authenticate without manual intervention. Use when AnythingLLM runs inside a Kubeflow Notebook workbench and Helm-managed seed jobs (see helm-seed-job-dual-curl-python-rag-ingestion) need a pre-provisioned API key; prefer helm-workbench-notebook-job-exec-git-clone for workbench automation via Job exec instead of a persistent sidecar. The sidecar shares a 5Gi ReadWriteOnce PVC at /opt/app-root/src, polls up to 120s for anythingllm/storage/anythingllm.db, waits 5s for initialization, then runs `CREATE TABLE IF NOT EXISTS api_keys` followed by `INSERT OR REPLACE` with hardcoded key `sk-automation-workspace-setup` which must also match the K8s Secret (anythingllm-api) and seed job env var. The sidecar must end with `sleep infinity` or the pod enters CrashLoopBackOff, the API key appears in three places (sidecar script, K8s Secret, seed job env var) that must stay in sync, and the PVC annotation `helm.sh/resource-policy: keep` prevents deletion on `helm uninstall` -- preserving workspace data but requiring manual cleanup."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, sqlite, jupyter]
  ai_pattern: []
  platform: [rhoai, openshift]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "keinos/sqlite3 sidecar in Kubeflow Notebook waits for AnythingLLM DB then injects API key via SQL, with shared PVC"
    approach: "A"
---

# Workbench SQLite Sidecar for API Key Injection

## Overview

This pattern adds a SQLite sidecar container to a Kubeflow Notebook (workbench) pod that automatically provisions an API key in AnythingLLM's SQLite database. The sidecar shares a PVC with the main workbench container, waits for the database file to appear, then injects a known API key via SQL -- enabling downstream seed jobs to authenticate against the AnythingLLM API without manual user intervention.

## Pattern Description

The Kubeflow Notebook pod runs three containers: the main AnythingLLM workbench, a conditional OAuth proxy sidecar (for older RHOAI versions), and a `keinos/sqlite3` sidecar. The SQLite sidecar shares the same PVC mount as the main container (`/opt/app-root/src`). It polls for the database file at a known path, waits for it to be initialized, then either confirms the API key already exists or inserts it via SQL. After setup, the sidecar enters `sleep infinity` to keep the pod running.

## Implementation

### SQLite Sidecar Container

The sidecar is defined as an additional container in the Kubeflow Notebook pod spec:

```yaml
# helm/templates/workbench.yaml (excerpt)
- name: anythingllm-automation
  image: keinos/sqlite3:latest
  command: ["/bin/sh", "-c"]
  resources:
    limits:
      cpu: 100m
      memory: 128Mi
    requests:
      cpu: 50m
      memory: 64Mi
  volumeMounts:
    - mountPath: /opt/app-root/src
      name: anythingllm
  args:
    - |
      set -e
      DB_PATH="/opt/app-root/src/anythingllm/storage/anythingllm.db"
      
      # Wait for AnythingLLM to create the database
      for i in $(seq 1 120); do
        if [ -f "$DB_PATH" ]; then
          echo "Database found after ${i} seconds!"
          break
        fi
        sleep 1
      done
      
      # Wait a bit for database to be fully initialized
      sleep 5
      
      # Check if API key already exists
      if sqlite3 "$DB_PATH" "SELECT 1 FROM api_keys WHERE secret = 'sk-automation-workspace-setup' LIMIT 1;" 2>/dev/null | grep -q 1; then
        echo "API key already exists"
      else
        sqlite3 "$DB_PATH" << 'EOF'
      CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        secret TEXT UNIQUE NOT NULL,
        createdBy INTEGER,
        createdAt DATETIME DEFAULT CURRENT_TIMESTAMP,
        lastUpdatedAt DATETIME DEFAULT CURRENT_TIMESTAMP
      );
      INSERT OR REPLACE INTO api_keys (secret, createdBy, createdAt, lastUpdatedAt)
      VALUES ('sk-automation-workspace-setup', 1, datetime('now'), datetime('now'));
      EOF
      fi
      
      # Keep the sidecar running
      sleep infinity
```

### Shared PVC Between Workbench and Sidecar

Both the main AnythingLLM container and the SQLite sidecar mount the same PVC at `/opt/app-root/src`:

```yaml
# helm/templates/workbench-pvc.yaml
kind: PersistentVolumeClaim
apiVersion: v1
metadata:
  annotations:
    helm.sh/resource-policy: keep
  name: anythingllm
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
  storageClassName: {{ .Values.storageClassName }}
```

### API Key Secret for Downstream Jobs

The injected API key is also stored as a Kubernetes Secret for use by seed jobs:

```yaml
# helm/templates/anythingllm-api.yaml (excerpt)
kind: Secret
apiVersion: v1
metadata:
  name: anythingllm-api
data:
  key: c2stYXV0b21hdGlvbi13b3Jrc3BhY2Utc2V0dXA=
type: Opaque
```

## Configuration

- **Key settings:** The API key value `sk-automation-workspace-setup` is hardcoded in both the sidecar SQL and the Kubernetes Secret; the database path is `anythingllm/storage/anythingllm.db` relative to the PVC mount
- **Defaults:** Sidecar runs with 50m-100m CPU and 64-128Mi memory; PVC is 5Gi with `helm.sh/resource-policy: keep` to survive Helm uninstall; timeout is 120 seconds for database creation
- **Dependencies:** The main AnythingLLM container must create the database file at the known path; the `keinos/sqlite3` image must be accessible from the cluster

## Gotchas

- The sidecar waits up to 120 seconds for the database file to appear, then adds a 5-second delay for database initialization -- if AnythingLLM takes longer to start, the sidecar will exit with an error and the pod may restart (see `helm/templates/workbench.yaml`)
- The `INSERT OR REPLACE` SQL is idempotent -- the sidecar can safely run on pod restarts without creating duplicate keys (see `helm/templates/workbench.yaml`)
- The PVC has `helm.sh/resource-policy: keep` which prevents Helm from deleting the PVC on `helm uninstall` -- this preserves the AnythingLLM database and workspace data across reinstalls (see `helm/templates/workbench-pvc.yaml`)
- The sidecar ends with `sleep infinity` because Kubernetes requires all containers in a pod to keep running -- if the sidecar exits, the pod would enter a `CrashLoopBackOff` state (see `helm/templates/workbench.yaml`)
- The API key `sk-automation-workspace-setup` appears in three places: the sidecar script, the Kubernetes Secret, and the seed job environment variable -- all must match (see `helm/templates/workbench.yaml`, `helm/templates/anythingllm-api.yaml`, `helm/templates/init_job.yaml`)

## Related Patterns

- `helm-seed-job-dual-curl-python-rag-ingestion.md` -- the seed jobs that consume the API key injected by this sidecar
- `helm-workbench-notebook-job-exec-git-clone.md` -- alternative workbench automation pattern using Job exec instead of sidecar
