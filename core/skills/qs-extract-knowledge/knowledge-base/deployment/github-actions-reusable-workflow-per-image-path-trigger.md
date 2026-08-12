---
name: github-actions-reusable-workflow-per-image-path-trigger
description: Per-component GitHub Actions workflows calling a shared reusable build-and-push workflow with path-filtered triggers
summary: "Builds multiple container images from a monorepo using per-image GitHub Actions caller workflows with path-filtered push/pull_request triggers, each calling a shared reusable-docker-build.yml via workflow_call that runs Docker Buildx on linux/amd64, logs into Quay.io via explicitly-passed QUAY_USERNAME/QUAY_PASSWORD secrets, generates triple tags (latest/SHA/PR) with docker/metadata-action v5, and pushes only on non-PR events using GHA cache mode=max. Use over matrix-based builds (see github-actions-path-filtered-matrix-skopeo-retag.md) when each image needs independent trigger control and workflow clarity; supporting workflows cover pytest with PostgreSQL 16-alpine service container using astral-sh/setup-uv and hashFiles-keyed venv cache, pre-commit lint requiring Go 1.22 for yamlfmt, workflow_dispatch autofix PR creation, and DareFox/delete-cache-by-key for stale cache cleanup on uv.lock changes. The reusable workflow accepts inputs for image_name, context, dockerfile, and optional use_lfs boolean for Git LFS checkout; the data image uniquely sets context to ./app (not ./app/data-image) because its Dockerfile copies from sibling directories like app/models/ and app/data/. Each caller workflow must include its own .yml path in the paths filter for self-triggering rebuilds, the test workflow has PR triggers commented out, and pre-commit-autofix runs only via workflow_dispatch creating a PR rather than blocking merges."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, nodejs]
  ai_pattern: [multimodal]
  platform: [openshift]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "6 per-image caller workflows + 1 reusable workflow + 1 test + 1 lint + 1 pre-commit-autofix + 1 cache cleanup; Quay.io registry with GHA cache"
    approach: "A"
---

# Per-Image Path-Filtered Workflows with Reusable Docker Build

## Overview

Builds multiple container images from a monorepo using one GitHub Actions workflow file per image, each calling a shared reusable workflow (`reusable-docker-build.yml`) via `workflow_call`. Path-filtered triggers on `push` and `pull_request` ensure only changed components rebuild. This pattern avoids matrix-based builds in favor of explicit per-image workflow files for maximum clarity and independent trigger control.

## Pattern Description

The repo contains 6 per-image caller workflows (backend, frontend, data, eval, runtime, jupyter-training), each with path-filtered triggers pointing to its source directory. All call the same reusable workflow that handles Docker Buildx setup, Quay.io login, metadata extraction (tags), and the build-and-push step with GHA layer caching. Supporting workflows handle linting (pre-commit), backend tests (pytest with PostgreSQL service container), pre-commit autofix (creates a PR), and stale venv cache cleanup.

## Implementation

### Reusable Docker Build Workflow

The shared workflow accepts image name, context, dockerfile, and optional LFS checkout:

```yaml
# .github/workflows/reusable-docker-build.yml
on:
  workflow_call:
    inputs:
      image_name:
        required: true
        type: string
      context:
        required: true
        type: string
      dockerfile:
        required: true
        type: string
      use_lfs:
        required: false
        type: boolean
        default: false
    secrets:
      QUAY_USERNAME:
        required: true
      QUAY_PASSWORD:
        required: true
```

The workflow uses `docker/metadata-action` for triple-tagging (latest on default branch, short SHA, PR number):

```yaml
# .github/workflows/reusable-docker-build.yml (metadata step)
- name: Extract metadata (tags, labels)
  uses: docker/metadata-action@v5
  with:
    images: ${{ env.REGISTRY }}/${{ inputs.image_name }}
    tags: |
      type=raw,value=latest,enable={{is_default_branch}}
      type=sha,prefix=,format=short
      type=ref,event=pr
```

Build-and-push uses GHA cache and only pushes on non-PR events:

```yaml
# .github/workflows/reusable-docker-build.yml (build step)
- name: Build and push Docker image
  uses: docker/build-push-action@v5
  with:
    push: ${{ github.event_name != 'pull_request' }}
    cache-from: type=gha
    cache-to: type=gha,mode=max
    platforms: linux/amd64
```

### Per-Image Caller Workflow

Each component has a minimal caller workflow with path-filtered triggers:

```yaml
# .github/workflows/build-backend.yml
on:
  push:
    branches: [main]
    paths:
      - 'app/backend/**'
      - '.github/workflows/build-backend.yml'
  pull_request:
    branches: [main]
    paths:
      - 'app/backend/**'
  workflow_dispatch:

jobs:
  build:
    uses: ./.github/workflows/reusable-docker-build.yml
    with:
      image_name: rh-ai-quickstart/ppe-compliance-monitor-backend
      context: ./app/backend
      dockerfile: ./app/backend/Dockerfile
    secrets:
      QUAY_USERNAME: ${{ secrets.QUAY_USERNAME }}
      QUAY_PASSWORD: ${{ secrets.QUAY_PASSWORD }}
```

### Data Image with Git LFS

The data image workflow enables LFS checkout for large model/video files:

```yaml
# .github/workflows/build-data.yml (excerpt)
jobs:
  build:
    uses: ./.github/workflows/reusable-docker-build.yml
    with:
      image_name: rh-ai-quickstart/ppe-compliance-monitor-data
      context: ./app
      dockerfile: ./app/data-image/Dockerfile
      use_lfs: true
```

### Backend Tests with PostgreSQL Service Container

The test workflow provisions a PostgreSQL service container and uses uv for dependency management:

```yaml
# .github/workflows/test-backend.yml (excerpt)
services:
  postgres:
    image: docker.io/library/postgres:16-alpine
    env:
      POSTGRES_DB: ppe_tracking
      POSTGRES_USER: ppe_user
      POSTGRES_PASSWORD: ppe_password
    ports: ["5432:5432"]
    options: >-
      --health-cmd "pg_isready -U ppe_user -d ppe_tracking"
steps:
  - uses: astral-sh/setup-uv@v4
  - name: Cache venv
    uses: actions/cache@v4
    with:
      path: app/backend/.venv
      key: venv-${{ runner.os }}-py3.11-${{ hashFiles('app/backend/uv.lock') }}
  - run: uv sync --group dev
  - run: uv run python -m pytest tests/ -v
```

### Stale Cache Cleanup

A dedicated workflow deletes old venv caches when `uv.lock` changes:

```yaml
# .github/workflows/cleanup-cache.yml
on:
  push:
    paths: ['app/backend/uv.lock']
jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - uses: DareFox/delete-cache-by-key@v1
        with:
          key: venv-
          mode: startsWith
```

## Configuration

- **Key settings:** `QUAY_USERNAME` and `QUAY_PASSWORD` repository secrets for Quay.io push; `use_lfs: true` for the data image
- **Defaults:** Images push only on non-PR events (`push: ${{ github.event_name != 'pull_request' }}`); platform fixed to `linux/amd64`; GHA cache with `mode=max` for build layers
- **Dependencies:** Docker Buildx for multi-platform build support; Git LFS for large files in the data image

## Gotchas

- Each caller workflow includes its own workflow file in the paths filter (`'.github/workflows/build-backend.yml'`) so workflow changes themselves trigger a rebuild
- The data image context is `./app` (not `./app/data-image`) because the Dockerfile references files from `app/models/` and `app/data/`, matching the Makefile's `build-data` target
- The test workflow is triggered on `push` to main but has PR triggers commented out, suggesting tests were initially run on PRs but disabled
- The `pre-commit-autofix` workflow only runs on `workflow_dispatch` and creates a PR with auto-fixes rather than blocking merges
- The lint workflow installs Go 1.22 and `yamlfmt` in addition to Python for the `yamlfmt` pre-commit hook

## Related Patterns

- `github-actions-path-filtered-matrix-skopeo-retag.md` -- alternative pattern using a single matrix build workflow with skopeo retagging
- `github-actions-multi-image-release-pipeline.md` -- alternative pattern using a multi-job release pipeline
