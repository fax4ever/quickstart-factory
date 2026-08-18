---
name: helm-consoleplugin-crd-proxy-auto-enable-patch-job
description: ConsolePlugin CRD with MCP server proxy and post-install Job to auto-enable plugin in OpenShift Console
summary: "Deploys an OpenShift Console plugin via ConsolePlugin CRD with a service proxy (alias: mcp, authorization: None since the console handles auth) routing browser requests to a backend MCP server, and auto-enables the plugin through a Helm post-install/post-upgrade hook Job (hook-delete-policy: before-hook-creation) that patches consoles.operator.openshift.io/cluster using oc+jq with unique deduplication via --type=merge. Use when building console plugins that need backend service proxying and automatic registration without manual oc patch steps -- single approach using CRD proxy plus patcher Job requiring ClusterRole permissions and ose-cli as the Job image. Key config: mcpServer.serviceName/port for proxy target, mcpServer.enabled gates the proxy block, plugin.jobs.patchConsoles.enabled gates the auto-enable Job, plugin.port defaults to 9443, plugin.basePath sets the service base path, and existingPlugins defaults via // [] to handle a nil plugins array. ConsolePlugin is cluster-scoped so same-name installs from different namespaces conflict (Makefile check-console-plugin-namespace pre-flight warns); uninstall must remove the plugin from the console operator (--type=json op:remove) BEFORE helm uninstall or the console will try loading a non-existent service."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, react, typescript, nginx]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "ConsolePlugin CRD with proxy to MCP server service, post-install hook Job using oc patch to auto-enable plugin, namespace collision check"
    approach: "A"
---

# OpenShift ConsolePlugin CRD with Proxy and Auto-Enable Patch Job

## Overview

This pattern deploys an OpenShift Console plugin using the `ConsolePlugin` CRD with a service proxy to a backend MCP server, and auto-enables the plugin in the OpenShift Console via a post-install Helm hook Job. The Makefile includes a pre-flight check for namespace collisions since ConsolePlugin resources are cluster-scoped.

## Pattern Description

The console plugin Helm chart templates a `ConsolePlugin` CRD that registers the plugin with the OpenShift Console and configures a proxy to route requests from the browser to the MCP server service. A post-install hook Job patches `consoles.operator.openshift.io/cluster` to add the plugin to the active plugin list. The Makefile's `check-console-plugin-namespace` target warns if the same ConsolePlugin already points to a different namespace.

## Implementation

### ConsolePlugin CRD with MCP Proxy

```yaml
# deploy/helm/openshift-console-plugin/templates/consoleplugin.yaml
apiVersion: console.openshift.io/v1
kind: ConsolePlugin
metadata:
  name: {{ template "openshift-console-plugin.name" . }}
spec:
  displayName: {{ .Values.plugin.description }}
  i18n:
    loadType: Preload
  backend:
    type: Service
    service:
      name: {{ template "openshift-console-plugin.name" . }}
      namespace: {{ .Release.Namespace }}
      port: {{ .Values.plugin.port }}
      basePath: {{ .Values.plugin.basePath }}
  {{- if .Values.mcpServer.enabled }}
  proxy:
    - alias: mcp
      authorization: None
      endpoint:
        type: Service
        service:
          name: {{ .Values.mcpServer.serviceName }}
          namespace: {{ default .Release.Namespace .Values.mcpServer.namespace }}
          port: {{ .Values.mcpServer.port }}
  {{- end }}
```

### Post-Install Auto-Enable Job

```yaml
# deploy/helm/openshift-console-plugin/templates/patch-consoles-job.yaml
{{- if .Values.plugin.jobs.patchConsoles.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ template "openshift-console-plugin.patcherName" . }}
  annotations:
    helm.sh/hook: post-install,post-upgrade
    helm.sh/hook-delete-policy: before-hook-creation
spec:
  template:
    spec:
      restartPolicy: OnFailure
      serviceAccountName: {{ template "openshift-console-plugin.patcherServiceAccountName" . }}
      containers:
        - name: {{ template "openshift-console-plugin.patcherName" . }}
          image: {{ .Values.plugin.jobs.patchConsoles.image }}
          command:
            - /bin/bash
            - -c
            - |
                existingPlugins=$(oc get consoles.operator.openshift.io cluster \
                  -o json | jq -c '.spec.plugins // []')
                mergedPlugins=$(jq --argjson existingPlugins "${existingPlugins}" \
                  --argjson consolePlugin '["{{ template "openshift-console-plugin.name" . }}"]' \
                  -c -n '$existingPlugins + $consolePlugin | unique')
                patchedPlugins=$(jq --argjson mergedPlugins $mergedPlugins \
                  -n -c '{ "spec": { "plugins": $mergedPlugins } }')
                oc patch consoles.operator.openshift.io cluster \
                  --patch $patchedPlugins --type=merge
{{- end }}
```

### Makefile Namespace Collision Check

```makefile
# Makefile
.PHONY: check-console-plugin-namespace
check-console-plugin-namespace:
	@PLUGIN_NAME=aiobs-console-plugin; \
	existing_ns=$$(oc get consoleplugin $$PLUGIN_NAME \
	  -o jsonpath='{.spec.backend.service.namespace}' 2>/dev/null); \
	if [ -n "$$existing_ns" ] && [ "$$existing_ns" != "$(NAMESPACE)" ]; then \
		echo "ConsolePlugin $$PLUGIN_NAME already points to namespace $$existing_ns"; \
		echo "Consider uninstalling the old release or set NAMESPACE=$$existing_ns"; \
	fi
```

### Makefile Uninstall with Plugin Disabling

```makefile
# Makefile
.PHONY: uninstall-console-plugin
uninstall-console-plugin:
	# Disable plugin in OpenShift Console first
	-@if oc get console.operator.openshift.io cluster \
	    -o jsonpath='{.spec.plugins}' 2>/dev/null | \
	    grep -q "openshift-ai-observability"; then \
		PLUGIN_INDEX=$$(oc get console.operator.openshift.io cluster -o json | \
		  jq '.spec.plugins | to_entries | .[] | \
		  select(.value=="openshift-ai-observability") | .key'); \
		if [ -n "$$PLUGIN_INDEX" ]; then \
			oc patch console.operator.openshift.io cluster --type=json \
			  -p="[{\"op\": \"remove\", \"path\": \"/spec/plugins/$$PLUGIN_INDEX\"}]"; \
		fi \
	fi
	-@helm -n $(NAMESPACE) uninstall $(CONSOLE_PLUGIN_RELEASE_NAME) --ignore-not-found
```

## Configuration

- **Key settings:** `mcpServer.serviceName` (default: aiobs-mcp-server-svc) for proxy target, `plugin.port` (default: 9443), `plugin.autoEnable` for automatic plugin registration
- **Defaults:** Plugin proxy to MCP server is enabled when `mcpServer.enabled` is true; the patcher Job image defaults to the ose-cli image
- **Dependencies:** Requires `consoles.operator.openshift.io` CRD (standard on OpenShift 4.x); the patcher Job needs ClusterRole permissions to patch the console operator resource

## Gotchas

- ConsolePlugin is a cluster-scoped resource -- installing the same plugin name from two different namespaces will conflict, which is why `check-console-plugin-namespace` exists as a pre-flight check
- The uninstall process must remove the plugin from `consoles.operator.openshift.io/cluster` BEFORE deleting the Helm release, otherwise the console will try to load a plugin from a non-existent service
- The patcher Job uses `jq` for array merging with `unique` to avoid adding duplicate plugin entries on upgrade
- The proxy configuration uses `authorization: None` because the console handles authentication -- the MCP server receives proxied requests from the console's backend, not directly from browsers

## Related Patterns

- `helm-openshift-console-dashboard-configmap.md` -- console dashboards via ConfigMap (different from plugin registration)
