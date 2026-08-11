---
name: milvus
description: "GPU-accelerated Milvus vector database deployed as nv-ingest Helm sub-dependency with ODF object storage on RHOAI"
summary: "Milvus v2.6.5-gpu provides GPU-accelerated vector indexing with GPU_CAGRA similarity search (dense or hybrid) for RAG quickstarts on RHOAI, deployed as a nested sub-dependency of nv-ingest v26.1.1 in standalone mode with collection multimodal_data consumed by ingestor-server, rag-server, and frontend at milvus:19530. Use when deploying the nv-ingest pipeline needing GPU-accelerated vector search; enable via nv-ingest.milvusDeployed: true in the rag-infrastructure parent chart and set fullnameOverride: milvus for predictable service DNS required by all three consuming services. MIG 1g.12gb GPU slicing requires explicitly setting nvidia.com/gpu: 0 alongside nvidia.com/mig-1g.12gb: \"1\" in both limits and requests to override subchart defaults; ODF ObjectBucketClaim replaces built-in MinIO (minio.enabled: false, externalS3.enabled: true) with OBC credentials mapped to MINIO_* env vars via extraEnv valueFrom. OpenShift requires anyuid SCC RoleBinding for default and nv-ingest ServiceAccounts, etcd podSecurityContext and containerSecurityContext must be {} to clear upstream values conflicting with restricted SCC, MINIO_PORT is forced to \"80\" to avoid TLS cert issues with ODF NooBaa, and OBC Secret/ConfigMap must exist before deployment or pods remain Pending."
metadata:
  type: component
tags:
  tech_stack: [milvus, etcd, helm]
  ai_pattern: [vector-search, rag, embeddings]
  platform: [openshift, rhoai, kserve]
  data_layer: [milvus]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "GPU-accelerated Milvus standalone via nv-ingest subchart with ODF ObjectBucketClaim storage and MIG GPU slicing"
    approach: "A"
---

# Milvus

## Overview

Milvus serves as the GPU-accelerated vector database for RAG-based AI Quickstarts on RHOAI, providing high-performance vector indexing and similarity search. In the aml-rag-nvidia quickstart, it is deployed as a sub-dependency of the nv-ingest Helm subchart in standalone mode, using the GPU-enabled container image with GPU_CAGRA indexing. Rather than using Milvus's built-in MinIO subchart, it connects to ODF-provisioned S3-compatible storage via an ObjectBucketClaim.

## Tech Stack & Dependencies

- **Runtime:** Milvus v2.6.5 (GPU build)
- **Container image:** `docker.io/milvusdb/milvus:v2.6.5-gpu`
- **Key dependencies:** etcd (metadata coordination, deployed as Milvus subchart), ODF NooBaa (S3-compatible object storage via ObjectBucketClaim)
- **Helm subchart:** Sub-dependency of `nv-ingest` v26.1.1 from `https://helm.ngc.nvidia.com/nvidia/nemo-microservices`; Milvus configuration is nested under `nv-ingest.milvus` in the parent chart's values

## Key Patterns

### Nested Subchart Dependency

Milvus is not declared as a direct Helm dependency. It is a sub-dependency of the nv-ingest chart. The parent chart (`rag-infrastructure`) declares nv-ingest as a dependency, and nv-ingest in turn deploys Milvus when `milvusDeployed: true`.

```yaml
# charts/ingest/Chart.yaml
dependencies:
  - condition: ingestor-server.enabled
    name: nv-ingest
    repository: https://helm.ngc.nvidia.com/nvidia/nemo-microservices
    version: 26.1.1
```

```yaml
# charts/ingest/values.yaml (under nv-ingest section)
nv-ingest:
  milvusDeployed: true
  milvus:
    fullnameOverride: milvus
```

### GPU-Accelerated Standalone with MIG Slicing

Milvus runs in standalone mode with GPU acceleration. Instead of consuming a full GPU, it uses a MIG (Multi-Instance GPU) 1g.12gb slice, reducing GPU waste. The subchart default of requesting a full GPU is overridden.

```yaml
# charts/ingest/values.yaml
milvus:
  standalone:
    resources:
      limits:
        # Override subchart default - disable full GPU, use MIG slice instead
        nvidia.com/gpu: 0
        nvidia.com/mig-1g.12gb: "1"
        cpu: "4"
        memory: 8Gi
      requests:
        nvidia.com/gpu: 0
        nvidia.com/mig-1g.12gb: "1"
        cpu: "2"
        memory: 4Gi
```

### ODF ObjectBucketClaim Instead of Built-in MinIO

The built-in Milvus MinIO subchart is disabled in favor of ODF-provisioned S3-compatible storage. OBC credentials are mapped to Milvus-specific `MINIO_*` env vars using `extraEnv` with `valueFrom` references.

```yaml
# charts/ingest/values.yaml
milvus:
  minio:
    enabled: false
  externalS3:
    enabled: true
    useSSL: false
    rootPath: ""
  standalone:
    extraEnv:
      - name: MINIO_ADDRESS
        valueFrom:
          configMapKeyRef:
            name: default-bucket
            key: BUCKET_HOST
      - name: MINIO_PORT
        value: "80"  # Force HTTP port 80; avoids TLS cert verification issues with ODF
      - name: MINIO_ACCESS_KEY_ID
        valueFrom:
          secretKeyRef:
            name: default-bucket
            key: AWS_ACCESS_KEY_ID
      - name: MINIO_SECRET_ACCESS_KEY
        valueFrom:
          secretKeyRef:
            name: default-bucket
            key: AWS_SECRET_ACCESS_KEY
      - name: MINIO_BUCKET_NAME
        valueFrom:
          configMapKeyRef:
            name: default-bucket
            key: BUCKET_NAME
```

### OpenShift-Compatible etcd Security Contexts

The etcd subchart ships with hardcoded security contexts that fail on OpenShift's restricted SCC. These are explicitly cleared to empty objects.

```yaml
# charts/ingest/values.yaml
milvus:
  etcd:
    enabled: true
    # Remove hardcoded security context for OpenShift compatibility
    podSecurityContext: {}
    containerSecurityContext: {}
```

### anyuid SCC for Milvus and nv-ingest

The ingest chart creates a RoleBinding granting `system:openshift:scc:anyuid` to the default and nv-ingest ServiceAccounts, which Milvus pods run under.

```yaml
# charts/ingest/templates/scc-rolebinding.yaml
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:openshift:scc:anyuid
subjects:
  - kind: ServiceAccount
    name: default
    namespace: {{ .Release.Namespace }}
  - kind: ServiceAccount
    name: {{ .Release.Name }}-nv-ingest
    namespace: {{ .Release.Namespace }}
```

### GPU_CAGRA Index Type with Dense Search

The rag-server configures GPU_CAGRA as the vector index type, enabling GPU-accelerated approximate nearest neighbor search with dense embeddings.

```yaml
# charts/rag-server/values.yaml
APP_VECTORSTORE_URL: "http://milvus:19530"
APP_VECTORSTORE_NAME: "milvus"
APP_VECTORSTORE_INDEXTYPE: "GPU_CAGRA"
APP_VECTORSTORE_SEARCHTYPE: "dense"  # Can be "dense" or "hybrid"
APP_VECTORSTORE_ENABLEGPUSEARCH: "True"
APP_VECTORSTORE_EF: "100"
COLLECTION_NAME: "multimodal_data"
```

### Multi-Service Milvus Consumption

Three services connect to Milvus at `http://milvus:19530`, each with their own vectorstore configuration:

```yaml
# charts/ingest/values.yaml (ingestor-server)
APP_VECTORSTORE_URL: "http://milvus:19530"
APP_VECTORSTORE_ENABLEGPUINDEX: "True"
APP_VECTORSTORE_ENABLEGPUSEARCH: "True"

# charts/rag-server/values.yaml
APP_VECTORSTORE_URL: "http://milvus:19530"
APP_VECTORSTORE_INDEXTYPE: "GPU_CAGRA"

# charts/frontend/values.yaml
VITE_MILVUS_URL: "http://milvus.{{ .Release.Namespace }}.svc:19530"
```

## Configuration

- **Environment variables:**
  - `APP_VECTORSTORE_URL` -- Milvus gRPC/REST endpoint, set to `http://milvus:19530` across consuming services
  - `APP_VECTORSTORE_NAME` -- Always `milvus` to select the Milvus driver
  - `APP_VECTORSTORE_INDEXTYPE` -- Index algorithm; set to `GPU_CAGRA` for GPU-accelerated search
  - `APP_VECTORSTORE_SEARCHTYPE` -- `dense` or `hybrid`; controls retrieval strategy
  - `APP_VECTORSTORE_ENABLEGPUINDEX` / `APP_VECTORSTORE_ENABLEGPUSEARCH` -- Enable GPU acceleration for indexing and search
  - `COLLECTION_NAME` -- Vector collection name; set to `multimodal_data`
  - `MILVUS_ENDPOINT` -- Used by nv-ingest directly (`http://milvus:19530`)
  - `MINIO_ADDRESS`, `MINIO_PORT`, `MINIO_ACCESS_KEY_ID`, `MINIO_SECRET_ACCESS_KEY`, `MINIO_BUCKET_NAME` -- Mapped from OBC to configure Milvus's object storage backend
- **Helm values:**
  - `nv-ingest.milvusDeployed` -- Boolean to enable/disable Milvus deployment (default: `true`)
  - `nv-ingest.milvus.fullnameOverride` -- Service name override; set to `milvus` for predictable DNS
  - `nv-ingest.milvus.image.all.tag` -- Milvus image tag; must use `-gpu` suffix for GPU acceleration
  - `nv-ingest.milvus.standalone.resources` -- GPU and memory resource requests/limits
  - `nv-ingest.milvus.minio.enabled` -- Disable built-in MinIO (`false` when using ODF)
  - `nv-ingest.milvus.externalS3.enabled` -- Enable external S3 storage (`true` for ODF)
  - `nv-ingest.milvus.etcd.podSecurityContext` / `containerSecurityContext` -- Set to `{}` for OpenShift

## Known Gotchas

- **MINIO_PORT forced to 80:** The `MINIO_PORT` is hardcoded to `"80"` rather than reading it from the OBC ConfigMap's `BUCKET_PORT`. The comment in `charts/ingest/values.yaml` line 260 explains this avoids TLS certificate verification issues with ODF NooBaa. If your ODF endpoint uses a different port, this value must be manually overridden.
- **anyuid SCC required:** Milvus containers need the `anyuid` SCC to run on OpenShift. The chart creates the RoleBinding automatically (`charts/ingest/templates/scc-rolebinding.yaml`), but the operator deploying the chart must have permission to bind the `anyuid` ClusterRole.
- **etcd security contexts must be emptied:** The Milvus Helm chart's etcd subchart ships with hardcoded `podSecurityContext` and `containerSecurityContext` values that conflict with OpenShift's restricted SCC. Both must be overridden to `{}` (see `charts/ingest/values.yaml` lines 237-238).
- **MIG resource name differs from full GPU:** When using MIG slicing, the resource request changes from `nvidia.com/gpu` to `nvidia.com/mig-1g.12gb`. Both the `limits` and `requests` must explicitly set `nvidia.com/gpu: 0` to prevent the subchart default from requesting a full GPU alongside the MIG slice.
- **OBC timing dependency:** Milvus references the OBC Secret/ConfigMap via `valueFrom`, so Kubernetes blocks pod startup until the OBC resources exist. If ODF is slow to provision the bucket, Milvus pods will remain in `Pending` state (see `docs/advanced-docs/storage-setup.md` lines 67-68).
- **fullnameOverride is critical:** The `fullnameOverride: milvus` setting ensures the service is discoverable at `milvus:19530`. Without it, the service name would include the Helm release name prefix, breaking hardcoded URLs in the ingestor-server, rag-server, nv-ingest, and frontend configurations.

## Testing Notes

- Verify Milvus is running: check that the `milvus` pod and `milvus-etcd` pod are both in `Running` state
- Confirm GPU allocation: `oc describe pod milvus-0 | grep "nvidia.com/mig"` should show the MIG slice allocated
- Test connectivity from consuming services: `oc exec <rag-server-pod> -- curl -s http://milvus:19530/v1/vector/collections` to list collections
- Verify the `multimodal_data` collection exists after ingesting documents
- Check OBC storage: confirm the OBC Secret and ConfigMap (`default-bucket`) exist before Milvus deployment

## Related Patterns

- `deployment/helm-subchart-wiring.md` -- How nested subchart dependencies are configured
- `architectures/rag-pipeline.md` -- How Milvus fits into the RAG retrieval pipeline as the vector store
