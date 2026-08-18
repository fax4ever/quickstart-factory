---
name: compose-local-dev-loki-grafana-hybrid-services
description: Local dev compose with Loki/Grafana/Promtail observability stack plus native uv-run Python processes
summary: "Provides hybrid local development at deploy/local/compose.yaml combining 10+ Compose services (Loki 4GB, Grafana anonymous-Admin with inline entrypoint datasource provisioning, Promtail multiline Ansible log aggregation with regex cluster_name extraction mirroring OpenShift Alloy, PostgreSQL user/password/logsdb, MinIO minioadmin/minioadmin, TEI nomic-embed-text-v1.5, RAG, AAP mock 4GB/120s start_period for 500 files, log collector, Phoenix) on a shared alm network with 3 native uv-run processes (backend, UI, annotation) for live code reloading. Use when building AI quickstarts requiring a full Loki observability pipeline locally — the single hybrid approach containerizes infrastructure while running application code natively via Makefile uv run targets for fast iteration, unlike fully containerized deployments where backend/UI are also in compose. Critical config: service_healthy dependency chains between services, build contexts from repo root (context: ../..),  shared Docker volumes between AAP mock and log collector for log file passing, .env loaded by Makefile, and Grafana datasource auto-provisioned via shell entrypoint. Gotchas: SELinux :z volume suffix fails on macOS with \"lsetxattr: operation not supported\" errors, Promtail requires root/privileged, Phoenix must connect to PostgreSQL via Docker-internal URL (postgres:5432) not DATABASE_URL since the backend runs outside the Docker network, and TEI embedding needs start_period: 180s for model loading."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [fastapi, gradio, grafana, loki, postgresql, minio]
  ai_pattern: [agents, rag, embeddings]
  platform: []
  data_layer: [pgvector, minio, faiss]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Hybrid compose+native: 10 compose services (Loki, Grafana, Promtail, Phoenix, PostgreSQL, MinIO, TEI, RAG, AAP mock, log collector) plus 3 native uv-run processes (backend, UI, annotation)"
    approach: "A"
---

# Compose Local Dev with Loki/Grafana Stack and Hybrid Native Processes

## Overview

This pattern provides a local development environment that combines containerized infrastructure services via Docker/Podman Compose with native Python processes run via `uv run`. The compose stack includes a full Loki observability pipeline (Loki, Grafana, Promtail), database and storage services (PostgreSQL, MinIO), AI services (TEI embedding, RAG), and mock services (AAP mock, log collector). Backend, UI, and annotation interface run as native processes for faster iteration.

## Pattern Description

The `compose.yaml` at `deploy/local/` defines 10+ services on a shared `alm` network. Unlike the OpenShift deployment which uses Alloy for log collection, the local dev uses Promtail. The backend, UI, and annotation interface are not in compose -- they are started via `uv run` from the Makefile, connecting to compose services over localhost. This hybrid approach enables live code reloading for the application code while keeping infrastructure containerized.

## Implementation

### Loki Observability Stack

Loki, Grafana, and Promtail form the local log observability pipeline:

```yaml
# deploy/local/compose.yaml (excerpt)
loki:
  image: grafana/loki:3.6.2
  ports:
    - "3100:3100"
  volumes:
    - ./config/loki/local-config.yaml:/etc/loki/local-config.yaml:z
    - loki_data:/loki
  command: -config.file=/etc/loki/local-config.yaml
  deploy:
    resources:
      limits:
        memory: 4g

grafana:
  image: grafana/grafana:latest
  ports:
    - "3000:3000"
  environment:
    - GF_AUTH_ANONYMOUS_ENABLED=true
    - GF_AUTH_ANONYMOUS_ORG_ROLE=Admin
  entrypoint:
    - sh
    - -euc
    - |
      mkdir -p /etc/grafana/provisioning/datasources
      cat <<EOF > /etc/grafana/provisioning/datasources/ds.yaml
      apiVersion: 1
      datasources:
      - name: Loki
        type: loki
        access: proxy
        url: http://loki:3100
        isDefault: true
      EOF
      /run.sh

promtail:
  image: grafana/promtail:latest
  user: "root"
  privileged: true
  volumes:
    - ./config/promtail/promtail-local-config.yaml:/etc/promtail/config.yaml:z
    - ansible_logs:/var/log/ansible_logs:ro,z
```

### AAP Mock and Log Collector with Shared Volume

The AAP mock and log collector share a Docker volume for log files:

```yaml
# deploy/local/compose.yaml (excerpt)
aap-log-collector:
  image: quay.io/rh-ai-quickstart/alm-aap-log-collector:latest
  volumes:
    - ansible_logs:/var/log/ansible_logs:z
  depends_on:
    aap-mock:
      condition: service_healthy
  healthcheck:
    test: ["CMD-SHELL", "pgrep -f 'python -m app.main' || exit 1"]

aap-mock:
  image: quay.io/rh-ai-quickstart/alm-aap-mock:latest
  ports:
    - "8082:8080"
  volumes:
    - aap_mock_data:/data
    - .staging/sample-logs/:/app/sample-logs:ro,z
  deploy:
    resources:
      limits:
        memory: 4G
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
    start_period: 120s  # Give time to load 500 files
```

### Embedding and RAG Services with Dependency Chain

The RAG service depends on both the embedding service and MinIO:

```yaml
# deploy/local/compose.yaml (excerpt)
alm-embedding:
  image: quay.io/rh-ai-quickstart/alm-rag:tei-rag-v1
  environment:
    - MODEL_ID=nomic-ai/nomic-embed-text-v1.5
    - MAX_CLIENT_BATCH_SIZE=32
  healthcheck:
    start_period: 180s  # Model loading can take 3+ minutes

alm-rag:
  build:
    context: ../..
    dockerfile: services/rag/Containerfile
  depends_on:
    alm-embedding:
      condition: service_healthy
    minio:
      condition: service_healthy
```

### Backend with Build Context from Repo Root

The backend compose service builds from the repo root context:

```yaml
# deploy/local/compose.yaml (excerpt)
backend:
  build:
    context: ../..
    dockerfile: Containerfile
  depends_on:
    postgres:
      condition: service_healthy
    alm-embedding:
      condition: service_healthy
    alm-rag:
      condition: service_started
```

### Promtail Ansible Log Pipeline

The local Promtail config mirrors the OpenShift Alloy pipeline with equivalent stages for multiline aggregation and status extraction:

```yaml
# deploy/local/config/promtail/promtail-local-config.yaml (excerpt)
scrape_configs:
  - job_name: ansible_logs
    static_configs:
      - targets: [localhost]
        labels:
          __path__: /var/log/ansible_logs/*/*.txt
    pipeline_stages:
      - multiline:
          firstline: '^(PLAY\s+\[|TASK\s+\[|PLAY\s+RECAP\s+\*+)'
          max_lines: 2000
      - regex:
          source: filename
          expression: '/var/log/ansible_logs/(?P<cluster_name>[^/]+)/'
```

## Configuration

- **Key settings:** Grafana anonymous auth enabled as Admin for local dev; PostgreSQL user/password/db set to `user`/`password`/`logsdb`; MinIO defaults to `minioadmin`/`minioadmin`
- **Defaults:** Loki limited to 4GB memory; AAP mock needs up to 4GB for 500 file loading; embedding service needs 3+ minutes to load model
- **Dependencies:** Requires `docker-compose` or `podman-compose`; backend/UI/annotation need `uv` installed locally; `.env` file loaded by the Makefile from project root

## Gotchas

- Volume mount `:z` suffix is for SELinux relabeling on RHEL/Fedora -- macOS users may need to remove `,z` if they get "lsetxattr: operation not supported" errors (commented in `compose.yaml` lines 82-83 and `aap-log-collector` section)
- Promtail runs as `root` with `privileged: true` to access Docker socket for container log collection (though the Docker socket scrape config is currently commented out, see `promtail-local-config.yaml`)
- The backend, UI, and annotation services are defined in compose but used only for containerized deployments -- the local Makefile runs them natively via `uv run` instead (see `deploy/local/Makefile` lines 117-126)
- Phoenix connects to PostgreSQL using a Docker-internal URL (`postgresql+asyncpg://user:password@postgres:5432/logsdb`), not `DATABASE_URL`, because the backend process runs outside the Docker network (see `compose.yaml` line 74)

## Related Patterns

- `makefile-delegating-router-cluster-local.md` -- the Makefile that orchestrates this compose stack
- `helm-inline-grafana-alerting-loki-webhook.md` -- OpenShift equivalent of the Grafana/Loki stack
