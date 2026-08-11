---
name: oracle-db
description: "Optional Oracle database subchart with TPC-DS sample data, paired with oracle-sqlcl MCP server for BI agent access"
summary: "Deploys an optional Oracle database pre-populated with TPC-DS decision-support data as a conditional Helm subchart (v0.5.5 from ai-architecture-charts, gated by `oracle-db.enabled` in Chart.yaml), activated when `ORACLE=true` triggers paired enablement of database and oracle-sqlcl MCP server via install_with_env.sh (`--set oracle-db.enabled=true --set mcp-servers.mcp-servers.oracle-sqlcl.enabled=true`). Use when AI agents need SQL access to structured BI data — the oracle-sqlcl MCP server (deployed uniformly alongside travel-research/hotel/flight servers via the mcp-servers subchart) is the sole access path since the backend has no direct Oracle connection code. Post-install, the `oracle-db-tpcds-populate` Kubernetes Job loads TPC-DS data with a 3600s timeout controlled by `oc wait` in the Makefile, which also exposes `ORACLE ?= false` as the deployment toggle. PVCs prefixed `oracle-data` require explicit deletion on uninstall; if the MCP server is not co-enabled alongside the database, Oracle runs but remains inaccessible to agents, and the hour-long populate job can make deployment appear incomplete while application pods are already running."
metadata:
  type: component
tags:
  tech_stack: [oracle, helm]
  ai_pattern: [agents, mcp-tools]
  platform: [openshift, rhoai]
  data_layer: [oracle]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Optional Oracle DB deployment with TPC-DS data population, enabled alongside oracle-sqlcl MCP server for BI analyst agent workflows"
    approach: "A"
---

# Oracle DB

## Overview

An optional database component that deploys an Oracle database instance pre-populated with TPC-DS benchmark data. In the ai-virtual-agent quickstart, it provides a relational data warehouse that BI analysts can query through an oracle-sqlcl MCP server, enabling AI agents to run SQL queries against structured business data. The component is deployed as a Helm subchart from the ai-architecture-charts repository and is disabled by default.

## Tech Stack & Dependencies

- **Runtime:** Oracle database (deployed via Helm subchart)
- **Container image:** Managed by the `oracle-db` subchart from ai-architecture-charts
- **Key dependencies:** Requires the `oracle-sqlcl` MCP server (from `mcp-servers` subchart) to expose database access to agents
- **Helm subchart:** `oracle-db` v0.5.5 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`, conditionally included

## Key Patterns

### Conditional Subchart Enablement

The oracle-db subchart is declared as a conditional dependency in the parent chart. It is disabled by default and activated only when the `ORACLE=true` flag is passed during installation. Enabling it also triggers the oracle-sqlcl MCP server.

```yaml
# deploy/cluster/helm/Chart.yaml (lines 45-48)
  - name: oracle-db
    version: 0.5.5
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
    condition: oracle-db.enabled
```

```yaml
# deploy/cluster/helm/values.yaml (lines 174-175)
oracle-db:
  enabled: false
```

### Paired Oracle + MCP Server Activation

When Oracle is enabled, the install script sets two Helm values together -- enabling the database and the oracle-sqlcl MCP server in a single Helm upgrade. This ensures the database and its MCP access layer are always deployed together.

```bash
# deploy/cluster/scripts/install_with_env.sh (lines 134-138)
# Oracle args
if [ "$ORACLE" = "true" ]; then
    cmd_args+=("--set" "oracle-db.enabled=true")
    cmd_args+=("--set" "mcp-servers.mcp-servers.oracle-sqlcl.enabled=true")
fi
```

### TPC-DS Data Population Job

After the Helm install completes, the Makefile waits for a Kubernetes Job named `oracle-db-tpcds-populate` to finish. This job populates the Oracle instance with TPC-DS benchmark data (a standard decision-support dataset). The timeout is set to 3600 seconds (1 hour), indicating this is a heavyweight data loading operation.

```makefile
# deploy/cluster/Makefile (lines 115-118)
@if [ "$(ORACLE)" = "true" ]; then \
    echo "Oracle enabled - waiting for TPC-DS data population to complete. This may take some time..."; \
    oc wait --for=condition=complete --timeout=3600s job/oracle-db-tpcds-populate -n $(NAMESPACE); \
fi
```

## Configuration

- **Environment variables:** None directly on the Oracle container from this quickstart -- all configuration is handled by the subchart's own defaults
- **Config files:** None in the quickstart repo; configuration lives in the upstream ai-architecture-charts oracle-db subchart
- **Helm values:**
  - `oracle-db.enabled` -- Boolean toggle to include or exclude the Oracle database (default: `false`)
  - `mcp-servers.mcp-servers.oracle-sqlcl.enabled` -- Must be set to `true` alongside `oracle-db.enabled` to provide agent access
- **Makefile variable:**
  ```makefile
  # deploy/cluster/Makefile (line 32)
  ORACLE ?= false
  ```
  Set `ORACLE=true` when running `make install` to activate Oracle deployment.

## Known Gotchas

- **Long data population time:** The TPC-DS populate job can take up to an hour (`--timeout=3600s`). The deployment will appear incomplete until this job finishes, even though the main application pods may already be running.
- **PVC cleanup required on uninstall:** The oracle-db creates persistent volume claims prefixed with `oracle-data`. The Makefile uninstall target explicitly deletes these PVCs alongside pg and minio PVCs:
  ```makefile
  # deploy/cluster/Makefile (line 136)
  @oc get pvc -n $(NAMESPACE) -o custom-columns=NAME:.metadata.name | grep -E '^(pg|minio|oracle)-data' | xargs -I {} oc delete pvc -n $(NAMESPACE) {} ||:
  ```
- **No backend code integration:** The application backend has no direct Oracle connection code. All Oracle access is mediated through the oracle-sqlcl MCP server, which agents invoke via the MCP tool protocol. If the MCP server is not enabled alongside the database, the Oracle instance will be running but inaccessible to agents.

## Testing Notes

- After deployment with `ORACLE=true`, verify the TPC-DS populate job completes: `oc wait --for=condition=complete job/oracle-db-tpcds-populate -n <namespace>`
- Confirm the oracle-sqlcl MCP server pod is running alongside the Oracle database pod
- Test agent access to Oracle data by creating an agent that uses the oracle-sqlcl MCP tool to run a SQL query against TPC-DS tables

## Related Patterns

- The `mcp-servers` subchart handles deployment of the oracle-sqlcl MCP server uniformly alongside other MCP servers (travel-research, hotel, flight)
- Conditional subchart enablement via `condition:` in Chart.yaml is used for other optional components in the ai-architecture-charts ecosystem
- The paired activation pattern (database + MCP server) ensures agents always have a working access path to the data source
