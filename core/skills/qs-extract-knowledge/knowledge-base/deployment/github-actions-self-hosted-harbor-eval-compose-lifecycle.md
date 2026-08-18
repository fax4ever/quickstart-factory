---
name: github-actions-self-hosted-harbor-eval-compose-lifecycle
description: Self-hosted runner Harbor skill eval with compose stack lifecycle, runner-side .env, and global concurrency lock
summary: "Orchestrates Harbor AI agent skill evaluations on self-hosted runners by managing the full Docker Compose stack lifecycle (build from PR HEAD with run-id-tagged image, 60x5s /health poll, Harbor trial execution, teardown with down -v --remove-orphans and ephemeral image cleanup) within a two-job GitHub Actions workflow. Use when CI must spin up a stateful backend+PostgreSQL stack per PR for live agent evaluation -- two-layer concurrency prevents collisions: workflow-level group cancels same-branch re-pushes while job-level aiq-harbor-eval group (cancel-in-progress: false) enforces global single-flight across all PRs; push events auto-trigger Harbor but workflow_dispatch requires inputs.run_harbor: true for two-tier gating. Critical config: runner-side .env (not GitHub Secrets) copied via install -m 0600 supplies credentials, workflow_dispatch free-form inputs passed via env: blocks (not ${{ }} interpolation) to prevent shell injection, and the Python eval script auto-masks any env var suffixed _KEY/_TOKEN/_SECRET/_PASSWORD in logs. Harbor containers must reach the host stack via host.docker.internal:8000 requiring extra_hosts: host.docker.internal:host-gateway in adapter config; --name-only diff compares against origin/develop for mirror branches but github.event.before for direct pushes; teardown must run as always() steps with volume removal to prevent PostgreSQL state leaking between runs."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, fastapi, postgresql]
  ai_pattern: [agents, evaluation]
  platform: []
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "AI-Q Blueprint Harbor eval on self-hosted aiq-eval runner with compose stack build, /health wait, global single-flight concurrency"
    approach: "A"
---

# Self-Hosted Harbor Skill Eval with Docker Compose Stack Lifecycle

## Overview

A GitHub Actions workflow that runs AI agent skill evaluations on a self-hosted runner by building the full application stack from the PR branch using Docker Compose, waiting for health, running Harbor trial evaluations, and tearing everything down. The workflow uses a runner-side `.env` file for credentials (never stored in GitHub Secrets for these long-lived runners), a global single-flight concurrency group to prevent parallel stack instances, and careful secret masking in logs.

## Pattern Description

The workflow has two jobs: (1) `generate-datasets` validates skill eval specs and materializes Harbor task datasets, and (2) `harbor-eval` brings up the full stack (backend + postgres) from the PR commit, waits for `/health`, runs Harbor trials against the live service, and tears down with volume cleanup. The harbor-eval job uses a separate concurrency group (`aiq-harbor-eval`) with `cancel-in-progress: false` to ensure only one stack runs at a time across all PRs, while same-PR re-pushes are handled by the workflow-level concurrency group.

## Implementation

### Runner-Side .env Materialization

Credentials live in a canonical `.env` file on the self-hosted runner, not in GitHub Secrets. The workflow copies it into the expected location for the compose file.

```yaml
env:
  RUNNER_ENV_FILE: /home/ubuntu/aiq-eval/.env

steps:
  - name: Verify runner .env exists
    run: |
      if [ ! -r "$RUNNER_ENV_FILE" ]; then
        echo "::error::Runner credential file missing at $RUNNER_ENV_FILE"
        exit 1
      fi
      # Print only the NAMES of keys present, never values
      grep -oE '^[A-Z_][A-Z0-9_]*=' "$RUNNER_ENV_FILE" | sed 's/=$//' | sort

  - name: Materialize deploy/.env from runner credentials
    run: |
      install -m 0600 "$RUNNER_ENV_FILE" deploy/.env
```

### Stack Build and Health Wait

The stack is built from the PR HEAD commit with a run-id-tagged image name to prevent collisions.

```yaml
  - name: Bring up AI-Q stack from PR HEAD
    working-directory: deploy/compose
    run: |
      set -a
      source "$RUNNER_ENV_FILE"
      set +a
      export BACKEND_IMAGE="aiq-agent:ci-${{ github.run_id }}"
      docker compose --env-file ../.env -f docker-compose.yaml \
        up -d --build aiq-agent postgres

  - name: Wait for AI-Q /health
    run: |
      for i in $(seq 1 60); do
        if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
          echo "AI-Q healthy after ${i} x 5s"
          exit 0
        fi
        sleep 5
      done
      echo "::error::AI-Q did not report healthy within 5 minutes"
      docker compose logs --tail 200 aiq-agent || true
      exit 1
```

### Global Single-Flight Concurrency

Two concurrency layers prevent conflicts: the workflow-level group cancels same-branch re-pushes, while the job-level group ensures only one harbor-eval runs anywhere at a time.

```yaml
# Workflow level: cancel same-branch re-pushes
concurrency:
  group: aiq-skills-eval-${{ github.ref }}
  cancel-in-progress: true

jobs:
  harbor-eval:
    # Job level: global single-flight for stack stateful operations
    concurrency:
      group: aiq-harbor-eval
      cancel-in-progress: false
```

### Comprehensive Teardown

The teardown runs in `always()` steps to ensure cleanup even on failure. It removes volumes to prevent PostgreSQL state leaking between runs.

```yaml
  - name: Tear down AI-Q stack
    if: always()
    working-directory: deploy/compose
    run: |
      docker compose --env-file ../.env -f docker-compose.yaml \
        down -v --remove-orphans || true
      docker image prune -f || true

  - name: Remove materialized deploy/.env
    if: always()
    run: rm -f deploy/.env || true

  - name: Clean ephemeral image
    if: always()
    run: docker image rm "aiq-agent:ci-${{ github.run_id }}" 2>/dev/null || true
```

### Harbor Trial Execution with Secret Masking

The Python eval script receives credentials via environment and provides built-in secret masking for any `KEY=VALUE` arguments where the key ends in `_KEY`, `_TOKEN`, `_SECRET`, or `_PASSWORD`.

```yaml
  - name: Run Harbor trials
    env:
      AIQ_SERVER_URL: http://host.docker.internal:8000
      AGENT_INPUT: ${{ inputs.agent }}
      MODEL_INPUT: ${{ inputs.model }}
    run: |
      AGENT="${AGENT_INPUT:-claude-code}"
      set -a; source "$RUNNER_ENV_FILE"; set +a
      if [ -n "$MODEL_INPUT" ]; then
        export AIQ_SKILL_EVAL_MODEL="$MODEL_INPUT"
      fi
      python3 .github/skill-eval/skills_eval_agent.py $SCOPE --run-harbor \
        --output-dir /tmp/aiq-skill-eval/datasets
```

## Configuration

- **Key settings:** `RUNNER_ENV_FILE` path on self-hosted runner; `AIQ_SERVER_URL` for Harbor to reach the stack; `inputs.agent` and `inputs.model` for workflow_dispatch overrides
- **Defaults:** Agent defaults to `claude-code`; model uses runner .env default unless overridden via dispatch
- **Dependencies:** Self-hosted runner labeled `[self-hosted, aiq-eval]`; Docker and docker-compose on the runner; runner-side `.env` with all API keys

## Gotchas

- The `host.docker.internal:8000` URL is used because Harbor tasks run in their own container and need to reach the stack running on the same host -- this requires `extra_hosts: host.docker.internal:host-gateway` in the Harbor adapter configuration
- The `install -m 0600` command copies the runner .env with restrictive permissions (owner read/write only) as defense-in-depth
- Workflow dispatch inputs (`inputs.agent`, `inputs.model`) are passed via `env:` rather than interpolated with `${{ }}` in shell scripts to prevent injection -- the comment explicitly calls this out as the free-form `model` input could otherwise allow injection
- Push events run Harbor automatically; `workflow_dispatch` requires `inputs.run_harbor: true` -- this two-tier gating prevents accidental full eval runs during manual debugging
- The `--name-only` diff for path detection compares against `origin/develop` for mirror branches but `github.event.before` for direct pushes

## Related Patterns

- `github-actions-copy-pr-bot-mirror-branch-push-only-ci.md` -- the trigger model used by this workflow
- `compose-local-dev-prebuilt-ngc-fallback-build-target-dask.md` -- the compose file used to bring up the stack
