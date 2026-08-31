---
name: rh-qs-verify-testing
description: >
  Validate that a Red Hat AI quickstart has a correct and complete testing
  strategy, using this skill's testing-practices reference as the only rubric.
  Reusable on any quickstart. Reports gaps; does not generate tests or CI.
allowed-tools: Read, Grep, Glob, Write
---

# rh-qs-verify-testing

**Category:** `testing/`

## Goal

Report whether a quickstart's testing strategy matches [references/testing-practices.md](./references/testing-practices.md). That file is the **only** bar. This skill does not invent extra criteria, generate tests, generate CI, or block any other work.

## Input

- A quickstart tree: a path the user names, or the workspace they are already in
- Nothing else is required. Missing design docs, pipeline files, or prior skill output is normal — inspect the product as it sits on disk

## Supporting Documents

**Main agent reads directly:**

| File | When |
|------|------|
| [references/testing-practices.md](./references/testing-practices.md) | Always, before judging anything — this is the entire rubric |
| [references/reasoning-guardrails.md](./references/reasoning-guardrails.md) | While classifying applicable kinds and writing the report |

There are no subagents. Do not load other skills' files as part of this work.

## Workflow

### 1. Read the rubric

Read `references/testing-practices.md` in full. Do not start the audit from memory. Every later judgment must trace to a section in that file.

### 2. Identify the tree

Use the path the user gave. If they did not give one, use the current workspace if it looks like a product repo (application code, deploy artifacts, or tests). If it is unclear which tree to inspect, ask once and wait.

### 3. See what the product is

From the tree, decide **applicability** the way the practices document requires: what parts exist (logic, collaborating services, deploy artifacts, Kubernetes install, OpenShift as the real target, model- or agent-facing path, UI). Do not require a design document for this. Infer from what is in the repo.

### 4. Inventory evidence

For each test kind in the practices document, look for executable checks and a way to run them (tests, scripts, jobs, documented commands). Note Kind vs OpenShift split when both could apply. Record what you found and where — paths, not vibes.

### 5. Compare to the rubric

For each kind:

- **Applicable and present** — evidence matches the kind (especially reduced+mocked Kind vs full OpenShift)
- **Applicable and missing** — a gap
- **Not applicable** — say why, from the product, in the practices document's terms

Do not fail the audit because a particular framework or CI vendor is absent. Do not treat Kind success as OpenShift coverage. Do not treat a health check as model-quality coverage.

### 6. Report

Tell the user, in the conversation:

- Which tree was inspected
- For each kind in the practices document: applicable or not, present or gap, evidence paths or reason for N/A
- Whether Kind and OpenShift are distinguished when both apply
- A short list of gaps only (no remediation plan that generates tests or CI)

Do not write a file unless the user asks for one. If they do, write a markdown report they name, containing the same content.

This skill ends when the report is delivered. It does not start other work and does not stop other work.

## Guidelines

**DO**

- Treat `references/testing-practices.md` as the only rubric
- Derive applicability from the product on disk
- Quote or paraphrase the practices document when calling something a gap
- Keep Kind (reduced, mocked) and OpenShift (full) separate in the report

**DO NOT**

- Generate tests, fixtures, workflows, or Makefile targets
- Read or require output from other skills
- Add criteria that are not in the practices document
- Treat a missing inapplicable kind as a gap
- Claim OpenShift is covered because Kind passed, or the reverse
- Block, gate, or sequence any other skill

## Success

The user has a report they can review, grounded only in the practices document and the tree you inspected.
