---
name: minio
description: "S3-compatible object storage for file attachments, optional via compose profiles and feature flags"
summary: "MinIO (quay.io/minio/minio:latest) provides S3-compatible object storage for quickstarts, handling chat attachment uploads (Approach A), serving as shared infrastructure for RAG index persistence, ML model storage, Loki log backend, and document seeding (Approach B), or providing infrastructure-only S3 storage with automated bucket provisioning and ODH dashboard integration (Approach C). Use Approach A (boto3, configure-pipeline subchart v0.5.6, ATTACHMENTS_BUCKET_* env vars) when MinIO is a single-purpose optional service gated by compose `attachments` profile and inverted DISABLE_ATTACHMENTS flag; use Approach B (minio Python SDK >=7.2.17, standalone minio subchart v0.1.0 as StatefulSet with 50Gi PVC, MINIO_* env vars with shared K8s Secret) when MinIO is always-on with multiple consumers (backend, clustering, rag, Loki); use Approach C (in-repo helm/minio/ chart as Deployment with 100Gi PVC, Makefile DEPLOY_MINIO flag, post-install minio/mc bucket Job, opendatahub.io/dashboard: 'true' labels) when MinIO is infrastructure-only with no Python SDK integration. Approach A uses lazy _get_s3() with module-level globals and auto-bucket via head_bucket/create_bucket storing attachments under session-scoped keys ({session_id}/{attachment_id}{ext}); Approach B uses centralized get_minio_client() factory (secure=False hardcoded, config priority: params > env vars > defaults), LATEST.json pointer tracking RAG index status (BUILDING/READY/FAILED), joblib serialization for ML model storage, and OpenShift Routes with TLS edge termination; Approach C uses Helm post-install hook Job with minio/mc:latest CLI connecting via in-cluster DNS (backoffLimit: 3, hook-delete-policy: hook-succeeded) and Makefile credential validation enforcing minimum length requirements. The start-dev.sh script bridges ENABLE_ATTACHMENTS to the inverted DISABLE_ATTACHMENTS flag, compose backend must declare MinIO with `required: false` to avoid blocking startup, Loki deploys its own separate MinIO with anyuid SCC for minio-sa, the minio subchart is packaged as .tgz requiring extraction to inspect templates, Approach C's Secret template is noted as not production-hardened (should use ExternalSecret/Vault), the post-install bucket Job has no explicit wait-for-ready logic, clustering model_loader.py duplicates client logic bypassing the shared factory, and session-scoped authorization remains unimplemented (TODO)."
metadata:
  type: component
tags:
  tech_stack: [minio, python, boto3, fastapi, joblib, faiss, helm]
  ai_pattern: [rag, embeddings, vector-search, data-pipeline]
  platform: [openshift, rhoai, opendatahub]
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

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (ansible-log-analysis) | Approach C (data-governance-co-pilot) |
|----------|-------------------------------|-----------------------------------|---------------------------------------|
| Primary use case | Chat attachment uploads | RAG index + ML model + Loki backend storage | General-purpose S3 storage (infrastructure-only) |
| Python SDK | boto3 / botocore | minio (>=7.2.17) | None -- no application-level client |
| Deployment method | configure-pipeline subchart | Standalone minio subchart (StatefulSet + PVC) | In-repo Helm chart (Deployment + separate PVC) |
| Optional/required | Optional via compose profiles and feature flag | Always-on required dependency | Optional via Makefile `DEPLOY_MINIO` flag |
| Number of consumers | Single (backend attachments API) | Multiple (backend, clustering, rag, Loki) | Infrastructure-only, consumers not wired in chart |
| Secret pattern | ATTACHMENTS_BUCKET_* env vars | Shared `minio` K8s Secret with secretKeyRef | `minio-secret` with ODH dashboard label |
| OpenShift Routes | Not created | API + WebUI routes with TLS edge termination | API + UI routes with TLS edge termination |
| Storage persistence | Compose volume (local dev) | 50Gi PVC via StatefulSet VolumeClaimTemplate | 100Gi PVC (ReadWriteOnce, separate resource) |
| Bucket creation | Python SDK auto-create on first use | Python SDK make_bucket + sample doc upload Job | Helm post-install hook Job using minio/mc CLI |
| ODH dashboard integration | No | No | Yes (`opendatahub.io/dashboard: 'true'` labels) |
| Chart source | ai-architecture-charts | ai-architecture-charts | In-repo (`helm/minio/`) |
