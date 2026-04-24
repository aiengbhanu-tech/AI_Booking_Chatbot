"use client";

import { useEffect, useMemo, useState } from "react";

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

type DashboardData = {
  summary: Summary;
  leads: Lead[];
  tenant: Tenant;
};

export default function Dashboard() {
  const [apiKey, setApiKey] = useState("");
  const [data, setData] = useState<DashboardData | null>(null);

  const [loading, setLoading] = useState(false);
  const [billingLoading, setBillingLoading] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const [error, setError] = useState<string>("");
  const [successMessage, setSuccessMessage] = useState<string>("");

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

  function clearMessages() {
    setError("");
    setSuccessMessage("");
  }

  function showError(message: string) {
    setError(message);
    setSuccessMessage("");
  }

  function showSuccess(message: string) {
    setSuccessMessage(message);
    setError("");
  }

  async function loadDashboard(customKey?: string) {
    try {
      clearMessages();

      const key = (customKey || apiKey).trim();

      if (!key) {
        showError("Please paste your private API key.");
        return;
      }

      setLoading(true);

      const headers = { "X-API-Key": key };

      const [summaryRes, leadsRes, tenantRes] = await Promise.all([
        fetch(`${API_BASE}/v1/analytics/summary`, { headers }),
        fetch(`${API_BASE}/v1/leads`, { headers }),
        fetch(`${API_BASE}/v1/tenants/me`, { headers }),
      ]);

      if (!summaryRes.ok) {
        throw new Error(`Summary failed: ${summaryRes.status}`);
      }
      if (!leadsRes.ok) {
        throw new Error(`Leads failed: ${leadsRes.status}`);
      }
      if (!tenantRes.ok) {
        throw new Error(`Tenant failed: ${tenantRes.status}`);
      }

      const summary: Summary = await summaryRes.json();
      const leads: Lead[] = await leadsRes.json();
      const tenant: Tenant = await tenantRes.json();

      localStorage.setItem("api_key", key);
      localStorage.setItem("widget_key", tenant.widget_public_key);

      setApiKey(key);
      setData({ summary, leads, tenant });
      showSuccess("Dashboard loaded successfully.");
    } catch (err) {
      console.error("Dashboard load error:", err);
      showError("Could not load dashboard. Check backend URL, backend status, and API key.");
    } finally {
      setLoading(false);
    }
  }

  async function createWorkspace() {
    try {
      clearMessages();

      if (!form.name.trim()) {
        showError("Please enter clinic name.");
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
      showSuccess("Workspace created successfully.");
    } catch (err) {
      console.error("Workspace creation error:", err);
      showError("Failed to create workspace.");
    } finally {
      setLoading(false);
    }
  }

  async function openBillingPortal() {
    try {
      clearMessages();

      if (!apiKey.trim()) {
        showError("Please load your dashboard first.");
        return;
      }

      setBillingLoading("portal");

      const res = await fetch(`${API_BASE}/v1/billing/portal`, {
        method: "POST",
        headers: {
          "X-API-Key": apiKey.trim(),
        },
      });

      if (!res.ok) {
        const txt = await res.text();
        throw new Error(txt || "Billing portal failed");
      }

      const json = await res.json();

      if (json.portal_url) {
        window.open(json.portal_url, "_blank", "noopener,noreferrer");
      } else {
        showError("No billing portal URL returned.");
      }
    } catch (err) {
      console.error("Billing portal error:", err);
      showError("Could not open billing portal.");
    } finally {
      setBillingLoading(null);
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
    clearMessages();
  }

  async function startCheckout(plan: "starter" | "growth" | "pro") {
    try {
      clearMessages();

      if (!apiKey.trim()) {
        showError("Please load your dashboard first.");
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
        showError("No checkout URL returned.");
      }
    } catch (err) {
      console.error("Billing error:", err);
      showError("Could not start checkout. Check Stripe setup and backend config.");
    } finally {
      setBillingLoading(null);
    }
  }

  async function copy(text: string, label = "Copied!") {
    try {
      await navigator.clipboard.writeText(text);
      showSuccess(label);
    } catch (err) {
      console.error("Copy failed:", err);
      showError("Copy failed.");
    }
  }

  const embedSnippet = useMemo(() => {
    if (!data) return "";
    return `<script src="${API_BASE}/widget/widget.js" data-tenant-key="${data.tenant.widget_public_key}" data-api-base="${API_BASE}"></script>`;
  }, [data]);

  const demoUrl = useMemo(() => {
    if (!data) return "";
    return `${API_BASE}/widget/demo.html?key=${encodeURIComponent(data.tenant.widget_public_key)}`;
  }, [data]);

  const subscriptionLabel = data?.tenant.subscription_status || "inactive";
  const planLabel = data?.tenant.plan_name || "Free / Not Set";

  return (
    <main className="page">
      <div className="bg-orb bg-orb-one" />
      <div className="bg-orb bg-orb-two" />

      <div className="container">
        <section className="hero">
          <div className="hero-left">
            <div className="eyebrow">AI Receptionist SaaS</div>
            <h1 className="title">Client Dashboard</h1>
            <p className="subtitle">
              Monitor leads, conversations, billing, and widget setup for your clinic.
            </p>
            <p className="subtitle secondary-subtitle">
              Convert website visitors into leads and bookings automatically, 24/7.
            </p>
          </div>

          <div className="hero-right">
            <div className="hero-card">
              <div className="hero-card-label">Backend</div>
              <div className="hero-card-value">{API_BASE}</div>
            </div>
          </div>
        </section>

        {(error || successMessage) && (
          <div className={`message-banner ${error ? "message-error" : "message-success"}`}>
            {error || successMessage}
          </div>
        )}

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
              <button className="ghost-btn danger-btn" onClick={logout}>
                Logout
              </button>
            )}
          </div>

          {!data && !showCreate && (
            <div className="stack-lg">
              <div className="button-row">
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
            </div>
          )}

          {!data && showCreate && (
            <div className="form-grid">
              <div className="input-block">
                <label className="input-label">Clinic Name</label>
                <input
                  className="key-input"
                  placeholder="e.g. Radiance Dentistry"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </div>

              <div className="input-block">
                <label className="input-label">Website URL</label>
                <input
                  className="key-input"
                  placeholder="https://example.com"
                  value={form.website_url}
                  onChange={(e) => setForm({ ...form, website_url: e.target.value })}
                />
              </div>

              <div className="input-block">
                <label className="input-label">Contact Email</label>
                <input
                  className="key-input"
                  placeholder="hello@clinic.com"
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
            <div className="dashboard-actions">
              <button
                className="primary-btn"
                onClick={() => window.open(demoUrl, "_blank", "noopener,noreferrer")}
              >
                🚀 Test Chatbot Live
              </button>

              <button className="ghost-btn" onClick={() => copy(demoUrl, "Demo link copied")}>
                Copy Demo Link
              </button>

              <button className="ghost-btn" onClick={() => loadDashboard()} disabled={loading}>
                {loading ? "Refreshing..." : "Refresh Dashboard"}
              </button>
            </div>
          )}
        </section>

        {data && (
          <>
            <section className="stats-grid">
              <StatCard
                title="Total Leads"
                value={data.summary.total_leads}
                tone="blue"
                helper="Captured lead submissions"
              />
              <StatCard
                title="Callback Requests"
                value={data.summary.callback_requests}
                tone="purple"
                helper="Visitors asking for call back"
              />
              <StatCard
                title="Total Messages"
                value={data.summary.total_messages}
                tone="green"
                helper="All chatbot conversations"
              />
            </section>

            <section className="panel">
              <div className="panel-header">
                <div>
                  <h2 className="panel-title">Billing & Subscription</h2>
                  <p className="panel-subtitle">
                    Manage the current plan and upgrade this clinic account.
                  </p>
                  <button className="ghost-btn" onClick={openBillingPortal}>
                    {billingLoading === "portal" ? "Opening..." : "Manage Billing"}
                  </button>
                </div>
              </div>

              <div className="billing-top">
                <StatusCard label="Current Plan" value={planLabel} />
                <StatusCard
                  label="Subscription Status"
                  value={subscriptionLabel}
                  status={subscriptionLabel}
                />
                <StatusCard
                  label="Stripe Customer"
                  value={data.tenant.stripe_customer_id || "Not linked yet"}
                />
              </div>

              <div className="billing-note">
                <div className="info-label">Why this pays for itself</div>
                <div className="panel-subtitle">
                  Just 1 extra client per month can easily cover the subscription cost.
                </div>
                <div className="panel-subtitle subtle-gap">
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
                  <InfoRow
                    label="Contact Email"
                    value={data.tenant.contact_email || "Not configured"}
                  />
                  <InfoRow label="Calendly" value={data.tenant.calendly_url || "Not configured"} />
                  <InfoRow
                    label="Widget Key"
                    value={data.tenant.widget_public_key}
                    action={
                      <button
                        className="ghost-btn small-btn"
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
                          <div className="lead-meta">{formatIntent(lead.intent)}</div>
                        </div>
                        <span className={`badge ${getIntentBadgeClass(lead.intent)}`}>
                          {lead.intent}
                        </span>
                      </div>

                      <div className="lead-details">
                        <LeadDetail label="Phone" value={lead.phone || "-"} />
                        <LeadDetail label="Email" value={lead.email || "-"} />
                        <LeadDetail label="Notes" value={lead.notes || "-"} />
                        <LeadDetail
                          label="Created"
                          value={new Date(lead.created_at).toLocaleString()}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>

      <style jsx global>{`
        :global(body) {
          margin: 0;
          background:
            radial-gradient(circle at top left, rgba(59, 130, 246, 0.12), transparent 25%),
            radial-gradient(circle at bottom right, rgba(168, 85, 247, 0.12), transparent 25%),
            #08111f;
          color: #e5eefc;
          font-family:
            Inter,
            ui-sans-serif,
            system-ui,
            -apple-system,
            BlinkMacSystemFont,
            "Segoe UI",
            sans-serif;
        }

        * {
          box-sizing: border-box;
        }

        .page {
          min-height: 100vh;
          position: relative;
          overflow-x: hidden;
          padding: 32px 16px 60px;
        }

        .bg-orb {
          position: fixed;
          border-radius: 999px;
          filter: blur(80px);
          pointer-events: none;
          z-index: 0;
        }

        .bg-orb-one {
          width: 280px;
          height: 280px;
          top: 40px;
          left: -80px;
          background: rgba(59, 130, 246, 0.18);
        }

        .bg-orb-two {
          width: 320px;
          height: 320px;
          right: -100px;
          bottom: 40px;
          background: rgba(168, 85, 247, 0.15);
        }

        .container {
          position: relative;
          z-index: 1;
          max-width: 1220px;
          margin: 0 auto;
          display: grid;
          gap: 22px;
        }

        .hero {
          display: grid;
          grid-template-columns: 1.4fr 0.8fr;
          gap: 18px;
          align-items: stretch;
        }

        .hero-left,
        .hero-card,
        .panel,
        .stat-card,
        .plan-card,
        .lead-card {
          background: rgba(12, 23, 42, 0.78);
          backdrop-filter: blur(14px);
          border: 1px solid rgba(148, 163, 184, 0.14);
          box-shadow: 0 12px 40px rgba(0, 0, 0, 0.26);
        }

        .hero-left {
          border-radius: 28px;
          padding: 30px;
        }

        .hero-right {
          display: flex;
        }

        .hero-card {
          width: 100%;
          border-radius: 28px;
          padding: 24px;
          display: flex;
          flex-direction: column;
          justify-content: center;
        }

        .hero-card-label {
          font-size: 12px;
          text-transform: uppercase;
          letter-spacing: 0.12em;
          color: #94a3b8;
          margin-bottom: 10px;
        }

        .hero-card-value {
          font-size: 18px;
          font-weight: 700;
          color: #f8fbff;
          word-break: break-word;
        }

        .eyebrow {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          background: rgba(59, 130, 246, 0.16);
          border: 1px solid rgba(96, 165, 250, 0.28);
          color: #bfdbfe;
          padding: 8px 12px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          margin-bottom: 16px;
        }

        .title {
          margin: 0;
          font-size: clamp(34px, 5vw, 52px);
          line-height: 1.02;
          letter-spacing: -0.03em;
          color: #ffffff;
        }

        .subtitle {
          margin: 14px 0 0;
          color: #b8c7de;
          font-size: 16px;
          line-height: 1.7;
          max-width: 760px;
        }

        .secondary-subtitle {
          margin-top: 6px;
        }

        .message-banner {
          padding: 14px 16px;
          border-radius: 18px;
          font-size: 14px;
          font-weight: 600;
          border: 1px solid transparent;
        }

        .message-error {
          background: rgba(239, 68, 68, 0.12);
          color: #fecaca;
          border-color: rgba(239, 68, 68, 0.28);
        }

        .message-success {
          background: rgba(34, 197, 94, 0.12);
          color: #bbf7d0;
          border-color: rgba(34, 197, 94, 0.28);
        }

        .panel {
          border-radius: 28px;
          padding: 24px;
        }

        .top-panel {
          padding: 26px;
        }

        .panel-header {
          display: flex;
          justify-content: space-between;
          gap: 16px;
          align-items: flex-start;
          margin-bottom: 18px;
        }

        .panel-title {
          margin: 0;
          font-size: 22px;
          color: #ffffff;
        }

        .panel-subtitle {
          margin: 6px 0 0;
          color: #94a3b8;
          line-height: 1.6;
        }

        .subtle-gap {
          margin-top: 4px;
        }

        .stack-lg {
          display: grid;
          gap: 16px;
        }

        .button-row,
        .dashboard-actions {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
        }

        .key-row {
          display: grid;
          grid-template-columns: 1fr auto;
          gap: 12px;
        }

        .form-grid {
          display: grid;
          gap: 14px;
        }

        .input-block {
          display: grid;
          gap: 8px;
        }

        .input-label {
          font-size: 13px;
          font-weight: 700;
          color: #cbd5e1;
        }

        .key-input {
          width: 100%;
          background: rgba(15, 23, 42, 0.82);
          border: 1px solid rgba(148, 163, 184, 0.2);
          color: #f8fafc;
          border-radius: 16px;
          padding: 14px 16px;
          outline: none;
          font-size: 15px;
          transition: border-color 0.2s ease, box-shadow 0.2s ease;
        }

        .key-input:focus {
          border-color: rgba(96, 165, 250, 0.7);
          box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.16);
        }

        .primary-btn,
        .ghost-btn {
          border: none;
          border-radius: 16px;
          padding: 13px 18px;
          font-size: 14px;
          font-weight: 700;
          cursor: pointer;
          transition:
            transform 0.18s ease,
            opacity 0.18s ease,
            background 0.18s ease,
            border-color 0.18s ease;
        }

        .primary-btn {
          background: linear-gradient(135deg, #3b82f6, #7c3aed);
          color: white;
          box-shadow: 0 10px 24px rgba(59, 130, 246, 0.24);
        }

        .primary-btn:hover:not(:disabled),
        .ghost-btn:hover:not(:disabled) {
          transform: translateY(-1px);
        }

        .primary-btn:disabled,
        .ghost-btn:disabled {
          opacity: 0.65;
          cursor: not-allowed;
          transform: none;
        }

        .ghost-btn {
          background: rgba(15, 23, 42, 0.75);
          color: #dbeafe;
          border: 1px solid rgba(148, 163, 184, 0.18);
        }

        .danger-btn {
          color: #fecaca;
        }

        .small-btn {
          padding: 10px 14px;
          border-radius: 12px;
          font-size: 13px;
        }
        
        .stat-card {
          border-radius: 24px;
          padding: 22px;
          position: relative;
          overflow: hidden;
          background: #f8fafc !important;
          border: 1px solid rgba(15, 23, 42, 0.08) !important;
        }

        .stat-label {
          color: #475569 !important;
          font-size: 13px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }

        .stat-value {
          margin-top: 10px;
          font-size: 34px;
          font-weight: 800;
          color: #0f172a !important;
        }

        .stat-helper {
          margin-top: 8px;
          color: #334155 !important;
          font-size: 14px;
        }

        .billing-status-card {
          background: #f8fafc !important;
          border: 1px solid rgba(15, 23, 42, 0.08) !important;
          border-radius: 20px;
          padding: 18px;
        }

        .info-label {
          color: #475569 !important;
          font-size: 12px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.08em;
        }

        .billing-value {
          margin-top: 8px;
          color: #0f172a !important;
          font-size: 18px;
          font-weight: 700;
          word-break: break-word;
        }

        .info-value {
          margin-top: 6px;
          color: #0f172a !important;
          line-height: 1.55;
          word-break: break-word;
        }

        .info-row {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: flex-start;
          padding: 14px 16px;
          border-radius: 16px;
          background: #f8fafc !important;
          border: 1px solid rgba(15, 23, 42, 0.08) !important;
        }

        .plan-card {
          border-radius: 24px;
          padding: 22px;
          display: flex;
          flex-direction: column;
          gap: 12px;
          position: relative;
          background: #f8fafc !important;
          border: 1px solid rgba(15, 23, 42, 0.08) !important;
        }

        .plan-title {
          font-size: 22px;
          font-weight: 800;
          color: #0f172a !important;
        }

        .plan-price {
          font-size: 30px;
          font-weight: 900;
          color: #0f172a !important;
        }

        .plan-features {
          margin: 0;
          padding-left: 18px;
          color: #334155 !important;
          display: grid;
          gap: 8px;
          line-height: 1.5;
          flex: 1;
        }

        .plan-features li {
          color: #334155 !important;
        }

        .plan-card .ghost-btn {
          background: #e2e8f0 !important;
          color: #0f172a !important;
          border: 1px solid rgba(15, 23, 42, 0.1) !important;
        }

        .plan-card .primary-btn {
          color: #ffffff !important;
        }

        .stats-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 16px;
        }

        .stat-card::after {
          content: "";
          position: absolute;
          inset: auto -30px -30px auto;
          width: 120px;
          height: 120px;
          border-radius: 999px;
          opacity: 0.12;
        }

        .stat-blue::after {
          background: #3b82f6;
        }

        .stat-purple::after {
          background: #8b5cf6;
        }

        .stat-green::after {
          background: #22c55e;
        }

        .billing-top {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 14px;
          margin-bottom: 18px;
        }

        .status-active {
          background: rgba(34, 197, 94, 0.14);
          color: #166534;
          border: 1px solid rgba(34, 197, 94, 0.3);
        }

        .status-inactive,
        .status-cancelled,
        .status-past_due,
        .status-unpaid {
          background: rgba(239, 68, 68, 0.14);
          color: #991b1b;
          border: 1px solid rgba(239, 68, 68, 0.3);
        }

        .status-trialing {
          background: rgba(59, 130, 246, 0.14);
          color: #1d4ed8;
          border: 1px solid rgba(59, 130, 246, 0.3);
        }

        .status-pill {
          display: inline-flex;
          margin-top: 8px;
          padding: 6px 10px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 700;
          text-transform: capitalize;
          width: fit-content;
        }

        .billing-note {
          margin-bottom: 18px;
        }

        .pricing-grid {
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 16px;
        }

        .plan-featured {
          border: 1px solid rgba(96, 165, 250, 0.45);
          box-shadow: 0 14px 36px rgba(59, 130, 246, 0.18);
        }

        .stat-card *,
        .billing-status-card *,
        .info-row *,
        .plan-card * {
          color: inherit;
        }

        .grid.two-col {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 16px;
        }

        .info-list {
          display: grid;
          gap: 14px;
        }

        .info-row:last-child {
          border-bottom: none;
        }

        .code-box {
          background: #06101f;
          border: 1px solid rgba(96, 165, 250, 0.18);
          color: #f8fafc;
          border-radius: 18px;
          padding: 16px;
          font-size: 13px;
          line-height: 1.7;
          overflow-x: auto;
          white-space: pre-wrap;
          word-break: break-word;
          margin-bottom: 16px;
        }

        .lead-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 16px;
        }

        .lead-card {
          border-radius: 22px;
          padding: 20px;
        }

        .lead-top {
          display: flex;
          justify-content: space-between;
          gap: 12px;
          align-items: flex-start;
          margin-bottom: 16px;
        }

        .lead-name {
          font-size: 18px;
          font-weight: 800;
          color: #ffffff;
        }

        .lead-meta {
          margin-top: 6px;
          color: #94a3b8;
          font-size: 14px;
        }

        .badge {
          border-radius: 999px;
          padding: 8px 12px;
          font-size: 12px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: 0.06em;
          border: 1px solid transparent;
          white-space: nowrap;
        }

        .badge-growth {
          background: rgba(59, 130, 246, 0.16);
          color: #bfdbfe;
          border-color: rgba(59, 130, 246, 0.35);
        }

        .badge-booking {
          background: rgba(34, 197, 94, 0.15);
          color: #bbf7d0;
          border-color: rgba(34, 197, 94, 0.3);
        }

        .badge-callback {
          background: rgba(168, 85, 247, 0.16);
          color: #e9d5ff;
          border-color: rgba(168, 85, 247, 0.32);
        }

        .badge-pricing {
          background: rgba(245, 158, 11, 0.16);
          color: #fde68a;
          border-color: rgba(245, 158, 11, 0.32);
        }

        .badge-default {
          background: rgba(148, 163, 184, 0.14);
          color: #e2e8f0;
          border-color: rgba(148, 163, 184, 0.24);
        }

        .lead-details {
          display: grid;
          gap: 10px;
        }

        .lead-detail {
          display: grid;
          gap: 4px;
          padding: 10px 12px;
          border-radius: 14px;
          background: rgba(8, 15, 28, 0.55);
          border: 1px solid rgba(148, 163, 184, 0.1);
        }

        .muted {
          color: #94a3b8;
          font-size: 12px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.06em;
        }

        .lead-text {
          color: #f8fafc;
          line-height: 1.55;
          word-break: break-word;
        }

        .empty-state {
          border-radius: 20px;
          padding: 28px;
          background: rgba(8, 15, 28, 0.55);
          border: 1px dashed rgba(148, 163, 184, 0.22);
          text-align: center;
        }

        .empty-title {
          color: #ffffff;
          font-size: 20px;
          font-weight: 800;
        }

        .empty-description {
          margin-top: 8px;
          color: #94a3b8;
          line-height: 1.6;
        }

        .stat-card .stat-label,
        .stat-card .stat-value,
        .stat-card .stat-helper,
        .billing-status-card .info-label,
        .billing-status-card .billing-value,
        .info-row .info-label,
        .info-row .info-value,
        .plan-card .plan-title,
        .plan-card .plan-price,
        .plan-card .plan-features,
        .plan-card .plan-features li {
          color: #0f172a !important;
        }

        .stat-card .stat-label,
        .billing-status-card .info-label,
        .info-row .info-label {
          color: #475569 !important;
        }

        .stat-card .stat-helper,
        .plan-card .plan-features,
        .plan-card .plan-features li {
          color: #334155 !important;
        }

        @media (max-width: 1100px) {
          .hero,
          .billing-top,
          .pricing-grid,
          .stats-grid,
          .grid.two-col,
          .lead-grid {
            grid-template-columns: 1fr;
          }
        }

        @media (max-width: 720px) {
          .page {
            padding: 20px 12px 48px;
          }

          .hero-left,
          .hero-card,
          .panel {
            border-radius: 22px;
          }

          .title {
            font-size: 34px;
          }

          .key-row {
            grid-template-columns: 1fr;
          }

          .panel-header,
          .info-row,
          .lead-top {
            flex-direction: column;
          }

          .primary-btn,
          .ghost-btn {
            width: 100%;
            justify-content: center;
          }

          .button-row,
          .dashboard-actions {
            display: grid;
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </main>
  );
}

function StatCard({
  title,
  value,
  tone,
  helper,
}: {
  title: string;
  value: number;
  tone: "blue" | "purple" | "green";
  helper?: string;
}) {
  return (
    <div className={`stat-card stat-${tone}`}>
      <div className="stat-label">{title}</div>
      <div className="stat-value">{value}</div>
      {helper ? <div className="stat-helper">{helper}</div> : null}
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

function LeadDetail({ label, value }: { label: string; value: string }) {
  return (
    <div className="lead-detail">
      <span className="muted">{label}</span>
      <span className="lead-text">{value}</span>
    </div>
  );
}

function StatusCard({
  label,
  value,
  status,
}: {
  label: string;
  value: string;
  status?: string;
}) {
  return (
    <div className="billing-status-card">
      <div className="info-label">{label}</div>
      <div className="billing-value">{value}</div>
      {status ? (
        <div className={`status-pill ${getStatusClass(status)}`}>{status}</div>
      ) : null}
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

function getIntentBadgeClass(intent: string) {
  const value = intent.toLowerCase();

  if (value.includes("book")) return "badge badge-booking";
  if (value.includes("callback") || value.includes("call")) return "badge badge-callback";
  if (value.includes("price") || value.includes("pricing")) return "badge badge-pricing";

  return "badge badge-default";
}

function formatIntent(intent: string) {
  if (!intent) return "General inquiry";

  return intent
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function getStatusClass(status: string) {
  const value = status.toLowerCase();

  if (value === "active") return "status-active";
  if (value === "trialing") return "status-trialing";
  if (value === "inactive") return "status-inactive";
  if (value === "cancelled") return "status-cancelled";
  if (value === "past_due") return "status-past_due";
  if (value === "unpaid") return "status-unpaid";

  return "status-inactive";
}