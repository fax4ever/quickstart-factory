---
name: github-actions-reusable-workflow-semver-release-cleanup
description: GitHub Actions pipeline with reusable workflow_call workflows for semantic versioning, 4-image matrix builds, and scheduled image cleanup
summary: "Implements a composable GitHub Actions CI/CD pipeline using 11 workflows — 3 reusable workflow_call (build-images, update-versions, build-operator-images) composed by callers for dev/feature push builds, release preparation with dev-to-main PR, and release tagging with GitHub release creation via gh CLI. Use when a quickstart needs semantic versioning from commit messages (BREAKING CHANGE->major, feat->minor, else patch), parallel multi-image matrix builds (4+ images including operator+bundle+catalog), and scheduled image cleanup — prefer over monolithic workflows when multiple pipelines share build/version-update logic via workflow_call. Critical config: Makefile `VERSION ?=` is the source of truth with `^` anchoring to avoid matching RHOAI_VERSION; sed-based version updates use two-line matching (`/repository:.*<image>/{n;s|tag: .*|...|}`) to target only app image tags in Helm values.yaml without overwriting unrelated tags like oauth-proxy. Main branch pushes must skip version computation (versions already set from dev); create-release retags numeric versions to v-prefixed tags protected from the monthly skopeo cleanup (Quay.io, 30-day retention); build-operator-images needs git stash/pop retry for parallel push conflicts; console-plugin requires pre-build yarn assets before Docker build."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, nodejs, python]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "11 workflows using workflow_call: semantic version from commits, 4-image matrix build, update-versions via sed, operator images, prepare-release, create-release with image retagging, cleanup-old-images via skopeo, deploy/undeploy with safety"
    approach: "A"
---

# GitHub Actions Reusable Workflow Pipeline with Semantic Versioning and Image Cleanup

## Overview

This pattern implements a GitHub Actions CI/CD pipeline using reusable workflows (`workflow_call`) as composable building blocks. The pipeline handles semantic versioning from commit messages, matrix-based multi-image builds, automated version file updates via sed, operator image management, release preparation with dev-to-main PR creation, release tagging with image retagging, and scheduled container image cleanup via skopeo.

## Pattern Description

The pipeline consists of 11 workflows organized as callers and callees. Three reusable workflows (`build-images.yml`, `update-versions.yml`, `build-operator-images.yml`) are consumed by multiple caller workflows (`build-and-push.yml`, `prepare-release.yml`, `create-release.yml`). The `build-and-push.yml` workflow triggers on push to dev/feature branches, computes a semantic version from commit messages, builds 4 container images in parallel via matrix strategy, updates version files, and builds operator images. A scheduled `cleanup-old-images.yml` workflow removes images older than 30 days from Quay.io while protecting release tags (v-prefix) and latest.

## Implementation

### Semantic Versioning from Commit Messages

```yaml
# .github/workflows/build-and-push.yml
- name: Calculate semantic version
  id: version
  run: |
    VERSION=$(grep "^VERSION.*=" Makefile | sed 's/VERSION.*= //' | head -1)
    IFS='.' read -r MAJOR MINOR PATCH <<< "${VERSION%%-*}"

    MAJOR_PATTERN="(BREAKING CHANGE:?|breaking:|\!:|major:)"
    MINOR_PATTERN="(feat:|feature:|add:|minor:)"

    COMMITS=$(git log --pretty=format:"%B" ${{ github.event.before }}..${{ github.event.after }})

    if echo "$COMMITS" | grep -qiE "$MAJOR_PATTERN"; then
      MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0
    elif echo "$COMMITS" | grep -qiE "$MINOR_PATTERN"; then
      MINOR=$((MINOR + 1)); PATCH=0
    else
      PATCH=$((PATCH + 1))
    fi
    NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
    # Add suffix for feature branch
    if [ "${{ github.ref_name }}" = "feature" ]; then
      NEW_VERSION="${NEW_VERSION}-feature"
    fi
    echo "version=$NEW_VERSION" >> $GITHUB_OUTPUT
```

### Reusable Build Images Workflow (workflow_call)

```yaml
# .github/workflows/build-images.yml
name: "Shared: Build Images"
on:
  workflow_call:
    inputs:
      version:
        required: true
        type: string
      org:
        required: true
        type: string
      image_prefix:
        required: true
        type: string
jobs:
  build-image:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - name: metrics-alerting
            context: src
            dockerfile: src/alerting/Dockerfile
          - name: mcp-server
            context: src
            dockerfile: src/mcp_server/Dockerfile
          - name: console-plugin
            context: openshift-plugin
            dockerfile: openshift-plugin/Dockerfile.plugin
            needs_build: true
            build_target: plugin
          - name: react-ui
            context: openshift-plugin
            dockerfile: openshift-plugin/Dockerfile.react-ui
            needs_build: true
            build_target: react-ui
    steps:
      # Pre-build yarn for console-plugin (assets must exist before docker build)
      - name: Build console-plugin assets
        if: ${{ matrix.needs_build == true && matrix.build_target == 'plugin' }}
        run: |
          cd openshift-plugin
          yarn install --frozen-lockfile
          yarn build:plugin
      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          tags: |
            ${{ inputs.registry }}/${{ inputs.org }}/${{ inputs.image_prefix }}-${{ matrix.component }}:${{ inputs.version }}
            ${{ inputs.registry }}/${{ inputs.org }}/${{ inputs.image_prefix }}-${{ matrix.component }}:latest
```

### Reusable Version Update Workflow

Updates version in multiple Helm chart values.yaml files and the Makefile via targeted sed:

```yaml
# .github/workflows/update-versions.yml
# NOTE: Each sed targets ONLY the app image tag by matching the repository line first,
# then substituting the very next 'tag:' line. This prevents overwriting unrelated tags.
- name: Update mcp-server values.yaml
  run: |
    sed -i '/repository:.*aiobs-mcp-server/{n;s|tag: .*|tag: '"${{ inputs.version }}"'|}' \
      deploy/helm/mcp-server/values.yaml

- name: Update Makefile version
  # NOTE: Anchor with ^ to match only the VERSION line
  run: |
    sed -i 's|^VERSION ?= .*|VERSION ?= '"${{ inputs.version }}"'|' Makefile
```

### Scheduled Image Cleanup with Skopeo

```yaml
# .github/workflows/cleanup-old-images.yml
on:
  schedule:
    - cron: '0 0 1 * *'  # 1st of every month
jobs:
  cleanup-images:
    strategy:
      matrix:
        component: [metrics-alerting, mcp-server, console-plugin, react-ui]
    steps:
      - name: Cleanup old tags
        run: |
          for TAG in $TAGS; do
            # Always protect: latest, v-prefix (release tags), user-specified
            if [ "$TAG" = "latest" ] || [[ "$TAG" == v* ]]; then continue; fi
            IMAGE_CREATED=$(skopeo inspect docker://$IMAGE_NAME:$TAG | jq -r '.Created')
            IMAGE_TIME=$(date -d "$IMAGE_CREATED" +%s)
            if [ "$IMAGE_TIME" -lt "$CUTOFF_TIME" ]; then
              skopeo delete docker://$IMAGE_NAME:$TAG
            fi
          done
```

### Pipeline Composition

```
build-and-push.yml (on push to dev/feature)
  ├── semantic-version (compute from commits)
  ├── build-images.yml (workflow_call, 4-image matrix)
  ├── update-versions.yml (workflow_call, sed across files)
  └── build-operator-images.yml (workflow_call, operator+bundle+catalog)

prepare-release.yml (workflow_dispatch)
  ├── compute-next-version (bump_type or custom)
  ├── update-versions.yml (workflow_call)
  ├── build-images.yml (workflow_call)
  ├── build-operator-images.yml (workflow_call)
  └── create-pr (dev → main)

create-release.yml (workflow_dispatch)
  ├── get_version (from Makefile)
  ├── verify images exist
  ├── tag images (v-prefix + latest)
  └── gh release create
```

## Configuration

- **Key settings:** `VERSION ?=` in Makefile is the source of truth for current version; semantic versioning priority: PR labels > PR title > commit messages; cleanup retains images for 30 days by default
- **Defaults:** Main branch pushes skip version computation and image builds (versions already set from dev); feature branch adds `-feature` suffix to version
- **Dependencies:** Quay.io credentials via `QUAY_USERNAME`/`QUAY_PASSWORD` secrets; `skopeo` for image cleanup; `gh` CLI for release creation

## Gotchas

- The `update-versions.yml` sed command uses a two-line match (`/repository:.*aiobs-mcp-server/{n;s|tag: .*|...|}`) to avoid overwriting unrelated `tag:` lines in the same values.yaml (e.g., oauth-proxy tags)
- The Makefile VERSION anchor uses `^VERSION ?=` to avoid matching variables like `RHOAI_VERSION` or `OPERATOR_VERSION`
- Main branch pushes are explicitly skipped for version computation and image building (`github.ref_name != 'main'`) because versions are already set by the dev branch workflow
- The `create-release.yml` workflow pulls images by their numeric version tag, then re-tags with `v`-prefix (e.g., `3.2.0` -> `v3.2.0`) -- the v-prefix tags are protected from the cleanup workflow
- The `build-operator-images.yml` workflow includes retry logic with `git stash/pop` for push conflicts when multiple parallel jobs update the same branch

## Related Patterns

- `github-actions-multi-image-release-pipeline.md` -- alternative multi-image pipeline without reusable workflows
- `github-actions-path-filtered-matrix-skopeo-retag.md` -- path-filtered builds with skopeo retagging
