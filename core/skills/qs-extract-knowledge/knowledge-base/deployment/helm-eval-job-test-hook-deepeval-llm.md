---
name: helm-eval-job-test-hook-deepeval-llm
description: LLM evaluation Job triggered as helm test hook with init container waiting for backend readiness
summary: "Runs deepeval-based LLM evaluation as a Helm test hook (`helm.sh/hook: test` with `before-hook-creation` delete policy) so `helm test <release>` or the `eval-k8s` Makefile target validates deployed chat quality without executing during install/upgrade -- use when post-deploy LLM answer quality must be gated before promotion. A busybox init container polls the backend health endpoint via `wget` (not `curl` -- busybox lacks it) until the full stack including model serving is ready, then the eval container runs with `BACKEND_URL`, `OPENAI_API_TOKEN` (from Helm values), and `DEEPEVAL_TELEMETRY_OPT_OUT: \"YES\"`; `eval.enabled` toggles Job creation, `EVAL_FEATURE` (chat/alerts) selects the suite, and `EVAL_DATASET` (ppe/bird) selects test data. Critical config: `backoffLimit: 0` with `restartPolicy: Never` ensures evaluation failures are definitive signals (not retried), `ttlSecondsAfterFinished: 600` auto-cleans completed Jobs after 10 minutes, and the same image runs locally via `podman-compose --profile eval` with prediction output mounted for environment consistency. Gotcha: `before-hook-creation` delete policy can hang if a previous Job is stuck in a non-terminal state, and OpenAI credentials must be set in Helm release values or the eval container will fail silently."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python]
  ai_pattern: [evaluation, agents]
  platform: [openshift]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Eval Job as helm.sh/hook: test with init container wait, deepeval framework, ttlSecondsAfterFinished: 600"
    approach: "A"
---

# LLM Evaluation Job as Helm Test Hook

## Overview

A Helm-templated Kubernetes Job that runs LLM evaluation (using the deepeval framework) as a `helm test` hook, allowing `helm test <release>` to validate the deployed application's LLM chat quality. The Job uses an init container to wait for the backend service to be ready before running the evaluation suite.

## Pattern Description

The eval Job is annotated with `helm.sh/hook: test` so it only runs when `helm test` is invoked (not during `helm install`/`upgrade`). It uses `helm.sh/hook-delete-policy: before-hook-creation` to clean up previous test runs. An init container polls the backend's health endpoint before the eval container starts, ensuring the full application stack (including model serving) is operational. The Makefile provides `eval-k8s` as a convenience target wrapping `helm test`.

## Implementation

### Helm Test Hook Job

```yaml
# deploy/helm/ppe-compliance-monitor/templates/eval-job.yaml
{{- if .Values.eval.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "ppe-compliance-monitor.fullname" . }}-eval
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      initContainers:
        - name: wait-for-backend
          image: "{{ .Values.initUtils.busybox.repository }}:{{ .Values.initUtils.busybox.tag }}"
          command:
            - /bin/sh
            - -c
            - |
              echo "Waiting for backend to be ready..."
              until wget -qO- http://{{ include "ppe-compliance-monitor.fullname" . }}-backend:{{ .Values.backend.port }}/api/ >/dev/null 2>&1; do
                echo "Backend not ready, retrying in 5s..."
                sleep 5
              done
              echo "Backend is ready"
      containers:
        - name: eval
          image: "{{ .Values.global.imageRegistry }}/{{ .Values.eval.image.repository }}:{{ .Values.eval.image.tag }}"
          env:
            - name: BACKEND_URL
              value: "http://{{ include "ppe-compliance-monitor.fullname" . }}-backend:{{ .Values.backend.port }}"
            - name: OPENAI_API_TOKEN
              value: {{ .Values.openai.apiToken | quote }}
            - name: DEEPEVAL_TELEMETRY_OPT_OUT
              value: "YES"
{{- end }}
```

### Makefile Target

The `eval-k8s` target wraps `helm test` with log output:

```makefile
# Makefile (excerpt)
eval-k8s:
	helm test $(HELM_RELEASE) --namespace $(NAMESPACE) --logs
```

### Local Eval via Compose Profile

The same eval image runs locally via a compose profile, with eval results mounted out:

```makefile
# Makefile (excerpt)
eval: check-openai-env
	@mkdir -p $(CURDIR)/app/evals/preds/$(EVAL_FEATURE)
	EVAL_FEATURE=$(EVAL_FEATURE) EVAL_DATASET=$(EVAL_DATASET) \
	podman-compose -f $(COMPOSE_FILE) --profile eval run --rm --no-deps --build \
	  -v $(CURDIR)/app/evals/preds:/evals/preds:z,U backend-eval
```

## Configuration

- **Key settings:** `eval.enabled` toggles Job creation; `EVAL_FEATURE` (chat or alerts) selects which evaluation suite to run; `EVAL_DATASET` (ppe or bird) selects the test dataset; `DEEPEVAL_TELEMETRY_OPT_OUT: "YES"` disables deepeval analytics
- **Defaults:** `backoffLimit: 0` (no retries -- evaluation failure is a definitive signal); `ttlSecondsAfterFinished: 600` (auto-cleanup after 10 minutes); `restartPolicy: Never`
- **Dependencies:** Backend must be fully operational including model serving and database; OpenAI credentials must be set in the Helm release values

## Gotchas

- The init container uses `wget` (busybox) instead of `curl` because the busybox image (`mirror.gcr.io/library/busybox`) does not include curl
- `backoffLimit: 0` means the Job will not retry on failure, which is intentional -- LLM eval failures should be investigated, not retried
- `ttlSecondsAfterFinished: 600` automatically cleans up completed/failed Jobs after 10 minutes, preventing resource accumulation from repeated `helm test` runs
- `helm.sh/hook-delete-policy: before-hook-creation` deletes the previous Job before creating a new one, which can hang if the previous Job is stuck in a non-terminal state
- The same evaluation image is used for both local (`podman-compose --profile eval`) and cluster (`helm test`) execution, ensuring consistency between environments

## Related Patterns

- `github-actions-kind-e2e-llm-eval-suite.md` -- alternative pattern running evaluation as a CI job
- `compose-local-dev-ovms-mediamtx-video-eval-phoenix.md` -- the compose file that provides local eval execution
