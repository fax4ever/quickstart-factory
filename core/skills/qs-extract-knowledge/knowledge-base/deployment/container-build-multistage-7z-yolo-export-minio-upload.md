---
name: container-build-multistage-7z-yolo-export-minio-upload
description: Three-stage container build extracting 7z archives, exporting YOLO models to OpenVINO IR and ONNX, uploading to MinIO
summary: "Solves preparing both YOLO model weights (OpenVINO IR and ONNX formats) and compressed video data for a multi-runtime serving quickstart (OVMS and Triton) via a three-stage Dockerfile pipeline. Use when a single data-image must produce runtime-ready artifacts for multiple model serving runtimes from raw .pt weights and 7z-split archives — stages are Alpine+p7zip extraction, ultralytics export via export_models.py with EXPORT_EXCLUDE_STEMS filtering, and minio/mc idempotent upload. Critical config: RUNTIME_TYPE controls Triton ONNX uploads (kserve only) while OVMS assets (ovms/<name>/1/<name>.xml layout) always upload; OVMS_CONFIG_NIREQ/PLUGIN_CONFIG/SHAPE env vars regenerate multi-model config.json; build context must be app/ not app/data-image/ (-f app/data-image/Dockerfile app). Regenerated config.json must write to /tmp (not baked-in path) because OpenShift random-UID SCC makes the container filesystem read-only; Triton config.pbtxt only uploads for the ppe model stem; MinIO must be healthy before start (compose depends_on service_healthy, Helm backoffLimit: 3)."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, minio]
  ai_pattern: [model-serving, multimodal]
  platform: [openvino, openshift]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "3-stage data image: alpine 7z extract, ultralytics YOLO export (OpenVINO IR + ONNX), minio/mc upload with idempotent upload.sh"
    approach: "A"
---

# Multi-Stage Container Build: 7z Extract, YOLO Export, MinIO Upload

## Overview

A three-stage container image pipeline that extracts compressed video archives, exports YOLO model weights to multiple inference formats (OpenVINO IR and ONNX), and uploads all artifacts to MinIO object storage. This pattern solves the problem of preparing both model and data artifacts for a multi-runtime model serving quickstart where the same weights must be served by different runtimes (OVMS and Triton).

## Pattern Description

The data image uses three build stages to convert raw `.pt` weights and compressed video archives into runtime-ready artifacts. Stage 1 (alpine) extracts 7z-split video archives and stages raw weights. Stage 2 (ultralytics) runs model export to OpenVINO IR and ONNX formats using a shared Python script. Stage 3 (minio/mc) bundles all outputs with an idempotent upload shell script that handles both runtime types and generates OVMS multi-model `config.json` from environment variables.

## Implementation

### Stage 1: Archive Extraction (alpine)

Uses `p7zip` to extract split 7z archives and stages raw `.pt` weights:

```dockerfile
# app/data-image/Dockerfile
FROM docker.io/library/alpine@sha256:... AS extractor
RUN apk add --no-cache p7zip
WORKDIR /extract
COPY data/combined-video-no-gap-rooftop.mp4.7z.* ./data/
RUN cd data && 7z x combined-video-no-gap-rooftop.mp4.7z.001
COPY data/bluejayclear.mp4 ./data/
COPY data/cars.mp4 ./data/
COPY models /extract/models/
```

### Stage 2: Model Export (ultralytics)

Exports every `.pt` file to OpenVINO IR and ONNX using a shared Python script (`export_models.py`), with exclusion support:

```dockerfile
# app/data-image/Dockerfile
FROM docker.io/ultralytics/ultralytics@sha256:... AS exporter
COPY --from=extractor /extract/models /weights
COPY data-image/export_models.py /tmp/export_models.py
RUN pip install --no-cache-dir git+https://github.com/openai/CLIP.git && \
    python3 /tmp/export_models.py
```

The export script writes OpenVINO IR trees to `/exported-openvino/` and ONNX trees to `/exported-onnx/`, organized for their respective runtimes (OVMS expects `ovms/<name>/1/<name>.xml`, Triton expects `triton/<name>/1/model.onnx`).

### Stage 3: Upload Image (minio/mc)

Assembles all artifacts and includes an idempotent upload script:

```dockerfile
# app/data-image/Dockerfile
FROM docker.io/minio/mc@sha256:...
WORKDIR /upload
COPY --from=extractor /extract/data/combined-video-no-gap-rooftop.mp4 /upload/data/
COPY --from=extractor /extract/models /upload/models-pt/
COPY --from=exporter /exported-openvino/ /upload/models/
COPY --from=exporter /exported-onnx/ /upload/models/
COPY data-image/config/config.pbtxt /upload/triton-config/config.pbtxt
COPY data-image/upload.sh /upload/upload.sh
ENTRYPOINT ["/bin/sh", "/upload/upload.sh"]
```

### Idempotent Upload Script

The `upload.sh` script checks each artifact before uploading (skips if already present), creates buckets idempotently, and regenerates OVMS `config.json` from environment variables when `OVMS_CONFIG_*` vars are set. It writes the regenerated config to `/tmp` because the baked-in file is read-only under OpenShift's random-UID SCC:

```bash
# app/data-image/upload.sh (excerpt)
mc mb --ignore-existing myminio/models
mc mb --ignore-existing myminio/data
mc mb --ignore-existing myminio/config

# Upload OVMS assets regardless of RUNTIME_TYPE
if [ -d /upload/models/ovms ]; then
  for d in /upload/models/ovms/*/; do
    base=$(basename "$d")
    if ! mc stat "myminio/models/ovms/${base}/1/${base}.xml" >/dev/null 2>&1; then
      mc cp --recursive "$d" "myminio/models/ovms/${base}/"
    fi
  done
fi
```

### Build Context

The build context must be the `app` directory (not `app/data-image`) so that both `data-image/` and `models/` subdirectories are available. The Makefile target reflects this:

```makefile
# Makefile (excerpt)
build-data:
	podman build --platform $(PLATFORM_RELEASE) -t $(DATA_IMAGE) -f app/data-image/Dockerfile app
```

## Configuration

- **Key settings:** `RUNTIME_TYPE` (openvino or kserve) controls which model format uploads are performed; `OVMS_CONFIG_NIREQ`, `OVMS_CONFIG_PLUGIN_CONFIG`, `OVMS_CONFIG_SHAPE` regenerate the OVMS multi-model config.json
- **Defaults:** Buckets `models`, `data`, `config` are created; OVMS assets always upload regardless of runtime type; Triton ONNX assets only upload when `RUNTIME_TYPE=kserve`
- **Dependencies:** Requires MinIO to be healthy before the container starts (compose uses `depends_on` with `service_healthy` condition; Helm Job has `backoffLimit: 3`)

## Gotchas

- The build context is `app` (not `app/data-image`), as specified in the Makefile's `build-data` target (`-f app/data-image/Dockerfile app`), because the Dockerfile needs access to `app/models/` and `app/data/`
- OVMS model trees are uploaded regardless of `RUNTIME_TYPE` value because a KServe InferenceService may still use OVMS as its backing runtime, as noted in the comment in `upload.sh`: "OVMS assets must reach MinIO whenever the data image includes them"
- The regenerated `config.json` is written to `/tmp/ovms-config.json` (not the baked-in `/upload/models/ovms/config.json`) because OpenShift's random-UID SCC makes the baked-in file read-only
- The `EXPORT_EXCLUDE_STEMS` mechanism in `export_models.py` skips stems like `custome_ppe`, as referenced in the `yolo-model-prep.sh` script's `if [[ $stem == "custome_ppe" ]]` check
- Triton config.pbtxt is only uploaded for the `ppe` model stem specifically, as noted in `upload.sh`: "repo template targets ppe I/O shape only -- do not copy to other stems"

## Related Patterns

- `helm-video-stream-minio-download-ffmpeg-mediamtx-sidecar.md` -- consumes the video files this image uploads to MinIO
- `helm-kserve-runtime-deployer-job-inline-rbac.md` -- deploys the ServingRuntime/InferenceService that serves the models this image uploads
