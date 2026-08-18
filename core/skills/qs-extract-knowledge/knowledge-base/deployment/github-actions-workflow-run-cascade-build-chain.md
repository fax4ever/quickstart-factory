---
name: github-actions-workflow-run-cascade-build-chain
description: Per-image GitHub Actions workflows with workflow_run dependency chaining for build order enforcement
summary: "Enforces container image build order in multi-component repos where downstream Containerfiles use upstream images as FROM base layers, using separate GitHub Actions workflow files per image with workflow_run event triggers to cascade rebuilds when upstream images change. Use when a monorepo has multiple container images with base-layer dependencies between them -- independent sibling workflows need only path filters without cascading; downstream workflows combine path-based push triggers with workflow_run completion events gated on github.event.workflow_run.conclusion == \"success\". All workflows push to quay.io with dual tags (git short SHA + latest), pass IMAGE_TAG as build-arg, require QUAY_USERNAME/QUAY_PASSWORD secrets, and include a github.repository gate in job if conditions. Upstream build failure blocks all downstream rebuilds due to the success conclusion check; backend workflow must use repo root context when its Containerfile copies from multiple directories; tester workflow self-triggers by including its own .yml path in filters; workflows pin actions/checkout@v3 while docker/setup-buildx-action versions vary (v2 vs v3)."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, nodejs]
  ai_pattern: [recommendation]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "4 separate build workflows with path filters; backend triggers on workflow_run completion of recommendation-core build"
    approach: "A"
---

# Per-Image Workflows with workflow_run Cascade Build Chain

## Overview

Separate GitHub Actions workflow files per container image use `workflow_run` event triggers to create a build dependency chain, ensuring that downstream images that depend on upstream images as base layers are rebuilt when the upstream image changes.

## Pattern Description

Each component has its own workflow file with path-based triggers on push to `main`. When a component's image serves as the `FROM` base for another component's Containerfile, the downstream workflow adds a `workflow_run` trigger that fires when the upstream workflow completes. This ensures the downstream image is rebuilt with the latest base even if its own source files did not change.

## Implementation

### Upstream Workflow (recommendation-core)

The recommendation-core workflow triggers only on changes to `recommendation-core/**`:

```yaml
# .github/workflows/build-recommendation-core.yml
name: Build and push recommendation-core image
on:
  push:
    branches: [main]
    paths:
      - 'recommendation-core/**'
jobs:
  build-recommendation-core-image:
    runs-on: ubuntu-latest
    if: >
      (github.repository == 'rh-ai-quickstart/product-recommender-system') &&
      (github.event_name == 'push')
    steps:
      - uses: actions/checkout@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: quay.io
          username: ${{ secrets.QUAY_USERNAME }}
          password: ${{ secrets.QUAY_PASSWORD }}
      - id: version
        run: echo "tag=$(git rev-parse --short HEAD)" >> $GITHUB_OUTPUT
      - uses: docker/build-push-action@v5
        with:
          context: recommendation-core
          file: recommendation-core/Containerfile
          push: true
          tags: |
            quay.io/rh-ai-quickstart/recommendation-core:${{ steps.version.outputs.tag }}
            quay.io/rh-ai-quickstart/recommendation-core:latest
```

### Downstream Workflow with workflow_run Chain

The backend/frontend workflow triggers on BOTH path changes AND completion of the upstream recommendation-core workflow:

```yaml
# .github/workflows/build-and-push.yml
name: Build and push backend/frontend image
on:
  push:
    branches: [main]
    paths:
      - 'backend/**'
      - 'frontend/**'
  workflow_run:
    workflows: ["Build and push recommendation-core image"]
    types: [completed]
    branches: [main]
jobs:
  build-backend-image:
    runs-on: ubuntu-latest
    if: >
      (github.repository == 'rh-ai-quickstart/product-recommender-system') &&
      ((github.event_name == 'push') ||
      (github.event_name == 'workflow_run' && github.event.workflow_run.conclusion == 'success'))
```

### Independent Sibling Workflows

Other workflows (recommendation-training, tester) trigger independently on their own paths without cascading:

```yaml
# .github/workflows/build-recommendation-training.yml
on:
  push:
    branches: [main]
    paths:
      - 'recommendation-training/**'

# .github/workflows/build-tester-image.yml
on:
  push:
    branches: [main]
    paths:
      - 'tests/**'
      - 'tester/**'
      - 'helm/**'
      - '.github/workflows/build-tester-image.yml'
```

## Configuration

- **Key settings:** All workflows use `quay.io/rh-ai-quickstart/` registry, tag images with both `git rev-parse --short HEAD` and `latest`
- **Defaults:** All workflows pass `IMAGE_TAG` as a build-arg for potential in-image version tracking
- **Dependencies:** `QUAY_USERNAME` and `QUAY_PASSWORD` repository secrets for Quay.io authentication

## Gotchas

- The `workflow_run` condition checks `github.event.workflow_run.conclusion == 'success'` -- if the upstream build fails, the downstream build is skipped, which is correct behavior but means a broken recommendation-core blocks all downstream rebuilds.
- The backend workflow uses `context: .` (repo root) rather than `context: backend` because the root Containerfile copies from multiple directories (`backend/`, `frontend/`, `recommendation-core/`).
- The tester workflow includes `'.github/workflows/build-tester-image.yml'` in its own path filter for self-triggering on workflow changes.
- All workflows use `actions/checkout@v3` (not v4), and `docker/setup-buildx-action` versions vary between workflows (v2 vs v3).

## Related Patterns

- `container-build-ubi-node-custom-base-hf-clip-prebake.md` — the downstream Containerfile that depends on recommendation-core as its base
