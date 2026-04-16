"use client";

import { useState, useEffect } from "react";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
  "http://localhost:8000";

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
  plan_name: string | null;
  subscription_status: string | null;
  stripe_customer_id: string | null;
};

type TenantCreateResponse = {
  id: number;
  name: string;
  api_key: string;
  widget_key: string;
  website_url: string | null;
};

export default function Dashboard() {
  const [apiKey, setApiKey] = useState("");
  const [data, setData] = useState<{
    summary: Summary;
    leads: Lead[];
    tenant: Tenant;
  } | null>(null);

  const [loading, setLoading] = useState(false);
  const [billingLoading, setBillingLoading] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    name: "",
    website_url: "",
    contact_email: "",
  });

  useEffect(() => {
    const savedKey = localStorage.getItem("api_key");
    if (savedKey) {
      setApiKey(savedKey);
      void loadDashboard(savedKey);
    }
  }, []);

  async function loadDashboard(customKey?: string) {
    try {
      const key = (customKey || apiKey).trim();

      if (!key) {
        alert("Please paste your private API key.");
        return;
      }

      setLoading(true);

      const headers = { "X-API-Key": key };

      const summaryRes = await fetch(`${API_BASE}/v1/analytics/summary`, {
        headers,
      });
      if (!summaryRes.ok) {
        throw new Error(`Summary failed: ${summaryRes.status}`);
      }
      const summary: Summary = await summaryRes.json();

      const leadsRes = await fetch(`${API_BASE}/v1/leads`, {
        headers,
      });
      if (!leadsRes.ok) {
        throw new Error(`Leads failed: ${leadsRes.status}`);
      }
      const leads: Lead[] = await leadsRes.json();

      const tenantRes = await fetch(`${API_BASE}/v1/tenants/me`, {
        headers,
      });
      if (!tenantRes.ok) {
        throw new Error(`Tenant failed: ${tenantRes.status}`);
      }
      const tenant: Tenant = await tenantRes.json();

      localStorage.setItem("api_key", key);
      localStorage.setItem("widget_key", tenant.widget_public_key);

      setApiKey(key);
      setData({ summary, leads, tenant });
    } catch (err) {
      console.error("Dashboard load error:", err);
      alert("Could not load dashboard. Check backend URL, backend status, and API key.");
    } finally {
      setLoading(false);
    }
  }

  async function createWorkspace() {
    try {
      if (!form.name.trim()) {
        alert("Please enter clinic name.");
        return;
      }

      setLoading(true);

      const payload = {
        name: form.name.trim(),
        website_url: form.website_url.trim() || null,
        contact_email: form.contact_email.trim() || null,
      };

      const res = await fetch(`${API_BASE}/v1/tenants`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || "Failed to create workspace");
      }

      const json: TenantCreateResponse = await res.json();

      localStorage.setItem("api_key", json.api_key);
      localStorage.setItem("widget_key", json.widget_key);

      setApiKey(json.api_key);
      setShowCreate(false);

      await loadDashboard(json.api_key);
    } catch (err) {
      console.error("Workspace creation error:", err);
      alert("Failed to create workspace.");
    } finally {
      setLoading(false);
    }
  }

  function logout() {
    localStorage.removeItem("api_key");
    localStorage.removeItem("widget_key");
    setApiKey("");
    setData(null);
    setShowCreate(false);
    setForm({
      name: "",
      website_url: "",
      contact_email: "",
    });
  }

  async function startCheckout(plan: "starter" | "growth" | "pro") {
    try {
      if (!apiKey.trim()) {
        alert("Please load your dashboard first.");
        return;
      }

      setBillingLoading(plan);

      const res = await fetch(`${API_BASE}/v1/billing/checkout?plan=${plan}`, {
        method: "POST",
        headers: {
          "X-API-Key": apiKey.trim(),
        },
      });

      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || "Checkout failed");
      }

      const json = await res.json();

      if (json.checkout_url) {
        window.open(json.checkout_url, "_blank", "noopener,noreferrer");
      } else {
        alert("No checkout URL returned.");
      }
    } catch (err) {
      console.error("Billing error:", err);
      alert("Could not start checkout. Check Stripe setup and backend config.");
    } finally {
      setBillingLoading(null);
    }
  }

  async function copy(text: string, label = "Copied!") {
    try {
      await navigator.clipboard.writeText(text);
      alert(label);
    } catch (err) {
      console.error("Copy failed:", err);
      alert("Copy failed.");
    }
  }

  const embedSnippet = data
    ? `<script src="${API_BASE}/widget/widget.js" data-tenant-key="${data.tenant.widget_public_key}" data-api-base="${API_BASE}"></script>`
    : "";

  const demoUrl = data
    ? `${API_BASE}/widget/demo.html?key=${encodeURIComponent(data.tenant.widget_public_key)}`
    : "";

  return (
    <main className="page">
      <div className="container">
        <div className="hero">
          <div>
            <div className="eyebrow">AI Receptionist SaaS</div>
            <h1 className="title">Client Dashboard</h1>
            <p className="subtitle">
              Monitor leads, conversations, billing, and widget setup for your clinic.
            </p>
            <p className="subtitle" style={{ marginTop: 8 }}>
              Convert website visitors into leads and bookings automatically 24/7.
            </p>
          </div>
        </div>

        <section className="panel top-panel">
          <div className="panel-header">
            <div>
              <h2 className="panel-title">{data ? "Workspace Loaded" : "Get Started"}</h2>
              <p className="panel-subtitle">
                {data
                  ? "Manage your chatbot, pricing, leads, and widget setup from one place."
                  : "Create a new workspace or load an existing one with your private API key."}
              </p>
            </div>

            {data && (
              <button className="ghost-btn" onClick={logout}>
                Logout
              </button>
            )}
          </div>

          {!data && !showCreate && (
            <>
              <div className="button-row" style={{ marginBottom: 16 }}>
                <button className="primary-btn" onClick={() => setShowCreate(true)}>
                  Create Workspace
                </button>
              </div>

              <div className="key-row">
                <input
                  className="key-input"
                  placeholder="Paste private API key"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <button className="primary-btn" onClick={() => loadDashboard()} disabled={loading}>
                  {loading ? "Loading..." : "Load Dashboard"}
                </button>
              </div>
            </>
          )}

          {!data && showCreate && (
            <div className="form-grid" style={{ display: "grid", gap: 12 }}>
              <div className="key-row">
                <input
                  className="key-input"
                  placeholder="Clinic Name"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>

              <div className="key-row">
                <input
                  className="key-input"
                  placeholder="Website URL"
                  value={form.website_url}
                  onChange={(e) => setForm({ ...form, website_url: e.target.value })}
                />
              </div>

              <div className="key-row">
                <input
                  className="key-input"
                  placeholder="Email"
                  value={form.contact_email}
                  onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
                />
              </div>

              <div className="button-row">
                <button className="primary-btn" onClick={createWorkspace} disabled={loading}>
                  {loading ? "Creating..." : "Create Workspace"}
                </button>
                <button className="ghost-btn" onClick={() => setShowCreate(false)}>
                  Back
                </button>
              </div>
            </div>
          )}

          {data && (
            <div className="button-row" style={{ marginTop: 8 }}>
              <button
                className="primary-btn"
                onClick={() => window.open(demoUrl, "_blank", "noopener,noreferrer")}
              >
                🚀 Test Chatbot Live
              </button>
              <button
                className="ghost-btn"
                onClick={() => copy(demoUrl, "Demo link copied")}
              >
                Copy Demo Link
              </button>
            </div>
          )}
        </section>

        {data && (
          <>
            <section className="stats-grid">
              <StatCard title="Total Leads" value={data.summary.total_leads} tone="blue" />
              <StatCard
                title="Callback Requests"
                value={data.summary.callback_requests}
                tone="purple"
              />
              <StatCard title="Total Messages" value={data.summary.total_messages} tone="green" />
            </section>

            <section className="panel">
              <div className="panel-header">
                <div>
                  <h2 className="panel-title">Billing & Subscription</h2>
                  <p className="panel-subtitle">
                    Manage the current plan and upgrade this clinic account.
                  </p>
                </div>
              </div>

              <div className="billing-top">
                <div className="billing-status-card">
                  <div className="info-label">Current Plan</div>
                  <div className="billing-value">{data.tenant.plan_name || "Free / Not Set"}</div>
                </div>

                <div className="billing-status-card">
                  <div className="info-label">Subscription Status</div>
                  <div className="billing-value">
                    {data.tenant.subscription_status || "inactive"}
                  </div>
                </div>

                <div className="billing-status-card">
                  <div className="info-label">Stripe Customer</div>
                  <div className="billing-value">
                    {data.tenant.stripe_customer_id || "Not linked yet"}
                  </div>
                </div>
              </div>

              <div style={{ marginBottom: 18 }}>
                <div className="info-label" style={{ marginBottom: 6 }}>
                  Why this pays for itself
                </div>
                <div className="panel-subtitle">
                  Just 1 extra client per month can easily cover the subscription cost.
                </div>
                <div className="panel-subtitle" style={{ marginTop: 4 }}>
                  Limited early pricing for the first 20 customers.
                </div>
              </div>

              <div className="pricing-grid">
                <PlanCard
                  title="Starter"
                  price="$49/mo"
                  features={[
                    "Basic AI assistant",
                    "Website embed",
                    "Lead capture",
                    "Up to 500 conversations/month",
                  ]}
                  buttonLabel={billingLoading === "starter" ? "Opening..." : "Start with Starter"}
                  onClick={() => startCheckout("starter")}
                />
                <PlanCard
                  title="Growth"
                  price="$99/mo"
                  featured
                  features={[
                    "AI assistant + booking CTA",
                    "Lead capture + dashboard",
                    "Priority support",
                    "Up to 2,000 conversations/month",
                  ]}
                  buttonLabel={billingLoading === "growth" ? "Opening..." : "Upgrade to Growth"}
                  onClick={() => startCheckout("growth")}
                />
                <PlanCard
                  title="Pro"
                  price="$199/mo"
                  features={[
                    "Multi-location support",
                    "Advanced analytics",
                    "Higher limits",
                    "Premium onboarding",
                  ]}
                  buttonLabel={billingLoading === "pro" ? "Opening..." : "Go Pro"}
                  onClick={() => startCheckout("pro")}
                />
              </div>
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
                  <InfoRow label="Website" value={data.tenant.website_url || "Not set"} />
                  <InfoRow label="Calendly" value={data.tenant.calendly_url || "Not configured"} />
                  <InfoRow
                    label="Widget Key"
                    value={data.tenant.widget_public_key}
                    action={
                      <button
                        className="ghost-btn"
                        onClick={() => copy(data.tenant.widget_public_key, "Widget key copied")}
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
                    onClick={() => copy(data.tenant.widget_public_key, "Widget key copied")}
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
                        <span className={`badge badge-${lead.intent}`}>{lead.intent}</span>
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

function PlanCard({
  title,
  price,
  features,
  buttonLabel,
  onClick,
  featured = false,
}: {
  title: string;
  price: string;
  features: string[];
  buttonLabel: string;
  onClick: () => void;
  featured?: boolean;
}) {
  return (
    <div className={`plan-card ${featured ? "plan-featured" : ""}`}>
      {featured && <div className="badge badge-growth">Most Popular</div>}
      <div className="plan-title">{title}</div>
      <div className="plan-price">{price}</div>
      <ul className="plan-features">
        {features.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>
      <button className={featured ? "primary-btn" : "ghost-btn"} onClick={onClick}>
        {buttonLabel}
      </button>
    </div>
  );
}