---
name: makefile-git-branch-version-autodetect
description: Makefile auto-detects image version tag from git branch with dev suffix and fork-from-dev detection
summary: "Auto-detects container image version tags from git branches using Makefile ifeq/$(origin VERSION) conditionals and IS_FORKED_FROM_DEV shell variable comparing git merge-base + git rev-list --count distances -- main resolves to BASE_VERSION (e.g., 0.0.14), dev and dev-forked branches to BASE_VERSION-dev, with explicit VERSION=<tag> overrides always honored. Use for Helm-deployed OpenShift quickstarts needing automatic image tag resolution across main/dev/feature branches without manual VERSION setting; CI extends via make version target adding commit-SHA and branch-name tags. Critical pattern: IS_FORKED_FROM_DEV compares merge-base distances to both main and dev, choosing the closer parent; helm_install_common logs whether version was auto-detected or explicitly set to debug tag mismatches. Gotcha: equidistant merge-bases default to stable version (not dev), fork detection requires local git access to both main and dev branches, and CI produces mutable (latest/branch) plus immutable (version-SHA) tags per image."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "VERSION auto-detected from git branch: main=0.0.14, dev=0.0.14-dev, forked-from-dev=0.0.14-dev"
    approach: "A"
---

# Makefile Git Branch Version Auto-Detection

## Overview

This pattern auto-detects the container image version tag from the current git branch. The `main` branch uses the base version (e.g., `0.0.14`), the `dev` branch appends `-dev`, and branches forked from `dev` also use the `-dev` suffix. This ensures developers on feature branches automatically pull the correct pre-built CI images without manually setting VERSION.

## Pattern Description

The Makefile defines `BASE_VERSION` and computes `VERSION` using a series of `ifeq`/`else ifeq` conditionals. A shell function detects whether the current branch was forked from `dev` (vs main) by comparing `git merge-base` distances, so feature branches inherit the correct version suffix. The `VERSION` variable can always be overridden explicitly (e.g., `VERSION=latest make helm-install-test`).

## Implementation

### Version Auto-Detection Logic

```makefile
# Makefile (excerpt)
BASE_VERSION := 0.0.14
DEV_VERSION := $(BASE_VERSION)-dev
GIT_BRANCH := $(shell git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

IS_FORKED_FROM_DEV := $(shell \
  BRANCH="$(GIT_BRANCH)"; \
  if [ -n "$$BRANCH" ] && [ "$$BRANCH" != "main" ] && [ "$$BRANCH" != "dev" ]; then \
    MERGE_BASE_MAIN=$$(git merge-base $$BRANCH main 2>/dev/null); \
    MERGE_BASE_DEV=$$(git merge-base $$BRANCH dev 2>/dev/null); \
    DISTANCE_FROM_MAIN=$$(git rev-list --count $$MERGE_BASE_MAIN..$$BRANCH); \
    DISTANCE_FROM_DEV=$$(git rev-list --count $$MERGE_BASE_DEV..$$BRANCH); \
    if [ "$$DISTANCE_FROM_DEV" -lt "$$DISTANCE_FROM_MAIN" ]; then \
      echo "true"; \
    else echo "false"; fi; \
  else echo "false"; fi)

ifeq ($(origin VERSION),undefined)
  ifeq ($(GIT_BRANCH),main)
    VERSION := $(BASE_VERSION)
  else ifeq ($(GIT_BRANCH),dev)
    VERSION := $(DEV_VERSION)
  else ifeq ($(IS_FORKED_FROM_DEV),true)
    VERSION := $(DEV_VERSION)
  else
    VERSION := $(BASE_VERSION)
  endif
endif
```

### CI Version Extension

The CI workflow extends the Makefile version with commit SHA and branch-specific tags:

```yaml
# .github/workflows/build-and-push.yaml (excerpt)
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
```

## Configuration

- **Key settings:** `BASE_VERSION` is the single source of truth for the stable version; `VERSION` can be overridden on the command line or via environment variable
- **Defaults:** main branch = `0.0.14`, dev branch = `0.0.14-dev`, branches forked from dev = `0.0.14-dev`, all others = `0.0.14`
- **Dependencies:** Requires git with access to both `main` and `dev` branches for fork detection; the `$(origin VERSION)` check ensures explicit overrides are respected

## Gotchas

- The fork-from-dev detection uses `git rev-list --count` to compare merge-base distances -- if both main and dev are equidistant, the branch defaults to the stable version (see `Makefile` IS_FORKED_FROM_DEV)
- The Makefile logs which version was auto-detected vs explicitly set during `helm upgrade --install` to help debug image tag mismatches: `echo "Using image version: $(VERSION) (auto-detected from branch: $(GIT_BRANCH))"` (see `helm_install_common` function)
- CI builds produce multiple tags per image (`BASE_VERSION`, `BASE_VERSION-SHA`, `latest` or `BRANCH_NAME`), ensuring both mutable and immutable references exist (see `.github/workflows/build-and-push.yaml`)

## Related Patterns

- `github-actions-multi-image-release-pipeline.md` -- CI pipeline that consumes the version
