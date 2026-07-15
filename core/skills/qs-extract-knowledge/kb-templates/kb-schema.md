# Knowledge Base Schema

Single source of truth for KB file frontmatter format, merge rules, naming conventions, and content depth guidelines. All researcher subagents reference this file.

## Frontmatter Schema

Every KB file uses this YAML frontmatter structure:

```yaml
---
name: <kebab-case-name>
description: <one-line description for retrieval — max 120 chars>
summary: "<4-sentence CoD summary — added by summary-generator, leave empty on creation>"
metadata:
  type: <component|archetype|architecture|deployment-pattern>
tags:
  tech_stack: [fastapi, react, postgresql, ...]
  ai_pattern: [rag, agents, guardrails, fine-tuning, ...]
  platform: [kserve, vllm, rhoai, openshift, ...]
  data_layer: [pgvector, milvus, redis, elasticsearch, ...]
source_examples:
  - quickstart: "<quickstart-repo-name>"
    repo: "https://github.com/rh-ai-quickstart/<name>"
    notes: "<what pattern this quickstart demonstrates>"
    approach: "A"
---
```

### Required Fields

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | Yes | Kebab-case, matches filename without `.md` |
| `description` | string | Yes | One line, max 120 chars |
| `summary` | string | No | Added by summary-generator in Phase 3. Leave as empty string `""` on creation |
| `metadata.type` | enum | Yes | One of: `component`, `archetype`, `architecture`, `deployment-pattern` |
| `tags` | object | Yes | At least `tech_stack` populated. Other tag keys optional but encouraged |
| `source_examples` | array | Yes | At least one entry linking to the quickstart being analyzed |

### Tag Vocabularies

Tags are **extensible** — add new keys and values when you encounter patterns not covered here. These are starting vocabularies, not exhaustive lists.

**tech_stack:** fastapi, flask, django, react, patternfly, angular, vue, postgresql, redis, minio, nginx, langchain, llama-index, haystack, gradio, streamlit, jupyter, python, nodejs, golang

**ai_pattern:** rag, agents, guardrails, fine-tuning, model-serving, embeddings, vector-search, prompt-chaining, evaluation, data-pipeline, multimodal

**platform:** kserve, vllm, tgi, rhoai, openshift, kubernetes, caikit, openvino, triton

**data_layer:** pgvector, milvus, qdrant, weaviate, elasticsearch, redis, chromadb, faiss

## File Naming Conventions

### By Category

| Category | Directory | Naming Pattern | Examples |
|----------|-----------|----------------|----------|
| Component | `components/` | `<tech-name>.md` or `<tech-role>.md` | `fastapi-backend.md`, `pgvector.md`, `kserve-vllm.md` |
| Archetype | `archetypes/` | `<pattern-name>.md` | `model-serving-app.md`, `rag-chatbot.md`, `agentic-app.md` |
| Architecture | `architectures/` | `<ai-pattern>.md` | `rag-pipeline.md`, `guardrails-layer.md`, `agent-orchestration.md` |
| Deployment | `deployment/` | `<concern-name>.md` | `helm-subchart-wiring.md`, `makefile-targets.md`, `github-actions-ci.md` |

### Rules
- Always kebab-case
- Descriptive but concise (2-4 words)
- No quickstart-specific names in filenames — files represent reusable patterns, not individual repos
- If unsure about naming, prefer the technology name (e.g., `pgvector.md` not `vector-database.md`)

## Source Examples Format

Each entry in `source_examples` links a KB file to the quickstart(s) that contributed knowledge:

```yaml
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "FastAPI backend with pgvector for document retrieval"
    approach: "A"
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "FastAPI backend with Redis caching layer"
    approach: "B"
```

- `quickstart`: Repo name (matches the GitHub repo name)
- `repo`: Full GitHub URL
- `notes`: One line explaining what this quickstart demonstrates for this pattern
- `approach`: Letter label (`A`, `B`, `C`, ...) matching the approach section in the body

## Merge Rules

When a KB file already exists, follow these rules:

### When to Add a New Approach (Approach B, C, ...)

Add a new approach when the implementation is **fundamentally different** in a way that requires different guidance:
- Different deployment architecture (StatefulSet vs Deployment vs DaemonSet)
- Different security model (restricted SCC vs anyuid)
- Different resource lifecycle (PVC vs emptyDir)
- Different integration method (Helm subchart vs standalone chart vs docker-compose)

### When to Update source_examples Only

Update `source_examples` (adding a new entry with the same approach letter) when:
- Same pattern with different config values
- Same architecture with different resource quantities
- Minor version differences
- Different naming conventions but same structure

### Merge Procedure

1. Read the existing KB file in full
2. Compare the new pattern against each existing approach
3. If fundamentally different → add new approach section and new `source_examples` entry
4. If same pattern → add new `source_examples` entry with existing approach letter
5. Update tags if the new quickstart introduces new tech/patterns
6. **Never overwrite existing content** — only append or update tags/source_examples

### Approach Section Structure (for Approach B+)

When adding a new approach to an existing file, append after the last approach:

```markdown
---

## Approach B: <Descriptive Name> (from <quickstart-name>)

### When to Use
<When this approach is preferred over Approach A>

### Differences from Approach A
<Key differences in deployment, config, or architecture>

### <Category-specific sections from the body template>
...

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| <decision factor> | <A's answer> | <B's answer> |
```

## Content Depth Guidelines

KB files should capture **principles + gotchas + short important snippets**, not full code dumps.

### DO Include
- Key YAML/config snippets that show the pattern (5-15 lines each)
- Specific configuration values that are non-obvious or RHOAI-specific
- Gotchas extracted from actual repo code, comments, docs, or commit history — never from general knowledge of the technology
- Decision criteria for when to use this pattern

### DON'T Include
- Full file contents (link to source instead)
- Boilerplate that any engineer would know
- Speculative patterns not present in the repo
- Internal implementation details that change frequently
