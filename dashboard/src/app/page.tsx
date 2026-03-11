"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

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

type Chat = {
  session_id: string;
  role: string;
  content: string;
  created_at: string;
};

type Me = {
  id: number;
  name: string;
  website_url: string | null;
  api_key_last4: string;
  calendly_url: string | null;
  contact_email: string | null;
  widget_public_key: string;
};

export default function Home() {
  const [ready, setReady] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [chats, setChats] = useState<Chat[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const saved = localStorage.getItem("tenant_api_key") || "";
    setApiKey(saved);
    setReady(true);
  }, []);

  async function loadData() {
    setError("");
    try {
      const [s, l, c, m] = await Promise.all([
        apiGet("/v1/analytics/summary"),
        apiGet("/v1/leads"),
        apiGet("/v1/analytics/recent-chats"),
        apiGet("/v1/tenants/me"),
      ]);
      setSummary(s);
      setLeads(l);
      setChats(c);
      setMe(m);
    } catch (e) {
      setError("Failed to load dashboard data. Check your API key.");
    }
  }

  function saveKey() {
    localStorage.setItem("tenant_api_key", apiKey);
    loadData();
  }

  if (!ready) return null;

  const embedSnippet = me
    ? `<script src="http://localhost:8000/widget/widget.js" data-tenant-key="${me.widget_public_key}" data-api-base="http://localhost:8000"></script>`
    : "";

  return (
    <main style={{ padding: 24, fontFamily: "Arial, sans-serif" }}>
      <h1>AI Booking Chatbot Dashboard</h1>

      <div style={{ marginBottom: 16 }}>
        <input
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder="Paste tenant private API key"
          style={{ padding: 10, width: 420, marginRight: 8 }}
        />
        <button onClick={saveKey} style={{ padding: "10px 16px" }}>
          Load Dashboard
        </button>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {summary && (
        <>
          <section style={{ display: "flex", gap: 16, marginBottom: 24 }}>
            <Card title="Total Leads" value={summary.total_leads} />
            <Card title="Callback Requests" value={summary.callback_requests} />
            <Card title="Total Messages" value={summary.total_messages} />
          </section>

          {me && (
            <section style={{ marginBottom: 24 }}>
              <h2>Embed Snippet</h2>
              <textarea
                readOnly
                value={embedSnippet}
                style={{ width: "100%", height: 100, padding: 12 }}
              />
            </section>
          )}

          <section style={{ marginBottom: 24 }}>
            <h2>Recent Leads</h2>
            <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
              {leads.length === 0 ? (
                <p>No leads yet.</p>
              ) : (
                leads.map((lead) => (
                  <div key={lead.id} style={{ borderBottom: "1px solid #eee", padding: "10px 0" }}>
                    <strong>{lead.intent}</strong> — {lead.name || "Unknown"} — {lead.email || "-"} — {lead.phone || "-"}
                    <div>{lead.notes || ""}</div>
                  </div>
                ))
              )}
            </div>
          </section>

          <section>
            <h2>Recent Chats</h2>
            <div style={{ border: "1px solid #ddd", borderRadius: 8, padding: 12 }}>
              {chats.length === 0 ? (
                <p>No chats yet.</p>
              ) : (
                chats.map((chat, idx) => (
                  <div key={idx} style={{ borderBottom: "1px solid #eee", padding: "10px 0" }}>
                    <strong>{chat.role}</strong> [{chat.session_id}]
                    <div>{chat.content}</div>
                  </div>
                ))
              )}
            </div>
          </section>
        </>
      )}
    </main>
  );
}

function Card({ title, value }: { title: string; value: number }) {
  return (
    <div
      style={{
        border: "1px solid #ddd",
        borderRadius: 12,
        padding: 16,
        minWidth: 180,
      }}
    >
      <div style={{ fontSize: 14, color: "#666" }}>{title}</div>
      <div style={{ fontSize: 28, fontWeight: 700 }}>{value}</div>
    </div>
  );
}