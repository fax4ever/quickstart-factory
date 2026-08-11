---
name: minio
description: "S3-compatible object storage for file attachments, optional via compose profiles and feature flags"
summary: "MinIO (quay.io/minio/minio:latest) provides S3-compatible object storage for quickstarts, handling chat attachment uploads (Approach A) or serving as shared infrastructure for RAG index persistence, ML model storage, Loki log backend, and document seeding (Approach B). Use Approach A (boto3, configure-pipeline subchart v0.5.6, ATTACHMENTS_BUCKET_* env vars) when MinIO is a single-purpose optional service gated by compose `attachments` profile and inverted DISABLE_ATTACHMENTS flag; use Approach B (minio Python SDK >=7.2.17, standalone minio subchart v0.1.0 as StatefulSet with 50Gi PVC, MINIO_* env vars with shared K8s Secret) when MinIO is always-on with multiple consumers (backend, clustering, rag, Loki). Approach A uses lazy _get_s3() with module-level globals and auto-bucket via head_bucket/create_bucket storing attachments under session-scoped keys ({session_id}/{attachment_id}{ext}); Approach B uses centralized get_minio_client() factory (secure=False hardcoded, config priority: params > env vars > defaults), LATEST.json pointer tracking RAG index status (BUILDING/READY/FAILED), joblib serialization for ML model storage, and OpenShift Routes with TLS edge termination. The start-dev.sh script bridges ENABLE_ATTACHMENTS to the inverted DISABLE_ATTACHMENTS flag, compose backend must declare MinIO with `required: false` to avoid blocking startup, Loki deploys its own separate MinIO with anyuid SCC for minio-sa, the minio subchart is packaged as .tgz requiring extraction to inspect templates, clustering model_loader.py duplicates client logic bypassing the shared factory, and session-scoped authorization remains unimplemented (TODO)."
metadata:
  type: component
tags:
  tech_stack: [minio, python, boto3, fastapi, joblib, faiss]
  ai_pattern: [rag, embeddings, vector-search]
  platform: [openshift, rhoai]
  data_layer: [minio]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Optional MinIO for chat attachment uploads, controlled by compose profiles and feature flag"
    approach: "A"
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Multi-purpose MinIO as StatefulSet for RAG index persistence, ML model storage, Loki backend, and sample doc upload"
    approach: "B"
---

# MinIO

## Overview

MinIO provides S3-compatible object storage used in quickstarts for file attachment handling. In the ai-virtual-agent quickstart it is deployed as an optional service gated by a compose profile and a backend feature flag, allowing the quickstart to run without it when attachments are not needed. On cluster, MinIO is provisioned via the `configure-pipeline` Helm subchart from ai-architecture-charts rather than a standalone chart.

## Tech Stack & Dependencies
- **Runtime:** MinIO server (S3-compatible API)
- **Container image:** `quay.io/minio/minio:latest`
- **Key dependencies:** boto3 and botocore in the Python backend for S3 client operations
- **Helm subchart:** `configure-pipeline` (v0.5.6) from `https://rh-ai-quickstart.github.io/ai-architecture-charts` handles MinIO provisioning on cluster

## Key Patterns

### Optional Service via Compose Profiles

MinIO is placed behind a Docker Compose profile so it only starts when explicitly enabled. The backend declares a soft dependency (`required: false`) so it can start even without MinIO.

```yaml
# deploy/local/compose.yaml (lines 239-262)
minio:
  image: quay.io/minio/minio:latest
  container_name: minio-dev
  restart: unless-stopped
  environment:
    - MINIO_ROOT_USER=${MINIO_ROOT_USER:-minio_rag_user}
    - MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD:-minio_rag_password}
  ports:
    - '${MINIO_PORT:-9000}:9000'
    - '${MINIO_CONSOLE_PORT:-9001}:9001'
  volumes:
    - minio_data:/data
  command: server /data --console-address ":9001"
  profiles:
    - attachments
```

The start script activates the profile based on an environment variable:

```bash
# deploy/local/scripts/start-dev.sh (lines 42-49)
ENABLE_ATTACHMENTS=${ENABLE_ATTACHMENTS:-true}
if [ "$ENABLE_ATTACHMENTS" = "true" ]; then
    COMPOSE_PROFILES="--profile attachments"
else
    COMPOSE_PROFILES=""
    export DISABLE_ATTACHMENTS=true
fi
```

### Feature Flag Gating in Backend

The backend uses a `DISABLE_ATTACHMENTS` env var (inverted logic -- unset means enabled) parsed through a centralized feature flag utility. This keeps import-time side effects out of the module.

```python
# backend/app/core/feature_flags.py (lines 24-33)
def is_attachments_feature_enabled() -> bool:
    """
    Convention in this project:
    - DISABLE_ATTACHMENTS=true disables attachments
    - any other value (including unset) enables attachments
    """
    disable_flag = os.getenv("DISABLE_ATTACHMENTS")
    return not _is_env_flag_true(disable_flag, default=False)
```

### Lazy S3 Client Initialization

The boto3 S3 client and resource are initialized lazily on first use, not at import time. This lets unit tests import the attachments module without needing a running MinIO instance. The bucket is auto-created if it does not exist.

```python
# backend/app/api/v1/attachments.py (lines 33-72)
def _get_s3():
    """Return lazily initialized (client, resource, bucket).

    This defers any network interaction until first use, making unit tests
    independent from a running MinIO/S3 service.
    """
    global _s3_client, _s3_resource, _bucket, _bucket_initialized

    if _s3_client is None or _s3_resource is None or _bucket is None:
        client = boto3.client(
            "s3",
            endpoint_url=f"http://{ATTACHMENTS_BUCKET_ENDPOINT}",
            aws_access_key_id=ATTACHMENTS_BUCKET_ACCESS_KEY,
            aws_secret_access_key=ATTACHMENTS_BUCKET_SECRET_KEY,
            region_name=ATTACHMENTS_BUCKET_REGION,
        )
        # ... resource setup ...
        if is_attachments_feature_enabled() and not _bucket_initialized:
            try:
                client.head_bucket(Bucket=ATTACHMENTS_BUCKET_NAME)
            except ClientError:
                client.create_bucket(Bucket=ATTACHMENTS_BUCKET_NAME)
            _bucket_initialized = True

    return _s3_client, _s3_resource, _bucket
```

### Session-Scoped Object Keys

Attachments are stored under `{session_id}/{attachment_id}{ext}` keys, enabling bulk deletion when a chat session is removed.

```python
# backend/app/api/v1/attachments.py (lines 89-98)
def delete_attachments_for_session(session_id: str):
    client, resource, bucket = _get_s3()
    try:
        bucket.objects.filter(Prefix=f"{session_id}/").delete()
    except ClientError as e:
        logger.warning(f"Failed to delete attachments for session {session_id}: {e}")
        raise
```

### Cluster Deployment via configure-pipeline Subchart

On OpenShift, MinIO is not deployed as a standalone chart. Instead the `configure-pipeline` Helm subchart handles MinIO secret creation and optional sample file upload.

```yaml
# deploy/cluster/helm/values.yaml (lines 159-172)
configure-pipeline:
  minio:
    secret:
      user: minio_rag_user
      password: minio_rag_password
      host: minio
      port: "9000"
    sampleFileUpload:
      enabled: true
      bucket: documents
      urls:
      - https://raw.githubusercontent.com/.../FantaCo-Fabulous-HR-Benefits.pdf
```

## Configuration
- **Environment variables:**
  - `ATTACHMENTS_BUCKET_ENDPOINT` -- MinIO host:port (default: `minio:9000`)
  - `ATTACHMENTS_BUCKET_ACCESS_KEY` -- S3 access key (default: `minio_rag_user`)
  - `ATTACHMENTS_BUCKET_SECRET_KEY` -- S3 secret key (default: `minio_rag_password`)
  - `ATTACHMENTS_BUCKET_NAME` -- bucket name (default: `attachments`)
  - `ATTACHMENTS_BUCKET_REGION` -- region, only relevant for non-self-hosted S3 (default: `us-east-1`)
  - `DISABLE_ATTACHMENTS` -- set to `true` to disable attachment feature entirely
  - `ENABLE_ATTACHMENTS` -- used by the start script to control compose profile activation (default: `true`)
  - `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` -- MinIO server credentials in compose
- **Config files:** No MinIO-specific config files; configuration is entirely via environment variables
- **Helm values:** `configure-pipeline.minio.secret.*` for credentials; `configure-pipeline.minio.sampleFileUpload.*` for seeding documents

## Known Gotchas
- The compose backend declares `minio` as a dependency with `required: false` (line 138-139 of compose.yaml), so the backend starts even when MinIO is not running. Without this, disabling the attachments profile would block the backend.
- The feature flag uses inverted logic (`DISABLE_ATTACHMENTS` rather than `ENABLE_ATTACHMENTS`). The start script bridges the two: when `ENABLE_ATTACHMENTS=false`, it exports `DISABLE_ATTACHMENTS=true` for the backend.
- The `_get_s3()` function uses module-level globals (`_s3_client`, `_s3_resource`, `_bucket`) with lazy initialization specifically to avoid import-time network calls that would break unit tests (noted in the docstring at line 34-37 of attachments.py).
- The attachments API has TODO comments (lines 111-113, 146-148 of attachments.py) noting that authorization checks for session-scoped uploads and downloads are not yet implemented.

## Testing Notes
- Unit tests can import the attachments module without a running MinIO because of the lazy init pattern
- Verify MinIO health via the healthcheck endpoint: `curl -f http://localhost:9000/minio/health/live`
- Console is available at port 9001 for manual inspection (credentials from `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`)
- On cluster, verify the `configure-pipeline` job created the MinIO secret and optionally uploaded sample files

## Related Patterns
- Deployment pattern: compose profiles for optional services
- Architecture: attachment handling as part of chat session lifecycle

---

## Approach B: StatefulSet with Multi-Purpose Buckets (from ansible-log-analysis)

### When to Use

When MinIO serves as shared infrastructure for multiple consumers -- RAG index persistence, ML model storage, Loki log backend, and optional document seeding -- rather than a single-purpose attachment store. This approach uses the minio Python SDK directly and deploys MinIO as a StatefulSet via a standalone Helm subchart from ai-architecture-charts.

### Differences from Approach A

- **Python SDK:** Uses the `minio` Python package (>=7.2.17) instead of boto3
- **Deployment:** StatefulSet with 50Gi PVC via standalone `minio` Helm subchart (v0.1.0), not the `configure-pipeline` subchart
- **Multi-consumer:** Three services (backend, clustering, rag) plus Loki all read from the same MinIO instance using a shared Kubernetes Secret
- **Env var naming:** `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_PORT` (not `ATTACHMENTS_BUCKET_*`)
- **Always-on:** MinIO is a required dependency, not optional via feature flags

### Tech Stack & Dependencies
- **Runtime:** MinIO server (S3-compatible API)
- **Container image:** `quay.io/minio/minio:latest`
- **Key dependencies:** `minio>=7.2.17` Python SDK, joblib for model serialization, faiss for index storage
- **Helm subchart:** `minio` (v0.1.0) from `https://rh-ai-quickstart.github.io/ai-architecture-charts`

### Key Patterns

#### StatefulSet with PVC

MinIO is deployed as a StatefulSet with a VolumeClaimTemplate for persistent storage, exposed via a ClusterIP Service with separate ports for the API (9000) and console (9090).

```yaml
# minio subchart values.yaml
command:
  - /bin/bash
  - -c
  - minio server /data --console-address :9090

volumeClaimTemplates:
  - metadata:
      name: minio-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 50Gi

service:
  type: ClusterIP
  port: 9090
  apiPort: 9000
```

#### Shared Secret for Multi-Consumer Access

A single Kubernetes Secret named `minio` holds user, password, host, and port. All consuming services (backend, clustering, rag) reference the same secret keys via `secretKeyRef`.

```yaml
# Parent chart values.yaml (lines 11-16)
minio:
  secret:
    user: minio_alm_user
    password: minio_alm_password
    host: minio
    port: "9000"
```

Consumer services wire the secret identically:

```yaml
# backend/values.yaml (lines 156-175)
- name: MINIO_ENDPOINT
  valueFrom:
    secretKeyRef:
      name: minio
      key: host
- name: MINIO_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: minio
      key: user
- name: MINIO_SECRET_KEY
  valueFrom:
    secretKeyRef:
      name: minio
      key: password
- name: MINIO_PORT
  valueFrom:
    secretKeyRef:
      name: minio
      key: port
```

#### Centralized Client Factory

A shared utility creates the Minio client with config priority: function params > env vars > defaults. The `secure=False` setting is hardcoded for internal cluster traffic.

```python
# src/alm/utils/minio.py (lines 10-32)
def get_minio_client(
    minio_endpoint=None, minio_port=None,
    minio_access_key=None, minio_secret_key=None,
) -> Minio:
    endpoint = minio_endpoint or os.getenv("MINIO_ENDPOINT", "localhost")
    port = minio_port or os.getenv("MINIO_PORT", "9000")
    access_key = minio_access_key or os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = minio_secret_key or os.getenv("MINIO_SECRET_KEY", "minioadmin")
    return Minio(
        endpoint=f"{endpoint}:{port}",
        access_key=access_key, secret_key=secret_key,
        secure=False,
    )
```

#### LATEST.json Pointer File for RAG Index Status

RAG index builds use a `LATEST.json` pointer file in the bucket to track build status (BUILDING, READY, FAILED). The init container polls this file before allowing the RAG service to start.

```python
# services/rag/src/rag/embed_and_index.py (lines 638-651)
pointer = {
    "status": "BUILDING",
    "error_message": None,
    "build_id": build_id,
    "build_ts": build_ts,
}
pointer_json = json.dumps(pointer)
minio_client.put_object(
    bucket_name, "LATEST.json",
    io.BytesIO(pointer_json.encode()),
    length=len(pointer_json),
)
```

The RAG deployment's init container polls MinIO until `LATEST.json` shows `status: "READY"`, blocking the main container from starting until the index is available (from `rag/templates/deployment.yaml` lines 76-150).

#### ML Model Upload and Download via joblib

The clustering service stores trained sklearn models in MinIO as serialized joblib files. Upload uses `put_object` with a BytesIO buffer; download uses `get_object` and deserializes in memory.

```python
# src/alm/utils/minio.py (lines 35-63)
def upload_model_to_minio(model, bucket_name: str, file_name: str):
    minio_client = get_minio_client()
    if not minio_client.bucket_exists(bucket_name):
        minio_client.make_bucket(bucket_name)
    with io.BytesIO() as buffer:
        joblib.dump(model, buffer)
        buffer.seek(0)
        minio_client.put_object(
            bucket_name, file_name, buffer,
            length=buffer.getbuffer().nbytes
        )
```

```python
# services/clustering/model_loader.py (lines 13-39)
def load_from_minio(bucket_name: str, file_name: str):
    minio_client = Minio(
        endpoint=f"{endpoint}:{port}",
        access_key=access_key, secret_key=secret_key,
        secure=False,
    )
    response = minio_client.get_object(bucket_name, file_name)
    with io.BytesIO() as buffer:
        buffer.write(response.data)
        buffer.seek(0)
        return joblib.load(buffer)
```

#### Sample Document Upload Job

An optional Kubernetes Job downloads files from URLs and uploads them to a MinIO bucket. It uses an init container to wait for MinIO health before proceeding.

```yaml
# minio subchart templates/upload-sample-docs.yaml (lines 103-116)
initContainers:
  - name: wait-for-minio
    image: "image-registry.openshift-image-registry.svc:5000/openshift/tools:latest"
    command:
      - /bin/bash
      - -c
      - |
        set -e
        url="http://{{ .Values.secret.host }}:{{ .Values.secret.port }}/minio/health/live"
        until curl -ksf "$url"; do
          sleep 10
        done
```

#### Loki Backend Storage

MinIO also serves as the S3-compatible object store for the Loki logging stack. The Loki Helm chart dependency has its own embedded minio deployment (`loki.minio.enabled: true`) with a separate service account (`minio-sa`) bound to the `anyuid` SCC.

```yaml
# Parent values.yaml (lines 399-442)
loki:
  minio:
    enabled: true
  # ...
  extraObjects:
    - apiVersion: rbac.authorization.k8s.io/v1
      kind: RoleBinding
      metadata:
        name: loki-anyuid-scc
      subjects:
        - kind: ServiceAccount
          name: minio-sa
      roleRef:
        kind: Role
        name: loki-anyuid-scc
```

#### OpenShift Routes

Two OpenShift Routes are created for external access: one for the API (port 9000) and one for the web console (port 9090), both with TLS edge termination.

```yaml
# minio subchart templates/route.yaml
- kind: Route
  metadata:
    name: minio-api
  spec:
    port:
      targetPort: api
    tls:
      termination: edge
      insecureEdgeTerminationPolicy: Redirect
- kind: Route
  metadata:
    name: minio-webui
  spec:
    port:
      targetPort: webui
    tls:
      termination: edge
```

### Configuration
- **Environment variables:**
  - `MINIO_ENDPOINT` -- MinIO hostname (default: `minio`)
  - `MINIO_PORT` -- API port (default: `9000`)
  - `MINIO_ACCESS_KEY` -- S3 access key (default: `minioadmin`)
  - `MINIO_SECRET_KEY` -- S3 secret key (default: `minioadmin`)
  - `MINIO_BUCKET_NAME` -- bucket for clustering models (set to `clustering-model`)
  - `RAG_BUCKET_NAME` -- bucket for RAG indexes (default: `rag-index`)
  - `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` -- server root credentials (set via Secret)
- **Helm values:**
  - `minio.secret.*` -- credentials and host/port for the shared Secret
  - `minio.sampleFileUpload.enabled` / `.bucket` / `.urls` -- optional document seeding Job
  - `minio.volumeClaimTemplates[0].spec.resources.requests.storage` -- PVC size (default: 50Gi)
  - `loki.minio.enabled` -- controls whether Loki deploys its own embedded MinIO

### Known Gotchas
- The `minio` subchart is packaged as a `.tgz` inside `charts/` rather than existing as an extracted directory, so inspecting or modifying templates requires extracting the archive first.
- Loki deploys its own separate MinIO instance (`loki.minio.enabled: true`) with a different service account (`minio-sa`). This is distinct from the application-level MinIO StatefulSet -- the two do not share storage or credentials.
- The `minio-sa` service account for Loki's MinIO requires the `anyuid` SCC on OpenShift (bound via RoleBinding in `loki.extraObjects`).
- The `secure=False` flag is hardcoded in the Python client factory (`src/alm/utils/minio.py` line 31) since traffic stays internal to the cluster. For external access, the OpenShift Routes provide TLS edge termination.
- The clustering service's `model_loader.py` creates its own Minio client directly rather than using the shared `get_minio_client()` utility, duplicating connection logic.
- The upload-sample-docs Job uses `image-registry.openshift-image-registry.svc:5000/openshift/tools:latest` for its init container, which only exists on OpenShift clusters with the internal registry enabled.

### Testing Notes
- Verify MinIO health: `curl -f http://minio:9000/minio/health/live`
- Check RAG index status by reading `LATEST.json` from the `rag-index` bucket -- status should be `READY`
- Verify clustering model exists: check `clustering-model` bucket for `clustering_model.joblib`
- The OpenShift Routes expose both the API and web console externally for manual inspection

### Related Patterns
- Architecture: RAG index lifecycle with LATEST.json status tracking
- Deployment: StatefulSet with PVC for persistent object storage
- Architecture: ML model serving from object storage via joblib

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (ansible-log-analysis) |
|----------|-------------------------------|-----------------------------------|
| Primary use case | Chat attachment uploads | RAG index + ML model + Loki backend storage |
| Python SDK | boto3 / botocore | minio (>=7.2.17) |
| Deployment method | configure-pipeline subchart | Standalone minio subchart (StatefulSet + PVC) |
| Optional/required | Optional via compose profiles and feature flag | Always-on required dependency |
| Number of consumers | Single (backend attachments API) | Multiple (backend, clustering, rag, Loki) |
| Secret pattern | ATTACHMENTS_BUCKET_* env vars | Shared `minio` K8s Secret with secretKeyRef |
| OpenShift Routes | Not created | API + WebUI routes with TLS edge termination |
| Storage persistence | Compose volume (local dev) | 50Gi PVC via StatefulSet VolumeClaimTemplate |
