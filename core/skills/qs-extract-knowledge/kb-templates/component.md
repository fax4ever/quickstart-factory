# Component KB File Body Template

Use this structure for all files in `knowledge-base/components/`. Each file describes one deployable component (service, database, model server, frontend, etc.) and how it is used in AI Quickstarts on RHOAI.

## Body Structure

```markdown
# <Component Name>

## Overview
<2-3 sentences: what this component is, its role in quickstart architectures, why it matters for RHOAI.>

## Tech Stack & Dependencies
- **Runtime:** <language/framework version>
- **Container image:** <image reference>
- **Key dependencies:** <list critical libraries or services this depends on>
- **Helm subchart:** <if applicable, which chart and version>

## Key Patterns

### <Pattern Name>
<Description of the pattern with a short code/YAML snippet showing the essential config.>

```yaml
# Example: 5-15 lines showing the key pattern
```

<Repeat for each distinct pattern found in this component.>

## Configuration
- **Environment variables:** <list RHOAI-relevant env vars with purpose>
- **Config files:** <list key config files and what they control>
- **Helm values:** <list key values.yaml overrides>

## Known Gotchas
- <Gotcha 1: concrete problem and its solution>
- <Gotcha 2: ...>

## Testing Notes
- <How to verify this component works on RHOAI>
- <What to check after deployment>

## Related Patterns
- <Links to related architecture or deployment KB files>
```

## Guidelines

- Focus on what makes this component's usage **specific to AI Quickstarts on RHOAI** — skip generic knowledge any engineer would know
- Include actual snippets from the repo, not reconstructed examples
- If the component uses shared Helm subcharts (ai-architecture-charts), note this explicitly
- Keep snippets short (5-15 lines) — show the pattern, not the whole file
