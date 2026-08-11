---
name: rag-chatbot
description: "Conversational AI app that answers questions using retrieval-augmented generation over user documents"
summary: "Grounds LLM responses in user-uploaded documents via chunking, embedding into a vector store (pgvector, GPU-accelerated Milvus, or inline SQLite-backed Milvus), and similarity search at query time for source-grounded conversational Q&A on RHOAI/OpenShift. Choose over agentic-app when core value is document-grounded Q&A without tool calls or multi-step reasoning, over model-serving-app when retrieval beyond direct inference is needed -- five approaches: A (ai-virtual-agent, f5-api-security) lightweight custom RAG with FastAPI+LlamaStack, pgvector, K8s Job ingestion, React/PatternFly or Streamlit, 1-2 GPUs; B (aml-rag-nvidia) NVIDIA RAG Blueprint with NV-Ingest (OCR/table/VLM captioning), GPU-accelerated Milvus, 4 KServe/vLLM models (Nemotron-Super-49B-FP8, VLM, embedding, reranking), embedding/ranking translation proxies bridging NIM API to vLLM, ODF, OpenTelemetry+Grafana+Tempo, 3-5 H100/A100 GPUs with MIG; C (f5-ai-guardrails) security-focused RAG with LlamaStack+pgvector via ai-architecture-charts subcharts, F5 AI Guardrails Moderator proxy for prompt injection/PII/toxicity/topic via OLM operator (SecurityOperator CR ai.security.f5.com/v1alpha1, certified-operators) across 5 namespaces, Llama-3.2-1B-Instruct + all-MiniLM-L6-v2, dual-panel Streamlit UI, Calypso AI Red Team; D (RAG) enterprise RAG with Kubeflow Pipelines multi-source ingestion (5 domains), Docling+inline PyPDF document processing, multi-device serving (GPU/HPU/Xeon/CPU), dual Direct/Agent-based modes with MCP+Tavily, LlamaStack safety shields (Llama Guard), DeepEval evaluation (faithfulness/contextual precision/relevancy/ConversationalGEval), ArgoCD multi-tenant bootstrap; E (llm-cpu-serving) CPU-only RAG via LlamaStackDistribution CR (llamastack.io/v1alpha1) with inline Milvus (SQLite-backed), inline sentence-transformers (granite-embedding-125m-english), TinyLlama-1.1B on CPU-only vLLM, AnythingLLM workbench, K8s Job URL-based document seeding, no GPU or custom backend. Approach B requires `APP_VECTORSTORE_ENABLEGPUINDEX: \"True\"` and `APP_VECTORSTORE_ENABLEGPUSEARCH: \"True\"` in charts/ingest/values.yaml for GPU Milvus plus embedding/ranking translation proxies bridging NVIDIA NIM API to vLLM; Approach C routes requests through F5 Moderator evaluating active guardrail policies before forwarding to LlamaStack, blocking violations with `cai_error` response containing `scanner_results`; Approach D configures device type via `global.models` with device-specific args and toggles 6 ai-architecture-charts subcharts via condition flags in umbrella chart; Approach E defines full LlamaStack configuration in a ConfigMap including remote vLLM inference, inline sentence-transformers, inline Milvus vector_io, and file-search tool runtime. Approach B requires NGC API key for cloud-hosted NV-Ingest NIMs (document detection/OCR not locally served); Approach C requires F5 license key + private registry credentials (harbor.calypsoai.app), anyuid SCC bindings plus pre-applied inference model SCC (`openshift-inference-models-scc.yaml`), Helm retry logic (`F5_HELM_MAX_ATTEMPTS=8`, `F5_HELM_RETRY_SLEEP=6`) for namespace races, and persists guardrail state to emptyDir JSON file (`F5_GUARDRAILS_STATE_FILE=/data/guardrails_state.json`) lost on pod replacement -- use PVC for persistence; Approach D requires min 16vCPU/64GB RAM for Xeon CPU-only deployment; Approach E stores all state (vector DB, metadata, KV store) in SQLite files within pod filesystem, lost on restart unless backed by a PVC."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, patternfly, postgresql, python, nvidia-rag-blueprint, redis, streamlit, llama-stack, ansible, docling, deepeval, kubeflow-pipelines, anythingllm, sentence-transformers]
  ai_pattern: [rag, embeddings, vector-search, model-serving, multimodal, guardrails, evaluation, data-pipeline, agents]
  platform: [rhoai, openshift, vllm, kserve, hpu, xeon]
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
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Enterprise RAG chatbot with Kubeflow Pipelines for multi-source data ingestion, Docling document processing, dual Direct/Agent-based modes, MCP server integration, DeepEval evaluation framework, multi-device model serving (GPU/HPU/Xeon/CPU), LlamaStack safety shields, and ArgoCD-based multi-tenant bootstrap"
    approach: "D"
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Lightweight CPU-only RAG via Llama Stack Distribution CR with inline Milvus vector storage and sentence-transformers embeddings, K8s Job document seeding, AnythingLLM chat frontend, no custom backend or GPU required"
    approach: "E"
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
| RAG | Enterprise RAG chatbot connecting employees to internal documentation (HR, procurement, sales, IT, legal) via Streamlit chat, with Kubeflow Pipelines for multi-source data ingestion, Docling PDF processing, dual Direct/Agent-based modes with MCP tool support, DeepEval evaluation, multi-device model serving (GPU/HPU/Xeon/CPU), and ArgoCD multi-tenant bootstrap |
| llm-cpu-serving | Lightweight CPU-only RAG playground using Llama Stack Distribution CR with inline Milvus vector storage and inline sentence-transformers embeddings (granite-embedding-125m-english), K8s Job seeding HR documents from URLs, AnythingLLM workbench as chat frontend, no GPU or custom backend required |

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

## Approach D: Enterprise RAG with Kubeflow Pipelines and Multi-Device Serving (from RAG)

### When to Use

When the RAG application requires automated multi-source document ingestion via Kubeflow Pipelines, supports multiple hardware backends (NVIDIA GPU, Intel Gaudi HPU, Intel Xeon CPU), includes a built-in evaluation framework, and offers both Direct (manual RAG) and Agent-based (automatic tool calling with MCP) interaction modes out of the box.

### Differences from Approach A

- **Ingestion pipeline:** Approach A uses a Kubernetes Job or background task for simple document chunking; Approach D uses Kubeflow Pipelines via ai-architecture-charts `ingestion-pipeline` subchart (0.7.5) and `configure-pipeline` subchart (0.5.9) for automated multi-source ingestion from GitHub repos, S3/MinIO buckets, and direct URLs, with per-domain pipeline configuration in `deploy/helm/rag/values.yaml` -- five pre-configured pipelines (HR, legal, sales, procurement, techsupport) each with independent `source`, `embedding_model`, `vector_store_name`, and source-specific parameters
- **Document processing:** Approach A uses basic chunking; Approach D includes a standalone `ingestion-service/` using Docling (`docling>=2.0.0`, `docling-core>=2.0.0`) for PDF processing with `DocumentConverter`, `PdfPipelineOptions` (picture image generation), and `HybridChunker` for intelligent chunking (`ingestion-service/ingest.py`), plus LlamaStack's inline PyPDF file processor (`llama-stack.fileProcessors.providers` with `provider_type: inline::pypdf` in `deploy/helm/rag/values.yaml`)
- **Multi-device model serving:** Approach A targets GPU-only deployment; Approach D supports four device types via the `global.models` configuration: `gpu` (NVIDIA, default), `hpu` (Intel Gaudi, requires drivers), `xeon` (Intel Xeon CPU, optimized for SPR/EMR/GNR, requires min 16vCPU and 64GB RAM), and `cpu` (generic CPU) -- each device type has documented model configuration examples with device-specific `args` in `deploy/helm/rag/values.yaml`
- **Interaction modes:** Approach A provides a single chat interface; Approach D offers dual modes toggled in the Streamlit UI (`frontend/llama_stack_ui/distribution/ui/page/playground/chat.py`) -- "Direct" mode for manual RAG with explicit vector store selection and file search, and "Agent-based" mode that uses LlamaStack Responses API with automatic tool calling, including `builtin::rag` (file_search), `web_search` (Tavily), and MCP tool integration
- **MCP server integration:** Approach A does not include MCP; Approach D deploys MCP servers as an ai-architecture-charts subchart (`mcp-servers` 0.5.18 in `deploy/helm/rag/Chart.yaml`, `mcp-servers.enabled: true` in values.yaml), accessible from Agent-based mode as `mcp::` prefixed toolgroups that are auto-discovered from the LlamaStack toolgroups API (`frontend/llama_stack_ui/distribution/ui/page/playground/agent.py`)
- **Safety shields:** Approach A has no built-in safety; Approach D integrates LlamaStack safety shields with UI-selectable input and output shields (`render_guardrails_selection` in `chat.py`) -- shield models (e.g., Llama-Guard-3-8B with `registerShield: true`) are automatically excluded from the chat model list and can be configured via `global.models` in values.yaml
- **Evaluation framework:** Approach A has no evaluation; Approach D includes a DeepEval-based evaluation suite (`evaluations/`) with `deep_eval_rag.py` using LLM-as-a-judge metrics (`FaithfulnessMetric`, `ContextualPrecisionMetric`, `ContextualRelevancyMetric`, custom `ChunkCountMetric`), conversation-level metrics via `ConversationalGEval`, `get_rag_metrics.py` for retrieval quality assessment, `test_conversations_ui.py` for automated UI conversation generation via pytest, and `evaluate.py` as a wrapper that chains conversation generation with evaluation
- **Multi-tenant deployment:** Approach A is single-tenant; Approach D includes a `tenant/bootstrap/` Helm chart that creates ArgoCD Applications for per-tenant RAG deployments, configuring namespace, user credentials, Git source, and per-tenant model/API key overrides via `tenant/bootstrap/values.yaml`
- **Backend:** Approach A includes a custom FastAPI backend; Approach D has no custom backend -- LlamaStack server (ai-architecture-charts `llama-stack` subchart 0.8.7) provides all backend APIs (chat completions, RAG tool queries, vector store management, shield evaluation, MCP tool routing), and the Streamlit frontend communicates directly with LlamaStack via `llama-stack-client` SDK
- **Frontend:** Approach A uses React/PatternFly; Approach D uses Streamlit (`frontend/llama_stack_ui/`) with pages for chat playground (Direct and Agent-based modes), vector database management, shield configuration, evaluation tasks, dataset management, and model inspection
- **Helm chart structure:** Approach A uses custom Helm; Approach D uses a single umbrella chart (`deploy/helm/rag/Chart.yaml` version 0.2.46) pulling 6 ai-architecture-charts subcharts: `pgvector` (0.5.6), `llm-service` (0.5.10), `configure-pipeline` (0.5.9), `ingestion-pipeline` (0.7.5), `llama-stack` (0.8.7), and `mcp-servers` (0.5.18), each with a `condition` toggle for selective deployment
- **Sample data:** Approach D includes pre-configured knowledge bases spanning 5 enterprise domains (HR benefits/policies, legal contracts, sales processes, procurement workflows, tech support) with suggested questions per domain configured in `suggestedQuestions` in `deploy/helm/rag/values.yaml`
- **Local development:** Approach D includes `deploy/local/podman-compose.yml` for local development with a local `deploy/local/Makefile` and `deploy/local/ingestion-config.yaml` for local ingestion pipeline configuration
- **Web search:** Approach D integrates Tavily web search via `llama-stack.secrets.TAVILY_SEARCH_API_KEY` in `deploy/helm/rag/values.yaml`, available as a `web_search` tool in Agent-based mode
- **Client examples:** Approach D includes standalone Python client examples (`client-examples-python/`) for vector DB CRUD operations (`rag-create-vector-db.py`, `rag-use-vector-db.py`, `rag-delete-vector-db.py`, `rag-list-vector-db.py`), shield testing (`test-shield.py`), and web search (`web-search.py`) using `llama-stack-client`
- **Notebooks:** Approach D includes Jupyter notebooks (`notebooks/data-ingestion-pipeline.ipynb`, `notebooks/query_pgvector.ipynb`) for interactive data ingestion and direct pgvector querying

### Typical Components

- **Model serving:** vLLM via ai-architecture-charts `llm-service` subchart (0.5.10) for LLM inference with multi-device support (GPU, HPU, Xeon, CPU); optional Llama Guard shield model for safety; all-MiniLM-L6-v2 for embedding generation
- **Backend:** LlamaStack via ai-architecture-charts `llama-stack` subchart (0.8.7) providing chat completions, RAG orchestration, vector store management, shield evaluation, MCP tool routing, and both native and OpenAI-compatible APIs
- **Frontend:** Streamlit (`frontend/llama_stack_ui/`) with dual Direct/Agent-based chat modes, vector DB management, shield selection, evaluation tasks, and model inspection pages
- **Data layer:** PostgreSQL + pgvector (ai-architecture-charts `pgvector` subchart 0.5.6) for document embeddings and semantic search; MinIO/S3 for raw document storage
- **Supporting:** Kubeflow Pipelines (ai-architecture-charts `ingestion-pipeline` 0.7.5 + `configure-pipeline` 0.5.9) for automated multi-source document ingestion; standalone ingestion-service with Docling for PDF processing; MCP servers (ai-architecture-charts `mcp-servers` 0.5.18) for Agent-based tool integration; DeepEval evaluation framework; tenant bootstrap chart for ArgoCD multi-tenancy; Tavily for web search; client example scripts and Jupyter notebooks

---

## Approach E: Lightweight Inline RAG via Llama Stack Distribution (from llm-cpu-serving)

### When to Use

When the RAG capability is a secondary feature of a model serving deployment -- the primary goal is serving a small LLM on CPU with no GPU, and the RAG layer is provided out-of-the-box via a Llama Stack Distribution CR with inline (embedded) vector storage and embeddings, requiring no separate vector database deployment, no custom backend, and no GPU resources.

### Differences from Approach A

- **Deployment architecture:** Approach A deploys LlamaStack as a standalone server with custom FastAPI backend; Approach E deploys a `LlamaStackDistribution` CR (`llamastack.io/v1alpha1` in `helm/templates/playground.yaml`) as a managed playground service with no custom backend code
- **Vector database:** Approach A uses pgvector (PostgreSQL extension, separate StatefulSet); Approach E uses inline Milvus (`inline::milvus` provider type) with SQLite-backed storage (`db_path: /opt/app-root/src/.llama/distributions/rh/milvus.db` in `helm/templates/playground.yaml` ConfigMap), requiring no separate database deployment
- **Embedding model:** Approach A serves embeddings via a separate KServe model or LlamaStack provider; Approach E uses `inline::sentence-transformers` provider with `ibm-granite/granite-embedding-125m-english` (768 dimensions) running within the Llama Stack Distribution pod itself (`helm/templates/playground.yaml` ConfigMap)
- **Model serving:** Approach A typically requires GPU for LLM inference; Approach E uses CPU-only vLLM (`registry.redhat.io/rhaii/vllm-cpu-rhel9`) serving TinyLlama-1.1B-Chat with `VLLM_CPU_KVCACHE_SPACE` tuning and Standard (Knative) deployment mode (`helm/templates/servingruntime.yaml`, `helm/templates/inferenceservice.yaml`)
- **Frontend:** Approach A uses React/PatternFly; Approach E uses AnythingLLM deployed as a Kubeflow Notebook workbench (`kubeflow.org/v1 Notebook` CR in `helm/templates/workbench.yaml`) with SQLite sidecar for API key auto-provisioning, plus the Llama Stack Distribution's built-in playground UI
- **Document ingestion:** Approach A uses a Kubernetes Job or background task with custom chunking; Approach E uses a Kubernetes Job (`helm/templates/rag-seed-job.yaml`) that fetches HR policy documents from URLs, strips HTML, and indexes via `llama-stack-client` into a per-user vector store (username hashed from namespace RoleBindings); AnythingLLM also gets separately seeded via a curl-based init Job (`helm/templates/init_job.yaml`)
- **Hardware requirements:** Approach A requires 1-2 GPUs; Approach E requires CPU only (minimum 2 cores / 4Gi, recommended 32 cores / 64Gi), compiled for Intel CPUs (AVX512 preferred) per `README.md`
- **LlamaStack configuration:** Approach E defines the full LlamaStack configuration in a ConfigMap (`llama-stack-config`) including remote vLLM inference provider, inline sentence-transformers, inline Milvus vector_io, file-search tool runtime, MCP tool protocol, SQLite-backed metadata and KV stores, and default embedding model configuration (`helm/templates/playground.yaml`)
- **Persistence:** Approach A persists embeddings to PostgreSQL; Approach E stores all state (vector DB, metadata, KV store) in SQLite files within the pod's filesystem -- data is lost on pod restart unless backed by a PVC

### Typical Components

- **Model serving:** KServe InferenceService with CPU-optimized vLLM ServingRuntime (`vllm-cpu`) serving TinyLlama-1.1B-Chat via OCI modelcar storage (`oci://quay.io/rh-aiservices-bu/tinyllama:1.0`), no GPU required
- **Backend:** Llama Stack Distribution CR (`LlamaStackDistribution`) providing inference, vector_io, file-search, responses, and tool_runtime APIs -- no custom backend
- **Frontend:** AnythingLLM Kubeflow Notebook workbench with workspace auto-provisioning; Llama Stack Distribution built-in playground UI
- **Data layer:** Inline Milvus (SQLite-backed) for vector storage within Llama Stack pod; inline sentence-transformers (`ibm-granite/granite-embedding-125m-english`) for embedding generation
- **Supporting:** K8s Job (`rag-seed-job`) for seeding HR documents from URLs into vector store using `llama-stack-client`; curl-based init Job for AnythingLLM workspace setup (workspace creation, system prompt, seed documents); ConfigMap-based Llama Stack configuration

---

## Choosing Between Approaches

| Criteria | Approach A (Custom-built) | Approach B (NVIDIA Blueprint) | Approach C (Guardrails-Secured) | Approach D (Enterprise RAG with Pipelines) | Approach E (Lightweight Inline RAG) |
|----------|--------------------------|-------------------------------|--------------------------------|-------------------------------------------|-------------------------------------|
| RAG pipeline | Custom FastAPI + LlamaStack | NVIDIA RAG Server pre-built container | LlamaStack (ai-architecture-charts subchart) | LlamaStack (ai-architecture-charts subchart) with Kubeflow Pipelines for ingestion | Llama Stack Distribution CR with inline providers (no custom backend) |
| Document processing | Simple chunking pipeline | NV-Ingest with OCR, table/graphic detection, VLM captioning | LlamaStack RAG tool chunking | Kubeflow Pipelines multi-source ingestion + Docling PDF processing + LlamaStack inline PyPDF | K8s Job fetching URLs + HTML stripping via llama-stack-client |
| Vector database | pgvector (CPU) | Milvus (GPU-accelerated) | pgvector (CPU) | pgvector (CPU) | Inline Milvus (SQLite-backed, no separate deployment) |
| Models required | 1-2 (LLM + optional embedding) | 4 (LLM, VLM, embedding, reranking) | 1 LLM + 1 embedding (Llama-3.2-1B + MiniLM) | 1 LLM + 1 embedding (configurable) + optional safety shield | 1 LLM (TinyLlama 1.1B) + 1 inline embedding (granite-embedding-125m-english) |
| GPU requirements | Low (1-2 GPUs) | High (3-5 H100/A100 GPUs, MIG optional) | Low (1 GPU for LLM) + dedicated GPU for F5 guardrail scanners | Flexible (1 GPU, or HPU, or Xeon CPU, or CPU-only) | None (CPU only, min 2 cores / 4Gi) |
| AI security | None | None | F5 AI Guardrails (prompt injection, PII, toxicity, topic) | LlamaStack safety shields (Llama Guard, configurable input/output shields) | None |
| External dependencies | None | NGC API key for cloud-hosted NV-Ingest NIMs | F5 license key + private registry credentials | Tavily API key (optional, for web search) | None |
| Namespace topology | Single namespace | Single namespace | 5 namespaces (RAG + 4 F5 operator-managed) | Single namespace (multi-tenant via ArgoCD bootstrap) | Single namespace |
| Frontend | React/PatternFly | React (NVIDIA Blueprint UI) | Streamlit (dual-panel guardrailed vs direct) | Streamlit (dual Direct/Agent-based modes with MCP tools) | AnythingLLM workbench + Llama Stack playground |
| Observability | Not included | Full stack (OpenTelemetry, Grafana, Tempo) | F5 Moderator dashboard (allowed/blocked counts, audit logs) | Not included (evaluation framework for offline quality assessment) | Not included |
| Evaluation | Not included | Not included | Not included | DeepEval (faithfulness, contextual precision/relevancy, chunk count, conversational G-Eval) | Not included |
| Agent capabilities | None | None | None | LlamaStack Agent mode with MCP tools, web search, file search | File-search tool runtime + MCP protocol support (via Llama Stack Distribution) |
| Multi-device support | GPU only | GPU only (NVIDIA H100/A100) | GPU only | GPU, Intel Gaudi HPU, Intel Xeon CPU, generic CPU | CPU only (Intel, AVX512 preferred) |
| Multi-tenancy | Not included | Not included | Not included | ArgoCD-based tenant bootstrap chart | Not included |
| Best for | Lightweight RAG within a broader app | Enterprise document-heavy RAG with GPU resources | Demonstrating AI-layer security for model inference endpoints | Full-featured enterprise RAG reference implementation with pipeline-based ingestion, multi-device flexibility, and built-in evaluation | Quick zero-GPU RAG demo with no custom code, inline vector DB, and out-of-the-box chat UI |
