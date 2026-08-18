---
name: github-actions-enforce-pr-branch-target-policy
description: GitHub Actions workflow enforcing PRs target dev branch and restricting main to automated release/* branches
summary: "Enforces PR branch targeting in a dev-to-main promotion model via enforce-pr-target.yml triggered on PR open/reopen/synchronize/edited events, checking github.actor and head.ref against a three-way policy: PRs to dev always pass, PRs to main require github-actions[bot] from release/* branches, all other base branches are rejected. Use when implementing a protected dev-to-main release flow alongside create-release-pr.yml which creates automated release/* branches using github.token -- single approach with shell-based validation. The workflow validates via env vars BASE_REF/HEAD_REF/ACTOR with a case statement matching release/* pattern for main-targeting PRs, allowing dev unconditionally and rejecting unknown base branches with descriptive error messages. Check is purely advisory unless added as a required status check in branch protection settings; the edited event trigger prevents base-branch switching to bypass policy, and using a PAT instead of github.token in the release workflow changes the actor from github-actions[bot], breaking the validation."
metadata:
  type: deployment-pattern
tags:
  tech_stack: []
  ai_pattern: []
  platform: []
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "enforce-pr-target.yml validates PR base branch: dev for all contributors, main restricted to github-actions[bot] from release/* branches only"
    approach: "A"
---

# GitHub Actions PR Branch Target Enforcement

## Overview

This pattern uses a GitHub Actions workflow to enforce branch targeting policy: all contributor PRs must target `dev`, and only automated release PRs from `github-actions[bot]` on `release/*` branches may target `main`. It prevents accidental direct-to-main PRs in a dev-to-main branch promotion model.

## Pattern Description

The `enforce-pr-target.yml` workflow triggers on PR open, reopen, synchronize, and edit events. It checks the PR's base branch and head branch against policy rules: PRs targeting `dev` are always allowed, PRs targeting `main` must come from `github-actions[bot]` on a `release/*` branch, and all other base branches are rejected.

## Implementation

### Branch Policy Enforcement

```yaml
# .github/workflows/enforce-pr-target.yml
name: Enforce PR Target Branch

on:
  pull_request:
    types: [opened, reopened, synchronize, edited]

jobs:
  validate-target-branch:
    runs-on: ubuntu-latest
    steps:
      - name: Validate PR base branch policy
        env:
          BASE_REF: ${{ github.event.pull_request.base.ref }}
          HEAD_REF: ${{ github.event.pull_request.head.ref }}
          ACTOR: ${{ github.actor }}
        run: |
          # Standard development flow: PRs target dev.
          if [ "${BASE_REF}" = "dev" ]; then
            echo "OK: PR targets dev."
            exit 0
          fi

          # Release flow: only GitHub Actions can open release/* PRs to main.
          if [ "${BASE_REF}" = "main" ]; then
            if [ "${ACTOR}" != "github-actions[bot]" ]; then
              echo "ERROR: PRs to main are restricted to github-actions[bot]."
              echo "Please open your PR against dev."
              exit 1
            fi

            case "${HEAD_REF}" in
              release/*)
                echo "OK: Automated release PR to main."
                exit 0
                ;;
              *)
                echo "ERROR: Automated PRs to main must come from release/* branches."
                exit 1
                ;;
            esac
          fi

          echo "ERROR: Invalid PR base branch '${BASE_REF}'."
          echo "PRs must target dev. Only automated release PRs may target main."
          exit 1
```

## Configuration

- **Key settings:** The workflow checks `github.actor` against `github-actions[bot]` and `github.event.pull_request.head.ref` against `release/*` pattern
- **Defaults:** All PRs to `dev` are allowed; all PRs to `main` from human actors are blocked
- **Dependencies:** Works with the `create-release-pr.yml` workflow that creates automated `release/*` branches

## Gotchas

- The workflow triggers on `edited` events, which means changing a PR's base branch will re-run the check -- this prevents a contributor from initially targeting `dev` and then changing the target to `main`
- The actor check (`github-actions[bot]`) only works when the release PR is created by the `create-release-pr.yml` workflow using `github.token`; if a different token (e.g., a PAT) is used, the actor may differ
- This check is purely advisory unless configured as a required status check in branch protection settings -- without branch protection, a contributor can still merge to main even if this check fails

## Related Patterns

- `github-actions-multi-image-release-pipeline.md` -- the release pipeline that creates the `release/*` branches this workflow permits
