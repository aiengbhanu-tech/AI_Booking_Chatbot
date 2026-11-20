"use client";

import { useCallback, useEffect, useState } from "react";

type VoiceSettings = {
  web_voice_enabled: boolean;
  phone_enabled: boolean;
  twilio_phone_number: string | null;
  forward_to_number: string | null;
  ring_business_first: boolean;
  ring_timeout_seconds: number;
  missed_call_mode: "ai_answer" | "callback_only";
  callback_enabled: boolean;
  callback_delay_seconds: number;
  callback_max_attempts: number;
  callback_retry_minutes: number;
  callback_window_start_hour: number;
  callback_window_end_hour: number;
  timezone: string;
  default_country_code: string;
  auto_callback_web_leads: boolean;
  sms_booking_link_enabled: boolean;
  voice: string | null;
  greeting: string | null;
  extra_instructions: string | null;
};

type Platform = {
  openai_configured: boolean;
  twilio_configured: boolean;
  public_base_url: string | null;
  realtime_model: string;
  webhooks: { voice_url: string | null; status_callback_url: string | null };
};

type VoiceSummary = {
  total_calls: number;
  web_voice_sessions: number;
  ai_handled: number;
  missed_calls: number;
  callbacks_pending: number;
  callbacks_completed: number;
};

type Call = {
  id: number;
  channel: "phone" | "web";
  direction: "inbound" | "outbound";
  from_number: string | null;
  to_number: string | null;
  status: string;
  answered_by: string | null;
  outcome: string | null;
  summary: string | null;
  duration_seconds: number | null;
  started_at: string | null;
  transcript?: { role: string; text: string }[];
  tool_events?: { name: string; ok: boolean }[];
};

type Callback = {
  id: number;
  phone: string;
  name: string | null;
  reason: string;
  context: string | null;
  status: string;
  attempts: number;
  max_attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
};

const VOICES = ["marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"];

export default function VoicePanel({ apiBase, apiKey }: { apiBase: string; apiKey: string }) {
  const [settings, setSettings] = useState<VoiceSettings | null>(null);
  const [platform, setPlatform] = useState<Platform | null>(null);
  const [summary, setSummary] = useState<VoiceSummary | null>(null);
  const [calls, setCalls] = useState<Call[]>([]);
  const [callbacks, setCallbacks] = useState<Callback[]>([]);
  const [selected, setSelected] = useState<Call | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [manual, setManual] = useState({ phone: "", name: "", context: "" });

  const api = useCallback(
    async (path: string, init?: RequestInit) => {
      const res = await fetch(`${apiBase}${path}`, {
        ...init,
        headers: { "X-API-Key": apiKey, "Content-Type": "application/json", ...(init?.headers || {}) },
        cache: "no-store",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = Array.isArray(body.detail) ? body.detail.map((d: { msg: string }) => d.msg).join("; ") : body.detail;
        throw new Error(detail || `Request failed (${res.status})`);
      }
      return body;
    },
    [apiBase, apiKey]
  );

  const load = useCallback(async () => {
    try {
      const [s, sum, c, cb] = await Promise.all([
        api("/v1/voice/settings"),
        api("/v1/voice/summary"),
        api("/v1/voice/calls?limit=30"),
        api("/v1/voice/callbacks?limit=30"),
      ]);
      setSettings(s.settings);
      setPlatform(s.platform);
      setSummary(sum);
      setCalls(c);
      setCallbacks(cb);
    } catch (e) {
      setNotice({ ok: false, text: `Voice data unavailable: ${(e as Error).message}` });
    }
  }, [api]);

  useEffect(() => {
    if (apiKey) void load();
  }, [apiKey, load]);

  function set<K extends keyof VoiceSettings>(key: K, value: VoiceSettings[K]) {
    setSettings((s) => (s ? { ...s, [key]: value } : s));
  }

  async function save() {
    if (!settings) return;
    setSaving(true);
    setNotice(null);
    try {
      const out = await api("/v1/voice/settings", { method: "PUT", body: JSON.stringify(settings) });
      setSettings(out.settings);
      setPlatform(out.platform);
      setNotice({ ok: true, text: "Voice settings saved." });
    } catch (e) {
      setNotice({ ok: false, text: (e as Error).message });
    } finally {
      setSaving(false);
    }
  }

  async function openCall(id: number) {
    try {
      setSelected(await api(`/v1/voice/calls/${id}`));
    } catch (e) {
      setNotice({ ok: false, text: (e as Error).message });
    }
  }

  async function scheduleManual() {
    try {
      await api("/v1/voice/callbacks", { method: "POST", body: JSON.stringify(manual) });
      setManual({ phone: "", name: "", context: "" });
      setNotice({ ok: true, text: "Callback queued. The AI will call shortly (within calling hours)." });
      void load();
    } catch (e) {
      setNotice({ ok: false, text: (e as Error).message });
    }
  }

  async function cancel(id: number) {
    try {
      await api(`/v1/voice/callbacks/${id}/cancel`, { method: "POST" });
      void load();
    } catch (e) {
      setNotice({ ok: false, text: (e as Error).message });
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setNotice({ ok: true, text: "Copied." });
    } catch {
      setNotice({ ok: false, text: "Copy failed." });
    }
  }

  if (!settings || !platform) {
    return (
      <section className="panel">
        <h2 className="panel-title">Voice Agent & Calls</h2>
        <p className="panel-subtitle">{notice?.text || "Loading voice settings…"}</p>
      </section>
    );
  }

  return (
    <>
      <section className="panel">
        <div className="panel-header">
          <div>
            <h2 className="panel-title">Voice Agent & Calls</h2>
            <p className="panel-subtitle">
              Let customers talk to your assistant from the website widget and on your phone line. Missed calls get an
              automatic AI call back.
            </p>
          </div>
          <button className="ghost-btn" onClick={() => void load()}>
            Refresh
          </button>
        </div>

        {notice && (
          <div className={`message-banner ${notice.ok ? "message-success" : "message-error"}`} style={{ marginBottom: 16 }}>
            {notice.text}
          </div>
        )}

        {summary && (
          <div className="voice-stats">
            <Stat label="Phone calls" value={summary.total_calls} />
            <Stat label="Handled by AI" value={summary.ai_handled} />
            <Stat label="Missed calls" value={summary.missed_calls} />
            <Stat label="Callbacks pending" value={summary.callbacks_pending} />
            <Stat label="Callbacks done" value={summary.callbacks_completed} />
            <Stat label="Widget voice chats" value={summary.web_voice_sessions} />
          </div>
        )}

        <div className="voice-setup">
          <SetupItem ok={platform.openai_configured} label="OpenAI key (voice model)" hint="Set OPENAI_API_KEY on the backend" />
          <SetupItem ok={platform.twilio_configured} label="Twilio + public URL" hint="Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, PUBLIC_BASE_URL" />
        </div>

        {platform.webhooks.voice_url && (
          <div className="voice-webhooks">
            <div className="input-label">Paste into your Twilio number → Voice configuration</div>
            <WebhookRow label="A call comes in (POST)" url={platform.webhooks.voice_url} onCopy={copy} />
            <WebhookRow label="Call status changes (POST)" url={platform.webhooks.status_callback_url || ""} onCopy={copy} />
          </div>
        )}
      </section>

      <section className="grid two-col">
        <div className="panel">
          <h2 className="panel-title">Website voice</h2>
          <p className="panel-subtitle">Adds a 🎤 button to the chat widget. Same knowledge, leads and booking as the text chat.</p>
          <div className="voice-form">
            <Toggle label="Enable voice in chat widget" checked={settings.web_voice_enabled} onChange={(v) => set("web_voice_enabled", v)} />
            <Field label="Voice">
              <select className="key-input" value={settings.voice || ""} onChange={(e) => set("voice", e.target.value || null)}>
                <option value="">Default</option>
                {VOICES.map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Greeting (optional)">
              <input
                className="key-input"
                placeholder="Hi! Thanks for reaching out to SmileCare. How can I help?"
                value={settings.greeting || ""}
                onChange={(e) => set("greeting", e.target.value)}
              />
            </Field>
            <Field label="Extra instructions for the agent (optional)">
              <textarea
                className="key-input voice-textarea"
                placeholder="e.g. We don't accept walk-ins. Always mention the free first consultation."
                value={settings.extra_instructions || ""}
                onChange={(e) => set("extra_instructions", e.target.value)}
              />
            </Field>
          </div>
        </div>

        <div className="panel">
          <h2 className="panel-title">Phone line</h2>
          <p className="panel-subtitle">Your Twilio number rings your team first; if nobody answers, the AI picks up or calls back.</p>
          <div className="voice-form">
            <Toggle label="Enable phone line" checked={settings.phone_enabled} onChange={(v) => set("phone_enabled", v)} />
            <Field label="Twilio phone number">
              <input className="key-input" placeholder="+15551234567" value={settings.twilio_phone_number || ""} onChange={(e) => set("twilio_phone_number", e.target.value)} />
            </Field>
            <Field label="Forward to (your team's phone)">
              <input className="key-input" placeholder="+15557654321" value={settings.forward_to_number || ""} onChange={(e) => set("forward_to_number", e.target.value)} />
            </Field>
            <Toggle label="Ring my team first" checked={settings.ring_business_first} onChange={(v) => set("ring_business_first", v)} />
            <div className="voice-row">
              <Field label="Ring for (seconds)">
                <input type="number" min={5} max={60} className="key-input" value={settings.ring_timeout_seconds} onChange={(e) => set("ring_timeout_seconds", Number(e.target.value))} />
              </Field>
              <Field label="If nobody answers">
                <select className="key-input" value={settings.missed_call_mode} onChange={(e) => set("missed_call_mode", e.target.value as VoiceSettings["missed_call_mode"])}>
                  <option value="ai_answer">AI answers the call</option>
                  <option value="callback_only">Hang up & AI calls back</option>
                </select>
              </Field>
            </div>
            <Toggle
              label="Text the booking link when callers ask (needs Calendly URL)"
              checked={settings.sms_booking_link_enabled}
              onChange={(v) => set("sms_booking_link_enabled", v)}
            />
          </div>
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Missed-call callbacks</h2>
        <p className="panel-subtitle">When a caller hangs up before talking to anyone, the AI calls them back inside your calling hours.</p>
        <div className="voice-form">
          <Toggle label="Call back missed callers automatically" checked={settings.callback_enabled} onChange={(v) => set("callback_enabled", v)} />
          <Toggle
            label="Also call website visitors who request a callback in the chat"
            checked={settings.auto_callback_web_leads}
            onChange={(v) => set("auto_callback_web_leads", v)}
          />
          <div className="voice-row voice-row-4">
            <Field label="Wait before calling (sec)">
              <input type="number" min={0} className="key-input" value={settings.callback_delay_seconds} onChange={(e) => set("callback_delay_seconds", Number(e.target.value))} />
            </Field>
            <Field label="Max attempts">
              <input type="number" min={1} max={5} className="key-input" value={settings.callback_max_attempts} onChange={(e) => set("callback_max_attempts", Number(e.target.value))} />
            </Field>
            <Field label="Retry after (min)">
              <input type="number" min={1} className="key-input" value={settings.callback_retry_minutes} onChange={(e) => set("callback_retry_minutes", Number(e.target.value))} />
            </Field>
            <Field label="Country code">
              <input className="key-input" value={settings.default_country_code} onChange={(e) => set("default_country_code", e.target.value)} />
            </Field>
          </div>
          <div className="voice-row voice-row-3">
            <Field label="Calling hours from">
              <input type="number" min={0} max={23} className="key-input" value={settings.callback_window_start_hour} onChange={(e) => set("callback_window_start_hour", Number(e.target.value))} />
            </Field>
            <Field label="Until">
              <input type="number" min={1} max={24} className="key-input" value={settings.callback_window_end_hour} onChange={(e) => set("callback_window_end_hour", Number(e.target.value))} />
            </Field>
            <Field label="Timezone (IANA)">
              <input className="key-input" placeholder="America/New_York" value={settings.timezone} onChange={(e) => set("timezone", e.target.value)} />
            </Field>
          </div>
        </div>

        <div className="button-row" style={{ marginTop: 18 }}>
          <button className="primary-btn" onClick={save} disabled={saving}>
            {saving ? "Saving..." : "Save Voice Settings"}
          </button>
        </div>
      </section>

      <section className="grid two-col">
        <div className="panel">
          <h2 className="panel-title">Recent calls</h2>
          <p className="panel-subtitle">Phone calls and widget voice chats. Click one for the transcript.</p>
          {calls.length === 0 ? (
            <p className="panel-subtitle">No calls yet.</p>
          ) : (
            <div className="voice-list">
              {calls.map((c) => (
                <button key={c.id} className={`voice-item ${selected?.id === c.id ? "voice-item-active" : ""}`} onClick={() => openCall(c.id)}>
                  <div className="voice-item-top">
                    <span>
                      {c.channel === "web" ? "🌐 Website voice" : c.direction === "outbound" ? "↗ Callback" : "📞 Incoming"}
                      {c.channel === "phone" && <span className="voice-muted"> · {c.direction === "outbound" ? c.to_number : c.from_number}</span>}
                    </span>
                    <span className={`voice-badge voice-${c.status}`}>{c.status.replace("_", " ")}</span>
                  </div>
                  <div className="voice-muted">
                    {pretty(c.outcome)} · {c.duration_seconds != null ? `${c.duration_seconds}s` : "—"} ·{" "}
                    {c.started_at ? new Date(c.started_at).toLocaleString() : ""}
                  </div>
                  {c.summary && <div className="voice-summary">{c.summary}</div>}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="panel">
          <h2 className="panel-title">{selected ? `Call #${selected.id}` : "Transcript"}</h2>
          {!selected ? (
            <p className="panel-subtitle">Select a call to see what was said and which actions the AI took.</p>
          ) : (
            <>
              {selected.summary && <p className="panel-subtitle">{selected.summary}</p>}
              {!!selected.tool_events?.length && (
                <div className="voice-tools">
                  {selected.tool_events.map((t, i) => (
                    <span key={i} className={`voice-badge ${t.ok ? "voice-completed" : "voice-failed"}`}>
                      {pretty(t.name)}
                    </span>
                  ))}
                </div>
              )}
              <div className="voice-transcript">
                {(selected.transcript || []).length === 0 && <p className="panel-subtitle">No conversation recorded.</p>}
                {(selected.transcript || []).map((t, i) => (
                  <div key={i} className={`voice-line voice-line-${t.role}`}>
                    <span className="voice-muted">{t.role === "assistant" ? "AI" : "Customer"}</span>
                    <span>{t.text}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </section>

      <section className="panel">
        <h2 className="panel-title">Callback queue</h2>
        <div className="voice-row voice-row-manual">
          <input className="key-input" placeholder="Phone (+1555…)" value={manual.phone} onChange={(e) => setManual({ ...manual, phone: e.target.value })} />
          <input className="key-input" placeholder="Name (optional)" value={manual.name} onChange={(e) => setManual({ ...manual, name: e.target.value })} />
          <input className="key-input" placeholder="What it's about (optional)" value={manual.context} onChange={(e) => setManual({ ...manual, context: e.target.value })} />
          <button className="ghost-btn" onClick={scheduleManual} disabled={!manual.phone.trim()}>
            Have AI call now
          </button>
        </div>
        {callbacks.length === 0 ? (
          <p className="panel-subtitle">No callbacks queued.</p>
        ) : (
          <div className="voice-list" style={{ marginTop: 14 }}>
            {callbacks.map((cb) => (
              <div key={cb.id} className="voice-item">
                <div className="voice-item-top">
                  <span>
                    {cb.name ? `${cb.name} · ` : ""}
                    {cb.phone}
                    <span className="voice-muted"> · {pretty(cb.reason)}</span>
                  </span>
                  <span className={`voice-badge voice-${cb.status}`}>{cb.status.replace("_", " ")}</span>
                </div>
                <div className="voice-muted">
                  Attempts {cb.attempts}/{cb.max_attempts}
                  {cb.status === "pending" && cb.next_attempt_at && ` · next ${new Date(cb.next_attempt_at).toLocaleString()}`}
                  {cb.last_error && ` · ${cb.last_error}`}
                </div>
                {cb.context && <div className="voice-summary">{cb.context}</div>}
                {cb.status === "pending" && (
                  <button className="ghost-btn small-btn" style={{ marginTop: 8 }} onClick={() => cancel(cb.id)}>
                    Cancel
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <style jsx global>{`
        .voice-stats {
          display: grid;
          grid-template-columns: repeat(6, minmax(0, 1fr));
          gap: 12px;
          margin-bottom: 16px;
        }
        .voice-stat {
          background: #f8fafc;
          border-radius: 18px;
          padding: 14px 16px;
          border: 1px solid rgba(15, 23, 42, 0.08);
        }
        .voice-stat-label {
          color: #475569;
          font-size: 12px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.06em;
        }
        .voice-stat-value {
          color: #0f172a;
          font-size: 26px;
          font-weight: 800;
          margin-top: 6px;
        }
        .voice-setup {
          display: flex;
          flex-wrap: wrap;
          gap: 10px;
          margin-bottom: 14px;
        }
        .voice-setup-item {
          border-radius: 999px;
          padding: 8px 14px;
          font-size: 13px;
          font-weight: 600;
          border: 1px solid rgba(148, 163, 184, 0.25);
        }
        .voice-ok {
          color: #bbf7d0;
          background: rgba(34, 197, 94, 0.12);
        }
        .voice-missing {
          color: #fde68a;
          background: rgba(245, 158, 11, 0.12);
        }
        .voice-webhooks {
          display: grid;
          gap: 8px;
        }
        .voice-webhook {
          display: grid;
          grid-template-columns: 200px 1fr auto;
          gap: 10px;
          align-items: center;
        }
        .voice-code {
          background: #06101f;
          border: 1px solid rgba(96, 165, 250, 0.18);
          border-radius: 12px;
          padding: 10px 12px;
          font-size: 13px;
          word-break: break-all;
        }
        .voice-form {
          display: grid;
          gap: 14px;
          margin-top: 16px;
        }
        .voice-row {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 12px;
        }
        .voice-row-3 {
          grid-template-columns: repeat(3, minmax(0, 1fr));
        }
        .voice-row-4 {
          grid-template-columns: repeat(4, minmax(0, 1fr));
        }
        .voice-row-manual {
          grid-template-columns: 1fr 1fr 2fr auto;
          margin-top: 12px;
        }
        .voice-toggle {
          display: flex;
          align-items: center;
          gap: 10px;
          color: #dbeafe;
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
        }
        .voice-toggle input {
          width: 18px;
          height: 18px;
          accent-color: #3b82f6;
        }
        .voice-textarea {
          min-height: 90px;
          resize: vertical;
          font-family: inherit;
        }
        .voice-list {
          display: grid;
          gap: 10px;
          max-height: 520px;
          overflow-y: auto;
        }
        .voice-item {
          text-align: left;
          width: 100%;
          background: rgba(8, 15, 28, 0.55);
          border: 1px solid rgba(148, 163, 184, 0.12);
          border-radius: 16px;
          padding: 12px 14px;
          color: #f8fafc;
          font: inherit;
          cursor: pointer;
        }
        div.voice-item {
          cursor: default;
        }
        .voice-item-active {
          border-color: rgba(96, 165, 250, 0.6);
        }
        .voice-item-top {
          display: flex;
          justify-content: space-between;
          gap: 10px;
          font-weight: 700;
        }
        .voice-muted {
          color: #94a3b8;
          font-size: 13px;
          font-weight: 500;
        }
        .voice-summary {
          margin-top: 6px;
          color: #cbd5e1;
          font-size: 13px;
          line-height: 1.5;
        }
        .voice-badge {
          border-radius: 999px;
          padding: 4px 10px;
          font-size: 11px;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: 0.05em;
          white-space: nowrap;
          background: rgba(148, 163, 184, 0.14);
          color: #e2e8f0;
          height: fit-content;
        }
        .voice-completed {
          background: rgba(34, 197, 94, 0.15);
          color: #bbf7d0;
        }
        .voice-missed,
        .voice-failed {
          background: rgba(239, 68, 68, 0.14);
          color: #fecaca;
        }
        .voice-pending,
        .voice-dialing,
        .voice-in_progress,
        .voice-ai_active,
        .voice-ringing,
        .voice-forwarded {
          background: rgba(59, 130, 246, 0.16);
          color: #bfdbfe;
        }
        .voice-voicemail {
          background: rgba(245, 158, 11, 0.16);
          color: #fde68a;
        }
        .voice-tools {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
          margin: 12px 0;
        }
        .voice-transcript {
          display: grid;
          gap: 8px;
          max-height: 460px;
          overflow-y: auto;
          margin-top: 12px;
        }
        .voice-line {
          display: grid;
          gap: 2px;
          padding: 10px 12px;
          border-radius: 14px;
          background: rgba(8, 15, 28, 0.55);
          line-height: 1.5;
        }
        .voice-line-assistant {
          background: rgba(59, 130, 246, 0.12);
        }
        @media (max-width: 1100px) {
          .voice-stats {
            grid-template-columns: repeat(3, minmax(0, 1fr));
          }
          .voice-row-4,
          .voice-row-manual {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }
        @media (max-width: 720px) {
          .voice-stats,
          .voice-row,
          .voice-row-3,
          .voice-row-4,
          .voice-row-manual,
          .voice-webhook {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="voice-stat">
      <div className="voice-stat-label">{label}</div>
      <div className="voice-stat-value">{value}</div>
    </div>
  );
}

function SetupItem({ ok, label, hint }: { ok: boolean; label: string; hint: string }) {
  return (
    <span className={`voice-setup-item ${ok ? "voice-ok" : "voice-missing"}`} title={ok ? "Configured" : hint}>
      {ok ? "✓" : "!"} {label}
      {!ok && <span style={{ fontWeight: 500 }}> — {hint}</span>}
    </span>
  );
}

function WebhookRow({ label, url, onCopy }: { label: string; url: string; onCopy: (t: string) => void }) {
  return (
    <div className="voice-webhook">
      <span className="voice-muted">{label}</span>
      <code className="voice-code">{url}</code>
      <button className="ghost-btn small-btn" onClick={() => onCopy(url)}>
        Copy
      </button>
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="voice-toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="input-block">
      <label className="input-label">{label}</label>
      {children}
    </div>
  );
}

function pretty(v: string | null | undefined) {
  if (!v) return "—";
  return v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
