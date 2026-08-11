---
name: configure-pipeline
description: "Shared Helm subchart that provisions MinIO S3 storage, seeds sample documents, and optionally creates a Jupyter notebook"
summary: "configure-pipeline (v0.5.6, ai-architecture-charts) is a shared Helm subchart that provisions MinIO S3-compatible object storage, creates credential Kubernetes Secrets, seeds sample documents from external URLs into a target bucket, optionally creates a Jupyter notebook (alpine/git init container clones notebook.repo into workspace) wired via rag-pipeline-secrets and rag-ingestion-pipeline-secret, and bootstraps a DataSciencePipelinesApplication (DSPA) CR for Kubeflow Pipelines v2 with MariaDB for RHOAI quickstart RAG data pipelines. Use as a Chart.yaml dependency when a quickstart needs S3 storage for document ingestion — set notebook.create=false via install script --set overrides when using Kubeflow Pipelines or a dedicated ingestion pod instead of interactive notebooks; set configure-pipeline.enabled=false for Kind e2e tests where OpenShift CRDs (DSPA, Notebook) are unavailable; downstream, ingestion-pipeline consumes the provisioned MinIO storage feeding pgvector and llamastack. Configure via configure-pipeline.minio.secret.{user,password,host,port} and sampleFileUpload.{enabled,bucket,urls} in values.yaml; Makefile defaults (MINIO_USER, MINIO_PASSWORD) are passed through install_with_env.sh via --set and must match the subchart's expected key paths; DSPA's pipelineStorage.deployMinio appends release namespace to MinIO host for in-cluster DNS; notebook secrets hardcode Llama Stack (port 8321) and DSPA (port 8888) service URLs. Credentials defined in both values.yaml and Makefile will break S3 if mismatched, sampleFileUpload.urls downloads from external GitHub URLs that fail silently if unreachable, port must be string \"9000\" not integer, notebook.create=false override lives only in install_with_env.sh — omitting it spawns an unnecessary notebook pod, the upload-sample-docs-job uses OpenShift-internal image registry unavailable on vanilla Kubernetes, and changing llamastack/DSPA service names silently breaks notebook environment secrets."
metadata:
  type: component
tags:
  tech_stack: [minio, helm, jupyter]
  ai_pattern: [data-pipeline, rag]
  platform: [openshift, kubernetes, rhoai, kubeflow]
  data_layer: []
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Uses configure-pipeline to provision MinIO with sample PDF upload for RAG knowledge base ingestion"
    approach: "A"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Uses configure-pipeline v0.5.9 with notebook enabled, DSPA for Kubeflow Pipelines, and multiple sample PDF uploads; disabled in Kind e2e tests"
    approach: "A"
---

# Configure Pipeline

## Overview

`configure-pipeline` is a shared Helm subchart from `ai-architecture-charts` that bootstraps the data ingestion infrastructure for RHOAI quickstarts. It provisions MinIO S3-compatible object storage, creates secrets for S3 credentials, optionally uploads sample files to a designated bucket, and can create a Jupyter notebook for interactive pipeline development. It works alongside the `ingestion-pipeline` subchart, which consumes the S3 storage it provisions.

## Tech Stack & Dependencies

- **Runtime:** Helm subchart (no application code of its own)
- **Container image:** MinIO (provisioned by the subchart)
- **Key dependencies:** ai-architecture-charts Helm repository
- **Helm subchart:** `configure-pipeline` v0.5.6 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`

## Key Patterns

### Subchart Dependency Declaration

The parent quickstart chart declares `configure-pipeline` as a dependency in `Chart.yaml`, pulling it from the shared `ai-architecture-charts` repository alongside other infrastructure subcharts.

```yaml
# deploy/cluster/helm/Chart.yaml
dependencies:
  - name: configure-pipeline
    version: 0.5.6
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
```

### MinIO Credential Configuration via Values

The parent chart passes MinIO credentials and sample file upload settings to the subchart through the `configure-pipeline` key in `values.yaml`. The secret block defines the S3-compatible credentials, and `sampleFileUpload` seeds the bucket with documents on first install.

```yaml
# deploy/cluster/helm/values.yaml
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
      - https://raw.githubusercontent.com/burrsutter/sample-pdfs/main/FantaCo/HR/FantaCo-Fabulous-HR-Benefits.pdf
```

### Notebook Creation Override

The install script explicitly disables the Jupyter notebook feature of `configure-pipeline` for cluster deployments, since this quickstart uses a dedicated ingestion monitor pod and Kubeflow Pipelines instead.

```bash
# deploy/cluster/scripts/install_with_env.sh
cmd_args+=("--set" "configure-pipeline.notebook.create=false")
cmd_args+=("--set" "ingestion-pipeline.defaultPipeline.enabled=false")
```

### MinIO Credentials Passed Through Makefile

The cluster Makefile defines MinIO credential defaults that are passed into the Helm install. These match the `configure-pipeline` values, ensuring consistency between the Makefile install target and the subchart secret.

```makefile
# deploy/cluster/Makefile
MINIO_USER ?= minio_rag_user
MINIO_PASSWORD ?= minio_rag_password
```

These are forwarded via `install_with_env.sh`:

```bash
cmd_args+=("--set" "minio.secret.user=$MINIO_USER")
cmd_args+=("--set" "minio.secret.password=$MINIO_PASSWORD")
```

### DataSciencePipelinesApplication (DSPA) Provisioning

The subchart creates a `DataSciencePipelinesApplication` custom resource (from OpenDataHub) that bootstraps Kubeflow Pipelines v2 infrastructure. The DSPA connects to MinIO for artifact storage and deploys MariaDB for pipeline metadata. When `pipelineStorage.deployMinio` is true, the subchart appends the release namespace to the MinIO host for correct in-cluster DNS resolution.

```yaml
# configure-pipeline/templates/pipeline.yaml
apiVersion: datasciencepipelinesapplications.opendatahub.io/v1
kind: DataSciencePipelinesApplication
metadata:
  name: dspa
spec:
  dspVersion: v2
  objectStorage:
    externalStorage:
      host: "minio.<namespace>"
      port: "9000"
      bucket: "mlpipeline"
      scheme: "http"
  database:
    mariaDB:
      deploy: true
      pvcSize: 10Gi
```

### Notebook Environment Secret Wiring

When `notebook.create` is true, the subchart creates two secrets that wire the notebook's environment to cluster-internal services. The `rag-pipeline-secrets` secret provides the notebook with MinIO, Llama Stack, and DSPA endpoints. The `rag-ingestion-pipeline-secret` secret provides S3 ingestion parameters (embedding model, bucket, credentials).

```yaml
# configure-pipeline/templates/rag-pipeline-secrets.yaml
stringData:
  MINIO_ENDPOINT: "http://minio.<namespace>.svc.cluster.local:9000"
  LLAMASTACK_BASE_URL: "http://llamastack.<namespace>.svc.cluster.local:8321"
  DS_PIPELINE_URL: "https://ds-pipeline-dspa.<namespace>.svc.cluster.local:8888"
```

## Configuration

- **Environment variables:** None injected directly; MinIO credentials are mounted as a Kubernetes Secret created by the subchart
- **Config files:** None (pure Helm values-driven)
- **Helm values:**
  - `configure-pipeline.minio.secret.user` -- MinIO access key
  - `configure-pipeline.minio.secret.password` -- MinIO secret key
  - `configure-pipeline.minio.secret.host` -- MinIO service hostname (default: `minio`)
  - `configure-pipeline.minio.secret.port` -- MinIO service port (default: `"9000"`)
  - `configure-pipeline.minio.sampleFileUpload.enabled` -- Whether to seed sample documents into the bucket
  - `configure-pipeline.minio.sampleFileUpload.bucket` -- Target bucket name for sample documents
  - `configure-pipeline.minio.sampleFileUpload.urls` -- List of URLs to download and upload into the bucket
  - `configure-pipeline.notebook.create` -- Whether to create a Jupyter notebook (set to `false` for cluster deploy in ai-virtual-agent)
  - `configure-pipeline.notebook.repo` -- Git repository URL cloned into the notebook workspace (default: RAG quickstart repo)
  - `configure-pipeline.notebook.pvcName` -- PVC name for notebook storage (default: `pipeline-vol`)
  - `configure-pipeline.notebook.embedding_model` -- Embedding model name written into the ingestion secret (default: `all-MiniLM-L6-v2`)
  - `configure-pipeline.pipelineStorage.deployMinio` -- Whether to deploy MinIO as a DSPA storage backend (default: `true`)
  - `configure-pipeline.pipelineStorage.externalStorage.bucket` -- Bucket for Kubeflow pipeline artifacts (default: `mlpipeline`)
  - `configure-pipeline.secret.create` -- Whether to create the `rag-pipeline-secrets` and `rag-ingestion-pipeline-secret` Kubernetes Secrets (default: `true`)
  - `configure-pipeline.enabled` -- Master toggle; set to `false` to skip the entire subchart (used by RAG e2e tests on Kind)

## Known Gotchas

- The install script sets `configure-pipeline.notebook.create=false` separately from the values.yaml defaults, meaning the notebook creation toggle is only visible in the install script (`deploy/cluster/scripts/install_with_env.sh` line 78), not in the chart's `values.yaml`. Forgetting this override would create an unnecessary notebook pod.
- MinIO credentials are set in two places: the `values.yaml` under `configure-pipeline.minio.secret` and the Makefile defaults (`MINIO_USER`, `MINIO_PASSWORD`). The install script passes the Makefile values via `--set minio.secret.user=...`, which must align with the subchart's expected key path. A mismatch between these two sources could produce a broken S3 configuration.
- The `sampleFileUpload.urls` list downloads from external GitHub URLs at install time. If the URLs are unreachable (network restrictions, deleted files), the sample seeding fails silently or blocks the init job.
- The `port` value under `minio.secret` is a string (`"9000"`), not an integer, as required by the subchart's secret template.
- (RAG) The configure-pipeline subchart requires OpenShift-specific CRDs (`DataSciencePipelinesApplication` from OpenDataHub, `Notebook` from Kubeflow). In Kind-based e2e tests, the RAG quickstart disables `configure-pipeline.enabled: false` entirely and stubs out these CRDs in the CI workflow (`.github/workflows/e2e-tests.yaml`).
- (RAG) The `rag-pipeline-secrets` Kubernetes Secret hardcodes the Llama Stack URL as `http://llamastack.<namespace>.svc.cluster.local:8321` and the DSPA URL as `https://ds-pipeline-dspa.<namespace>.svc.cluster.local:8888`. Changing service names for llamastack or the DSPA in other subcharts would silently break the notebook's environment.
- (RAG) The `upload-sample-docs-job` init container uses `image-registry.openshift-image-registry.svc:5000/openshift/tools:latest` to wait for MinIO readiness, which is only available on OpenShift clusters. This prevents the sample upload job from running on vanilla Kubernetes.

## Testing Notes

- After deployment, verify MinIO is running: check for the `minio` pod and `minio` service in the namespace
- Verify the sample document was uploaded: `aws --endpoint-url http://minio:9000 s3 ls s3://documents/` (or use `oc port-forward svc/minio 9000:9000` for local access)
- The uninstall target in the Makefile explicitly cleans up MinIO PVCs: `oc get pvc -n $NAMESPACE | grep minio-data`
- The ingestion pipeline downstream depends on MinIO being ready; if `configure-pipeline` fails, knowledge base creation will stay in PENDING status indefinitely
- (RAG) On OpenShift, the DSPA creates several pods: `ds-pipeline-dspa`, `ds-pipeline-metadata-envoy-dspa`, `ds-pipeline-metadata-grpc-dspa`, `ds-pipeline-persistenceagent-dspa`, `ds-pipeline-scheduledworkflow-dspa`, `ds-pipeline-workflow-controller-dspa`, `mariadb-dspa`, and `minio-dspa`. Expect 8+ additional pods from the DSPA alone.
- (RAG) The Jupyter notebook pod (`rag-pipeline-notebook-0`) clones the quickstart repo's `notebooks/` directory into its workspace via an `alpine/git` init container. Verify the notebooks are present at `/opt/app-root/src/` inside the notebook container.

## Related Patterns

- `ingestion-pipeline` subchart -- consumes the MinIO storage provisioned by `configure-pipeline` to run Kubeflow-based document ingestion
- `pgvector` component -- stores the vector embeddings produced by the ingestion pipeline
- `llamastack` component -- registers vector databases and serves RAG queries against the ingested data
