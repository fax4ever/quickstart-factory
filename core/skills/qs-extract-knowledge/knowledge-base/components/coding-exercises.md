---
name: coding-exercises
description: Starter/solution exercise files for AI code assistant demos, delivered via DevSpaces workspaces
summary: "Provides bundled starter/solution coding exercise pairs (Python + Bash) for AI code-assistant quickstarts, where starters contain only comment-based structured prompts under game_starters/ and solutions hold complete implementations under game_solutions/ — users practice AI-assisted coding via Continue IDE features like \"Edit Highlighted Code\" and \"Optimize this Code\" with no external packages required. Use when building a code-assistant quickstart needing guided educational content delivered into DevSpaces workspaces as static repo files cloned by a DevWorkspace CRD rather than via a Helm subchart. DevWorkspace delivery uses Helm-templated CRDs with udi-rhel9:3.25.0 image creating per-user workspaces in wksp-<user> namespaces (routingClass: che, workspace.enabled toggle), while Continue IDE config in .vscode/config.yaml points at the MaaS-served LLM (NVIDIA Nemotron) with CHE_DASHBOARD_URL injected from the cluster wildcard domain. Continue config ships with placeholder YOUR_MAAS_ROUTE/YOUR_API_KEY values requiring manual post-provisioning replacement, and solution files use different naming than starters (e.g., rps_solution.py vs rock_paper_scissors.py) which breaks filename-based auto-pairing tooling."
metadata:
  type: component
tags:
  tech_stack: [python, bash, devspaces, continue-ide]
  ai_pattern: [model-serving]
  platform: [rhoai, openshift]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "Guided coding exercises for Continue IDE with NVIDIA Nemotron via MaaS"
    approach: "A"
---

# Coding Exercises

## Overview

Coding exercises are bundled educational content shipped inside a code-assistant quickstart repo. They provide guided prompts and reference solutions so users can practice AI-assisted coding through an IDE extension (Continue) connected to a privately hosted LLM. The exercises are delivered into OpenShift DevSpaces workspaces via a DevWorkspace CRD that clones the repo, giving each user an isolated cloud IDE preloaded with the exercise files.

## Tech Stack & Dependencies

- **Runtime:** Python 3 and Bash (no external packages required)
- **Container image:** `registry.redhat.io/devspaces/udi-rhel9:3.25.0` (DevSpaces Universal Developer Image)
- **Key dependencies:** OpenShift DevSpaces with Continue IDE extension, MaaS-served LLM endpoint
- **Helm subchart:** None (delivered as static files cloned into the DevWorkspace)

## Key Patterns

### Starter/Solution File Structure

Each exercise ships as a pair: a starter file containing only commented prompts, and a solution file with the completed implementation. Both Python and Bash versions are provided for every exercise.

```
coding-exercises/
  game_starters/
    rock_paper_scissors/
      rock_paper_scissors.py    # Comment-only prompts
      rock_paper_scissors.sh
    simple_quiz/
    word_scramble/
  game_solutions/
    rock_paper_scissors/
      rps_solution.py           # Completed implementation
      rps_solution.sh
    simple_quiz/
    word_scramble/
```

### Guided Prompt Pattern in Starters

Starter files contain no executable code. Instead they provide a structured prompt the user copies into the Continue chat, followed by feature-specific practice suggestions and enhancement ideas.

```python
# Start by asking Continue's chat:
# "Create a Python rock paper scissors game that:
# - Uses random.choice() to pick the computer's move from ['rock', 'paper', 'scissors']
# - Asks the user to input their choice
# - Compares the choices and determines the winner using game rules
# - Shows both choices and declares the result (win/lose/tie)
# - Uses fun emojis in the output messages"
```

Each starter then lists Continue-specific IDE features to practice:

```python
# - In the Chat: Ask "How can I add score tracking?"
# - Highlight any section -> "Add Highlighted Code to Context" -> Ask about the game rules
# - Highlight any section -> "Edit Highlighted Code" -> "simplify this logic"
# - Highlight the entire script -> "Optimize this Code" for better structure
# - Highlight complex sections -> "Write Comments for this Code" for clarity
```

### DevWorkspace Delivery

The exercises reach users through a Helm-templated DevWorkspace CRD that clones the repo into each user's namespace. The workspace name is set to `exercises` in the Helm values.

```yaml
# From charts/maas-code-assistant/values.yaml
workspace:
  enabled: true
  namespacePrefix: wksp
  devworkspace:
    name: exercises
    projects:
      repoUrl: https://github.com/rh-ai-quickstart/maas-code-assistant.git
      revision: main
    image: registry.redhat.io/devspaces/udi-rhel9:3.25.0
```

The DevWorkspace template iterates over configured users, creating one workspace per user namespace:

```yaml
# From charts/maas-code-assistant/templates/workspace/devworkspace.yaml
{{- range $user := .Values.users }}
kind: DevWorkspace
apiVersion: workspace.devfile.io/v1alpha2
metadata:
  name: {{ $.Values.workspace.devworkspace.name }}
  namespace: {{ $.Values.workspace.namespacePrefix }}-{{ $user }}
spec:
  routingClass: che
  template:
    projects:
    - name: {{ $.Values.workspace.devworkspace.name }}
      git:
        remotes:
          origin: {{ $.Values.workspace.devworkspace.projects.repoUrl }}
{{- end }}
```

### Continue IDE Configuration

The repo bundles a `.vscode/config.yaml` that configures Continue to point at the MaaS-served model and a `.vscode/extensions.json` that recommends the Continue extension.

```yaml
# From .vscode/config.yaml
name: Local Assistant
version: 1.0.0
schema: v1
models:
  - name: NVIDIA Nemotron 3 Nano 30B-A3B
    provider: openai
    model: "nemotron-3-nano-30b-a3b"
    apiBase: "YOUR_MAAS_ROUTE/v1"
    apiKey: "YOUR_API_KEY"
```

## Configuration

- **Environment variables:** `CHE_DASHBOARD_URL` is injected into the tooling container from the cluster's wildcard domain
- **Config files:** `.vscode/config.yaml` (Continue model config), `.vscode/extensions.json` (extension recommendations)
- **Helm values:** `workspace.enabled`, `workspace.namespacePrefix`, `workspace.devworkspace.name`, `workspace.devworkspace.projects.repoUrl`, `workspace.devworkspace.image`

## Known Gotchas

- The Continue config in `.vscode/config.yaml` ships with placeholder values (`YOUR_MAAS_ROUTE`, `YOUR_API_KEY`) that must be replaced with the actual MaaS endpoint and API token after workspace provisioning
- Solution files use slightly different naming conventions than starters (e.g., `rps_solution.py` vs `rock_paper_scissors.py`), which means filename-based tooling cannot automatically pair them

## Testing Notes

- Verify each starter file contains no executable code (only comments) so users must use the AI assistant to generate it
- Verify solution files run correctly standalone: `python rps_solution.py`, `bash rps_solution.sh`
- Confirm the DevWorkspace clones the repo and the exercises directory appears under `/projects/exercises/coding-exercises/`

## Related Patterns

- DevSpaces workspace provisioning via Helm (see deployment patterns)
- MaaS model serving for code assistant use cases
