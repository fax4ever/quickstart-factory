---
name: github-actions-openshift-deploy-undeploy-confirm-safety
description: GitHub Actions deploy/undeploy workflows with safety confirmation, rebase check, and oc-login for OpenShift
summary: "Provides three GitHub Actions workflow_dispatch workflows for OpenShift deployment lifecycle — deploy via `make install` with oc-login, undeploy with destructive-action safety confirmation, and PR rebase enforcement. Use when quickstarts need manual deploy/undeploy triggers with namespace targeting and PR freshness enforcement; pairs with the semver-release-cleanup pattern that produces the container images deployed here. Deploy requires OPENSHIFT_SERVER, OPENSHIFT_TOKEN, and HUGGINGFACE_API_KEY repo secrets with redhat-actions/openshift-tools-installer@v1 and oc-login@v1; undeploy uses dual mutually exclusive jobs with opposite `if` conditions matching `format(\"DELETE {0}\", namespace)` for clear error messaging on failed confirmation. Undeploy confirmation must be exactly \"DELETE my-namespace\" including the specific namespace name (not just \"DELETE\"); deploy uses `insecure_skip_tls_verify: true` needing production update; rebase-check requires `fetch-depth: 0` and deduplicates bot comments to avoid PR spam; `make install` triggers the entire chain including operators, observability, RAG, and MCP server."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "Deploy via workflow_dispatch with namespace input, undeploy with DELETE {namespace} confirmation, rebase-check enforcing PR freshness"
    approach: "A"
---

# GitHub Actions OpenShift Deploy/Undeploy with Safety Confirmation

## Overview

This pattern provides GitHub Actions workflows for deploying and undeploying to OpenShift via `workflow_dispatch`, with a safety confirmation mechanism for destructive operations and a PR rebase enforcement workflow. The deploy workflow runs `make install`, the undeploy requires typing "DELETE {namespace}" as confirmation, and a separate workflow blocks PRs that are not rebased on the target branch.

## Pattern Description

Three workflows handle deployment lifecycle: `deploy.yml` takes a namespace parameter and runs `make install` after `oc login`; `undeploy.yml` requires the user to type `DELETE {namespace}` as confirmation to prevent accidental deletions; `rebase-check.yml` runs on PRs and fails if the PR branch is behind the base branch, posting a comment with rebase instructions.

## Implementation

### Deploy Workflow

```yaml
# .github/workflows/deploy.yml
name: Deploy to OpenShift
on:
  workflow_dispatch:
    inputs:
      namespace:
        description: 'Target namespace for deployment'
        required: true
        type: string
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: redhat-actions/openshift-tools-installer@v1
        with:
          oc: 4
      - uses: redhat-actions/oc-login@v1
        with:
          openshift_server_url: ${{ secrets.OPENSHIFT_SERVER }}
          openshift_token: ${{ secrets.OPENSHIFT_TOKEN }}
          insecure_skip_tls_verify: true
      - name: Deploy
        env:
          HF_TOKEN: ${{ secrets.HUGGINGFACE_API_KEY }}
          NAMESPACE: ${{ github.event.inputs.namespace }}
        run: make install
```

### Undeploy Workflow with Safety Confirmation

```yaml
# .github/workflows/undeploy.yml
name: Undeploy from OpenShift
on:
  workflow_dispatch:
    inputs:
      namespace:
        description: 'Target namespace for undeployment'
        required: true
        type: string
      confirm_uninstall:
        description: 'Type "DELETE {namespace}" to confirm'
        required: true
        type: string

jobs:
  check-confirmation:
    runs-on: ubuntu-latest
    if: ${{ github.event.inputs.confirm_uninstall != format('DELETE {0}', github.event.inputs.namespace) }}
    steps:
      - name: Log confirmation error
        run: |
          EXPECTED="DELETE ${{ github.event.inputs.namespace }}"
          echo "Safety Check Failed:"
          echo "  Expected: '$EXPECTED'"
          echo "  You entered: '${{ github.event.inputs.confirm_uninstall }}'"
          exit 1

  undeploy:
    runs-on: ubuntu-latest
    if: ${{ github.event.inputs.confirm_uninstall == format('DELETE {0}', github.event.inputs.namespace) }}
    steps:
      - name: Show resources before uninstall
        run: make status NAMESPACE=${{ env.NAMESPACE }}
      - name: Uninstall
        run: make uninstall NAMESPACE=${{ env.NAMESPACE }}
```

### Rebase Check Workflow

```yaml
# .github/workflows/rebase-check.yml
name: Rebase Check
on:
  pull_request:
    types: [opened, synchronize, reopened]
jobs:
  rebase-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - name: Check if PR is up to date
        id: rebase-check
        run: |
          BASE_BRANCH="${{ github.event.pull_request.base.ref }}"
          git fetch origin $BASE_BRANCH
          BASE_HEAD=$(git rev-parse origin/$BASE_BRANCH)
          MERGE_BASE=$(git merge-base HEAD origin/$BASE_BRANCH)
          if [ "$MERGE_BASE" != "$BASE_HEAD" ]; then
            echo "is_up_to_date=false" >> $GITHUB_OUTPUT
            exit 1
          fi
      - name: Comment on PR if not up to date
        if: steps.rebase-check.outputs.is_up_to_date == 'false'
        uses: actions/github-script@v7
        with:
          script: |
            // Only post comment once (check for existing rebase comment)
            const { data: comments } = await github.rest.issues.listComments({...});
            const hasRebaseComment = comments.some(c =>
              c.user.type === 'Bot' && c.body.includes('Rebase Required'));
            if (!hasRebaseComment) {
              await github.rest.issues.createComment({
                body: `**Rebase Required**\n\`\`\`bash\ngit rebase origin/$BASE_BRANCH\ngit push --force-with-lease\n\`\`\``
              });
            }
```

## Configuration

- **Key settings:** `OPENSHIFT_SERVER` and `OPENSHIFT_TOKEN` as repository secrets; `HUGGINGFACE_API_KEY` for model deployment; namespace specified at workflow_dispatch time
- **Defaults:** Deploy workflow uses `insecure_skip_tls_verify: true` (noted as needing update for production); undeploy requires exact string match including namespace name
- **Dependencies:** `redhat-actions/openshift-tools-installer@v1` for oc CLI; `redhat-actions/oc-login@v1` for authentication; Makefile's `install` and `uninstall` targets

## Gotchas

- The undeploy confirmation uses `format('DELETE {0}', ...)` in the `if` condition -- the user must type exactly "DELETE my-namespace" including the specific namespace name, not just "DELETE"
- The undeploy workflow has two mutually exclusive jobs controlled by opposite `if` conditions: `check-confirmation` (fails with error message) and `undeploy` (actually runs) -- this ensures a clear failure message when confirmation is wrong
- The rebase check only posts one comment per PR (checks for existing bot comments with "Rebase Required" text to avoid spam)
- The deploy workflow runs `make install` which triggers the entire installation chain including operator installs, observability stack, RAG, and MCP server

## Related Patterns

- `github-actions-reusable-workflow-semver-release-cleanup.md` -- the build/release pipeline that produces images deployed by this workflow
