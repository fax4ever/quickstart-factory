---
name: makefile-autodetect-podman-docker-profile-compose
description: Makefile auto-detecting podman-compose vs docker compose and podman vs docker CLI with profile-based compose targets
summary: "Solves container toolchain portability in Makefiles by auto-detecting podman-compose vs docker compose and podman vs docker at parse time using $(shell command -v ...) with ?= conditional assignment, enabling the same Makefile to work across Podman and Docker environments without modification. Use when a quickstart needs profile-based local development (progressively layered services via compose --profile) combined with image build/push and Helm deploy chain in a single Makefile -- prefer over split Makefiles when all targets share the same auto-detected toolchain variables. Profile targets map to progressive service layers -- run-minimal (base), run-auth/run-ai/run-obs (individual profiles), run (--profile full) -- while deploy chains oc new-project, push-images (to REGISTRY/REGISTRY_NS, default quay.io/rh-ai-quickstart), helm-dep-update, and scripts/deploy.sh with all variables exported via export. Auto-detection uses PATH lookup so podman-compose installed outside PATH silently falls back to docker compose; stop target must use --profile full or profiled services from run-auth/run-ai remain running; helm-dep-update uses || echo to no-op when chart has no dependencies; smoke test must explicitly pass COMPOSE variable because the script re-detects if unset."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, react]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Makefile with shell-based auto-detection of compose and container CLI, profile-based run targets, image build/push, and Helm deploy chain"
    approach: "A"
---

# Makefile with Auto-Detected Container Toolchain and Profile Targets

## Overview

This pattern provides a Makefile that auto-detects whether podman-compose or docker compose is available, and separately detects podman vs docker for image builds. It exposes profile-based compose targets (run, run-minimal, run-auth, run-ai, run-obs) and chains image build, push, and Helm deploy targets for OpenShift deployment.

## Pattern Description

The Makefile uses `$(shell command -v ...)` to detect the available container toolchain at parse time, with all detection overridable via environment variables. Compose profiles map to Makefile targets that progressively add service layers. Image build targets use the detected container CLI to build from Containerfiles, and push targets tag and push to a configurable registry. The deploy target chains project creation, image push, Helm dependency update, and the deploy script.

## Implementation

### Tool Auto-Detection

```makefile
# Makefile (excerpt)
# Auto-detect compose: podman-compose > docker compose v2
COMPOSE ?= $(shell command -v podman-compose >/dev/null 2>&1 && echo "podman-compose" || echo "docker compose")

# Auto-detect container CLI: podman > docker
CONTAINER_CLI ?= $(shell command -v podman >/dev/null 2>&1 && echo "podman" || echo "docker")
```

### Profile-Based Compose Targets

```makefile
# Makefile (excerpt)
run:
	$(COMPOSE) --profile full up -d

run-minimal:
	$(COMPOSE) up -d

run-auth:
	$(COMPOSE) --profile auth up -d

run-ai:
	$(COMPOSE) --profile ai up -d

run-obs:
	$(COMPOSE) --profile observability up -d

stop:
	$(COMPOSE) --profile full down
```

### Image Build with Configurable Registry

```makefile
# Makefile (excerpt)
REGISTRY    ?= quay.io
REGISTRY_NS ?= rh-ai-quickstart
IMAGE_TAG   ?= latest

build-images:
	@$(CONTAINER_CLI) build -f packages/api/Containerfile -t mortgage-ai-api:$(IMAGE_TAG) .
	@$(CONTAINER_CLI) build -f packages/ui/Containerfile -t mortgage-ai-ui:$(IMAGE_TAG) .
```

### Deploy Chain

```makefile
# Makefile (excerpt)
deploy: create-project push-images helm-dep-update
	@scripts/deploy.sh

create-project:
	@oc new-project $(NAMESPACE) || echo "Project $(NAMESPACE) already exists"
```

### Exported Variables for Scripts

```makefile
# Makefile (excerpt)
export PROJECT_NAME NAMESPACE REGISTRY REGISTRY_NS IMAGE_TAG CONTAINER_CLI \
       ENV_FILE HELM_TIMEOUT HELM_EXTRA_ARGS
```

## Configuration

- **Key settings:** `COMPOSE` (auto-detected), `CONTAINER_CLI` (auto-detected), `REGISTRY` (default: quay.io), `REGISTRY_NS` (default: rh-ai-quickstart), `IMAGE_TAG` (default: latest), `NAMESPACE` (default: mortgage-ai), `HELM_TIMEOUT` (default: 15m)
- **Defaults:** All variables are overridable via `make deploy REGISTRY=my-registry.io`; the deploy target chains three prerequisites before calling the deploy script
- **Dependencies:** `oc` CLI for `create-project`; `helm` for `helm-dep-update` and the deploy script; container CLI for `build-images` and `push-images`

## Gotchas

- The auto-detection uses `command -v podman-compose` which checks PATH -- if podman-compose is installed but not in PATH, it falls back to `docker compose` (see `Makefile` line 16)
- The `stop` target uses `--profile full` to ensure all profiled services are stopped, not just the always-on ones -- without `--profile full`, profiled services started by `run-auth` or `run-ai` would not be stopped (see `Makefile`)
- The `export` statement makes all listed variables available to scripts called by the Makefile -- this is how `scripts/deploy.sh` and `scripts/push-images.sh` receive their configuration (see `Makefile`)
- The smoke test target delegates to a script: `smoke: @COMPOSE="$(COMPOSE)" scripts/smoke-test.sh` -- the `COMPOSE` variable is explicitly passed because the script re-detects it if not set (see `Makefile`)
- The `helm-dep-update` target includes `|| echo "No dependencies to update"` because the chart has no `dependencies:` block -- this makes the target a no-op that doesn't fail (see `Makefile`)

## Related Patterns

- `makefile-split-cluster-local-interactive-env.md` -- alternative Makefile with interactive env file generation
- `makefile-multi-profile-helm-install.md` -- Makefile with Helm profile selection
- `deploy-script-conditional-env-helm-set-cluster-autodiscovery.md` -- the deploy script called by the deploy target
