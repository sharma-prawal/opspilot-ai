"use client";

import { useState } from "react";

interface TelemetryChannel {
  id: string;
  channel: string;
  name: string;
  sensor: string;
  unit: string;
  baseline: string;
  anomalyWindow: string;
  status: "nominal" | "warning" | "critical" | "offline";
  delta: string;
  correlatedCause: string;
  uncertaintyNotes?: string;
}

const CHANNELS: TelemetryChannel[] = [
  {
    id: "CH-01",
    channel: "CH-01 // DB_POOL_MAX",
    name: "Database Connection Pool Ceiling",
    sensor: "prom:pg_stat_database_numbackends",
    unit: "backends",
    baseline: "12 / 50",
    anomalyWindow: "47 / 50 (94% saturation)",
    status: "critical",
    delta: "+291% in 120s",
    correlatedCause: "Unindexed sequential table scan in dep-ls-0291",
  },
  {
    id: "CH-02",
    channel: "CH-02 // HTTP_5XX_RATE",
    name: "API Gateway 500 Spike",
    sensor: "mcp:search_logs",
    unit: "req/s",
    baseline: "0.02 req/s",
    anomalyWindow: "48.4 req/s",
    status: "critical",
    delta: "+2420x above threshold",
    correlatedCause: "FATAL: remaining connection slots reserved for superuser",
  },
  {
    id: "CH-03",
    channel: "CH-03 // RECENT_DEPLOY",
    name: "Production Release History",
    sensor: "mcp:get_recent_deployments",
    unit: "commit_hash",
    baseline: "dep-ls-0290 (stable)",
    anomalyWindow: "dep-ls-0291 (promoted 09:39:00 UTC)",
    status: "warning",
    delta: "T-02:15 prior to onset",
    correlatedCause: "SQL balance calculation query filter modified without covering index",
  },
  {
    id: "CH-04",
    channel: "CH-04 // GATE_FENCE_D25",
    name: "Deterministic Capacity Fence D25",
    sensor: "kernel:safety_gates",
    unit: "RAM limit",
    baseline: "Max 50 backends",
    anomalyWindow: "Blocked scale_connection_pool(120)",
    status: "critical",
    delta: "0 unauthorized mutations",
    correlatedCause: "Safety kernel intercepted dangerous parameter resize; forced rollback replan",
  },
  {
    id: "CH-05",
    channel: "CH-05 // LOG_AGGREGATOR",
    name: "Distributed Log Ingress Stream",
    sensor: "loki:stream_heartbeat",
    unit: "heartbeat/s",
    baseline: "100.0% nominal",
    anomalyWindow: "100.0% steady",
    status: "nominal",
    delta: "0 dropped frames",
    correlatedCause: "Log pipeline healthy; all errors delivered with full stack traces",
  },
  {
    id: "CH-06",
    channel: "CH-06 // EXTERNAL_INGRESS",
    name: "External Traffic Volume",
    sensor: "prom:ingress_requests_total",
    unit: "req/s",
    baseline: "840 req/s",
    anomalyWindow: "852 req/s (+1.4%)",
    status: "nominal",
    delta: "Flat baseline",
    uncertaintyNotes: "External traffic spike hypothesis REFUTED: volume is unchanged; internal query inefficiency proven.",
    correlatedCause: "External DDoS ruled out by flat request rate",
  },
];

export default function ConceptBExplorerPage() {
  const [selectedChannel, setSelectedChannel] = useState<TelemetryChannel>(CHANNELS[0]);

  return (
    <div className="space-y-4 font-mono">
      {/* Console Masthead */}
      <div className="avionics-frame p-4">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#232A35] pb-2">
          <div>
            <div className="text-[10px] text-[#F59E0B] font-bold">
              FLIGHT DATA RECORDER // SENSOR MATRIX
            </div>
            <h2 className="text-base font-bold text-white">
              Multi-Sensor Telemetry Ribbon &amp; Anomaly Matrix
            </h2>
          </div>
          <div className="text-[10px] text-[#8B97A8]">
            SYNC FREQUENCY: <span className="text-[#06B6D4]">100ms REAL-TIME BUS</span>
          </div>
        </div>
        <p className="mt-1 text-xs text-[#8B97A8]">
          Cross-sensor synchronized telemetry channels. Correlates metric spikes with deployment diffs, intercept fences, and telemetry uncertainty bounds.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-12">
        {/* Sensor Channels Grid (7 cols) */}
        <div className="lg:col-span-7 space-y-2.5">
          {CHANNELS.map((ch) => {
            const isSel = selectedChannel.id === ch.id;
            return (
              <div
                key={ch.id}
                onClick={() => setSelectedChannel(ch)}
                className={`cursor-pointer rounded border p-3 text-xs transition-all ${
                  isSel
                    ? "border-[#F59E0B] bg-[#181D24] shadow-[0_0_10px_rgba(245,158,11,0.15)]"
                    : "border-[#232A35] bg-[#111419] hover:border-[#3B4657]"
                }`}
              >
                <div className="flex items-center justify-between text-[10px]">
                  <span className="font-bold text-[#F59E0B]">{ch.channel}</span>
                  <span
                    className={`font-bold uppercase ${
                      ch.status === "critical"
                        ? "text-[#EF4444]"
                        : ch.status === "warning"
                        ? "text-[#F59E0B]"
                        : "text-[#10B981]"
                    }`}
                  >
                    [{ch.status}]
                  </span>
                </div>

                <div className="mt-1 flex items-center justify-between">
                  <h4 className="font-bold text-white">{ch.name}</h4>
                  <span className="text-[#06B6D4] font-bold">{ch.delta}</span>
                </div>

                <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] text-[#8B97A8]">
                  <div>SENSOR: <code>{ch.sensor}</code></div>
                  <div>ANOMALY: <span className="text-[#F0F3F6] font-semibold">{ch.anomalyWindow}</span></div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Selected Sensor Channel Deep-Readout (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <div className="avionics-frame p-4">
            <div className="avionics-header mb-3">
              <span>TELEMETRY CHANNEL READOUT // {selectedChannel.id}</span>
              <span className="text-[#F59E0B] font-bold">STATE: ACTIVE</span>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <span className="text-[10px] text-[#525D6D]">CHANNEL NAME</span>
                <div className="text-white font-bold">{selectedChannel.name}</div>
              </div>

              <div>
                <span className="text-[10px] text-[#525D6D]">TELEMETRY SENSOR PORT</span>
                <div className="text-[#06B6D4] font-mono text-[11px]">{selectedChannel.sensor}</div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-2">
                  <span className="text-[10px] text-[#525D6D]">HISTORICAL BASELINE</span>
                  <div className="text-white font-bold">{selectedChannel.baseline}</div>
                </div>
                <div className="rounded border border-[#232A35] bg-[#0A0C0E] p-2">
                  <span className="text-[10px] text-[#525D6D]">ANOMALY EXCURSION</span>
                  <div className="text-[#EF4444] font-bold">{selectedChannel.anomalyWindow}</div>
                </div>
              </div>

              <div>
                <span className="text-[10px] text-[#525D6D]">CORRELATED CAUSAL ATTRIBUTION</span>
                <p className="mt-1 text-[11px] text-[#8B97A8] leading-relaxed">
                  {selectedChannel.correlatedCause}
                </p>
              </div>

              {selectedChannel.uncertaintyNotes && (
                <div className="rounded border border-[#232A35] bg-[#181D24] p-2.5">
                  <span className="text-[10px] text-[#F59E0B] font-bold">UNCERTAINTY RESOLUTION</span>
                  <p className="mt-0.5 text-[10px] text-[#8B97A8]">
                    {selectedChannel.uncertaintyNotes}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
