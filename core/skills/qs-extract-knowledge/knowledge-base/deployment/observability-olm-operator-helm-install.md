---
name: observability-olm-operator-helm-install
description: Individual Helm charts wrapping OLM Subscription and OperatorGroup for OpenShift operator installation
summary: "Solves declarative, reproducible installation of OpenShift observability operators (OTel, Grafana, Tempo, Cluster Observability, Logging, Loki) by wrapping OLM Namespace, OperatorGroup, and Subscription resources in either individual Helm charts (Approach A) or a centralized operator-manager.sh bash script with Makefile targets (Approach B). Approach A (4 operators, static values.yaml channels, three-template-per-chart structure, `helm upgrade --install` idempotency) suits Helm-native workflows; Approach B (5 operators adding Logging/Loki dropping Grafana, auto-detected channels via `oc get packagemanifest -l catalog=redhat-operators`, `verify-operators-ready` target checking CSV phase) is preferred when a Helm Operator would conflict with inline OLM charts or when Logging/Loki operators are required. Critical config: `subscription.channel` (stable for most, v5 for Grafana), `subscription.source` (redhat-operators vs community-operators for Grafana), `installPlanApproval: Automatic`, namespace label `openshift.io/cluster-monitoring: 'true'` for metrics scraping, and empty `targetNamespaces: []` for AllNamespaces install mode required by Tempo. Gotchas: Grafana uses `community-operators` catalog affecting support posture; Loki channel must filter with `-l catalog=redhat-operators` to avoid community alpha; operator charts install only the operator not CR instances like TempoStack; `_require_operator_channel` guard runs at recipe time only so non-cluster targets work without connectivity; `openshift-operators-redhat` is a shared namespace requiring careful operatorgroup management."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, opentelemetry, grafana]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "4 operators (OTel, Grafana, Tempo, Cluster Observability) installed via separate Helm charts with OLM Subscriptions"
    approach: "A"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "Same 4 OLM operators (OTel, Grafana, Tempo, Cluster Observability) with identical Namespace+OperatorGroup+Subscription structure, installed in parallel via bash script"
    approach: "A"
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "5 operators (Cluster Observability, OTel, Tempo, Logging, Loki) managed via centralized operator-manager.sh script with auto-detected channels/CSVs from cluster catalog"
    approach: "B"
---

# Observability OLM Operator Installation via Helm Charts

## Overview

This pattern installs OpenShift operators through Helm charts that template OLM (Operator Lifecycle Manager) resources: Namespace, OperatorGroup, and Subscription. Each operator gets its own dedicated Helm chart, enabling independent lifecycle management while keeping operator installation declarative and reproducible.

## Pattern Description

Rather than manually creating OLM Subscriptions via the OpenShift console or `oc apply`, each operator is wrapped in a small Helm chart that templates the Namespace, OperatorGroup, and Subscription resources. This approach enables operators to be installed as part of a `helm install` workflow with configurable channels, sources, and approval modes. Four operators follow this pattern: OpenTelemetry, Grafana, Tempo, and Cluster Observability.

## Implementation

### Common Chart Structure

Each operator chart follows the same three-template structure. Example for the OpenTelemetry Operator:

```yaml
# charts/observability/helm/otel-operator/templates/namespace.yaml (pattern)
apiVersion: v1
kind: Namespace
metadata:
  name: {{ .Values.namespace.name }}
  annotations:
    {{- toYaml .Values.namespace.annotations | nindent 4 }}
  labels:
    {{- toYaml .Values.namespace.labels | nindent 4 }}
```

```yaml
# charts/observability/helm/otel-operator/templates/operatorgroup.yaml (pattern)
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: {{ .Values.operatorGroup.name }}
  namespace: {{ .Values.namespace.name }}
spec:
  targetNamespaces: {{ .Values.operatorGroup.targetNamespaces | toYaml | nindent 4 }}
```

```yaml
# charts/observability/helm/otel-operator/templates/subscription.yaml (pattern)
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: {{ .Values.subscription.name }}
  namespace: {{ .Values.namespace.name }}
spec:
  channel: {{ .Values.subscription.channel }}
  installPlanApproval: {{ .Values.subscription.installPlanApproval }}
  name: {{ .Values.subscription.packageName }}
  source: {{ .Values.subscription.source }}
  sourceNamespace: {{ .Values.subscription.sourceNamespace }}
```

### Values per Operator

Each operator has its own namespace, channel, and catalog source:

```yaml
# charts/observability/helm/otel-operator/values.yaml
namespace:
  name: openshift-opentelemetry-operator
  labels:
    openshift.io/cluster-monitoring: 'true'
subscription:
  name: opentelemetry-product
  packageName: opentelemetry-product
  channel: stable
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

```yaml
# charts/observability/helm/grafana-operator/values.yaml
namespace:
  name: openshift-grafana-operator
subscription:
  name: grafana
  packageName: grafana-operator
  channel: v5
  source: community-operators     # Note: community, not redhat-operators
```

### All Four Operator Charts

| Chart | Namespace | Source | Channel |
|-------|-----------|--------|---------|
| `otel-operator` | `openshift-opentelemetry-operator` | `redhat-operators` | `stable` |
| `grafana-operator` | `openshift-grafana-operator` | `community-operators` | `v5` |
| `tempo-operator` | `openshift-tempo-operator` | `redhat-operators` | `stable` |
| `cluster-observability-operator` | `openshift-cluster-observability-operator` | `redhat-operators` | `stable` |

## Configuration

- **Key settings:** `subscription.channel` determines the operator version stream; `subscription.source` selects the catalog (redhat-operators vs community-operators); `installPlanApproval: Automatic` enables auto-upgrades
- **Defaults:** All operators default to `Automatic` install plan approval and empty `targetNamespaces` (cluster-wide scope)
- **Dependencies:** OLM must be available (standard on OpenShift); catalog sources (`redhat-operators`, `community-operators`) must be present in `openshift-marketplace`

## Gotchas

- Grafana Operator comes from `community-operators` while all other operators come from `redhat-operators`; this affects support posture and update cadence
- The `openshift.io/cluster-monitoring: 'true'` label on operator namespaces enables cluster monitoring to scrape metrics from the operator pods
- The Tempo Operator chart's values.yaml comments note that TempoStack instances should be created separately using the `tempo` chart -- the operator chart only installs the operator itself
- Empty `targetNamespaces: []` in OperatorGroup means cluster-wide scope (AllNamespaces install mode); the Tempo operator specifically requires this since it does not support OwnNamespace mode

## Related Patterns

- `otel-sidecar-inject-vllm-model-metrics.md` -- the OTel Collector sidecars that depend on the OTel Operator installed by this pattern
- `helm-uwm-podmonitor-vllm.md` -- the UWM configuration that works alongside these observability operators

---

## Approach B: Centralized Bash Script with Auto-Detected OLM Channels (from openshift-ai-observability-summarizer)

### When to Use

Use when operators need to be managed via `make` targets with auto-detected channels and CSVs from the cluster catalog, rather than pre-configured Helm chart values. Preferred when the project also uses a Helm Operator (where inline Helm charts for OLM resources would conflict with the operator's reconciliation) or when the operator set includes Logging and Loki operators alongside the standard observability operators.

### Differences from Approach A

- **No Helm charts for operators** -- uses a centralized `operator-manager.sh` bash script with YAML templates in `scripts/operators/` instead of Helm charts
- **Auto-detected channels and CSVs** -- queries `oc get packagemanifest` at Makefile parse time to discover the correct channel and startingCSV for each operator
- **5 operators instead of 4** -- adds Logging and Loki operators alongside Cluster Observability, OTel, and Tempo (no Grafana)
- **Guard macro for operator channels** -- `_require_operator_channel` fails with actionable error when channel/CSV detection fails, but only at recipe time (non-cluster targets like test/build are unaffected)

### Implementation

#### Makefile Operator Targets

Each operator has install, uninstall, and check targets that delegate to the script:

```makefile
# Makefile
OPERATOR_MANAGER_SCRIPT := scripts/operator-manager.sh

.PHONY: install-cluster-observability-operator
install-cluster-observability-operator:
	@$(OPERATOR_MANAGER_SCRIPT) -i observability -n openshift-cluster-observability-operator

.PHONY: install-logging-operator
install-logging-operator:
	$(call _require_operator_channel)
	@CHANNEL=$(LOGGING_CHANNEL) STARTING_CSV=$(LOGGING_STARTING_CSV) \
	  $(OPERATOR_MANAGER_SCRIPT) -i logging -n openshift-logging

.PHONY: install-operators
install-operators: install-cluster-observability-operator \
  install-opentelemetry-operator install-tempo-operator \
  install-logging-operator install-loki-operator
	@sleep 15  # Wait for operators to stabilize and CRDs to be ready
```

#### Auto-Detected Operator Channels

```makefile
# Makefile
# Must query with -l catalog=redhat-operators because loki-operator
# also exists in community-operators (with only an 'alpha' channel).
LOGGING_CHANNEL := $(shell oc get packagemanifest -l catalog=redhat-operators \
    -o jsonpath='{range .items[?(@.metadata.name=="cluster-logging")]}{.status.defaultChannel}{end}' \
    2>/dev/null)
LOGGING_STARTING_CSV := $(shell oc get packagemanifest -l catalog=redhat-operators \
    -o jsonpath='{range .items[?(@.metadata.name=="cluster-logging")].status.channels[?(@.name=="$(LOGGING_CHANNEL)")]}{.currentCSV}{end}' \
    2>/dev/null)
```

#### Verify Operators Ready Target

Checks all 5 operators' subscription status and CSV phase:

```makefile
# Makefile
verify-operators-ready:
	@ERRORS=0; \
	for sub in cluster-observability-operator opentelemetry-product tempo-product \
	           cluster-logging loki-operator; do \
		CSV=$$(oc get subscription $$sub -n $$NS -o jsonpath='{.status.installedCSV}'); \
		PHASE=$$(oc get csv $$CSV -n $$NS -o jsonpath='{.status.phase}'); \
		if [ "$$PHASE" != "Succeeded" ]; then ERRORS=$$((ERRORS + 1)); fi; \
	done; \
	if [ $$ERRORS -gt 0 ]; then exit 1; fi
```

### All Five Operators

| Operator | Namespace | Script Alias | Channel Source |
|----------|-----------|-------------|----------------|
| Cluster Observability | `openshift-cluster-observability-operator` | `observability` | Hardcoded in script |
| OpenTelemetry | `openshift-opentelemetry-operator` | `otel` | Hardcoded in script |
| Tempo | `openshift-tempo-operator` | `tempo` | Hardcoded in script |
| Logging | `openshift-logging` | `logging` | Auto-detected from packagemanifest |
| Loki | `openshift-operators-redhat` | `loki` | Auto-detected from packagemanifest |

### Gotchas

- The Loki operator channel must be queried with `-l catalog=redhat-operators` because `loki-operator` also exists in `community-operators` with only an `alpha` channel that would be incorrect
- The `_require_operator_channel` guard macro is called at recipe time only (not Makefile parse time) so that non-cluster targets like `test`, `build`, and `help` work without cluster connectivity
- The `openshift-operators-redhat` namespace is a shared namespace where multiple unrelated Subscriptions coexist -- the operator-manager.sh script avoids running `operatorgroup --all` in this namespace to prevent breaking other operators
- After `install-operators`, a `sleep 15` wait allows operators to stabilize and register their CRDs before downstream targets attempt to create CR instances

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Operator management tool | Helm charts | Bash script + Makefile targets |
| Channel configuration | Static in values.yaml | Auto-detected from cluster catalog |
| Number of operators | 4 (OTel, Grafana, Tempo, Cluster Observability) | 5 (OTel, Tempo, Cluster Observability, Logging, Loki) |
| Grafana operator | Included (community-operators) | Not included |
| Logging/Loki operators | Not included | Included with auto-detected channels |
| Idempotency mechanism | `helm upgrade --install` | Script checks existing subscriptions |
| Integration with Helm Operator | May conflict with operator reconciliation | No conflict (script runs independently) |
