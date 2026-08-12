---
name: compose-local-dev-ovms-mediamtx-video-eval-phoenix
description: Local dev compose with YOLO model prep, OVMS multi-model serving, MediaMTX RTSP video streaming, eval profile, and Phoenix tracing
summary: "Provides a 14-service Podman Compose stack for local development of a multimodal compliance monitor combining YOLO object detection via OpenVINO Model Server, RTSP video streaming (MediaMTX + FFmpeg from MinIO-stored video), LangGraph LLM analysis with Arize Phoenix OTEL tracing, PostgreSQL with MCP read-only access, Label Studio annotation, and frontend runtime config injection via window.__ENV__. Use when building a local dev environment needing multi-model OVMS serving with a YOLO export pipeline, live video stream ingestion, profile-gated LLM evaluation (EVAL_FEATURE: chat/alerts, EVAL_DATASET: ppe/bird), and observability -- single approach (A) targets the multimodal-compliance-monitor quickstart. Critical dependency chain: data-loader completes artifact uploads to MinIO first, then yolo-model-prep exports .pt to OpenVINO IR with generated config.json (tuned via OVMS_CONFIG_NIREQ, PLUGIN_CONFIG, SHAPE) into a shared model_repo volume that OVMS reads via service_completed_successfully, while FFmpeg waits for both data-loader and MediaMTX; MediaMTX buffers configured via MTX_WRITEQUEUESIZE and MTX_UDPREADBUFFERSIZE. Shared model_repo volume creates a failure cascade where yolo-model-prep failure blocks OVMS startup, data-loader hardcodes RUNTIME_TYPE: openvino (Helm supports kserve switching), init-eval-db installs psycopg2-binary at runtime via pip in a bare python image rather than a pre-built one, and all 14 services use pinned @sha256: digests with six named volumes (minio_data, postgres_data, labelstudio_data, model_repo, eval_snapshots, phoenix_data) for persistence."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [flask, postgresql, minio, python]
  ai_pattern: [multimodal, model-serving, evaluation]
  platform: [openvino]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "14-service compose: MinIO, PostgreSQL, postgres-mcp, Label Studio, MediaMTX, FFmpeg, data-loader, yolo-model-prep, OVMS, backend, frontend, Phoenix, backend-eval (profile), init-eval-db (profile)"
    approach: "A"
---

# Compose Local Dev with OVMS, MediaMTX Video Stream, Eval Profile, and Phoenix

## Overview

A 14-service Podman Compose stack for local development of a multimodal compliance monitoring application that combines YOLO object detection (via OpenVINO Model Server), RTSP video streaming (via MediaMTX + FFmpeg), LLM-powered analysis (via LangGraph), PostgreSQL with MCP read-only access, Label Studio annotation, Arize Phoenix LLM tracing, and an LLM evaluation framework gated behind a Compose profile.

## Pattern Description

The compose file orchestrates a complex startup dependency chain: MinIO and PostgreSQL start first, then the data-loader uploads model and video artifacts to MinIO, yolo-model-prep exports `.pt` weights to OpenVINO IR format with a generated `config.json`, OVMS starts with the prepared model repository, MediaMTX starts independently while its FFmpeg publisher waits for both the data-loader and MediaMTX, and finally the backend starts after the video stream, MinIO, PostgreSQL, and postgres-mcp are all healthy. The eval services use Compose profiles to avoid starting during normal development.

## Implementation

### Model Preparation Pipeline (yolo-model-prep + OVMS)

The `yolo-model-prep` service exports `.pt` files to OpenVINO IR and generates a multi-model `config.json`, using a shared volume that OVMS reads from:

```yaml
# deploy/local/podman-compose.yaml (excerpt)
yolo-model-prep:
  image: docker.io/ultralytics/ultralytics@sha256:...
  environment:
    OVMS_CONFIG_NIREQ: "8"
    OVMS_CONFIG_PLUGIN_CONFIG: '{"PERFORMANCE_HINT": "THROUGHPUT", "ENABLE_CPU_PINNING": false}'
    OVMS_CONFIG_SHAPE: '{"x":"(-1,3,640,640)"}'
  volumes:
    - ../../app/models:/source:ro,z
    - model_repo:/models:z
    - ./yolo-model-prep.sh:/prep.sh:ro,z
    - ../../app/data-image/export_models.py:/export_models/export_models.py:ro,z
  entrypoint: ["bash", "/prep.sh"]

ovms:
  image: docker.io/openvino/model_server@sha256:...
  depends_on:
    yolo-model-prep:
      condition: service_completed_successfully
  command:
    - --config_path
    - /models/ovms/config.json
    - --port
    - "8081"
    - --rest_port
    - "8080"
  volumes:
    - model_repo:/models:z
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/v2/health/ready"]
```

### Video Streaming (MediaMTX + FFmpeg)

The video stream uses two containers: MediaMTX as the RTSP server and a separate FFmpeg publisher that downloads video from MinIO and loops it:

```yaml
# deploy/local/podman-compose.yaml (excerpt)
video-stream:
  image: docker.io/bluenviron/mediamtx@sha256:...
  environment:
    MTX_WRITEQUEUESIZE: "2048"
    MTX_UDPREADBUFFERSIZE: "4194304"
  ports:
    - "8554:8554"

video-stream-ffmpeg:
  build:
    context: ../../app
    dockerfile: video-stream-image/Dockerfile
  depends_on:
    data-loader:
      condition: service_completed_successfully
    video-stream:
      condition: service_started
    minio:
      condition: service_healthy
```

### Eval Profile (Gated Services)

Evaluation services are hidden behind the `eval` profile to prevent them from starting during normal development:

```yaml
# deploy/local/podman-compose.yaml (excerpt)
backend-eval:
  build:
    context: ../../app/evals
    dockerfile: Containerfile
  environment:
    BACKEND_URL: "http://backend:8888"
    EVAL_FEATURE: "${EVAL_FEATURE:-chat}"
    EVAL_DATASET: "${EVAL_DATASET:-ppe}"
    DEEPEVAL_TELEMETRY_OPT_OUT: "YES"
  profiles:
    - eval

init-eval-db:
  image: docker.io/library/python@sha256:...
  command: sh -c "pip install -q psycopg2-binary && python /evals/init_db.py"
  volumes:
    - ../../app/evals:/evals:z
  profiles:
    - eval
```

### Phoenix LLM Tracing

Arize Phoenix runs as a standalone service, with the backend sending traces via OTEL:

```yaml
# deploy/local/podman-compose.yaml (excerpt)
phoenix:
  image: docker.io/arizephoenix/phoenix@sha256:...
  ports:
    - "6006:6006"
    - "4317:4317"
  environment:
    PHOENIX_WORKING_DIR: /mnt/data
  volumes:
    - phoenix_data:/mnt/data
```

The backend connects via `PHOENIX_COLLECTOR_ENDPOINT: "http://phoenix:4317"`.

### Frontend Runtime Config Injection

The frontend container injects the API URL at startup using a shell command, avoiding rebuild for different environments:

```yaml
# deploy/local/podman-compose.yaml (excerpt)
frontend:
  command:
    - sh
    - -c
    - >
      printf "window.__ENV__ = { API_URL: \"%s\" };\n" "$${FRONTEND_API_URL}" > /app/build/env.js && serve -s /app/build -l tcp://0.0.0.0:3000
  environment:
    FRONTEND_API_URL: "http://localhost:8888/api"
```

## Configuration

- **Key settings:** `RUNTIME_TYPE` in data-loader selects model format; `EVAL_FEATURE` (chat/alerts) and `EVAL_DATASET` (ppe/bird) control evaluation scope; `PHOENIX_COLLECTOR_ENDPOINT` enables LLM tracing
- **Defaults:** OVMS runs on gRPC port 8081 and REST port 8080; MinIO on 9000/9001; PostgreSQL on 5432; backend on 8888; frontend on 3000; Phoenix on 6006/4317
- **Dependencies:** `data-loader` must complete before backend, OVMS, and FFmpeg can use uploaded artifacts; `yolo-model-prep` must complete before OVMS starts

## Gotchas

- All images use pinned `@sha256:` digests for reproducibility, not floating tags
- The `model_repo` volume is shared between `yolo-model-prep` and `ovms` -- if prep fails, OVMS will also fail to start (enforced by `service_completed_successfully` condition)
- The `data-loader` service runs with `RUNTIME_TYPE: openvino` hardcoded in the compose file, while the Helm deploy supports switching to `kserve`
- The `init-eval-db` service installs `psycopg2-binary` at runtime via `pip install -q` because it uses a bare `python` image rather than a pre-built image
- The `video-stream-ffmpeg` depends on `data-loader` with `service_completed_successfully` because the video file must be uploaded to MinIO before FFmpeg can download it
- Six named volumes (`minio_data`, `postgres_data`, `labelstudio_data`, `model_repo`, `eval_snapshots`, `phoenix_data`) persist data across restarts

## Related Patterns

- `compose-profile-layered-optional-services.md` -- similar profile-based gating pattern for optional services
- `container-build-multistage-7z-yolo-export-minio-upload.md` -- the data image used by the `data-loader` service
