---
name: model-serving-app
description: "Deploys and serves AI models via KServe/vLLM with optional orchestration layers, no custom app backend"
summary: "Deploys and serves AI models on RHOAI via KServe InferenceServices with vLLM ServingRuntimes in RawDeployment mode, without a custom application backend (no FastAPI/Flask), focusing on model deployment, inference configuration, GPU resource management, and optional multi-model orchestration via TrustyAI GuardrailsOrchestrator. Choose over rag-chatbot when no vector database or retrieval pipeline is needed, over agentic-app when no agent framework (LangGraph, LlamaStack, CrewAI) manages tool dispatch or multi-step reasoning, and over vendor-integration when all components are RHOAI-native (KServe, vLLM, TrustyAI); suits low-to-medium complexity. Critical architecture: KServe model endpoints with optional GuardrailsOrchestrator coordinating specialized safety detector services (gibberish, prompt injection, hate/profanity, regex PII), ConfigMaps for orchestrator routing, OCI modelcar artifacts or PVCs for model storage, and Jupyter workbench for interactive testing. Do not use when the app requires a persistent data store, custom backend business logic, document retrieval pipelines, agent-based tool dispatch, or ISV product integration -- this archetype covers only RHOAI-native model serving infrastructure without an application layer."
metadata:
  type: archetype
tags:
  tech_stack: [jupyter, python]
  ai_pattern: [model-serving, guardrails]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Multi-model KServe deployment with TrustyAI GuardrailsOrchestrator coordinating safety detectors (gibberish, prompt injection, hate/profanity, regex PII) around a vLLM-served Llama 3.2 3B Instruct model"
    approach: "A"
---

# Model Serving App

## Overview

A model serving app deploys one or more AI models on Red Hat OpenShift AI via KServe InferenceServices and exposes them for inference, optionally with orchestration layers that coordinate between models. Unlike RAG chatbots or agentic apps, there is no custom application backend (FastAPI, Flask) managing business logic -- the architecture is primarily composed of KServe-managed model endpoints, ServingRuntimes, and optional model-to-model orchestration. On RHOAI, this pattern demonstrates model deployment, inference configuration, and platform-native orchestration features.

## Typical Components

- **Model serving:** KServe InferenceService with vLLM ServingRuntime for LLM inference, potentially additional specialized model endpoints for classification or detection tasks
- **Backend:** None (model endpoints serve directly) or a platform-native orchestrator (e.g., TrustyAI GuardrailsOrchestrator) that routes and coordinates between model services
- **Frontend:** Jupyter Notebook workbench for interactive demo and testing, or no frontend at all
- **Data layer:** None required -- models serve inference directly without a persistent data store
- **Supporting:** ConfigMaps for orchestrator routing configuration, model storage via OCI modelcar artifacts or PVCs

## When to Use

- **Business problem:** Deploying AI models for inference on RHOAI where the primary value is the model serving infrastructure itself -- model configuration, multi-model coordination, safety checks, or inference optimization -- rather than a full application stack built on top of the models
- **RHOAI capabilities:** Demonstrates KServe InferenceService and ServingRuntime configuration, RawDeployment mode, model-to-model orchestration via TrustyAI GuardrailsOrchestrator, GPU resource management, and Jupyter workbench integration for interactive testing
- **Scale/complexity:** Low to medium complexity; suitable when the focus is on getting models deployed and serving correctly on RHOAI without building a full application around them

## Example Quickstarts

| Quickstart | What It Demonstrates |
|------------|---------------------|
| guardrailing-llms | Multi-model deployment with TrustyAI GuardrailsOrchestrator coordinating four safety detector services (gibberish, prompt injection, hate/profanity, regex PII) around a vLLM-served Llama 3.2 3B Instruct model, with a Jupyter workbench for interactive healthcare demo |

## Decision Criteria

### vs rag-chatbot

Pick **model-serving-app** when the focus is on deploying and exposing model endpoints without a retrieval pipeline or vector database. Pick **rag-chatbot** when the application needs to ground LLM responses in user documents via vector search and includes an ingestion pipeline.

### vs agentic-app

Pick **model-serving-app** when there is no agent orchestration layer managing tool dispatch, multi-step reasoning, or conversation state on top of the served models. Pick **agentic-app** when the application wraps model serving with an agent framework (LangGraph, LlamaStack, CrewAI) for tool use and multi-turn reasoning.

### vs vendor-integration

Pick **model-serving-app** when all components are RHOAI-native (KServe, vLLM, TrustyAI) and the quickstart demonstrates platform capabilities rather than an ISV product. Pick **vendor-integration** when the primary purpose is demonstrating a partner product (F5, NVIDIA) integrated with RHOAI model serving.
