import { useEffect, useMemo, useState } from "react";
import { fetchApiIndex } from "../api/apiIndex";
import { DataTable, Panel, SectionHeader } from "../components/mina";

export default function ApiHub() {
  const [registry, setRegistry] = useState<any>(null);
  const [message, setMessage] = useState("");

  const load = async () => {
    try {
      const data = await fetchApiIndex();
      setRegistry(data || {});
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Failed to load API registry.");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const rows = useMemo(() => {
    const endpoints = Array.isArray(registry?.endpoints) ? registry.endpoints : [];
    return endpoints.map((e: any, idx: number) => ({
      id: idx + 1,
      method: String(e.method || "GET").toUpperCase(),
      route: e.route || "—",
      description: e.description || "—",
      sample_curl: e.sample_curl || "—",
    }));
  }, [registry]);

  const webhook = registry?.webhook_integration || {};

  return (
    <div>
      <SectionHeader
        title="API Explorer"
        subtitle="Gateway endpoint registry and integration guide from /api/api-docs/registry"
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel
        title="Registry"
        subtitle={registry?.generated_at ? `Generated at ${registry.generated_at}` : "Static + generated docs"}
        right={
          <button className="action-btn" onClick={() => void load()}>
            Refresh
          </button>
        }
      >
        <DataTable
          rows={rows}
          emptyText="No endpoints listed in registry."
          pageSize={20}
          columns={[
            { key: "method", title: "Method", render: (row: any) => row.method },
            { key: "route", title: "Route", render: (row: any) => row.route },
            { key: "description", title: "Description", render: (row: any) => row.description },
            { key: "sample_curl", title: "Sample curl", render: (row: any) => <code>{row.sample_curl}</code> },
          ]}
        />
      </Panel>

      <Panel title="Webhook Integration" subtitle="Inbound endpoint contract through gateway.">
        <DataTable
          rows={[
            {
              inbound_endpoint: webhook?.inbound_endpoint || "/api/webhooks",
              auth_header: webhook?.auth?.header || "X-Webhook-Token",
              auth_description: webhook?.auth?.description || "Send token header with each webhook request.",
              sample_curl: webhook?.sample_curl || "curl -s -X POST http://localhost:8200/api/webhooks -H 'X-Webhook-Token: <token>'",
            },
          ]}
          columns={[
            { key: "inbound_endpoint", title: "Inbound Endpoint", render: (row: any) => row.inbound_endpoint },
            { key: "auth_header", title: "Auth Header", render: (row: any) => row.auth_header },
            { key: "auth_description", title: "Auth", render: (row: any) => row.auth_description },
            { key: "sample_curl", title: "Sample curl", render: (row: any) => <code>{row.sample_curl}</code> },
          ]}
        />
      </Panel>
    </div>
  );
}
