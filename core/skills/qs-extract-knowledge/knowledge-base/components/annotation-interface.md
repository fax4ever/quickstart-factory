---
name: annotation-interface
description: "Gradio-based data annotation UI for reviewing AI pipeline outputs with deepeval LLM evaluation"
summary: "Provides a Gradio 5.42+ human-in-the-loop annotation interface for reviewing AI pipeline outputs stored in PostgreSQL, enabling annotators to provide feedback and golden solutions while supporting cluster-based log sampling to reduce annotation workload. Use when AI pipeline quality needs iterative measurement — integrates deepeval GEval metrics (Root Cause Accuracy, Solution Steps Alignment) via vLLM OpenAI-compatible API to compare AI-generated solutions against human annotations. Helm deploys two init containers: oc wait blocking on backend-init job (requires RBAC job-reader Role for get/list/watch on batch/jobs) and conditional annotation.json seed to 1Gi PVC; DATABASE_URL is rewritten from +asyncpg to psycopg2 at init via replace chain, and feedback is persisted atomically with os.replace. Critical gotchas: deepeval requires /app/.deepeval with chmod 777 and HOME=/app or container crashes with PermissionError under OpenShift restricted SCC; Gradio needs WebSocket nginx annotations (proxy-buffering: off, upgrade headers) or live UI fails through ingress; psycopg2.errors.UndefinedTable is caught gracefully when pipeline hasn't run."
metadata:
  type: component
tags:
  tech_stack: [gradio, python, sqlalchemy, psycopg2, deepeval, pandas, uv]
  ai_pattern: [evaluation, data-pipeline, annotation]
  platform: [openshift, rhoai]
  data_layer: [pgvector]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Gradio annotation interface for reviewing LLM-generated log analysis with deepeval GEval metrics"
    approach: "A"
---

# Annotation Interface

## Overview

A Gradio-based web application that provides a human-in-the-loop annotation interface for reviewing AI-generated pipeline outputs. It reads structured data (log summaries, solutions, context) from PostgreSQL via SQLAlchemy, lets annotators provide feedback and golden solutions, and runs LLM-based evaluation using deepeval GEval metrics to compare AI outputs against human annotations. Used in RHOAI quickstarts where AI pipeline quality needs to be measured and iteratively improved.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12, Gradio 5.42+
- **Container image:** `quay.io/rh-ai-quickstart/alm-annotation-interface:latest`
- **Base image:** `registry.access.redhat.com/ubi8/python-312`
- **Package manager:** uv (copied from `ghcr.io/astral-sh/uv:0.9.7`)
- **Key dependencies:** gradio, sqlalchemy, psycopg2-binary, deepeval, pandas
- **Helm subchart:** `annotation-interface` (v0.1.0) under parent chart `ansible-log-monitor`

## Key Patterns

### Gradio Dark-Theme Annotation UI

The interface uses `gr.Blocks` with a custom dark theme and JavaScript auto-redirect to enforce dark mode. The UI is organized into sections: navigation/evaluation controls, AI-generated output display, and human annotation tabs (feedback, golden solution, expected behavior, context assessment).

```python
# From services/annotation_interface/app.py
with gr.Blocks(
    css=css,
    head=head_js,  # JS auto-redirects to ?__theme=dark
    theme=gr.themes.Soft(
        primary_hue="indigo",
        secondary_hue="blue",
        neutral_hue="slate",
        font=gr.themes.GoogleFont("Inter"),
        font_mono=gr.themes.GoogleFont("JetBrains Mono"),
    ).set(
        body_background_fill="*neutral_950",
        body_text_color="*neutral_100",
        block_background_fill="*neutral_900",
    ),
    title="Ansible Log Annotation Interface",
) as interface:
```

### SQLAlchemy Sync Engine from Async DATABASE_URL

The component receives a `DATABASE_URL` configured for asyncpg (from a shared secret) but requires a synchronous connection. It rewrites the URL at init time to use psycopg2.

```python
# From services/annotation_interface/app.py
self.engine = create_engine(
    os.getenv("DATABASE_URL")
    .replace("+asyncpg", "")
    .replace("postgresql", "postgresql+psycopg2")
)
```

### Cluster-Based Log Sampling

Supports toggling between viewing all log entries and viewing one representative sample per log cluster. This reduces annotation workload when many logs share the same template.

```python
# From services/annotation_interface/app.py
def toggle_cluster_sampling(self, show_sample: bool):
    if show_sample:
        cluster_samples = {}
        for entry in self.all_data:
            cluster_id = entry.get("log_cluster")
            if cluster_id is None:
                cluster_id = f"_no_cluster_{entry.get('id')}"
            if cluster_id not in cluster_samples:
                cluster_samples[cluster_id] = entry
        self.data = list(cluster_samples.values())
```

### DeepEval GEval LLM-as-Judge Evaluation

The annotation interface integrates deepeval to run LLM-based evaluation comparing AI-generated solutions against human golden solutions. It defines custom GEval metrics (Root Cause Accuracy, Solution Steps Alignment) using a vLLM-served model via OpenAI-compatible API.

```python
# From services/annotation_interface/test_end_to_end.py
llm_vllm = LocalModel(
    model=os.environ.get("OPENAI_MODEL"),
    base_url=os.environ.get("OPENAI_API_ENDPOINT"),
    api_key=os.environ.get("OPENAI_API_TOKEN"),
    temperature=float(os.environ.get("OPENAI_TEMPERATURE")),
)

root_cause_metric = GEval(
    name="Root Cause Accuracy",
    criteria="Evaluate whether the actual output correctly identifies "
             "the same root cause/underlying problem as the expected output",
    evaluation_params=[
        LLMTestCaseParams.INPUT,
        LLMTestCaseParams.ACTUAL_OUTPUT,
        LLMTestCaseParams.EXPECTED_OUTPUT,
    ],
    model=llm_vllm,
)
```

### Init Container: Wait for Backend Job

The Helm deployment uses an init container with `oc wait` to block until the backend init job completes, ensuring database tables exist before the annotation interface loads data.

```yaml
# From deploy/helm/.../annotation-interface/templates/deployment.yaml
initContainers:
  - name: wait-for-{{ .Values.global.servicesNames.backend }}-init
    image: quay.io/openshift/origin-cli:latest
    command:
      - sh
      - -c
      - |
        echo "Waiting for {{ .Values.global.servicesNames.backend }}-init job..."
        oc wait --for=condition=complete --timeout=600s \
          job/{{ .Values.global.servicesNames.backend }}-init \
          -n {{ .Release.Namespace }}
```

### Init Container: Seed Annotation Data to PVC

A second init container copies the bundled `annotation.json` from the container image to the PVC only if it does not already exist, preserving human annotations across pod restarts.

```yaml
# From deploy/helm/.../annotation-interface/templates/deployment.yaml
- name: init-annotation-data
  image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
  command:
    - sh
    - -c
    - |
      if [ -f /mnt/data/feedback/annotation.json ]; then
        echo "annotation.json already exists, skipping copy."
      else
        mkdir -p /mnt/data/feedback
        cp /app/data/feedback/annotation.json /mnt/data/feedback/annotation.json
      fi
  volumeMounts:
    - name: data-volume
      mountPath: /mnt/data
```

### Atomic File Writes for Feedback Persistence

Feedback data is saved atomically by writing to a temp file then using `os.replace` to rename, preventing data corruption if the process crashes mid-write.

```python
# From services/annotation_interface/app.py
temp_file = self.feedback_file + ".tmp"
with open(temp_file, "w") as f:
    json.dump(self.feedback_data, f, indent=2)
os.replace(temp_file, self.feedback_file)
```

## Configuration

- **Environment variables:**
  - `DATABASE_URL` -- PostgreSQL connection URI (from `pgvector` secret, key `uri`)
  - `ALERTS_TABLE_NAME` -- Database table to read pipeline results from (default: `grafanaalert`)
  - `GRADIO_SERVER_NAME` -- Bind address (default: `0.0.0.0`)
  - `GRADIO_SERVER_PORT` -- HTTP port (default: `7861`)
  - `OPENAI_MODEL`, `OPENAI_API_ENDPOINT`, `OPENAI_API_TOKEN`, `OPENAI_TEMPERATURE` -- vLLM model endpoint for deepeval (from `model-secret`)
  - `PYTHONPATH` -- Set to `/app` in Helm values
- **Config files:** `data/feedback/annotation.json` -- persisted annotation and evaluation results (JSON)
- **Helm values:**
  - `persistence.enabled: true` with 1Gi PVC for annotation data
  - `route.enabled: true` with TLS edge termination for OpenShift
  - `ingress.enabled: true` with WebSocket proxy annotations for Gradio
  - `rbac.create: true` -- creates Role/RoleBinding for job-reader (needed by init container `oc wait`)
  - `service.port: 7861` / `service.targetPort: 7861`

## Known Gotchas

- **deepeval cache directory permissions:** The Containerfile creates `/app/.deepeval` with `chmod 777` and sets `HOME=/app` because deepeval tries to create a cache directory under `$HOME/.deepeval`, which fails as non-root in OpenShift's restricted SCC. Without this, the container crashes on startup with a `PermissionError`.
- **Async-to-sync DATABASE_URL rewrite:** The component receives a `DATABASE_URL` with `+asyncpg` suffix (shared by the async backend) but needs synchronous psycopg2. The string replacement chain (`.replace("+asyncpg", "").replace("postgresql", "postgresql+psycopg2")`) handles this transparently but would break if the URL format changes.
- **WebSocket proxy for Gradio:** The Helm ingress values include extensive nginx annotations for WebSocket support (`proxy-buffering: off`, `upgrade`, `connection: upgrade`). Without these, Gradio's live UI updates fail through the ingress.
- **Init container requires RBAC:** The `oc wait` init container needs `get`, `list`, `watch` on `batch/jobs`, provided by the `job-reader` Role. If RBAC creation is disabled (`rbac.create: false`), the init container will fail with a permissions error.
- **Table not found handling:** If the PostgreSQL table does not exist yet (pipeline has not run), the app catches `psycopg2.errors.UndefinedTable` and gracefully shows empty data rather than crashing.

## Testing Notes

- Verify the Gradio UI is accessible via the OpenShift Route (port 7861)
- Confirm the init container waits for the backend-init job before starting
- Check that `annotation.json` persists across pod restarts (PVC-backed)
- Run the deepeval evaluation from the UI and verify metrics are computed against the vLLM endpoint
- Confirm navigation and cluster sampling work with the database-loaded entries

## Related Patterns

- `pgvector.md` -- the PostgreSQL database this component reads from
- `fastapi-backend.md` -- the backend service whose init job must complete first
