---
name: data-loader
description: "Init container that exports YOLO .pt weights to OpenVINO IR and ONNX, then uploads models and videos to MinIO"
summary: "Init container that converts YOLO .pt weights to dual formats — OpenVINO IR (ovms/<stem>/1/<stem>.xml) and ONNX (triton/<stem>/1/model.onnx) — via a 3-stage Dockerfile (Alpine+p7zip extraction, ultralytics+CLIP export, minio/mc upload), then uploads models and sample videos to MinIO before model-serving components start. Use as a Kubernetes Job (backoffLimit: 3) or Compose service_completed_successfully dependency when deploying OVMS or KServe/Triton serving; RUNTIME_TYPE env var (kserve|openvino) controls ONNX upload but OVMS assets always upload since KServe-backed OVMS still needs them; EXPORT_EXCLUDE_STEMS skips specific .pt stems; Helm values at data.image.* and modelServing.runtimeType drive configuration. Auto-generates OVMS config.json with per-model tuning via OVMS_CONFIG_* env vars (NIREQ, PLUGIN_CONFIG, TARGET_DEVICE, BATCH_SIZE, SHAPE, mount base /mnt/models); idempotent uploads use mc stat checks before copying; Triton config.pbtxt targets only the ppe model with GPU/TensorRT FP16 optimization. Build context must be app/ not app/data-image/ since Dockerfile copies sibling dirs; random-UID SCC on OpenShift makes /upload/ read-only requiring config.json regeneration to /tmp; large videos use 7z split files needing Git LFS (use_lfs: true in CI); Compose uses a separate yolo-model-prep service for runtime export instead of baking into the image."
metadata:
  type: component
tags:
  tech_stack: [minio, ultralytics, openvino, onnx, triton, podman, python, shell]
  ai_pattern: [model-serving, data-pipeline, multimodal]
  platform: [rhoai, openshift, kserve, ovms]
  data_layer: [minio]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Multi-stage init image that exports YOLO weights to OpenVINO IR + ONNX, then uploads models and sample videos to MinIO via mc CLI"
    approach: "A"
---

# Data Loader

## Overview

An init-style container image that prepares ML model artifacts and sample data for a quickstart deployment. It converts YOLO `.pt` weight files to OpenVINO IR and ONNX formats in a multi-stage Docker build, then at runtime uploads the exported models and video files to MinIO. It runs as a Kubernetes Job (or a `service_completed_successfully` dependency in Compose) so that model-serving and backend components have their data available before they start.

## Tech Stack & Dependencies

- **Runtime:** Alpine (extraction stage), `ultralytics/ultralytics` (export stage), `minio/mc` (upload stage)
- **Container image:** `ppe-compliance-monitor-data` (multi-stage Dockerfile at `app/data-image/Dockerfile`)
- **Key dependencies:** `p7zip` (archive extraction), `ultralytics` YOLO CLI (`yolo export`), OpenAI CLIP (pip-installed at build), MinIO `mc` CLI (final stage base image)
- **Helm subchart:** None -- deployed as a standalone Kubernetes Job via `deploy/helm/ppe-compliance-monitor/templates/init-data.yaml`

## Key Patterns

### Multi-Stage Model Export Build

The Dockerfile uses three stages to separate concerns: extract compressed data, export weights, and package the uploader. This keeps the final image small (only `mc` CLI + artifacts) while running heavy ML export tooling only at build time.

```dockerfile
# Stage 1: Extract compressed archives + stage raw .pt weights
FROM docker.io/library/alpine@sha256:... AS extractor
RUN apk add --no-cache p7zip
COPY data/combined-video-no-gap-rooftop.mp4.7z.* ./data/
RUN cd data && 7z x combined-video-no-gap-rooftop.mp4.7z.001

# Stage 2: Export each *.pt to OpenVINO IR + ONNX
FROM docker.io/ultralytics/ultralytics@sha256:... AS exporter
COPY --from=extractor /extract/models /weights
RUN pip install --no-cache-dir git+https://github.com/openai/CLIP.git && \
    python3 /tmp/export_models.py

# Stage 3: Create uploader image with mc CLI
FROM docker.io/minio/mc@sha256:...
COPY --from=exporter /exported-openvino/ /upload/models/
COPY --from=exporter /exported-onnx/ /upload/models/
```

Source: `app/data-image/Dockerfile`

### Dual-Format Model Export (OpenVINO IR + ONNX)

The `export_models.py` script iterates over all `.pt` files and exports each to both OpenVINO IR (for OVMS) and ONNX (for Triton), laying them out in the directory structures each serving runtime expects.

```python
WEIGHTS_DIR = os.environ.get("WEIGHTS_DIR", "/weights")
EXCLUDE_STEMS = frozenset(
    s.strip()
    for s in os.environ.get("EXPORT_EXCLUDE_STEMS", "custome_ppe").split(",")
    if s.strip()
)

# OpenVINO layout: ovms/<stem>/1/<stem>.xml + .bin
d_ov = os.path.join(OUT_OPENVINO, "ovms", stem, "1")
subprocess.run(["yolo", "export", f"model={tmp_pt}",
                "format=openvino", "task=detect", "dynamic=True"], check=True)

# Triton layout: triton/<stem>/1/model.onnx
d_onx = os.path.join(OUT_ONNX, "triton", stem, "1")
subprocess.run(["yolo", "export", f"model={tmp_pt}",
                "format=onnx", "task=detect", "dynamic=True"], check=True)
```

Source: `app/data-image/export_models.py`

### Auto-Generated OVMS Multi-Model config.json

After exporting, the script generates an OVMS `config.json` that registers every exported OpenVINO model. Per-model tuning (nireq, plugin_config, target_device, batch_size, shape) is driven entirely by environment variables.

```python
def write_ovms_config_json(root, mount_base=OVMS_MOUNT_BASE):
    for name in sorted(os.listdir(ovms_dir)):
        xml = os.path.join(path, "1", f"{name}.xml")
        if os.path.isfile(xml):
            model_cfg = {
                "name": name,
                "base_path": f"{mount_base.rstrip('/')}/{name}",
            }
            model_cfg.update(_ovms_per_model_extras())
            entries.append({"config": model_cfg})
    cfg = {"model_config_list": entries}
```

Source: `app/data-image/export_models.py` (function `write_ovms_config_json`)

### Idempotent MinIO Upload

The upload script checks whether each artifact already exists in MinIO before uploading, making the Job safe to re-run (backoffLimit: 3 in the Helm Job spec). It waits for MinIO readiness in a retry loop.

```sh
until mc alias set myminio "${MINIO_ENDPOINT}" \
      "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" 2>/dev/null; do
    sleep 2
done

# Per-model idempotent check
if ! mc stat "myminio/models/ovms/${base}/1/${base}.xml" >/dev/null 2>&1; then
    mc cp --recursive "$d" "myminio/models/ovms/${base}/"
else
    echo "OpenVINO ovms/${base} already present, skipping"
fi
```

Source: `app/data-image/upload.sh`

### Runtime-Aware Upload Logic

The upload script uses `RUNTIME_TYPE` to decide which model format directories to upload -- OVMS models are always uploaded (regardless of runtime type, since an OVMS InferenceService still needs them), while Triton ONNX models are only uploaded when `RUNTIME_TYPE=kserve`.

```sh
# OVMS assets always uploaded (not gated on RUNTIME_TYPE)
if [ -d /upload/models/ovms ]; then
    # ... upload OpenVINO models ...
fi

if [ "$RUNTIME_TYPE" = "kserve" ]; then
    # Upload Triton ONNX models
elif [ "$RUNTIME_TYPE" = "openvino" ]; then
    echo "Skipping Triton ONNX uploads (runtime is OpenVINO)."
else
    echo "ERROR: Unknown RUNTIME_TYPE '${RUNTIME_TYPE}'."
    exit 1
fi
```

Source: `app/data-image/upload.sh`

## Configuration

- **Environment variables:**
  - `MINIO_ENDPOINT` -- MinIO URL (default: `http://minio:9000`)
  - `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` -- MinIO credentials (default: `minioadmin`)
  - `RUNTIME_TYPE` -- `kserve` or `openvino`, controls which model formats are uploaded
  - `EXPORT_EXCLUDE_STEMS` -- Comma-separated list of `.pt` stems to skip during export (default: `custome_ppe`)
  - `OVMS_CONFIG_NIREQ` -- Number of inference requests per model in OVMS config (default: `2`)
  - `OVMS_CONFIG_PLUGIN_CONFIG` -- JSON string for OVMS plugin config (default: `{"PERFORMANCE_HINT": "THROUGHPUT"}`)
  - `OVMS_CONFIG_TARGET_DEVICE` -- OVMS target device (optional)
  - `OVMS_CONFIG_BATCH_SIZE` -- OVMS batch size (optional)
  - `OVMS_CONFIG_SHAPE` -- OVMS shape override, JSON or string (optional)
  - `OVMS_CLUSTER_MOUNT_BASE` -- Model mount path inside OVMS on OpenShift (default: `/mnt/models`)
- **Config files:** `app/data-image/config/config.pbtxt` -- Triton config for the `ppe` model (ONNX runtime, GPU with TensorRT FP16 optimization)
- **Helm values:** `data.image.repository`, `data.image.tag`, `data.image.pullPolicy` in `deploy/helm/ppe-compliance-monitor/values.yaml`; `modelServing.runtimeType` controls which `RUNTIME_TYPE` is passed to the Job; `modelServing.openvino.config.*` values flow into `OVMS_CONFIG_*` env vars

## Known Gotchas

- **Build context must be `app/`, not `app/data-image/`:** The Dockerfile copies from `data/`, `models/`, and `data-image/` which are siblings under `app/`. The Makefile correctly uses `podman build -f app/data-image/Dockerfile app` as the build context. Source: `app/data-image/Dockerfile` header comment.
- **Random-UID SCC breaks baked-in config.json:** On OpenShift, the random-UID SCC makes `/upload/` read-only. The upload script regenerates `config.json` to `/tmp/ovms-config.json` when any `OVMS_CONFIG_*` env var is set, avoiding write permission errors. Source: `app/data-image/upload.sh` comments at lines 25-27.
- **OVMS assets upload regardless of RUNTIME_TYPE:** Even when `runtimeType` is `kserve`, OpenVINO model trees are still uploaded because a KServe InferenceService backed by OVMS still expects them under `models/ovms/`. The upload script documents this explicitly. Source: `app/data-image/upload.sh` lines 102-105.
- **Triton config.pbtxt only targets the `ppe` model:** The `config.pbtxt` is specifically shaped for the `ppe` model's I/O and is only uploaded when that model's ONNX exists. It should not be copied to other model stems. Source: `app/data-image/upload.sh` lines 148-151.
- **Large video archives use 7z split files:** The rooftop video is split across four 100 MB `.7z` parts, requiring `p7zip` in the extractor stage. If Git LFS is not configured, the build will fail silently with corrupt archives. The CI workflow sets `use_lfs: true`. Source: `.github/workflows/build-data.yml`.
- **Duplicate `regen_ovms_config` function in upload.sh:** The function is defined twice (lines 29-61 and 68-100), though only the second definition is used at runtime. Source: `app/data-image/upload.sh`.

## Testing Notes

- After the init Job completes, verify MinIO buckets contain the expected artifacts: `mc ls myminio/models/ovms/`, `mc ls myminio/models/triton/`, `mc ls myminio/data/`
- The Job prints a summary of all uploaded files at the end -- check Job logs for "Data upload complete"
- For local testing, the `data-loader` service in `deploy/local/podman-compose.yaml` uses `service_completed_successfully` so dependent services wait for it
- In Compose, a separate `yolo-model-prep` service handles the OpenVINO export at runtime (volume-mounting the source `.pt` files and reusing `export_models.py`) rather than baking exports into the image

## Related Patterns

- `minio.md` -- MinIO object storage used as the model and data backend
- `model-serving.md` -- Model serving patterns (OVMS/KServe) that consume the uploaded artifacts
