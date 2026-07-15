# Reasoning Guardrails for qs-extract-knowledge

This document defines the concern areas that should be investigated during knowledge extraction from AI Quickstart repositories. These are **not** a checklist to mechanically fill out, but a mental framework to ensure critical aspects aren't overlooked while reasoning dynamically.

## Purpose

When extracting reusable patterns from quickstart repos, questions should emerge organically from analysis. However, certain concerns are easy to miss without explicit attention. These guardrails ensure comprehensive, accurate knowledge extraction.

## How to Use

As you reason about extraction results:
1. Think freely — let questions emerge naturally from analysis
2. Periodically check: "Have I considered [concern area]?"
3. If not yet addressed, reason about it explicitly
4. Don't force irrelevant concerns

## Concern Areas

### 1. No Proprietary Data in KB Files
**What to consider:**
- API keys, tokens, passwords, or credentials appearing in code snippets
- Internal hostnames, IP addresses, or org-specific URLs
- Proprietary model names or endpoints that shouldn't be shared
- Customer or user data visible in example configs

**Key questions:**
- Do any extracted snippets contain hardcoded secrets?
- Are internal infrastructure details leaking into KB files?
- Would publishing this KB file expose anything sensitive?

**Where to look:**
- Environment variable definitions in docker-compose, Helm values
- ConfigMap and Secret references in Kubernetes manifests
- README sections with setup instructions

---

### 2. Deduplication Before Creating
**What to consider:**
- Whether a KB file for this component/pattern already exists
- Whether the pattern is genuinely different or a superficial variation
- Whether merging (adding Approach B) is better than creating a new file

**Key questions:**
- Does a file with a similar name or covering the same tech already exist in the KB?
- Is this implementation fundamentally different from the existing approach, or just different config values?
- Would an engineer following the existing approach need different guidance for this quickstart?

**Where to look:**
- Existing files in `knowledge-base/` subdirectories
- The `source_examples` section of existing KB files
- Existing approach descriptions to compare patterns

---

### 3. Preserve KB Structure
**What to consider:**
- Category boundaries: components vs architectures vs deployment vs archetypes
- File naming conventions (kebab-case, descriptive)
- Frontmatter schema compliance (all required fields present)
- Body structure matching the category template

**Key questions:**
- Is this knowledge in the right category? (Use the boundary table in SKILL.md)
- Does the frontmatter match `kb-schema.md`?
- Does the body follow the category template?

**Where to look:**
- `kb-templates/kb-schema.md` for frontmatter rules
- `kb-templates/<category>.md` for body structure
- Existing KB files for naming patterns

---

### 4. Validate Frontmatter
**What to consider:**
- All required fields present: name, description, metadata.type, tags, source_examples
- Tags use consistent vocabulary (check existing files for conventions)
- `source_examples` correctly links to the quickstart being analyzed
- `approach` field is set correctly (A for new, B/C for additional approaches)

**Key questions:**
- Are all required frontmatter fields present and correctly typed?
- Do the tags accurately reflect the technology and patterns?
- Is the source_examples entry complete with repo URL and notes?

**Where to look:**
- `kb-templates/kb-schema.md` for the canonical schema
- Existing KB files for tag vocabulary

---

### 5. Factual Accuracy
**What to consider:**
- Snippets match the actual repo code (not imagined or hallucinated)
- Technology names and versions are correct
- Configuration values reflect what the repo actually uses
- Deployment patterns described are actually present in the repo

**Key questions:**
- Did I verify this pattern exists in the repo, or am I inferring it?
- Are the code snippets copied from actual files, or reconstructed from memory?
- Do the described gotchas come from real issues in the repo?
- Could I point to a specific file, line, comment, doc, or commit message in the repo that supports this claim? If not, I must remove it.

**Where to look:**
- The cloned repo itself — verify claims by reading actual files
- README.md for project description accuracy
- Commit messages for gotchas and known issues

---

### 6. Appropriate Splitting Granularity
**What to consider:**
- Components should be atomic (one per file)
- Deployment patterns should be split by distinct concern
- Architecture files should represent genuine AI patterns, not component lists
- Archetypes should be broad usage categories, not per-quickstart

**Key questions:**
- Am I lumping unrelated concerns into one file?
- Am I splitting too fine — creating files that would never be useful standalone?
- Does each file answer one clear question an engineer would ask?

**Where to look:**
- The category boundary table in SKILL.md
- Existing KB files for granularity examples

---

### 7. Merge Quality
**What to consider:**
- When adding Approach B, does it genuinely differ from Approach A?
- Is the "Choosing Between Approaches" guidance clear and actionable?
- Are source_examples correctly tagged with approach letters?
- Is the existing content preserved during merge?

**Key questions:**
- Would an engineer read both approaches and understand when to pick each?
- Did I preserve all existing content, or accidentally overwrite something?
- Is the approach label (A, B, C) consistent with the source_examples?

**Where to look:**
- The existing KB file content before merging
- `kb-templates/kb-schema.md` merge rules

## Additional Concerns (Context-Specific)

### Shared Helm Subcharts (ai-architecture-charts)
- Several newer quickstarts use the `ai-architecture-charts` shared subchart library
- When extracting deployment patterns, note whether the quickstart uses shared subcharts or standalone Helm
- This affects how deployment KB files should be structured

### Notebook-Only Quickstarts
- Some quickstarts are Jupyter notebooks with no deployment infrastructure
- The scout should detect this and the extraction should focus on architecture patterns rather than deployment

## Dynamic Reasoning Example

```
Analyzing RAG quickstart...
  ↓ Found: FastAPI backend with pgvector integration

Question emerges: "Is this a new component or does pgvector already exist in KB?"
  ↓ Check knowledge-base/components/ for pgvector files
  ↓ Answer: pgvector.md exists with Approach A from another quickstart

Guardrail check: "Have I considered deduplication?" ✓ Yes, need to compare approaches
Guardrail check: "Have I considered factual accuracy?" ✓ Will verify snippets from repo

Question emerges: "Is this pgvector usage fundamentally different?"
  ↓ Existing: standalone StatefulSet with pgvector extension
  ↓ This repo: pgvector as Helm subchart with ai-architecture-charts
  ↓ Decision: Different approach — add Approach B

Continue reasoning...
```

## When to Stop Checking Guardrails

Once you've reasoned about all applicable concerns:
- Concerns that don't apply to this quickstart can be skipped
- If a concern was implicitly handled during reasoning, that counts
- Don't force concerns that are truly irrelevant

## Self-Check Before Completing Extraction

Before printing the Phase 4 console report, quickly verify:
- [ ] All relevant guardrails considered
- [ ] No proprietary data in any KB file
- [ ] No duplicate KB files created (existing ones merged instead)
- [ ] Frontmatter schema validated on all files
- [ ] Code snippets verified against actual repo content
