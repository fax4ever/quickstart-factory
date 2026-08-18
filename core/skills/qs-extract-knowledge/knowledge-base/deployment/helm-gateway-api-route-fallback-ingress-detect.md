---
name: helm-gateway-api-route-fallback-ingress-detect
description: Gateway API with conditional Route fallback when ingress is not LoadBalancer, detected at deploy time
summary: "Solves Gateway API deployment on OpenShift clusters where ingress is not LoadBalancer (NodePort, HostNetwork) by detecting the router-default service type at deploy time and conditionally falling back to an OpenShift Route with edge TLS termination. Use when deploying Gateway API Gateways that must work across clusters with varying ingress configurations -- set gateways.maasDefaultGateway.useRoute to true (Route-fronted HTTP on port 80 with ClusterIP service override via infrastructure.parametersRef ConfigMap) or false/default (direct HTTPS on port 443 with TLS from global.wildcardCertName); the openshift-default GatewayClass must pre-exist from the DataScienceCluster Job. Critical config: the all-in-one.sh script detects ingress by checking oc get svc -n openshift-ingress router-default type, the ConfigMap in openshift-ingress configures both Istio proxy resources and service type override, hostname defaults to maas.<wildcardDomain>, and the Gateway requires annotations opendatahub.io/managed: \"false\" and security.opendatahub.io/authorino-tls-bootstrap: \"true\". Gotchas: Route mode terminates TLS at the Route (edge) not the Gateway so the listener must be HTTP port 80, the Route targets the auto-generated service name maas-default-gateway-openshift-default (pattern: gateway-name + gatewayclass-name), and insecureEdgeTerminationPolicy: Allow permits plain HTTP access in Route mode."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [model-serving]
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "MaaS default Gateway with conditional Route fallback for non-LoadBalancer ingress, infrastructure ConfigMap for Istio proxy resources"
    approach: "A"
---

# Gateway API with Route Fallback for Non-LoadBalancer Ingress

## Overview

This pattern deploys a Kubernetes Gateway API Gateway resource that conditionally falls back to an OpenShift Route when the cluster's ingress controller does not use a LoadBalancer service type. The ingress type is detected at deploy time by the orchestrating shell script, and the Gateway template switches between HTTPS (direct LoadBalancer) and HTTP (behind a Route with edge TLS termination) based on a `useRoute` flag.

## Pattern Description

Not all OpenShift clusters expose ingress via LoadBalancer services -- some use NodePort, HostNetwork, or other configurations. This pattern detects the ingress service type at deploy time and conditionally creates an OpenShift Route in front of the Gateway's ClusterIP service. When `useRoute: true`, the Gateway listens on HTTP port 80 (since the Route handles TLS termination), and the service type is overridden to ClusterIP via an infrastructure ConfigMap. When `useRoute: false`, the Gateway uses HTTPS port 443 with a TLS certificate reference.

## Implementation

### Deploy-Time Ingress Detection

The `all-in-one.sh` script detects the ingress type before Helm install:

```bash
# all-in-one.sh
function gateway_use_route {
  ret=1
  if ! oc get svc -n openshift-ingress router-default >/dev/null 2>&1; then
    ret=0
  fi
  if [ "$(oc get svc -n openshift-ingress router-default \
    -ojsonpath='{.spec.type}')" != "LoadBalancer" ]; then
    ret=0
  fi
  if [ "$ret" -ne 1 ]; then
    echo "WARNING: Detected a non-load-balancer ingress configuration. \
Using a Route to back Gateway API resources." >&2
  fi
  return $ret
}
if gateway_use_route; then
  GATEWAY_USE_ROUTE=true
else
  GATEWAY_USE_ROUTE=false
fi
```

### Conditional Gateway Template

```yaml
# charts/dependency-operators/files/openshift-ai/gateway.yaml
{{- with .Values.gateways.maasDefaultGateway }}
{{- if .create }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: maas-default-gateway-config
  namespace: openshift-ingress
data:
  deployment: |
    spec:
      template:
        spec:
          containers:
          - name: istio-proxy
            resources:
              {{- toYaml .resources | nindent 16 }}
{{- if .useRoute }}
  service: |
    spec:
      type: ClusterIP
{{- end }}
---
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: maas-default-gateway
  namespace: openshift-ingress
  annotations:
    opendatahub.io/managed: "false"
    security.opendatahub.io/authorino-tls-bootstrap: "true"
spec:
  gatewayClassName: openshift-default
  infrastructure:
    parametersRef:
      group: ""
      kind: ConfigMap
      name: maas-default-gateway-config
  listeners:
    {{- if .useRoute }}
    - name: http
      port: 80
      protocol: HTTP
      hostname: {{ .hostname | default (printf "maas.%s" $.Values.global.wildcardDomain) }}
    {{- else }}
    - name: https
      port: 443
      protocol: HTTPS
      hostname: {{ .hostname | default (printf "maas.%s" $.Values.global.wildcardDomain) }}
      tls:
        certificateRefs:
        - kind: Secret
          name: {{ $.Values.global.wildcardCertName }}
        mode: Terminate
    {{- end }}
      allowedRoutes:
        namespaces:
          from: All
{{- end }}
{{- end }}
```

### Route Resource for Fallback

When `useRoute: true`, an OpenShift Route is created to front the Gateway:

```yaml
# gateway.yaml (continued, within useRoute conditional)
{{- if .useRoute }}
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: maas-default-gateway
  namespace: openshift-ingress
spec:
  host: {{ .hostname | default (printf "maas.%s" $.Values.global.wildcardDomain) }}
  port:
    targetPort: 80
  tls:
    insecureEdgeTerminationPolicy: Allow
    termination: edge
  to:
    kind: Service
    name: maas-default-gateway-openshift-default
    weight: 100
{{- end }}
```

### Infrastructure ConfigMap for Istio Proxy

The Gateway uses an `infrastructure.parametersRef` pointing to a ConfigMap that configures the Istio proxy sidecar resources and optionally overrides the service type:

```yaml
# values.yaml
gateways:
  maasDefaultGateway:
    create: true
    useRoute: false
    hostname: ""
    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        cpu: "2"
        memory: 2Gi
```

## Configuration

- **Key settings:** `gateways.maasDefaultGateway.useRoute` (boolean) toggles between direct HTTPS and Route-fronted HTTP; `hostname` defaults to `maas.<wildcardDomain>`; `resources` configures the Istio proxy container
- **Defaults:** `useRoute: false` (direct LoadBalancer HTTPS); hostname derived from cluster wildcard domain; TLS certificate from `global.wildcardCertName`
- **Dependencies:** `openshift-default` GatewayClass must exist (created by the create-datasciencecluster Job); the wildcard TLS certificate Secret must exist in the `openshift-ingress` namespace

## Gotchas

- The `opendatahub.io/managed: "false"` annotation prevents RHOAI from managing this Gateway, since the quickstart handles its own Gateway lifecycle
- The Route targets the service name `maas-default-gateway-openshift-default`, which is auto-generated by the GatewayClass controller from the Gateway name and class name
- When using Route fallback, TLS termination happens at the Route (edge mode) not at the Gateway, so the Gateway listens on plain HTTP port 80
- The Route's `insecureEdgeTerminationPolicy: Allow` permits HTTP access alongside HTTPS when in Route mode

## Related Patterns

- `shell-script-two-phase-helm-cluster-autodetect.md` -- the script that detects ingress type and sets `GATEWAY_USE_ROUTE`
- `helm-hook-configmap-mounted-script-jobs.md` -- the Job that creates the GatewayClass prerequisite
