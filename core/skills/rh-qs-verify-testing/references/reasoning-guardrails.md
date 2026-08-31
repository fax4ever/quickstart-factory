# Reasoning Guardrails for rh-qs-verify-testing

This document defines concern areas while auditing a quickstart against [testing-practices.md](./testing-practices.md). These are **not** a checklist and **not** extra rubric. The practices document remains the only bar.

## Purpose

The audit is easy to skew: extra criteria creep in, Kind and OpenShift get collapsed, or missing factory files get treated as product gaps. These guardrails keep the work inside the couple (this skill + the practices document).

## How to Use

1. Think freely while reading the tree
2. Periodically check: "Have I considered [concern area]?"
3. If not, reason about it explicitly
4. Skip concerns that do not apply

## Concern Areas

### 1. Rubric fidelity

**What to consider:**
- Every gap should map to a kind or rule already written in the practices document
- Tool or framework preference is not a gap
- Coverage percentages and test counts are not in the rubric

**Key questions:**
- Can I point at a section of `testing-practices.md` for this finding?
- Am I marking something missing just because I expected pytest, a named CI vendor, or a factory pipeline file?

**Where to look:**
- The practices document, especially "What this document is not" and "What complete means"

---

### 2. Applicability from the product

**What to consider:**
- Kinds apply because of what the quickstart *is*, not because a template listed them
- No UI, no model, not Kubernetes — those make kinds not applicable
- Absence of an inapplicable kind is not a gap

**Key questions:**
- Did I infer this kind from the tree, or from habit?
- If this part of the product does not exist, why would I require tests for it?

**Where to look:**
- The tree: deploy artifacts, services, model clients, UI packages
- The practices document "Applies when" lines and "Principles"

---

### 3. Kind is not OpenShift

**What to consider:**
- Kind E2E is reduced and mocked; OpenShift E2E is full and real
- One environment passing does not cover the other
- A Kind suite that needs real OpenShift APIs is not Kind E2E as defined
- An OpenShift suite that stubs the platform is not OpenShift E2E as defined

**Key questions:**
- Did this run stub or disable OpenShift-only pieces? Then it is Kind-shaped, even if someone labeled it e2e
- Did this run use the real platform and the user journey? Then it is OpenShift-shaped
- Am I reporting a single "E2E: present" line that hides the split?

**Where to look:**
- The practices document sections 4, 5, and "Kind versus OpenShift"
- Separate configs, jobs, or docs for the two environments

---

### 4. Functional proof vs quality proof

**What to consider:**
- Health, install, and "it responded" are not model-quality checks
- Quality kinds apply only when the product's value is model- or agent-shaped

**Key questions:**
- Does this check assert behavior of the model or agent, or only that a process is up?
- If there is no model-facing path, did I correctly mark quality as not applicable?

**Where to look:**
- The practices document section 6
- Test names and assertions, not just job titles containing "eval"

---

### 5. Independence of this couple

**What to consider:**
- This skill does not need other skills' outputs
- Missing design docs or pipeline manifests are not gaps in *testing strategy*
- The response is a report; it does not generate tests or CI and does not gate later work

**Key questions:**
- Am I about to refuse to audit because a factory file is missing?
- Am I about to write workflows or tests "to help"?
- Am I adding a finding that is really "they did not run another skill"?

**Where to look:**
- This skill's SKILL.md guidelines
- The tree as a product, not as a factory workspace

---

## Additional Concerns (Context-Specific)

### OpenShift E2E is infrequent
Infrequent full-cluster runs are allowed. The gap is when the strategy never defines full OpenShift E2E, or when the rare run is still a mocked subset.

### User asks to save a file
Only write a file if they ask. Same content as the conversation report. Do not create pipeline bookkeeping.

## Dynamic Reasoning Example

```
Reading the tree...
  ↓ Found: Helm chart, API package, no UI, calls a model endpoint

Question: "Which kinds apply?"
  ↓ Unit yes, integration likely, artifact checks yes,
    Kind E2E yes, OpenShift E2E yes, quality likely, UI tests N/A

Guardrail: Rubric fidelity — not requiring a named test runner ✓
Guardrail: Kind vs OpenShift — there is one "e2e" job; need to see if it mocks or not
  ↓ Job installs a reduced chart and stubs platform CRDs
  ↓ That is Kind E2E, not OpenShift E2E → OpenShift kind still a gap if nothing else exists

Guardrail: Independence — no design.md; continue from the tree ✓
```

## When to Stop Checking Guardrails

Once applicable kinds are classified, Kind/OpenShift are not collapsed, and every gap cites the practices document, stop. Do not add more bars.

## Self-Check Before Reporting

- [ ] Practices document was read this session
- [ ] Each finding maps to that document
- [ ] Inapplicable kinds are labeled N/A, not gaps
- [ ] Kind and OpenShift are separate lines when both apply
- [ ] No tests or CI were generated
- [ ] Report is the deliverable; nothing else is gated
