---
name: recommendation-core
description: "PyTorch two-tower recommendation library with Feast feature store, CLIP multimodal search, and KFP pipeline integration"
summary: "Shared Python library (pip-installable, not a standalone service) providing two-tower retrieval model training (ItemTower/UserTower into 64-dim embedding space via L2 distance with ratio-based dim_ratio allocation across numeric/text/image features), Feast feature store definitions with PostgreSQL vector search, and dual search services for the product-recommender-system quickstart. Use as the single ML/feature-store dependency when building a KFP-based recommendation pipeline on RHOAI -- containerized as quay.io/rh-ai-quickstart/recommendation-core and consumed as @dsl.component base_image by training pipelines and imported by FastAPI backends for BGE-small text search (384-dim, client-side cosine via get_online_features) and CLIP-vit-base-patch32 image search (512-dim, 2x image weighting, server-side via retrieve_online_documents). Requires env vars FEAST_PROJECT_NAME, FEAST_REGISTRY_URL, DB_HOST/PORT/NAME/USER/PASSWORD, DATABASE_URL, HF_HOME, and BASE_REC_SYS_IMAGE; feature_store.yaml uses env var interpolation with remote registry over TLS (cert at /app/feature_repo/secrets/tls.crt) and postgres online_store with vector_enabled: true. Categorical features are commented out and hard-coded to 0 throughout towers and data_util, torch.set_num_threads(6) is hard-coded to KFP pod CPU limits (not auto-detected), image URL detection uses brittle .png/http prefix heuristic, Feast registry cache requires allow_registry_cache=False plus refresh_registry() workaround during candidate generation, and Containerfile duplicates source to two paths for package imports vs Feast CLI repo_path resolution."
metadata:
  type: component
tags:
  tech_stack: [python, pytorch, feast, transformers, clip, pandas, numpy, pillow]
  ai_pattern: [embeddings, vector-search, multimodal, data-pipeline]
  platform: [rhoai, openshift, kfp]
  data_layer: [pgvector, postgresql]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Shared Python library providing two-tower model training, Feast feature definitions, CLIP encoding, and text/image search services consumed by KFP training pipeline and FastAPI backend"
    approach: "A"
---

# Recommendation Core

## Overview

Recommendation Core is a shared Python library (not a standalone service) that provides the machine learning models, feature store definitions, and search services for the product-recommender-system quickstart. It is installed as a pip package into both the KFP training pipeline containers and the FastAPI backend, acting as the single source of truth for model architecture, data preprocessing, and Feast feature view schemas. It is built into a container image (`quay.io/rh-ai-quickstart/recommendation-core`) that serves as the `base_image` for Kubeflow Pipeline components on RHOAI.

## Tech Stack & Dependencies

- **Runtime:** Python >= 3.12
- **Container image:** `registry.access.redhat.com/ubi9/python-312` (base), published as `quay.io/rh-ai-quickstart/recommendation-core`
- **Key dependencies:** PyTorch 2.6.x, Feast[postgres] 0.49.0, Transformers 4.52.4, einops, Pillow, requests, pandas, numpy
- **Optional dependencies:** `diffusers` (data-gen), `pytest` (test), `ruff` (dev)
- **Build system:** setuptools with `src/` layout, installed via `uv pip install .`

## Key Patterns

### Two-Tower Model Architecture

The core ML pattern is a two-tower retrieval model. Separate `ItemTower` and `UserTower` neural networks encode items and users into a shared 64-dimensional embedding space. The `TwoTowerModel` computes the L2 distance between the two embeddings to predict interaction magnitude.

```python
# recommendation-core/src/recommendation_core/models/two_tower.py
class TwoTowerModel(nn.Module):
    def __init__(self, item_tower: ItemTower, user_tower: UserTower):
        super().__init__()
        self.item_tower = item_tower
        self.user_tower = user_tower

    def forward(self, items_dict, users_dict):
        items_embed = self.item_tower(**items_dict)   # shape -> bs, dim
        users_embed = self.user_tower(**users_dict)   # shape -> bs, dim
        return torch.norm(items_embed - users_embed, dim=-1)  # shape -> bs
```

### Ratio-Based Dimension Allocation in Entity Towers

Each tower allocates its `d_model` embedding dimensions across feature types using a ratio dictionary. This avoids hard-coding dimension splits and lets the architecture adapt to varying numbers of features.

```python
# recommendation-core/src/recommendation_core/models/entity_tower.py
class EntityTower(nn.Module):
    def __init__(self, num_numerical=1, num_of_categories=0, d_model=64,
                 text_embed_dim=384, image_embed_dim=384,
                 dim_ratio={"numeric": 1, "categorical": 2, "text": 7, "image": 0}):
        ratio_weight = d_model / sum(dim_ratio.values())
        numerical_dim = int(dim_ratio["numeric"] * ratio_weight) if num_numerical > 0 else 0
        categorical_dim = int(dim_ratio["categorical"] * ratio_weight) if num_of_categories > 0 else 0
        self.text_dim = d_model - numerical_dim - categorical_dim
```

### Text Embedding with BGE for Training Features

The data preprocessing pipeline uses `BAAI/bge-small-en-v1.5` (384-dim) to embed text columns of item and user DataFrames. CLS pooling with L2 normalization is applied. The thread count is hard-coded for KFP pod resource limits.

```python
# recommendation-core/src/recommendation_core/models/data_util.py
available_cpus = 6
torch.set_num_threads(available_cpus)
tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
model = AutoModel.from_pretrained("BAAI/bge-small-en-v1.5")
# CLS pooling
batch_embeddings = model_output[0][:, 0]
batch_embeddings = torch.nn.functional.normalize(batch_embeddings, p=2, dim=1)
```

### CLIP Multimodal Encoding for Image Search

A `ClipEncoder` class uses `openai/clip-vit-base-patch32` (512-dim) to create joint text+image embeddings for items. Image embeddings are weighted 2x relative to text, then L2-normalized. None images are handled gracefully with zero vectors.

```python
# recommendation-core/src/recommendation_core/service/clip_encoder.py
CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"
CLIP_MODEL_SIZE = 512

# In encode_texts_and_images:
combined_embeddings = (image_embeddings * 2) + text_embeddings
return torch.nn.functional.normalize(combined_embeddings, p=2, dim=1)
```

### Feast Feature Store Integration

Feature definitions live in `feature_repo/` with a remote registry over TLS and a PostgreSQL online store with vector support enabled. Entities, feature views, and feature services are defined in separate Python modules. The `feature_store.yaml` uses environment variables for all connection details.

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

### Vector Search via Feast Online Documents

Text search uses Feast `get_online_features` to retrieve pre-computed BGE embeddings, then calculates cosine similarity client-side. Image search uses `retrieve_online_documents` with CLIP embeddings for server-side vector similarity search in the PostgreSQL online store.

```python
# recommendation-core/src/recommendation_core/service/search_by_image.py
ids = self.store.retrieve_online_documents(
    query=list(clip_embedding),
    top_k=k,
    features=["item_clip_features_embed:item_id"],
).to_df()
```

### Interaction Magnitude Calculation

Training labels are computed from user-item interaction data using a rule-based magnitude function. Different interaction types (purchase, cart, view, rate) and ratings/quantities modulate a default magnitude value using multiplicative factors.

```python
# recommendation-core/src/recommendation_core/models/data_util.py
"interaction_type": {
    "positive_view": lambda x: x / factor,
    "negative_view": lambda x: x * factor,
    "cart": lambda x: x / (factor * 3),
    "purchase": lambda x: x / (factor * 10),
    "rate": lambda x: x,
},
```

### KFP Base Image Pattern

The library is containerized and used as `base_image` for KFP `@dsl.component` decorators. The training pipeline (`train-workflow.py`) imports directly from the installed package inside these components.

```python
# recommendation-training/train-workflow.py
BASE_IMAGE = os.getenv("BASE_REC_SYS_IMAGE",
    "quay.io/rh-ai-quickstart/recommendation-core:latest")

@dsl.component(base_image=BASE_IMAGE)
def generate_candidates(...):
    from recommendation_core.models.data_util import data_preproccess
    from recommendation_core.models.entity_tower import EntityTower
    from recommendation_core.service.clip_encoder import ClipEncoder
```

## Configuration

- **Environment variables:**
  - `FEAST_PROJECT_NAME` -- Feast project name (default: `feast_rec_sys`)
  - `FEAST_REGISTRY_URL` -- URL for the remote Feast registry service
  - `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` -- PostgreSQL connection for Feast online store
  - `DATABASE_URL` -- SQLAlchemy connection string used by `SearchService` to query product IDs directly
  - `HF_HOME` -- Hugging Face cache directory (set to `/hf_cache` in container)
  - `BASE_REC_SYS_IMAGE` -- Override for the KFP component base image
- **Config files:** `feature_store.yaml` (Feast config with env var interpolation)
- **TLS:** Feast registry TLS cert mounted at `/app/feature_repo/secrets/tls.crt` via Kubernetes secret volume

## Known Gotchas

- **Categorical features disabled:** The code has categorical feature processing commented out in `EntityTower`, `ItemTower` (legacy path), `UserTower`, and `data_util.py`. Categorical counts are hard-coded to 0 in `train_two_tower.py`. The commented code is still present, suggesting this is intentional to simplify the model but could be re-enabled.
- **Hard-coded CPU thread count:** `data_util.py` hard-codes `torch.set_num_threads(6)` with a comment noting that the limit comes from the KFP pod resource requests in `train-workflow.py`. Changing pod CPU limits without updating this value will not utilize additional cores.
- **URL detection heuristic for images:** `data_preproccess()` identifies image URL columns by checking if values end with `.png` or start with `http`. A code comment warns this is "inherently brittle" and was already broken once when switching from absolute to relative URLs.
- **Feast registry cache:** Multiple push calls in `generate_candidates` use `allow_registry_cache=False` and call `store.refresh_registry()` before pushing text features. This works around stale registry state during the candidate generation pipeline step.
- **Duplicate PYTHONPATH in Containerfile:** The Containerfile copies source files to both `/app/src/` and `/app/recommendation-core/src/recommendation_core/feature_repo/` to satisfy imports from two different paths -- the installed package and the Feast CLI's `repo_path` based resolution.
- **Default magnitude value:** The `_calculate_interaction_loss` function uses a magic number `11.265591558187197` as the default magnitude. No comment explains how it was derived.

## Testing Notes

- Tests are in `recommendation-core/tests/` and use pytest with `pythonpath = ["src"]`
- Test files cover: CLIP encoder, two-tower model creation/training, data utility functions, entity tower, and search service
- The library has no standalone deployment -- verify it works by running the KFP training pipeline or calling the search services through the FastAPI backend

## Related Patterns

- Architecture: two-tower retrieval models, Feast feature store with PostgreSQL vector search
- Deployment: KFP pipeline components using shared base image, Feast remote registry with TLS
- Components: fastapi-backend (consumes search services), pgvector (online store backend)
