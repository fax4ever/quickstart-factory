---
name: container-build-python-slim-ocr-pdf-ingestion
description: python:3.12-slim Containerfile with tesseract, poppler, and OpenCV system deps for document ingestion
summary: "Builds a python:3.12-slim document ingestion container (ingestion-service/Containerfile) that installs heavy system-level dependencies for OCR (tesseract-ocr, tesseract-ocr-eng), PDF extraction (poppler-utils), and OpenCV runtime libs (libgl1, libglib2.0-0, libsm6, libxext6, libxrender-dev) plus libgomp1 for numpy/scipy parallelism. Use when building RAG or data-pipeline ingestion services that must extract text from scanned documents, PDFs, or images -- unlike frontend containers that minimize system packages, this pattern adds the full document-processing toolchain; only one approach (pip-based, root, run-once). Critical config: INGESTION_CONFIG=/config/ingestion-config.yaml points to a mounted YAML for runtime settings, PYTHONUNBUFFERED=1 ensures immediate log output, and CMD [\"python\", \"ingest.py\"] (not ENTRYPOINT) allows runtime command override for debugging; container runs as a one-shot job (compose restart: \"no\"). Gotchas: two separate apt-get update/install layers with git installed redundantly in both inflates the image; no non-root USER directive means the container will fail on OpenShift clusters with restricted SCCs enforcing non-root; the run-once design means it exits after ingestion completes."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python]
  ai_pattern: [rag, data-pipeline, embeddings]
  platform: []
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Ingestion service Containerfile with tesseract-ocr, poppler-utils, libgl1/glib/sm/xext/xrender for OpenCV, and gomp1 for numpy; runs as root with config mounted read-only"
    approach: "A"
---

# Python Slim Container with OCR/PDF System Dependencies for Document Ingestion

## Overview

This pattern builds a document ingestion service container from `python:3.12-slim` that includes heavy system-level dependencies for OCR (Tesseract), PDF processing (Poppler), and image handling (OpenCV runtime libs). Unlike frontend containers that minimize system packages, ingestion containers need these libraries to extract text from diverse document formats.

## Pattern Description

The `ingestion-service/Containerfile` installs system packages in two `apt-get` layers: one for basic tools (git, curl) and one for document processing libraries (tesseract-ocr, poppler-utils, and OpenCV runtime dependencies). Python dependencies are installed via `pip` from `requirements.txt`. The container reads its configuration from a mounted YAML file and runs as root (no non-root user setup).

## Implementation

### Containerfile with Document Processing Dependencies

```dockerfile
# ingestion-service/Containerfile
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && \
    apt-get install -y \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY ingest.py .
RUN chmod +x ingest.py

RUN mkdir -p /config

ENV PYTHONUNBUFFERED=1
ENV INGESTION_CONFIG=/config/ingestion-config.yaml

CMD ["python", "ingest.py"]
```

### System Package Purposes

The installed system packages serve specific document processing roles:

| Package | Purpose |
|---------|---------|
| `tesseract-ocr` | OCR engine for extracting text from scanned documents |
| `tesseract-ocr-eng` | English language data for Tesseract |
| `poppler-utils` | PDF rendering utilities (pdftotext, pdfimages) |
| `libgl1` | OpenGL runtime for OpenCV image processing |
| `libglib2.0-0` | GLib runtime for OpenCV |
| `libsm6`, `libxext6`, `libxrender-dev` | X11 runtime libs required by OpenCV |
| `libgomp1` | GNU OpenMP for numpy/scipy parallel operations |

### Runtime Configuration via Mounted Config

The container reads ingestion configuration from a mounted YAML file rather than environment variables:

```yaml
# deploy/local/ingestion-config.yaml (mounted at /config/ingestion-config.yaml)
# Ingestion configuration for the RAG pipeline
# Defines document sources, embedding models, and vector store targets
```

## Configuration

- **Key settings:** `INGESTION_CONFIG` env var points to the config file path (default `/config/ingestion-config.yaml`); `PYTHONUNBUFFERED=1` ensures log output is immediate
- **Defaults:** Runs as root (no UID/GID restrictions); config file must be mounted at `/config/ingestion-config.yaml`
- **Dependencies:** Requires `requirements.txt` in `ingestion-service/` with document processing Python libraries

## Gotchas

- The Containerfile has two separate `apt-get update` and `apt-get install` layers (lines 4-6 and 13-23), with `git` installed redundantly in both; this increases the image size due to duplicate layers
- No non-root user is configured (`chown`/`chmod`/`USER` directives are absent), so the container runs as root -- suitable for local dev and batch jobs but may fail in OpenShift clusters with restricted SCCs that enforce non-root
- The `CMD` directive (not `ENTRYPOINT`) means the command can be overridden at runtime, useful for debugging (`docker run ... /bin/bash`)
- The ingestion service is designed to run once and exit (compose uses `restart: "no"`), not as a long-running service

## Related Patterns

- `compose-local-dev-host-ollama-ingestion-build.md` -- the compose file that builds and runs this container
- `container-build-python-slim-pip-uv-version-sed.md` -- the frontend Containerfile for the same repo (uses uv instead of pip, includes non-root user)
