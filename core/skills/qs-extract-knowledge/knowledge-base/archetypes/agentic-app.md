---
name: agentic-app
description: "Agent-based AI app with tool use, multi-framework runners, and orchestrated workflows on RHOAI"
summary: "Archetype for deploying AI agents on RHOAI that reason, invoke tools via MCP protocol, and orchestrate multi-step workflows -- Approach A (ai-virtual-agent) provides user-initiated conversational platform with pluggable multi-framework runners (LlamaStack, LangGraph, CrewAI) and configurable guardrails, Approach B (ansible-log-analysis) provides event-driven LangGraph pipeline triggered by Grafana alerts with nested sub-agents (main graph -> get_more_context_agent -> loki_agent) following fixed domain flow, and Approach C (data-governance-co-pilot) provides framework-less MCP-native agent with LLMProvider abstraction (MCPDirectProvider self-managed loop vs LlamaStackProvider delegated orchestration switchable via COPILOT_PROVIDER_MODE). Choose over rag-chatbot when AI must take actions beyond document retrieval (API calls, dynamic tool selection, multi-step reasoning) and over model-serving-app when an orchestration layer managing agent state, tool dispatch, and multi-turn reasoning wraps the served model; pick A for general-purpose interactive tool use, B for automated domain-specific analysis triggered by external events, C for domain-specific MCP-native agents needing switchable orchestration modes and hard-coded tool security with Pydantic-validated ALLOWED_TOOLS allowlist (fail-closed). A stacks vLLM/LlamaStack with function calling behind FastAPI managing agent lifecycle, session state, and SSE streaming with React/PatternFly, PostgreSQL/pgvector, and MCP tool servers; B uses dual OpenAI-compatible endpoints (separate for tool-calling models), Gradio UI with DeepEval annotation, FAISS RAG with HuggingFace TEI, and Arize Phoenix + Grafana + Alloy observability; C deploys KServe + vLLM (Nemotron Nano 9B or Qwen3-14B AWQ), auto-converts MCP tools to OpenAI function calling format, injects governance policies via REST API (/policy/upload), and renders Vega-Lite visualizations in SvelteKit. Medium-to-high complexity requiring model serving with function calling support and a full agent orchestration layer; B adds deployment complexity with nested sub-agent topology and full log management stack (Alloy collects, Loki stores, Grafana alerts); C requires MCP session reconnection with exponential backoff for pod restarts and handles dual tool calling formats (Nemotron custom TOOLCALL tags vs standard OpenAI) with auto-detection from model name; simple prompt-response or document-only QA should use model-serving-app or rag-chatbot instead."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, patternfly, postgresql, python, gradio, langchain, langgraph, sveltekit, vega-lite, mcp, openai-sdk, pydantic]
  ai_pattern: [agents, rag, guardrails, model-serving, embeddings, evaluation, tool-calling, governance]
  platform: [rhoai, openshift, vllm, tei, kserve, llama-stack]
  data_layer: [pgvector, faiss]
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

## Choosing Between Approaches

| Criteria | Approach A (Conversational Agent Platform) | Approach B (Event-Driven Agent Pipeline) | Approach C (MCP-Native Agent with Provider Abstraction) |
|----------|-------------------------------------------|------------------------------------------|--------------------------------------------------------|
| Triggering | User-initiated conversation | External events (Grafana alerts, webhooks) | User-initiated conversation |
| Agent framework | Multi-framework (LlamaStack, LangGraph, CrewAI) | LangGraph only | None (MCP-Direct) or Llama Stack (delegated) |
| Agent topology | Single agent with tool access | Main graph with nested sub-agents | Single agent with tool allowlist |
| Pipeline | Open-ended conversational tool use | Fixed domain-specific multi-step flow | Domain-specific conversational tool use (database governance) |
| Model serving | Self-hosted vLLM/LlamaStack | API-only (OpenAI-compatible endpoint) | KServe + vLLM with optional Llama Stack |
| Frontend | React/PatternFly | Gradio | SvelteKit + Vega-Lite |
| RAG | pgvector knowledge bases | FAISS cheat sheet from domain docs | None (database accessed via MCP tools) |
| Observability | Not included | Arize Phoenix + Grafana + Alloy | Not included |
| Tool security | Framework-managed | Framework-managed | Hard-coded allowlist + Pydantic validation |
| Best for | General-purpose agent with interactive tool use | Automated domain-specific analysis pipelines | Domain-specific agent with direct MCP integration and switchable orchestration modes |
