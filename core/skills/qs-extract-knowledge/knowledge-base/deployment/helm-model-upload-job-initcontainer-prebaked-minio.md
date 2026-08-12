---
name: helm-model-upload-job-initcontainer-prebaked-minio
description: Helm Job with initContainer that copies model files from a prebaked image to an emptyDir for MinIO upload via mc CLI
summary: "Uploads ML model files from a prebaked container image to MinIO S3 using a Helm-templated Kubernetes Job with an initContainer that copies files via cp glob to an emptyDir volume, then a minio/mc container that creates the bucket with mc mb --ignore-existing and uploads via mc cp --recursive. Use when models are already embedded in a container image (from a multistage build) and must be staged in MinIO for KServe InferenceService consumption; for models sourced from HuggingFace, use helm-minio-initcontainer-hf-model-download instead. Key settings: backoffLimit: 3, ttlSecondsAfterFinished: 300 for auto-cleanup, MC_CONFIG_DIR: /tmp/.mc (default ~/.mc not writable in minio/mc image), restartPolicy: OnFailure, and a shared minio-credentials Secret with serving.kserve.io/s3-endpoint and s3-usehttps annotations that configures both the upload Job env vars and the KServe ServiceAccount. Gotchas: initContainer cp glob flattens files into /export/ without parent directory structure, the 30-retry mc alias set loop is essential because the Job may launch before MinIO Deployment is ready, and the dual-purpose minio-credentials Secret must carry serving.kserve.io/s3-* annotations for KServe S3 discovery."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [model-serving]
  platform: [openshift, kserve]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Job uses prebaked MLServer image as initContainer to extract sklearn model files, then uploads to MinIO via mc CLI with retry loop"
    approach: "A"
---

# Model Upload Job with InitContainer from Prebaked Image

## Overview

This pattern uploads machine learning model files to MinIO S3 storage using a Kubernetes Job with two containers: an initContainer that copies model files from a prebaked container image to an emptyDir volume, and a main container that uploads them to MinIO using the `mc` (MinIO Client) CLI. It bridges the gap between models embedded in container images and model storage systems like MinIO/S3 that KServe InferenceService expects.

## Pattern Description

The Job's initContainer runs the prebaked model image (which contains the model files at a known path) and uses a simple `cp` command to extract files to a shared emptyDir volume. The main container then runs the `minio/mc` image, waits for MinIO readiness with a retry loop, creates the target bucket, and uploads the model files. The Job uses `ttlSecondsAfterFinished` for automatic cleanup and `backoffLimit` for retry on failure.

## Implementation

### Job Template

```yaml
# deploy/helm/templates/job-model-upload.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: model-upload
  namespace: {{ .Values.namespace }}
spec:
  backoffLimit: 3
  ttlSecondsAfterFinished: 300
  template:
    spec:
      restartPolicy: OnFailure
      initContainers:
        - name: prepare-model
          image: {{ .Values.image.repository }}:{{ .Values.image.tags.guidelinesModel }}
          command:
            - sh
            - -c
            - cp /opt/mlserver/models/guidelines-mlp/* /export/
          volumeMounts:
            - name: model-files
              mountPath: /export
      containers:
        - name: upload
          image: docker.io/minio/mc:latest
          command:
            - sh
            - -c
            - |
              set -e
              ls -la /export/
              for i in $(seq 1 30); do
                mc alias set minio http://minio:9000 "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" && break
                echo "Waiting for MinIO... ($i/30)"
                sleep 2
              done
              mc mb --ignore-existing minio/models
              mc cp --recursive /export/ minio/models/guidelines-mlp/
              mc ls minio/models/guidelines-mlp/
              echo "Model uploaded successfully"
          env:
            - name: MC_CONFIG_DIR
              value: /tmp/.mc
            - name: AWS_ACCESS_KEY_ID
              valueFrom:
                secretKeyRef:
                  name: minio-credentials
                  key: AWS_ACCESS_KEY_ID
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom:
                secretKeyRef:
                  name: minio-credentials
                  key: AWS_SECRET_ACCESS_KEY
          volumeMounts:
            - name: model-files
              mountPath: /export
      volumes:
        - name: model-files
          emptyDir: {}
```

### MinIO Credentials Secret

The MinIO credentials are shared between the upload Job and the KServe ServiceAccount:

```yaml
# deploy/helm/templates/secret-minio.yaml
apiVersion: v1
kind: Secret
metadata:
  name: minio-credentials
  annotations:
    serving.kserve.io/s3-endpoint: minio.{{ .Values.namespace }}.svc.cluster.local:9000
    serving.kserve.io/s3-usehttps: "0"
    serving.kserve.io/s3-region: us-east-1
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: {{ .Values.minio.rootUser }}
  AWS_SECRET_ACCESS_KEY: {{ .Values.minio.rootPassword }}
```

## Configuration

- **Key settings:** `backoffLimit: 3` retries on failure; `ttlSecondsAfterFinished: 300` auto-cleans completed Jobs after 5 minutes; `MC_CONFIG_DIR: /tmp/.mc` avoids writing to read-only home directory
- **Defaults:** MinIO endpoint is `http://minio:9000`; model path is `/opt/mlserver/models/guidelines-mlp/` in the prebaked image; target bucket is `minio/models/guidelines-mlp/`
- **Dependencies:** MinIO deployment must be running in the same namespace; the prebaked model image must be accessible from the cluster; MinIO credentials Secret must exist

## Gotchas

- The initContainer copies from `/opt/mlserver/models/guidelines-mlp/*` (a glob) rather than the directory itself, so the files are placed directly in `/export/` without the parent directory structure (see `job-model-upload.yaml` initContainer command)
- The `MC_CONFIG_DIR` is set to `/tmp/.mc` because the default `~/.mc` location may not be writable in the `minio/mc` container (see `job-model-upload.yaml` env)
- The MinIO credentials Secret uses `serving.kserve.io/s3-*` annotations which configure the KServe ServiceAccount for S3 access; the same Secret serves both the upload Job and the KServe model serving (see `deploy/helm/templates/secret-minio.yaml` annotations)
- The `--ignore-existing` flag on `mc mb` makes the bucket creation idempotent, allowing the Job to be rerun without error if the bucket already exists (see `job-model-upload.yaml` upload command)
- The retry loop attempts `mc alias set` up to 30 times with 2-second sleep to wait for MinIO readiness; this is necessary because the Job may start before the MinIO Deployment is fully ready (see `job-model-upload.yaml` upload command)

## Related Patterns

- `container-build-mlserver-model-unwrap-multistage.md` -- the prebaked image used as the initContainer source
- `helm-kserve-mlserver-sklearn-minio-rawdeployment.md` -- the InferenceService that consumes models from MinIO
- `helm-minio-initcontainer-hf-model-download.md` -- alternative pattern that downloads models from HuggingFace into MinIO
