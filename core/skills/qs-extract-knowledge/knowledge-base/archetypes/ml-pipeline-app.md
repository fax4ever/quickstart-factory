---
name: ml-pipeline-app
description: "Trains custom ML models via Kubeflow Pipelines with feature engineering, batch scoring, and online serving"
summary: "Covers the full ML lifecycle on RHOAI — data processing, feature engineering via Feast Operator (offline Parquet, online PostgreSQL+pgvector ANN), custom model training through Kubeflow Pipelines (Data Science Pipelines), batch scoring, and prediction serving — with FastAPI backend, React frontend, MinIO artifact storage, and optional Strimzi Kafka streaming. Pick over model-serving-app when custom training pipelines and Feast feature engineering are central (not just deploying pre-trained models via KServe), over rag-chatbot when vector search returns ranked entities by embedding similarity (not document chunks for LLM grounding), and over agentic-app when no agent orchestration framework manages tool dispatch. Source example (product-recommender-system) demonstrates a three-stage Kubeflow pipeline (load Feast data, train two-tower PyTorch model, generate candidate embeddings), 8+ Feast feature views for user/item/interaction/embedding data, hybrid semantic/symbolic search via Feast retrieve_online_documents with BGE text and CLIP image embeddings, user-item cosine similarity recommendations, and external LLM integration at /v1/chat/completions for review summarization. Key risk is misclassification — this archetype requires custom model training pipelines and batch scoring infrastructure (medium-to-high complexity); if the app only deploys pre-trained models or retrieves documents for LLM grounding, use model-serving-app or rag-chatbot instead."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, postgresql, python, pytorch, kubeflow-pipelines, feast, minio, clip, bge, strimzi-kafka]
  ai_pattern: [data-pipeline, embeddings, vector-search, model-serving, recommendation, semantic-search]
  platform: [rhoai, openshift, openshift-ai-dsp]
  data_layer: [pgvector]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "E-commerce product recommender with Kubeflow Pipelines training workflow for two-tower PyTorch model, Feast feature store (offline Parquet, online PostgreSQL+pgvector), CLIP/BGE embedding generation, batch scoring pushed to Feast online store, hybrid semantic/symbolic search, and LLM-based review summarization via external API"
    approach: "A"
---

# ML Pipeline App

## Overview

An ML pipeline app trains, evaluates, and serves custom machine learning models on Red Hat OpenShift AI using Kubeflow Pipelines (Data Science Pipelines) for orchestrated training workflows and feature stores for feature engineering and online serving. Unlike model-serving-app which deploys pre-trained models or rag-chatbot which retrieves documents for LLM grounding, this archetype focuses on the full ML lifecycle: data processing, feature engineering, model training, batch scoring, and prediction serving. On RHOAI, this pattern demonstrates Data Science Pipelines for workflow orchestration, Feast Operator for feature management, and PostgreSQL+pgvector for both feature storage and vector similarity search.

## Typical Components

- **Model serving:** Custom-trained models served through a feature store online layer (Feast + pgvector ANN) or via direct inference endpoints, with optional external LLM integration for supplementary text generation tasks
- **Backend:** FastAPI managing prediction serving, search endpoints, and user interaction tracking, reading pre-computed predictions and embeddings from the feature store online store
- **Frontend:** React providing product/entity browsing, search (text and image), and recommendation display
- **Data layer:** PostgreSQL+pgvector as both relational store and vector database, Feast feature store with offline (Parquet) and online (PostgreSQL) stores for feature management and ANN retrieval
- **Supporting:** Kubeflow Pipelines (OpenShift AI Data Science Pipelines) for training workflow orchestration, MinIO for model artifact and dataset storage, optional Kafka (Strimzi) for event streaming

## When to Use

- **Business problem:** Building an application that requires training custom ML models on domain-specific data (not just calling pre-trained LLMs) and serving the resulting predictions or embeddings at scale -- such as recommendation engines, search ranking, fraud detection, or demand forecasting
- **RHOAI capabilities:** Demonstrates Data Science Pipelines (Kubeflow Pipelines) for orchestrated training workflows, Feast Operator for feature store management, PostgreSQL+pgvector for vector similarity search, and the full train-then-serve ML lifecycle on OpenShift
- **Scale/complexity:** Medium to high complexity; suitable when the application requires custom model training pipelines, feature engineering, and batch scoring infrastructure beyond simple API calls to pre-trained models

## Example Quickstarts

| Quickstart | What It Demonstrates |
|------------|---------------------|
| product-recommender-system | E-commerce product recommender with Kubeflow Pipelines three-stage training workflow (load data from Feast, train two-tower PyTorch model, generate candidate embeddings), Feast feature store with 8+ feature views for user/item/interaction/embedding data, hybrid semantic/symbolic product search via Feast `retrieve_online_documents` with BGE text and CLIP image embeddings, personalized recommendations via user-item embedding cosine similarity, and LLM-powered review summarization via external API (`/v1/chat/completions`) |

## Decision Criteria

### vs model-serving-app

Pick **ml-pipeline-app** when the quickstart includes custom model training workflows (Kubeflow Pipelines), feature engineering (Feast, custom data processing), and batch scoring -- the value is in the ML lifecycle, not just deploying a pre-trained model. Pick **model-serving-app** when deploying pre-trained models (LLMs, detection models) via KServe without custom training.

### vs rag-chatbot

Pick **ml-pipeline-app** when vector search serves pre-computed embeddings from trained models for recommendation or entity discovery (not document retrieval for LLM grounding). The query returns entities (products, users) ranked by embedding similarity, not document chunks injected into an LLM prompt. Pick **rag-chatbot** when the core interaction is document-grounded Q&A where retrieved text augments LLM generation.

### vs agentic-app

Pick **ml-pipeline-app** when the AI component is a trained ML model producing predictions or embeddings, with no agent framework managing tool dispatch or multi-step reasoning. Pick **agentic-app** when the application uses an agent orchestration layer (LangGraph, LlamaStack, CrewAI) to reason and call tools.
