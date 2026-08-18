---
name: model-serving-app
description: "Deploys and serves AI models via KServe/vLLM with optional orchestration layers, no custom app backend"
summary: "Deploys and serves AI models on RHOAI via KServe InferenceServices with vLLM ServingRuntimes (RawDeployment or Standard/Knative mode) or LLMInferenceService with vLLM/llm-d for MaaS, optionally coordinating multi-model safety detection through TrustyAI GuardrailsOrchestrator or multi-tenant governed access through MaaS subscriptions, without requiring a full custom application backend or persistent data store. Choose over rag-chatbot when no vector DB or retrieval pipeline is needed, over agentic-app when no agent framework (LangGraph, LlamaStack, CrewAI) manages tool dispatch, and over vendor-integration when all components are RHOAI-native; Approach A suits Jupyter-based GPU testing with GuardrailsOrchestrator coordinating four detectors (gibberish, prompt injection, HAP, regex PII) around Llama 3.2 3B Instruct with OCI modelcar, Approach B adds production chatbot with FastAPI + HTML/JS SSE chat UI (HAProxy Route timeout 300s), R Shiny Prometheus dashboard (per-detector/per-direction via ServiceMonitor), MinIO + HuggingFace Hub init container for detector models, Lingua language detector, gRPC sentence chunker, regex pre-filtering in 13 languages, 100-char input limit, ConfigMap system prompt, `enableBuiltInDetectors: true`, and BYO model via conditional Helm rendering (`{{ if not .Values.model }}`), Approach C runs CPU-only TinyLlama-1.1B via `vllm-cpu-rhel9` (Intel AVX512 preferred) in Knative mode with AnythingLLM workbench (SQLite sidecar API key provisioning + init Job workspace creation), Llama Stack Distribution playground with inline Milvus RAG and `llama-stack-client` Job for HR document seeding, and tool calling (`--enable-auto-tool-choice --tool-call-parser hermes`), and Approach D provides MaaS-governed multi-tenant serving of NVIDIA Nemotron-3-Nano-30B-A3B FP8 via LLMInferenceService with vLLM/llm-d, Kuadrant rate-limited MaaSSubscription CRs with per-group token limits, Keycloak SSO with MaaSAuthPolicy, DevSpaces + Continue.dev IDE with coding exercises, Perses observability dashboards via COO, TelemetryPolicy for per-subscription usage attribution (model, user, subscription, organization_id, cost_center), Istio Telemetry for per-subscription request duration metrics, HardwareProfile-based GPU allocation, two-phase Helm deployment installing 9 OLM operators, and `all-in-one.sh` with cluster auto-detection. Critical config: A/B use RawDeployment with OCI modelcar while C uses `serving.kserve.io/deploymentMode: Standard` with `VLLM_CPU_KVCACHE_SPACE` for CPU KV-cache tuning and `maxModelLen: 2048`; B exposes Routes with `haproxy.router.openshift.io/timeout: 300s` for SSE and configures detector GPU/CPU via `detectors.hap.useGpu`/`detectors.promptInjection.useGpu` Helm values; D uses `serving.kserve.io/v1alpha1 LLMInferenceService` routed through MaaS default Gateway with `DataScienceCluster` kserve.modelsAsService.managementState: Managed and tool calling via `--tool-call-parser=qwen3_coder` with custom `nano_v3` reasoning parser. Gotchas: Approach C requires OpenShift Service Mesh and Serverless for Knative deployment (not needed by A/B RawDeployment), the vLLM CPU image is Intel-compiled (suggest m6i.4xlarge equivalent), Approach D spans multiple namespaces (llm, models-as-a-service, openshift-ingress, keycloak, maas-db, per-user wksp-<user>) with a `job-restart-kuadrant` workaround for intermittent Kuadrant misbehavior, and do not use this archetype when the app requires persistent data stores, custom business logic beyond guardrail proxying, document retrieval pipelines, agent-based tool dispatch, or ISV product integration."
metadata:
  type: archetype
tags:
  tech_stack: [jupyter, python, fastapi, r-shiny, anythingllm, llama-stack, devspaces, continue-dev, keycloak, perses, cloudnative-pg]
  ai_pattern: [model-serving, guardrails, maas]
  platform: [kserve, vllm, rhoai, openshift, kuadrant, llm-d]
  data_layer: [milvus, postgresql]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Multi-model KServe deployment with TrustyAI GuardrailsOrchestrator coordinating safety detectors (gibberish, prompt injection, hate/profanity, regex PII) around a vLLM-served Llama 3.2 3B Instruct model"
    approach: "A"
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Customer service chatbot with TrustyAI GuardrailsOrchestrator (HAP, prompt injection, language detection, regex competitor blocking), custom FastAPI backend with chat UI and Prometheus metrics, and R Shiny monitoring dashboard for real-time guardrail visualization"
    approach: "B"
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "CPU-only vLLM serving of TinyLlama-1.1B via KServe ServingRuntime with OCI modelcar storage, AnythingLLM workbench for chat, and Llama Stack Distribution playground with inline Milvus RAG and HR document seeding"
    approach: "C"
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "MaaS-governed multi-tenant model serving of NVIDIA Nemotron-3-Nano-30B-A3B via LLMInferenceService with vLLM/llm-d, Kuadrant rate-limited subscriptions, Keycloak authentication, DevSpaces + Continue.dev IDE as consumer, Perses observability dashboards, and per-subscription usage attribution for chargeback"
    approach: "D"
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
| llm-cpu-serving | CPU-only vLLM serving TinyLlama-1.1B via dedicated CPU ServingRuntime (no GPU required), with AnythingLLM workbench for chat and Llama Stack Distribution playground with inline Milvus RAG and HR document seeding |
| maas-code-assistant | MaaS-governed multi-tenant model serving of NVIDIA Nemotron-3-Nano-30B-A3B via LLMInferenceService with vLLM/llm-d, per-group rate-limited subscriptions via Kuadrant, Keycloak SSO, DevSpaces + Continue.dev IDE as the developer consumer, Perses observability dashboards, and per-subscription telemetry for usage attribution and chargeback |

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

## Approach C: CPU-Only Lightweight Serving with AnythingLLM Workbench (from llm-cpu-serving)

### When to Use

When the deployment target has no GPU available or GPU is not necessary, and the goal is to quickly spin up a minimal vLLM instance serving a small model (e.g., TinyLlama 1.1B) on CPU with an out-of-the-box chat interface (AnythingLLM) and an optional Llama Stack Distribution playground with inline RAG capabilities -- no custom backend code or guardrails orchestration required.

### Differences from Approach A

- **Hardware requirements:** Approach A requires GPU resources for vLLM-served LLM and multiple detector models; Approach C requires CPU only (minimum 2 cores / 4Gi memory, recommended 32 cores / 64Gi memory) with no GPU (`README.md`)
- **vLLM runtime:** Approach A uses the standard GPU-based vLLM ServingRuntime; Approach C uses a dedicated CPU-optimized vLLM image (`registry.redhat.io/rhaii/vllm-cpu-rhel9`) with `VLLM_CPU_KVCACHE_SPACE` environment variable for CPU KV-cache tuning (`helm/templates/servingruntime.yaml`)
- **Deployment mode:** Approach A uses RawDeployment mode for KServe InferenceServices; Approach C uses Standard (Knative) deployment mode with `serving.kserve.io/deploymentMode: Standard` and `networking.knative.dev/visibility: cluster-local` labels (`helm/templates/inferenceservice.yaml`)
- **Model size and packaging:** Approach A serves Llama 3.2 3B Instruct; Approach C serves TinyLlama-1.1B-Chat-v1.0 via OCI modelcar image (`oci://quay.io/rh-aiservices-bu/tinyllama:1.0`) with `maxModelLen: 2048` and `maxOutputTokens: 512` (`helm/values.yaml`)
- **Orchestration:** Approach A uses TrustyAI GuardrailsOrchestrator for multi-model coordination; Approach C has no orchestration layer -- the model serves directly
- **Frontend:** Approach A uses Jupyter Notebook workbench for interactive testing; Approach C uses AnythingLLM deployed as a Kubeflow Notebook workbench (`kubeflow.org/v1 Notebook` CR in `helm/templates/workbench.yaml`) with a SQLite sidecar (`keinos/sqlite3:latest`) that auto-provisions an API key (`sk-automation-workspace-setup`) for workspace automation
- **Playground layer:** Approach C includes a Llama Stack Distribution CR (`llamastack.io/v1alpha1 LlamaStackDistribution` in `helm/templates/playground.yaml`) providing a separate playground with remote vLLM inference provider, inline Milvus vector storage (`inline::milvus` with SQLite-backed `milvus.db`), inline sentence-transformers embeddings (`ibm-granite/granite-embedding-125m-english`), and file-search tool runtime; this is absent in Approach A
- **RAG capability:** Approach C includes a Kubernetes Job (`helm/templates/rag-seed-job.yaml`) that seeds HR policy documents from URLs into the Llama Stack vector store using `llama-stack-client` -- the Job fetches web content, strips HTML, and indexes into a per-user vector store (hashed username from namespace RoleBindings); Approach A has no RAG capability
- **Document seeding for AnythingLLM:** Approach C includes a curl-based init Job (`helm/templates/init_job.yaml`) that creates an AnythingLLM workspace named "Assistant to the HR Representative", sets a domain-specific system prompt for financial services HR advisory, and uploads seed documents
- **Tool calling:** Approach C enables vLLM tool calling with `--enable-auto-tool-choice` and `--tool-call-parser hermes` args on the ServingRuntime (`helm/templates/servingruntime.yaml`), enabling function calling even on a small CPU model
- **Intel CPU optimization:** Approach C notes the vLLM CPU image is compiled for Intel CPUs (preferably with AVX512 for compressed models) per `README.md`, suggesting AWS m6i.4xlarge equivalent instances
- **RHOAI software dependencies:** Approach C requires Red Hat OpenShift Service Mesh and Red Hat OpenShift Serverless for KServe Standard deployment mode (`README.md`); Approach A does not require these since it uses RawDeployment mode

### Typical Components

- **Model serving:** KServe InferenceService with CPU-optimized vLLM ServingRuntime (`vllm-cpu`) serving TinyLlama-1.1B-Chat via OCI modelcar storage, Standard (Knative) deployment mode, no GPU required
- **Backend:** None -- model endpoint serves directly via KServe, AnythingLLM connects to vLLM OpenAI-compatible API
- **Frontend:** AnythingLLM deployed as a Kubeflow Notebook workbench with workspace auto-provisioning (SQLite sidecar for API key setup, curl-based init Job for workspace creation, HR-focused system prompt configuration, and seed document upload)
- **Data layer:** Inline Milvus (SQLite-backed `milvus.db`) within Llama Stack Distribution for vector storage of seeded documents
- **Supporting:** Llama Stack Distribution CR (`LlamaStackDistribution`) as optional playground layer with remote vLLM inference provider, inline sentence-transformers embedding (`ibm-granite/granite-embedding-125m-english`), inline Milvus vector_io, file-search tool runtime, and MCP tool protocol support; Kubernetes Job (`rag-seed-job`) for seeding HR documents from URLs into the vector store using `llama-stack-client`; ConfigMap-based Llama Stack configuration (`llama-stack-config`)

---

## Approach D: MaaS-Governed Multi-Tenant Model Serving with Developer IDE (from maas-code-assistant)

### When to Use

When the goal is centralized, governed model serving for developer teams -- providing rate-limited, subscription-based access to an LLM via Red Hat AI's Models-as-a-Service (MaaS) offering, with Keycloak-based authentication, per-subscription usage attribution and chargeback telemetry, and developers consuming the model through an IDE (OpenShift DevSpaces + Continue.dev) rather than a custom UI or notebook.

### Differences from Approach A

- **Model serving API:** Approach A uses KServe `InferenceService` (serving.kserve.io/v1beta1) with vLLM; Approach D uses `LLMInferenceService` (serving.kserve.io/v1alpha1) with vLLM/llm-d, which is part of the RHOAI MaaS stack and integrates with the MaaS gateway router (`router.gateway.refs` referencing `maas-default-gateway` in `openshift-ingress`) for centralized ingress and governance (`charts/maas-code-assistant/templates/models/llminferenceservice.yaml`)
- **Multi-tenant governance:** Approach A has no access governance; Approach D deploys a full MaaS governance layer -- `MaaSSubscription` CRs define per-group token rate limits (e.g., admin: 100,000 tokens/1min, user: 50,000 tokens/1min in `charts/maas-code-assistant/values.yaml`), `MaaSAuthPolicy` CRs restrict model access by group membership (`charts/maas-code-assistant/templates/maasauthpolicy.yaml`), and `MaaSModelRef` CRs register models with the MaaS system (`charts/maas-code-assistant/templates/models/maasmodelref.yaml`)
- **Rate limiting:** Approach D uses Kuadrant (Red Hat Connectivity Link, `rhcl-operator` v1.3.4) for token-level rate limiting enforced at the gateway layer; the `MaaSSubscription` CR's `tokenRateLimits` field specifies per-model, per-subscription limits with configurable time windows (`charts/maas-code-assistant/templates/maassubscription.yaml`); Approach A has no rate limiting
- **Usage attribution and chargeback:** Approach D deploys a Kuadrant `TelemetryPolicy` (extensions.kuadrant.io/v1alpha1) that extracts `model`, `user`, `subscription`, `organization_id`, and `cost_center` from response body and auth identity metadata for per-subscription usage attribution (`charts/maas-code-assistant/templates/telemetrypolicy.yaml`), plus an Istio `Telemetry` resource that upserts a `subscription` label on `REQUEST_DURATION` metrics from the `x-maas-subscription` request header (`charts/maas-code-assistant/templates/telemetry.yaml`); Approach A has no usage attribution
- **Authentication:** Approach A has no authentication layer; Approach D deploys Red Hat Build of Keycloak (RHBK, operator `rhbk-operator` stable-v26.4) with a `sso` realm, configurable admin/user credentials, optional `kubeadmin` removal, and OpenShift OAuth integration via the `ocp-idp` client (`charts/maas-code-assistant/charts/keycloak/values.yaml`); users are pre-provisioned (user1-user5 by default) with group-based subscription assignment
- **User interface:** Approach A uses Jupyter Notebook workbench for interactive testing; Approach D uses OpenShift DevSpaces (`CheCluster` CR in `charts/maas-code-assistant/templates/devspaces/checluster.yaml`) with per-user `DevWorkspace` CRs (`workspace.devfile.io/v1alpha2` in `charts/maas-code-assistant/templates/workspace/devworkspace.yaml`) that provision IDE instances with the Continue.dev AI coding extension pre-configured to connect to the MaaS model endpoint; workspaces clone the quickstart repo's `coding-exercises/` (rock-paper-scissors, quiz, word-scramble Python games) for hands-on AI-assisted coding demos
- **Model:** Approach A serves Llama 3.2 3B Instruct; Approach D serves NVIDIA Nemotron-3-Nano-30B-A3B FP8 (`oci://quay.io/jharmison/models:redhatai--nvidia-nemotron-3-nano-30b-a3b-fp8-modelcar`), a 30B-parameter hybrid Mamba-Transformer MoE model with 256k-token context window, requiring 1 GPU with minimum 48GB VRAM (tested on AWS g6e.2xlarge with L40S) per `README.md`
- **Tool calling:** Approach D enables vLLM tool calling with `--enable-auto-tool-choice` and `--tool-call-parser=qwen3_coder` plus a custom reasoning parser (`--reasoning-parser-plugin=/mnt/models/nano_v3_reasoning_parser.py --reasoning-parser=nano_v3`) on the LLMInferenceService (`charts/maas-code-assistant/values.yaml`); Approach A does not document tool calling support
- **Hardware profiles:** Approach D uses RHOAI `HardwareProfile` CRs (`infrastructure.opendatahub.io/v1` in `charts/maas-code-assistant/templates/hardwareprofile.yaml`) to define GPU resource allocations with configurable CPU, memory, and accelerator limits and scheduling policies (Node or Kueue-based); Approach A has no HardwareProfile integration
- **Observability:** Approach A has no observability; Approach D enables the Cluster Observability Operator (v1.4.0) with Perses dashboards embedded in the OpenShift AI console, User Workload Monitoring with Prometheus retention (168h cluster, 72h user) and PVC-backed storage, and OpenTelemetry for distributed tracing -- the `OdhDashboardConfig` is patched via a post-install Helm hook Job to enable `genAiStudio`, `modelAsService`, `maasAuthPolicies`, and `observabilityDashboard` features (`charts/maas-code-assistant/templates/job-patch-odhdashboardconfig.yaml`)
- **Database:** Approach A has no database; Approach D deploys PostgreSQL via CloudNative-PG operator (`cloudnative-pg`, certified-operators catalog) for MaaS backend storage (`postgresCluster.name: maas` in `charts/dependency-operators/values.yaml`) and optionally for Keycloak persistence
- **Deployment model:** Approach A deploys a single chart; Approach D uses a two-phase Helm deployment -- first `dependency-operators` chart installs 9 OLM operators (DevSpaces, cert-manager, LWS, RHOAI stable-3.4, RHCL, CloudNative-PG, RHBK, COO, OpenTelemetry) and creates the `DataScienceCluster` with `kserve.modelsAsService.managementState: Managed`, then the `maas-code-assistant` chart deploys the model, MaaS governance, workspaces, and observability -- orchestrated by `all-in-one.sh` which auto-detects cluster configuration (ingress domain, certificates, existing operators, monitoring config, Gateway API route mode)
- **Namespace topology:** Approach A deploys in a single namespace; Approach D spans multiple namespaces -- `llm` for model serving, `models-as-a-service` for MaaS subscriptions and auth policies, `openshift-ingress` for MaaS gateway and telemetry policies, `openshift-devspaces` for CheCluster, per-user `wksp-<user>` namespaces for DevWorkspaces, `keycloak` for RHBK, `maas-db` for CloudNative-PG PostgreSQL, `kuadrant-system` for RHCL, plus operator namespaces
- **Kuadrant workaround:** Approach D includes an optional post-install Helm hook Job (`job-restart-kuadrant`) that restarts Kuadrant deployments to work around intermittent misbehavior, controlled by `kuadrant.restart` flag (`charts/maas-code-assistant/templates/job-restart-kuadrant.yaml`)

### Typical Components

- **Model serving:** LLMInferenceService (`serving.kserve.io/v1alpha1`) with vLLM/llm-d serving NVIDIA Nemotron-3-Nano-30B-A3B FP8 via OCI modelcar storage, routed through the MaaS default Gateway in `openshift-ingress`, with HardwareProfile-based GPU resource allocation and tool calling enabled (`--enable-auto-tool-choice --tool-call-parser=qwen3_coder`)
- **Backend:** None -- model endpoint serves directly via MaaS gateway; MaaS governance resources (MaaSSubscription, MaaSAuthPolicy, MaaSModelRef, TelemetryPolicy) provide the governance layer
- **Frontend:** OpenShift DevSpaces (CheCluster CR) with per-user DevWorkspace CRs provisioning IDE instances; Continue.dev AI coding extension connects to the MaaS model endpoint; coding exercises (Python games) as demo content
- **Data layer:** PostgreSQL via CloudNative-PG for MaaS backend storage; optionally PostgreSQL for Keycloak persistence
- **Supporting:** Red Hat Build of Keycloak (RHBK) for SSO authentication and user management with OpenShift OAuth integration; Kuadrant (RHCL) for per-subscription token rate limiting at the gateway layer; TelemetryPolicy for per-subscription usage attribution (model, user, subscription, organization_id, cost_center); Istio Telemetry for per-subscription request duration metrics; Cluster Observability Operator with Perses dashboards embedded in OpenShift AI console; User Workload Monitoring with PVC-backed Prometheus; 9 OLM-managed prerequisite operators; `all-in-one.sh` deployment script with auto-detection of cluster configuration

---

## Choosing Between Approaches

| Criteria | Approach A (Jupyter-Based Testing) | Approach B (Chatbot Application with Monitoring) | Approach C (CPU-Only Lightweight Serving) | Approach D (MaaS Multi-Tenant Developer IDE) |
|----------|-----------------------------------|------------------------------------------------|------------------------------------------|----------------------------------------------|
| User interface | Jupyter Notebook workbench | Browser-based HTML/JS chat UI with SSE streaming | AnythingLLM workbench + Llama Stack Distribution playground | OpenShift DevSpaces IDE with Continue.dev AI coding extension |
| Backend | None (direct orchestrator interaction) | FastAPI proxy to GuardrailsOrchestrator | None (AnythingLLM connects directly to vLLM) | None (model serves via MaaS gateway; Continue.dev connects to MaaS endpoint) |
| Monitoring | None | R Shiny dashboard with real-time guardrail metrics | None | Perses dashboards embedded in OpenShift AI console via Cluster Observability Operator |
| Metrics | None | Prometheus-format metrics (per-detector, per-direction) with ServiceMonitor | None | Per-subscription usage attribution (model, user, subscription, organization_id, cost_center) via TelemetryPolicy + Istio Telemetry per-subscription request duration |
| Hardware | GPU required | GPU required (CPU/GPU configurable per detector) | CPU only (no GPU required, minimum 2 cores / 4Gi) | GPU required (minimum 48GB VRAM, tested on AWS g6e.2xlarge with L40S) |
| Model | Llama 3.2 3B Instruct (OCI modelcar) | Llama 3.2 3B Instruct (OCI modelcar) | TinyLlama-1.1B-Chat (OCI modelcar) | NVIDIA Nemotron-3-Nano-30B-A3B FP8 (OCI modelcar, 30B hybrid Mamba-Transformer MoE, 256k context) |
| Deployment mode | RawDeployment | RawDeployment | Standard (Knative) | LLMInferenceService via MaaS gateway (vLLM/llm-d) |
| Orchestration | TrustyAI GuardrailsOrchestrator | TrustyAI GuardrailsOrchestrator | None | None (MaaS governance layer for access control and rate limiting) |
| Detectors | Gibberish, prompt injection, HAP, regex PII | HAP, prompt injection, language detection (Lingua), regex competitor blocking | None | None |
| RAG capability | None | None | Llama Stack Distribution with inline Milvus and HR document seeding | None |
| Tool calling | Not documented | Not documented | Enabled (`--enable-auto-tool-choice` with hermes parser) | Enabled (`--enable-auto-tool-choice` with qwen3_coder parser + custom nano_v3 reasoning parser) |
| System prompt | Not configurable | ConfigMap-mounted, changeable without image rebuild | Configured via AnythingLLM workspace init Job | Configured via Continue.dev IDE extension settings |
| Authentication | None | None | None | Keycloak (RHBK) with OpenShift OAuth integration, per-group MaaSAuthPolicy |
| Multi-tenancy | None | None | None | MaaSSubscription per group with token rate limits, per-user DevWorkspace namespaces |
| RHOAI dependencies | KServe, vLLM | KServe, vLLM, TrustyAI | KServe, vLLM, OpenShift Service Mesh, OpenShift Serverless | KServe, vLLM/llm-d, MaaS, RHCL (Kuadrant), DevSpaces, RHBK, CloudNative-PG, COO, OpenTelemetry, cert-manager |
| Best for | Interactive model serving exploration and demo via notebook | Production-ready customer-facing chatbot with guardrail monitoring | Quick lightweight model deployment on CPU-only environments with out-of-the-box chat and RAG playground | Centralized multi-tenant model serving for developer teams with governed access, rate limiting, usage tracking, and chargeback |
