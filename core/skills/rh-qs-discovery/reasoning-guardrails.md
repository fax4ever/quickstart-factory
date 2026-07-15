# Reasoning Guardrails for rh-qs-discovery

This document defines the concern areas that should be investigated during quickstart discovery and PRD generation. These are **not** a checklist to mechanically fill out, but a mental framework to ensure critical aspects aren't overlooked while reasoning dynamically.

## Purpose

When interviewing a user about a new quickstart idea, questions should emerge organically from the conversation. However, certain concerns are easy to miss — especially when the user is enthusiastic and the idea sounds exciting. These guardrails ensure the PRD accurately captures the user's intent without adding, assuming, or pre-deciding things they didn't ask for.

## How to Use

As you reason about the quickstart idea and draft the PRD:
1. Think freely — let questions emerge naturally from the conversation
2. Periodically check: "Have I considered [concern area]?"
3. If not yet addressed, reason about it explicitly
4. Don't force irrelevant concerns — not every idea triggers every guardrail

## Concern Areas

### 1. Scope Creep

**What to consider:**
- Requirements the user explicitly stated vs ones you inferred
- Features that sound useful but weren't requested
- Complexity escalation — a simple request becoming an enterprise system
- Adding "nice to have" features as if they were requirements

**Key questions:**
- Did the user actually ask for this, or am I adding it?
- Would removing this feature change the user's stated problem?
- Am I designing for a scale the user didn't mention?
- Is this requirement in the user's words, or in mine?

**Where to look:**
- The user's original input (exact words matter)
- PRD sections you've drafted — do they go beyond the conversation?
- Technology choices — are you picking complex stacks for simple problems?
- The requirement mapping — did you map to more components than the idea needs?

---

### 2. Technology Bias

**What to consider:**
- Defaulting to RAG when a simpler approach (classification, rules engine) suffices
- Assuming a UI is needed when API-only would work
- Choosing Llama Stack or specific frameworks before understanding the use case
- Recommending technologies because they're familiar, not because they fit
- Assuming on-cluster model serving when a remote endpoint would work

**Key questions:**
- Am I recommending this technology because it fits the problem, or because it's what I know?
- Has the user expressed a preference for any technology?
- Is there a simpler technology choice that would solve the same problem?
- Am I adding infrastructure components (MinIO, Redis, message queues) without a stated need?

**Where to look:**
- The AI touchpoints section — does the chosen capability match the stated problem?
- The requirement mapping table — did the mapping pull in more components than necessary?
- User's actual stated needs vs the concrete requirements you derived

---

### 3. GPU Assumptions

**What to consider:**
- Not every quickstart needs GPU — many AI tasks run fine on CPU
- Small models (7B, 8B) can run on a single GPU or even CPU for demos
- Inference can be remote (API endpoint) rather than on-cluster
- The user may not have GPU access or budget
- Batch processing may not need dedicated GPU resources

**Key questions:**
- Does the AI capability actually require on-cluster GPU?
- Could a smaller model or remote endpoint work for this use case?
- Has the user mentioned GPU availability or constraints?
- Am I assuming GPU because "it's an AI quickstart" rather than because the use case demands it?

**Where to look:**
- AI touchpoints section — what models and capabilities are specified?
- Deploy target — did the user mention GPU?
- Model requirements — size constraints, latency needs, throughput expectations

---

### 4. Completeness Without Over-specification

**What to consider:**
- The PRD should define the problem and constraints, not the solution
- Enough detail for `rh-qs-architect` to make informed decisions, without constraining those decisions
- Implementation details (specific API endpoints, database schemas, UI component trees) belong in architecture, not discovery
- All required PRD sections must have substantive content — but "substantive" means useful information, not padding

**Key questions:**
- Am I specifying implementation details that belong in the architecture phase?
- Are all required PRD sections filled with substantive content (not filler)?
- Would an architect reading this PRD have enough context to design the system?
- Am I leaving appropriate room for architectural decisions, or pre-deciding the design?

**Where to look:**
- Each PRD section — is the content at the right level of abstraction?
- Gaps flagged by the prd-structurer subagent — are they real gaps or things that belong in architecture?
- The boundary between "constraints" (discovery) and "design decisions" (architecture)

---

### 5. User Voice Fidelity

**What to consider:**
- Paraphrasing that subtly changes meaning
- Interpreting ambiguity as certainty — the user said "maybe" but you wrote "must"
- Losing nuance from uploaded documents when extracting structured sections
- Replacing the user's domain language with generic tech jargon
- Resolving open questions without the user's input

**Key questions:**
- Does my PRD draft reflect what the user said, or what I think they meant?
- Have I flagged ambiguities as open questions rather than resolving them myself?
- Am I preserving the user's terminology, or replacing it with my own?
- If the user read this PRD, would they recognize their own idea?

**Where to look:**
- Original user input vs drafted PRD sections — compare side by side
- Open questions section — are genuinely unresolved items listed there?
- The prd-structurer output — were confidence levels respected, or did you treat "low" confidence content as certain?

---

## Additional Concerns (Context-Specific)

### Gap Analysis Mode
- Don't let trend-chasing override practical viability — a trendy technology doesn't mean it makes a good quickstart
- Proposed quickstarts should fill genuine coverage gaps, not just pad the backlog
- Consider implementation complexity when proposing new ideas — a gap exists for a reason if it requires unavailable infrastructure

### Uploaded Documents
- Don't treat every detail in an uploaded document as a requirement — some content is background context
- Distinguish between what the document describes (existing system) and what the user wants to build (new quickstart)
- Design docs often include aspirational features — confirm which ones are in scope

---

## Dynamic Reasoning Example

```
Analyzing user input: "I want to build a quickstart that helps developers
search through API documentation using natural language."
  ↓ Idea: Natural language search over API docs

Question emerges: "What AI capability is central here?"
  ↓ RAG seems like a fit — user wants to search documents
  ↓ But could semantic search without generation work?
  ↓ Need to ask user: do they want answers or just relevant doc sections?

Guardrail check: "Have I considered technology bias?" ✓
  → I almost defaulted to RAG. Semantic search might suffice.
  → Added to remaining questions.

Guardrail check: "Have I considered scope creep?" ✓
  → User said "developers" — not building for multiple personas.
  → User said "API documentation" — not general documents.
  → Keep scope tight.

Guardrail check: "Have I considered GPU assumptions?" ✓
  → Embedding models for search are small, may not need GPU.
  → If generation is needed, could use a remote endpoint.
  → Added GPU question to interview plan.

Question emerges: "Does this need a UI?"
  ↓ Developers might prefer CLI or API integration
  ↓ Don't assume web UI — ask.

Guardrail check: "Have I considered user voice fidelity?" ✓
  → User said "search" not "chat" — keeping that distinction.

Continue reasoning...
```

## When to Stop Checking Guardrails

Once you've reasoned about all applicable concerns:
- Concerns that don't apply to this quickstart can be skipped (e.g., GPU assumptions for a pure classification quickstart using a small model)
- If a concern was implicitly handled during the conversation, that counts
- Don't force concerns that are truly irrelevant — a gap analysis doesn't need user voice fidelity checks

## Self-Check Before Generating PRD

Before writing the final PRD to `data/prds/<slug>.md`, quickly verify:
- [ ] All relevant guardrails considered
- [ ] PRD content traces to user input (not invented)
- [ ] Ambiguities listed as open questions, not silently resolved
- [ ] Technology choices reflect user needs, not defaults
- [ ] GPU determination is evidence-based

If any guardrail feels unaddressed, reason about it explicitly before proceeding.
