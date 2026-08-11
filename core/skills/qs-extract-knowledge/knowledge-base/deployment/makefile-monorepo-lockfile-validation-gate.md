---
name: makefile-monorepo-lockfile-validation-gate
description: Makefile prerequisites validate uv lockfiles and requirements.txt across 12 service directories before builds
summary: "Prevents building container images with stale Python dependencies in a monorepo by gating each Makefile build target on `uv lock --check` prerequisites across 12 LOCKFILE_DIRS, plus compound `check-deps-<template>` targets that validate shared libraries (shared-models, shared-clients, agent-service, mock-employee-data). Use when a Python monorepo has multiple containerized services sharing libraries via Containerfile templates -- Makefile `define` functions (check_lockfile, update_lockfile) provide per-directory validation and a batch `update-lockfiles` target updates all lockfiles including the root project in one command. Build targets chain prerequisites (e.g., `build-request-mgr-image` depends on `check-lockfile-request-manager` and `check-deps-services-template`); CI runs `make check-lockfiles` and `make check-requirements` with uv pinned via `astral-sh/setup-uv` and `check-release-manifest` preventing BASE_VERSION drift against bump-release.manifest.json. `check-uv-version` is a prerequisite of both check-lockfiles and check-requirements enforcing local/CI version parity; REQUIREMENTS_DIRS is a smaller subset of LOCKFILE_DIRS because only containerized services need requirements.txt export for the `USE_PIP_INSTALL=true` fallback build path."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python]
  ai_pattern: []
  platform: []
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "12 LOCKFILE_DIRS with check-lockfile/update-lockfile per dir, build targets depend on shared lib lockfile checks"
    approach: "A"
---

# Makefile Monorepo Lockfile Validation Gate

## Overview

This pattern uses Makefile prerequisites to validate that `uv.lock` files are current across all service directories in a Python monorepo before allowing container image builds. Build targets for each service depend on `check-lockfile-<service>` targets that run `uv lock --check`, plus `check-deps-<template>` targets that validate shared libraries used by the Containerfile template. This prevents building images with stale or missing dependencies.

## Pattern Description

The Makefile defines `LOCKFILE_DIRS` listing all 12 directories containing `uv.lock` files, and `REQUIREMENTS_DIRS` for the subset that also need `requirements.txt` export. Two `define` functions (`check_lockfile` and `update_lockfile`) provide the implementation. Build targets chain through dependency prerequisites: `build-request-mgr-image` depends on `check-lockfile-request-manager` and `check-deps-services-template`, where the latter validates shared-models, shared-clients, agent-service, and mock-employee-data lockfiles.

## Implementation

### Lockfile Check Function

```makefile
# Makefile (excerpt)
LOCKFILE_DIRS := shared-models shared-clients agent-service request-manager \
  integration-dispatcher mcp-servers/mcp-common mcp-servers/snow mcp-servers/zammad \
  mock-eventing-service mock-employee-data scripts/servicenow-bootstrap zammad-bootstrap

define check_lockfile
	@echo "Checking $(1)..."
	@if [ -d "$(1)" ]; then \
		if (cd "$(1)" && uv lock --check); then \
			echo "$(1) lockfile is up-to-date"; \
		else \
			echo "$(1) lockfile needs updating"; \
			exit 1; \
		fi; \
	fi
endef
```

### Template Dependency Chains

Each Containerfile template has a compound prerequisite checking all shared libraries it copies:

```makefile
# Makefile (excerpt)
check-deps-services-template: check-lockfile-shared-models check-lockfile-shared-clients \
  check-lockfile-agent-service check-lockfile-mock-employee-data

check-deps-mcp-template: check-lockfile-shared-models check-lockfile-mcp-common

build-request-mgr-image: check-lockfile-request-manager check-deps-services-template
build-mcp-snow-image: check-lockfile-mcp-snow check-deps-mcp-template
```

### CI Integration

The PR quality check workflow validates all lockfiles and requirements.txt sync:

```yaml
# .github/workflows/pr-checks.yml (excerpt)
- name: Check lockfiles are up-to-date
  run: make check-lockfiles
- name: Check requirements.txt files are in sync with lockfiles
  run: make check-requirements
```

### Update All Lockfiles

A single command updates all lockfiles and optionally re-exports requirements.txt:

```makefile
# Makefile (excerpt)
update-lockfiles: check-uv-version
	@uv lock  # root project
	@for dir in $(LOCKFILE_DIRS); do \
		$(MAKE_SAME) _update-one-lockfile DIR="$$dir"; \
	done
```

## Configuration

- **Key settings:** `LOCKFILE_DIRS` lists all directories with lockfiles; `REQUIREMENTS_DIRS` lists the subset needing requirements.txt export; `UV_VERSION` is the required uv version (enforced by `check-uv-version` target)
- **Defaults:** `check-lockfiles` also validates the root project lockfile; `update-lockfiles` always runs `uv lock` (no `--check`) for updates
- **Dependencies:** Requires `uv` at the version specified in the Makefile; the CI workflow pins uv version via `astral-sh/setup-uv` action

## Gotchas

- The `check-uv-version` target is a prerequisite of both `check-lockfiles` and `check-requirements`, ensuring version consistency between local development and CI (see `Makefile`)
- The `REQUIREMENTS_DIRS` subset is smaller than `LOCKFILE_DIRS` because only containerized services need `requirements.txt` (for the `USE_PIP_INSTALL=true` fallback build path) -- shared libraries and scripts do not
- The CI workflow also validates `check-release-manifest` which ensures the Makefile `BASE_VERSION` matches `scripts/bump-release.manifest.json`, preventing version drift between the Makefile and the release manifest

## Related Patterns

- `container-build-parameterized-containerfile-template.md` -- build targets that depend on these lockfile checks
