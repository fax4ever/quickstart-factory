---
name: aap-log-collector
description: "Polling sidecar that fetches Ansible Automation Platform job logs via API and writes them to a shared volume"
summary: "AAP Log Collector is a Python 3.12 (UBI8, sole dependency `requests>=2.31.0`) sidecar deployed via Helm `alloy.controller.extraContainers` (no dedicated subchart) alongside Grafana Alloy, polling an AAP API for completed job logs and writing them to a shared PVC (`ansible-logs-pvc`) for Alloy/Loki ingestion and Grafana alerting. Use when collecting AAP job logs into an observability pipeline -- it filters for `successful`/`failed` final states using paginated API fetching with in-memory `Set[int]` dedup, writing files atomically (temp-then-rename) to `{OUTPUT_DIR}/{CLUSTER_NAME}/job-{job_id}.txt`. Critical config: `Config.from_env()` dataclass with `AAP_API_URL`, `OUTPUT_DIR`, `POLL_INTERVAL=300`, `PAGE_SIZE` (must be 1--200); a `wait-for-aap-mock` init container ensures API readiness and data availability before first poll cycle. In-memory `processed_job_ids` resets on pod restart causing idempotent re-processing of all final-state jobs; SELinux `:z` volume mount suffix must be removed on macOS; container runs as non-root UID 1001 per OpenShift restricted SCC."
metadata:
  type: component
tags:
  tech_stack: [python, requests]
  ai_pattern: [data-pipeline]
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Sidecar container in the Alloy pod that polls AAP mock API for completed job logs and writes them to a shared PVC for Grafana Alloy ingestion"
    approach: "A"
---

# AAP Log Collector

## Overview

A lightweight Python polling service that collects job logs from an Ansible Automation Platform (AAP) API and writes them as individual text files to a shared volume. In the ansible-log-analysis quickstart it runs as a sidecar container inside the Grafana Alloy pod, sharing a PVC so Alloy can ingest the log files for Loki storage and Grafana alerting. The service tracks processed job IDs in-memory and only writes logs for jobs in a final state (successful or failed).

## Tech Stack & Dependencies
- **Runtime:** Python 3.12 on `registry.access.redhat.com/ubi8/python-312`
- **Container image:** `quay.io/rh-ai-quickstart/alm-aap-log-collector:latest`
- **Key dependencies:** `requests>=2.31.0` (sole runtime dependency)
- **Helm subchart:** None -- deployed as an `extraContainers` sidecar in the Alloy Helm chart

## Key Patterns

### Sidecar Container via Helm extraContainers

The collector runs as a sidecar alongside Grafana Alloy rather than as its own Deployment. Both containers share the same PVC (`ansible-logs-pvc`), so Alloy can read log files the collector writes without cross-pod networking.

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (under alloy.controller)
extraContainers:
  - name: alm-aap-log-collector
    image: quay.io/rh-ai-quickstart/alm-aap-log-collector:latest
    env:
      - name: AAP_API_URL
        value: "http://alm-aap-mock:8080"
      - name: OUTPUT_DIR
        value: "/var/log/ansible_logs"
      - name: POLL_INTERVAL
        value: "300"
    volumeMounts:
      - name: ansible-logs
        mountPath: /var/log/ansible_logs
    resources:
      limits:
        cpu: 200m
        memory: 256Mi
      requests:
        cpu: 50m
        memory: 128Mi
```

### Paginated API Polling with In-Memory Dedup

The collector fetches all jobs from the AAP API using pagination, filters for final states only, and tracks processed IDs in a global `Set[int]` to avoid re-writing logs. The poll cycle repeats on a configurable interval.

```python
# services/aap-log-collector/app/main.py
FINAL_STATES = {"successful", "failed"}
processed_job_ids: Set[int] = set()

def process_jobs(config: Config) -> int:
    all_jobs = fetch_all_jobs(config.aap_api_url, config.page_size)
    jobs_to_process = [
        job for job in all_jobs
        if job["id"] not in processed_job_ids
        and job.get("status") in FINAL_STATES
    ]
    # ... fetch logs, write files, mark processed
```

### Atomic File Writes

Log files are written via a temp-file-then-rename pattern to prevent partial writes if the container is interrupted mid-cycle.

```python
# services/aap-log-collector/app/main.py
def write_log_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)  # atomic rename
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise
```

### Dataclass-Based Config from Environment

All configuration is loaded from environment variables with sensible defaults using a Python `dataclass` with a `from_env()` classmethod and a `validate()` method that enforces constraints (e.g., `PAGE_SIZE` must be 1--200).

```python
# services/aap-log-collector/app/config.py
@dataclass
class Config:
    aap_api_url: str
    output_dir: str
    cluster_name: str
    poll_interval: int
    log_level: str
    page_size: int = 100

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            aap_api_url=os.getenv("AAP_API_URL", "http://alm-aap-mock:8080"),
            output_dir=os.getenv("OUTPUT_DIR", "/var/log/ansible_logs"),
            ...
        )
```

## Configuration
- **Environment variables:**
  - `AAP_API_URL` -- Base URL of the AAP API (default: `http://alm-aap-mock:8080`)
  - `OUTPUT_DIR` -- Directory to write log files (default: `/var/log/ansible_logs`)
  - `CLUSTER_NAME` -- Subdirectory name under OUTPUT_DIR; organizes logs per cluster (default: `default-cluster`)
  - `POLL_INTERVAL` -- Seconds between poll cycles (default: `300`, i.e. 5 minutes)
  - `PAGE_SIZE` -- Jobs per API page, must be 1--200 (default: `100`)
  - `LOG_LEVEL` -- Python logging level (default: `INFO`)
- **Config files:** None -- all configuration via env vars
- **Helm values:** Configured inline within `alloy.controller.extraContainers` in `values.yaml`; no dedicated subchart or values block

## Known Gotchas
- **In-memory dedup resets on restart:** The `processed_job_ids` set is held in memory, so a pod restart causes the collector to re-process all final-state jobs. This is idempotent (same files are overwritten) but generates redundant I/O. From `main.py`: the global `processed_job_ids: Set[int] = set()` is never persisted.
- **SELinux volume mount suffix:** The compose.yaml includes `:z` on the shared volume mount. A comment in `deploy/local/compose.yaml` notes: "macOS users: remove :z if you get 'lsetxattr: operation not supported' error".
- **Container runs as non-root (UID 1001):** The Containerfile explicitly sets `USER 1001` after granting group-0 write access with `chmod -R g=u /app`, following OpenShift restricted SCC conventions.
- **Init container ordering in Helm:** An init container `wait-for-aap-mock` runs before the Alloy pod starts, checking both the AAP mock health endpoint and that job count > 0, ensuring the sidecar has data to poll on first cycle.

## Testing Notes
- The component's Makefile provides a `make run` target that builds and runs the container locally with `AAP_API_URL=http://localhost:8082` and a bind-mounted `test-logs/` directory
- In the compose deployment, the collector has a healthcheck: `pgrep -f 'python -m app.main'` with 30s interval
- Output files land at `{OUTPUT_DIR}/{CLUSTER_NAME}/job-{job_id}.txt`; verify by listing that directory after a poll cycle

## Related Patterns
- Shared PVC sidecar pattern (Alloy + collector in one pod)
- Grafana Alloy log ingestion pipeline
- AAP mock API as a data source for log generation
