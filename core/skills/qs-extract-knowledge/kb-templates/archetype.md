# Archetype KB File Body Template

Use this structure for all files in `knowledge-base/archetypes/`. Each file describes an RHOAI usage pattern — a high-level category of quickstart that answers "what kind of app is this?"

## Body Structure

```markdown
# <Archetype Name>

## Overview
<2-3 sentences: what this archetype represents, what class of problems it solves, how it leverages RHOAI.>

## Typical Components
- **Model serving:** <e.g., KServe + vLLM, standalone inference API>
- **Backend:** <e.g., FastAPI, Flask, LangChain-based>
- **Frontend:** <e.g., React/PatternFly, Gradio, Streamlit, none>
- **Data layer:** <e.g., pgvector, Milvus, Redis>
- **Supporting:** <e.g., MinIO for object storage, Prometheus for metrics>

## When to Use
<Clear guidance on when this archetype is the right choice. Include:>
- What business problem it solves
- What RHOAI capabilities it demonstrates
- What scale/complexity it targets

## Example Quickstarts
| Quickstart | What It Demonstrates |
|------------|---------------------|
| <name> | <one-line description of how it exemplifies this archetype> |

## Decision Criteria

### vs <Other Archetype>
<When to pick this archetype over the alternative. Focus on the distinguishing factor.>

### vs <Another Archetype>
<Repeat for each relevant comparison.>
```

## Guidelines

- Archetypes are **broad categories**, not per-quickstart descriptions
- A good archetype should apply to 3+ quickstarts (current or future)
- Focus on the RHOAI usage pattern, not the specific technology stack
- Decision criteria should help an engineer pick the right archetype before choosing components
- When a quickstart spans two archetypes, it contributes to both files
