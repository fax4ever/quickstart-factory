---
name: recommendation-pipeline
description: Two-tower neural network recommendation with Kubeflow training, Feast feature store, and pgvector ANN serving
summary: "Solves personalized product recommendations using a TwoTowerModel encoding user/item features into shared d_model=64 embedding space with Euclidean distance, trained via three-step Kubeflow Pipeline (load_data_from_feast, train_model, generate_candidates) using interaction-magnitude-aware loss (_loss_map weights purchases at factor*10, negative views inversely) and BAAI/bge-small-en-v1.5 text embeddings with CLS pooling. Use when building RHOAI recommendation systems needing both batch pre-computation (top-64 items per user in user_items FeatureView via PushSource) and real-time ANN inference for new users -- the architecture is purely embedding-based with no LLM in the core recommendation flow. Critical config: Feast online_store with vector_enabled=true and vector_search_metric=\"cosine\" on item_embedding FeatureView; model weights semantically versioned in MinIO with PostgreSQL model_version table; categorical features are commented out, treating all non-numeric non-URL columns as text. Gotchas: pipeline hardcodes CPU/memory at 6000m/4000Mi with caching disabled (re-trains every run), torch.set_num_threads hardcoded to 6 must match CPU request, only first 5000 historical interactions used (head(5000)) biasing toward early data, and d_model=64 is unusually small and may degrade retrieval quality for large catalogs."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, pytorch, python, feast, kubeflow-pipelines, minio]
  ai_pattern: [embeddings, model-serving, data-pipeline]
  platform: [rhoai, openshift, kubernetes]
  data_layer: [pgvector, minio]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Two-tower recommendation model trained via Kubeflow Pipelines with Feast feature store for embedding storage and pgvector ANN search for personalized product recommendations"
    approach: "A"
---

# Recommendation Pipeline

## Overview

This architecture implements a personalized product recommendation system using a two-tower neural network model. One tower encodes user features (age, gender, signup date, preferences) and the other encodes item features (price, category, ratings, text descriptions) into a shared 64-dimensional embedding space. The model is trained via Kubeflow Pipelines on OpenShift AI, embeddings are stored in Feast feature store backed by PostgreSQL with pgvector, and recommendations are served via approximate nearest neighbor (ANN) cosine similarity search at query time.

## Data Flow

1. Kubeflow Pipeline `load_data_from_feast` step loads item, user, and interaction data from Feast feature store (historical features) and merges with live user registrations and interactions from PostgreSQL
2. `train_model` step runs `create_and_train_two_tower()` which preprocesses features (numerical normalization, text embedding via BAAI/bge-small-en-v1.5, categorical encoding), creates the TwoTowerModel, and trains with MSE loss over interaction magnitudes
3. Trained item and user encoder weights are saved to MinIO object storage with semantic versioning tracked in a `model_version` PostgreSQL table
4. `generate_candidates` step loads trained encoders, encodes all items and users into embeddings, pushes embeddings to Feast online store via PushSource, generates CLIP embeddings for image search, and pre-computes top-k item recommendations per user via `retrieve_online_documents`
5. At serving time, the FastAPI backend loads the user encoder from MinIO, encodes new user features on-the-fly, and queries Feast's `retrieve_online_documents` for ANN search over item embeddings

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Kubeflow Pipeline | Feast Feature Store | Python SDK (feast) | Load historical features for training, push embeddings to online store |
| Kubeflow Pipeline | MinIO | Python SDK (minio) | Store/retrieve trained model weights (.pth) and config (.json) |
| Kubeflow Pipeline | PostgreSQL | SQLAlchemy | Track model version, load live user/interaction data |
| FastAPI backend | MinIO | Python SDK (minio) | Download latest user encoder on startup |
| FastAPI backend | Feast Feature Store | Python SDK (feast) | Retrieve item features, ANN search over embeddings, get pre-computed recommendations |
| FastAPI backend | PostgreSQL | SQLAlchemy | Read products, users, interactions, model version |
| Feast Feature Store | PostgreSQL (pgvector) | Internal | Online store with vector_enabled: true for ANN search |
| React frontend | FastAPI backend | REST | Request recommendations, search, product views |

## Key Integration Points

### Two-Tower Model Architecture

The TwoTowerModel computes the Euclidean distance between item and user embeddings. Each tower (EntityTower) projects numerical, categorical, and text features into a shared d_model=64 space using dimension-ratio allocation.

```python
# recommendation-core/src/recommendation_core/models/two_tower.py (lines 1-22)
class TwoTowerModel(nn.Module):
    def __init__(self, item_tower: ItemTower, user_tower: UserTower):
        super().__init__()
        self.item_tower = item_tower
        self.user_tower = user_tower

    def forward(self, items_dict: Dict[str, Tensor], users_dict: Dict[str, Tensor]):
        items_embed = self.item_tower(**items_dict)  # shape -> bs, dim
        users_embed = self.user_tower(**users_dict)  # shape -> bs, dim
        return torch.norm(items_embed - users_embed, dim=-1)  # shape -> bs
```

### Text Feature Embedding with BGE

Both towers embed textual features (product name, description, category for items; preferences for users) using BAAI/bge-small-en-v1.5 with CLS pooling and L2 normalization, producing 384-dimensional embeddings that are then projected to lower dimensions inside each tower.

```python
# recommendation-core/src/recommendation_core/models/data_util.py (lines 92-162)
def tokenize_and_embed_dataframe(df, batch_size=128):
    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
    model = AutoModel.from_pretrained("BAAI/bge-small-en-v1.5")
    model.eval()
    device = torch.device("cpu")
    # ...
    for column in df.columns:
        for i in range(0, len(texts), batch_size):
            encoded_input = tokenizer(batch_texts, padding=True, truncation=True,
                                      return_tensors="pt", max_length=64)
            with torch.inference_mode():
                model_output = model(**encoded_input)
                batch_embeddings = model_output[0][:, 0]  # CLS pooling
                batch_embeddings = torch.nn.functional.normalize(batch_embeddings, p=2, dim=1)
    return torch.stack(embeddings_columns).permute(1, 0, 2)  # shape: (len(df), n_col, dim)
```

### Feast Feature Store with pgvector ANN

The Feast online store uses PostgreSQL with `vector_enabled: true` for ANN search. Item embeddings are stored in a FeatureView with `vector_index=True` and `vector_search_metric="cosine"`, and recommendations are retrieved via `retrieve_online_documents`.

```yaml
# recommendation-core/src/recommendation_core/feature_repo/feature_store.yaml
project: ${FEAST_PROJECT_NAME}
provider: local
registry:
  registry_type: remote
  path: ${FEAST_REGISTRY_URL}
  cert: /app/feature_repo/secrets/tls.crt
online_store:
  type: postgres
  host: ${DB_HOST}
  port: ${DB_PORT}
  database: ${DB_NAME}
  user: ${DB_USER}
  password: ${DB_PASSWORD}
  vector_enabled: true
```

```python
# recommendation-core/src/recommendation_core/feature_repo/feature_views.py (lines 118-133)
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

### Kubeflow Pipeline DAG

The training workflow is a three-step Kubeflow pipeline: load data, train model, generate candidates. Each step runs in a container built from the recommendation-core image and accesses secrets via Kubernetes secret mounts.

```python
# recommendation-training/train-workflow.py (lines 646-697)
@dsl.pipeline(name=os.path.basename(__file__).replace(".py", ""))
def batch_recommendation():
    load_data_task = load_data_from_feast()
    mount_secret_feast_repository(load_data_task)
    load_data_task.set_caching_options(False)
    load_data_task.set_cpu_request("6000m")
    load_data_task.set_memory_request("4000Mi")

    train_model_task = train_model(
        item_df_input=load_data_task.outputs["item_df_output"],
        user_df_input=load_data_task.outputs["user_df_output"],
        interaction_df_input=load_data_task.outputs["interaction_df_output"],
    ).after(load_data_task)

    generate_candidates_task = generate_candidates(
        item_input_model=train_model_task.outputs["item_output_model"],
        user_input_model=train_model_task.outputs["user_output_model"],
        item_df_input=load_data_task.outputs["item_df_output"],
        user_df_input=load_data_task.outputs["user_df_output"],
        models_definition_input=train_model_task.outputs["models_definition_output"],
    ).after(train_model_task)
```

### New User Recommendation at Serving Time

For new users who have preferences, the backend encodes their features on-the-fly using the user encoder loaded from MinIO and queries Feast for ANN search. Users without preferences receive random items.

```python
# backend/src/services/feast/feast_service.py (lines 135-154)
def load_items_new_user(self, user: User, k: int = 10):
    if not user.preferences or user.preferences.strip() == "" or user.preferences is None:
        return self._load_random_items(k)

    user_as_df = pd.DataFrame([user.model_dump()])
    self.user_encoder.eval()
    user_embed = self.user_encoder(**data_preproccess(user_as_df))[0]
    top_k = self.store.retrieve_online_documents(
        query=user_embed.tolist(), top_k=k, features=["item_embedding:item_id"]
    )
    top_item_ids = top_k.to_df()["item_id"].tolist()
    return self._item_ids_to_product_list(top_item_ids)
```

### Interaction Magnitude Loss Function

The training loss uses interaction-type-aware magnitude computation: purchases reduce distance (stronger signal), negative views increase it, and ratings adjust proportionally. This custom loss shapes the embedding space so high-affinity user-item pairs are closer.

```python
# recommendation-core/src/recommendation_core/models/data_util.py (lines 330-348)
def _loss_map(factor, none_value):
    return {
        "interaction_type": {
            "positive_view": lambda x: x / factor,
            "negative_view": lambda x: x * factor,
            "cart": lambda x: x / (factor * 3),
            "purchase": lambda x: x / (factor * 10),
            "rate": lambda x: x,
        },
        "rating": lambda x, r: (
            x if (r is none_value or r == 3.0)
            else x * (factor * (3 - r)) if r <= 2.0 else x / (factor * (r - 2))
        ),
        "quantity": lambda x, q: (
            x if (q is none_value or q <= 1.0) else x / (factor * (q - 1))
        ),
    }
```

### Model Versioning and MinIO Storage

Trained model weights are versioned with semantic versioning (major.minor.patch) stored in a PostgreSQL `model_version` table. Each training run increments the patch version and uploads the user encoder to MinIO. At serving time, the backend reads the latest version and downloads the corresponding model file.

```python
# recommendation-training/train-workflow.py (lines 453-488)
# In train_model step:
minio_client = Minio(
    endpoint=os.getenv("MINIO_HOST") + ":" + os.getenv("MINIO_PORT"),
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
    secure=False,
)
bucket_name = "user-encoder"
object_name = f"user-encoder-{new_version}.pth"
configuration = f"user-encoder-config-{new_version}.json"
minio_client.fput_object(bucket_name=bucket_name, object_name=object_name,
                         file_path=user_output_model.path)
```

## Prompt / Chain Patterns

This architecture does not use LLM prompts for the core recommendation flow. The recommendation logic is purely embedding-based (encode user features, ANN search against item embeddings). An external LLM is used only for a separate review summarization feature (see Related Architectures).

## Gotchas

- The `generate_candidates` step pre-computes top-64 items per user and stores them in a `user_items` FeatureView. Existing users get recommendations from this pre-computed list (fast lookup), while new users require on-the-fly encoding and ANN search (slower, requires the model weights in memory).
- Kubeflow Pipeline steps hardcode CPU/memory requests at 6000m/4000Mi in the pipeline definition (`train-workflow.py` lines 654-656). These values cannot be overridden via Helm values without modifying the pipeline code. A TODO comment notes this limitation.
- The training pipeline disables caching (`set_caching_options(False)`) for all three steps, meaning every pipeline run re-trains from scratch even if inputs haven't changed.
- `torch.set_num_threads(available_cpus)` is hardcoded to 6 in `data_util.py` (line 99), matching the pipeline's CPU request. Changing one without the other causes either thread contention or underutilization.
- Categorical features are commented out in multiple places (`entity_tower.py`, `data_util.py`, `train-workflow.py`) with no explanation beyond a heuristic `unique_percentages < 0.8` threshold that was previously used to auto-detect them. The current code treats all non-numeric, non-URL columns as text features.
- The `_load_user_encoder` method in `feast_service.py` downloads the model to `/tmp/user-encoder.pth` on every FeastService initialization, though the singleton pattern means this only happens once per process.
- Feast's `retrieve_online_documents` performs ANN search using pgvector's cosine similarity index. The embedding dimension is 64 (from d_model in EntityTower), which is unusually small and may affect retrieval quality for large catalogs.
- Interaction data from the live `stream_interaction` table is concatenated with historical data during training (`load_data_from_feast` step, line 589), but only the first 5000 historical interactions are used (`interaction_df.head(5000)`), potentially biasing toward early interactions.

## Related Architectures

- [hybrid-search-pipeline](hybrid-search-pipeline.md) -- The same system also implements multi-signal product search (text + image + SQL deterministic) using separate embedding models (BGE for text, CLIP for images) stored in Feast
