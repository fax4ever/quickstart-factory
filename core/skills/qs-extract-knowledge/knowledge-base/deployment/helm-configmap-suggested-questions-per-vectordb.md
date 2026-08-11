---
name: helm-configmap-suggested-questions-per-vectordb
description: Helm ConfigMap storing per-vector-database suggested questions as JSON, injected into frontend via configMapKeyRef
summary: "Provides per-vector-database starter questions in a RAG Streamlit frontend by storing a suggestedQuestions map in Helm values.yaml, serialized to a ConfigMap, and injected as a JSON environment variable into the UI deployment. Use when the RAG frontend needs context-specific suggested questions varying by knowledge base -- single-approach pattern covering Helm (ConfigMap with configMapKeyRef), podman-compose (inline YAML env var), and Makefile dev-start (oc get configmap jsonpath extraction) deployment modes. The values.yaml suggestedQuestions map keys vector store identifiers (e.g., hr-vector-db-v1-0) to question arrays with five default categories (hr, legal, sales, procurement, techsupport) at 6 questions each; the ConfigMap template named via rag.fullname serializes with toJson and nindent 4, conditionally injecting RAG_QUESTION_SUGGESTIONS via configMapKeyRef guarded by {{- if .Values.suggestedQuestions }}. Vector store keys must exactly match vector_store_name in the ingestion pipeline config (hyphenated with version suffix), the frontend must parse RAG_QUESTION_SUGGESTIONS as JSON, omitting suggestedQuestions from values skips both ConfigMap creation and env var injection, and compose/Helm maintain slightly different question text independently."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, streamlit]
  ai_pattern: [rag]
  platform: [openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "ConfigMap with suggestedQuestions keyed by vector_store_name, rendered as JSON via toJson, injected into UI deployment as RAG_QUESTION_SUGGESTIONS env var via configMapKeyRef"
    approach: "A"
---

# Helm ConfigMap for Per-Vector-Database Suggested Questions

## Overview

This pattern stores UI-facing suggested questions in a Helm-managed ConfigMap, keyed by vector database identifier. The deployment template injects the ConfigMap value as a JSON-encoded environment variable, allowing the Streamlit frontend to display context-specific starter questions when a user selects a particular knowledge base.

## Pattern Description

The `values.yaml` defines a `suggestedQuestions` map where each key matches a vector store name (e.g., `hr-vector-db-v1-0`) and the value is a list of question strings. A dedicated ConfigMap template serializes this map to JSON using Helm's `toJson` function. The deployment template conditionally adds a `RAG_QUESTION_SUGGESTIONS` environment variable via `configMapKeyRef` when suggested questions are configured. The same data structure is replicated in `podman-compose.yml` as an inline YAML environment variable for local development.

## Implementation

### Values Configuration

Questions are grouped by vector store identifier in `values.yaml`:

```yaml
# deploy/helm/rag/values.yaml (lines 211-250)
suggestedQuestions:
  hr-vector-db-v1-0:
    - "What are the health insurance benefits offered?"
    - "How many vacation days do employees get?"
    - "What is the parental leave policy?"
  sales-vector-db-v1-0:
    - "What is the sales process?"
    - "How do I qualify leads?"
    - "What are the pricing strategies?"
  techsupport-vector-db-v1-0:
    - "How do I install CloudSync on Mac?"
    - "How do I troubleshoot CloudSync sync issues?"
```

### ConfigMap Template

The ConfigMap serializes the entire `suggestedQuestions` map to a single JSON string:

```yaml
# deploy/helm/rag/templates/configmap-suggested-questions.yaml
{{- if .Values.suggestedQuestions }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "rag.fullname" . }}-suggested-questions
  labels:
    {{- include "rag.labels" . | nindent 4 }}
data:
  RAG_QUESTION_SUGGESTIONS: |
    {{- .Values.suggestedQuestions | toJson | nindent 4 }}
{{- end }}
```

### Deployment Environment Variable Injection

The deployment template conditionally adds the env var from the ConfigMap:

```yaml
# deploy/helm/rag/templates/deployment.yaml (lines 55-61)
{{- if .Values.suggestedQuestions }}
- name: RAG_QUESTION_SUGGESTIONS
  valueFrom:
    configMapKeyRef:
      name: {{ include "rag.fullname" . }}-suggested-questions
      key: RAG_QUESTION_SUGGESTIONS
{{- end }}
```

### Local Dev Equivalent

The same data structure is inlined in the compose file as a YAML multiline environment variable:

```yaml
# deploy/local/podman-compose.yml (rag-ui environment, lines 72-114)
environment:
  RAG_QUESTION_SUGGESTIONS: |
    {
      "hr-vector-db-v1-0": [
        "What benefits does FantaCo provide?",
        "How many vacation days do employees get?"
      ],
      "sales-vector-db-v1-0": [
        "What is the sales process?",
        "How do I qualify leads?"
      ]
    }
```

### Makefile Dev-Start ConfigMap Extraction

The Makefile `dev-start` target extracts the ConfigMap value for local Streamlit use:

```makefile
# deploy/helm/Makefile (dev-start target, lines 399-410)
SUGGESTED_QUESTIONS_JSON=$$(oc get configmap \
    "$(RAG_CHART)-suggested-questions" -n $(NAMESPACE) \
    -o jsonpath='{.data.RAG_QUESTION_SUGGESTIONS}' 2>/dev/null || true); \
cd $(FRONTEND_DIR) && \
LLAMA_STACK_ENDPOINT=http://localhost:$(LLAMASTACK_LOCAL_PORT) \
RAG_QUESTION_SUGGESTIONS="$$SUGGESTED_QUESTIONS_JSON" \
bash start.sh
```

## Configuration

- **Key settings:** `suggestedQuestions` map in `values.yaml` keyed by vector store identifier; each key maps to a list of question strings
- **Defaults:** Five vector store categories preconfigured (hr, legal, sales, procurement, techsupport) with 6 questions each
- **Dependencies:** Frontend must parse `RAG_QUESTION_SUGGESTIONS` as JSON to display per-database questions

## Gotchas

- The vector store key format uses hyphens and version suffix (e.g., `hr-vector-db-v1-0`) which must match the `vector_store_name` field in the ingestion pipeline configuration (`values.yaml` lines 259-323)
- The `toJson` template function produces a single-line JSON string; the `nindent 4` ensures it is properly indented in the ConfigMap YAML
- The ConfigMap is conditionally rendered (`{{- if .Values.suggestedQuestions }}`); if the key is omitted from values, no ConfigMap is created and the env var is not injected
- The compose file and the Helm values have slightly different question text for the same databases (compose uses "What benefits does FantaCo provide?" while Helm uses "What are the health insurance benefits offered?") -- these are maintained independently

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the umbrella chart this ConfigMap is part of
