---
name: flask-backend
description: "Flask backend with LangGraph agents, OVMS/KServe inference, video streaming, and PostgreSQL tracking"
summary: "Flask backend (Python 3.11/UBI9, uv) for multimodal compliance monitoring on RHOAI combining threaded InferencePool with batched gRPC inference (OVMS or KServe/Triton selected via RUNTIME_TYPE/OPENSHIFT env vars), MJPEG video broadcast with per-client queues dropping oldest frames, boxmot+supervision multi-object tracking, async DbWriterThread with executemany batched PostgreSQL writes, and dual LangGraph StateGraph pipelines -- chat router (clarifier->router->context_answer or sql_planner->sql_agent->sql_answer with MemorySaver) and alert-to-SQL using MCP-wrapped postgres-mcp SSE tools with contextvars app_config_id scoping against cross-tenant leakage. Single approach (A) from multimodal-compliance-monitor; use when building Flask apps needing real-time batched video inference via gRPC, LangGraph agent orchestration with MCP tool integration, MJPEG browser streaming, and PostgreSQL/MinIO persistence. All configuration via environment variables -- RUNTIME_TYPE selects backend, INFERENCE_WORKERS/MIN_BATCH/MAX_BATCH tune thread pool, OPENAI_API_ENDPOINT/TOKEN/MODEL for vLLM-backed LLM, POSTGRES_MCP_URL for read-only SQL, PHOENIX_COLLECTOR_ENDPOINT for optional arize-phoenix OTEL tracing; Helm backend section sets replicas and resources (default 1400m CPU/2.5Gi memory). Gotchas: set TRANSFORMERS_CACHE/HF_HOME/XDG_CACHE_HOME to /tmp subdirs with chmod 777 for OpenShift restricted SCC (non-root UID 1001), install mesa-libGL/glib2 on UBI9 for OpenCV, model_url_to_ovms_grpc remaps port 80->9000 for OVMS gRPC, three-layer SQL defense-in-depth (keyword blocking + readonly session + MCP app_config_id scoping), SSE heartbeats every 30s for HAProxy keepalive, X-Accel-Buffering:no header for MJPEG streaming, and foreign key CASCADE upgrades via idempotent ALTER without migration tools."
metadata:
  type: component
tags:
  tech_stack: [flask, python, langchain, langgraph, opencv, postgresql, minio, pydantic, psycopg2]
  ai_pattern: [agents, multimodal, model-serving, embeddings]
  platform: [openvino, kserve, rhoai, openshift]
  data_layer: [postgresql]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Flask backend with dual LangGraph pipelines (chat router + alert-to-SQL), MJPEG video broadcast, OVMS/KServe/Triton inference pool, and MCP-based SQL execution"
    approach: "A"
---

# Flask Backend

## Overview

Flask backend serving a multimodal compliance monitoring application on RHOAI. It combines real-time video inference (via OVMS or KServe/Triton gRPC), object tracking with database persistence, MJPEG video streaming to multiple browser clients, and two LangGraph-powered LLM pipelines for conversational chat and natural-language-to-SQL alert creation. The backend connects to PostgreSQL for detection tracking, MinIO for video/thumbnail storage, and a postgres-mcp server for safe read-only SQL execution by LLM agents.

## Tech Stack & Dependencies
- **Runtime:** Python 3.11 on UBI9 (`registry.access.redhat.com/ubi9/python-311:1-77`)
- **Container image:** `quay.io/rh-ai-quickstart/ppe-compliance-monitor-backend:latest`
- **Package manager:** uv (copied from `ghcr.io/astral-sh/uv:0.9.7`)
- **Key dependencies:**
  - Flask 3.1+ with flask-cors for CORS handling
  - LangChain 1.2+, LangGraph 1.0+, langchain-openai (OpenAI-compatible LLM via vLLM/RHOAI)
  - langchain-mcp-adapters for MCP tool integration
  - OpenCV (opencv-python 4.13+) for video frame processing and MJPEG encoding
  - ovmsclient for OVMS gRPC inference, tritonclient[grpc] for KServe/Triton gRPC
  - psycopg2-binary for PostgreSQL, minio client for S3-compatible storage
  - boxmot + supervision for multi-object tracking
  - torch + torchvision for model support
  - arize-phoenix-otel + openinference-instrumentation-langchain for optional tracing
- **Helm chart:** `deploy/helm/ppe-compliance-monitor` (monolithic chart, backend is one component)

## Key Patterns

### Dual-Runtime Inference (OVMS and KServe/Triton)

The `Runtime` class dynamically selects inference backend based on environment variables, supporting OVMS (local or OpenShift) and KServe V2/OIP via Triton gRPC. Each inference worker thread creates its own `Runtime` instance to avoid sharing gRPC stubs or numpy buffers.

```python
# From app/backend/runtime.py
runtime_type = os.getenv("RUNTIME_TYPE", "openvino").lower()
openshift_mode = os.getenv("OPENSHIFT", "false").lower() == "true"

if runtime_type == "kserve":
    grpc_url = self.service_url.replace("https://", "").replace("http://", "")
    self._triton_client = triton_grpc.InferenceServerClient(url=grpc_url)
    self.inference_fun = self.kserve_inference_grpc
elif openshift_mode:
    grpc_url = model_url_to_ovms_grpc(self.service_url)
    self._grpc_client = make_grpc_client(grpc_url)
    self.inference_fun = self.remote_inference
else:
    self._grpc_client = make_grpc_client(self.service_url)
    self.inference_fun = self.local_inference
```

### Threaded Inference Pool with Batch Processing

An `InferencePool` runs multiple daemon worker threads (configurable via `INFERENCE_WORKERS`), each owning its own `Runtime`. Workers accumulate frames into batches (min/max controlled via `INFERENCE_MIN_BATCH`/`INFERENCE_MAX_BATCH`) and run batched inference in a single gRPC call. A reorder buffer ensures frames exit in sequence order.

```python
# From app/backend/video_processing/inference.py
class InferencePool:
    def __init__(self, in_queue, out_queue, stop_event, num_workers=None):
        if num_workers is None:
            num_workers = int(os.environ.get("INFERENCE_WORKERS", _DEFAULT_WORKERS))
        self._min_batch = max(1, int(os.environ.get("INFERENCE_MIN_BATCH", 3)))
        self._max_batch = max(self._min_batch, int(os.environ.get("INFERENCE_MAX_BATCH", 3)))
```

### LangGraph Chat Router Pipeline

The chat system uses a multi-node LangGraph `StateGraph` with conditional routing: a clarifier resolves coreferences using conversation history, a router classifies questions as present-tense (context-only answer) or historical (SQL pipeline), then either a direct context answer or a SQL planner -> agent -> answer chain executes. Per-session memory is maintained via `MemorySaver`.

```python
# From app/backend/chat/graph.py
graph.add_edge(START, "clarifier")
graph.add_edge("clarifier", "router")
graph.add_conditional_edges(
    "router",
    _route_after_router,
    {"context": "context_answer", "sql": "sql_planner"},
)
graph.add_edge("sql_planner", "sql_agent")
graph.add_edge("sql_agent", "sql_answer")
```

### MCP Tool Wrapping with Config Scoping

SQL execution goes through a postgres-mcp server (SSE transport). The `execute_sql` tool is wrapped with a `contextvars`-based guard that rejects any query touching detection tables without an `app_config_id` filter, preventing cross-config data leakage in multi-tenant scenarios.

```python
# From app/backend/tools/mcp_tools.py
current_app_config_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_app_config_id", default=None
)

def _wrap_execute_sql(original_tool):
    async def _scoped_execute(sql: str) -> str:
        config_id = current_app_config_id.get()
        if config_id is not None:
            sql_lower = sql.lower()
            touches_scoped = any(t in sql_lower for t in _SCOPED_TABLES)
            has_filter = f"app_config_id = {config_id}" in sql_lower
            if touches_scoped and not has_filter:
                return f"ERROR: Query rejected. You MUST include ..."
        return await original_tool.ainvoke({"sql": sql})
    return StructuredTool.from_function(coroutine=_scoped_execute, ...)
```

### MJPEG Broadcast to Multiple Clients

Video frames are processed once (draw boxes, encode JPEG) by a single broadcaster thread, then the same encoded chunk is pushed to per-client queues. Slow clients get their oldest frame dropped to stay near real-time. When the last client disconnects, streaming stops to save resources.

```python
# From app/backend/video_processing/video_handler.py
def register_client(self) -> tuple[str, queue.Queue]:
    client_id = str(uuid.uuid4())
    client_queue = queue.Queue(maxsize=30)  # ~1 second at 30 FPS
    with self._clients_lock:
        self._clients[client_id] = client_queue
    return client_id, client_queue
```

### Async DB Writer Thread with Batched Writes

A `DbWriterThread` background thread drains a queue of `(op, args)` tuples in batches, groups by operation type, and executes with `executemany` in correct dependency order (tracks before observations). It maintains a persistent connection and reconnects on failure.

```python
# From app/backend/database.py
class DbWriterThread:
    def __init__(self, max_batch: int = 10, poll_timeout: float = 0.05):
        self._queue: queue_mod.Queue = queue_mod.Queue(maxsize=5000)
    def enqueue(self, op: str, args: tuple) -> None:
        try:
            self._queue.put_nowait((op, args))
        except queue_mod.Full:
            log.warning("DB writer queue full, dropping %s", op)
```

### Read-Only Database Connections for LLM-Generated SQL

The database module provides `get_readonly_connection()` which sets `conn.set_session(readonly=True)` so PostgreSQL itself rejects any writes, regardless of what SQL the LLM generates. The `execute_query` function additionally blocks dangerous keywords (DROP, DELETE, UPDATE, etc.) at the application level.

```python
# From app/backend/database.py
@contextmanager
def get_readonly_connection():
    conn = psycopg2.connect(get_connection_string())
    try:
        conn.set_session(readonly=True, autocommit=False)
        yield conn
    finally:
        conn.rollback()
        conn.close()
```

### OpenShift gRPC URL Mapping

On OpenShift with KServe, the predictor Service exposes HTTP on port 80 but OVMS gRPC is on port 9000. The `model_url_to_ovms_grpc` helper remaps `http://host:80` or `http://host` to `host:9000` for ovmsclient.

```python
# From app/backend/openshift_grpc_url.py
def model_url_to_ovms_grpc(model_url: str) -> str:
    p = urlparse(parse_src)
    if p.hostname and p.scheme in ("http", "https"):
        port = p.port
        if port is not None and port not in (80, 443):
            return _grpc_host_port(p.hostname, port)
        return _grpc_host_port(p.hostname, 9000)
```

## Configuration
- **Environment variables:**
  - `RUNTIME_TYPE` (`openvino` or `kserve`): selects inference backend
  - `OPENSHIFT` (`true`/`false`): enables OpenShift-specific gRPC URL remapping
  - `OPENAI_API_ENDPOINT`, `OPENAI_API_TOKEN`, `OPENAI_MODEL`: LLM endpoint config (uses OpenAI-compatible API, typically vLLM on RHOAI)
  - `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: PostgreSQL connection
  - `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`: MinIO/S3 storage
  - `POSTGRES_MCP_URL`: SSE URL for postgres-mcp server (read-only SQL execution)
  - `INFERENCE_WORKERS` (default 2): number of inference worker threads
  - `INFERENCE_MIN_BATCH`, `INFERENCE_MAX_BATCH` (default 3): frame batch sizing
  - `MODEL_INPUT_NAME` (default `x`): OVMS/Triton input tensor name
  - `OVMS_GRPC_TIMEOUT` (default 60s): gRPC predict deadline
  - `PHOENIX_COLLECTOR_ENDPOINT`: optional Phoenix OTEL tracing endpoint
  - `LOG_LEVEL` (default `INFO`): application log level
  - `CORS_ORIGINS`: comma-separated allowed origins or `*`
  - `CONFIG_BUCKET` (default `config`): MinIO bucket for user uploads and thumbnails
  - `YOLO_CLASS_SIGMOID` (`auto`/`true`/`false`): controls class score sigmoid application
- **Config files:** No external config files; all configuration via environment variables
- **Helm values:** `backend.*` section in `deploy/helm/ppe-compliance-monitor/values.yaml` controls replicas, resources (default 1400m CPU / 2.5Gi memory request), image, port (8888), model URL, and CORS

## Known Gotchas
- Database init retries connection up to 10 times with 3-second delays because on Kubernetes the backend pod may start before PostgreSQL is ready (`database.py` lines 70-87). The Helm chart also uses init containers to wait for video-stream and postgres-mcp services.
- The Dockerfile sets `TRANSFORMERS_CACHE`, `HF_HOME`, `XDG_CACHE_HOME`, `MPLCONFIGDIR`, and `YOLO_CONFIG_DIR` all to `/tmp/` subdirectories and pre-creates them with `chmod 777` to work under OpenShift's restricted SCC (non-root UID 1001). Without this, HuggingFace/YOLO cache writes fail at runtime.
- System packages `mesa-libGL` and `glib2` must be installed from EPEL on UBI9 for OpenCV (`cv2`) to function; they are not in the base image.
- The `model_url_to_ovms_grpc` function remaps HTTP port 80 (KServe predictor default) to gRPC port 9000 (OVMS). If a non-standard port is in the URL, it is kept as-is. Forgetting this mapping causes connection failures when using ovmsclient on OpenShift.
- The `execute_query` function uses keyword-blocking (`DROP`, `DELETE`, etc.) plus PostgreSQL `readonly` session mode as defense-in-depth against LLM-generated destructive SQL. The MCP tool wrapper adds a third layer by rejecting queries missing `app_config_id` scoping.
- SSE heartbeat comments (`: heartbeat\n\n`) are sent every 30 seconds to keep connections alive through OpenShift HAProxy (`active_config_manager` SSE endpoint). Without these, the proxy may close idle connections.
- Video feed response headers include `X-Accel-Buffering: no` to disable nginx/HAProxy buffering that causes periodic pauses in the MJPEG stream on OpenShift.
- Foreign key constraints in the database schema were upgraded from non-CASCADE to `ON DELETE CASCADE` via idempotent ALTER statements to handle schema evolution without migration tools (see `_init_schema` in `database.py`).

## Testing Notes
- Health check: `GET /api/` returns `{"status": "ok"}`
- Helm readiness probe hits `/api/` on port 8888 with 10s initial delay, 10s period, 6 failure threshold
- Liveness probe hits `/api/` with 30s initial delay, 30s period
- Backend has a `tests/` directory with pytest fixtures in `conftest.py` and at least `test_config_delete.py`; run with `pytest` inside the container
- Verify video streaming by connecting to `/api/video_feed` after setting an active config via `POST /api/active_config`
- Verify LLM pipelines by posting to `/api/chat` and `/api/alerts` (requires `OPENAI_API_ENDPOINT` and `OPENAI_API_TOKEN` to be set)

## Related Patterns
- PostgreSQL database for detection tracking (see `pgvector.md` or `postgresql` deployment patterns)
- MinIO for video/model/thumbnail storage (see `minio.md`)
- Model serving via OVMS or KServe/Triton (see `model-serving.md`)
- LangGraph agent orchestration patterns (see architecture KB files)
- Phoenix OTEL tracing for LLM observability (see `phoenix.md`)
