---
name: vendor-integration
description: "Quickstart integrating an ISV AI product with RHOAI model serving via operator or partner blueprint"
summary: "Demonstrates ISV AI product integration with RHOAI model serving via OLM-managed operators or Helm charts that wrap, proxy, or augment inference — e.g., F5 AI Guardrails deploys a Calypso AI Moderator proxy intercepting LlamaStack requests/responses for prompt injection, PII filtering, toxicity scanning, and topic enforcement, with a dual-panel Streamlit UI comparing guardrailed vs direct access and Red Team adversarial testing. Choose over rag-chatbot when the primary purpose is evaluating a vendor product (RAG app serves as demo workload being protected/enhanced), and over model-serving-app when wrapping KServe/vLLM with vendor capabilities (AI security, observability, specialized inference) not in the base RHOAI stack. Components span KServe + vLLM or LlamaStack model serving, operator-managed or Helm-deployed vendor backend, Streamlit/React/vendor demo UI, pgvector/Milvus data layer, private container registry credentials, vendor license keys, and multi-namespace deployment topology. Medium-to-high complexity because the vendor product adds its own deployment footprint (operators, namespaces, storage, GPU resources) on top of the base RHOAI workload, requiring coordination of OLM operator lifecycle with RHOAI model serving."
metadata:
  type: archetype
tags:
  tech_stack: [streamlit, llama-stack, postgresql, python]
  ai_pattern: [guardrails, model-serving, rag]
  platform: [rhoai, openshift, vllm, kserve]
  data_layer: [pgvector]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "F5 AI Guardrails (Calypso AI) operator integration with RHOAI -- OLM-managed operator deploys AI security proxy alongside a LlamaStack RAG workload for prompt/response policy enforcement"
    approach: "A"
---

# Vendor Integration

## Overview

A vendor integration quickstart demonstrates how to deploy and operate an ISV (Independent Software Vendor) AI product alongside Red Hat OpenShift AI model serving. The quickstart pairs a working RHOAI application workload (e.g., a RAG chatbot, model serving endpoint) with a partner product that extends the platform with capabilities not built into RHOAI itself -- such as AI-layer security, specialized inference blueprints, or enterprise document processing. On RHOAI, vendor integrations typically use OLM-managed operators or Helm-based deployment of partner components that wrap, proxy, or augment the model serving layer.

## Typical Components

- **Model serving:** KServe + vLLM or LlamaStack for RHOAI-native LLM inference
- **Backend:** Partner product backend (operator-managed or Helm-deployed) providing the vendor-specific capability
- **Frontend:** Demo UI showing the vendor product in action (Streamlit, React, or vendor-provided UI)
- **Data layer:** Application-specific (pgvector, Milvus, etc.) depending on the workload archetype
- **Supporting:** OLM operator or Helm chart for vendor product lifecycle management, private container registry credentials, vendor license keys

## When to Use

- **Business problem:** Evaluating or demonstrating a partner AI product on Red Hat OpenShift AI -- showing how the product integrates with RHOAI model serving, what operational requirements it introduces, and what value it adds to the platform
- **RHOAI capabilities:** Demonstrates RHOAI extensibility through ISV product integration, OLM operator lifecycle, multi-namespace deployment topology, and coexistence of vendor components with RHOAI model serving
- **Scale/complexity:** Medium to high complexity; the vendor product adds its own deployment footprint (operators, namespaces, storage, GPU resources) on top of the base RHOAI workload

## Example Quickstarts

| Quickstart | What It Demonstrates |
|------------|---------------------|
| f5-ai-guardrails | F5 AI Guardrails (Calypso AI) integration -- OLM-managed operator deploys Moderator proxy that intercepts model inference requests/responses for AI-layer content inspection (prompt injection, PII filtering, toxicity scanning, topic enforcement), with dual-panel Streamlit UI comparing guardrailed vs direct LlamaStack access and Calypso AI Red Team for adversarial testing |

## Decision Criteria

### vs rag-chatbot

Pick **vendor-integration** when the primary purpose is demonstrating or evaluating an ISV AI product on RHOAI, where the RAG chatbot (or other workload) serves as the demo application being protected or enhanced by the vendor product. Pick **rag-chatbot** when the primary purpose is building a document-grounded Q&A application and the focus is on the RAG pipeline architecture itself.

### vs model-serving-app

Pick **vendor-integration** when the quickstart wraps RHOAI model serving with a vendor product that adds capabilities (security, observability, specialized inference) not present in the base model serving stack. Pick **model-serving-app** when the focus is on deploying and configuring KServe/vLLM model endpoints without vendor-specific layers.
