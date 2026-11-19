import { SignalIcon } from "./brand";
import { Badge, Card } from "./ui";

/** Product capability catalog, not connection health. Planned rows have no implemented signals. */
export function IntegrationMatrix() {
  const rows = [
    {
      name: "Simulator",
      icon: "simulator",
      signals: "Logs · metrics · changes · dependencies",
      state: "Implemented",
      access: "Sandbox actions with approval",
      auth: "Operator session",
    },
    {
      name: "File uploads",
      icon: "upload",
      signals: "Logs · metrics · traces · events",
      state: "Implemented",
      access: "Read-only",
      auth: "Operator session",
    },
    {
      name: "Grafana Loki",
      icon: "logs",
      signals: "Logs",
      state: "Implemented",
      access: "Read-only GET",
      auth: "Bearer / basic / none",
    },
    {
      name: "Prometheus",
      icon: "metrics",
      signals: "Metrics",
      state: "Implemented",
      access: "Read-only GET",
      auth: "Bearer / basic / none",
    },
    {
      name: "Datadog",
      icon: "connector",
      signals: "Logs · metrics · APM spans",
      state: "Implemented",
      access: "Read-only (allowlisted query POSTs)",
      auth: "API key + application key",
    },
    {
      name: "Azure Monitor",
      icon: "connector",
      signals: "No adapter yet",
      state: "Planned",
      access: "Unavailable",
      auth: "Not implemented",
    },
    {
      name: "AWS CloudWatch",
      icon: "connector",
      signals: "No adapter yet",
      state: "Planned",
      access: "Unavailable",
      auth: "Not implemented",
    },
  ] as const;
  return (
    <Card title="Connector capabilities">
      <div
        className="overflow-x-auto"
        tabIndex={0}
        aria-label="Scrollable integration capability comparison"
      >
        <table className="capability-table">
          <caption className="sr-only">
            Implemented capabilities and planned providers. Connection health is
            tested separately below.
          </caption>
          <thead>
            <tr>
              <th scope="col">Source</th>
              <th scope="col">Signals</th>
              <th scope="col">Availability</th>
              <th scope="col">Access</th>
              <th scope="col">Authentication</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name}>
                <td>
                  <span className="provider-name">
                    <span className="provider-icon">
                      <SignalIcon name={r.icon} />
                    </span>
                    {r.name}
                  </span>
                </td>
                <td>{r.signals}</td>
                <td>
                  <Badge
                    tone={r.state === "Implemented" ? "success" : "neutral"}
                  >
                    {r.state}
                  </Badge>
                </td>
                <td>{r.access}</td>
                <td>{r.auth}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-muted">
        Catalog availability is separate from connection health. Provider icons
        indicate capability, not official trademarks. Planned adapters cannot
        collect evidence.
      </p>
    </Card>
  );
}
