---
name: hybrid-search-pipeline
description: Multi-signal product search combining SQL deterministic matching, semantic text embeddings, and CLIP image search
summary: "Multi-signal product search combining deterministic SQL name matching (exact > prefix > substring via regexp_replace/lower/strip-non-alphanumeric normalization), semantic text search (BGE-small-en-v1.5, 384-dim cosine similarity across product name and description FeatureViews), CLIP image search (clip-vit-base-patch32, 512-dim via Feast retrieve_online_documents), and LLM review summarization with stratified sampling by star rating — served via FastAPI to a React frontend. Use when building product catalogs needing text+image multimodal search with deterministic-first fallback semantics; embeddings are pre-computed via Kubeflow Pipelines into six Feast FeatureViews (item/user 64-dim, text/name/category 384-dim BGE, CLIP 512-dim) backed by pgvector. Critical pattern: deterministic SQL matches short-circuit semantic search when >= k results found; CLIP embeddings combine (image * 2) + text then L2-normalize, falling back to text-only when images are missing; category embeddings are stored in Feast but unused at serving time. Key gotchas: SearchService.search_by_text loads ALL item embeddings into memory per call scaling linearly with catalog size, synchronous requests.post in async route blocks the event loop during LLM inference, MODEL_ENDPOINT assertion at import crashes startup even if summarization is never invoked, and the default 200-review stratified sample can exceed LLM context limits."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, pytorch, python, feast, clip, sentence-transformers]
  ai_pattern: [vector-search, embeddings, multimodal, semantic-search]
  platform: [rhoai, openshift, kubernetes]
  data_layer: [pgvector]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Hybrid product search combining SQL deterministic name matching (exact > prefix > substring), semantic text search via BGE embeddings with multi-field cosine similarity, and CLIP image search via Feast ANN, with LLM-based review summarization as a secondary feature"
    approach: "A"
---

# Hybrid Search Pipeline

## Overview

This architecture implements multi-signal product search that combines three retrieval strategies: deterministic SQL name matching with priority-based boosting (exact > prefix > substring), semantic text search using BAAI/bge-small-en-v1.5 embeddings with cosine similarity across multiple text fields (product name, description, category), and CLIP-based visual similarity search for image queries. All embedding-based searches use Feast feature store backed by PostgreSQL with pgvector for ANN retrieval. An external LLM provides review summarization as a complementary feature alongside the search capabilities.

## Data Flow

### Text Search
1. User submits text query via frontend (`GET /products/search?query=...`)
2. Backend performs deterministic SQL matching first: normalized exact match, prefix match, and substring match against product names in PostgreSQL
3. If deterministic results provide >= k items, they are returned immediately (no embedding search needed)
4. Otherwise, semantic search fills remaining slots: query text is embedded with BGE model, cosine similarity is computed against pre-stored product name and description embeddings from Feast online store
5. Results are merged with deterministic matches taking priority, then semantic results filling remaining slots up to k

### Image Search
1. User submits image (file upload or URL) via frontend (`POST /products/search/image-file` or `POST /products/search/image-link`)
2. Backend encodes the query image using CLIP (openai/clip-vit-base-patch32) producing a 512-dimensional embedding
3. Feast `retrieve_online_documents` performs ANN cosine similarity search against pre-stored CLIP embeddings
4. Top-k results are fetched from Feast item feature service and returned as Product objects

### Review Summarization
1. User requests summarization for a product (`GET /products/{product_id}/reviews/summarize`)
2. Backend fetches up to 1000 reviews from PostgreSQL with stratified sampling by star rating
3. Reviews are formatted into a prompt and sent to an external LLM via OpenAI-compatible chat completions API
4. LLM response is returned as the summary

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| React frontend | FastAPI backend | REST | Submit text/image search queries, request review summarization |
| FastAPI backend | PostgreSQL | SQLAlchemy | Deterministic name matching via normalized SQL queries |
| FastAPI backend (SearchService) | Feast Feature Store | Python SDK (feast) | Retrieve pre-stored text embeddings for semantic search |
| FastAPI backend (SearchByImageService) | Feast Feature Store | Python SDK (feast) | ANN search over CLIP embeddings for image queries |
| FastAPI backend (ClipEncoder) | CLIP model (local) | PyTorch/Transformers | Encode query images into 512-dim embeddings |
| FastAPI backend (SearchService) | BGE model (local) | PyTorch/Transformers | Encode query text into 384-dim embeddings |
| FastAPI backend | External LLM | REST (OpenAI-compatible) | Review summarization via chat completions endpoint |
| Kubeflow Pipeline | Feast Feature Store | Python SDK (feast) | Push pre-computed text and CLIP embeddings during training |

## Key Integration Points

### Deterministic-First Search with Semantic Fallback

The text search implements a priority cascade: deterministic SQL matches are always preferred over embedding-based results. Semantic search is only invoked if deterministic results are insufficient. Both are merged into a deduplicated result set.

```python
# backend/src/services/feast/feast_service.py (lines 184-294)
def search_item_by_text(self, text: str, k=5):
    search_service = SearchService(self.store)

    def _norm(s: str) -> str:
        return "".join(ch.lower() for ch in (s or "") if ch.isalnum())
    qn = _norm(text)

    # Deterministic name boosting via SQL
    norm_expr = "regexp_replace(lower(name), '[^a-z0-9]', '', 'g')"
    exact_ids = _query_item_ids(f"{norm_expr} = :qn", {"qn": qn}, exact_limit)
    prefix_ids = _query_item_ids(f"{norm_expr} LIKE :prefix", {"prefix": f"{qn}%"}, prefix_limit)
    contains_ids = _query_item_ids(f"{norm_expr} LIKE :contains", {"contains": f"%{qn}%"}, contains_limit)

    # Merge with priority and dedupe
    merged: List[str] = []
    seen = set()
    for bucket in (exact_ids, prefix_ids, contains_ids):
        for iid in bucket:
            if iid not in seen:
                merged.append(iid)
                seen.add(iid)

    # If we already have k or more, return immediately
    if len(merged) >= k:
        return self._item_ids_to_product_list(merged[:k])

    # Otherwise fetch semantic candidates to fill remaining slots
    semantic_df = search_service.search_by_text(text, max(k, 50))
    # ...merge semantic results after deterministic
```

### Multi-Field Semantic Text Search

The semantic search computes embeddings for both product names and descriptions (stored as separate Feast FeatureViews), stacks them as a 2D tensor, and calculates cosine similarity against the query embedding. The max score across fields determines ranking.

```python
# recommendation-core/src/recommendation_core/service/search_by_text.py (lines 109-218)
def search_by_text(self, text, k) -> pd.DataFrame:
    all_items_df = self._get_item_ids()

    about_product_embeddings_df = self.store.get_online_features(
        features=["item_textual_features_embed:about_product_embedding"],
        entity_rows=[{"item_id": item_id} for item_id in all_items_df["item_id"]],
    ).to_df()
    product_name_embeddings_df = self.store.get_online_features(
        features=["item_name_features_embed:product_name_embedding"],
        entity_rows=[{"item_id": item_id} for item_id in all_items_df["item_id"]],
    ).to_df()

    items_embeddings = torch.stack(
        [about_product_tensor, product_name_tensor], dim=1
    )  # shape: (n_items, 2, embed_dim)

    free_text_embeddings = self._get_free_text_embeddings(text)
    similarity_scores = self._calculate_similarity_scores(free_text_embeddings, items_embeddings)
    top_items = self._get_top_k_items(all_items_df, similarity_scores, k=k)
```

### CLIP Image Search via Feast ANN

Image search uses OpenAI's CLIP model to encode images into 512-dimensional embeddings. During training, all product images and descriptions are encoded together (image weight 2x, text weight 1x, then L2-normalized) and pushed to a Feast FeatureView with `vector_index=True`. At query time, the image is CLIP-encoded and searched via `retrieve_online_documents`.

```python
# recommendation-core/src/recommendation_core/service/search_by_image.py (lines 9-35)
class SearchByImageService:
    def __init__(self, store: FeatureStore, clip_encoder: ClipEncoder):
        self.store = store
        self.clip_encoder = clip_encoder

    def search_by_image(self, image, k):
        clip_embedding = (
            self.clip_encoder.encode_images([image])[0].cpu().detach().numpy()
        )
        ids = self.store.retrieve_online_documents(
            query=list(clip_embedding),
            top_k=k,
            features=["item_clip_features_embed:item_id"],
        ).to_df()
```

### CLIP Embedding Creation (Text + Image Weighted Combination)

CLIP embeddings combine both text (product description) and image features with a 2:1 image-to-text weighting ratio, then L2-normalize. When product images are missing, the combined embedding falls back to text-only.

```python
# recommendation-core/src/recommendation_core/service/clip_encoder.py (lines 38-56)
def encode_texts_and_images(self, texts: list[str], images: list[Image], batch_size: int = 32):
    assert len(texts) == len(images)
    text_embeddings = self.encode_texts_batched(texts, batch_size=batch_size)
    image_embeddings, _ = self.encode_images_batched_having_nones(images, batch_size=batch_size)
    # image_embeddings can be null if the image is not present
    #   in this case: combined_embeddings == text_embeddings
    combined_embeddings = (image_embeddings * 2) + text_embeddings
    # we don't need to divide by 3, since we normalize them
    return (
        torch.nn.functional.normalize(combined_embeddings, p=2, dim=1)
        .cpu().detach().numpy().tolist()
    )
```

### LLM Review Summarization with Stratified Sampling

Review summarization uses an external LLM via OpenAI-compatible API. Reviews are stratified-sampled by star rating (ensuring representation across 1-5 stars proportionally) before being formatted into a summarization prompt.

```python
# backend/src/routes/reviews.py (lines 153-324)
@router.get("/{product_id}/reviews/summarize", response_model=ReviewSummarization)
async def summarize_reviews(product_id: str, db: AsyncSession = Depends(get_db)):
    reviews = await _fetch_reviews_from_db(product_id, db, limit=1000)
    # Stratified sampling by rating (1..5)
    # ...allocate per-bucket quota proportionally with minimum of 1...

    prompt = f"""
Please analyze and summarize the following product reviews. Provide a concise summary...
Reviews:
{combined_reviews}
"""
    response = requests.post(
        MODEL_ENDPOINT,
        json={"model": MODEL_NAME,
              "messages": [
                  {"role": "system", "content": "You are a helpful, smart shopper..."},
                  {"role": "user", "content": prompt}],
              "stream": False},
        headers=headers,
    )
    summary = response.json()["choices"][0]["message"]["content"].strip()
```

### Feast FeatureViews for Multiple Embedding Types

The system stores five distinct embedding types in separate Feast FeatureViews, each with `vector_index=True` for ANN search: item embeddings (64-dim, from two-tower model), user embeddings (64-dim), text description embeddings (384-dim, BGE), product name embeddings (384-dim, BGE), category embeddings (384-dim, BGE), and CLIP embeddings (512-dim).

```python
# recommendation-core/src/recommendation_core/feature_repo/feature_views.py (lines 164-231)
item_textual_features_embed_view = FeatureView(
    name="item_textual_features_embed",
    entities=[item_entity],
    schema=[
        Field(name="item_id", dtype=String),
        Field(name="about_product_embedding", dtype=Array(Float32),
              vector_index=True, vector_search_metric="cosine"),
    ],
    source=item_textual_features_embed_push_source,
    online=True,
)

item_clip_features_embed_view = FeatureView(
    name="item_clip_features_embed",
    entities=[item_entity],
    schema=[
        Field(name="item_id", dtype=String),
        Field(name="clip_latent_space_embedding",  # a unique space for text and images
              dtype=Array(Float32),
              vector_index=True, vector_search_metric="cosine"),
    ],
    source=item_clip_features_embed_push_source,
    online=True,
)
```

## Prompt / Chain Patterns

The review summarization uses a simple system + user prompt pair. The system prompt sets the persona ("helpful, smart shopper") and the user prompt includes all sampled reviews with their ratings and asks for sentiment analysis, strengths, concerns, and a recommendation.

```python
# backend/src/routes/reviews.py (lines 297-303)
"messages": [
    {"role": "system",
     "content": "You are a helpful, smart shopper who helps customers summarize "
                "other customers reviews to make it easier for them to decide "
                "whether to buy a product."},
    {"role": "user", "content": prompt},
],
```

## Gotchas

- The semantic text search in `SearchService.search_by_text` loads ALL item embeddings into memory on every search call via `get_online_features` with entity rows for every product. This scales linearly with catalog size and will become a bottleneck for large catalogs. The deterministic SQL fallback mitigates this by short-circuiting when name matches are sufficient.
- The deterministic search normalizes both the query and product names by stripping all non-alphanumeric characters and lowering case (`regexp_replace(lower(name), '[^a-z0-9]', '', 'g')`). This means "USB-C" and "USBC" match, but it also means "TV Stand" matches "TVStand".
- CLIP embeddings use a weighted combination of `(image * 2) + text` before normalization. When a product has no image, the image embedding is zero (from `encode_images_having_nones`), so the combined embedding equals the text embedding only -- meaning image-only products and text-only products occupy different scales in the embedding space before normalization.
- The category embedding FeatureView is fetched during the `generate_candidates` pipeline step but is NOT used in the `SearchService.search_by_text` method at serving time. Only `about_product_embedding` and `product_name_embedding` are used for text search, despite category embeddings being available.
- The `MODEL_ENDPOINT` and `MODEL_NAME` environment variables for review summarization are asserted at module import time (`assert MODEL_ENDPOINT is not None`), meaning the backend will crash on startup if these are not set, even if review summarization is never called.
- The review summarization endpoint uses synchronous `requests.post` (not `httpx.AsyncClient`) inside an `async` route handler, blocking the event loop during LLM inference.
- The stratified sampling for review summarization uses a complex quota allocation algorithm (lines 183-254 in reviews.py) with adjust-up and adjust-down loops to hit exactly `SUMMARIZE_MAX_REVIEWS` (default 200). The default of 200 reviews can produce very long prompts that may exceed model context limits depending on the LLM used.

## Related Architectures

- [recommendation-pipeline](recommendation-pipeline.md) -- The same system's personalized recommendation engine using two-tower model embeddings trained via Kubeflow Pipelines, which shares the Feast feature store infrastructure
