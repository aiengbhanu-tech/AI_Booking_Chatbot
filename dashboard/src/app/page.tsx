"use client";

import { useState } from "react";

type Summary = {
  tenant_id: number;
  total_leads: number;
  callback_requests: number;
  total_messages: number;
};

type Lead = {
  id: number;
  name: string | null;
  email: string | null;
  phone: string | null;
  intent: string;
  notes: string | null;
  created_at: string;
};

type Tenant = {
  id: number;
  name: string;
  website_url: string | null;
  api_key_last4: string;
  calendly_url: string | null;
  contact_email: string | null;
  widget_public_key: string;
};

export default function Dashboard() {
  const [apiKey, setApiKey] = useState("");
  const [data, setData] = useState<{
    summary: Summary;
    leads: Lead[];
    tenant: Tenant;
  } | null>(null);

  const [loading, setLoading] = useState(false);

  async function loadDashboard() {
    try {
      setLoading(true);

      const summaryRes = await fetch("http://localhost:8000/v1/analytics/summary", {
        headers: { "X-API-Key": apiKey },
      });
      if (!summaryRes.ok) throw new Error(`Summary failed: ${summaryRes.status}`);
      const summary = await summaryRes.json();

      const leadsRes = await fetch("http://localhost:8000/v1/leads", {
        headers: { "X-API-Key": apiKey },
      });
      if (!leadsRes.ok) throw new Error(`Leads failed: ${leadsRes.status}`);
      const leads = await leadsRes.json();

      const tenantRes = await fetch("http://localhost:8000/v1/tenants/me", {
        headers: { "X-API-Key": apiKey },
      });
      if (!tenantRes.ok) throw new Error(`Tenant failed: ${tenantRes.status}`);
      const tenant = await tenantRes.json();

      setData({ summary, leads, tenant });
    } catch (err) {
      console.error("Dashboard load error:", err);
      alert("Could not load dashboard. Check backend is running and API key is correct.");
    } finally {
      setLoading(false);
    }
  }

  function copy(text: string, label = "Copied!") {
    navigator.clipboard.writeText(text);
    alert(label);
  }

  const embedSnippet = data
    ? `<script src="http://localhost:8000/widget/widget.js" data-tenant-key="${data.tenant.widget_public_key}" data-api-base="http://localhost:8000"></script>`
    : "";

  return (
    <main className="page">
      <div className="container">
        <div className="hero">
          <div>
            <div className="eyebrow">AI Receptionist SaaS</div>
            <h1 className="title">Client Dashboard</h1>
            <p className="subtitle">
              Monitor leads, conversations, and widget setup for your clinic.
            </p>
          </div>
        </div>

        <section className="panel top-panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">Load your workspace</h2>
              <p className="panel-subtitle">
                Paste your private API key to access tenant data.
              </p>
            </div>
          </div>

          <div className="key-row">
            <input
              className="key-input"
              placeholder="Paste private API key"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <button className="primary-btn" onClick={loadDashboard} disabled={loading}>
              {loading ? "Loading..." : "Load Dashboard"}
            </button>
          </div>
        </section>

        {data && (
          <>
            <section className="stats-grid">
              <StatCard
                title="Total Leads"
                value={data.summary.total_leads}
                tone="blue"
              />
              <StatCard
                title="Callback Requests"
                value={data.summary.callback_requests}
                tone="purple"
              />
              <StatCard
                title="Total Messages"
                value={data.summary.total_messages}
                tone="green"
              />
            </section>

            <section className="grid two-col">
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h2 className="panel-title">Clinic Information</h2>
                    <p className="panel-subtitle">Core account and widget details</p>
                  </div>
                </div>

                <div className="info-list">
                  <InfoRow label="Clinic Name" value={data.tenant.name} />
                  <InfoRow
                    label="Website"
                    value={data.tenant.website_url || "Not set"}
                  />
                  <InfoRow
                    label="Calendly"
                    value={data.tenant.calendly_url || "Not configured"}
                  />
                  <InfoRow
                    label="Widget Key"
                    value={data.tenant.widget_public_key}
                    action={
                      <button
                        className="ghost-btn"
                        onClick={() =>
                          copy(data.tenant.widget_public_key, "Widget key copied")
                        }
                      >
                        Copy
                      </button>
                    }
                  />
                </div>
              </div>

              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h2 className="panel-title">Embed on Website</h2>
                    <p className="panel-subtitle">
                      Paste this one-line script into the client website.
                    </p>
                  </div>
                </div>

                <div className="code-box">{embedSnippet}</div>

                <div className="button-row">
                  <button
                    className="primary-btn"
                    onClick={() => copy(embedSnippet, "Embed snippet copied")}
                  >
                    Copy Snippet
                  </button>
                  <button
                    className="ghost-btn"
                    onClick={() =>
                      copy(data.tenant.widget_public_key, "Widget key copied")
                    }
                  >
                    Copy Widget Key
                  </button>
                </div>
              </div>
            </section>

            <section className="panel">
              <div className="panel-header">
                <div>
                  <h2 className="panel-title">Recent Leads</h2>
                  <p className="panel-subtitle">
                    Captured appointment and callback requests
                  </p>
                </div>
              </div>

              {data.leads.length === 0 ? (
                <EmptyState
                  title="No leads yet"
                  description="Once visitors interact with the widget and submit their details, leads will appear here."
                />
              ) : (
                <div className="lead-grid">
                  {data.leads.map((lead) => (
                    <div key={lead.id} className="lead-card">
                      <div className="lead-top">
                        <div>
                          <div className="lead-name">{lead.name || "Unknown visitor"}</div>
                          <div className="lead-meta">{lead.intent}</div>
                        </div>
                        <span className={`badge badge-${lead.intent}`}>
                          {lead.intent}
                        </span>
                      </div>

                      <div className="lead-details">
                        <div>
                          <span className="muted">Phone:</span> {lead.phone || "-"}
                        </div>
                        <div>
                          <span className="muted">Email:</span> {lead.email || "-"}
                        </div>
                        <div>
                          <span className="muted">Notes:</span> {lead.notes || "-"}
                        </div>
                        <div>
                          <span className="muted">Created:</span>{" "}
                          {new Date(lead.created_at).toLocaleString()}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </main>
  );
}

function StatCard({
  title,
  value,
  tone,
}: {
  title: string;
  value: number;
  tone: "blue" | "purple" | "green";
}) {
  return (
    <div className={`stat-card stat-${tone}`}>
      <div className="stat-label">{title}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}

function InfoRow({
  label,
  value,
  action,
}: {
  label: string;
  value: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="info-row">
      <div>
        <div className="info-label">{label}</div>
        <div className="info-value">{value}</div>
      </div>
      {action}
    </div>
  );
}

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="empty-state">
      <div className="empty-title">{title}</div>
      <div className="empty-description">{description}</div>
    </div>
  );
}