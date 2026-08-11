---
name: rag-chatbot
description: "Conversational AI app that answers questions using retrieval-augmented generation over user documents"
summary: "Grounds LLM responses in user-uploaded documents by chunking, embedding into pgvector, and performing similarity search at query time to provide source-grounded conversational Q&A rather than generic LLM output. Choose over agentic-app when the core value is document-grounded Q&A without external tool calls or multi-step agent reasoning; choose over model-serving-app when retrieval-augmented answers via vector search are needed beyond direct model inference — suitable for low-to-medium complexity scenarios on RHOAI/OpenShift. Stack combines vLLM or LlamaStack for both chat inference and embedding generation, FastAPI for knowledge base CRUD/document ingestion/chat sessions, React/PatternFly for document upload and conversational UI, a Kubernetes Job or background task for the chunking/embedding pipeline, and MinIO/S3 for raw document storage. Key boundary: if the app needs to dynamically select tools or orchestrate multi-step workflows beyond retrieval, it belongs in the agentic-app archetype — the ai-virtual-agent reference (Approach A) demonstrates this boundary by integrating RAG via LlamaStack RAG tool and pgvector within a broader agent platform."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, patternfly, postgresql, python]
  ai_pattern: [rag, embeddings, vector-search, model-serving]
  platform: [rhoai, openshift, vllm]
  data_layer: [pgvector]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Knowledge base management with document upload, pgvector vector storage, and LlamaStack RAG tool integration for grounded Q&A within an agent platform"
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

## Decision Criteria

### vs agentic-app

Pick **rag-chatbot** when the core value is document-grounded Q&A and the app does not need to call external tools or orchestrate multi-step workflows. Pick **agentic-app** when the AI needs to dynamically select and invoke tools, manage multi-step reasoning, or take actions beyond retrieval.

### vs model-serving-app

Pick **rag-chatbot** when the application needs to ground LLM responses in user documents via vector search. Pick **model-serving-app** when the focus is on exposing a model endpoint for direct inference without a retrieval layer.
