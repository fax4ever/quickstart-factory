---
name: healthcare-guardrails-notebook
description: Jupyter notebook demonstrating TrustyAI guardrails for healthcare AI with PII, content, and injection detection
summary: "Provides a Jupyter notebook demo interface for the guardrailing-llms quickstart, exercising TrustyAI GuardrailsOrchestrator's combined /all/ route to chain regex (PII/SSN), HAP, prompt injection, and gibberish detectors in a single OpenAI-compatible /v1/chat/completions request against Llama 3.2 3B Instruct on vLLM. Use as the primary interactive demo when deploying guardrailing-llms on RHOAI — the notebook runs in a Kubeflow workbench (s2i-minimal-notebook:2025.1) auto-provisioned via Helm with a git-clone Job that uses oc exec, requiring all 7 pods (3 detectors, LLM, orchestrator, workbench, clone job) to reach Running/Completed before testing four sequential cases (normal, PII/SSN, HAP, prompt injection). Detector routes are defined in fms-orchestr8-config-gateway ConfigMap while thresholds (gibberish: 0.35, prompt injection: 0.5, HAP: 0.5) are set in Helm values.yaml rendered into fms-orchestr8-config-nlp; the notebook uses only `from requests import post` with no auth headers for in-cluster calls to gorch-sample-service.guardrails-demo.svc.cluster.local:8090. Critical gotcha: the orchestrator URL hardcodes namespace guardrails-demo requiring manual update if installed elsewhere, the git-clone Job needs pod exec RBAC via workbench-role.yaml, and blocked responses return empty choices with detections/warnings fields but detector thresholds are not surfaced in the notebook itself."
metadata:
  type: component
tags:
  tech_stack: [jupyter, python, trustyai, vllm]
  ai_pattern: [guardrails, model-serving]
  platform: [rhoai, openshift, kserve]
source_examples:
  - quickstart: "guardrailing-llms"
    repo: "https://github.com/rh-ai-quickstart/guardrailing-llms"
    notes: "Healthcare AI assistant notebook with TrustyAI GuardrailsOrchestrator gateway for PII, HAP, prompt injection, and gibberish detection"
    approach: "A"
---

# Healthcare Guardrails Notebook

## Overview

A Jupyter notebook (`docs/healthcare-guardrails.ipynb`) that serves as the primary demo interface for the guardrailing-llms quickstart. It exercises the TrustyAI GuardrailsOrchestrator gateway by sending healthcare-themed queries through a combined detector pipeline covering PII detection, content moderation, prompt injection protection, and gibberish filtering. The notebook runs inside a Kubeflow Notebook workbench deployed as part of the Helm chart on RHOAI.

## Tech Stack & Dependencies

- **Runtime:** Python (Jupyter Minimal CPU notebook, `s2i-minimal-notebook:2025.1`)
- **Container image:** `image-registry.openshift-image-registry.svc:5000/redhat-ods-applications/s2i-minimal-notebook:2025.1`
- **Key dependencies:** `requests` (only external library used in the notebook itself)
- **Backing services:** TrustyAI GuardrailsOrchestrator (`gorch-sample-service`), Llama 3.2 3B Instruct via vLLM, four detector InferenceServices (gibberish, prompt injection, HAP, regex)
- **Helm subchart:** None (workbench is deployed directly by the parent chart as a `kubeflow.org/v1 Notebook` CR)

## Key Patterns

### Guardrails Gateway `/all/` Route

The notebook uses a single combined endpoint that applies all configured detectors in one request, rather than calling each detector individually. The gateway config defines named routes; the `/all/` route chains regex, HAP, prompt injection, and gibberish detectors.

```python
guardrails_gateway_endpoint = f'{guardrails_orchestrator_route}/all/v1/chat/completions'

def send_query(query):
    payload = {
        'model': model_name,
        'messages': [{'content': query, 'role': 'user'}]
    }
    response = post(guardrails_gateway_endpoint, json=payload)
    pprint(response.json())
```

The gateway route configuration in `fms-orchestr8-config-gateway` ConfigMap defines which detectors apply to input vs output:

```yaml
routes:
  - name: all
    detectors:
      - regex
      - hap
      - prompt_injection
      - gibberish
  - name: passthrough
    detectors:
```

### OpenAI-Compatible Chat Completions API

The GuardrailsOrchestrator gateway exposes an OpenAI-compatible `/v1/chat/completions` endpoint. The notebook sends standard `messages` format payloads with a `model` field pointing to the vLLM-served LLM name.

```python
model_name = 'llama-32-3b-instruct'
guardrails_orchestrator_route = 'http://gorch-sample-service.guardrails-demo.svc.cluster.local:8090'
```

### Blocked Response Structure

When a detector triggers, the response returns empty `choices` (no model output reaches the user) and includes `warning` and `detections` fields with details about which detector flagged the input:

- **PII (regex detector):** Returns a `SocialSecurity` detection type for SSN patterns
- **HAP (hate-and-profanity detector):** Returns a `sequence_classifier` detection for explicit language
- **Prompt injection detector:** Returns a `sequence_classifier` detection for override attempts

### Workbench Auto-Provisioning with Git Clone Job

The notebook is delivered to users automatically. The Helm chart deploys a Kubeflow `Notebook` CR with a PVC, then a Kubernetes `Job` waits for the workbench pod to be running and clones the repo into it:

```yaml
# workbench-job-clone.yaml (init container waits for workbench)
initContainers:
  - name: wait-for-workbench
    command: ["/bin/bash"]
    args:
      - -ec
      - |
        echo "Waiting for workbench pod..."
        while [ -z "$(oc get pods -n {{ .Release.Namespace }} -l notebook-name={{ .Values.workbench.name }} -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep Running)" ]; do
          sleep 2
        done
```

## Configuration

- **Environment variables:**
  - `model_name`: Set in notebook cell to `llama-32-3b-instruct` (must match the InferenceService name)
  - `guardrails_orchestrator_route`: In-cluster service URL for the GuardrailsOrchestrator gateway (`http://gorch-sample-service.guardrails-demo.svc.cluster.local:8090`)
  - `NOTEBOOK_ARGS`: Configured in the Notebook CR spec with JupyterLab server settings (port 8888, empty token/password, base URL with namespace)
  - `JUPYTER_IMAGE`: Set to the workbench container image reference
- **Config files:** None within the notebook itself; detector thresholds are configured in Helm `values.yaml` and rendered into the `fms-orchestr8-config-nlp` and `fms-orchestr8-config-gateway` ConfigMaps
- **Helm values:** `workbench.enabled`, `workbench.name`, `workbench.image`, `workbench.resources`, `workbench.storage.size`, `workbench.gitRepo.url`, `workbench.gitRepo.enabled`

## Known Gotchas

- The notebook hardcodes the orchestrator service URL with namespace `guardrails-demo` (`gorch-sample-service.guardrails-demo.svc.cluster.local`). If the Helm release is installed in a different namespace, the notebook URL must be manually updated to match.
- The workbench git-clone Job uses `oc exec` to run `git clone` inside the running workbench pod rather than using an init container or volume-based approach. This requires the Job's ServiceAccount to have RBAC permissions for pod exec (deployed via `workbench-role.yaml`).
- The notebook uses `post` directly from `requests` (imported as `from requests import post`) with no authentication headers. This works only for in-cluster service-to-service calls; external access would require additional auth configuration.
- Detector thresholds are set in `values.yaml` (gibberish: 0.35, prompt injection: 0.5, HAP: 0.5) but are not surfaced in the notebook. Users may need to adjust these in the ConfigMap if detectors are too aggressive or too lenient.

## Testing Notes

- Deploy the Helm chart and wait for all 7 pods (3 detectors, 1 LLM, 1 orchestrator, 1 workbench, 1 clone job) to reach Running/Completed state
- Access the workbench via the RHOAI Dashboard under Data Science Projects, then open `docs/healthcare-guardrails.ipynb`
- The notebook includes four test cases that can be run sequentially: normal healthcare query (should pass), PII with SSN (should block), inappropriate language (should block), prompt injection attempt (should block)
- Verify blocked responses return empty `choices` and populated `detections`/`warnings` fields

## Related Patterns

- Deployment: See the overall guardrailing-llms architecture for how the GuardrailsOrchestrator, detectors, and LLM InferenceServices are wired together
- Component: See notebooks KB file for general Kubeflow Notebook workbench patterns on RHOAI
