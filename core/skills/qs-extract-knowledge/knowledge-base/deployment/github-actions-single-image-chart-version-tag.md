---
name: github-actions-single-image-chart-version-tag
description: Single GitHub Actions workflow building one container image with version tag extracted from a nested Chart.yaml
summary: "Automates building and pushing a single container image to Quay.io with version tags extracted from a nested Helm Chart.yaml in a GitHub Actions workflow triggered on main push or workflow_dispatch. Use for single-image quickstarts with one Containerfile where the version lives in a subchart (deploy/helm/rag/Chart.yaml); prefer github-actions-multi-image-release-pipeline for projects needing multiple images, five-workflow CI, or Buildx registry caching. Version extraction uses `grep '^version:' deploy/helm/rag/Chart.yaml | awk '{print $2}'` passed via $GITHUB_OUTPUT with a repository guard (`if: github.repository == 'rh-ai-quickstart/...'`) preventing fork pushes to the upstream registry -- requires QUAY_USERNAME and QUAY_PASSWORD secrets. The `grep '^version:'` pattern assumes version is a top-level YAML key (not indented), LLAMASTACK_VERSION build arg is hardcoded at 0.6.0 independent of chart version requiring dual updates in pyproject.toml and the workflow file, and no Buildx cache-from/cache-to is configured unlike the multi-image pattern."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, streamlit, python]
  ai_pattern: [rag]
  platform: [openshift]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "Single workflow, one Containerfile, version from deploy/helm/rag/Chart.yaml, dual tags (version + latest)"
    approach: "A"
---

# GitHub Actions Single Image with Chart.yaml Version Tag

## Overview

This pattern uses a single GitHub Actions workflow to build and push one container image, extracting the version tag from a Helm `Chart.yaml` located in a nested deploy directory. The image is tagged with both the extracted version and `latest`, and a build argument injects the LlamaStack SDK version at build time.

## Pattern Description

The `build-and-push.yaml` workflow triggers on pushes to `main` and manual dispatch. It extracts the version from `deploy/helm/rag/Chart.yaml` (not the root), builds a single container image from `frontend/Containerfile`, and pushes with dual tags to Quay.io. The workflow is guarded by a repository check (`if: github.repository == 'rh-ai-quickstart/f5-ai-guardrails'`) to prevent forks from pushing to the upstream registry.

## Implementation

### Workflow File

```yaml
# .github/workflows/build-and-push.yaml
name: Build and push image

on:
  push:
    branches:
      - 'main'
  workflow_dispatch:

jobs:
  build-and-push:
    if: github.repository == 'rh-ai-quickstart/f5-ai-guardrails'
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to Quay.io
        uses: docker/login-action@v3
        with:
          registry: quay.io
          username: ${{ secrets.QUAY_USERNAME }}
          password: ${{ secrets.QUAY_PASSWORD }}

      - name: Extract version from Chart.yaml
        id: version
        run: |
          f5_version=$(grep '^version:' deploy/helm/rag/Chart.yaml | awk '{print $2}')
          echo "f5_tag=$f5_version" >> $GITHUB_OUTPUT

      - name: Build and push f5-ai-guardrails
        uses: docker/build-push-action@v5
        with:
          context: frontend
          file: frontend/Containerfile
          push: true
          tags: |
            quay.io/rh-ai-quickstart/f5-ai-guardrails:${{ steps.version.outputs.f5_tag }}
            quay.io/rh-ai-quickstart/f5-ai-guardrails:latest
          build-args: |
            LLAMASTACK_VERSION=0.6.0
```

## Configuration

- **Key settings:** Version source is `deploy/helm/rag/Chart.yaml` (nested path, not root); build context is `frontend/` with `frontend/Containerfile`; registry is `quay.io`
- **Defaults:** Triggers on main branch push and manual dispatch; `LLAMASTACK_VERSION=0.6.0` is hardcoded in the workflow (not extracted from Chart.yaml)
- **Dependencies:** Requires `QUAY_USERNAME` and `QUAY_PASSWORD` secrets configured in the GitHub repository

## Gotchas

- The version is extracted from `deploy/helm/rag/Chart.yaml` (the RAG subchart), not from a root `Chart.yaml` -- the grep command uses `grep '^version:'` which assumes the version field is at the top level of the YAML (not indented under another key)
- The `LLAMASTACK_VERSION` build arg is hardcoded to `0.6.0` in the workflow, independent of the chart version -- updating the LlamaStack SDK requires changing both `pyproject.toml` and the workflow file
- No Buildx cache configuration is used (no `cache-from`/`cache-to`), unlike the multi-image pipeline pattern which uses registry-based caching for the main app image
- The repository guard (`if: github.repository == 'rh-ai-quickstart/f5-ai-guardrails'`) prevents fork builds from attempting to push to the upstream Quay.io registry

## Related Patterns

- `container-build-python-slim-pip-uv-version-sed.md` -- the Containerfile this workflow builds
- `github-actions-multi-image-release-pipeline.md` -- more complex CI with five workflows and multi-image builds
