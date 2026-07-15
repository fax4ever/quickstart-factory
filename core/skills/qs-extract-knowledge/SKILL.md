---
name: qs-extract-knowledge
description: Extract reusable knowledge from an existing AI Quickstart repo and produce structured KB files
argument-hint: --repo <github-url>
allowed-tools: Bash, Read, Write, Edit, Agent
---

# Quickstart Knowledge Extraction Skill

You are extracting reusable patterns from an existing Red Hat AI Quickstart repository. The extracted knowledge populates a structured knowledge base that a future creation skill will use to build new quickstarts from scratch.

## Goal

Analyze a cloned quickstart repo and produce atomic, reusable KB files organized by category: components, archetypes, architectures, and deployment. Each extraction run adds to or merges with the growing knowledge base.

## Input

The user provides a GitHub repository URL:
- `--repo <url>`: AI Quickstart repository (e.g., `https://github.com/rh-ai-quickstart/RAG`)

## Supporting Documents

**Main agent reads directly:**

| File | When |
|------|------|
| This file (`SKILL.md`) | Always |
| `reasoning-guardrails.md` | During Phase 2 dispatch decisions |
| `kb-templates/kb-schema.md` | When validating subagent output |

**Only subagents read (passed by file path):**

| File | Read by |
|------|---------|
| `subagents/scout-prompt.md` | Scout subagent |
| `subagents/component-researcher-prompt.md` | Component researcher subagents |
| `subagents/archetype-researcher-prompt.md` | Archetype researcher subagent |
| `subagents/architecture-researcher-prompt.md` | Architecture researcher subagent |
| `subagents/deployment-researcher-prompt.md` | Deployment researcher subagent |
| `subagents/summary-generator-prompt.md` | Summary generator subagents |
| `kb-templates/kb-schema.md` | All researcher subagents |
| `kb-templates/component.md` | Component researcher subagents |
| `kb-templates/archetype.md` | Archetype researcher subagent |
| `kb-templates/architecture.md` | Architecture researcher subagent |
| `kb-templates/deployment.md` | Deployment researcher subagent |

## Workflow

### Phase 1: Scout

1. Parse `--repo <github-url>` from user input.
2. Derive repo name from URL (e.g., `RAG` from `https://github.com/rh-ai-quickstart/RAG`).
3. Set `SKILL_DIR` to the directory containing this SKILL.md file.
4. Spawn the **scout subagent**:

```
Agent(
    description="Scout: clone and scan <repo_name>",
    prompt="""
Read and follow instructions from:
<SKILL_DIR>/subagents/scout-prompt.md

repo_url: <github-url>
"""
)
```

5. Parse the scout's JSON return value. Expected structure:

```json
{
  "repo_name": "RAG",
  "clone_path": ".tmp/cloned-quickstart/RAG",
  "components": [
    {"name": "fastapi-backend", "type": "backend", "path": "app/", "tech": "FastAPI"},
    {"name": "react-frontend", "type": "frontend", "path": "frontend/", "tech": "React/PatternFly"}
  ],
  "deployment_methods": ["helm", "docker-compose"],
  "ai_pattern_hint": "rag",
  "model_serving": "kserve-vllm",
  "repo_layout": "monorepo",
  "ci_cd": ["github-actions", "makefile"],
  "readme_summary": "Enterprise RAG chatbot with..."
}
```

### Phase 2: Parallel Research + Write

Spawn ALL of the following subagents **in parallel** (no file conflicts by design — each writes to a different category directory or distinct component file):

**Per-component subagents** — one for each component in the scout report:

```
Agent(
    description="Research component: <component.name>",
    prompt="""
Read and follow instructions from:
<SKILL_DIR>/subagents/component-researcher-prompt.md

component_name: <component.name>
component_type: <component.type>
component_path: <component.path>
clone_path: <scout.clone_path>
repo_name: <scout.repo_name>
kb_path: <SKILL_DIR>/knowledge-base
templates_path: <SKILL_DIR>/kb-templates
"""
)
```

**Archetype researcher** — one subagent:

```
Agent(
    description="Research archetypes for <repo_name>",
    prompt="""
Read and follow instructions from:
<SKILL_DIR>/subagents/archetype-researcher-prompt.md

scout_report: <full scout JSON>
clone_path: <scout.clone_path>
repo_name: <scout.repo_name>
kb_path: <SKILL_DIR>/knowledge-base
templates_path: <SKILL_DIR>/kb-templates
"""
)
```

**Architecture researcher** — one subagent:

```
Agent(
    description="Research architectures for <repo_name>",
    prompt="""
Read and follow instructions from:
<SKILL_DIR>/subagents/architecture-researcher-prompt.md

scout_report: <full scout JSON>
clone_path: <scout.clone_path>
repo_name: <scout.repo_name>
kb_path: <SKILL_DIR>/knowledge-base
templates_path: <SKILL_DIR>/kb-templates
"""
)
```

**Deployment researcher** — one subagent:

```
Agent(
    description="Research deployment patterns for <repo_name>",
    prompt="""
Read and follow instructions from:
<SKILL_DIR>/subagents/deployment-researcher-prompt.md

scout_report: <full scout JSON>
clone_path: <scout.clone_path>
repo_name: <scout.repo_name>
kb_path: <SKILL_DIR>/knowledge-base
templates_path: <SKILL_DIR>/kb-templates
"""
)
```

6. Collect all subagent return values. Each returns JSON with a `files` array listing what it created/updated.

### Phase 3: Summary Generation

7. Aggregate the `files` arrays from all Phase 2 subagents into a single list of KB file paths.
8. Spawn **summary-generator subagents in parallel** — one per KB file:

```
Agent(
    description="Generate CoD summary for <file>",
    prompt="""
Read and follow instructions from:
<SKILL_DIR>/subagents/summary-generator-prompt.md

kb_file_path: <SKILL_DIR>/knowledge-base/<file>
"""
)
```

9. Collect results. Log any failures but do not block the report.

### Phase 4: Console Report

10. Print a structured report to the console:

```
# Knowledge Extraction Report

**Quickstart:** <repo_name>
**Repository:** <github-url>
**Clone Path:** <clone_path>

## Files Created
- components/<name>.md
- archetypes/<name>.md
- ...

## Files Updated (merged)
- components/<name>.md — added Approach B
- ...

## Patterns Discovered
- AI Pattern: <ai_pattern_hint>
- Deployment: <deployment_methods>
- Model Serving: <model_serving>

## Manual Review Items
- <any files where subagents flagged uncertainty>

## Summary Generation
- Succeeded: N files
- Failed: N files (list)
```

### Phase 5: Cleanup

11. Remove the cloned repository using `clone_path` from the scout's JSON output:

```bash
rm -rf <scout.clone_path>
```

## Guidelines

### DO
- Pass subagent prompts by file path — never read them into your own context
- Spawn all Phase 2 subagents in a single parallel batch
- Spawn all Phase 3 summary subagents in a single parallel batch
- Report every file created/updated in the console report
- Preserve existing KB files — merge, don't overwrite

### DON'T
- Don't read subagent prompt files (`subagents/*.md`) yourself
- Don't perform the research work inline — delegate to subagents
- Don't delete or overwrite existing KB files without merging
- Don't skip any phase — follow all phases in order

## Error Handling

- If scout fails to clone: report error and stop
- If a researcher subagent fails: log the failure, continue with other subagents, report in Phase 4
- If a summary subagent fails: retry once, then report failure in Phase 4
- Partial extraction is acceptable — document gaps in the report
- Always run Phase 5 cleanup, even if earlier phases had failures

## Subagent Boundaries

Each KB category answers a different question. Subagents stay in their lane:

| Researcher | Question | Owns | Does NOT own |
|---|---|---|---|
| Component | "What do I deploy?" | Individual component internals: source code, per-component Dockerfile, app configs, component-level Helm subchart settings | Cross-component wiring, deploy orchestration |
| Architecture | "What AI pattern?" | Inter-component data flow, prompt chains, AI pipeline structure | Individual component internals, how to install/operate |
| Deployment | "How do I build, deploy, operate?" | Cross-cutting deploy concerns: repo-level Helm structure, chart dependencies, Makefile, CI/CD, compose.yml, container build orchestration | Individual component source code, app configs, AI pattern logic |
| Archetype | "What RHOAI usage pattern?" | High-level pattern classification, when-to-use guidance | Technical details covered by the other three |
