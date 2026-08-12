---
name: multimodal-video-analytics
description: Real-time CV inference pipeline combined with LLM-powered conversational analytics over detection data
summary: "Combines real-time YOLO object detection via OVMS or KServe/Triton gRPC with LangGraph conversational analytics over detection data persisted to PostgreSQL, using BoostTrack++ tracking (motion-only, no ReID) and multi-client MJPEG broadcasting with encode-once fan-out through per-client queues. Use when building video analytics requiring both live visual context answers and historical SQL queries -- the LangGraph chat graph routes via structured-output to context-only or sql_planner->sql_agent->sql_answer paths using postgres-mcp, while a separate alert graph converts plain-English rules to validated SQL via ReAct agent. Critical patterns: InferencePool runs batched gRPC inference (preprocess to (N,3,640,640)) with reorder buffer for frame ordering, Runtime selects backend via RUNTIME_TYPE/OPENSHIFT env vars with OpenShift gRPC URL mapping (HTTP:80->OVMS gRPC:9000), epoch-based invalidation prevents cross-source frame leakage, and NMS applies score threshold 0.25/IoU 0.45 with separate 0.5 confidence floor. Key gotchas: ovmsclient gRPC stubs are not thread-safe (per-worker Runtime instances required), SQL generator must alias detection_observations as \"obs\" not \"do\" (PostgreSQL reserved word), MemorySaver loses conversation state on pod restart, majority-vote buffer (50 frames ~5-6s) may miss short events, S3 temp files are not cleaned on crash, and per-client queues (size 30) drop oldest frames at capacity to avoid latency accumulation."
metadata:
  type: architecture
tags:
  tech_stack: [flask, langchain, langgraph, python, opencv, numpy, postgresql, minio, ovmsclient, tritonclient]
  ai_pattern: [multimodal, model-serving, agents, prompt-chaining]
  platform: [openvino, triton, kserve, rhoai, openshift]
  data_layer: [postgresql, minio]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "YOLO object detection via OVMS/KServe-Triton gRPC with BoostTrack++ tracking, detection persistence to PostgreSQL, and LangGraph conversational analytics querying detection data via postgres-mcp"
    approach: "A"
---

# Multimodal Video Analytics

## Overview

This architecture combines real-time computer vision inference with LLM-powered conversational analytics in a single application. A video ingestion pipeline captures frames from RTSP streams or video files, runs YOLO object detection via OVMS or KServe/Triton over gRPC, tracks objects across frames using BoostTrack++, and persists detection data (tracks, observations, attributes) to PostgreSQL. Separately, LangGraph-based conversational agents answer user questions about the detection data -- either from live visual context (what the camera sees now) or from historical database records queried via a postgres-mcp server. The two modalities (vision and language) share PostgreSQL as the integration point: the CV pipeline writes structured detection records that the LLM pipeline reads through SQL.

## Data Flow

1. `FrameConsumer` thread reads frames from an RTSP stream, S3-stored video, or local file using OpenCV `VideoCapture`
2. Frames are placed into a `frame_queue` (maxsize 150)
3. `InferencePool` worker threads (default 2) pull frame batches (min 3, max 3), preprocess to `(N, 3, 640, 640)` blobs, and run batched gRPC inference against OVMS or KServe/Triton
4. `postprocess_image` applies NMS (`cv2.dnn.NMSBoxes`) to raw model output, producing `Detection` objects with bounding boxes, class names, and confidence scores
5. `process_detections` filters detections by `include_in_counts` flags and enriches with trackability metadata
6. Results go into `inference_out_queue` (maxsize 350) with frame ordering preserved via a reorder buffer
7. `_broadcast_loop` thread pulls results, draws bounding boxes on frames once, encodes JPEG once, and broadcasts the MJPEG chunk to all connected HTTP clients
8. `TrackerProcess` (separate OS process) runs BoostTrack++ object tracking, associates PPE items to tracked persons via numpy overlap, and batch-writes tracks/observations to PostgreSQL
9. Flask `/api/latest_info` returns the latest detection description and compliance summary computed from a rolling buffer of the last 50 frames
10. Flask `/api/chat` passes the user question plus current visual context to a LangGraph `ChatState` graph that routes to either a context-only answerer or a SQL planner/agent/answer chain
11. The SQL agent generates SQL queries via LLM, executes them through a wrapped `execute_sql` MCP tool (postgres-mcp), and the sql_answer node synthesizes a natural-language response

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| FrameConsumer | frame_queue | Python queue | Decoded video frames (numpy arrays + frame IDs) |
| InferencePool workers | OVMS or KServe/Triton | gRPC (ovmsclient or tritonclient) | Batched YOLO inference on preprocessed frames |
| InferencePool workers | inference_out_queue | Python queue | InferenceResult with frame, detections, counts, epoch |
| broadcast_loop thread | HTTP clients | MJPEG over HTTP (multipart/x-mixed-replace) | Annotated video frames to all connected browsers |
| TrackerProcess | PostgreSQL | psycopg2 (SQL) | Batch upsert detection_tracks and detection_observations |
| Flask /api/chat | LangGraph ChatState | Python method call | Question + visual context routed through graph |
| LangGraph sql_agent node | postgres-mcp | SSE (langchain-mcp-adapters) | Execute SQL queries against detection tables |
| Flask /api/alerts | LangGraph AlertState | Python method call | Plain-English alert rule converted to SQL query |
| Flask /api/video_feed | Per-client queue | Python queue | MJPEG chunks from broadcaster to individual HTTP streams |

## Key Integration Points

### Dual-Runtime Inference (OVMS and KServe/Triton)

The `Runtime` class selects between three inference backends based on `RUNTIME_TYPE` and `OPENSHIFT` environment variables. All share the same preprocess/postprocess pipeline but use different gRPC clients.

```python
# app/backend/runtime.py (lines 55-73)
if runtime_type == "kserve":
    grpc_url = self.service_url.replace("https://", "").replace("http://", "")
    self._triton_client = triton_grpc.InferenceServerClient(
        url=grpc_url,
        channel_args=[
            ("grpc.max_send_message_length", -1),
            ("grpc.max_receive_message_length", -1),
            ("grpc.optimization_target", "throughput"),
        ],
    )
    self._infer_output = triton_grpc.InferRequestedOutput("output0")
    self.inference_fun = self.kserve_inference_grpc
elif openshift_mode:
    grpc_url = model_url_to_ovms_grpc(self.service_url)
    self._grpc_client = make_grpc_client(grpc_url)
    self.inference_fun = self.remote_inference
else:
    self._grpc_client = make_grpc_client(self.service_url)
    self.inference_fun = self.local_inference
```

### Batched Inference with Reorder Buffer

The InferencePool runs multiple worker threads, each with its own Runtime instance. A reorder buffer ensures frames arrive in sequence despite out-of-order parallel processing.

```python
# app/backend/video_processing/inference.py (lines 222-262)
def run_batch(self, images: list[np.ndarray]) -> list[list[Detection]]:
    """Run inference on a batch of images with a single gRPC call."""
    if not images:
        return []
    if len(images) == 1:
        return [self.run(images[0])]

    n = len(images)
    if self._batch_blob is None or self._batch_blob.shape[0] < n:
        self._batch_blob = np.empty((n, 3, 640, 640), dtype=np.float32)
    batched_blob = self._batch_blob[:n]

    scales = self._preprocess_batch_into(images, batched_blob)
    raw_outputs = self.inference(batched_blob)
    raw_tensor = _raw_prediction_tensor(raw_outputs)

    results: list[list[Detection]] = []
    for i in range(n):
        per_image = raw_tensor[i : i + 1]
        dets = postprocess_image(per_image, scales[i], self.CLASSES)
        results.append(dets)
    return results
```

### Vision-to-Language Bridge via Detection Context

The video pipeline produces detection descriptions and summaries that are injected as context into the LLM chat graph. The `/api/chat` endpoint strips the "Detected: " prefix and passes the raw detection string as `context` in the ChatState.

```python
# app/backend/app.py (lines 200-226)
desc = video_handler.get_latested_description() or latest_description
context = desc.replace("Detected: ", "", 1)

answer = llm_chat.chat(
    question=question,
    context=context,
    session_id=session_id,
    app_config_id=app_config_id,
    classes_info=classes_info,
)
```

The description comes from a majority-vote over the last 50 frames, providing stable detection counts despite per-frame noise:

```python
# app/backend/video_processing/video_handler.py (lines 603-608)
def get_majority_description(self) -> str:
    """Return the most common description among the last K frames."""
    if not self._description_vote_buffer:
        return ""
    counter = Counter(self._description_vote_buffer)
    return counter.most_common(1)[0][0]
```

### Multi-Client MJPEG Broadcasting

The broadcaster thread encodes each frame to JPEG once and fans out the same bytes to all connected HTTP clients via per-client queues, avoiding redundant encoding.

```python
# app/backend/video_processing/video_handler.py (lines 349-377)
# Draw bounding boxes ONCE (not per client)
frame = self.draw_detections(result.frame, result.detections)

# Encode to JPEG ONCE (not per client)
chunk = self.encode_mjpeg_chunk(frame)
if chunk is None:
    continue

# Submit detections to tracker for database persistence
self._tracker.submit(result.detections, epoch=current_epoch)

# Broadcast the same chunk to all connected clients
with self._clients_lock:
    clients_snapshot = list(self._clients.items())

for client_id, client_queue in clients_snapshot:
    try:
        client_queue.put_nowait(chunk)
    except queue.Full:
        try:
            client_queue.get_nowait()
            client_queue.put_nowait(chunk)
        except queue.Empty:
            pass
```

### Epoch-Based Pipeline Invalidation

When switching video sources, the pipeline increments an epoch counter. In-flight frames from the previous source are dropped by checking `result.epoch != current_epoch`, preventing cross-source frame leakage.

```python
# app/backend/video_processing/video_handler.py (lines 334-338)
# Skip stale frames from a previous video source
if result.epoch != current_epoch:
    log.debug(
        f"Broadcaster: dropping stale frame (epoch {result.epoch} != {current_epoch})"
    )
    continue
```

### OpenShift gRPC URL Resolution

On OpenShift, KServe predictor Services expose HTTP on port 80 but OVMS gRPC on port 9000. The `model_url_to_ovms_grpc` function maps app_config HTTP URLs to the correct gRPC endpoint.

```python
# app/backend/openshift_grpc_url.py (lines 17-38)
def model_url_to_ovms_grpc(model_url: str) -> str:
    """Map app_config model_url to host:port for ovmsclient on OpenShift.

    The KServe predictor Service exposes HTTP on default port 80; OVMS gRPC is on 9000.
    """
    raw = (model_url or "").strip()
    parse_src = raw if "://" in raw else f"http://{raw}"
    p = urlparse(parse_src)
    if p.hostname and p.scheme in ("http", "https"):
        port = p.port
        if port is not None and port not in (80, 443):
            return _grpc_host_port(p.hostname, port)
        return _grpc_host_port(p.hostname, 9000)
```

## Prompt / Chain Patterns

The architecture uses two LangGraph StateGraphs: a chat graph for conversational queries and an alert graph for rule-to-SQL conversion. Both consume the same `execute_sql` MCP tool and share a similar SQL generation prompt pattern.

**Chat Graph** (`clarifier -> router -> context_answer | sql_planner -> sql_agent -> sql_answer`):

```python
# app/backend/chat/graph.py (lines 33-55)
def _build_graph(llm: ChatOpenAI, execute_sql_tool: StructuredTool) -> StateGraph:
    graph = StateGraph(ChatState)

    graph.add_node("clarifier", make_clarifier_node(llm))
    graph.add_node("router", make_router_node(llm))
    graph.add_node("context_answer", make_context_answer_node(llm))
    graph.add_node("sql_planner", make_sql_planner_node(llm))
    graph.add_node("sql_agent", make_sql_agent_node(llm, execute_sql_tool))
    graph.add_node("sql_answer", make_sql_answer_node(llm))

    graph.add_edge(START, "clarifier")
    graph.add_edge("clarifier", "router")
    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {"context": "context_answer", "sql": "sql_planner"},
    )
    graph.add_edge("sql_planner", "sql_agent")
    graph.add_edge("sql_agent", "sql_answer")
    graph.add_edge("context_answer", END)
    graph.add_edge("sql_answer", END)

    return graph
```

The `router` node uses `with_structured_output(RouteDecision)` to classify questions as `"context"` (answerable from what the camera sees now) or `"sql"` (requires historical database queries). The visual context string and detection class information are injected into the router prompt.

**Alert Graph** (`clarifier_planner -> sql_agent`):

```python
# app/backend/alert/graph.py (lines 21-34)
def _build_alert_graph(llm: ChatOpenAI, execute_sql_tool: StructuredTool) -> StateGraph:
    graph = StateGraph(AlertState)
    graph.add_node("clarifier_planner", make_alert_clarifier_planner_node(llm))
    graph.add_node("sql_agent", make_alert_sql_agent_node(llm, execute_sql_tool))
    graph.add_edge(START, "clarifier_planner")
    graph.add_edge("clarifier_planner", "sql_agent")
    graph.add_edge("sql_agent", END)
    return graph
```

The alert graph converts plain-English rules (e.g., "Alert me when more than 5 people have no hardhat") into validated SQL queries. The `clarifier_planner` uses `with_structured_output(AlertMetric)` to extract a single metric description, then the `sql_agent` generates and validates SQL via a `create_agent` ReAct loop with the `execute_sql` tool.

The SQL generator prompt embeds the full database schema, app_config_id constraints, and dynamically generated query pattern examples tailored to the specific detection classes configured for that app_config.

## Gotchas

- The `InferencePool` creates a new `Runtime` instance per worker thread with its own gRPC stub. Workers never share Runtime instances, which is required because `ovmsclient` gRPC stubs are not thread-safe.
- The `FrameConsumer` downloads S3-stored videos to a local temp file before opening with `cv2.VideoCapture`. The temp file is cleaned up on source switch, but not on crash.
- NMS uses a hardcoded score threshold of 0.25 (`nms_score_thr` in `response.py`) and IoU threshold of 0.45. The `cv2.dnn.NMSBoxes` third parameter (0.5) is a confidence floor applied before NMS, separate from the drawing threshold (`VIDEO_FEED_DRAW_MIN_CONF = 0.5` in `video_handler.py`).
- The SQL generator prompt includes a rule to never alias `detection_observations` as `"do"` because it is a PostgreSQL reserved keyword. The prompt instructs using `"obs"` instead (line 15 in `chat/prompts/sql_agent/generator.py`).
- The majority-vote description buffer (`DESCRIPTION_VOTE_WINDOW = 50`) and the description buffer (`DESCRIPTION_BUFFER_SIZE = 50`) are both fixed at 50. At typical video frame rates (25-30 fps) with batched inference, this covers roughly 5-6 seconds of stable context. Short events may be missed in the description.
- The `TrackerProcess` runs BoostTrack++ in motion-only mode (`use_ecc=False, with_reid=False`) to avoid sending pixel data through the multiprocessing queue. Only bounding box coordinates and class IDs cross the process boundary.
- The chat graph uses `MemorySaver` for in-memory conversation history. Conversation state is lost on pod restart. Multi-worker deployments would require switching to a persistent checkpointer.
- When the last video client disconnects, the `VideoHandler` schedules `stop_streaming` on a separate thread to avoid holding the `_clients_lock` during the potentially blocking stop operation.
- Per-client queues are sized to 30 frames (~1 second at 30 fps). If a client falls behind, the oldest frame is dropped to keep the stream near real-time rather than accumulating latency.

## Related Architectures

- [agent-orchestration](agent-orchestration.md) -- The LangGraph chat and alert graphs use structured-output routing and ReAct SQL agents
- [mcp-tool-integration](mcp-tool-integration.md) -- postgres-mcp provides read-only SQL execution for the LangGraph agents
- [evaluation-pipeline](evaluation-pipeline.md) -- LLM-as-judge evaluation framework for chat quality and alert SQL correctness
