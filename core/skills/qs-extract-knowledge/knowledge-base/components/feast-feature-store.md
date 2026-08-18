---
name: feast-feature-store
description: Feast feature store for serving user/item features and vector embeddings in a product recommendation system
summary: "Feast feature store manages user/item features and vector embeddings for product recommendations, deployed via feast.dev/v1alpha1 FeatureStore CRD with PostgreSQL online store (vector_enabled: true), DuckDB offline store, and SQL-backed registry managed by the Feast Kubernetes operator with pgvector subchart as backend. Use when serving real-time feature retrieval and cosine-similarity vector search via retrieve_online_documents across multiple embedding FeatureViews (item, text, CLIP, product name, category with vector_index=True) grouped into FeatureServices (item_service, user_service, user_top_k_items), with PushSource-based ingestion from training pipelines and a singleton FeastService pattern loading a user encoder model from MinIO. Critical config: three feature_store.yaml copies exist (hardcoded local dev at backend/, env var template at backend/src/services/feast/, canonical operator version at recommendation-core/.../feature_repo/); feast-data-stores secret provides both sql and postgres connection strings; FeastService hardcodes repo path to /app/recommendation-core/src/recommendation_core/feature_repo. Gotchas: the feast-apply-job init container polls https://$FEAST_REGISTRY_URL/health with curl -k (skips TLS verify), TLS cert is mounted from a secret configured via feast.secret Helm value, and user encoder model download at init time depends on a model_version database table existing before the db-init job proceeds."
metadata:
  type: component
tags:
  tech_stack: [feast, postgresql, python, fastapi, minio, torch]
  ai_pattern: [embeddings, vector-search, model-serving, data-pipeline]
  platform: [openshift, kubernetes]
  data_layer: [pgvector]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Feast operator-managed feature store with PostgreSQL online store, vector-enabled embeddings, and remote registry for product recommendations"
    approach: "A"
---

# Feast Feature Store

## Overview

Feast (Feature Store) serves as the central feature management layer in a product recommendation quickstart, providing online feature retrieval for users, items, and vector embeddings. It is deployed via the Feast Kubernetes operator (`feast.dev/v1alpha1` CRD) and connects to a PostgreSQL online store with `vector_enabled: true` to support cosine-similarity vector search for recommendation retrieval. The backend application uses Feast's Python SDK as a singleton service to serve real-time recommendations.

## Tech Stack & Dependencies
- **Runtime:** Python 3.12 / Feast SDK 0.49.0 with `[postgres]` extra
- **Container image:** `quay.io/rh-ai-quickstart/recommendation-core:latest` (used for Feast apply job and init containers)
- **Key dependencies:** `feast[postgres]==0.49.0`, `torch>=2.6.0`, `transformers>=4.52.4`, `minio>=7.2.15`, `sqlalchemy==2.0.30`
- **Helm subchart:** pgvector from `https://rh-ai-quickstart.github.io/ai-architecture-charts` (provides the PostgreSQL backend)

## Key Patterns

### Feast Operator CRD Deployment

The feature store is deployed via the `feast.dev/v1alpha1` FeatureStore CRD rather than a standalone Helm chart. The operator manages offline store (DuckDB), online store (PostgreSQL), and registry (SQL-backed) as separate services.

```yaml
apiVersion: feast.dev/v1alpha1
kind: FeatureStore
metadata:
  name: feast-recommendation
spec:
  feastProject: {{ .Values.feast.project }}
  feastProjectDir:
    git:
      url: https://github.com/rh-ai-quickstart/product-recommender-system
      ref: main
      featureRepoPath: recommendation-core/src/recommendation_core/feature_repo
  services:
    onlineStore:
      persistence:
        store:
          type: postgres
          secretRef:
            name: feast-data-stores
    registry:
      local:
        persistence:
          store:
            type: sql
            secretRef:
              name: feast-data-stores
```

### Singleton FeastService Pattern

The backend wraps Feast in a singleton class that initializes the FeatureStore client, loads a user encoder model from MinIO, and pre-configures feature services and search capabilities.

```python
class FeastService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FeastService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            path = Path("/app/recommendation-core/src/recommendation_core/feature_repo")
            self.store = FeatureStore(str(path))
            self._initialized = True
            self.user_encoder = self._load_user_encoder()
            self.user_service = self.store.get_feature_service("user_service")
```

### Vector-Enabled Online Store with Embedding Retrieval

The feature store uses PostgreSQL with `vector_enabled: true` to support cosine-similarity vector search via `retrieve_online_documents`. User embeddings are generated at query time by the user encoder model (loaded from MinIO) and matched against pre-computed item embeddings.

```python
# For new users: encode preferences, then vector search
user_embed = self.user_encoder(**data_preproccess(user_as_df))[0]
top_k = self.store.retrieve_online_documents(
    query=user_embed.tolist(), top_k=k, features=["item_embedding:item_id"]
)
```

### Multiple Embedding Feature Views

The feature repo defines several embedding feature views using `vector_index=True` with `cosine` search metric, covering different search modalities (item embeddings, text embeddings, CLIP image-text embeddings, product name and category embeddings).

```python
item_embedding_view = FeatureView(
    name="item_embedding",
    entities=[item_entity],
    ttl=timedelta(days=365 * 5),
    schema=[
        Field(name="item_id", dtype=String),
        Field(name="embedding", dtype=Array(Float32),
              vector_index=True, vector_search_metric="cosine"),
    ],
    source=item_embed_push_source,
    online=True,
)
```

### Push Sources for Embedding Ingestion

Embeddings are ingested via `PushSource` objects backed by parquet dummy sources. This allows the training pipeline to push computed embeddings directly into the online store.

```python
item_embed_push_source = PushSource(
    name="item_embed_push_source", batch_source=items_embed_dummy_source
)
```

### Feast Apply Job with Init Container

A Kubernetes Job runs `feast apply` after the registry is healthy. An init container polls the registry health endpoint before the apply step runs.

```yaml
initContainers:
  - name: wait-for-reg
    command:
      - /bin/bash
      - -c
      - |
        set -e
        url="https://$FEAST_REGISTRY_URL/health"
        until curl -ksf "$url"; do sleep 10; done
containers:
  - name: feast-0
    command:
      - /bin/bash
      - -c
      - |
        export FEAST_PROJECT_NAME={{ .Values.feast.project }}
        cd /app/recommendation-core/src/recommendation_core/feature_repo/
        feast apply
```

### Feature Services for Grouped Retrieval

Feature services group feature views for retrieval at serving time, providing clean abstractions for item lookup, user lookup, embedding retrieval, and pre-computed top-k results.

```python
item_feature_service = FeatureService(name="item_service", features=[item_feature_view])
user_feature_service = FeatureService(name="user_service", features=[user_feature_view])
user_top_k_items_service = FeatureService(name="user_top_k_items", features=[user_items_view])
```

## Configuration
- **Environment variables:**
  - `FEAST_PROJECT_NAME` -- project identifier (set via Helm `feast.project`, e.g., `feast_rec_sys`)
  - `FEAST_REGISTRY_URL` -- in-cluster registry service address (constructed as `<registry-name>.<namespace>.svc.cluster.local`)
  - `FEAST_SECRET_NAME` -- name of the TLS secret for registry communication
  - `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` -- PostgreSQL online store credentials (sourced from `pgvector` secret)
  - `MINIO_HOST`, `MINIO_PORT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` -- MinIO credentials for user encoder model download
- **Config files:**
  - `backend/feature_store.yaml` -- hardcoded remote config for local development (includes specific cluster hostnames)
  - `backend/src/services/feast/feature_store.yaml` -- template version with environment variable substitution
  - `recommendation-core/src/recommendation_core/feature_repo/feature_store.yaml` -- the canonical feature repo config used by the Feast operator and apply job
- **Helm values:**
  - `feast.project` -- Feast project name (default: `feast_rec_sys`)
  - `feast.secret` -- TLS secret name for registry (default: `feast-feast-recommendation-registry-tls`)
  - `feast.registry` -- Registry service name for constructing in-cluster URL

## Known Gotchas
- The `feature_store.yaml` at `backend/feature_store.yaml` contains hardcoded cluster-specific hostnames (e.g., `feast-feast-edb-recommendation-registry.recommendation.svc.cluster.local`) and a `password: placeholder` comment says it is replaced by `entry_point.sh` at runtime. The template version at `backend/src/services/feast/feature_store.yaml` uses environment variable substitution instead.
- Three copies of `feature_store.yaml` exist in the repo with different purposes: one hardcoded for local dev, one with env var templates, and one for the Feast operator. The canonical one used by the operator is in `recommendation-core/src/recommendation_core/feature_repo/`.
- The `FeastService.__init__` hardcodes the feature repo path to `/app/recommendation-core/src/recommendation_core/feature_repo` -- this must match the container image layout.
- The `feast-apply-job` requires the registry to be healthy before running. The init container polls `https://$FEAST_REGISTRY_URL/health` with `curl -ksf` (skipping certificate verification with `-k`).
- TLS certificate for registry communication is mounted from a Kubernetes secret at `/app/feature_repo/secrets/tls.crt` -- the secret name is configured via `feast.secret` in Helm values.
- The user encoder model is downloaded from MinIO at service initialization time, using a model version retrieved from a `model_version` database table. The db-init job waits for this table to exist before proceeding.
- The `feast-data-stores` secret provides both `sql` and `postgres` connection strings for the Feast operator's registry and online store persistence, using `${variable}` placeholders resolved by the pgvector secret's values.

## Testing Notes
- Verify the Feast registry is healthy by checking `https://<feast-registry-url>/health`
- After `feast apply` completes, confirm feature views are registered by querying the registry
- Test recommendations for existing users via `GET /recommendations/{user_id}` and for new users via `POST /recommendations`
- Confirm vector search works by verifying `retrieve_online_documents` returns relevant item IDs for a given embedding

## Related Patterns
- pgvector (provides the PostgreSQL online store backend)
- minio (stores user encoder model artifacts)
- fastapi-backend (hosts the FeastService singleton)
