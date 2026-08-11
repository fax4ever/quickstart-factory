---
name: github-actions-path-filtered-matrix-skopeo-retag
description: Path-filtered matrix builds on PR merge with skopeo-based image retagging for backend
summary: "Solves selective container image builds in a multi-service monorepo by triggering only changed-service builds on merged PRs, with a separate skopeo-based retagging flow for backend images that developers push independently. Use when services live in subdirectories of one repo (e.g., ui, annotation_interface, clustering, aap-log-collector) and only modified services should rebuild on merge; the backend retag pattern applies when one service is built externally and CI only promotes its branch tag to `latest` instead of rebuilding. Three workflows compose the pipeline: `build-and-push.yml` uses `pull_request_target` (types: [closed]) with `if: github.event.pull_request.merged == true`, `dorny/paths-filter@v2` for change detection, a conditional matrix with `docker/build-push-action@v5` and Containerfiles pushing short-SHA + `latest` tags to Quay.io via `QUAY_USERNAME`/`QUAY_PASSWORD` secrets, and a `tag-backend-latest` job that runs `skopeo inspect` then `skopeo copy`; lint uses `astral-sh/ruff-action@v3` and test uses `uv sync --frozen` + pytest. `pull_request_target` runs base-branch workflow code (required for secret access but means PR workflow changes are not tested until merged); branch names are sanitized via `sed 's/\\//-/g'` for Docker tag compatibility; skopeo retag fails with exit 1 if the developer did not push the branch-tagged backend image before merging."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "3 workflows: path-filtered matrix build, lint, test; backend retagged via skopeo on merge"
    approach: "A"
---

# Path-Filtered Matrix Builds with Skopeo Image Retagging

## Overview

This pattern implements a CI/CD pipeline where container image builds are conditionally triggered based on which service directories changed in a merged PR. A separate job retags the backend image from its branch tag to `latest` using `skopeo copy` rather than rebuilding. Three workflows handle the full pipeline: build-and-push (on PR merge), lint (on PR), and test (on PR).

## Pattern Description

The `build-and-push.yml` workflow triggers on merged PRs to main via `pull_request_target`. A `detect-changes` job uses `dorny/paths-filter` to check which service directories were modified. A matrix build job then conditionally builds and pushes only the changed services. A separate `tag-backend-latest` job handles the backend differently -- since the backend image is built per-branch by developers, it uses `skopeo` to copy the branch-tagged image to `latest` rather than rebuilding.

## Implementation

### Path-Filtered Change Detection

The `detect-changes` job outputs booleans for each service directory:

```yaml
# .github/workflows/build-and-push.yml
on:
  pull_request_target:
    types: [closed]
    branches:
      - main

jobs:
  detect-changes:
    name: Detect changed directories
    runs-on: ubuntu-latest
    if: github.event.pull_request.merged == true
    outputs:
      ui: ${{ steps.filter.outputs.ui }}
      annotation: ${{ steps.filter.outputs.annotation }}
      clustering: ${{ steps.filter.outputs.clustering }}
      collector: ${{ steps.filter.outputs.collector }}
    steps:
      - uses: dorny/paths-filter@v2
        id: filter
        with:
          filters: |
            ui:
              - 'services/ui/**'
            annotation:
              - 'services/annotation_interface/**'
            clustering:
              - 'services/clustering/**'
            collector:
              - 'services/aap-log-collector/**'
```

### Conditional Matrix Build

The matrix defines all four service images, but the build step runs only for changed services:

```yaml
# .github/workflows/build-and-push.yml (build-image job)
strategy:
  matrix:
    include:
      - name: alm-ui
        context: services/ui
        image-name: alm-ui
      - name: alm-annotation-interface
        context: services/annotation_interface
        image-name: alm-annotation-interface
      - name: alm-clustering
        context: services/clustering
        image-name: alm-clustering
      - name: alm-aap-log-collector
        context: services/aap-log-collector
        image-name: alm-aap-log-collector

steps:
  - name: Set version from run number
    id: version
    run: echo "tag=$(git rev-parse --short HEAD)" >> $GITHUB_OUTPUT

  - name: Build and push ${{ matrix.name }}
    if: |
      (matrix.image-name == 'alm-ui' && needs.detect-changes.outputs.ui == 'true') ||
      (matrix.image-name == 'alm-annotation-interface' && needs.detect-changes.outputs.annotation == 'true') ||
      (matrix.image-name == 'alm-clustering' && needs.detect-changes.outputs.clustering == 'true') ||
      (matrix.image-name == 'alm-aap-log-collector' && needs.detect-changes.outputs.collector == 'true')
    uses: docker/build-push-action@v5
    with:
      context: ${{ matrix.context }}
      file: ${{ matrix.context }}/Containerfile
      push: true
      tags: |
        quay.io/rh-ai-quickstart/${{ matrix.image-name }}:${{ steps.version.outputs.tag }}
        quay.io/rh-ai-quickstart/${{ matrix.image-name }}:latest
```

### Backend Retagging via Skopeo

The backend is handled separately because developers push branch-tagged images. On PR merge, skopeo copies the branch tag to `latest`:

```yaml
# .github/workflows/build-and-push.yml (tag-backend-latest job)
tag-backend-latest:
  runs-on: ubuntu-latest
  if: github.event.pull_request.merged == true
  steps:
    - name: Extract source branch
      id: extract-branch
      run: |
        BRANCH_NAME="${{ github.event.pull_request.head.ref }}"
        BRANCH_TAG=$(echo "$BRANCH_NAME" | sed 's/\//-/g')
        echo "branch_tag=$BRANCH_TAG" >> $GITHUB_OUTPUT

    - name: Install skopeo
      run: |
        sudo apt-get update
        sudo apt-get install -y skopeo

    - name: Tag backend image as latest
      env:
        QUAY_USERNAME: ${{ secrets.QUAY_USERNAME }}
        QUAY_PASSWORD: ${{ secrets.QUAY_PASSWORD }}
        BRANCH_TAG: ${{ steps.extract-branch.outputs.branch_tag }}
      run: |
        if skopeo inspect --creds="$QUAY_USERNAME:$QUAY_PASSWORD" \
           docker://quay.io/rh-ai-quickstart/alm-backend:$BRANCH_TAG > /dev/null 2>&1; then
          skopeo copy \
            --src-creds="$QUAY_USERNAME:$QUAY_PASSWORD" \
            --dest-creds="$QUAY_USERNAME:$QUAY_PASSWORD" \
            docker://quay.io/rh-ai-quickstart/alm-backend:$BRANCH_TAG \
            docker://quay.io/rh-ai-quickstart/alm-backend:latest
        else
          echo "Source image not found: alm-backend:$BRANCH_TAG"
          exit 1
        fi
```

### Lint and Test Workflows

Separate workflows handle linting (Ruff) and testing (pytest via uv):

```yaml
# .github/workflows/check-lint-and-format.yml
steps:
  - uses: astral-sh/ruff-action@v3
    with:
      args: 'check'
  - uses: astral-sh/ruff-action@v3
    with:
      args: 'format --check'

# .github/workflows/test.yml
steps:
  - uses: astral-sh/setup-uv@v5
    with:
      version: "0.7.19"
  - run: uv sync --frozen
  - run: uv run pytest tests/ -v
```

## Configuration

- **Key settings:** Quay.io credentials as `QUAY_USERNAME`/`QUAY_PASSWORD` secrets; image tags use short git SHA (`git rev-parse --short HEAD`)
- **Defaults:** Build triggers only on merged PRs to main (`pull_request_target` with `types: [closed]`); all four service images push to `quay.io/rh-ai-quickstart/`
- **Dependencies:** Requires `dorny/paths-filter@v2` for change detection; `docker/build-push-action@v5` for builds; `skopeo` installed via apt for retagging

## Gotchas

- The backend image is NOT built by the CI matrix -- developers push it manually with branch-tagged names, and CI only retags to `latest` via skopeo (see `tag-backend-latest` job)
- The branch name is sanitized by replacing `/` with `-` for use as a Docker tag (`sed 's/\//-/g'`), so `feat/my-branch` becomes `feat-my-branch` (see `extract-branch` step)
- The `build-and-push` workflow uses `pull_request_target` (not `pull_request`), which runs in the context of the base branch -- this is required for access to repository secrets but means the workflow code comes from main, not the PR branch
- If the developer forgets to push the backend image for their branch before merging, the skopeo retag fails with "Source image not found" and exits with code 1 (see workflow lines 122-139)

## Related Patterns

- `container-build-ubi-uv-python-multistage.md` -- the Containerfiles built by this pipeline
- `container-build-tei-model-prebake.md` -- TEI image built separately from this pipeline
