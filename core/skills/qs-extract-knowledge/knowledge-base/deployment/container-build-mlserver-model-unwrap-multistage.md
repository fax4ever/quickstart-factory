---
name: container-build-mlserver-model-unwrap-multistage
description: Multistage Dockerfile using MLServer sklearn image to unwrap a wrapped joblib model and prebake it for serving
summary: "Prebakes scikit-learn models into MLServer containers via multistage Dockerfile when models are saved in a custom wrapped joblib format (dict with \"model\", \"saved_at\", \"sklearn_version\", \"type\" keys) that MLServer's joblib.load() cannot consume directly, producing a KServe-ready serving image. Use when a project-specific serialization wraps the raw sklearn Pipeline in a metadata dictionary requiring extraction before serving — the prebaked image also doubles as the initContainer source for a Helm model-upload Job that copies models to MinIO via emptyDir volume, so prefer over runtime unwrapping when both KServe serving and object-storage upload are needed. Builder stage on seldonio/mlserver:1.7.1-sklearn runs a Python unwrap script (positional args: source, destination) to extract the Pipeline into /opt/mlserver/models/<name>/ alongside model-settings.json (implementation: mlserver_sklearn.SKLearnModel, uri: ./<file>.joblib), then the final stage copies only that directory and sets MLSERVER_MODELS_DIR=/opt/mlserver/models. Build context must be the repo root (compose uses context: ../.. with dockerfile: tools/.../Dockerfile) since the Dockerfile copies models from root, builder requires USER 0 to write /opt/mlserver/models/ with temp cleanup in the same RUN layer, and the unwrap script handles both wrapped dict and raw Pipeline formats for idempotency."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python]
  ai_pattern: [model-serving]
  platform: [kserve]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "MLServer sklearn image as builder to unwrap project-format joblib model, then copies to clean MLServer image for KServe serving"
    approach: "A"
---

# MLServer Model Unwrap Multistage Build

## Overview

This pattern prebakes a scikit-learn model into an MLServer container image using a multistage build that transforms a project-specific wrapped model format into the plain format MLServer expects. It solves the problem of models saved in a custom envelope format (with metadata like version and type) that must be unwrapped before MLServer's `joblib.load()` can consume them directly.

## Pattern Description

The builder stage uses the official MLServer sklearn image, copies a wrapped `.joblib` model file and a Python unwrap script, then runs the script to extract the raw sklearn Pipeline and write it to the MLServer models directory alongside a `model-settings.json`. The final stage copies only the unwrapped models directory from the builder, producing a clean image ready for serving. This image serves dual duty: it runs as the MLServer for KServe InferenceService on the cluster, and its model files are extracted by a Job's initContainer for upload to MinIO.

## Implementation

### Multistage Dockerfile

```dockerfile
# tools/guidelines-model/Dockerfile
FROM docker.io/seldonio/mlserver:1.7.1-sklearn AS builder

USER 0
COPY models/investment-guidelines-mlp.joblib /tmp/wrapped-model.joblib
COPY tools/guidelines-model/unwrap_model.py /tmp/unwrap_model.py
COPY tools/guidelines-model/model-settings.json /tmp/model-settings.json

RUN python /tmp/unwrap_model.py \
        /tmp/wrapped-model.joblib \
        /opt/mlserver/models/guidelines-mlp/investment-guidelines-mlp.joblib && \
    cp /tmp/model-settings.json /opt/mlserver/models/guidelines-mlp/model-settings.json && \
    rm -f /tmp/wrapped-model.joblib /tmp/unwrap_model.py /tmp/model-settings.json

FROM docker.io/seldonio/mlserver:1.7.1-sklearn

COPY --from=builder /opt/mlserver/models /opt/mlserver/models

ENV MLSERVER_MODELS_DIR=/opt/mlserver/models
```

### Python Unwrap Script

The unwrap script handles the project's custom model serialization format where models are saved as a dictionary with metadata:

```python
# tools/guidelines-model/unwrap_model.py
"""Extract the plain sklearn Pipeline from the project's wrapped joblib format.

The guidelines agent saves models as::

    {"model": Pipeline(...), "saved_at": "...", "sklearn_version": "...", "type": "..."}

MLServer expects ``joblib.load()`` to return the model directly.
"""

import sys
import os
import joblib

def main():
    src = sys.argv[1]
    dst = sys.argv[2]
    payload = joblib.load(src)
    model = (
        payload["model"]
        if isinstance(payload, dict) and "model" in payload
        else payload
    )
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    joblib.dump(model, dst)
    print(f"Unwrapped model saved to {dst}")

if __name__ == "__main__":
    main()
```

### Model Settings

```json
{
  "name": "guidelines-mlp",
  "implementation": "mlserver_sklearn.SKLearnModel",
  "parameters": {
    "uri": "./investment-guidelines-mlp.joblib"
  }
}
```

## Configuration

- **Key settings:** `MLSERVER_MODELS_DIR=/opt/mlserver/models` tells MLServer where to find the prebaked model; the unwrap script accepts source and destination paths as positional arguments
- **Defaults:** Uses `mlserver:1.7.1-sklearn` as the base image for both builder and runtime stages; model is placed at `/opt/mlserver/models/guidelines-mlp/`
- **Dependencies:** The build context must be the repo root (not `tools/guidelines-model/`) because the Dockerfile copies from `models/` at the repo root; this is reflected in the compose file using `context: ../..` with `dockerfile: tools/guidelines-model/Dockerfile`

## Gotchas

- The Dockerfile build context is the repo root, not the `tools/guidelines-model/` directory, because it needs to `COPY models/investment-guidelines-mlp.joblib` from the repo root -- the compose file reflects this with `context: ../..` and `dockerfile: tools/guidelines-model/Dockerfile` (see `deploy/local/compose.yml` lines 102-104)
- The unwrap script handles both wrapped (dict with `"model"` key) and unwrapped (raw Pipeline) formats, making the build idempotent even if the model format changes (see `tools/guidelines-model/unwrap_model.py`)
- The builder runs as `USER 0` to write to `/opt/mlserver/models/` which is owned by root in the MLServer image; temp files are cleaned up in the same RUN layer to avoid bloating the builder stage (see `tools/guidelines-model/Dockerfile`)
- This prebaked image is also used by the Helm model-upload Job's initContainer, which copies `/opt/mlserver/models/guidelines-mlp/*` to an emptyDir volume for upload to MinIO (see `deploy/helm/templates/job-model-upload.yaml`)

## Related Patterns

- `container-build-tei-model-prebake.md` -- similar model prebake pattern for TEI embedding models
- `helm-model-upload-job-initcontainer-prebaked-minio.md` -- the Job that extracts models from this image for MinIO upload
