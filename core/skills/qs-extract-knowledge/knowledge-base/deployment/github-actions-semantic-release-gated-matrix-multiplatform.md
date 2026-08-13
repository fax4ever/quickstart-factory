---
name: github-actions-semantic-release-gated-matrix-multiplatform
description: GitHub Actions pipeline with semantic-release creating tags that gate matrix builds of 3 packages to Quay with multi-platform and TORCH_VARIANT=cuda
summary: "Automates release-gated container image builds for a monorepo (ui, api, db packages) using a two-job GitHub Actions pipeline where semantic-release creates version tags from conventional commits, and a conditional matrix build job runs only when a new tag exists. Use when a monorepo needs automated versioning via conventional commits with per-package multi-platform container images pushed to Quay — semantic-release gates builds so only tagged commits produce images, with fork protection via head.repo.full_name == github.repository. Build job requires context: . (repo root) because packages/<pkg>/Containerfile references sibling directories via COPY, uses Docker Buildx with platforms: linux/amd64,linux/arm64, GHA cache (cache-to: type=gha,mode=max), TORCH_VARIANT=cuda build arg, and a custom TOKEN secret (not GITHUB_TOKEN) so created tags trigger downstream workflows. git describe --tags --abbrev=0 returns the most recent tag even on re-runs (triggering redundant builds when no new release was created), fetch-depth: 0 is required for semantic-release commit analysis, and TORCH_VARIANT=cuda is applied to all matrix packages including non-Python ones like ui (Node-based) wasting build time on irrelevant build args."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [nodejs, python, pytorch]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "semantic-release job creates tags gating matrix builds of ui/api/db to Quay with linux/amd64+arm64 and TORCH_VARIANT=cuda build arg"
    approach: "A"
---

# GitHub Actions: Semantic-Release Gated Matrix Multi-Platform Build

## Overview

This pattern uses a two-job GitHub Actions pipeline where a `semantic-release` job creates version tags (only when commits warrant a release), and a `build-and-push` job conditionally runs only when a new tag is created. The build job uses a matrix strategy to build multiple packages (ui, api, db) as separate container images, with Docker Buildx multi-platform builds (linux/amd64, linux/arm64) and GHA layer caching. Production builds pass `TORCH_VARIANT=cuda` as a build argument.

## Pattern Description

The `semantic-release` job runs first and outputs the new release tag (if any). The `build-and-push` job has an `if` condition gating on a non-empty tag, preventing unnecessary builds on every push. Each matrix entry builds from a package-specific Containerfile in the monorepo root context, pushes both the versioned tag and `latest`, and uses GHA cache for build layer reuse across runs.

## Implementation

### Semantic-Release Job

```yaml
jobs:
  semantic-release:
    if: github.event.pull_request.head.repo.full_name == github.repository || github.event_name != 'pull_request'
    runs-on: ubuntu-latest
    outputs:
      new_release_tag: ${{ steps.get-tag.outputs.tag }}
    steps:
    - uses: actions/checkout@v4
      with:
        token: ${{ secrets.TOKEN }}
        fetch-depth: 0
    - uses: actions/setup-node@v4
      with:
        node-version: '20'
    - run: npm install -g semantic-release @semantic-release/changelog @semantic-release/commit-analyzer @semantic-release/release-notes-generator @semantic-release/github
    - run: semantic-release
      env:
        GITHUB_TOKEN: ${{ secrets.TOKEN }}
    - id: get-tag
      run: |
        TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
        echo "tag=$TAG" >> $GITHUB_OUTPUT
```

Source: `.github/workflows/build-push.yml`

### Conditional Matrix Build

```yaml
  build-and-push:
    needs: semantic-release
    if: needs.semantic-release.outputs.new_release_tag != ''
    runs-on: ubuntu-latest
    strategy:
      matrix:
        package: [ui, api, db]
    steps:
    - uses: actions/checkout@v4
    - uses: docker/setup-buildx-action@v3
    - uses: docker/login-action@v3
      with:
        registry: ${{ env.REGISTRY }}
        username: ${{ secrets.QUAY_USERNAME }}
        password: ${{ secrets.QUAY_PASSWORD }}
    - uses: docker/build-push-action@v5
      with:
        context: .
        file: ./packages/${{ matrix.package }}/Containerfile
        platforms: linux/amd64,linux/arm64
        push: true
        tags: |
          ${{ env.REGISTRY }}/${{ env.REPOSITORY }}/${{ env.PROJECT_NAME }}-${{ matrix.package }}:${{ needs.semantic-release.outputs.new_release_tag }}
          ${{ env.REGISTRY }}/${{ env.REPOSITORY }}/${{ env.PROJECT_NAME }}-${{ matrix.package }}:latest
        cache-from: type=gha
        cache-to: type=gha,mode=max
        build-args: |
          TORCH_VARIANT=cuda
```

Source: `.github/workflows/build-push.yml`

## Configuration

- **Trigger:** Push to `main` or PRs targeting `main`
- **Registry:** `quay.io/rh-ai-quickstart`
- **Image naming:** `spending-monitor-<package>` (e.g., `spending-monitor-ui`, `spending-monitor-api`, `spending-monitor-db`)
- **Platforms:** `linux/amd64,linux/arm64`
- **Build args:** `TORCH_VARIANT=cuda` for GPU-enabled PyTorch in production images
- **Tags:** Semantic version tag + `latest` floating tag
- **Secrets:** `TOKEN` (GitHub PAT for semantic-release), `QUAY_USERNAME`, `QUAY_PASSWORD`
- **Fork protection:** `semantic-release` job skips forked PRs via `head.repo.full_name == github.repository`

## Gotchas

- `git describe --tags --abbrev=0` returns the most recent tag; if semantic-release did not create a new tag, this returns the previous tag -- but the `if` condition on the build job relies on it being non-empty, meaning builds trigger even for pre-existing tags on re-runs
- `fetch-depth: 0` is required for semantic-release to analyze the full commit history for conventional commits
- `TORCH_VARIANT=cuda` is hardcoded for all packages in CI, including `ui` and `db` where PyTorch may not be relevant; the Containerfile's conditional handles this gracefully but wastes build time on non-Python packages (ui uses Node)
- The `context: .` (repo root) is required because Containerfiles use `COPY packages/api/` paths that reference sibling directories
- Uses a custom `TOKEN` secret (not `GITHUB_TOKEN`) for semantic-release to ensure created tags trigger subsequent workflows

## Related Patterns

- `github-actions-multi-image-release-pipeline.md` - Multi-workflow release pipeline
- `github-actions-path-filtered-matrix-skopeo-retag.md` - Path-filtered matrix builds
