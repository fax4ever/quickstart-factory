---
name: rag-chatbot
description: "Conversational AI app that answers questions using retrieval-augmented generation over user documents"
summary: "Grounds LLM responses in user-uploaded documents via chunking, embedding into a vector store (pgvector or GPU-accelerated Milvus), and similarity search at query time for source-grounded conversational Q&A on RHOAI/OpenShift. Choose over agentic-app when core value is document-grounded Q&A without tool calls or multi-step reasoning, over model-serving-app when retrieval beyond direct inference is needed — Approach A (ai-virtual-agent, f5-api-security) suits lightweight custom RAG with FastAPI+LlamaStack, pgvector, K8s Job ingestion, MinIO/S3, React/PatternFly or Streamlit, and 1-2 GPUs; Approach B (aml-rag-nvidia) suits enterprise document-heavy RAG using NVIDIA RAG Blueprint with NV-Ingest (OCR, table/graphic detection, VLM captioning), GPU-accelerated Milvus, 4 KServe/vLLM models (Nemotron-Super-49B-FP8, VLM, embedding, reranking), embedding/ranking translation proxies, Redis task queue, ODF ObjectBucketClaim, OpenTelemetry+Grafana+Tempo observability, and 3-5 H100/A100 GPUs with optional MIG partitioning; Approach C (f5-ai-guardrails) suits security-focused RAG with LlamaStack+pgvector via ai-architecture-charts subcharts (llm-service, llama-stack, pgvector), F5 AI Guardrails (Calypso AI) Moderator proxy for prompt injection/PII/toxicity/topic enforcement, OLM-managed F5 operator (SecurityOperator CR ai.security.f5.com/v1alpha1, certified-operators catalog) across 5 namespaces with Prefect workflow orchestration, Llama-3.2-1B-Instruct + all-MiniLM-L6-v2, dual-panel Streamlit UI (guardrailed vs direct), and Calypso AI Red Team for adversarial testing. Approach B requires `APP_VECTORSTORE_ENABLEGPUINDEX: \"True\"` and `APP_VECTORSTORE_ENABLEGPUSEARCH: \"True\"` in charts/ingest/values.yaml for GPU Milvus, plus embedding/ranking translation proxies bridging NVIDIA NIM API formats to vLLM; Approach C routes requests through the F5 Moderator endpoint which evaluates against active guardrail policies before forwarding to LlamaStack, blocking violations with a `cai_error` response containing `scanner_results`. Approach B requires an NGC API key for cloud-hosted NV-Ingest NIMs (document detection/OCR not locally served); Approach C requires F5 license key + private registry credentials (harbor.calypsoai.app), anyuid SCC bindings for F5 namespaces plus pre-applied inference model SCC (`openshift-inference-models-scc.yaml`), Helm retry logic for operator namespace races (`F5_HELM_MAX_ATTEMPTS=8`, `F5_HELM_RETRY_SLEEP=6`), and persists guardrail state (URL + API token) to emptyDir JSON file (`F5_GUARDRAILS_STATE_FILE=/data/guardrails_state.json`) — lost on pod replacement, use PVC for persistence."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, patternfly, postgresql, python, nvidia-rag-blueprint, redis, streamlit, llama-stack, ansible]
  ai_pattern: [rag, embeddings, vector-search, model-serving, multimodal, guardrails]
  platform: [rhoai, openshift, vllm, kserve]
  data_layer: [pgvector, milvus]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Knowledge base management with document upload, pgvector vector storage, and LlamaStack RAG tool integration for grounded Q&A within an agent platform"
    approach: "A"
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "NVIDIA RAG Blueprint adapted for RHOAI with NV-Ingest document processing, GPU-accelerated Milvus, 4-model KServe/vLLM serving, translation proxies, and full observability stack"
    approach: "B"
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "LlamaStack RAG chatbot secured by F5 AI Guardrails proxy for AI-layer content inspection -- prompt injection detection, PII filtering, toxicity scanning, and topic enforcement via OLM-managed operator"
    approach: "C"
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/f5-api-security"
    notes: "LlamaStack RAG chatbot (Streamlit + pgvector + vLLM) with F5 Distributed Cloud XC network-layer API security (WAF, API spec enforcement, rate limiting) -- RAG stack is same basic LlamaStack+pgvector pattern"
    approach: "A"
---

# RAG Chatbot

## Overview

A RAG chatbot combines a large language model with a retrieval system to answer questions grounded in user-provided documents. Users upload documents that are chunked, embedded, and stored in a vector database. At query time, relevant document chunks are retrieved and injected into the LLM prompt, producing answers that are factually grounded in the source material. On RHOAI, this pattern leverages model serving for both embedding generation and chat inference, with a vector database for similarity search.

## Typical Components

- **Model serving:** vLLM or LlamaStack for LLM inference and embedding generation
- **Backend:** FastAPI managing document ingestion, knowledge base CRUD, and chat sessions
- **Frontend:** React/PatternFly providing document upload, knowledge base management, and conversational chat interface
- **Data layer:** pgvector (PostgreSQL with vector extension) for storing document embeddings and performing similarity search
- **Supporting:** Ingestion pipeline (Kubernetes Job or background task) for document chunking and embedding, MinIO or S3 for raw document storage

## When to Use

- **Business problem:** Users need to ask questions about their own documents (manuals, policies, knowledge articles) and get accurate, source-grounded answers rather than generic LLM responses
- **RHOAI capabilities:** Demonstrates model serving for inference and embeddings, vector database integration for semantic search, and document ingestion pipelines on OpenShift
- **Scale/complexity:** Low to medium complexity; suitable when the primary interaction is conversational Q&A over a document corpus without needing external tool calls or multi-step agent reasoning

## Example Quickstarts

| Quickstart | What It Demonstrates |
|------------|---------------------|
| ai-virtual-agent | RAG as an integrated capability within an agent platform -- knowledge bases with pgvector, document ingestion pipeline, and LlamaStack RAG tool for grounded responses |
| aml-rag-nvidia | NVIDIA RAG Blueprint adapted for RHOAI -- NV-Ingest enterprise document processing, GPU-accelerated Milvus vector search, 4-model KServe/vLLM serving (LLM, VLM, embedding, reranking), and built-in observability |
| f5-ai-guardrails | LlamaStack RAG chatbot secured by F5 AI Guardrails (Calypso AI) -- Moderator proxy intercepts prompts and responses for policy evaluation (prompt injection, PII, toxicity, topic), with dual-panel Streamlit UI comparing guardrailed vs direct model access |
| f5-api-security | LlamaStack RAG chatbot for financial services secured by F5 Distributed Cloud (XC) WAAP at the network layer -- WAF for XSS/SQL injection, API spec enforcement against shadow APIs, and rate limiting for DoS prevention, with Streamlit UI supporting configurable XC URL endpoint |

## Decision Criteria

### vs agentic-app

Pick **rag-chatbot** when the core value is document-grounded Q&A and the app does not need to call external tools or orchestrate multi-step workflows. Pick **agentic-app** when the AI needs to dynamically select and invoke tools, manage multi-step reasoning, or take actions beyond retrieval.

### vs model-serving-app

Pick **rag-chatbot** when the application needs to ground LLM responses in user documents via vector search. Pick **model-serving-app** when the focus is on exposing a model endpoint for direct inference without a retrieval layer.

---

## Approach B: NVIDIA RAG Blueprint on RHOAI (from aml-rag-nvidia)

### When to Use

When the RAG application is built on top of a vendor-provided blueprint (NVIDIA RAG Blueprint) adapted for Red Hat OpenShift AI, requiring enterprise document processing (OCR, table/graphic detection, VLM captioning), GPU-accelerated vector search, and multiple specialized models for different tasks (generation, vision, embedding, reranking).

### Differences from Approach A

- **Vendor blueprint vs custom-built:** Approach A builds the RAG pipeline from scratch with FastAPI and LlamaStack; Approach B adapts NVIDIA's pre-built RAG Server container (`nvcr.io/nvidia/blueprint/rag-server:2.4.0`) and NV-Ingest pipeline for RHOAI
- **Vector database:** Approach A uses pgvector (PostgreSQL extension); Approach B uses Milvus with GPU-accelerated indexing and search (`APP_VECTORSTORE_ENABLEGPUINDEX: "True"`, `APP_VECTORSTORE_ENABLEGPUSEARCH: "True"` in `charts/ingest/values.yaml`)
- **Document processing:** Approach A uses a Kubernetes Job or background task for chunking and embedding; Approach B uses NVIDIA NV-Ingest 26.1.1 with cloud-hosted NIMs for page element detection, graphic element detection, table structure detection, OCR, and VLM-based image captioning (`charts/ingest/values.yaml`)
- **Model count:** Approach A serves 1-2 models; Approach B deploys 4 specialized models via KServe/vLLM -- Nemotron-Super-49B-FP8 (LLM), Nemotron-Nano-12B-VL-FP8 (VLM), llama-nemotron-embed-1b-v2, llama-nemotron-rerank-1b-v2 (`charts/model-serving/values.yaml`)
- **API translation proxies:** Approach B includes Python proxy services that translate NVIDIA NIM embedding and ranking API formats to vLLM-compatible formats, enabling vendor blueprint components to work with RHOAI model serving (`charts/rag-server/templates/embedding-proxy-configmap.yaml`, `charts/rag-server/templates/ranking-proxy-configmap.yaml`)
- **Object storage:** Approach A uses MinIO/S3; Approach B uses ODF ObjectBucketClaim (`charts/ingest/values.yaml`)
- **Observability:** Approach A has no built-in observability; Approach B includes a full stack -- OpenTelemetry Collector, Grafana, Tempo, User Workload Monitoring (`charts/observability/`)
- **GPU requirements:** Approach B requires 3-5 NVIDIA H100/A100 GPUs with optional MIG partitioning to reduce requirements via GPU Operator ClusterPolicy (`charts/gpu-operator/`)
- **Hybrid processing:** Approach B serves models locally via KServe/vLLM but uses NGC cloud-hosted NIMs for document detection and OCR tasks, requiring an NGC API key (`charts/ingest/values.yaml`)

### Typical Components

- **Model serving:** KServe + vLLM ServingRuntime deploying 4 NVIDIA models (LLM, VLM, embedding, reranking) with tensor parallelism and MIG support
- **Backend:** NVIDIA RAG Server (pre-built container) for query/answer orchestration, custom ingestor server for document ingestion coordination
- **Frontend:** React (customized NVIDIA RAG Blueprint UI)
- **Data layer:** Milvus (GPU-accelerated vector DB) for dense and sparse search with RRF ranking, ODF for raw document storage
- **Supporting:** NV-Ingest for document processing, Redis for NV-Ingest task queue, embedding and ranking translation proxies, NVIDIA GPU Operator with MIG support, OpenTelemetry + Grafana + Tempo observability stack

---

## Approach C: Guardrails-Secured RAG (from f5-ai-guardrails)

### When to Use

When the primary objective is demonstrating or enforcing AI-layer security on model inference endpoints -- protecting a RAG chatbot against prompt injection attacks, PII leakage, toxic content generation, and off-topic misuse using a vendor-managed guardrails proxy, rather than building guardrails into the application code.

### Differences from Approach A

- **Security layer:** Approach A has no AI-layer security; Approach C deploys F5 AI Guardrails (Calypso AI) as a transparent proxy between the client and LlamaStack, scanning both prompts and responses against configurable policies (`deploy/helm/f5-ai-security/values.yaml`)
- **Deployment topology:** Approach A deploys all components in a single namespace; Approach C spans 5 namespaces -- the RAG app namespace plus 4 F5 namespaces (`f5-ai-sec` for the operator, `cai-moderator` for the Moderator UI + PostgreSQL, `prefect` for workflow orchestration, `f5-ai-sec-inference` for guardrail/red-team model serving) managed by the F5 AI Security Operator via OLM (`deploy/helm/f5-ai-security/templates/20-subscription.yaml`)
- **Operator management:** Approach C uses an OLM-managed operator (`f5-ai-security-operator` from `certified-operators` catalog, channel `stable`, CSV `f5-ai-security-operator.v0.8.1`) with a `SecurityOperator` custom resource (`ai.security.f5.com/v1alpha1`) that deploys Moderator, PostgreSQL, Prefect job manager, and inference components (`deploy/helm/f5-ai-security/templates/40-security-operator.yaml`)
- **Data flow:** Approach A sends requests directly to LlamaStack; Approach C routes requests through the F5 Moderator endpoint, which evaluates against active guardrail policies before forwarding to LlamaStack, and scans responses on the return path -- if either prompt or response violates a policy, the request is blocked with a `cai_error` response body containing `scanner_results` (`frontend/llama_stack_ui/distribution/ui/page/playground/chat.py` lines 42-73)
- **Frontend:** Approach A uses React/PatternFly; Approach C uses Streamlit with a dual-panel layout -- left panel sends requests through the F5 Guardrails Moderator endpoint, right panel sends directly to LlamaStack, allowing side-by-side comparison of guardrailed vs unguarded responses (`frontend/llama_stack_ui/distribution/ui/page/playground/chat.py` lines 258-277)
- **AI security capabilities:** Approach C includes four out-of-the-box guardrail types: prompt injection detection, PII filtering (SSNs, credit card numbers), toxicity scanning, and topic restriction/enforcement (`docs/ai_guardrails_use_cases.md`); custom guardrails can be created via GenAI, Keyword, and Regex patterns in the Moderator UI
- **Red Team:** Approach C includes Calypso AI Red Team for adversarial testing and vulnerability assessment of model endpoints, deployed alongside guardrails via the `SecurityOperator` CR (`securityOperator.inference.redteam: true` in `deploy/helm/f5-ai-security/values.yaml`)
- **Registry credentials:** Approach C requires private registry access to `harbor.calypsoai.app` for F5 component images, plus an F5 license key (`securityOperator.moderator.license` in `deploy/helm/f5-ai-security/values.yaml`)
- **Model serving:** Both use vLLM + LlamaStack via `ai-architecture-charts` subcharts (`deploy/helm/rag/Chart.yaml` dependencies: `llm-service` 0.5.2, `llama-stack` 0.8.6, `pgvector` 0.1.0); Approach C defaults to `Llama-3.2-1B-Instruct` (quantized) with `all-MiniLM-L6-v2` embeddings (README architecture table)
- **Guardrail state persistence:** Approach C persists the F5 Guardrails URL and API token to a JSON file on an `emptyDir` volume (`F5_GUARDRAILS_STATE_FILE=/data/guardrails_state.json` in `deploy/helm/rag/values.yaml`); state is lost on pod replacement -- comment in values.yaml notes: "use a PVC on /data for values that must survive rescheduling"
- **SCC requirements:** F5 components require `anyuid` SCC bindings for Moderator and inference namespaces (`deploy/helm/f5-ai-security/templates/50-scc-anyuid-bindings.yaml`); additional inference model SCC must be pre-applied before operator install (`deploy/helm/f5-ai-security/extras/openshift-inference-models-scc.yaml`)
- **Helm install resilience:** Approach C Makefile includes retry logic for F5 chart installation (`F5_HELM_MAX_ATTEMPTS=8`, `F5_HELM_RETRY_SLEEP=6`) to handle namespace and API races on cold clusters (`deploy/helm/Makefile`)

### Typical Components

- **Model serving:** vLLM via KServe InferenceService (ai-architecture-charts `llm-service` subchart) for LLM inference; LlamaStack for RAG orchestration and OpenAI-compatible API
- **Backend:** LlamaStack server providing RAG tool query/insert APIs, vector DB management, and model routing
- **Frontend:** Streamlit (`frontend/llama_stack_ui/`) with dual-panel chat UI (guardrailed vs direct), document collection management, and F5 Guardrails endpoint configuration sidebar
- **Data layer:** PostgreSQL + pgvector (ai-architecture-charts `pgvector` subchart) for document embeddings and semantic retrieval
- **Supporting:** F5 AI Security Operator (OLM, `certified-operators`) managing Moderator, Prefect workflow orchestration, and inference components; F5 AI Guardrails Moderator for prompt/response policy evaluation; Calypso AI Red Team for adversarial testing; private F5 container registry (`harbor.calypsoai.app`)

---

## Choosing Between Approaches

| Criteria | Approach A (Custom-built) | Approach B (NVIDIA Blueprint) | Approach C (Guardrails-Secured) |
|----------|--------------------------|-------------------------------|--------------------------------|
| RAG pipeline | Custom FastAPI + LlamaStack | NVIDIA RAG Server pre-built container | LlamaStack (ai-architecture-charts subchart) |
| Document processing | Simple chunking pipeline | NV-Ingest with OCR, table/graphic detection, VLM captioning | LlamaStack RAG tool chunking |
| Vector database | pgvector (CPU) | Milvus (GPU-accelerated) | pgvector (CPU) |
| Models required | 1-2 (LLM + optional embedding) | 4 (LLM, VLM, embedding, reranking) | 1 LLM + 1 embedding (Llama-3.2-1B + MiniLM) |
| GPU requirements | Low (1-2 GPUs) | High (3-5 H100/A100 GPUs, MIG optional) | Low (1 GPU for LLM) + dedicated GPU for F5 guardrail scanners |
| AI security | None | None | F5 AI Guardrails (prompt injection, PII, toxicity, topic) |
| External dependencies | None | NGC API key for cloud-hosted NV-Ingest NIMs | F5 license key + private registry credentials |
| Namespace topology | Single namespace | Single namespace | 5 namespaces (RAG + 4 F5 operator-managed) |
| Frontend | React/PatternFly | React (NVIDIA Blueprint UI) | Streamlit (dual-panel guardrailed vs direct) |
| Observability | Not included | Full stack (OpenTelemetry, Grafana, Tempo) | F5 Moderator dashboard (allowed/blocked counts, audit logs) |
| Best for | Lightweight RAG within a broader app | Enterprise document-heavy RAG with GPU resources | Demonstrating AI-layer security for model inference endpoints |
