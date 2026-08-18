---
name: github-actions-reusable-workflow-per-image-path-trigger
description: Per-component GitHub Actions workflows calling a shared reusable build-and-push workflow with path-filtered triggers
summary: "Builds multiple container images from a monorepo using per-image GitHub Actions caller workflows with path-filtered triggers (Approach A: 6 separate files, separate Quay repos) or a single dynamic jq-matrix caller with dorny/paths-filter v3 (Approach B: shared Quay repo with per-service tags via service_tag input, fail-fast: false), both invoking a shared reusable-docker-build.yml via workflow_call that runs Docker Buildx on linux/amd64, logs into Quay.io via explicitly-passed QUAY_USERNAME/QUAY_PASSWORD secrets, generates triple tags (latest/SHA/PR) with docker/metadata-action v5, and pushes only on non-PR events using GHA cache mode=max. Choose Approach A when each image needs independent trigger control, self-triggering on workflow file changes, and separate Quay repos per image; choose Approach B when images share one Quay repo with per-service tags and workflow_dispatch should build all services rather than one, with has_services output preventing empty matrix errors. The reusable workflow accepts inputs for image_name, context, dockerfile, and optional use_lfs boolean for Git LFS checkout; supporting workflows cover pytest with PostgreSQL 16-alpine service container using astral-sh/setup-uv and hashFiles-keyed venv cache, pre-commit lint requiring Go 1.22 for yamlfmt, workflow_dispatch autofix PR creation, DareFox/delete-cache-by-key for stale cache cleanup on uv.lock changes, and Helm lint + compose config validation (Approach B only). Each Approach A caller must include its own .yml path in the paths filter for self-triggering rebuilds, the data image uniquely sets context to ./app (not ./app/data-image) because its Dockerfile copies from sibling directories like app/models/ and app/data/, test workflow has PR triggers commented out, and pre-commit-autofix runs only via workflow_dispatch creating a PR rather than blocking merges."
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
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Single caller workflow with dorny/paths-filter change detection and dynamic jq-built matrix, calling the same reusable-docker-build.yml; shared image repo with per-service tags, workflow_dispatch builds all"
    approach: "B"
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

---

## Approach B: Dynamic jq Matrix Caller with Reusable Build (from portfolio-manager-agent)

### When to Use

When all images share a single container registry repository with per-service tags and you want a single caller workflow rather than one per image. The dynamic matrix avoids spawning build jobs for unchanged services.

### Differences from Approach A

- Single caller workflow (`build-images.yml`) instead of 6 separate per-image workflow files
- Matrix is dynamically constructed via `jq` based on `dorny/paths-filter@v3` outputs, so unchanged services produce no matrix entries (no job spawned at all)
- All images share one Quay repo (`ikatav/portfolio-manager-agent`) differentiated by per-service tags (`ui`, `orchestrator`, `risk`, `portfolio`, `guidelines`) instead of separate repos per image
- `workflow_dispatch` builds ALL services (hardcoded full matrix), not just changed ones
- No `use_lfs` input, no stale cache cleanup workflow, no PostgreSQL test service container
- Supporting workflows include helm lint + compose config validation, frontend npm test, backend pytest, pre-commit lint, and pre-commit autofix PR creation

### Implementation

#### Dynamic Matrix Construction

The `build-matrix` job takes path-filter outputs and dynamically constructs a JSON matrix using jq:

```yaml
# .github/workflows/build-images.yml (build-matrix job)
- name: Build matrix from changed services
  id: set-matrix
  run: |
    services='[]'

    # On workflow_dispatch, build all services
    if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
      services='[
        {"name":"ui","image_name":"ikatav/portfolio-manager-agent","service_tag":"ui","context":"./frontend","dockerfile":"./frontend/Dockerfile"},
        {"name":"orchestrator","image_name":"ikatav/portfolio-manager-agent","service_tag":"orchestrator","context":"./orchestrator/src","dockerfile":"./orchestrator/src/Dockerfile"},
        ...
      ]'
    else
      services='[]'
      if [ "${{ needs.detect-changes.outputs.ui }}" = "true" ]; then
        services=$(echo "$services" | jq -c '. + [{"name":"ui",...}]')
      fi
      ...
    fi

    echo "matrix={\"service\":$services}" >> "$GITHUB_OUTPUT"
    echo "has_services=$has_services" >> "$GITHUB_OUTPUT"
```

#### Reusable Workflow Call with Matrix

The build job uses the dynamically constructed matrix to call the reusable workflow:

```yaml
# .github/workflows/build-images.yml (build job)
build:
  needs: build-matrix
  if: needs.build-matrix.outputs.has_services == 'true'
  strategy:
    fail-fast: false
    matrix: ${{ fromJson(needs.build-matrix.outputs.matrix) }}
  uses: ./.github/workflows/reusable-docker-build.yml
  with:
    image_name: ${{ matrix.service.image_name }}
    service_tag: ${{ matrix.service.service_tag }}
    context: ${{ matrix.service.context }}
    dockerfile: ${{ matrix.service.dockerfile }}
  secrets:
    QUAY_USERNAME: ${{ secrets.QUAY_USERNAME }}
    QUAY_PASSWORD: ${{ secrets.QUAY_PASSWORD }}
```

#### Per-Service Tag in Reusable Workflow

The reusable workflow uses `service_tag` (Approach B addition) for per-service tagging within a shared image repo:

```yaml
# .github/workflows/reusable-docker-build.yml (metadata step)
tags: |
  type=raw,value=${{ inputs.service_tag }},enable={{is_default_branch}}
  type=raw,value=${{ inputs.service_tag }}-{{sha}},enable={{is_default_branch}}
  type=ref,event=pr,prefix=${{ inputs.service_tag }}-pr-
```

#### Deploy Manifest Validation

A separate workflow validates Helm and compose configs without deploying:

```yaml
# .github/workflows/test-deploy.yml
jobs:
  helm:
    steps:
      - run: helm lint deploy/helm
      - run: helm template ci-test deploy/helm
  compose:
    steps:
      - run: podman compose -f deploy/local/compose.yml config
```

### Gotchas

- The `has_services` output prevents the build job from running with an empty matrix, which would cause a GitHub Actions error (see `build-matrix` job)
- The `fail-fast: false` on the matrix strategy ensures one failing service build does not cancel others (see `build` job)
- The per-service tag approach means all images share one Quay repo -- `quay.io/ikatav/portfolio-manager-agent:ui` and `quay.io/ikatav/portfolio-manager-agent:orchestrator` -- unlike Approach A which uses separate repos per image

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Workflow files per image | One per image (6 callers) | One shared caller |
| Matrix construction | No matrix; each file is standalone | Dynamic jq matrix from path-filter outputs |
| Image repository | Separate repo per image | Shared repo with per-service tags |
| Unchanged service builds | Workflow skipped by path filter | Matrix entry not created (no job spawned) |
| workflow_dispatch | Builds one specific image | Builds all images |
| Self-triggering on workflow changes | Yes (workflow path in filters) | No (only source paths filtered) |

## Related Patterns

- `github-actions-path-filtered-matrix-skopeo-retag.md` -- alternative pattern using a single matrix build workflow with skopeo retagging
- `github-actions-multi-image-release-pipeline.md` -- alternative pattern using a multi-job release pipeline
