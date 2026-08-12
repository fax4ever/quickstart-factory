---
name: minio
description: "S3-compatible object storage for attachments, models, RAG indexes, Langfuse, KServe, document/MLflow, and video/config storage"
summary: "Provides S3-compatible object storage for chat attachments, RAG index and ML model persistence, Loki logging backend, Langfuse v3 observability, KServe guardrail detector model serving, document/MLflow artifact storage, and multimodal video/model/config storage across seven approaches (A-G) with different deployment kinds, Python SDK choices, and optionality patterns. Choose A (boto3, compose profiles, DISABLE_ATTACHMENTS feature flag, configure-pipeline subchart) for optional single-consumer attachment uploads with lazy _get_s3() and session-scoped keys; B (minio Python SDK, standalone StatefulSet subchart, 50Gi PVC) for multi-consumer RAG/ML/Loki with LATEST.json index tracking, joblib serialization, and centralized client factory; C (in-repo Helm Deployment, 100Gi PVC, post-install mc CLI bucket Job) for infrastructure-only with Makefile DEPLOY_MINIO gating, credential validation, and ODH dashboard labels; D (embedded StatefulSet 10Gi PVC, init container mc provisioning, MC_CONFIG_DIR=/tmp/.mc) for Langfuse-dedicated S3 gated by langfuse.enabled with full OpenShift restricted SCC and per-feature LANGFUSE_S3_*_FORCE_PATH_STYLE env vars; E (TrustyAI image, HuggingFace CLI init container, RHOAI data connection Secret with opendatahub.io/connection-type: s3) for KServe InferenceService detector models with helm.sh/weight ordering; F (async boto3 singleton via run_in_executor, embedded Deployment with minio.enabled toggle and external S3 override, 10Gi PVC with persistence toggle) for dual-consumer document uploads with presigned URLs and path traversal protection plus MLflow artifact storage with testcontainers integration tests; G (minio SDK v7.2.20 with retry-with-backoff, ai-architecture-charts subchart v0.5.4, volumeClaimTemplates:[] for ephemeral storage) for multi-bucket video/model/config with s3:// URI scheme, config bucket for horizontal scaling, server-side copy for demo seeding, and mc CLI init container video download. Env var naming differs per approach -- ATTACHMENTS_BUCKET_* (A), MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY with secure=False (B), minio.userId/password Helm values (C), LANGFUSE_S3_*_FORCE_PATH_STYLE: \"true\" required for path-style addressing (D), AWS_* keys in data connection Secret (E), S3_*/AWS_*/MLFLOW_S3_ENDPOINT_URL from centralized Secret with secretKeyRef (F), MINIO_ENDPOINT with http:// scheme auto-stripped by get_minio_client() plus CONFIG_BUCKET/MINIO_VIDEO_BUCKET for bucket-specific env vars (G) -- and Python SDK splits between boto3 lazy initialization for test compatibility (A), minio SDK centralized client factory with config priority params > env > defaults (B), boto3 async singleton with _ensure_bucket() at app lifespan startup (F), and minio SDK with URL parsing and retry-with-backoff download (G). Common gotchas: inverted DISABLE_ATTACHMENTS logic bridged by start script (A); Loki deploys its own separate MinIO instance requiring anyuid SCC via minio-sa ServiceAccount (B); post-install bucket Job lacks wait-for-ready with backoffLimit: 3 and mc:latest unpinned (C); MC_CONFIG_DIR=/tmp/.mc required because default ~/.mc is not writable under restricted SCC, and anonymous download policy exposes all three buckets namespace-wide (D); credentials hardcoded as plain-text THEACCESSKEY/THESECRETKEY and TrustyAI image has different update cadence than standard quay.io/minio/minio (E); Helm entrypoint only pre-creates documents bucket while compose creates both documents and mlflow, and _ensure_bucket() raises ClientError if MinIO not yet healthy at API startup (F); volumeClaimTemplates:[] means all data lost on pod restart including user-uploaded configs, _ping_minio() succeeds before bucketCreation Job completes, and inconsistent retry defaults across download_file() (5 retries/3s) vs _ensure_object_with_retry() (12 retries/2s) (G)."
metadata:
  type: component
tags:
  tech_stack: [minio, python, boto3, fastapi, flask, joblib, faiss, helm, langfuse, kserve, huggingface, mlflow, langgraph, opencv, mediamtx]
  ai_pattern: [rag, embeddings, vector-search, data-pipeline, evaluation, guardrails, model-serving, agents, multimodal]
  platform: [openshift, rhoai, opendatahub, kserve]
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
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Optional MinIO Deployment with in-repo Helm chart, post-install bucket Job, ODH dashboard labels, Makefile-gated install"
    approach: "C"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Langfuse-dedicated MinIO StatefulSet with init container bucket provisioning, OpenShift-hardened security context, pinned image version"
    approach: "D"
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "MinIO Deployment for guardrail detector model storage with HuggingFace init container download, KServe InferenceService consumption via RHOAI data connection Secret"
    approach: "E"
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Multi-consumer MinIO Deployment for document uploads and MLflow artifact storage, boto3 async singleton with thread-pool executor, embedded Helm chart with minio.enabled toggle and external S3 override pattern"
    approach: "F"
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Ephemeral MinIO StatefulSet for multi-bucket video/model/config storage with s3:// URI scheme, mc CLI init container video download, config bucket for horizontal scaling, retry-with-backoff Python client"
    approach: "G"
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

## Approach C: In-Repo Helm Deployment with Post-Install Bucket Job (from data-governance-co-pilot)

### When to Use

When MinIO is an optional infrastructure component deployed via a self-contained Helm chart checked into the repo (not from ai-architecture-charts). This approach is suited for quickstarts that need S3-compatible storage but do not require Python SDK integration -- MinIO is purely infrastructure provisioned through Helm with bucket creation automated via a post-install hook Job.

### Differences from Approach A and B

- **Deployment kind:** Kubernetes Deployment with a separate PVC (not StatefulSet with VolumeClaimTemplate like B, not configure-pipeline subchart like A)
- **Chart source:** In-repo standalone Helm chart at `helm/minio/` -- not packaged from ai-architecture-charts
- **Optionality:** Gated by Makefile `DEPLOY_MINIO` flag (default `false`) with credential validation -- not compose profiles/feature flags (A) or always-on (B)
- **Bucket creation:** Helm `post-install` hook Job using `minio/mc:latest` CLI, not Python SDK auto-create
- **ODH integration:** Secret and ConfigMap carry `opendatahub.io/dashboard: 'true'` label for Open Data Hub dashboard visibility
- **No Python SDK:** No code-level MinIO client -- purely infrastructure

### Tech Stack & Dependencies
- **Runtime:** MinIO server (S3-compatible API)
- **Container image:** `quay.io/minio/minio:latest`
- **Bucket init image:** `minio/mc:latest`
- **Key dependencies:** None at application level -- MinIO is infrastructure-only
- **Helm chart:** In-repo `helm/minio/` chart (v0.1.0, application type)

### Key Patterns

#### Deployment with Separate PVC

MinIO runs as a single-replica Deployment with a Recreate strategy. Storage is a separate 100Gi PVC mounted with a subPath, and explicit resource limits and health probes are defined.

```yaml
# helm/minio/templates/deployment.yaml (lines 1-30, 60-78)
kind: Deployment
apiVersion: apps/v1
metadata:
  name: minio
spec:
  replicas: 1
  strategy:
    type: Recreate
  template:
    spec:
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: minio-pvc
      containers:
        - name: minio
          image: 'quay.io/minio/minio:latest'
          resources:
            limits:
              cpu: 250m
              memory: 1Gi
            requests:
              cpu: 20m
              memory: 100Mi
          readinessProbe:
            tcpSocket:
              port: 9000
            initialDelaySeconds: 5
          livenessProbe:
            tcpSocket:
              port: 9000
            initialDelaySeconds: 30
          volumeMounts:
            - name: data
              mountPath: /data
              subPath: minio
          args:
            - server
            - /data
            - '--console-address'
            - ':9090'
```

#### Post-Install Bucket Creation Job

A Helm post-install hook Job uses the `minio/mc` CLI to create the default bucket after the MinIO pod is ready. The Job uses `helm.sh/hook-delete-policy: hook-succeeded` for automatic cleanup.

```yaml
# helm/minio/templates/create-bucket.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: create-bucket
  annotations:
    "helm.sh/hook": post-install
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: create-bucket
        image: minio/mc:latest
        command: ["/bin/sh", "-c"]
        args:
          - |
            mc alias set minio http://minio-service.{{.Release.Namespace}}.svc.cluster.local:9000 \
              "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" --api S3v4;
            mc mb --ignore-existing minio/${MINIO_DEFAULT_BUCKET};
  backoffLimit: 3
```

#### ODH Dashboard-Labeled Secret and ConfigMap

The Secret and ConfigMap carry the `opendatahub.io/dashboard: 'true'` label, making them visible in the Open Data Hub / RHOAI dashboard. The Secret template comment explicitly notes it should be replaced with ExternalSecret for production.

```yaml
# helm/minio/templates/secrets.yaml
kind: Secret #Should be replaced with ExternalSecret and use a cloud-based solution or something like Vault
apiVersion: v1
metadata:
  name: minio-secret
  labels:
    opendatahub.io/dashboard: 'true'
data:
  MINIO_ROOT_PASSWORD: {{ .Values.minio.password | b64enc | quote}}
  MINIO_ROOT_USER: {{ .Values.minio.userId | b64enc | quote }}
```

```yaml
# helm/minio/templates/config-map.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: minio-config
  labels:
    opendatahub.io/dashboard: 'true'
data:
  DEFAULT_BUCKET: copilot
  DEFAULT_REGION: us-east-1
```

#### Makefile-Gated Install with Credential Validation

The Makefile defaults `DEPLOY_MINIO` to `false` and enforces minimum length requirements on credentials before allowing installation.

```makefile
# helm/Makefile (lines 33, 157-172, 295-306)
DEPLOY_MINIO ?= false

check-minio-credentials:
	@if [ -z "$(minio.userId)" ]; then \
		echo "Set minio.userId to a value that is at least $(MINIMUM_USERID_LENGTH) characters in length."; \
		exit 1; fi
	@if [ -z "$(minio.password)" ]; then \
		echo "Set minio.password to a value that is at least $(MINIMUM_PASSWORD_LENGTH) characters in length."; \
		exit 1; fi

minio-install:
	@helm -n $(NAMESPACE) upgrade --install minio $(MINIO_CHART) \
		--set minio.userId=$(minio.userId) \
		--set minio.password=$(minio.password) \
		--timeout 5m
	@oc wait pod -l app=minio -n $(NAMESPACE) --for=condition=Ready --timeout=60s
```

#### OpenShift Routes with TLS Edge Termination

Two routes expose the MinIO API and console UI externally with TLS edge termination, similar to Approach B.

```yaml
# helm/minio/templates/routes.yaml
kind: Route
apiVersion: route.openshift.io/v1
metadata:
  name: minio-ui
spec:
  to:
    kind: Service
    name: minio-service
  port:
    targetPort: ui
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

### Configuration
- **Environment variables (container):**
  - `MINIO_ROOT_USER` -- server root user from `minio-secret` Secret
  - `MINIO_ROOT_PASSWORD` -- server root password from `minio-secret` Secret
- **ConfigMap (`minio-config`):**
  - `DEFAULT_BUCKET` -- bucket name created by the post-install Job (value: `copilot`)
  - `DEFAULT_REGION` -- AWS region setting (value: `us-east-1`)
- **Helm values:**
  - `minio.userId` -- MinIO root user (required, passed at install time via Makefile)
  - `minio.password` -- MinIO root password (required, passed at install time via Makefile)
- **Makefile parameters:**
  - `DEPLOY_MINIO` -- set to `true` to include MinIO in the install target (default: `false`)
  - `minio.userId` -- forwarded to Helm `--set` (min 3 characters enforced)
  - `minio.password` -- forwarded to Helm `--set` (min 8 characters enforced)

### Known Gotchas
- The Secret template contains a code comment (`#Should be replaced with ExternalSecret and use a cloud-based solution or something like Vault`) indicating this is not production-hardened -- the credentials are plain Helm values base64-encoded into a Secret.
- The PVC requests 100Gi with `ReadWriteOnce` access mode and no storageClassName, relying on the cluster's default StorageClass. This differs from Approach B's 50Gi VolumeClaimTemplate.
- The post-install bucket creation Job uses `minio/mc:latest` and connects to MinIO via the in-cluster service DNS (`minio-service.{{.Release.Namespace}}.svc.cluster.local:9000`). If MinIO is slow to start, the Job may fail and retry up to 3 times (`backoffLimit: 3`) -- there is no explicit wait-for-ready logic in the Job itself.
- The Deployment uses `securityContext: {}` (empty), which means it inherits the namespace's default security context. No explicit SCC binding is created, unlike Approach B's Loki MinIO which requires `anyuid`.
- The `volumeMount` uses `subPath: minio` meaning data is stored in a subdirectory of the PVC rather than at the root, allowing the PVC to potentially be shared with other subPath mounts.
- The Makefile `minio-uninstall` target attempts to delete PVCs matching `minio-data` pattern, but the actual PVC is named `minio-pvc` -- this pattern may not match correctly.

### Testing Notes
- Verify MinIO health via readiness probe: `oc wait pod -l app=minio --for=condition=Ready`
- Check that the post-install Job completed: `oc get jobs create-bucket` (should show `1/1` completions)
- Verify the default bucket exists via the MinIO console route (`minio-ui`)
- Confirm ODH dashboard visibility by checking for resources with `opendatahub.io/dashboard: 'true'` label

### Related Patterns
- Deployment: Helm post-install hook Jobs for initialization
- Deployment: Makefile-gated optional components with credential validation
- Architecture: ODH/RHOAI dashboard integration via resource labels

---

## Approach D: Langfuse-Dedicated StatefulSet with Init Container Bucket Provisioning (from it-self-service-agent)

### When to Use

When MinIO serves as the S3-compatible backend specifically for Langfuse v3 observability (event upload, batch export, media upload). This approach embeds MinIO resources directly in the parent Helm chart templates (not a subchart), uses an init container for bucket provisioning with wait-for-ready logic, and enforces OpenShift-hardened security contexts on all containers.

### Differences from Approaches A, B, and C

- **Purpose:** Dedicated to Langfuse S3 storage, not general-purpose or application-level
- **Conditionality:** Gated by `.Values.langfuse.enabled` -- MinIO only deploys when Langfuse is enabled
- **Image versioning:** Pinned release tag (`RELEASE.2024-12-18T13-15-44Z`) rather than `latest`
- **Deployment kind:** StatefulSet with VolumeClaimTemplate (like B), but embedded in the parent chart templates (not a subchart)
- **Bucket provisioning:** Init container in the Langfuse Deployment pod (not a post-install hook Job like C), with explicit wait-for-ready loop
- **Security:** Full OpenShift-hardened security context on both the MinIO pod and the init container (runAsNonRoot, drop ALL capabilities, seccomp RuntimeDefault)
- **Consumer wiring:** Uses `LANGFUSE_S3_*` namespaced env vars with per-feature bucket separation (events, exports, media) and `FORCE_PATH_STYLE: "true"`
- **No Python SDK:** No application code interacts with MinIO directly -- purely infrastructure for Langfuse
- **Console port:** 9001 (not 9090 like B)

### Tech Stack & Dependencies
- **Runtime:** MinIO server (S3-compatible API)
- **Container image:** `quay.io/minio/minio:RELEASE.2024-12-18T13-15-44Z` (pinned version)
- **Bucket init image:** `quay.io/minio/mc:latest`
- **Key dependencies:** Langfuse web and worker containers consume S3 storage
- **Helm chart:** Embedded in parent chart `helm/templates/minio-deployment.yaml` (not a subchart)

### Key Patterns

#### StatefulSet Gated by Langfuse Feature Flag

The entire MinIO manifest (Secret, Service, StatefulSet) is wrapped in `{{- if .Values.langfuse.enabled }}`, coupling MinIO lifecycle to Langfuse enablement. All resources are labeled with `app.kubernetes.io/component: minio`.

```yaml
# helm/templates/minio-deployment.yaml (lines 1-2, 47-48)
{{- if .Values.langfuse.enabled }}
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ include "self-service-agent.fullname" . }}-minio
spec:
  serviceName: {{ include "self-service-agent.fullname" . }}-minio
  replicas: 1
```

#### OpenShift-Hardened Security Context

Both the pod-level and container-level security contexts enforce restricted SCC compliance, with `runAsNonRoot`, all capabilities dropped, and seccomp profile set to `RuntimeDefault`.

```yaml
# helm/templates/minio-deployment.yaml (lines 65-79)
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: minio
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop:
            - ALL
          runAsNonRoot: true
          seccompProfile:
            type: RuntimeDefault
```

#### Init Container Bucket Provisioning with Wait-for-Ready

Buckets are created by an init container in the Langfuse Deployment (not in the MinIO StatefulSet itself). The init container uses the `MC_HOST_` environment variable pattern to avoid needing a config file, sets `MC_CONFIG_DIR=/tmp/.mc` for OpenShift writability, and polls MinIO with `mc ls` until ready before creating three dedicated buckets with anonymous download policy.

```yaml
# helm/templates/langfuse-deployment.yaml (lines 163-213)
      - name: init-minio
        image: quay.io/minio/mc:latest
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop:
            - ALL
          runAsNonRoot: true
          seccompProfile:
            type: RuntimeDefault
        command:
        - /bin/sh
        - -c
        - |
          export MC_HOST_myminio="http://${MINIO_ACCESS_KEY}:${MINIO_SECRET_KEY}@${MINIO_ENDPOINT}"
          export MC_CONFIG_DIR=/tmp/.mc

          until mc ls myminio/ >/dev/null 2>&1; do
            echo "Waiting for MinIO to be ready..."
            sleep 2
          done

          mc mb --ignore-existing myminio/langfuse-events
          mc mb --ignore-existing myminio/langfuse-exports
          mc mb --ignore-existing myminio/langfuse-media

          mc anonymous set download myminio/langfuse-events
          mc anonymous set download myminio/langfuse-exports
          mc anonymous set download myminio/langfuse-media
```

#### Per-Feature S3 Bucket Wiring in Langfuse

Langfuse web and worker containers each receive three sets of `LANGFUSE_S3_*` env vars -- one per feature (event upload, batch export, media upload). All three point to the same MinIO endpoint but use separate buckets. `FORCE_PATH_STYLE` is required because MinIO uses path-style addressing, not virtual-hosted-style.

```yaml
# helm/templates/langfuse-worker-deployment.yaml (lines 139-203)
        # S3/MinIO Configuration (Event Upload)
        - name: LANGFUSE_S3_EVENT_UPLOAD_ENABLED
          value: "true"
        - name: LANGFUSE_S3_EVENT_UPLOAD_BUCKET
          value: "langfuse-events"
        - name: LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT
          value: http://{{ include "self-service-agent.fullname" . }}-minio:9000
        - name: LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE
          value: "true"
        # ... repeated for BATCH_EXPORT (langfuse-exports) and MEDIA_UPLOAD (langfuse-media)
```

#### Configurable Health Probes and Resources

MinIO health probes use the standard MinIO health endpoints (`/minio/health/live` and `/minio/health/ready`) with all timing parameters exposed through Helm values, allowing tuning without template changes.

```yaml
# helm/values.yaml (lines 864-875)
    healthChecks:
      livenessProbe:
        initialDelaySeconds: 30
        periodSeconds: 10
        timeoutSeconds: 5
        failureThreshold: 3
      readinessProbe:
        initialDelaySeconds: 10
        periodSeconds: 5
        timeoutSeconds: 3
        failureThreshold: 3
```

### Configuration
- **Environment variables (MinIO container):**
  - `MINIO_ROOT_USER` -- from Secret `access-key` field (default: `minioadmin`)
  - `MINIO_ROOT_PASSWORD` -- from Secret `secret-key` field (default: `changeme`)
- **Environment variables (Langfuse consumers):**
  - `LANGFUSE_S3_EVENT_UPLOAD_ENABLED` / `_BUCKET` / `_REGION` / `_ENDPOINT` / `_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` / `_FORCE_PATH_STYLE` -- event upload config
  - `LANGFUSE_S3_BATCH_EXPORT_ENABLED` / `_BUCKET` / `_REGION` / `_ENDPOINT` / `_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` / `_FORCE_PATH_STYLE` -- batch export config
  - `LANGFUSE_S3_MEDIA_UPLOAD_ENABLED` / `_BUCKET` / `_REGION` / `_ENDPOINT` / `_ACCESS_KEY_ID` / `_SECRET_ACCESS_KEY` / `_FORCE_PATH_STYLE` -- media upload config
- **Helm values (`langfuse.minio.*`):**
  - `version` -- MinIO image tag (default: `RELEASE.2024-12-18T13-15-44Z`)
  - `accessKey` / `secretKey` -- credentials stored in Secret
  - `storage` -- PVC size (default: `10Gi`)
  - `storageClass` -- optional, uses cluster default if empty
  - `resources` -- requests and limits (default: 512Mi-1Gi memory, 250m-500m CPU)
  - `healthChecks.livenessProbe.*` / `healthChecks.readinessProbe.*` -- probe timing

### Known Gotchas
- The init container uses `MC_CONFIG_DIR=/tmp/.mc` because the default `~/.mc` directory is not writable in OpenShift's restricted SCC. Without this, the `mc` CLI fails on startup.
- The `MC_HOST_myminio` environment variable pattern (`http://${ACCESS_KEY}:${SECRET_KEY}@${ENDPOINT}`) embeds credentials in a URL. This avoids needing `mc alias set` (which writes a config file) but the credentials appear in the container's environment.
- Anonymous download policy is set on all three buckets (`mc anonymous set download`). This is required for Langfuse's internal S3 access pattern but means any pod in the namespace can read bucket contents without credentials.
- The `LANGFUSE_S3_*_FORCE_PATH_STYLE` env var must be `"true"` because MinIO uses path-style S3 addressing. Omitting this causes Langfuse to attempt virtual-hosted-style requests, which fail against MinIO.
- The Secret default password is `changeme` (line 13 of minio-deployment.yaml) with a hardcoded fallback of `minioadmin` for the access key -- both should be overridden for production via `langfuse.minio.secretKey` and `langfuse.minio.accessKey`.
- The init container image (`quay.io/minio/mc:latest`) is unpinned while the MinIO server image is pinned, creating a potential version mismatch between the CLI and server.
- The S3 region is hardcoded to `us-east-1` in the Langfuse consumer env vars rather than being templated from values, so changing it requires editing the templates directly.

### Testing Notes
- Verify MinIO health: `curl -f http://<release>-minio:9000/minio/health/live`
- Check readiness probe: `curl -f http://<release>-minio:9000/minio/health/ready`
- Confirm buckets exist by exec-ing into the init container log or using the MinIO console at port 9001
- Verify Langfuse can write events by checking the `langfuse-events` bucket for data after running a traced LLM call
- The StatefulSet PVC name follows the pattern `data-<release>-minio-0` -- check `oc get pvc` to confirm binding

### Related Patterns
- Architecture: Langfuse v3 observability stack with S3 backend
- Deployment: Init container for service dependency readiness
- Deployment: OpenShift restricted SCC compliance in security contexts

---

## Approach E: Guardrail Detector Model Storage with HuggingFace Init Container (from lemonade-stand-assistant)

### When to Use

When MinIO serves as S3-compatible storage specifically for guardrail detector models consumed by KServe InferenceServices. Models are downloaded from HuggingFace Hub via an init container and served to KServe through an RHOAI data connection Secret. This approach is suited for quickstarts that deploy multiple small detector models (HAP, prompt injection) alongside a guardrails orchestrator.

### Differences from Approaches A, B, C, and D

- **Purpose:** Dedicated to serving HuggingFace guardrail detector models to KServe InferenceServices, not general storage/attachments/Langfuse
- **Container image:** Uses `quay.io/trustyai/modelmesh-minio-examples:latest` (TrustyAI image), not the standard `quay.io/minio/minio` used in all other approaches
- **Model loading:** Init container uses `quay.io/rgeada/llm_downloader:latest` with `huggingface-cli download` to pull models before MinIO starts
- **Consumer pattern:** KServe InferenceService `storage.key` pointing to an RHOAI data connection Secret (not env vars, not Python SDK, not Langfuse S3 config)
- **Secret format:** RHOAI data connection Secret with `opendatahub.io/connection-type: s3` annotation and AWS_* key names (`AWS_ACCESS_KEY_ID`, `AWS_S3_BUCKET`, etc.)
- **Deployment kind:** Kubernetes Deployment with separate PVC (like C), not StatefulSet
- **No bucket creation step:** Models are written to the PVC by the init container and MinIO serves from that volume directly
- **Helm ordering:** Uses `helm.sh/weight` annotations (`-5` for Service/PVC/Secret, `-4` for Deployment) for install ordering

### Tech Stack & Dependencies
- **Runtime:** MinIO server (S3-compatible API via TrustyAI image)
- **Container image:** `quay.io/trustyai/modelmesh-minio-examples:latest`
- **Model downloader image:** `quay.io/rgeada/llm_downloader:latest`
- **Key dependencies:** KServe InferenceServices and ServingRuntimes consume the stored models; guardrails-detector-huggingface-runtime serves them
- **Helm chart:** Embedded in parent chart `chart/templates/minio-storage-models.yaml` (not a subchart)

### Key Patterns

#### Init Container for HuggingFace Model Download

An init container uses the HuggingFace CLI to download multiple detector models into a shared PVC before the MinIO server starts. The models are stored under `/mnt/models/huggingface/<model-name>`.

```yaml
# chart/templates/minio-storage-models.yaml (lines 56-79)
initContainers:
  - name: download-model
    image: quay.io/rgeada/llm_downloader:latest
    command:
      - bash
      - -c
      - |
        models=(
          ibm-granite/granite-guardian-hap-125m
          protectai/deberta-v3-base-prompt-injection-v2
        )
        echo "Starting download"
        mkdir /mnt/models/llms/
        for model in "${models[@]}"; do
          echo "Downloading $model"
          /tmp/venv/bin/huggingface-cli download $model --local-dir /mnt/models/huggingface/$(basename $model)
        done
        echo "Done!"
    resources:
      limits:
        memory: "2Gi"
        cpu: "1"
    volumeMounts:
      - mountPath: "/mnt/models/"
        name: model-volume
```

#### RHOAI Data Connection Secret

The Secret follows the RHOAI data connection pattern with `opendatahub.io/connection-type: s3` annotation and `opendatahub.io/dashboard: 'true'` plus `opendatahub.io/managed: 'true'` labels. KServe InferenceServices reference this Secret by name via the `storage.key` field to access models from MinIO.

```yaml
# chart/templates/minio-storage-models.yaml (lines 103-120)
apiVersion: v1
kind: Secret
metadata:
  name: minio-data-connection-detector-models
  labels:
    opendatahub.io/dashboard: 'true'
    opendatahub.io/managed: 'true'
  annotations:
    opendatahub.io/connection-type: s3
    openshift.io/display-name: Minio Data Connection - Guardrail Detector Models
data: 
  AWS_ACCESS_KEY_ID: VEhFQUNDRVNTS0VZ
  AWS_DEFAULT_REGION: dXMtc291dGg=
  AWS_S3_BUCKET: aHVnZ2luZ2ZhY2U=
  AWS_S3_ENDPOINT: aHR0cDovL21pbmlvLXN0b3JhZ2UtZ3VhcmRyYWlsLWRldGVjdG9yczo5MDAw
  AWS_SECRET_ACCESS_KEY: VEhFU0VDUkVUS0VZ
type: Opaque
```

#### KServe InferenceService Model Consumption

Downstream KServe InferenceServices reference the data connection Secret and specify a `path` within the S3 bucket to locate each specific model. The `storage.key` field points to the Secret name.

```yaml
# chart/templates/prompt-injection-detector.yaml (lines 59-79)
spec:
  predictor:
    model:
      modelFormat:
        name: guardrails-detector-huggingface
      runtime: guardrails-detector-runtime-prompt-injection
      storage:
        key: minio-data-connection-detector-models
        path: deberta-v3-base-prompt-injection-v2
```

```yaml
# chart/templates/ibm-hap-detector.yaml (lines 57-77)
spec:
  predictor:
    model:
      runtime: guardrails-detector-runtime-hap
      storage:
        key: minio-data-connection-detector-models
        path: granite-guardian-hap-125m
```

#### Hardcoded Credentials in Deployment

MinIO credentials are set as plain-text environment variables directly in the Deployment template, not sourced from a Secret.

```yaml
# chart/templates/minio-storage-models.yaml (lines 85-89)
containers:
  - args:
      - server
      - /models
    env:
      - name: MINIO_ACCESS_KEY
        value:  THEACCESSKEY
      - name: MINIO_SECRET_KEY
        value: THESECRETKEY
```

#### Helm Weight-Based Install Ordering

Resources use `helm.sh/weight` annotations to control installation order. The Service, PVC, and Secret deploy first (weight `-5`), followed by the MinIO Deployment (weight `-4`), then ServingRuntimes (weight `0`), then InferenceServices (weight `1`).

```yaml
# chart/templates/minio-storage-models.yaml (lines 5, 22, 35-36, 110-111)
# Service and PVC at weight -5
annotations:
  helm.sh/weight: "-5"
# Deployment at weight -4
annotations:
  helm.sh/weight: "-4"
```

### Configuration
- **Environment variables (MinIO container):**
  - `MINIO_ACCESS_KEY` -- S3 access key (hardcoded: `THEACCESSKEY`)
  - `MINIO_SECRET_KEY` -- S3 secret key (hardcoded: `THESECRETKEY`)
- **Data connection Secret (`minio-data-connection-detector-models`):**
  - `AWS_ACCESS_KEY_ID` -- base64-encoded access key (decoded: `THEACCESSKEY`)
  - `AWS_SECRET_ACCESS_KEY` -- base64-encoded secret key (decoded: `THESECRETKEY`)
  - `AWS_S3_BUCKET` -- bucket name (decoded: `huggingface`)
  - `AWS_S3_ENDPOINT` -- MinIO endpoint (decoded: `http://minio-storage-guardrail-detectors:9000`)
  - `AWS_DEFAULT_REGION` -- region (decoded: `us-south`)
- **Helm values:** No values.yaml overrides for MinIO itself; detector resources are configurable via `detectors.hap.resources.*` and `detectors.promptInjection.resources.*`
- **Models downloaded:** `ibm-granite/granite-guardian-hap-125m`, `protectai/deberta-v3-base-prompt-injection-v2`

### Known Gotchas
- Credentials are hardcoded as plain-text environment variables in the Deployment template (`MINIO_ACCESS_KEY: THEACCESSKEY`, `MINIO_SECRET_KEY: THESECRETKEY`) and duplicated as base64 in the Secret. These are placeholder values that should be changed for production use.
- The init container downloads models from HuggingFace Hub at deploy time, which requires internet access from the cluster and can be slow depending on model size and network bandwidth. There is no retry logic or progress tracking beyond stdout logging.
- The `maistra.io/expose-route: 'true'` label on the pod template (line 49) suggests this was used in a Service Mesh environment, which may cause unexpected route creation if Istio/Maistra is installed.
- The init container creates a `/mnt/models/llms/` directory (line 68) that is not used by any of the downloaded models -- models are stored under `/mnt/models/huggingface/`. This appears to be a leftover from a previous configuration.
- The MinIO container mounts the volume at `/models/` while the init container mounts at `/mnt/models/`. The init container writes to `/mnt/models/huggingface/<model>` and MinIO serves from `/models/` -- these are the same PVC, so the HuggingFace models end up under `/models/huggingface/<model>` from MinIO's perspective, matching the `huggingface` bucket name in the data connection Secret.
- The container uses `quay.io/trustyai/modelmesh-minio-examples:latest` instead of the standard MinIO image. This is a TrustyAI-maintained image that may have different update cadences or configurations.
- The security context on the MinIO container includes `allowPrivilegeEscalation: false`, `capabilities.drop: ALL`, and `seccompProfile: RuntimeDefault`, but does NOT include `runAsNonRoot` -- unlike Approach D which sets it at both pod and container level.

### Testing Notes
- Verify MinIO pod is running: `oc get pods -l app=minio-storage-guardrail-detectors`
- Check that the init container completed model downloads: `oc logs <pod> -c download-model`
- Verify the data connection Secret exists: `oc get secret minio-data-connection-detector-models`
- Confirm KServe InferenceServices are ready: `oc get inferenceservices prompt-injection-detector guardrails-detector-ibm-hap`
- The InferenceServices should show `READY=True` once they successfully load models from the MinIO storage endpoint

### Related Patterns
- Architecture: Guardrails pipeline with multiple detector models
- Deployment: KServe InferenceService model storage via RHOAI data connections
- Deployment: Init containers for model downloading from HuggingFace Hub
- Deployment: Helm weight annotations for resource ordering

---

## Approach F: Multi-Consumer Document and MLflow Storage with Async boto3 Singleton (from multi-agent-loan-origination)

### When to Use

When MinIO serves two distinct consumers in a multi-agent application -- the FastAPI backend for document uploads (mortgage documents) and MLflow for artifact storage (agent traces, experiment data). This approach uses boto3 with an async thread-pool executor wrapper as a module-level singleton, deploys MinIO as a Deployment embedded in the parent Helm chart with `minio.enabled` toggle, and supports external S3 override for production via `--set minio.enabled=false --set secrets.S3_ENDPOINT=https://...`.

### Differences from Approaches A through E

- **Python SDK:** boto3 with async wrapper via `asyncio.run_in_executor()`, initialized as a singleton at app lifespan (not lazy globals like A, not minio SDK like B)
- **Deployment kind:** Kubernetes Deployment with Recreate strategy, embedded in parent chart templates (not a subchart like A/B, not standalone chart like C)
- **Multi-consumer:** API (document uploads with presigned URLs) and MLflow (artifact storage using AWS_* env vars) share one MinIO instance but use separate buckets (`documents`, `mlflow`)
- **Optionality:** Helm `minio.enabled` toggle with external S3 override pattern documented in values.yaml comments and chart README
- **Bucket init:** Entrypoint `mkdir -p /data/mlflow /data/documents` pre-creates data directories on server side; StorageService `_ensure_bucket()` auto-creates the API bucket client-side
- **Env var naming:** `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION` for API; `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `MLFLOW_S3_ENDPOINT_URL` for MLflow
- **Secret pattern:** Centralized `<release>-secret` K8s Secret containing all app config (S3_* keys for API, MINIO_ROOT_* for server), consumed via secretKeyRef
- **Persistence:** Configurable via `minio.persistence.enabled` with toggle between PVC (10Gi default) and emptyDir
- **Security:** Pod and container security contexts inherited from shared `podSecurityContext` and `securityContext` values
- **Compose:** Always-on service (no profiles), pre-creates both buckets via entrypoint, both API and MLflow declare `minio` as a healthcheck dependency

### Tech Stack & Dependencies
- **Runtime:** MinIO server (S3-compatible API)
- **Container image:** `minio/minio:latest`
- **Key dependencies:** boto3 and botocore in the Python backend for S3 client operations; MLflow uses AWS SDK env vars internally
- **Helm chart:** Embedded in parent chart `deploy/helm/mortgage-ai/templates/minio.yaml` (not a subchart)

### Key Patterns

#### Async boto3 Singleton with Thread-Pool Executor

The StorageService wraps boto3's synchronous S3 client in async methods using `asyncio.run_in_executor()`. It is initialized as a module-level singleton at app startup via `init_storage_service()` and injected via `get_storage_service()`. The s3v4 signature version and path-style addressing are configured explicitly for MinIO compatibility.

```python
# packages/api/src/services/storage.py (lines 23-48)
class StorageService:
    """Thin wrapper around a boto3 S3 client."""

    def __init__(self, endpoint, access_key, secret_key,
                 bucket, region="us-east-1"):
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=BotoConfig(
                signature_version="s3v4",
                s3={"addressing_style": "path",
                    "use_accelerate_endpoint": False},
            ),
        )
        self._ensure_bucket()
```

#### Client-Side Bucket Auto-Creation

The StorageService auto-creates its target bucket on initialization if it does not exist, using `head_bucket` to check existence and `create_bucket` as fallback. This runs at app startup, not lazily.

```python
# packages/api/src/services/storage.py (lines 51-57)
def _ensure_bucket(self) -> None:
    """Create the bucket if it doesn't already exist."""
    try:
        self._client.head_bucket(Bucket=self._bucket)
    except ClientError:
        logger.info("Creating S3 bucket: %s", self._bucket)
        self._client.create_bucket(Bucket=self._bucket)
```

#### Path Traversal Protection in Object Keys

Object keys are built with `os.path.basename()` to strip path components from user-supplied filenames, preventing path traversal attacks through S3 key manipulation.

```python
# packages/api/src/services/storage.py (lines 102-109)
@staticmethod
def build_object_key(application_id: int, document_id: int,
                     filename: str) -> str:
    """Build the S3 object key: {app_id}/{doc_id}/{filename}.

    Strips path components from filename to prevent path traversal.
    """
    safe_name = os.path.basename(filename) or f"doc-{document_id}"
    return f"{application_id}/{document_id}/{safe_name}"
```

#### Presigned URL Generation for Downloads

The StorageService generates presigned GET URLs for secure, time-limited document downloads without exposing MinIO credentials to the frontend.

```python
# packages/api/src/services/storage.py (lines 88-100)
async def get_download_url(self, object_key: str,
                           expires_in: int = 3600) -> str:
    """Return a presigned GET URL for the given object key."""
    loop = asyncio.get_running_loop()
    url: str = await loop.run_in_executor(
        None,
        partial(
            self._client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket, "Key": object_key},
            ExpiresIn=expires_in,
        ),
    )
    return url
```

#### Dual-Bucket Entrypoint Initialization

The compose and Helm entrypoint pre-creates both `documents` and `mlflow` bucket directories before starting the MinIO server, ensuring both consumers have their buckets available immediately.

```yaml
# compose.yml (lines 210-211)
minio:
  image: docker.io/minio/minio:latest
  entrypoint: sh
  command: >-
    -c 'mkdir -p /data/mlflow /data/documents &&
    exec minio server --address ":9000"
    --console-address ":9001" /data'
```

The Helm template uses the same pattern:

```yaml
# deploy/helm/mortgage-ai/templates/minio.yaml (lines 29-35)
command:
  - sh
  - -c
  - >-
    mkdir -p /data/documents &&
    exec minio server --address ":9000"
    --console-address ":9001" /data
```

#### External S3 Override Pattern

The Helm chart supports swapping MinIO for an external S3 endpoint by disabling the MinIO Deployment and overriding the S3 connection secrets. This is documented in the values.yaml header comments.

```yaml
# deploy/helm/mortgage-ai/values.yaml (lines 8-9)
#   External MinIO/S3:  --set minio.enabled=false
#                       --set secrets.S3_ENDPOINT=https://...
```

#### MLflow S3 Artifact Backend

MLflow uses MinIO as its artifact store via AWS SDK env vars. The MLflow container receives `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `MLFLOW_S3_ENDPOINT_URL` pointing to the same MinIO instance, with `s3://mlflow` as the default artifact root.

```yaml
# compose.yml (lines 189-197)
mlflow:
  depends_on:
    minio:
      condition: service_healthy
  environment:
    MLFLOW_DEFAULT_ARTIFACT_ROOT: s3://mlflow
    AWS_ACCESS_KEY_ID: minio
    AWS_SECRET_ACCESS_KEY: miniosecret
    MLFLOW_S3_ENDPOINT_URL: http://minio:9000
```

#### Helm Deployment with Persistence Toggle

The Helm template supports toggling between PVC-backed and emptyDir storage via `minio.persistence.enabled`. The PVC uses the global `storageClass` if set, defaulting to the cluster default.

```yaml
# deploy/helm/mortgage-ai/templates/minio.yaml (lines 72-78)
volumes:
  - name: minio-storage
    {{- if .Values.minio.persistence.enabled }}
    persistentVolumeClaim:
      claimName: {{ .Values.minio.name }}-pvc
    {{- else }}
    emptyDir: {}
    {{- end }}
```

#### Centralized Secret with secretKeyRef

MinIO server credentials and S3 client credentials are both stored in a single centralized Secret (`<release>-secret`). The MinIO Deployment consumes `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` via secretKeyRef; the API Deployment consumes `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_BUCKET`, and `S3_REGION` from the same Secret.

```yaml
# deploy/helm/mortgage-ai/templates/minio.yaml (lines 44-53)
env:
  - name: MINIO_ROOT_USER
    valueFrom:
      secretKeyRef:
        name: {{ include "mortgage-ai.fullname" . }}-secret
        key: MINIO_ROOT_USER
  - name: MINIO_ROOT_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {{ include "mortgage-ai.fullname" . }}-secret
        key: MINIO_ROOT_PASSWORD
```

#### Integration Test with testcontainers

Integration tests use `testcontainers.minio.MinioContainer` to spin up an ephemeral MinIO instance for testing the StorageService, avoiding dependency on external infrastructure.

```python
# packages/api/tests/integration/conftest.py (lines 19, 46-47)
from testcontainers.minio import MinioContainer

@pytest.fixture(scope="session")
def minio_container():
    """Start minio/minio:latest via testcontainers."""
```

### Configuration
- **Environment variables (API consumer):**
  - `S3_ENDPOINT` -- MinIO endpoint URL (default: `http://localhost:9090` local, `http://minio:9000` in compose/cluster)
  - `S3_ACCESS_KEY` -- S3 access key (default: `minio`)
  - `S3_SECRET_KEY` -- S3 secret key (default: `miniosecret`)
  - `S3_BUCKET` -- bucket name for document uploads (default: `documents`)
  - `S3_REGION` -- region (default: `us-east-1`)
  - `UPLOAD_MAX_SIZE_MB` -- maximum upload size in MB (default: `50`)
- **Environment variables (MLflow consumer):**
  - `AWS_ACCESS_KEY_ID` -- S3 access key (same credentials as API)
  - `AWS_SECRET_ACCESS_KEY` -- S3 secret key (same credentials as API)
  - `MLFLOW_S3_ENDPOINT_URL` -- MinIO endpoint (`http://minio:9000`)
  - `MLFLOW_DEFAULT_ARTIFACT_ROOT` -- artifact store URI (`s3://mlflow`)
- **Environment variables (MinIO server):**
  - `MINIO_ROOT_USER` -- root user (default: `minio`)
  - `MINIO_ROOT_PASSWORD` -- root password (default: `miniosecret`)
- **Helm values:**
  - `minio.enabled` -- deploy MinIO (default: `true`); set `false` for external S3
  - `minio.name` -- resource name (default: `minio`)
  - `minio.image.repository` / `.tag` -- container image (default: `minio/minio:latest`)
  - `minio.persistence.enabled` -- PVC or emptyDir (default: `true`)
  - `minio.persistence.size` -- PVC size (default: `10Gi`)
  - `minio.resources` -- requests and limits (default: 128Mi-384Mi memory, 100m-500m CPU)
  - `secrets.S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` / `S3_REGION` -- S3 connection for API
  - `secrets.MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` -- MinIO server credentials

### Known Gotchas
- The compose port mapping uses `9090:9000` for the API and `9091:9001` for the console, which differs from most MinIO setups that use `9000:9000`. The `S3_ENDPOINT` default in the Python config (`config.py` line 132) is `http://localhost:9090` to match this mapping, while the in-container endpoint remains `http://minio:9000`.
- The Helm entrypoint only pre-creates the `documents` directory (`mkdir -p /data/documents`) while the compose entrypoint pre-creates both `documents` and `mlflow` (`mkdir -p /data/mlflow /data/documents`). The MLflow bucket on cluster may need to be created separately or by MLflow's own initialization.
- The StorageService uses `run_in_executor(None, ...)` with the default executor (thread pool), wrapping boto3's synchronous calls. This is documented as intentional at the top of the module (`storage.py` lines 4-5: "Uses boto3 synchronous client run in a thread-pool executor for async compatibility").
- The `_ensure_bucket()` method runs at singleton initialization time (app startup), not lazily. If MinIO is not yet healthy when the API starts, initialization will raise a `ClientError`. The compose healthcheck dependency (`minio: condition: service_healthy`) prevents this in local dev, but on cluster the API pod may need readiness probes tuned to allow MinIO startup time.
- The `get_storage_service()` function raises `RuntimeError("StorageService not initialised")` if called before `init_storage_service()` -- this guards against using the storage module before the app lifespan hook runs.
- The `build_object_key()` static method includes path traversal protection via `os.path.basename()` (noted in the docstring at line 107 of storage.py: "Strips path components from filename to prevent path traversal attacks").
- MLflow and the API use the same MinIO credentials but different env var naming conventions -- `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` for MLflow vs. `S3_ACCESS_KEY`/`S3_SECRET_KEY` for the API. Both are sourced from the same Helm Secret.

### Testing Notes
- Verify MinIO health via compose healthcheck: `curl -sf http://localhost:9090/minio/health/live`
- Console is available at port 9091 locally for manual inspection (credentials from `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`)
- Integration tests use `testcontainers.minio.MinioContainer` to spin up ephemeral MinIO instances -- no external MinIO dependency needed for testing
- Verify both buckets exist (`documents` and `mlflow`) after startup by checking the MinIO console or using `mc ls`
- Test the external S3 override by deploying with `--set minio.enabled=false --set secrets.S3_ENDPOINT=https://...`

### Related Patterns
- Architecture: Multi-agent loan origination with per-agent document handling
- Deployment: Embedded Helm Deployment with enabled/disabled toggle and external override
- Architecture: MLflow artifact storage via S3-compatible backend
- Architecture: async singleton service pattern with FastAPI lifespan hooks

---

## Approach G: Ephemeral Multi-Bucket Video/Model/Config Storage with s3:// URI Scheme (from multimodal-compliance-monitor)

### When to Use

When MinIO serves as shared ephemeral storage for a multimodal video processing pipeline -- storing ML models, video files, and user-uploaded configs across purpose-specific buckets. This approach uses the `minio` Python SDK with retry-with-backoff logic, deploys via the ai-architecture-charts `minio` subchart (v0.5.4) as a StatefulSet but overrides the VolumeClaimTemplate to empty (no PVC left after `helm uninstall`), and uses `s3://bucket/key` URIs as universal object references parsed by both Python code and shell scripts. A separate "config" bucket enables horizontal scaling by moving user uploads and thumbnails out of the local filesystem.

### Differences from Approaches A through F

- **Storage lifecycle:** Ephemeral -- `volumeClaimTemplates: []` overrides the subchart default 50Gi PVC, so no PVC is created or left behind after `helm uninstall` (unlike B which uses VolumeClaimTemplate and C/E which use separate PVCs)
- **Multi-bucket strategy:** Three purpose-specific buckets (`models`, `data`, `config`) auto-created by the subchart's `bucketCreation` feature (not Python SDK like A/B, not post-install Job like C, not init container like D)
- **Video pipeline consumer:** mc CLI init container downloads video from MinIO for FFmpeg/RTSP streaming via MediaMTX (unique to this approach)
- **s3:// URI scheme:** Universal `s3://bucket/key` object references parsed by both Python (`_resolve_video_source_to_path()`) and Helm templates (`mc cp` commands) -- not used in other approaches
- **Config bucket for horizontal scaling:** User uploads and thumbnails stored in MinIO (`config` bucket) instead of local filesystem, documented in values.yaml as enabling horizontal scaling
- **Server-side copy:** Uses `copy_object()` (S3 server-side copy) for seeding demo configs between buckets -- not used in other approaches
- **Retry logic:** Built-in retry-with-backoff in `download_file()` and `_ping_minio()` utility for startup readiness
- **URL parsing:** `get_minio_client()` strips scheme from full URLs (handles both `host:port` and `http://host:port`)
- **Python SDK:** Uses `minio>=7.2.20` (like B's minio SDK, not boto3 like A/F)
- **Helm subchart:** ai-architecture-charts `minio` subchart v0.5.4 (B uses v0.1.0 of the same chart)
- **Env var naming:** `MINIO_ENDPOINT` (full URL with `http://` prefix), `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_SECURE`, `CONFIG_BUCKET`, `MINIO_VIDEO_BUCKET` -- includes bucket-specific env vars not in other approaches
- **Secret pattern:** Plain values in Helm `values.yaml` (`minio.secret.*`) injected directly into env vars (not secretKeyRef like B/F)
- **Always-on:** Required dependency with no feature flag gating

### Tech Stack & Dependencies
- **Runtime:** MinIO server (S3-compatible API)
- **Container image:** `quay.io/minio/minio:latest` (from subchart)
- **Key dependencies:** `minio>=7.2.20` Python SDK, `minio/mc:latest` CLI for init containers, opencv-python for thumbnail generation, Flask backend
- **Helm subchart:** `minio` (v0.5.4) from `https://rh-ai-quickstart.github.io/ai-architecture-charts`

### Key Patterns

#### Ephemeral StatefulSet with PVC Override

The parent chart overrides the subchart's VolumeClaimTemplate to empty, preventing persistent storage. This means MinIO data does not survive pod restarts but also avoids PVCs being left behind after `helm uninstall`.

```yaml
# deploy/helm/ppe-compliance-monitor/values.yaml (lines 71-73)
minio:
  # Disable persistent storage so the PVC is not left behind after helm uninstall
  volumeClaimTemplates: []
  volumeMounts: []
```

#### Multi-Bucket Auto-Creation via Subchart Feature

Three purpose-specific buckets are auto-created by the subchart's `bucketCreation` feature, each serving a distinct role in the video processing pipeline.

```yaml
# deploy/helm/ppe-compliance-monitor/values.yaml (lines 63-69)
minio:
  bucketCreation:
    enabled: true
    buckets:
      - models
      - data
      - config # User uploads and thumbnails (enables horizontal scaling)
```

#### Centralized MinIO Client with URL Parsing and Retry

The `minio_client.py` module provides a centralized client factory that handles both bare `host:port` and full `http://host:port` URL formats by stripping the scheme. The `download_file()` function includes configurable retry-with-backoff logic.

```python
# app/backend/minio_client.py (lines 23-41)
def get_minio_client():
    endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
    access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"
    # Minio() expects bare host:port; strip scheme if a full URL was provided
    parsed = urlparse(endpoint)
    if parsed.scheme in ("http", "https"):
        endpoint = parsed.netloc or parsed.path
        if parsed.scheme == "https":
            secure = True
    return Minio(endpoint, access_key=access_key,
                 secret_key=secret_key, secure=secure)
```

```python
# app/backend/minio_client.py (lines 44-88)
def download_file(bucket, object_name, local_path,
                  max_retries=5, retry_delay=3):
    client = get_minio_client()
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    for attempt in range(max_retries):
        try:
            client.fget_object(bucket, object_name, local_path)
            return local_path
        except S3Error as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                raise
```

#### s3:// URI Scheme as Universal Object Reference

Video sources, thumbnails, and demo config seeds all use `s3://bucket/key` URIs as universal references. The backend parses these to determine whether to download from MinIO or use a local/RTSP path.

```python
# app/backend/video_processing/consumer.py (lines 18-43)
def _resolve_video_source_to_path(video_source: str):
    """S3 URIs (s3://bucket/key) are downloaded to a temp file."""
    p = video_source.strip()
    if p.startswith("s3://"):
        parts = p[5:].split("/", 1)
        if len(parts) == 2:
            bucket, key = parts[0], parts[1]
            fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            download_file(bucket, key, tmp_path)
            return tmp_path, tmp_path
    return video_source, None
```

The seeding code builds these URIs when creating app configs:

```python
# app/backend/seed_demo_configs.py (lines 233-234)
dest_key = f"uploads/{video_filename}"
video_uri = f"s3://{cfg_bucket}/{dest_key}"
```

#### Config Bucket for Horizontal Scaling

User-uploaded videos and generated thumbnails are stored in the MinIO `config` bucket instead of the local filesystem, enabling multiple backend replicas to share state. The upload endpoint returns an `s3://` URI.

```python
# app/backend/app.py (lines 581-603)
@api.route("/config/upload", methods=["POST"])
def config_upload():
    """Upload a video file to MinIO. Returns S3 URI."""
    safe_name = os.path.basename(f.filename)
    bucket = get_config_bucket()
    object_key = f"uploads/{safe_name}"
    data = f.read()
    upload_bytes(bucket, object_key, data, content_type="video/mp4")
    path = f"s3://{bucket}/{object_key}"
    return jsonify({"path": path, "filename": safe_name})
```

Thumbnails are generated from S3 videos and stored back in MinIO:

```python
# app/backend/thumbnail_utils.py (lines 35-42)
def generate_thumbnail_for_video_source(video_path: str):
    """Generate a JPEG thumbnail from S3 video, upload to MinIO.
    Thumbnails are always stored in the config bucket under thumbnails/."""
    thumb_bucket = get_config_bucket()
    thumb_key = f"thumbnails/{stem}.jpg"
```

#### Server-Side Copy for Demo Seeding

Demo configuration seeding uses MinIO server-side copy to move sample videos from the `data` bucket to the `config` bucket, avoiding unnecessary data transfer through the backend.

```python
# app/backend/seed_demo_configs.py (lines 162-192)
def _ensure_object_with_retry(dest_bucket, dest_key,
                               src_bucket, src_key,
                               max_retries=12, delay_s=2.0):
    if object_exists(dest_bucket, dest_key):
        return
    for attempt in range(max_retries):
        if not object_exists(src_bucket, src_key):
            time.sleep(delay_s)
            continue
        copy_object(dest_bucket, dest_key, src_bucket, src_key)
        return
```

#### mc CLI Init Container for Video Download

The video-stream deployment uses a `minio/mc` init container to download video files from MinIO before the FFmpeg sidecar starts streaming via MediaMTX. The init container uses `mc alias set` with wait-for-ready retry logic.

```yaml
# deploy/helm/ppe-compliance-monitor/templates/video-stream-deployment.yaml (lines 23-52)
initContainers:
  - name: download-video
    image: "{{ .Values.videoStream.ffmpegImage.repository }}:{{ .Values.videoStream.ffmpegImage.tag }}"
    command:
      - /bin/sh
      - -c
      - |
        set -e
        export MC_CONFIG_DIR=/tmp/.mc
        SRC="myminio/{{ .Values.storage.video.bucket }}/{{ .Values.storage.video.key }}"
        until mc alias set myminio "${MINIO_ENDPOINT}" \
            "{{ .Values.minio.secret.user }}" "{{ .Values.minio.secret.password }}"; do
          sleep 2
        done
        mc cp "${SRC}" /data/video.mp4
```

#### MinIO Startup Ping with Retry

The demo seeding process includes an explicit MinIO readiness check with retry before attempting any bucket operations.

```python
# app/backend/seed_demo_configs.py (lines 195-209)
def _ping_minio(max_attempts=15, delay_s=2.0):
    for attempt in range(max_attempts):
        try:
            client = get_minio_client()
            client.list_buckets()
            return
        except Exception as e:
            if attempt == max_attempts - 1:
                raise RuntimeError(
                    f"MinIO not reachable after {max_attempts} attempts: {e}"
                ) from e
            time.sleep(delay_s)
```

#### Runtime Deployer Consuming MinIO Credentials

The KServe runtime deployer Job receives MinIO credentials to create a data connection Secret for model serving. It references the first bucket from `bucketCreation.buckets` for the model storage bucket.

```yaml
# deploy/helm/ppe-compliance-monitor/templates/runtime-deployer.yaml (lines 143-166)
- name: S3_BUCKET
  value: {{ index .Values.minio.bucketCreation.buckets 0 | quote }}
- name: MINIO_ENDPOINT
  value: "http://{{ .Values.minio.secret.host }}:{{ .Values.minio.secret.port }}"
- name: MINIO_ACCESS_KEY
  value: {{ .Values.minio.secret.user | quote }}
- name: MINIO_SECRET_KEY
  value: {{ .Values.minio.secret.password | quote }}
```

### Configuration
- **Environment variables (backend):**
  - `MINIO_ENDPOINT` -- MinIO endpoint URL with scheme (default: `http://minio:9000`)
  - `MINIO_ACCESS_KEY` -- S3 access key (default: `minioadmin`)
  - `MINIO_SECRET_KEY` -- S3 secret key (default: `minioadmin`)
  - `MINIO_SECURE` -- TLS flag (default: `false`)
  - `CONFIG_BUCKET` -- bucket for user uploads and thumbnails (default: `config`)
  - `MINIO_VIDEO_BUCKET` -- bucket for video files (default: `data`)
- **Environment variables (MinIO server):**
  - `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` -- from subchart Secret
- **Helm values:**
  - `minio.secret.user` / `password` / `host` / `port` -- credentials and connection (default: `minioadmin`/`minioadmin`/`minio`/`9000`)
  - `minio.bucketCreation.enabled` / `buckets` -- auto-create buckets on deployment (default: `[models, data, config]`)
  - `minio.volumeClaimTemplates` -- override to `[]` to disable persistent storage
  - `minio.volumeMounts` -- override to `[]` when PVC is disabled
  - `storage.model.bucket` / `key` -- model file location (default: `models`/`ppe.pt`)
  - `storage.video.bucket` / `key` -- video file location (default: `data`/`combined-video-no-gap-rooftop.mp4`)

### Known Gotchas
- The `volumeClaimTemplates: []` override disables persistent storage, meaning all MinIO data is lost on pod restart. The init-data Job re-uploads models and videos on each deployment, but user-uploaded configs and thumbnails in the `config` bucket are not recovered. This is a deliberate tradeoff documented in the values.yaml comment (line 72): "Disable persistent storage so the PVC is not left behind after helm uninstall."
- The `get_minio_client()` function (line 29-31 of `minio_client.py`) strips the URL scheme from `MINIO_ENDPOINT` because the `Minio()` constructor expects bare `host:port`. The Helm templates inject `http://minio:9000` as the full URL, so this parsing is required. If the scheme is `https`, the function also sets `secure=True`.
- The video-stream init container uses `minio/mc` as its image (line 24 of `video-stream-deployment.yaml`) via `videoStream.ffmpegImage.repository`, which is confusingly named since it is not actually FFmpeg -- it is the MinIO client CLI used for downloading video.
- Credentials are injected as plain Helm values directly into env vars (not via secretKeyRef from a K8s Secret). The init-data Job, backend deployment, video-stream, and runtime-deployer all receive credentials the same way. The subchart does create a K8s Secret, but the parent chart templates do not reference it.
- The `_ping_minio()` function (line 195 of `seed_demo_configs.py`) calls `list_buckets()` to check MinIO readiness. If MinIO is up but the `bucketCreation` Job has not yet completed, the ping succeeds but subsequent bucket operations may fail on non-existent buckets.
- Unit tests mock the `minio_client` module at the `sys.modules` level (line 59-64 of `test_alert_endpoints.py`) to avoid needing a running MinIO instance, similar to Approach A's lazy init pattern but using monkeypatch instead.
- The `download_file()` retry logic (5 retries, 3-second delay) and `_ensure_object_with_retry()` (12 retries, 2-second delay) use different defaults, creating inconsistent retry behavior across the codebase.

### Testing Notes
- Verify MinIO health: `curl -f http://minio:9000/minio/health/live` (compose healthcheck uses this)
- Console is available at port 9001 locally for manual inspection (credentials: `minioadmin`/`minioadmin`)
- Check that all three buckets exist (`models`, `data`, `config`) after the `bucketCreation` Job completes
- Verify the init-data Job uploaded model and video files: check `models` bucket for `ppe.pt` and `data` bucket for video files
- Unit tests use `monkeypatch.setitem(sys.modules, "minio_client", ...)` to stub out MinIO operations
- On OpenShift, verify the video-stream init container successfully downloaded from MinIO by checking its logs: `oc logs <pod> -c download-video`

### Related Patterns
- Architecture: Video processing pipeline with RTSP streaming from S3-hosted MP4 files
- Deployment: ai-architecture-charts minio subchart with PVC override for ephemeral storage
- Architecture: Config bucket pattern for horizontal backend scaling
- Deployment: mc CLI init containers for artifact download

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (ansible-log-analysis) | Approach C (data-governance-co-pilot) | Approach D (it-self-service-agent) | Approach E (lemonade-stand-assistant) | Approach F (multi-agent-loan-origination) | Approach G (multimodal-compliance-monitor) |
|----------|-------------------------------|-----------------------------------|---------------------------------------|-------------------------------------|---------------------------------------|-------------------------------------------|---------------------------------------------|
| Primary use case | Chat attachment uploads | RAG index + ML model + Loki backend storage | General-purpose S3 storage (infrastructure-only) | Langfuse v3 S3 backend (events, exports, media) | Guardrail detector model storage for KServe | Document uploads + MLflow artifact storage | Video/model/config storage for multimodal video processing pipeline |
| Python SDK | boto3 / botocore | minio (>=7.2.17) | None -- no application-level client | None -- Langfuse handles S3 internally | None -- KServe handles S3 via data connection | boto3 / botocore with async thread-pool executor wrapper | minio (>=7.2.20) with retry-with-backoff and URL parsing |
| Deployment method | configure-pipeline subchart | Standalone minio subchart (StatefulSet + PVC) | In-repo Helm chart (Deployment + separate PVC) | Embedded in parent chart templates (StatefulSet + VolumeClaimTemplate) | Embedded in parent chart templates (Deployment + separate PVC) | Embedded in parent chart templates (Deployment + optional PVC) | ai-architecture-charts minio subchart (StatefulSet, PVC disabled via override) |
| Optional/required | Optional via compose profiles and feature flag | Always-on required dependency | Optional via Makefile `DEPLOY_MINIO` flag | Conditional on `langfuse.enabled` | Always-on required dependency | Optional via Helm `minio.enabled` toggle with external S3 override | Always-on required dependency |
| Number of consumers | Single (backend attachments API) | Multiple (backend, clustering, rag, Loki) | Infrastructure-only, consumers not wired in chart | Two (Langfuse web + worker) | Multiple KServe InferenceServices (HAP, prompt injection detectors) | Two (FastAPI document API + MLflow artifact store) | Multiple (backend, init-data Job, video-stream init container, runtime-deployer) |
| Secret pattern | ATTACHMENTS_BUCKET_* env vars | Shared `minio` K8s Secret with secretKeyRef | `minio-secret` with ODH dashboard label | `<release>-minio-secret` with access-key/secret-key fields | RHOAI data connection Secret with AWS_* keys and `opendatahub.io/connection-type: s3` | Centralized `<release>-secret` with S3_* and MINIO_ROOT_* keys via secretKeyRef | Plain values in Helm values.yaml injected directly into env vars |
| OpenShift Routes | Not created | API + WebUI routes with TLS edge termination | API + UI routes with TLS edge termination | Not created (internal-only) | Not created (internal-only) | Not created (internal-only) | API + WebUI routes with TLS edge termination (from subchart) |
| Storage persistence | Compose volume (local dev) | 50Gi PVC via StatefulSet VolumeClaimTemplate | 100Gi PVC (ReadWriteOnce, separate resource) | 10Gi PVC via StatefulSet VolumeClaimTemplate | 50Gi PVC (ReadWriteOnce, separate resource) | 10Gi PVC or emptyDir (toggled via `persistence.enabled`) | Ephemeral -- VolumeClaimTemplate overridden to [] (compose uses named volume) |
| Bucket creation | Python SDK auto-create on first use | Python SDK make_bucket + sample doc upload Job | Helm post-install hook Job using minio/mc CLI | Init container with mc CLI + wait-for-ready loop | Init container downloads models directly to PVC | Entrypoint mkdir + Python SDK auto-create on startup | Subchart `bucketCreation` feature with bucket list |
| ODH dashboard integration | No | No | Yes (`opendatahub.io/dashboard: 'true'` labels) | No | Yes (`opendatahub.io/dashboard: 'true'` + `opendatahub.io/managed: 'true'` labels, `opendatahub.io/connection-type: s3` annotation) | No | No |
| Chart source | ai-architecture-charts | ai-architecture-charts | In-repo (`helm/minio/`) | Embedded in parent chart templates | Embedded in parent chart templates | Embedded in parent chart templates | ai-architecture-charts (minio v0.5.4 subchart) |
| Image version | latest | latest | latest | Pinned release tag | latest (TrustyAI image) | latest | latest (from subchart) |
| Security context | Not specified | Not specified | Empty (`{}`) | Full OpenShift restricted SCC (runAsNonRoot, drop ALL, seccomp) | Partial (drop ALL, seccomp, no runAsNonRoot) | Inherited from shared podSecurityContext/securityContext values | Not specified (subchart defaults) |
