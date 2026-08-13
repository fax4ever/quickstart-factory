---
name: ml-pipeline-app
description: "Trains custom ML models via Kubeflow Pipelines with feature engineering, batch scoring, and online serving"
summary: "Covers the full ML lifecycle on RHOAI — data processing, feature engineering via Feast Operator (offline Parquet, online PostgreSQL+pgvector), custom model training through Kubeflow Pipelines (Data Science Pipelines), batch scoring, and prediction serving — with FastAPI backend, React frontend, MinIO artifact storage, and optional Strimzi Kafka streaming. Pick over model-serving-app when custom training pipelines and Feast feature engineering are central (not just deploying pre-trained models via KServe), over rag-chatbot when vector search returns ranked entities by embedding similarity (not document chunks for LLM grounding), and over agentic-app when no agent orchestration framework manages tool dispatch; Approach A (product-recommender-system) suits PyTorch two-tower models with 8+ Feast feature views, CLIP/BGE hybrid search via Feast retrieve_online_documents, user-item cosine similarity recommendations, and external LLM integration at /v1/chat/completions for review summarization, while Approach B (spending-transaction-monitor) suits scikit-learn KNN collaborative filtering deployed via KServe InferenceService with MLServer sklearn runtime (RawDeployment mode, MinIO model storage) with dual recommendation engine (MLAlertRecommendationService + LLM-based AlertRecommendationService fallback via LlamaStack for cold-start users). Approach A runs a 3-stage Kubeflow pipeline (load Feast data, train two-tower PyTorch model, generate candidate embeddings) with embeddings as primary recommendation mechanism; Approach B runs a 5-stage pipeline (prepare data, train KNN, save to MinIO, optionally register in Model Registry, deploy as KServe InferenceService) with automatic staleness detection and on-demand retraining, background recommendation caching (24-hour TTL), 4-notebook interactive development workflow, sentence-transformers (all-MiniLM-L6-v2) for rule deduplication only, DSPA Helm resource for pipeline infrastructure, and companion LangGraph agent pipeline for NL-to-SQL alert rule processing. Key risk is misclassification — this archetype requires custom model training pipelines and batch scoring infrastructure (medium-to-high complexity); if the app only deploys pre-trained models or retrieves documents for LLM grounding, use model-serving-app or rag-chatbot instead."
metadata:
  type: archetype
tags:
  tech_stack: [fastapi, react, postgresql, python, pytorch, kubeflow-pipelines, feast, minio, clip, bge, strimzi-kafka, scikit-learn, langchain, langgraph, llama-stack-client, keycloak, sentence-transformers, alembic, nginx]
  ai_pattern: [data-pipeline, embeddings, vector-search, model-serving, recommendation, semantic-search, anomaly-detection, collaborative-filtering]
  platform: [rhoai, openshift, openshift-ai-dsp, kserve, mlserver]
  data_layer: [pgvector]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "E-commerce product recommender with Kubeflow Pipelines training workflow for two-tower PyTorch model, Feast feature store (offline Parquet, online PostgreSQL+pgvector), CLIP/BGE embedding generation, batch scoring pushed to Feast online store, hybrid semantic/symbolic search, and LLM-based review summarization via external API"
    approach: "A"
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "KNN collaborative filtering model trained via 5-stage Kubeflow Pipeline (prepare data from PostgreSQL, train KNN model, save to MinIO with MLServer-compatible artifacts, optional Model Registry registration, deploy as KServe InferenceService with MLServer sklearn runtime in RawDeployment mode), consumed by MLAlertRecommendationService for personalized alert recommendations with automatic fallback to LLM-based recommendations, combined with LangGraph agent pipelines for NL-to-SQL alert rule processing"
    approach: "B"
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
| spending-transaction-monitor | KNN collaborative filtering for alert recommendations with 5-stage Kubeflow Pipeline (prepare data from PostgreSQL, train sklearn KNN model, save to MinIO with MLServer-compatible artifacts, optional Model Registry registration, deploy as KServe InferenceService with MLServer sklearn runtime in RawDeployment mode), `MLAlertRecommendationService` consuming KServe-served model predictions for personalized user-specific alert rule suggestions with automatic fallback to LLM-based `AlertRecommendationService`, background recommendation caching (`BackgroundRecommendationService` with 24-hour TTL), and Jupyter notebooks (4-notebook series: train, save, deploy, cleanup) as the development-time training workflow |

## Decision Criteria

### vs model-serving-app

Pick **ml-pipeline-app** when the quickstart includes custom model training workflows (Kubeflow Pipelines), feature engineering (Feast, custom data processing), and batch scoring -- the value is in the ML lifecycle, not just deploying a pre-trained model. Pick **model-serving-app** when deploying pre-trained models (LLMs, detection models) via KServe without custom training.

### vs rag-chatbot

Pick **ml-pipeline-app** when vector search serves pre-computed embeddings from trained models for recommendation or entity discovery (not document retrieval for LLM grounding). The query returns entities (products, users) ranked by embedding similarity, not document chunks injected into an LLM prompt. Pick **rag-chatbot** when the core interaction is document-grounded Q&A where retrieved text augments LLM generation.

### vs agentic-app

Pick **ml-pipeline-app** when the AI component is a trained ML model producing predictions or embeddings, with no agent framework managing tool dispatch or multi-step reasoning. Pick **agentic-app** when the application uses an agent orchestration layer (LangGraph, LlamaStack, CrewAI) to reason and call tools.

---

## Approach B: KNN Collaborative Filtering with KServe MLServer (from spending-transaction-monitor)

### When to Use

When the application trains a KNN collaborative filtering model for user-specific recommendations (alert suggestions, content recommendations, similar-user discovery) and serves predictions via KServe InferenceService with MLServer sklearn runtime, especially when the ML model operates alongside an LLM-based fallback for cold-start users.

### Differences from Approach A

- **ML framework:** Approach A trains a PyTorch two-tower model for product recommendations; Approach B trains a scikit-learn KNN model for collaborative filtering-based alert recommendations
- **Model serving:** Approach A serves predictions through Feast online store (pgvector ANN retrieval); Approach B deploys a KServe InferenceService with MLServer sklearn runtime in RawDeployment mode, with model artifacts stored in MinIO
- **Feature store:** Approach A uses Feast Operator with offline (Parquet) and online (PostgreSQL) stores and 8+ feature views; Approach B builds features directly from PostgreSQL queries (`build_user_features` in `feature_engineering.py`) without a dedicated feature store
- **Pipeline stages:** Approach A has a 3-stage Kubeflow pipeline (load Feast data, train model, generate embeddings); Approach B has a 5-stage Kubeflow pipeline (prepare data, train model, save model, register model optionally, deploy model) with optional Model Registry integration (`register_model` task)
- **Development workflow:** Approach A does not include standalone notebooks; Approach B includes a 4-notebook series (`ml-pipeline/notebooks/`: `1_train_alert_model.ipynb`, `2_save_model.ipynb`, `3_deploy_model.ipynb`, `4_cleanup_deployment.ipynb`) that mirrors the Kubeflow pipeline stages for interactive development
- **Model lifecycle:** Approach B includes automatic model staleness detection (`should_retrain_model` checking model age) and on-demand retraining within the serving application (`MLAlertRecommendationService` triggers `retrain_model` when the model is stale or missing)
- **Fallback strategy:** Approach B implements a dual recommendation engine -- `MLAlertRecommendationService` (KServe-served KNN model) with automatic fallback to `AlertRecommendationService` (LLM-based demographic and transaction pattern analysis via LlamaStack) when the ML model is unavailable or produces no recommendations
- **Background caching:** Approach B includes `BackgroundRecommendationService` that pre-generates and caches recommendations for users with a 24-hour TTL, using a thread pool executor (`llm_thread_pool`) for concurrent LLM operations
- **Pipeline infrastructure:** Approach B deploys a dedicated FastAPI service for the pipeline (`alert-recommender-pipeline/src/alert_recommender_pipeline/main.py`) with Kubernetes utilities for InferenceService management (`k8s.py`), Pydantic models for pipeline configuration, and Helm-managed Data Science Pipelines Application (DSPA) resource
- **Embedding usage:** Approach A uses embeddings (CLIP, BGE) as the primary recommendation mechanism (user-item cosine similarity); Approach B uses sentence-transformers embeddings (all-MiniLM-L6-v2) only for rule similarity checking (preventing duplicate alert rules), not as the primary recommendation method
- **Companion agent layer:** Approach B coexists with a LangGraph agent pipeline that translates natural language alert rules to SQL -- the ML pipeline and agent pipeline are independent subsystems within the same quickstart, with the ML model producing recommendations and the agent pipeline processing individual transaction alerts

### Typical Components

- **Model serving:** KServe InferenceService with MLServer sklearn runtime for KNN collaborative filtering model (RawDeployment mode, `serving.kserve.io/deploymentMode: RawDeployment`, MinIO model storage with S3-compatible endpoint); LlamaStack (remote vLLM) for LLM-based recommendation fallback
- **Backend:** FastAPI (`packages/api/`) with `MLAlertRecommendationService` consuming KServe model predictions, `AlertRecommendationService` for LLM-based fallback, `BackgroundRecommendationService` for async recommendation caching, and feature engineering module (`services/recommendations/ml/feature_engineering.py` with `build_user_features`, `extract_alert_types_from_rules`, `get_alert_columns`); separate FastAPI pipeline service (`ml-pipeline/alert-recommender-pipeline/`) managing Kubeflow pipeline runs and KServe InferenceService lifecycle
- **Frontend:** React/Vite/TypeScript (`packages/ui/`) providing alert rule management with recommendation display
- **Data layer:** PostgreSQL for user profiles, transactions, alert rules, and cached recommendations (training data source); MinIO for model artifacts and pipeline storage; pgvector for embedding-based alert rule similarity
- **Supporting:** Kubeflow Pipeline (Data Science Pipelines via DSPA Helm resource) for 5-stage training workflow; Jupyter notebooks (4-notebook series) for interactive training workflow; Alembic for database migrations; Helm charts for pipeline infrastructure (`deploy/helm/alert-recommender-pipeline/` with templates for DSPA, serving runtime, MinIO, RBAC)

---

## Choosing Between Approaches

| Criteria | Approach A (Feast + PyTorch Two-Tower) | Approach B (KServe MLServer + sklearn KNN) |
|----------|---------------------------------------|-------------------------------------------|
| ML framework | PyTorch two-tower model | scikit-learn KNN collaborative filtering |
| Feature store | Feast Operator (offline Parquet, online PostgreSQL+pgvector) | None -- features built from PostgreSQL queries at prediction time |
| Model serving | Feast online store (pgvector ANN) | KServe InferenceService with MLServer sklearn runtime (RawDeployment) |
| Pipeline stages | 3-stage (load Feast data, train, generate embeddings) | 5-stage (prepare data, train, save, register, deploy) |
| Model storage | Feast online store | MinIO (S3-compatible) |
| Embedding role | Primary recommendation mechanism (user-item cosine similarity) | Rule deduplication only (sentence-transformers for similarity checking) |
| Fallback | External LLM for review summarization | Full LLM-based recommendation engine as fallback for cold-start users |
| Model lifecycle | Manual retraining | Automatic staleness detection and on-demand retraining |
| Optional integration | Kafka streaming (Strimzi) | Model Registry, LangGraph agent pipeline for NL-to-SQL |
| Best for | E-commerce product recommendations with rich feature engineering | Collaborative filtering recommendations with KServe serving and ML/LLM hybrid strategy |
