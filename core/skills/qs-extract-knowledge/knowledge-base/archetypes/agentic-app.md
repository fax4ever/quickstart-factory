---
name: agentic-app
description: "Agent-based AI app with tool use, multi-framework runners, and orchestrated workflows on RHOAI"
summary: "Archetype for deploying AI agents on RHOAI that reason, invoke tools via MCP protocol, and orchestrate multi-step workflows -- Approach A (ai-virtual-agent) provides a user-initiated conversational platform with pluggable multi-framework runners (LlamaStack, LangGraph, CrewAI) and configurable guardrails, while Approach B (ansible-log-analysis) provides an event-driven LangGraph pipeline triggered by Grafana alerts with nested sub-agents following a fixed domain flow (detect, classify, route, gather Loki context via MCP, remediate). Choose over rag-chatbot when AI must take actions beyond document retrieval (API calls, dynamic tool selection, multi-step reasoning) and over model-serving-app when an orchestration layer managing agent state, tool dispatch, and multi-turn reasoning wraps the served model; pick Approach A for general-purpose interactive tool use and Approach B for automated domain-specific analysis pipelines triggered by external events. Approach A stacks vLLM/LlamaStack model serving with function calling behind FastAPI managing agent lifecycle, session state, and SSE streaming, with React/PatternFly frontend, PostgreSQL/pgvector, MCP tool servers, and ingestion pipelines; Approach B uses dual OpenAI-compatible endpoints (separate for tool-calling models), Gradio UI with DeepEval annotation, FAISS RAG with HuggingFace TEI, nested sub-agents (main graph to get_more_context_agent to loki_agent), and Arize Phoenix + Grafana + Alloy observability. Medium-to-high complexity archetype requiring model serving with function calling support and a full agent orchestration layer; Approach B adds deployment complexity with its nested sub-agent topology and log management stack (Alloy, Loki, Grafana), and a simple prompt-response or document-only QA should use model-serving-app or rag-chatbot instead."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, patternfly, postgresql, python, gradio, langchain, langgraph]
  ai_pattern: [agents, rag, guardrails, model-serving, embeddings, evaluation]
  platform: [rhoai, openshift, vllm, tei]
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

## Choosing Between Approaches

| Criteria | Approach A (Conversational Agent Platform) | Approach B (Event-Driven Agent Pipeline) |
|----------|-------------------------------------------|------------------------------------------|
| Triggering | User-initiated conversation | External events (Grafana alerts, webhooks) |
| Agent framework | Multi-framework (LlamaStack, LangGraph, CrewAI) | LangGraph only |
| Agent topology | Single agent with tool access | Main graph with nested sub-agents |
| Pipeline | Open-ended conversational tool use | Fixed domain-specific multi-step flow |
| Model serving | Self-hosted vLLM/LlamaStack | API-only (OpenAI-compatible endpoint) |
| Frontend | React/PatternFly | Gradio |
| RAG | pgvector knowledge bases | FAISS cheat sheet from domain docs |
| Observability | Not included | Arize Phoenix + Grafana + Alloy |
| Best for | General-purpose agent with interactive tool use | Automated domain-specific analysis pipelines |
