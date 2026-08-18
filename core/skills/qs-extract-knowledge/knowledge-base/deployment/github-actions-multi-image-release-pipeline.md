---
name: github-actions-multi-image-release-pipeline
description: Five-workflow GitHub Actions pipeline building 4 container images with release PR and Helm chart publishing
summary: "Implements a five-workflow GitHub Actions CI/CD pipeline (ci, build-dev, build-main, create-release-pr, release) that builds four container images (main app + 3 MCP servers) across dev->main->release branch promotion with automated semantic version bumping via workflow_dispatch (patch/minor/major), Helm chart publishing to GitHub Releases, and release branch cleanup after PR close. Use Approach A for separate CI (5 parallel jobs: frontend lint+build, Python flake8/black/isort, Helm chart lint, pre-commit, compose overlay integration tests with coverage artifact upload), per-branch builds, and release management with Helm packaging; use Approach B (single build-and-push workflow delegating to Makefile for 8 images via `make build-all-images`, `make version` extraction, concurrency cancel-in-progress, and multi-tag loop over BASE_VERSION/VERSION_WITH_COMMIT/latest|branch_name) when images share build tooling and no release PR or Helm publishing is needed. Images push to quay.io/rh-ai-quickstart/ via QUAY_USERNAME/QUAY_PASSWORD secrets with `<branch>-<short-sha>` plus floating `latest-<branch>` tags; only the main app image uses Buildx registry caching (`cache-from`/`cache-to: type=registry`); release workflow reads version from Chart.yaml, runs `helm dependency update` then `helm package` to `.helm-releases/`, and attaches the .tgz via `gh release create --latest`. CI test job uses `docker compose -f compose.yaml -f compose.ci.yaml` (not podman) with a GHA-caching overlay; the version bump commit from create-release-pr must be present in the merged PR for release.yml to read the correct Chart.yaml version; MCP server images skip Buildx caching as small single-stage builds; release PR merge conflicts are resolved by preferring the release branch's Chart.yaml/values.yaml/Chart.lock via `git checkout --ours`."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, nodejs, python]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "5 workflows: CI, build-dev, build-main, create-release-pr, release; builds main app + 3 MCP server images"
    approach: "A"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Single build-and-push workflow for 8 images via make build-all-images with Makefile version extraction"
    approach: "B"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "3 release workflows (build-dev, create-release-pr, release) for single UI image; version from Chart.yaml, Buildx registry caching on dev, release creates git tag + Helm package + GitHub Release; no CI or build-main workflows (E2E tests are separate)"
    approach: "A"
---

# GitHub Actions Multi-Image Release Pipeline

## Overview

This pattern implements a five-workflow CI/CD pipeline that handles linting, testing, multi-image container builds, automated version bumping, release PR creation, and GitHub Release publishing with Helm chart artifacts. It manages four separate container images (main application plus three MCP servers) across dev, main, and release branches.

## Pattern Description

The pipeline is split into five workflows following a branch promotion model: `ci.yml` runs on all PRs and pushes, `build-dev.yml` builds images on dev branch pushes, `build-main.yml` builds images on main branch pushes, `create-release-pr.yml` automates version bumps and PR creation via manual trigger, and `release.yml` creates git tags, builds versioned images, packages Helm charts, and publishes GitHub Releases when release PRs are merged.

## Implementation

### CI Workflow (ci.yml)

Runs five parallel jobs on every PR and push to main/dev: frontend lint+build, Python lint (flake8, black, isort), Helm chart lint, pre-commit hooks, and a test job that uses compose with a CI overlay:

```yaml
# .github/workflows/ci.yml (test job excerpt)
- name: Build and start services
  working-directory: deploy/local
  run: docker compose -f compose.yaml -f compose.ci.yaml up -d --wait
  env:
    ENABLE_ATTACHMENTS: false
    LOCAL_DEV_ENV_MODE: true
    ENABLE_COVERAGE: true

- name: Run integration tests
  run: ./tests/run_tests.sh

- name: Upload coverage reports as artifacts
  uses: actions/upload-artifact@v4
  with:
    name: coverage-report
    path: |
      .coverage
      .coverage.unit
      .coverage.integration
      htmlcov/
```

### Dev and Main Branch Builds

Both `build-dev.yml` and `build-main.yml` build and push all four images to Quay.io. Tags use `<branch>-<short-sha>` plus a floating `latest-<branch>` tag. The main app image uses Buildx registry-based caching:

```yaml
# .github/workflows/build-dev.yml (excerpt)
- name: Generate dev tag
  id: tag
  run: |
    short_sha=$(git rev-parse --short HEAD)
    echo "value=dev-${short_sha}" >> $GITHUB_OUTPUT

- name: Build and push ai-virtual-agent
  uses: docker/build-push-action@v5
  with:
    context: .
    file: deploy/cluster/Containerfile
    push: true
    tags: |
      quay.io/rh-ai-quickstart/ai-virtual-agent:${{ steps.tag.outputs.value }}
      quay.io/rh-ai-quickstart/ai-virtual-agent:latest-dev
    cache-from: type=registry,ref=quay.io/rh-ai-quickstart/ai-virtual-agent:buildcache
    cache-to: type=registry,ref=quay.io/rh-ai-quickstart/ai-virtual-agent:buildcache,mode=max
```

### Release PR Workflow (create-release-pr.yml)

Triggered manually via `workflow_dispatch` with a version bump type (patch/minor/major). Reads the current version from main's `Chart.yaml`, calculates the new version, updates Chart.yaml and values.yaml image tag, then creates a PR from a `release/v*` branch targeting main. Handles merge conflicts by preferring the release branch's version files:

```yaml
# .github/workflows/create-release-pr.yml (excerpt)
- name: Get current version
  run: |
    git fetch origin main
    version=$(git show origin/main:deploy/cluster/helm/Chart.yaml | grep '^version:' | awk '{print $2}')

- name: Update Chart version
  run: |
    sed -i "s/^version: .*/version: ${{ steps.new_version.outputs.version }}/" deploy/cluster/helm/Chart.yaml
    sed -i "s/^appVersion: .*/appVersion: \"${{ steps.new_version.outputs.version }}\"/" deploy/cluster/helm/Chart.yaml

- name: Commit version bump
  run: |
    git checkout -b release/v${{ steps.new_version.outputs.version }}
    git merge origin/main --no-edit || {
      git checkout --ours deploy/cluster/helm/Chart.yaml deploy/cluster/helm/values.yaml deploy/cluster/helm/Chart.lock
      git add deploy/cluster/helm/Chart.yaml deploy/cluster/helm/values.yaml deploy/cluster/helm/Chart.lock
      git commit --no-edit
    }
```

### Release Workflow (release.yml)

Triggers on merged PRs from `release/*` branches to main. Creates a git tag, builds all four images with the version tag plus `latest`, packages the Helm chart, and creates a GitHub Release with the chart `.tgz` attached:

```yaml
# .github/workflows/release.yml (excerpt)
- name: Package Helm chart
  run: |
    helm dependency update deploy/cluster/helm/
    helm package deploy/cluster/helm/ -d .helm-releases

- name: Create GitHub Release
  run: |
    gh release create "v${{ steps.version.outputs.value }}" \
      --title "Release v${{ steps.version.outputs.value }}" \
      --latest \
      .helm-releases/*.tgz
```

### Cleanup Branch Job

The release workflow also deletes the `release/v*` branch after the PR is closed (merged or not):

```yaml
# .github/workflows/release.yml (excerpt)
cleanup-branch:
  if: startsWith(github.event.pull_request.head.ref, 'release/')
  steps:
    - name: Delete release branch
      run: git push origin --delete ${{ github.event.pull_request.head.ref }}
```

## Configuration

- **Key settings:** Quay.io credentials stored as `QUAY_USERNAME` and `QUAY_PASSWORD` secrets; four image repositories under `quay.io/rh-ai-quickstart/`
- **Defaults:** CI runs on all PRs and pushes; build workflows trigger only on their respective branch pushes; release workflow triggers only on PR merge from `release/*` to main
- **Dependencies:** Requires Docker Buildx for multi-platform builds; Helm CLI for chart packaging; `gh` CLI for release creation

## Gotchas

- The CI test job uses `docker compose -f compose.yaml -f compose.ci.yaml` (not podman) while local dev uses podman compose. The CI overlay adds GHA build caching (see `compose.ci.yaml`)
- The release workflow reads the version from `Chart.yaml` after merge, so the version bump commit from `create-release-pr` must be present in the merged PR
- MCP server images do not use Buildx caching (`cache-from`/`cache-to`) unlike the main application image, since they are small single-stage builds
- The `create-release-pr` workflow handles merge conflicts by preferring the release branch's versions of `Chart.yaml`, `values.yaml`, and `Chart.lock` using `git checkout --ours` (see `create-release-pr.yml` lines 81-84)

---

## Approach B: Single Build-and-Push Workflow with Makefile Delegation (from it-self-service-agent)

### When to Use

When all images share the same build tooling (shared Containerfile templates) and a Makefile already handles versioning, lockfile validation, and multi-image builds. A single workflow replaces separate per-branch build workflows.

### Differences from Approach A

- Single `build-and-push.yaml` workflow instead of five separate workflows
- Delegates entirely to Makefile (`make build-all-images`, `make push-all-images`) instead of per-image `docker/build-push-action` steps
- Version extracted from Makefile (`make version`) rather than read from Chart.yaml
- Builds 8 images (via shared Containerfile templates) instead of 4
- No Buildx caching -- relies on Makefile build ordering
- No release PR or Helm chart publishing workflows
- Multi-tag loop: iterates over `${BASE_VERSION} ${VERSION_WITH_COMMIT} latest|branch_name`

### Build-and-Push Workflow

```yaml
# .github/workflows/build-and-push.yaml (excerpt)
on:
  push:
    branches: ['main', 'dev']
concurrency:
  group: ${{ github.workflow }}-${{ github.sha }}
  cancel-in-progress: true
jobs:
  build-and-push:
    steps:
      - name: Extract version from Makefile
        run: |
          BASE_VERSION=$(make version)
          VERSION_WITH_COMMIT="${BASE_VERSION}-${{ github.sha }}"
          VERSIONS="${BASE_VERSION} ${VERSION_WITH_COMMIT}"
          if [[ "${BRANCH_NAME}" == "main" ]]; then
            VERSIONS="${VERSIONS} latest"
          else
            VERSIONS="${VERSIONS} ${BRANCH_NAME}"
          fi
      - name: Build all Images
        run: |
          for version in "${VERSIONS[@]}"; do
            VERSION="${version}" make build-all-images
          done
      - name: Push all Images
        run: |
          for version in "${VERSIONS[@]}"; do
            VERSION="${version}" make push-all-images
          done
```

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Workflows | 5 (CI, build-dev, build-main, release-pr, release) | 1 (build-and-push) |
| Image build method | docker/build-push-action per image | make build-all-images (Makefile delegation) |
| Version source | Chart.yaml | Makefile BASE_VERSION |
| Buildx caching | Registry-based for main app | Not used |
| Release management | Automated PR + GitHub Release + Helm package | Not included |
| Image count | 4 | 8 |
| Branch model | dev -> main -> release | dev -> main |

## Related Patterns

- `container-build-ubi-multistage-fullstack.md` -- the Containerfiles built by these workflows (Approach A)
- `compose-ci-overlay-gha-cache-coverage.md` -- the CI compose overlay used in the test job (Approach A)
- `container-build-parameterized-containerfile-template.md` -- the Containerfile templates built by Approach B
- `makefile-git-branch-version-autodetect.md` -- version auto-detection used by Approach B
