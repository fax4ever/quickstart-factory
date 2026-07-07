# Deployment KB File Body Template

Use this structure for all files in `knowledge-base/deployment/`. Each file describes one deployment concern — a specific aspect of how quickstarts are built, deployed, and operated on RHOAI/OpenShift.

## Body Structure

```markdown
# <Deployment Pattern Name>

## Overview
<2-3 sentences: what deployment concern this covers, why it matters for RHOAI quickstarts.>

## Pattern Description
<Explain the pattern in detail: what it does, how it works, what problem it solves.>

## Implementation

### <Implementation Aspect>
<Description with a short code/YAML snippet showing the pattern.>

```yaml
# 5-15 lines showing the key configuration
```

<Repeat for each distinct aspect of this deployment pattern.>

## Configuration
- **Key settings:** <list critical configuration knobs>
- **Defaults:** <what the defaults are and when to change them>
- **Dependencies:** <what must be in place before this pattern works>

## Gotchas
- <Gotcha 1: deployment issue and its solution>
- <Gotcha 2: ...>

## Related Patterns
- <Links to related deployment KB files>
```

## Guidelines

- **Aggressively split** deployment knowledge into separate files per distinct concern
- Each file should cover ONE thing well: Helm subchart wiring, Makefile targets, CI/CD pipeline, container build pattern, security contexts, etc.
- Capture what's **unique** about this quickstart's usage of a pattern — even if many quickstarts share Helm subcharts, note what's different here
- **Stick to facts** from the repo — don't imagine ideal patterns or recommend changes
- Include actual snippets from Helm templates, Makefiles, CI configs, docker-compose files
- This builds a rich, wide KB over many extractions — breadth is more valuable than depth per file
