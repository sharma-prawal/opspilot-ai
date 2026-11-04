# Component Diagram

```mermaid
flowchart TB
  subgraph web["apps/web (Next.js)"]
    pages[Pages: overview, incidents, investigation,<br/>approvals, knowledge]
    bff["/api/ops/* route handler<br/>(server-side proxy, injects operator token)"]
    pages --> bff
  end

  subgraph api["apps/api (opspilot_api)"]
    routes[Routes: health, knowledge, incidents,<br/>investigations, approvals, system]
    services[Application services:<br/>IncidentService, InvestigationService,<br/>ApprovalService, KnowledgeService]
    runner[InvestigationRunner<br/>bounded background tasks]
    repos[Repositories (SQLAlchemy async)]
    routes --> services --> repos
    services --> runner
  end

  subgraph agents["packages/agents (opspilot_agents)"]
    graph[LangGraph StateGraph]
    nodes[Nodes: intake, plan, dispatch, telemetry,<br/>changes, dependencies, knowledge, rca,<br/>followup, propose, await_approval,<br/>execute, verify, report]
    analysis[Deterministic analysis:<br/>anomaly onset, log signatures,<br/>change correlation]
    ports[Ports: ChatModel, ToolGateway]
    graph --> nodes --> analysis
    nodes --> ports
  end

  subgraph mcp["packages/mcp (opspilot_mcp)"]
    client[McpToolGateway<br/>(implements ToolGateway)]
    readsrv[MCP read server]
    actsrv[MCP action server]
  end

  subgraph rag["packages/rag (opspilot_rag)"]
    ingest[Ingestion pipeline]
    retr[HybridRetriever: vector + keyword + RRF]
  end

  subgraph sim["services/simulator (opspilot_simulator)"]
    scen[Scenario generators (seeded)]
    store[Sim store / sandbox actions]
  end

  subgraph shared["packages/shared (opspilot_shared)"]
    cfg[Settings] --- log[Logging/Tracing]
    dom[Domain contracts] --- orm[ORM + sessions]
    llm[OllamaChatModel / OllamaEmbedder]
  end

  bff --> routes
  runner --> graph
  runner -. checkpoints .-> pg[(PostgreSQL)]
  ports -. implemented by .-> client
  ports -. implemented by .-> llm
  client -- stdio MCP --> readsrv
  client -- stdio MCP --> actsrv
  readsrv --> store
  readsrv --> retr
  actsrv --> store
  retr --> pg
  ingest --> pg
  store --> pg
  llm --> ollama[(Ollama)]
  retr --> llm
```

## Dependency rules (enforced by import-linter)

- `opspilot_agents` must not import `opspilot_api`, `opspilot_mcp`, `opspilot_rag`, `opspilot_simulator`.
- `opspilot_shared` must not import any other `opspilot_*` package.
- `opspilot_rag` and `opspilot_simulator` must not import `opspilot_agents` or `opspilot_api`.
- Nothing imports `opspilot_eval`.
