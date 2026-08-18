---
name: api-security-gateway
description: Network-level API security (WAF, rate limiting, API spec enforcement) protecting AI inference endpoints
summary: "Deploys F5 Distributed Cloud Customer Edge (DaemonSet + StatefulSet in ves-system, connected via IPsec/SSL tunnel) onto OpenShift via multi-role Ansible playbook (ocp_preflight, hugepages, storage_validation, f5xc_mesh) to provide WAF, OpenAPI v3 shadow-API enforcement on base path /v1, and rate limiting for LlamaStack/vLLM inference endpoints -- complementary to AI-level guardrails-layer for defense-in-depth. Use when HTTP-transport-layer protection is needed for model-serving APIs against injection attacks (XSS, SQLi), undocumented endpoint exposure, and DoS; operates independently of prompt-semantic guardrails with a single approach (Approach A: F5 XC CE deployed via Ansible). CE registers via vpm-cfg ConfigMap (ClusterName, Token, MauriceEndpoint, CertifiedHardware: k8s-minikube-voltmesh) with Ansible auto-approving site registration via F5 XC API; HTTP Load Balancer origin pool forwards to llamastack.<namespace>:8321 while Streamlit frontend optionally routes inference through configurable XC URL but RAG/pgvector queries always bypass the gateway directly to local LlamaStack. Gotchas: HugePages require MachineConfigPool/Tuned profile and node reboot, CE needs three 1Gi PVCs with privileged security context, Prometheus deployment requires hostPort patching, WAF/rate-limiting/API-protection policies are F5 XC Console UI configuration (not IaC), and tenant subdomain is auto-discovered from API token via discover_tenant.yml."
metadata:
  type: architecture
tags:
  tech_stack: [streamlit, llamastack, python, vllm, ansible]
  ai_pattern: [model-serving, rag]
  platform: [rhoai, openshift, f5-distributed-cloud]
  data_layer: [pgvector]
source_examples:
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/f5-api-security"
    notes: "F5 Distributed Cloud Customer Edge deployed via Ansible onto OpenShift, providing WAF, API spec enforcement, and rate limiting for LlamaStack inference endpoints exposed through an HTTP Load Balancer"
    approach: "A"
---

# API Security Gateway

## Overview

This architecture places a network-level API security gateway in front of AI model inference endpoints, protecting them against traditional web application attacks (XSS, SQL injection), shadow/undocumented API exposure, and denial-of-service through rate limiting. Unlike AI-level guardrails that inspect prompt content for safety violations, this pattern operates at the HTTP transport layer -- intercepting, inspecting, and enforcing policies on raw API requests before they reach the model-serving backend. The gateway is deployed as a separate infrastructure component (F5 Distributed Cloud Customer Edge) that runs alongside the AI workloads on the same OpenShift cluster.

## Data Flow

1. External client sends an OpenAI-compatible request (e.g., `POST /v1/chat/completions`) to the F5 XC HTTP Load Balancer endpoint
2. F5 XC Load Balancer receives the request and applies security policies in sequence:
   a. WAF policy evaluates the request body for injection patterns (XSS, SQLi)
   b. API spec enforcement checks the request path against the uploaded OpenAPI specification -- undocumented endpoints are blocked as shadow APIs
   c. Rate limiting checks per-client request counts against the configured threshold (e.g., 10 requests/minute)
3. If any policy triggers a violation in Block mode, the request is rejected immediately (403 Forbidden or 429 Too Many Requests) -- the request never reaches the model
4. If all policies pass, the Load Balancer forwards the request to the LlamaStack service inside the cluster via the origin pool (K8s service discovery on port 8321)
5. LlamaStack routes the request to the vLLM model for inference
6. The model response is returned through the Load Balancer to the client
7. The Streamlit frontend can optionally route its inference requests through the F5 XC endpoint by configuring the XC URL in the Settings page, enabling the security policies to protect the chatbot's inference calls

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| External client / Streamlit frontend | F5 XC HTTP Load Balancer | HTTPS | Inference requests routed through API security |
| F5 XC Load Balancer | LlamaStack service (port 8321) | HTTP (K8s service) | Forward approved requests to model backend |
| F5 XC Customer Edge (ves-system) | F5 XC Console (Volterra cloud) | IPsec/SSL tunnel | CE registration, policy sync, telemetry |
| Streamlit frontend | LlamaStack service (port 8321) | HTTP (direct) | Local RAG queries (vector store search) bypass the gateway |
| Ansible playbook | OpenShift API | HTTPS | Deploy CE manifest, configure HugePages, validate storage |
| Ansible playbook | F5 XC API | HTTPS | Auto-approve site registration, poll for ONLINE state |

## Key Integration Points

### F5 XC Customer Edge Deployment via Ansible

The CE is deployed onto OpenShift as a DaemonSet (volterra-ce-init) and StatefulSet (vp-manager) in the `ves-system` namespace. An Ansible playbook orchestrates the full lifecycle: preflight checks, HugePages configuration, storage validation, CE manifest application, and site registration approval.

```yaml
# deploy/ansible/site.yml (lines 37-48)
  roles:
    - role: ocp_preflight
      tags: [preflight, step1]

    - role: hugepages
      tags: [hugepages, step1]

    - role: storage_validation
      tags: [storage, step1]

    - role: f5xc_mesh
      tags: [mesh, step2]
```

### CE Configuration via ConfigMap

The vp-manager StatefulSet reads its configuration from a ConfigMap that specifies the cluster name, registration token, Maurice endpoints, and certified hardware type. The cluster name and token are the primary credentials linking this CE to the F5 XC tenant.

```yaml
# deploy/ansible/roles/f5xc_mesh/templates/ce_k8s.yml.j2 (lines 139-152)
apiVersion: v1
kind: ConfigMap
metadata:
  name: vpm-cfg
  namespace: {{ f5xc_namespace }}
data:
 config.yaml: |
  Vpm:
    ClusterName: {{ f5xc_cluster_name }}
    ClusterType: ce
    Config: /etc/vpm/config.yaml
    DisableModules: ["recruiter"]
    MauriceEndpoint: {{ f5xc_maurice_endpoint }}
    MauricePrivateEndpoint: {{ f5xc_maurice_private_endpoint }}
    PrivateNIC: eth0
    SkipStages: ["osSetup", "etcd", "kubelet", "master", "pool", "voucher", "workload", "controlWorkload", "csi"]
    Token: {{ f5xc_token }}
    CertifiedHardware: {{ f5xc_certified_hardware }}
```

### Auto-Approval of Site Registration via F5 XC API

The Ansible playbook polls the F5 XC API for a pending site registration matching the cluster name, then approves it programmatically. This eliminates manual Console intervention.

```yaml
# deploy/ansible/roles/f5xc_mesh/tasks/approve_registration.yml (lines 116-135)
- name: Approve site registration via F5 XC API
  ansible.builtin.uri:
    url: "{{ f5xc_console_base }}/api/register/namespaces/system/registration/{{ f5xc_reg_name }}/approve"
    method: POST
    headers: "{{ f5xc_api_headers }}"
    body_format: json
    body:
      name: "{{ f5xc_reg_name }}"
      state: APPROVED
      passport:
        cluster_name: "{{ f5xc_cluster_name }}"
        cluster_size: "{{ f5xc_cluster_size | int }}"
        cluster_type: "{{ f5xc_cluster_type }}"
        latitude: "{{ f5xc_latitude | float }}"
        longitude: "{{ f5xc_longitude | float }}"
      tunnel_type: "{{ f5xc_tunnel_type }}"
    status_code: 200
  when: f5xc_reg_current_state | default('') in ['NEW', 'PENDING']
```

### HTTP Load Balancer Origin Pool to LlamaStack

The F5 XC HTTP Load Balancer is configured in the F5 XC Console (not via code) with an origin pool pointing to the LlamaStack Kubernetes service. The origin server type is "K8s Service Name of Origin Server on given Sites" with the service name `llamastack.<namespace>` on port 8321. This bridges the F5 XC control plane to the in-cluster service.

```
# Configured in F5 XC Console (not in code):
Origin Server Type: K8s Service Name of Origin Server on given Sites
Service Name:       llamastack.<namespace>
Virtual Site:       system/<site-name>
Network:            Outside Network
Port:               8321
```

### OpenAPI Spec for Shadow API Enforcement

An OpenAPI v3 specification file is included in the repository and uploaded to the F5 XC Console to define the approved API surface. Any endpoint not in the specification (e.g., `/v1/version`) is blocked as a shadow API when API Protection is enabled with a "Block" fall-through rule on base path `/v1`.

```json
// deploy/openapi-swagger-v3-fixed2-version.json (lines 1-6)
{
  "openapi": "3.0.1",
  "info": {
    "title": "FastAPI",
    "version": "0.1.0"
  },
  "paths": { ... }
}
```

### Frontend XC URL Routing

The Streamlit frontend allows users to configure an XC URL in the Settings page. When set, inference requests (chat completions) are routed through the F5 XC endpoint instead of directly to LlamaStack. Vector store queries always use the local LlamaStack endpoint because pgvector runs in-cluster.

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/chat.py (lines 104-111)
# Determine which client to use based on XC URL configuration
if "xc_url" in st.session_state and st.session_state.get("xc_url"):
    # Use XC URL client for all operations
    xc_url = st.session_state["xc_url"]
    client = llama_stack_api.create_client_with_url(xc_url)
else:
    # Use default endpoint client
    client = llama_stack_api.client
```

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/chat.py (lines 471-473)
# Always use local endpoint for vector DBs (pgvector is local, not on XC)
vector_dbs = list(llama_stack_api.client.vector_stores.list()) or []
```

## Prompt / Chain Patterns

The API security gateway operates entirely outside the prompt chain. It inspects raw HTTP request bodies (JSON payloads) for injection patterns, validates request paths against the OpenAPI spec, and counts requests for rate limiting. The gateway does not understand prompt semantics, context injection, or model behavior -- it treats inference requests as ordinary API traffic. This is complementary to AI-level guardrails (see [guardrails-layer](guardrails-layer.md)) which inspect prompt content for semantic safety violations.

## Gotchas

- The CE deployment requires HugePages enabled on the OpenShift node. The Ansible playbook applies a MachineConfigPool, a Tuned profile for boot-time HugePages allocation, and labels the node with a `hugepages_role_label` (default `worker-hp`). These node-level changes require the node to reboot (deploy/ansible/roles/hugepages/tasks/main.yml).
- The Prometheus deployment created by the CE may fail on OpenShift due to `hostPort` bindings. The Ansible playbook includes a workaround that patches the Prometheus deployment to remove `hostPort` entries from container port specs (deploy/ansible/roles/f5xc_mesh/tasks/main.yml lines 139-165).
- The CE requires three PersistentVolumeClaims (etcvpm, varvpm, data -- each 1Gi) and uses `privileged: true` security context for both the ce-init DaemonSet and vp-manager StatefulSet. The storage validation role checks that a default StorageClass exists and can provision dynamic PVs (deploy/ansible/roles/storage_validation/tasks/main.yml).
- WAF, API spec enforcement, and rate limiting are configured in the F5 XC Console UI, not via Infrastructure-as-Code in the repository. The repository provides the OpenAPI specification file and the Ansible deployment automation, but security policy configuration is a manual Console step documented in docs/securing_model_inference_use_cases.md.
- The tenant subdomain for the F5 XC API is auto-discovered from the API token via a discovery task (deploy/ansible/roles/f5xc_mesh/tasks/discover_tenant.yml). This can be overridden by setting `f5xc_tenant` in secrets.yml or the `F5XC_TENANT` environment variable.
- Vector store queries (RAG retrieval) always bypass the F5 XC gateway and go directly to the local LlamaStack endpoint. The code comment in chat.py (line 471) explains: "Always use local endpoint for vector DBs (pgvector is local, not on XC)." This means RAG retrieval traffic is never subject to WAF or rate limiting -- only the final LLM inference call can be routed through the gateway.
- The `certified_hardware` value `k8s-minikube-voltmesh` (deploy/ansible/group_vars/all/vars.yml line 12) is used for Kubernetes-based CE deployments regardless of the actual cluster type (OpenShift, EKS, etc.). This is the standard F5 XC hardware profile for non-bare-metal K8s deployments.

## Related Architectures

- [guardrails-layer](guardrails-layer.md) -- AI-level content safety (prompt injection, PII, toxicity) operates at the semantic layer; api-security-gateway operates at the HTTP transport layer. Both can be deployed simultaneously for defense-in-depth.
- [rag-pipeline](rag-pipeline.md) -- The RAG pipeline in this quickstart (Approach D) runs independently of the security gateway; RAG retrieval bypasses the gateway and goes directly to LlamaStack.
