# Subagent Index

## Overview

The `qs-extract-knowledge` skill uses 6 subagent roles across 3 workflow phases. The main agent (SKILL.md) spawns subagents by passing their prompt file path — it never reads these files itself.

## Subagent Roles

| Name | Purpose | Input | Output | Phase | Why Subagent |
|------|---------|-------|--------|-------|-------------|
| `scout-prompt.md` | Clone repo, scan structure, identify components and metadata | `repo_url` | JSON: component list + metadata | Phase 1 | Isolates cloning and scanning from orchestration; returns structured data for dispatch |
| `component-researcher-prompt.md` | Deep-dive one component, write/merge KB file | `component_name`, `component_type`, `component_path`, `clone_path`, `repo_name`, `kb_path`, `templates_path` | JSON: `{files: [...], success: true}` | Phase 2 | One instance per component — parallelizable, focused context per component |
| `archetype-researcher-prompt.md` | Identify RHOAI usage pattern(s), write/merge KB files | `scout_report`, `clone_path`, `repo_name`, `kb_path`, `templates_path` | JSON: `{files: [...], success: true}` | Phase 2 | Separate concern from technical analysis; high-level pattern recognition |
| `architecture-researcher-prompt.md` | Analyze AI pattern and component wiring, write/merge KB files | `scout_report`, `clone_path`, `repo_name`, `kb_path`, `templates_path` | JSON: `{files: [...], success: true}` | Phase 2 | Owns inter-component data flow — distinct from per-component internals |
| `deployment-researcher-prompt.md` | Analyze deployment, CI/CD, build patterns, write/merge KB files | `scout_report`, `clone_path`, `repo_name`, `kb_path`, `templates_path` | JSON: `{files: [...], success: true}` | Phase 2 | Owns cross-cutting deploy concerns — aggressively splits into multiple files |
| `summary-generator-prompt.md` | Generate Chain of Density 4-sentence summary, edit into frontmatter | `kb_file_path` | JSON: `{file: "...", success: true}` | Phase 3 | One instance per KB file — parallelizable, focused CoD iteration |

## Parallelism Design

- **Phase 1:** Scout runs alone (must complete before Phase 2)
- **Phase 2:** ALL subagents run in parallel — no file conflicts because:
  - Component researchers write to `components/<name>.md` (distinct filenames per component)
  - Archetype researcher writes to `archetypes/` (different directory)
  - Architecture researcher writes to `architectures/` (different directory)
  - Deployment researcher writes to `deployment/` (different directory)
- **Phase 3:** ALL summary generators run in parallel — each edits a different file's frontmatter

## Shared Resources

All researcher subagents (Phase 2) read:
- `kb-templates/kb-schema.md` — frontmatter schema and merge rules
- Their category-specific body template from `kb-templates/`

Summary generators (Phase 3) read:
- The KB file they are summarizing (passed as `kb_file_path`)
