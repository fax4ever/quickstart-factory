---
name: agentic-app
description: "Agent-based AI app with tool use, multi-framework runners, and orchestrated workflows on RHOAI"
summary: "Archetype for deploying AI agents on RHOAI that reason, invoke tools via MCP protocol, and orchestrate multi-step workflows for customer interaction automation and internal workflow scenarios of medium-to-high complexity. Choose over rag-chatbot when the AI must take actions beyond document retrieval (API calls, dynamic tool selection, multi-step reasoning) and over model-serving-app when an orchestration layer managing agent state, tool dispatch, and multi-turn reasoning wraps the served model endpoint. Architecture stacks vLLM/LlamaStack model serving with tool/function calling behind FastAPI managing agent lifecycle, session state, and SSE streaming, with React/PatternFly frontend, PostgreSQL/pgvector for persistence and knowledge-base vector search, MCP tool servers, configurable guardrails, and ingestion pipelines -- the ai-virtual-agent reference implements pluggable multi-framework runners (LlamaStack, LangGraph, CrewAI). Medium-to-high complexity archetype requiring both model serving with function calling support and a full agent orchestration layer with session management; a simple prompt-response flow or document-only QA should use model-serving-app or rag-chatbot instead."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, patternfly, postgresql, python]
  ai_pattern: [agents, rag, guardrails, model-serving]
  platform: [rhoai, openshift, vllm]
  data_layer: [pgvector]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Multi-runner agent platform (LlamaStack, LangGraph, CrewAI) with MCP tool integration, guardrails, and RAG knowledge bases"
    approach: "A"
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

## Decision Criteria

### vs rag-chatbot

Pick **agentic-app** when the AI needs to take actions beyond retrieval -- calling external APIs, executing multi-step workflows, or using tools dynamically selected at runtime. Pick **rag-chatbot** when the primary interaction is question-answering grounded in uploaded documents, without tool orchestration or multi-step agent reasoning.

### vs model-serving-app

Pick **agentic-app** when the application includes an orchestration layer that manages agent state, tool dispatch, and multi-turn reasoning on top of the served model. Pick **model-serving-app** when the focus is on deploying and exposing a model endpoint (KServe/vLLM) without an agent framework wrapping it.
