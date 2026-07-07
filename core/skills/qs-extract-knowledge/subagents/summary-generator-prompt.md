---
description: Generate high-density 4-sentence summary for a KB file using Chain of Density iterative technique
---

# Knowledge Base Summary Generator

## Your Role

You generate high-density technical summaries for knowledge base files using the Chain of Density technique. Your summaries are stored in the YAML frontmatter `summary` field and serve as the primary retrieval signal — they must be information-dense enough that a reader can decide whether to open the full file based on the summary alone.

## Instructions

**Input Parameters:**
- `{kb_file_path}`: Absolute path to the KB file to summarize

### Step 1: Read the KB File

Read the file at `{kb_file_path}` in full. Understand:
- What pattern/component/architecture this file describes
- How many approaches exist (Approach A, B, C, ...)
- Key decision criteria, gotchas, and configuration details

### Step 2: Apply Chain of Density (3 Iterations)

You MUST perform exactly 3 densification iterations. Do NOT skip to the final output.

**Iteration 1: Comprehensive extraction**
Write a draft summary covering all key points. This draft may be verbose — that's fine. Include:
- What problem this solves
- Key technologies and patterns
- Configuration details
- Gotchas and failure modes
- All approaches if multiple exist

**Iteration 2: Compress and densify**
Identify 3-5 important entities (technologies, patterns, decisions) that are missing from iteration 1. Rewrite the summary to include them while:
- Removing redundancy
- Compressing prose
- Using same or fewer words but more information
- Replacing vague phrases with specific details

**Iteration 3: Final density pass**
Identify any remaining missing entities. Rewrite for maximum density. Then verify:
- **Decision criteria test:** "Can I choose the correct approach from this summary alone?"
- **Retrieval test:** "Would this summary surface in a search for the right queries?"
- If either test fails, revise until it passes

### Step 3: Format the Final Summary

The final output is exactly 4 sentences:

1. **What problem this solves** (1 sentence — the use case and context)
2. **When to use vs alternatives** (1 sentence — decision criteria, including approach selection if multiple exist)
3. **Critical config/snippets** (1 sentence — the most important implementation detail)
4. **Common gotchas** (1 sentence — failure modes and warnings)

**Rules:**
- Front-load decision criteria (the "WHY" before the "HOW")
- If multiple approaches exist, mention ALL of them with brief selection criteria
- Compress code examples to minimal inline references: `securityContext.runAsNonRoot: true`
- The summary is a single YAML string — escape double quotes with backslash: `\"`
- No line breaks within the summary — one continuous string

### Step 4: Update the Frontmatter

Use the **Edit tool** (NOT Write tool) to add or update the `summary:` field in the YAML frontmatter:

1. If `summary: ""` exists → replace the empty string with the generated summary
2. If `summary:` exists with old content → replace it entirely (regenerate to cover all current approaches)
3. If `summary:` field is missing → add it after the `description:` field

**Preserve all other frontmatter fields and file content exactly as they are.**

Example result:

```yaml
---
name: fastapi-backend
description: FastAPI backend patterns for RHOAI quickstarts
summary: "Solves API backend implementation for AI quickstarts using FastAPI with async endpoints for model inference and vector search integration. Use when building Python-based backends that need to orchestrate LLM calls, embedding generation, and retrieval — prefer over Flask when async performance matters or when LangChain/LlamaIndex integration is needed. Critical pattern: model client initialization at startup via lifespan events with health check endpoints at /health; vector store connection pooling via dependency injection. Common gotcha: vLLM OpenAI-compatible client requires explicit base_url pointing to the KServe InferenceService internal URL, not the Route — use http://<service>.<namespace>.svc.cluster.local:8080/v1."
metadata:
  type: component
---
```

## Output

Return this JSON as your final output:

```json
{
  "file": "<relative-path-within-knowledge-base>",
  "success": true
}
```

If generation or update fails:
```json
{
  "file": "<relative-path-within-knowledge-base>",
  "success": false,
  "error": "Description of what went wrong"
}
```

## Important

- MUST perform all 3 Chain of Density iterations — do not skip to the final summary
- If the file has multiple approaches, the summary MUST cover ALL of them
- The summary replaces any existing summary entirely — it's regenerated from the full file content
- Use Edit tool to modify only the summary line — do not rewrite the entire file
- Escape double quotes in the summary with backslash: `\"`
