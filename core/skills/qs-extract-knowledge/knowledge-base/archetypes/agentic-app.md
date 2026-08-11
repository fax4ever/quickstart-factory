---
name: agentic-app
description: "Agent-based AI app with tool use, multi-framework runners, and orchestrated workflows on RHOAI"
summary: "Archetype for deploying AI agents on RHOAI that reason, invoke tools via MCP protocol, and orchestrate multi-step workflows -- Approach A (ai-virtual-agent) provides user-initiated conversational platform with pluggable multi-framework runners (LlamaStack, LangGraph, CrewAI) and configurable guardrails, Approach B (ansible-log-analysis) provides event-driven LangGraph pipeline triggered by Grafana alerts with nested sub-agents (main graph -> get_more_context_agent -> loki_agent) following fixed domain flow, Approach C (data-governance-co-pilot) provides framework-less MCP-native agent with LLMProvider abstraction (MCPDirectProvider self-managed loop vs LlamaStackProvider delegated orchestration switchable via COPILOT_PROVIDER_MODE) and Nemotron think-tag handling for streaming reasoning separation, Approach D (it-self-service-agent) provides CloudEvent-driven multi-microservice platform (agent-service, request-manager, integration-dispatcher) with YAML-configurable LangGraph state machines, router-specialist agent topology, Knative Eventing + Kafka, multi-channel integration (Slack, email, Zammad), and NeMo Guardrails with NemoGuard JailbreakDetect NIM, and Approach E (lls-observability) provides operator-managed LlamaStackDistribution CR with standalone MCP servers (weather, HR API, OpenShift ops with read-only RBAC ClusterRole), Llama Guard safety shields, comprehensive OTel + Tempo + Grafana observability with sidecar injection for both vLLM and LlamaStack for LLM audit and compliance tracing, and optional MaaS integration (maas.enabled via LiteLLM endpoint) for larger models without local GPU resources. Choose over rag-chatbot when AI must take actions beyond document retrieval (API calls, dynamic tool selection, multi-step reasoning) and over model-serving-app when an orchestration layer managing agent state, tool dispatch, and multi-turn reasoning wraps the served model; pick A for general-purpose interactive tool use, B for automated domain-specific analysis triggered by external events, C for domain-specific MCP-native agents needing switchable orchestration modes and hard-coded tool security with Pydantic-validated ALLOWED_TOOLS allowlist (fail-closed), D for production enterprise IT self-service with extensible YAML-driven agent workflows, multi-channel input, and event-driven microservice architecture, E for observability-first agent deployment requiring end-to-end distributed tracing, metrics dashboards, and LLM audit trails with zero custom backend code. A stacks vLLM/LlamaStack with function calling behind FastAPI managing agent lifecycle, session state, and SSE streaming with React/PatternFly, PostgreSQL/pgvector, and MCP tool servers; B uses dual OpenAI-compatible endpoints (separate for tool-calling models), Gradio UI with DeepEval annotation, FAISS RAG with HuggingFace TEI, sentence-transformers + scikit-learn log clustering, and Arize Phoenix + Grafana + Alloy observability; C deploys KServe + vLLM (Nemotron Nano 9B or Qwen3-14B AWQ), auto-converts MCP tools to OpenAI function calling format, injects governance policies via REST API (/policy/upload), and renders Vega-Lite visualizations in SvelteKit; D deploys three FastAPI microservices with shared-models/shared-clients libraries, LlamaStack + vLLM (Llama 3 70B) via ai-architecture-charts subcharts, MCP servers for ServiceNow/Zammad, PostgreSQL-backed LangGraph checkpoint storage with session locking, Langfuse + MLflow + OpenTelemetry + ClickHouse observability, and DeepEval evaluation pipeline; E deploys operator-managed LlamaStackDistribution CR (llama-stack-operator) with custom OTel-instrumented vLLM image supporting multi-device deployment (GPU and Intel Xeon CPU via conditional Helm values), Llama Guard 3-1B safety via dedicated KServe InferenceService, 3 standalone MCP servers as separate Helm charts, inline Milvus + sentence-transformers for RAG, Llama Stack Playground (Streamlit) + Jupyter notebooks, and full observability stack (OTel sidecars for vLLM traces+metrics and LlamaStack traces, TempoStack with MinIO, Grafana with vLLM dashboard, UWM PodMonitors, Distributed Tracing UI Plugin). Medium-to-high complexity requiring model serving with function calling support and a full agent orchestration layer; B adds deployment complexity with nested sub-agent topology and full log management stack (Alloy collects, Loki stores, Grafana alerts); C requires MCP session reconnection with exponential backoff for pod restarts and handles dual tool calling formats (Nemotron custom TOOLCALL tags vs standard OpenAI) with auto-detection from model name; D adds significant infrastructure overhead with Knative Eventing + Kafka Broker (Strimzi-managed), requires session locking (acquire_agent_session_lock/release_agent_session_lock) for concurrent request handling, and needs mock services for development without external dependencies; E adds significant operator and observability infrastructure overhead with 5 OLM operators and phased deployment (operators -> observability -> AI services -> MCP servers) but requires no custom application code; simple prompt-response or document-only QA should use model-serving-app or rag-chatbot instead."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, patternfly, postgresql, python, gradio, langchain, langgraph, sveltekit, vega-lite, mcp, openai-sdk, pydantic, knative, kafka, redis, langfuse, mlflow, deepeval, streamlit, jupyter, opentelemetry, grafana, tempo]
  ai_pattern: [agents, rag, guardrails, model-serving, embeddings, evaluation, tool-calling, governance, observability, distributed-tracing]
  platform: [rhoai, openshift, vllm, tei, kserve, llama-stack, knative-eventing, llama-stack-operator]
  data_layer: [pgvector, faiss, clickhouse, milvus]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Multi-runner agent platform (LlamaStack, LangGraph, CrewAI) with MCP tool integration, guardrails, and RAG knowledge bases"
    approach: "A"
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Event-driven LangGraph agent pipeline for automated Ansible log analysis with MCP-based Loki querying, error classification, expert routing, and step-by-step remediation"
    approach: "B"
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Framework-less MCP-native agent with provider abstraction (MCP-Direct self-managed loop vs Llama Stack delegated orchestration), pg-airman-mcp for PostgreSQL governance, hard-coded tool allowlist security, and dual model format support (Nemotron vs OpenAI)"
    approach: "C"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "CloudEvent-driven multi-microservice agent platform (agent-service, request-manager, integration-dispatcher) with YAML-configurable LangGraph state machines, router-specialist agent topology, Knative Eventing + Kafka, multi-channel integration (Slack, email, Zammad), MCP servers for ServiceNow/Zammad, NeMo Guardrails, Langfuse + MLflow + OpenTelemetry observability, and DeepEval evaluation pipeline"
    approach: "D"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Operator-managed LlamaStackDistribution CR with MCP servers (weather, HR API, OpenShift ops), Llama Guard safety shields, comprehensive OTel + Tempo + Grafana observability with sidecar injection for both vLLM and LlamaStack, multi-device vLLM (GPU/Xeon), Llama Stack Playground + Jupyter notebooks (RAG, evals, LangGraph agent/tools)"
    approach: "E"
---

# Agentic App

## Overview

An agentic app deploys one or more AI agents that can reason, use tools, and take actions to accomplish tasks on behalf of users. Unlike simple chat interfaces that only generate text, agentic apps integrate tool ecosystems (web search, databases, external APIs) and can orchestrate multi-step workflows. On RHOAI, these apps leverage model serving for LLM inference while the agent orchestration layer manages tool dispatch, conversation state, and safety guardrails.

## Typical Components

- **Model serving:** vLLM or LlamaStack for LLM inference (chat completions with tool/function calling support)
- **Backend:** FastAPI handling agent lifecycle, session management, and streaming responses
- **Frontend:** React/PatternFly providing agent configuration UI and real-time chat with SSE streaming
- **Data layer:** PostgreSQL for agent/session persistence, pgvector for knowledge base vector search
- **Supporting:** MCP servers for tool integration, guardrails for safety controls, ingestion pipelines for knowledge bases

## When to Use

- **Business problem:** Automating customer interactions or internal workflows that require the AI to take actions (search the web, query databases, call APIs) rather than just answer questions from static knowledge
- **RHOAI capabilities:** Demonstrates model serving with tool/function calling, agent orchestration across multiple frameworks, MCP protocol for extensible tool integration, and configurable guardrails
- **Scale/complexity:** Medium to high complexity; suitable when a simple prompt-response flow is insufficient and the application needs multi-step reasoning with external tool invocations

## Example Quickstarts

| Quickstart | What It Demonstrates |
|------------|---------------------|
| ai-virtual-agent | Multi-framework agent platform with pluggable runners (LlamaStack, LangGraph, CrewAI), MCP tool servers, configurable guardrails, and RAG-backed knowledge bases |
| ansible-log-analysis | Event-driven LangGraph agent pipeline that detects Ansible errors from Grafana alerts, classifies and routes them to domain experts, retrieves additional log context via MCP-based Loki queries, and generates step-by-step remediation |
| data-governance-co-pilot | Framework-less MCP-native agent with dual provider modes (MCP-Direct and Llama Stack), pg-airman-mcp for PostgreSQL governance tools, hard-coded tool allowlist with Pydantic validation, governance policy injection, and SvelteKit + Vega-Lite frontend |
| it-self-service-agent | CloudEvent-driven multi-microservice platform with YAML-configurable LangGraph state machines, router-specialist agent topology, Knative Eventing + Kafka for inter-service communication, multi-channel integration (Slack, email, Zammad), MCP servers for ServiceNow ticketing, NeMo Guardrails, and Langfuse + MLflow + OpenTelemetry observability |
| lls-observability | Operator-managed Llama Stack agent with comprehensive LLM observability -- LlamaStackDistribution CR via llama-stack-operator, standalone MCP servers (weather, HR API, OpenShift ops), Llama Guard safety shields, OTel sidecar injection for vLLM and LlamaStack traces/metrics, TempoStack distributed tracing, Grafana dashboards, User Workload Monitoring PodMonitors, and Jupyter notebooks for RAG, evals, and LangGraph agent demos |

## Decision Criteria

### vs rag-chatbot

Pick **agentic-app** when the AI needs to take actions beyond retrieval -- calling external APIs, executing multi-step workflows, or using tools dynamically selected at runtime. Pick **rag-chatbot** when the primary interaction is question-answering grounded in uploaded documents, without tool orchestration or multi-step agent reasoning.

### vs model-serving-app

Pick **agentic-app** when the application includes an orchestration layer that manages agent state, tool dispatch, and multi-turn reasoning on top of the served model. Pick **model-serving-app** when the focus is on deploying and exposing a model endpoint (KServe/vLLM) without an agent framework wrapping it.

---

## Approach B: Event-Driven Agent Pipeline (from ansible-log-analysis)

### When to Use

When the agentic app is triggered by external events (alerts, webhooks, log streams) rather than user conversations, and the agent follows a domain-specific multi-step pipeline (detect, classify, route, gather context, remediate) rather than open-ended conversational tool use.

### Differences from Approach A

- **Triggering model:** Approach A is user-initiated (conversational chat); Approach B is event-driven (Grafana alerts trigger the pipeline via webhook to `backend-inference-webhook` in `deploy/helm/ansible-log-monitor/values.yaml`)
- **Agent framework:** Approach A supports pluggable multi-framework runners (LlamaStack, LangGraph, CrewAI); Approach B uses LangGraph exclusively with a fixed multi-step graph (`src/alm/agents/graph.py`)
- **Agent topology:** Approach A has a single agent with tool access; Approach B composes a main graph with nested sub-agents -- a `get_more_context_agent` that decides whether to invoke a `loki_agent` sub-graph for additional log retrieval (`src/alm/agents/get_more_context_agent/graph.py`, `src/alm/agents/loki_agent/graph.py`)
- **Pipeline structure:** Approach B follows a fixed domain-specific flow: cluster logs -> summarize -> classify error type -> route to expert domain -> decide if more context needed -> query Loki via MCP -> summarize Loki context -> generate step-by-step solution (`src/alm/agents/graph.py`)
- **MCP usage:** Both use MCP, but differently -- Approach A uses MCP servers as general-purpose tool providers; Approach B uses a custom `MCPClient` class (`src/alm/mcp/mcp_client.py`) to query a Loki MCP server for domain-specific log retrieval with JSON-RPC 2.0 protocol
- **Tool definition:** Approach B defines LangChain `@tool`-decorated functions for specific Loki query patterns (file logs, text search, play recaps, log lines above) in `src/alm/tools/loki_tools.py`
- **Model serving:** Approach A deploys vLLM/LlamaStack for self-hosted inference; Approach B connects to any OpenAI-compatible endpoint via `OPENAI_API_ENDPOINT` env var (`src/alm/llm.py`), with a separate endpoint for tool-calling-capable models (`OPENAI_API_ENDPOINT_WITH_TOOL_CALLING`)
- **RAG integration:** Approach A uses pgvector for knowledge base vector search; Approach B uses a separate FAISS-based RAG service (`services/rag/`) with HuggingFace TEI for embeddings, providing "cheat sheet" context from Ansible error documentation PDFs
- **Frontend:** Approach A uses React/PatternFly; Approach B uses Gradio for both the main UI (`services/ui/`) and an annotation/evaluation interface (`services/annotation_interface/`) with DeepEval
- **Observability:** Approach A has no built-in observability; Approach B includes Arize Phoenix for LLM tracing (`src/alm/utils/phoenix.py`), Grafana for dashboards, and Alloy for log ingestion (`services/alloy/`)
- **Log management stack:** Approach B includes a full log management pipeline -- Grafana Alloy collects logs from AAP clusters, Loki stores and indexes them, Grafana provides alerting on error patterns, and the agent queries Loki via MCP for additional context

### Typical Components

- **Model serving:** Any OpenAI-compatible API endpoint (RHOAI model serving, external LLM), with separate endpoint option for tool-calling models
- **Backend:** FastAPI (`src/alm/`) with LangGraph agent orchestration, MCP client for Loki tool integration, LangChain tools
- **Frontend:** Gradio UI for log analysis dashboard (`services/ui/`), Gradio annotation interface with DeepEval for evaluation (`services/annotation_interface/`)
- **Data layer:** PostgreSQL for alert/metadata persistence, FAISS for RAG vector storage (Ansible error documentation), Loki for time-series log storage
- **Supporting:** HuggingFace TEI for text embeddings, MinIO for object storage, Arize Phoenix for LLM tracing, Grafana + Alloy for log ingestion and alerting, MCP server for Loki queries, sentence-transformers + scikit-learn for log clustering (`services/clustering/`)

---

## Approach C: Framework-less MCP-Native Agent with Provider Abstraction (from data-governance-co-pilot)

### When to Use

When the agentic app needs direct control over the agentic loop without framework dependencies, connects to a single specialized MCP server for domain-specific tool use (e.g., database governance), and benefits from the ability to switch between a self-managed agentic loop (MCP-Direct) and a delegated orchestration mode (Llama Stack) via a provider abstraction layer.

### Differences from Approach A

- **Agent framework:** Approach A uses pluggable framework runners (LlamaStack, LangGraph, CrewAI); Approach C uses no agent framework in MCP-Direct mode -- the agentic loop is hand-coded in `packages/copilot/src/copilot/providers/mcp_direct.py` using the MCP SDK (`mcp.ClientSession`) and OpenAI SDK (`AsyncOpenAI`) directly, with an alternative Llama Stack provider (`packages/copilot/src/copilot/providers/llama_stack.py`) that delegates orchestration to Llama Stack's Agents API
- **Provider abstraction:** Approach C introduces a `LLMProvider` abstract base class (`packages/copilot/src/copilot/providers/base.py`) with `MCPDirectProvider` and `LlamaStackProvider` implementations, switchable via the `COPILOT_PROVIDER_MODE` environment variable (`packages/copilot/src/copilot/providers/factory.py`); Approach A uses pluggable runners within a single framework
- **MCP integration:** Approach A uses MCP servers as general-purpose tool providers; Approach C connects to a single specialized MCP server (EDB's `pg-airman-mcp` for PostgreSQL) via the official MCP SDK's `streamablehttp_client` transport (`packages/copilot/src/copilot/providers/mcp_direct.py` line 31), with MCP tool definitions automatically converted to OpenAI function calling format (`_convert_mcp_tools_to_openai` method)
- **Tool security:** Approach C implements a hard-coded tool allowlist with Pydantic schema validation in `packages/copilot/src/copilot/providers/tool_validation.py` -- every tool call is validated against `ALLOWED_TOOLS` set and type-checked via Pydantic models (`ExecuteSqlArgs`, `ListObjectsArgs`, etc.) before execution, with fail-closed behavior (unknown tools are rejected even if MCP server advertises them); Approach A delegates tool validation to the framework runners
- **Model format detection:** Approach C supports two tool calling formats -- Nemotron's custom `<TOOLCALL>` tags parsed by `_parse_nemotron_tool_calls()` and standard OpenAI function calling -- with auto-detection from model name (`_detect_tool_call_format` in `mcp_direct.py`); configurable via `LLM_TOOL_CALL_FORMAT` env var (`auto`/`nemotron`/`openai`)
- **Governance policy:** Approach C makes data governance policy a first-class concept -- policies can be uploaded/deleted via REST API (`/policy/upload`, `/policy/status`, `/policy/delete` in `service.py`), injected into the system prompt dynamically for MCP-Direct mode (no conversation restart needed), or trigger agent recreation for Llama Stack mode (requires conversation restart per `requires_conversation_restart_on_policy_update()`)
- **MCP session resilience:** Approach C includes MCP session reconnection logic (`_reconnect_mcp` method) and retry with exponential backoff (`_retry_mcp_operation` method) for handling pod restarts and transient failures
- **Thinking tag handling:** Approach C handles Nemotron's `<think>` and `</think>` tags during streaming, separating LLM reasoning from user-facing content, with support for both `enable_reasoning=True` (show thinking) and `enable_reasoning=False` (silently discard via Nemotron's `/no_think` instruction)
- **Frontend:** Approach A uses React/PatternFly; Approach C uses SvelteKit with Vega-Lite for inline data visualizations (bar charts, pie charts, line charts) generated by the LLM in `vega-lite` code blocks (`packages/copilot/src/copilot/providers/mcp_direct.py` system prompt lines 433-466)
- **Model options:** Approach C supports two models -- NVIDIA Nemotron Nano 9B v2 (9B params, custom TOOLCALL format, MCP-Direct only) and Qwen3-14B AWQ (14B params, OpenAI function calling, both modes) -- deployed via KServe + vLLM (`helm/nemotron-model/`, `helm/qwen3-model/`)

### Typical Components

- **Model serving:** KServe + vLLM deploying either NVIDIA Nemotron Nano 9B v2 or Qwen3-14B AWQ; optional Llama Stack Distribution for delegated agent orchestration (`helm/copilot-llama-stack/`)
- **Backend:** FastAPI (`packages/copilot/`) with provider abstraction layer, direct MCP SDK + OpenAI SDK agentic loop (MCP-Direct) or Llama Stack Agents API delegation, SSE streaming, tool validation allowlist
- **Frontend:** SvelteKit (`apps/ui/`) with Vega-Lite for inline data visualizations, Markdown rendering, SQL syntax highlighting
- **Data layer:** PostgreSQL + pgvector (`helm/pgvector/`) for the governed e-commerce loyalty dataset (not used for RAG), EDB pg-airman-mcp (`helm/pg-airman-mcp/`) for MCP-based database tools
- **Supporting:** MinIO for object storage (`helm/minio/`), pgAdmin for database administration (`helm/pgadmin/`), Jupyter notebooks for model download and data verification (`notebooks/`)

---

## Approach D: CloudEvent-Driven Multi-Microservice Agent Platform (from it-self-service-agent)

### When to Use

When the agentic app requires a production-grade multi-microservice architecture with event-driven inter-service communication, multi-channel integration (Slack, email, ticketing systems), YAML-configurable agent workflows for adding new use cases without code changes, and a router-specialist agent topology where a routing agent classifies user intent and hands off to domain-specific specialist agents.

### Differences from Approach A

- **Service architecture:** Approach A is a monolithic FastAPI service; Approach D decomposes into three core microservices -- `agent-service` (LangGraph agent orchestration, knowledge bases, MCP tool integration), `request-manager` (request validation, session lifecycle, communication strategy), and `integration-dispatcher` (multi-channel delivery to Slack, email, Zammad, webhooks) -- each as separate FastAPI deployments with shared-models and shared-clients libraries (`shared-models/`, `shared-clients/`)
- **Inter-service communication:** Approach A uses direct HTTP; Approach D uses CloudEvents over Knative Eventing with a Kafka Broker (`helm/templates/knative-broker.yaml`, `helm/templates/knative-triggers.yaml`) -- events like `com.self-service-agent.request.created` and `com.self-service-agent.agent.response-ready` route between services via Knative Triggers with per-partition FIFO ordering (`kafka.eventing.knative.dev/delivery.order: ordered`) and exponential backoff retry; a mock eventing service (`mock-eventing-service/`) enables development without Knative infrastructure
- **Agent topology:** Approach A has a single agent with tool access; Approach D uses a router-specialist topology -- a `routing-agent` (`agent-service/config/agents/routing-agent.yaml`) classifies user intent (laptop refresh, email change, etc.) and hands the session off to a specialist agent (e.g., `laptop-refresh-agent` with its own MCP servers and knowledge bases); specialist agents can return users to the routing agent upon task completion via `task_complete_return_to_router`
- **YAML-driven state machines:** Approach A uses framework-provided agent configuration; Approach D defines LangGraph state machines entirely in YAML (`agent-service/config/lg-prompts/*.yaml`) with configurable states (e.g., `waiting`, `llm_processor`), transitions, prompts, temperature settings, and business fields -- the `StateMachine` class (`agent-service/src/agent_service/langgraph/lg_flow_state_machine.py`) dynamically creates `AgentState` TypedDict classes from YAML `state_schema` and builds `StateGraph` instances from YAML `states` definitions, enabling new agent workflows without code changes
- **Agent configuration:** Approach D defines each agent in a declarative YAML file (`agent-service/config/agents/<name>.yaml`) specifying `name`, `system_message`, `lg_state_machine_config` (path to LangGraph prompt YAML), `mcp_servers` (list of MCP server URIs), `knowledge_bases` (list of RAG knowledge base names), and `sampling_params` (temperature, top_p)
- **Multi-channel integration:** Approach A provides a single React/PatternFly frontend; Approach D supports multiple inbound channels -- Slack (real-time conversations via Bolt SDK), email (asynchronous notifications), Zammad (ticketing system with CloudEvent-driven ticket lifecycle), CLI, and webhooks -- managed by the `integration-dispatcher` service with per-channel handlers (`integration-dispatcher/src/integration_dispatcher/integrations/slack.py`, `email.py`, `zammad.py`, `webhook.py`) and a template engine for formatting responses per channel
- **MCP usage:** Approach A uses MCP servers as general-purpose tool providers within a single agent; Approach D deploys dedicated MCP servers for specific backend integrations -- `mcp-servers/snow/` for ServiceNow ticket operations (laptop refresh requests) and `mcp-servers/zammad/` for Zammad ticketing -- using FastMCP with shared MCP utilities (`mcp-servers/mcp-common/`); MCP servers are deployed as separate pods via ai-architecture-charts `mcp-servers` subchart (`helm/Chart.yaml`)
- **Model serving:** Both use LlamaStack; Approach D deploys via ai-architecture-charts subcharts (`llm-service` 0.5.6, `llama-stack` 0.8.5, `pgvector` 0.1.0 in `helm/Chart.yaml`) and targets Llama 3 70B for agent reasoning, with LlamaStack providing both native and OpenAI-compatible APIs (`agent-service/src/agent_service/langgraph/responses_agent.py`)
- **Knowledge bases:** Approach A uses pgvector with document upload UI; Approach D uses LlamaStack vector stores with knowledge base YAML configuration files (`agent-service/config/knowledge_bases/`) registered at startup via `KnowledgeBaseManager` (`agent-service/src/agent_service/knowledge/kb_manager.py`) -- e.g., laptop refresh policy documents and laptop options per region
- **Guardrails:** Approach A has configurable guardrails within the agent framework; Approach D optionally integrates NVIDIA NeMo Guardrails with NemoGuard JailbreakDetect NIM (`helm/nemo-guardrails/`) via TrustyAI, controlled by `USE_NEMO_GUARDRAILS` env var (`agent-service/src/agent_service/langgraph/responses_agent.py`) -- the guardrails service runs as a separate deployment with its own GPU allocation
- **Observability:** Approach A has no built-in observability; Approach D includes a comprehensive stack -- Langfuse for session-level LLM tracing (`LANGFUSE_ENABLED` env var, ClickHouse analytics backend in `helm/templates/clickhouse-deployment.yaml`, `helm/templates/langfuse-deployment.yaml`), MLflow for per-turn LLM call tracking (`agent-service/src/agent_service/langgraph/mlflow_tracking.py`), OpenTelemetry for distributed tracing across all three microservices (`tracing-config/`), and Redis for caching (`helm/templates/redis-deployment.yaml`)
- **Database schema:** Approach A uses a simple PostgreSQL schema; Approach D uses shared SQLAlchemy models with Alembic migrations (`shared-models/alembic/`) covering request sessions, delivery logs, user integration configs, and channel behavior policies -- the database is shared across all three microservices via the `shared-models` library
- **Mock services for development:** Approach D includes mock services for developing without external dependencies -- `mock-service-now/` (mock ServiceNow REST API), `mock-employee-data/` (mock employee and laptop data), `mock-eventing-service/` (lightweight CloudEvent relay replacing Knative/Kafka)
- **Evaluation pipeline:** Approach A has no built-in evaluation; Approach D includes a DeepEval-based evaluation framework (`evaluations/`) that generates synthetic conversations (`evaluations/flows/ticket_laptop_refresh/flow.py`), exports real conversations from the running system, and evaluates against business metrics (policy compliance, information gathering completeness)
- **Session management:** Approach D implements session locking with `acquire_agent_session_lock`/`release_agent_session_lock` for concurrent request handling (`agent-service/src/agent_service/main.py`), PostgreSQL-backed LangGraph checkpoint storage (`agent-service/src/agent_service/langgraph/postgres_checkpoint.py`), and session resumption across agent handoffs

### Typical Components

- **Model serving:** vLLM via ai-architecture-charts `llm-service` subchart for LLM inference (Llama 3 70B); LlamaStack via ai-architecture-charts `llama-stack` subchart for agent orchestration, knowledge base RAG, and OpenAI-compatible API
- **Backend:** Three FastAPI microservices -- `agent-service` (LangGraph state machines, agent routing, knowledge base management, MCP tool integration), `request-manager` (request normalization, session lifecycle, communication strategy), `integration-dispatcher` (multi-channel delivery with Slack, email, Zammad, webhook handlers and template engine)
- **Frontend:** CLI for direct agent interaction; Slack, email, and Zammad as conversational interfaces via the integration-dispatcher
- **Data layer:** PostgreSQL + pgvector (ai-architecture-charts `pgvector` subchart) for shared database (sessions, delivery logs, user configs) and LangGraph checkpoint storage; LlamaStack vector stores for knowledge base RAG; ClickHouse for Langfuse analytics
- **Supporting:** Knative Eventing with Kafka Broker (Strimzi-managed via `helm/templates/kafka-cluster.yaml`) for inter-service CloudEvent routing; MCP servers for ServiceNow (`mcp-servers/snow/`) and Zammad (`mcp-servers/zammad/`) via ai-architecture-charts `mcp-servers` subchart; NVIDIA NeMo Guardrails with NemoGuard JailbreakDetect NIM (`helm/nemo-guardrails/`); Langfuse for session-level LLM observability; MLflow for per-turn tracking; OpenTelemetry for distributed tracing; Redis for caching; MinIO for object storage; mock services for development without external dependencies

---

## Approach E: Operator-Managed Llama Stack Agent with Comprehensive Observability (from lls-observability)

### When to Use

When the agentic app needs operator-managed lifecycle for the Llama Stack instance (no custom backend code), standalone MCP servers deployed as separate Helm charts, Llama Guard safety shields, and comprehensive LLM observability instrumentation (distributed tracing, metrics, dashboards) as a first-class capability for audit, compliance, and performance monitoring of the entire AI stack.

### Differences from Approach A

- **Service architecture:** Approach A is a monolithic FastAPI backend managing agent lifecycle, session state, and SSE streaming; Approach E has no custom backend code -- the entire agent orchestration is delegated to a `LlamaStackDistribution` CR (`llamastack.io/v1alpha1` in `helm/03-ai-services/llama-stack-instance/templates/llamastackdistribution.yaml`) managed by the `llama-stack-operator` (`helm/01-operators/llama-stack-operator/`)
- **Operator lifecycle:** Approach E uses the Llama Stack Kubernetes operator to manage the Llama Stack instance lifecycle (deployment, scaling, upgrades); Approach A deploys Llama Stack as a standalone server within a custom application
- **MCP server deployment:** Approach A integrates MCP servers within the application; Approach E deploys each MCP server as a separate Helm chart (`helm/04-mcp-servers/mcp-weather/`, `helm/04-mcp-servers/hr-api/`, `helm/04-mcp-servers/openshift-mcp/`) with independent lifecycle, NetworkPolicies, and RBAC -- the OpenShift MCP server (`quay.io/hveeradh/ocp-mcp-server`) has read-only ClusterRole bindings for pods, services, deployments, routes, etc. (`helm/04-mcp-servers/openshift-mcp/values.yaml`)
- **MCP integration:** Approach E connects MCP servers to Llama Stack via the `remote::model-context-protocol` tool runtime provider, with MCP server URIs configured in `helm/03-ai-services/llama-stack-instance/values.yaml` under `mcpServers` and rendered as `mcp::<name>` toolgroups with `/sse` endpoint suffix in the ConfigMap (`helm/03-ai-services/llama-stack-instance/templates/configmap.yaml`)
- **Safety:** Approach A has configurable guardrails within the agent framework; Approach E deploys a dedicated Llama Guard 3-1B model via KServe InferenceService (`helm/03-ai-services/llama-guard/`) with its own vLLM ServingRuntime and GPU allocation, connected to Llama Stack as the `inline::llama-guard` safety provider with a registered shield (`shield_id: meta-llama/Llama-Guard-3-1B` in the ConfigMap)
- **Model serving:** Approach A deploys vLLM/LlamaStack within the application; Approach E deploys Llama 3.2 3B Instruct via a standalone KServe InferenceService with a custom OTel-instrumented vLLM image (`quay.io/rcarrata/vllm-otlp-tracing`) that sends traces directly to the OTel collector via `--otlp-traces-endpoint` ServingRuntime arg (`helm/03-ai-services/llama3.2-3b/values.yaml`), plus support for both GPU (`nvidia.com/gpu`) and Intel Xeon CPU (`VLLM_CPU_KVCACHE_SPACE`) device types with separate image, resource, node selector, and affinity configurations per device
- **Observability stack:** Approach A has no built-in observability; Approach E includes a comprehensive observability stack deployed across 5 OLM-managed operators (`helm/01-operators/`) and 5 observability components (`helm/02-observability/`):
  - **OpenTelemetry Collector** -- central collector in `observability-hub` namespace (`helm/02-observability/otel-collector/otel-collector.yaml`) receives OTLP traces/metrics from sidecars and scrapes Prometheus metrics from vLLM endpoints; sidecar collectors for both LlamaStack (`otel-collector-llamastack-sidecar.yaml`, traces pipeline) and vLLM (`otel-collector-vllm-sidecar.yaml`, traces + metrics pipelines with `localhost:8000` Prometheus scraping) injected via `sidecar.opentelemetry.io/inject` pod annotation
  - **TempoStack** -- distributed tracing backend (`helm/02-observability/tempo/`) with MinIO S3-compatible storage, multi-tenant mode (`tenants.mode: openshift`, tenant `dev`), and Gateway for authenticated trace querying
  - **Grafana** -- operator-managed instance (`helm/02-observability/grafana/`) with Prometheus (via Thanos Querier) and Tempo datasources, pre-built vLLM dashboard loaded from `opendatahub-io/llama-stack-demos` GitHub repo via `GrafanaDashboard` CR URL reference
  - **User Workload Monitoring** -- PodMonitors (`helm/02-observability/uwm/`) scraping vLLM metrics from pods matching `app: safety | llama32-3b | granite-8b | llama31-70b` labels at 30s intervals, plus KServe predictor pods (`app: isvc.llama3-2-3b-predictor`) at 15s intervals
  - **Distributed Tracing UI Plugin** -- OpenShift Console plugin (`helm/02-observability/distributed-tracing-ui-plugin/`) for in-console trace visualization
- **Namespace topology:** Approach A deploys in a single namespace; Approach E uses at least 2 namespaces -- `llama-serve` for AI services and MCP servers, `observability-hub` for the observability stack (Tempo, Grafana, central OTel collector), plus `openshift-monitoring` and `openshift-user-workload-monitoring` for cluster monitoring ConfigMaps
- **LlamaStack configuration:** Approach E defines the full Llama Stack configuration in a Helm-templated ConfigMap (`helm/03-ai-services/llama-stack-instance/templates/configmap.yaml`) including: `remote::vllm` inference providers (separate for chat and safety models), `inline::sentence-transformers` (all-MiniLM-L6-v2), `inline::milvus` vector_io with SQLite-backed kvstore, `inline::llama-guard` safety, `inline::meta-reference` agents with SQLite persistence, `inline::meta-reference` telemetry with configurable sinks (console, sqlite, OTEL via `OTEL_TRACE_ENDPOINT`/`OTEL_METRIC_ENDPOINT` env vars), `remote::model-context-protocol` tool runtime, `remote::brave-search`/`remote::tavily-search`/`remote::wolfram-alpha` tool runtimes, and `inline::rag-runtime` for RAG
- **MaaS support:** Approach E includes optional Model-as-a-Service integration (`maas.enabled: true` in values.yaml) to add a remote vLLM provider pointing to a LiteLLM endpoint for larger models like Llama-4-Scout-17B without local GPU resources
- **Frontend:** Approach A uses React/PatternFly; Approach E uses the Llama Stack Playground (`helm/03-ai-services/llama-stack-playground/`, Streamlit on port 8501) with chat, agents, and tools features enabled, connecting to the LlamaStackDistribution service (`http://llama-stack-instance-service:8321`)
- **Demo content:** Approach A provides an interactive web UI; Approach E includes 4 Jupyter notebooks (`docs/notebooks/`) demonstrating different interaction patterns: simple RAG (`1-simpleRAG.ipynb`), evaluations (`2-evals.ipynb`), LangGraph agent (`3-langgraph-agent.ipynb`), and LangGraph tools (`4-langgraph-tools.ipynb`)
- **Phased deployment:** Approach E organizes Helm charts into 4 dependency phases -- Phase 1: Operators (cluster-observability-operator, grafana-operator, otel-operator, tempo-operator, llama-stack-operator), Phase 2: Observability (tempo, otel-collector, grafana, uwm, distributed-tracing-ui-plugin), Phase 3: AI Services (llama3.2-3b, llama-guard, llama-stack-instance, llama-stack-playground), Phase 4: MCP Servers (mcp-weather, hr-api, openshift-mcp) -- with `Makefile` targets `install-operators`, `deploy-observability`, `deploy-ai`, and `install-all` orchestrating the sequence via shell scripts

### Typical Components

- **Model serving:** KServe InferenceService with custom OTel-instrumented vLLM image (`quay.io/rcarrata/vllm-otlp-tracing`) for Llama 3.2 3B Instruct with built-in tracing (`--otlp-traces-endpoint`, `--collect-detailed-traces all`); separate KServe InferenceService for Llama Guard 3-1B safety model; both support GPU and Intel Xeon CPU device types via conditional Helm values
- **Backend:** LlamaStackDistribution CR managed by llama-stack-operator -- no custom backend code; Llama Stack provides agents, inference, safety, vector_io, tool_runtime, eval, scoring, datasetio, and telemetry APIs
- **Frontend:** Llama Stack Playground (Streamlit, `quay.io/rh-aiservices-bu/llama-stack-playground:0.2.11`) with chat, agent, and tool UI; Jupyter notebooks for RAG, evaluation, and LangGraph agent demos
- **Data layer:** Inline Milvus (SQLite-backed) within Llama Stack for vector storage; inline sentence-transformers (all-MiniLM-L6-v2) for embeddings; SQLite for agent persistence, responses, eval, and metadata stores
- **Supporting:** 5 OLM-managed operators (Cluster Observability, Grafana, OpenTelemetry, Tempo, Llama Stack); central OTel Collector in `observability-hub` with Prometheus receiver scraping vLLM metrics and OTLP receiver for traces; OTel sidecar collectors for LlamaStack (traces) and vLLM (traces + metrics); TempoStack with MinIO for distributed trace storage; Grafana with Prometheus and Tempo datasources and pre-built vLLM dashboard; User Workload Monitoring PodMonitors for vLLM pods; Distributed Tracing UI Plugin for OpenShift Console; 3 standalone MCP servers (weather, HR enterprise API, OpenShift/Kubernetes ops) deployed as separate Helm charts with NetworkPolicies and RBAC

---

## Choosing Between Approaches

| Criteria | Approach A (Conversational Agent Platform) | Approach B (Event-Driven Agent Pipeline) | Approach C (MCP-Native Agent with Provider Abstraction) | Approach D (CloudEvent-Driven Multi-Microservice Platform) | Approach E (Operator-Managed Agent with Observability) |
|----------|-------------------------------------------|------------------------------------------|--------------------------------------------------------|-----------------------------------------------------------|-------------------------------------------------------|
| Triggering | User-initiated conversation | External events (Grafana alerts, webhooks) | User-initiated conversation | Multi-channel (Slack, email, Zammad, CLI, webhooks) | User-initiated via Playground UI or Jupyter notebooks |
| Agent framework | Multi-framework (LlamaStack, LangGraph, CrewAI) | LangGraph only | None (MCP-Direct) or Llama Stack (delegated) | LangGraph with YAML-configurable state machines | LlamaStack (operator-managed LlamaStackDistribution CR) |
| Agent topology | Single agent with tool access | Main graph with nested sub-agents | Single agent with tool allowlist | Router agent + specialist agents (routing-agent hands off to domain agents) | Single agent with MCP tool access via LlamaStack |
| Pipeline | Open-ended conversational tool use | Fixed domain-specific multi-step flow | Domain-specific conversational tool use (database governance) | Configurable per-agent state machine flows defined in YAML | Open-ended conversational tool use with full trace visibility |
| Service architecture | Monolithic FastAPI | Monolithic FastAPI + services | Monolithic FastAPI | Three microservices (agent-service, request-manager, integration-dispatcher) | No custom backend -- operator-managed LlamaStackDistribution CR + standalone MCP Helm charts |
| Inter-service communication | Direct HTTP | Direct HTTP | Direct HTTP | CloudEvents via Knative Eventing + Kafka Broker | Direct HTTP (LlamaStack to MCP servers via SSE) |
| Model serving | Self-hosted vLLM/LlamaStack | API-only (OpenAI-compatible endpoint) | KServe + vLLM with optional Llama Stack | vLLM + LlamaStack via ai-architecture-charts subcharts | KServe + custom OTel-instrumented vLLM + operator-managed LlamaStack (GPU and Xeon CPU device types) |
| Frontend | React/PatternFly | Gradio | SvelteKit + Vega-Lite | CLI + Slack + email + Zammad (no custom web UI) | Llama Stack Playground (Streamlit) + Jupyter notebooks |
| RAG | pgvector knowledge bases | FAISS cheat sheet from domain docs | None (database accessed via MCP tools) | LlamaStack vector stores with YAML-configured knowledge bases | Inline Milvus (SQLite-backed) with inline sentence-transformers |
| Guardrails | Configurable within agent framework | Not included | Not included | NVIDIA NeMo Guardrails + NemoGuard JailbreakDetect NIM (optional) | Llama Guard 3-1B via dedicated KServe InferenceService |
| Observability | Not included | Arize Phoenix + Grafana + Alloy | Not included | Langfuse + MLflow + OpenTelemetry + ClickHouse | Full stack: OTel sidecars (vLLM + LlamaStack), TempoStack, Grafana (vLLM dashboard), UWM PodMonitors, OCP Distributed Tracing UI Plugin |
| Evaluation | Not included | Not included | Not included | DeepEval-based evaluation pipeline with synthetic and real conversations | Jupyter notebook for evals + LlamaStack inline eval/scoring providers |
| Tool security | Framework-managed | Framework-managed | Hard-coded allowlist + Pydantic validation | Framework-managed via LlamaStack + MCP require_approval config | Framework-managed via LlamaStack; OpenShift MCP server uses read-only RBAC ClusterRole |
| Best for | General-purpose agent with interactive tool use | Automated domain-specific analysis pipelines | Domain-specific agent with direct MCP integration and switchable orchestration modes | Production enterprise IT self-service with multi-channel input, extensible YAML-driven agent workflows, and event-driven microservice architecture | Observability-first agent deployment requiring end-to-end tracing, metrics, and dashboards for LLM audit, compliance, and performance monitoring with zero custom backend code |
