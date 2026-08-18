---
name: github-actions-copy-pr-bot-mirror-branch-push-only-ci
description: CI triggers on push to mirror branches created by copy-pr-bot after /ok to test approval gate
summary: "A push-only CI trigger model where all GitHub Actions workflows fire on push to develop, release/**, and pull-request/[0-9]+ branches -- never pull_request -- with copy-pr-bot mirroring approved PRs to pull-request/<N> after maintainer /ok to test gate, solving pull_request_target secret-exposure risk for fork PRs. Use when external contributors need full CI with repository secrets access gated by maintainer approval; CI splits across four workflows (ci.yml, ui.yml, skills-eval.yml, request-nvskills-ci.yml) sharing the trigger block with permissions: contents: read and cancel-in-progress: true concurrency on github.ref. Path filters silently skip mirror-branch pushes because copy-pr-bot creates branches at existing commits with no file diff -- use a detect-changes job that diffs pull-request/* against origin/develop and direct pushes against github.event.before, falling back to relevant=true on missing or zero base SHA. Context values (github.ref_name, github.event.before) must be passed via env: not ${{ }} shell interpolation to prevent branch-name injection attacks, and pull-request/* vs develop/release branches use fundamentally different diff base references."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, nodejs, helm]
  ai_pattern: []
  platform: []
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "AI-Q Blueprint CI with push-only triggers on develop, release/**, and pull-request/[0-9]+ mirror branches"
    approach: "A"
---

# GitHub Actions Push-Only CI with copy-pr-bot Mirror Branches

## Overview

A CI trigger model where all GitHub Actions workflows use `push` events exclusively (never `pull_request`) on `develop`, `release/**`, and `pull-request/[0-9]+` branches. Pull requests from both internal and external contributors are mirrored to `pull-request/<N>` branches by a copy-pr-bot after a maintainer approves with `/ok to test`. This creates a trust gate that prevents untrusted PR code from accessing repository secrets while still running full CI.

## Pattern Description

The copy-pr-bot mirrors approved PRs to `pull-request/<N>` branches, which then trigger push-based workflows. This approach solves the `pull_request_target` security problem (where fork PRs can access secrets) without sacrificing CI coverage for external contributions. Since the mirror is a push event on a branch the repo owns, all repository secrets are available without the risks of `pull_request_target`. Concurrency groups use `github.ref` to cancel in-progress runs for the same branch.

## Implementation

### Standard Workflow Trigger Pattern

Every workflow uses the same trigger block. The comment at the top explains why `push` is used instead of `pull_request`.

```yaml
name: AIQ CI

# Trigger: push-only. All PRs (internal and external) are mirrored to
# pull-request/<N> branches by copy-pr-bot after `/ok to test` approval.
on:
  push:
    branches:
      - develop
      - "release/**"
      - "pull-request/[0-9]+"

permissions:
  contents: read

concurrency:
  group: aiq-ci-${{ github.ref }}
  cancel-in-progress: true
```

### Path-Filtered Workflows

Some workflows add `paths:` filters to only run when relevant files change. However, the skills-eval workflow explicitly documents why it cannot use `paths:` -- because copy-pr-bot creates the mirror branch at an already-existing commit, so the branch-creation push has no file diff and a `paths:` filter would silently skip the workflow.

```yaml
# ui.yml - path-filtered
on:
  push:
    branches:
      - develop
      - "release/**"
      - "pull-request/[0-9]+"
    paths:
      - "frontends/ui/**"
      - ".github/workflows/ui.yml"

# skills-eval.yml - NO paths filter (documented reason)
# NB: deliberately NO `paths:` filter. copy-pr-bot creates the mirror
# branch at an already-existing commit, so the branch-creation push has
# no file diff and a `paths:` filter would silently exclude the workflow.
```

### Change Detection Job (Alternative to paths filter)

When `paths:` cannot be used, a `detect-changes` job performs the path gating by diffing against the PR base.

```yaml
  detect-changes:
    name: Detect skill/eval changes
    runs-on: ubuntu-latest
    outputs:
      relevant: ${{ steps.f.outputs.relevant }}
    steps:
      - name: Filter watched paths
        id: f
        env:
          REF_NAME: ${{ github.ref_name }}
          BEFORE_SHA: ${{ github.event.before }}
        run: |
          case "$REF_NAME" in
            pull-request/*) BASE="origin/develop" ;;
            *)              BASE="$BEFORE_SHA" ;;
          esac
          if git diff --name-only "$BASE"...HEAD \
               | grep -qE '^(skills/|\.github/skill-eval/)'; then
            echo "relevant=true" >> "$GITHUB_OUTPUT"
          else
            echo "relevant=false" >> "$GITHUB_OUTPUT"
          fi
```

### Multi-Workflow Split

The CI is split across four workflow files, each with the same trigger pattern:

| Workflow | Purpose | Path filter |
|----------|---------|-------------|
| `ci.yml` | Pre-commit hooks, pytest with coverage, Helm lint, script validation | None |
| `ui.yml` | Frontend lint, type-check, unit tests, build | `frontends/ui/**` |
| `skills-eval.yml` | Skill spec validation, Harbor eval on self-hosted runner | detect-changes job |
| `request-nvskills-ci.yml` | Trigger NVSkills validation via reusable workflow | `/nvskills-ci` comment or bot push |

## Configuration

- **Key settings:** Branch patterns (`develop`, `release/**`, `pull-request/[0-9]+`); concurrency group per workflow
- **Defaults:** `cancel-in-progress: true` for all workflows; `permissions: contents: read` for least privilege
- **Dependencies:** copy-pr-bot must be configured on the repository to mirror PRs to `pull-request/<N>` branches

## Gotchas

- Path filters in workflow triggers do NOT work reliably with copy-pr-bot mirror branches because the branch creation push carries no file diff -- use a detect-changes job instead if path gating is needed
- The `detect-changes` job falls back to `relevant=true` when the base SHA is missing, zero (`0000000000000000000000000000000000000000`), or unresolvable -- this ensures new branches always run CI rather than silently skipping
- `pull-request/*` mirror branches diff against `origin/develop`, while direct pushes to `develop`/`release` diff against the pre-push SHA (`github.event.before`) -- these are fundamentally different base references
- Context values (`github.ref_name`, `github.event.before`) are passed via `env:` rather than interpolated directly into shell scripts with `${{ }}` to prevent injection attacks from branch names

## Related Patterns

- `github-actions-self-hosted-harbor-eval-compose-lifecycle.md` -- the skills-eval workflow that uses this trigger model with self-hosted runners
