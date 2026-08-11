---
name: model-serving-app
description: "Deploys and serves AI models via KServe/vLLM with optional orchestration layers, no custom app backend"
summary: "Deploys and serves AI models on RHOAI via KServe InferenceServices with vLLM ServingRuntimes in RawDeployment mode, focusing on model deployment, inference configuration, GPU resource management, and optional multi-model orchestration via TrustyAI GuardrailsOrchestrator. Choose over rag-chatbot when no vector database or retrieval pipeline is needed, over agentic-app when no agent framework (LangGraph, LlamaStack, CrewAI) manages tool dispatch or multi-step reasoning, and over vendor-integration when all components are RHOAI-native (KServe, vLLM, TrustyAI); Approach A suits Jupyter-based interactive testing while Approach B suits production-ready chatbot applications with guardrail monitoring. Approach A coordinates safety detector KServe InferenceServices (gibberish, prompt injection, HAP, regex PII) around vLLM-served Llama 3.2 3B Instruct with OCI modelcar storage and Jupyter workbench; Approach B adds FastAPI backend with HTML/JS chat UI (SSE streaming, OpenShift Route with HAProxy timeout annotations), R Shiny dashboard with Prometheus metrics (per-detector, per-direction) and ServiceMonitor, MinIO + HuggingFace Hub init container for detector models, Lingua language detector, gRPC sentence chunker, CPU/GPU-configurable detectors via Helm values, client-side regex pre-filtering in 13 languages, ConfigMap-mounted system prompt, and BYO model support via conditional `model.endpoint`/`model.port` Helm values. Do not use when the app requires a persistent data store, custom backend business logic beyond guardrail proxying, document retrieval pipelines, agent-based tool dispatch, or ISV product integration -- this archetype covers RHOAI-native model serving infrastructure without an application layer (Approach A) or with a thin guardrail-proxying application layer (Approach B)."
metadata:
  type: archetype
tags:
  tech_stack: [jupyter, python, fastapi, r-shiny]
  ai_pattern: [model-serving, guardrails]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Multi-model KServe deployment with TrustyAI GuardrailsOrchestrator coordinating safety detectors (gibberish, prompt injection, hate/profanity, regex PII) around a vLLM-served Llama 3.2 3B Instruct model"
    approach: "A"
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Customer service chatbot with TrustyAI GuardrailsOrchestrator (HAP, prompt injection, language detection, regex competitor blocking), custom FastAPI backend with chat UI and Prometheus metrics, and R Shiny monitoring dashboard for real-time guardrail visualization"
    approach: "B"
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
| lemonade-stand-assistant | Customer service chatbot (FastAPI + HTML/JS chat UI) with TrustyAI GuardrailsOrchestrator coordinating HAP, prompt injection, language detection, and regex competitor blocking detectors around vLLM-served Llama 3.2 3B Instruct, with R Shiny monitoring dashboard for real-time guardrail metrics |

## Decision Criteria

### vs rag-chatbot

Pick **model-serving-app** when the focus is on deploying and exposing model endpoints without a retrieval pipeline or vector database. Pick **rag-chatbot** when the application needs to ground LLM responses in user documents via vector search and includes an ingestion pipeline.

### vs agentic-app

Pick **model-serving-app** when there is no agent orchestration layer managing tool dispatch, multi-step reasoning, or conversation state on top of the served models. Pick **agentic-app** when the application wraps model serving with an agent framework (LangGraph, LlamaStack, CrewAI) for tool use and multi-turn reasoning.

### vs vendor-integration

Pick **model-serving-app** when all components are RHOAI-native (KServe, vLLM, TrustyAI) and the quickstart demonstrates platform capabilities rather than an ISV product. Pick **vendor-integration** when the primary purpose is demonstrating a partner product (F5, NVIDIA) integrated with RHOAI model serving.

---

## Approach B: Guardrailed Chatbot Application with Monitoring (from lemonade-stand-assistant)

### When to Use

When the model serving and guardrails pattern needs a complete application layer -- a user-facing chat UI, server-side request handling, and a monitoring dashboard for guardrail metrics -- rather than just deploying model endpoints for ad-hoc testing via Jupyter.

### Differences from Approach A

- **Custom backend:** Approach B includes a FastAPI application (`lemonade-stand-app/app_fastapi.py`) that serves a browser-based chat UI, proxies user messages to the GuardrailsOrchestrator, handles SSE streaming responses, and collects guardrail detection metrics; Approach A has no backend and uses a Jupyter workbench for interactive testing
- **Chat UI:** Approach B serves a single-page HTML/JS chat interface directly from FastAPI with SSE streaming, example question buttons, and per-detector color-coded error messages (`error-hap`, `error-language`, `error-prompt-injection`, `error-regex` CSS classes in inline HTML); Approach A uses Jupyter notebook cells
- **Monitoring dashboard:** Approach B deploys an R Shiny dashboard (`shiny-dashboard/app.R`) that polls the FastAPI `/metrics` endpoint every second for real-time visualization of total requests, input/output blocks, approved requests, and per-detector detection breakdowns; Approach A has no monitoring
- **Prometheus metrics:** Approach B exposes Prometheus-format metrics via `/metrics` endpoint (`AsyncMetricsCollector` class) tracking `guardrail_requests_total`, `guardrail_detections_total` (per-detector, per-direction), `guardrail_detections_by_detector`, and `guardrail_detections_by_direction`, consumed by both the R Shiny dashboard and an OpenShift `ServiceMonitor` (`chart/templates/lemonade-stand-app.yaml`); Approach A has no metrics collection
- **Client-side regex pre-filtering:** Approach B performs local regex matching on competitor fruit names in 13 languages (English, Turkish, Swedish, Finnish, Dutch, French, Spanish, German, Japanese, Russian, Italian, Polish, Chinese, Hindi) before sending requests to the orchestrator (`check_regex_locally()` in `app_fastapi.py`), reducing orchestrator load; Approach A relies entirely on the orchestrator for all detection
- **Input length validation:** Approach B enforces a 100-character input limit (`MAX_INPUT_CHARS = 100`) at the application layer before orchestrator routing
- **Detector deployment flexibility:** Approach B configures HAP and prompt injection detector resources via Helm values (`detectors.hap.useGpu`, `detectors.promptInjection.useGpu` in `chart/values.yaml`) defaulting to CPU; the `guardrails-detector-huggingface-runtime` image runs detectors via uvicorn with 4 workers
- **Detector models:** Approach B uses granite-guardian-hap-125m for HAP detection and deberta-v3-base-prompt-injection-v2 for prompt injection, both served via KServe InferenceService with `guardrails-detector-huggingface` model format; Approach A uses similar detector services (gibberish, prompt injection, HAP, regex PII)
- **Lingua language detector:** Approach B includes Lingua (`chart/templates/lingua.yaml`) as a standalone Deployment (not KServe-managed) for language detection, enforcing English-only interactions; Approach A does not include language detection
- **Chunker service:** Approach B deploys a standalone sentence chunker service (`chart/templates/chunker.yaml`, port 8085 gRPC) used by the orchestrator to split text into sentences before passing to detectors; the orchestrator config (`fms-orchestr8-config-nlp`) references this chunker for all detector types via `chunker_id: sentence`
- **Model storage:** Approach B uses a MinIO instance (`chart/templates/minio-storage-models.yaml`) with an init container that downloads detector models from HuggingFace Hub at startup, then serves them via S3 protocol to KServe; the LLM uses OCI modelcar (`oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct`); Approach A uses OCI modelcar for all models
- **System prompt via ConfigMap:** Approach B mounts the system prompt as a ConfigMap volume (`lemonade-stand-system-prompt`) at `/system-prompt/prompt`, allowing prompt changes without image rebuilds
- **GuardrailsOrchestrator CR:** Approach B uses `enableBuiltInDetectors: true` on the GuardrailsOrchestrator CR (`chart/templates/guardrails-orchestrator.yaml`) and `enableGuardrailsGateway: false`
- **OpenShift Route:** Approach B exposes the chat UI via OpenShift Route with HAProxy annotations for SSE compatibility (`haproxy.router.openshift.io/timeout: 300s`, `haproxy.router.openshift.io/timeout-tunnel: 300s`)
- **BYO model support:** Approach B supports connecting to an external model endpoint via `model.endpoint` and `model.port` Helm values instead of deploying its own LLM (the LLM templates are conditionally rendered: `{{ if not .Values.model }}` in `chart/templates/llm-llama32.yaml`)

### Typical Components

- **Model serving:** KServe InferenceService with vLLM ServingRuntime for LLM inference (Llama 3.2 3B Instruct via OCI modelcar), KServe InferenceServices with `guardrails-detector-huggingface-runtime` for HAP and prompt injection detectors (CPU or GPU configurable)
- **Backend:** FastAPI application (`lemonade-stand-app/`) serving chat UI, proxying to GuardrailsOrchestrator, collecting Prometheus metrics, and performing client-side regex pre-filtering
- **Frontend:** Single-page HTML/JS chat interface served by FastAPI, with SSE streaming and per-detector color-coded error messages
- **Data layer:** None -- no persistent data store required
- **Supporting:** TrustyAI GuardrailsOrchestrator CR coordinating detectors; MinIO for detector model storage (HuggingFace Hub download via init container); Lingua language detector (standalone Deployment); sentence chunker service (gRPC); R Shiny monitoring dashboard consuming Prometheus metrics; ConfigMap-mounted system prompt; OpenShift ServiceMonitor for cluster-level metrics collection

---

## Choosing Between Approaches

| Criteria | Approach A (Jupyter-Based Testing) | Approach B (Chatbot Application with Monitoring) |
|----------|-----------------------------------|------------------------------------------------|
| User interface | Jupyter Notebook workbench | Browser-based HTML/JS chat UI with SSE streaming |
| Backend | None (direct orchestrator interaction) | FastAPI proxy to GuardrailsOrchestrator |
| Monitoring | None | R Shiny dashboard with real-time guardrail metrics |
| Metrics | None | Prometheus-format metrics (per-detector, per-direction) with ServiceMonitor |
| Detectors | Gibberish, prompt injection, HAP, regex PII | HAP, prompt injection, language detection (Lingua), regex competitor blocking |
| Detector hosting | KServe InferenceServices | KServe InferenceServices (CPU/GPU configurable via Helm values) + Lingua standalone Deployment |
| Client-side filtering | None | Regex pre-filtering for competitor fruit names in 13 languages before orchestrator |
| Model storage | OCI modelcar for all models | MinIO + HuggingFace Hub init container for detectors, OCI modelcar for LLM |
| BYO model | Not documented | Supported via `model.endpoint` and `model.port` Helm values |
| System prompt | Not configurable | ConfigMap-mounted, changeable without image rebuild |
| Best for | Interactive model serving exploration and demo via notebook | Production-ready customer-facing chatbot with guardrail monitoring |
