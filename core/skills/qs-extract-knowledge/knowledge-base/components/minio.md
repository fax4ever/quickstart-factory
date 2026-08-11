---
name: minio
description: "S3-compatible object storage for file attachments, optional via compose profiles and feature flags"
summary: "MinIO (quay.io/minio/minio:latest) provides S3-compatible object storage for chat attachment uploads in quickstarts, deployed as an optional service gated by a compose `attachments` profile and a backend DISABLE_ATTACHMENTS feature flag with inverted logic. Use when quickstarts need file attachment handling alongside chat sessions; on OpenShift, MinIO is provisioned via the configure-pipeline Helm subchart (v0.5.6) with secret creation and optional sampleFileUpload document seeding rather than a standalone chart. Critical pattern is the _get_s3() lazy initialization of boto3 client/resource using module-level globals with auto-bucket creation via head_bucket/create_bucket, storing attachments under session-scoped keys ({session_id}/{attachment_id}{ext}) for bulk deletion. The compose backend must declare MinIO with `required: false` to avoid blocking startup when attachments are disabled, the start script bridges ENABLE_ATTACHMENTS to DISABLE_ATTACHMENTS for the backend, lazy S3 init is required to avoid import-time network calls that break unit tests, and session-scoped authorization checks remain unimplemented (TODO)."
metadata:
  type: component
tags:
  tech_stack: [minio, python, boto3, fastapi]
  ai_pattern: []
  platform: [openshift, rhoai]
  data_layer: [minio]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Optional MinIO for chat attachment uploads, controlled by compose profiles and feature flag"
    approach: "A"
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
