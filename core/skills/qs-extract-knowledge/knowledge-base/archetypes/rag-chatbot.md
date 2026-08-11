---
name: rag-chatbot
description: "Conversational AI app that answers questions using retrieval-augmented generation over user documents"
summary: "Grounds LLM responses in user-uploaded documents by chunking, embedding into a vector store (pgvector or GPU-accelerated Milvus), and performing similarity search at query time to provide source-grounded conversational Q&A rather than generic LLM output on RHOAI/OpenShift. Choose over agentic-app when the core value is document-grounded Q&A without external tool calls or multi-step agent reasoning; choose over model-serving-app when retrieval-augmented answers via vector search are needed beyond direct inference — Approach A (ai-virtual-agent) suits lightweight custom-built RAG with FastAPI+LlamaStack, pgvector, K8s Job ingestion, and 1-2 GPUs, while Approach B (aml-rag-nvidia) suits enterprise document-heavy RAG using NVIDIA RAG Blueprint with NV-Ingest (OCR, table/graphic detection, VLM captioning), GPU-accelerated Milvus, 4 KServe/vLLM models (Nemotron-Super-49B-FP8, VLM, embedding, reranking), and 3-5 H100/A100 GPUs with optional MIG partitioning. Approach A integrates via LlamaStack RAG tool with MinIO/S3 storage; Approach B requires embedding and ranking translation proxies to convert NIM API formats to vLLM-compatible formats, NGC cloud-hosted NIMs for document detection/OCR (NGC API key required), Redis for NV-Ingest task queue, ODF ObjectBucketClaim, and OpenTelemetry+Grafana+Tempo observability. Key archetype boundary: if the app needs dynamic tool selection or multi-step workflow orchestration beyond retrieval, use agentic-app instead; Approach B's hybrid processing (local KServe/vLLM + NGC cloud NIMs) creates external cloud dependency, and its GPU-accelerated Milvus indexing/search requires explicit enablement in charts/ingest/values.yaml."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, patternfly, postgresql, python, nvidia-rag-blueprint, redis]
  ai_pattern: [rag, embeddings, vector-search, model-serving, multimodal]
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

## Choosing Between Approaches

| Criteria | Approach A (Custom-built) | Approach B (NVIDIA Blueprint) |
|----------|--------------------------|-------------------------------|
| RAG pipeline | Custom FastAPI + LlamaStack | NVIDIA RAG Server pre-built container |
| Document processing | Simple chunking pipeline | NV-Ingest with OCR, table/graphic detection, VLM captioning |
| Vector database | pgvector (CPU) | Milvus (GPU-accelerated) |
| Models required | 1-2 (LLM + optional embedding) | 4 (LLM, VLM, embedding, reranking) |
| GPU requirements | Low (1-2 GPUs) | High (3-5 H100/A100 GPUs, MIG optional) |
| External dependencies | None | NGC API key for cloud-hosted NV-Ingest NIMs |
| Observability | Not included | Full stack (OpenTelemetry, Grafana, Tempo) |
| Best for | Lightweight RAG within a broader app | Enterprise document-heavy RAG with GPU resources |
