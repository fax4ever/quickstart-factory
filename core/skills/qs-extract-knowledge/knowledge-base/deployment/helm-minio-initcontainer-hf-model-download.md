---
name: helm-minio-initcontainer-hf-model-download
description: MinIO Deployment with HuggingFace CLI init container downloading detector models into PVC for KServe S3 storage
summary: "Deploys MinIO with a quay.io/rgeada/llm_downloader init container (2Gi memory, 1 CPU) that downloads HuggingFace detector models (granite-guardian-hap-125m, deberta-v3-base-prompt-injection-v2) into a 50Gi PVC at /mnt/models/huggingface/<basename>, served to KServe InferenceServices via OpenDataHub-labeled S3 data connection Secret minio-data-connection-detector-models -- an alternative to OCI modelcar URIs for guardrail model delivery. Use when KServe detectors need S3-compatible model access rather than OCI modelcar packaging; requires public HuggingFace access from the cluster during init. Helm weights (-5/-4 for Service/PVC/Secret, 0/1 for ServingRuntimes/InferenceServices) enforce deployment ordering; InferenceServices reference models via storage.key pointing to the data connection Secret and storage.path for the model subdirectory. Gotchas: MinIO credentials (THEACCESSKEY/THESECRETKEY) are hardcoded in Deployment env vars and base64-encoded in the Secret rather than templated from values.yaml, the init container uses non-standard path /tmp/venv/bin/huggingface-cli from the downloader image, and an unused /mnt/models/llms/ directory is created during download."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, minio]
  ai_pattern: [guardrails, model-serving]
  platform: [kserve, rhoai, openshift]
source_examples:
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "MinIO Deployment with init container downloading 2 HF detector models into PVC, served to KServe InferenceServices via S3 data connection Secret"
    approach: "A"
---

# MinIO with HuggingFace CLI Init Container for Model Download

## Overview

This pattern deploys a MinIO object storage server as a standard Kubernetes Deployment with an init container that pre-downloads HuggingFace model weights using `huggingface-cli`. The downloaded models are stored on a PVC and served to KServe InferenceServices via an S3-compatible data connection Secret. This provides an alternative to OCI modelcar URIs for delivering model weights to detector services.

## Pattern Description

A single template file defines four resources: a Service, PVC, Deployment (with init container), and a Secret for the S3 data connection. The init container uses a dedicated downloader image (`quay.io/rgeada/llm_downloader`) that includes `huggingface-cli` to download one or more models into a shared PVC. The main MinIO container then serves these models over S3. KServe InferenceServices reference the models via their `storage.key` field pointing to the data connection Secret.

## Implementation

### Init Container Model Download

The init container iterates over a list of HuggingFace model IDs and downloads each one into a subdirectory under `/mnt/models/huggingface/`:

```yaml
# chart/templates/minio-storage-models.yaml
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

### MinIO Deployment with PVC

The MinIO container serves the downloaded models from the same PVC, with security context for OpenShift:

```yaml
# chart/templates/minio-storage-models.yaml
containers:
  - args:
      - server
      - /models
    env:
      - name: MINIO_ACCESS_KEY
        value: THEACCESSKEY
      - name: MINIO_SECRET_KEY
        value: THESECRETKEY
    image: quay.io/trustyai/modelmesh-minio-examples:latest
    name: minio
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop:
          - ALL
      seccompProfile:
        type: RuntimeDefault
    volumeMounts:
      - mountPath: "/models/"
        name: model-volume
```

### S3 Data Connection Secret

KServe InferenceServices reference the MinIO storage through an OpenDataHub-labeled data connection Secret:

```yaml
# chart/templates/minio-storage-models.yaml
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

### Helm Weight Ordering

The MinIO resources use `helm.sh/weight` annotations to ensure storage is available before detectors deploy:

```yaml
# chart/templates/minio-storage-models.yaml
# Service, PVC, and Secret use weight "-5" (deploy first)
# Deployment uses weight "-4" (deploy after PVC/Service)
# Detector ServingRuntimes use weight "0"
# Detector InferenceServices use weight "1" (deploy after runtimes)
```

## Configuration

- **Key settings:** MinIO access/secret keys are hardcoded in the Deployment env vars (`THEACCESSKEY`/`THESECRETKEY`) and base64-encoded in the Secret; the PVC requests 50Gi storage; the init container has 2Gi memory / 1 CPU limits
- **Defaults:** The init container downloads two specific models (`ibm-granite/granite-guardian-hap-125m` and `protectai/deberta-v3-base-prompt-injection-v2`); MinIO serves from `/models/` (mapped to PVC)
- **Dependencies:** KServe InferenceServices must reference the Secret name via `storage.key: minio-data-connection-detector-models` and the model subdirectory via `storage.path` (e.g., `granite-guardian-hap-125m`); requires public HuggingFace access from the cluster during init

## Gotchas

- The MinIO access and secret keys are hardcoded in both the Deployment env vars and the data connection Secret (base64-encoded `THEACCESSKEY`/`THESECRETKEY`) -- these are not templated from values.yaml (see `chart/templates/minio-storage-models.yaml`)
- The init container uses `/tmp/venv/bin/huggingface-cli` which is pre-installed in the `quay.io/rgeada/llm_downloader:latest` image -- this is not the standard `huggingface_hub` CLI install path (see `chart/templates/minio-storage-models.yaml`)
- The init container downloads models into `/mnt/models/huggingface/<model-basename>` but also creates an empty `/mnt/models/llms/` directory that appears unused (see `chart/templates/minio-storage-models.yaml`)
- Helm weights ensure ordering: MinIO resources at weight `-5`/`-4` deploy before detector ServingRuntimes at weight `0` and InferenceServices at weight `1` -- without these weights, detectors might attempt to load models before MinIO is ready (see `chart/templates/minio-storage-models.yaml` and `chart/templates/ibm-hap-detector.yaml`)

## Related Patterns

- `kserve-rawdeployment-detector-fleet-gpu-toggle.md` -- the detector InferenceServices that consume models from this MinIO storage
- `helm-trustyai-orchestrator-configmap-detector-wiring.md` -- the orchestrator that routes traffic through detectors served by these models
