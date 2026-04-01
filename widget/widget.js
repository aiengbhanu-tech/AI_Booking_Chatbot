(function () {
  const script = document.currentScript;
  const tenantKey = script.getAttribute("data-tenant-key");
  const apiBase = script.getAttribute("data-api-base") || "http://localhost:8000";

  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = script.src.replace("widget.js", "widget.css");
  document.head.appendChild(css);

  if (!tenantKey) {
    console.error("Widget requires data-tenant-key");
    return;
  }

  const root = document.createElement("div");
  root.id = "ai-chat-widget";
  root.innerHTML = `
    <div class="ai-bubble">💬</div>
    <div class="ai-panel">
      <div class="ai-header">
        <span class="ai-title">Assistant</span>
        <span class="ai-close">×</span>
      </div>
      <div class="ai-messages"></div>
      <div class="ai-quick"></div>
      <div class="ai-form-wrap" style="display:none;"></div>
      <div class="ai-input">
        <input placeholder="Ask a question..." />
        <button>Send</button>
      </div>
    </div>
  `;
  document.body.appendChild(root);

  const bubble = root.querySelector(".ai-bubble");
  const panel = root.querySelector(".ai-panel");
  const close = root.querySelector(".ai-close");
  const messages = root.querySelector(".ai-messages");
  const input = root.querySelector("input");
  const send = root.querySelector(".ai-input button");
  const quick = root.querySelector(".ai-quick");
  const formWrap = root.querySelector(".ai-form-wrap");

  let sessionId = "sess_" + Date.now();
  let currentIntent = "inquiry";

  bubble.onclick = () => panel.classList.toggle("open");
  close.onclick = () => panel.classList.remove("open");

  function addMessage(text, cls) {
    const m = document.createElement("div");
    m.className = "msg " + cls;
    m.textContent = text;
    messages.appendChild(m);
    messages.scrollTop = messages.scrollHeight;
    return m;
  }

  function addTyping() {
    const el = document.createElement("div");
    el.className = "msg bot typing";
    el.innerHTML = `<span></span><span></span><span></span>`;
    messages.appendChild(el);
    messages.scrollTop = messages.scrollHeight;
    return el;
  }

  function renderQuickReplies(items) {
    quick.innerHTML = "";
    items.forEach((label) => {
      const btn = document.createElement("button");
      btn.className = "quick-btn";
      btn.textContent = label;
      btn.onclick = () => sendMessage(label);
      quick.appendChild(btn);
    });
  }

  function renderLeadForm(intent = "inquiry", helperText = "Leave your details and we’ll get back to you.") {
    currentIntent = intent;
    formWrap.style.display = "block";
    formWrap.innerHTML = `
      <div class="lead-form-card">
        <div class="lead-form-title">Request ${intent === "appointment" ? "Appointment" : intent === "callback" ? "Callback" : "Information"}</div>
        <div class="lead-form-helper">${helperText}</div>
        <input class="lead-input" id="lead-name" placeholder="Your name" />
        <input class="lead-input" id="lead-phone" placeholder="Phone number" />
        <input class="lead-input" id="lead-email" placeholder="Email (optional)" />
        <input class="lead-input" id="lead-time" placeholder="Preferred time (optional)" />
        <textarea class="lead-input lead-textarea" id="lead-notes" placeholder="Any notes"></textarea>
        <div class="lead-form-actions">
          <button class="lead-submit">Submit</button>
          <button class="lead-cancel" type="button">Cancel</button>
        </div>
        <div class="lead-status"></div>
      </div>
    `;

    formWrap.querySelector(".lead-cancel").onclick = () => {
      formWrap.style.display = "none";
      formWrap.innerHTML = "";
    };

    formWrap.querySelector(".lead-submit").onclick = submitLead;
  }

  async function submitLead() {
    const name = formWrap.querySelector("#lead-name").value.trim();
    const phone = formWrap.querySelector("#lead-phone").value.trim();
    const email = formWrap.querySelector("#lead-email").value.trim();
    const time = formWrap.querySelector("#lead-time").value.trim();
    const notes = formWrap.querySelector("#lead-notes").value.trim();
    const status = formWrap.querySelector(".lead-status");

    if (!name || !phone) {
      status.textContent = "Please enter at least your name and phone number.";
      status.className = "lead-status error";
      return;
    }

    try {
      const res = await fetch(`${apiBase}/v1/widget/lead`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          widget_key: tenantKey,
          session_id: sessionId,
          name,
          phone,
          email,
          intent: currentIntent,
          notes: [time ? `Preferred time: ${time}` : "", notes].filter(Boolean).join(" | ")
        })
      });

      const data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.detail || "Lead submission failed");
      }

      status.textContent = "Thanks! Your request has been submitted.";
      status.className = "lead-status success";

      addMessage("Thanks! Your details have been submitted. Someone will reach out to you soon.", "bot");

      setTimeout(() => {
        formWrap.style.display = "none";
        formWrap.innerHTML = "";
      }, 1200);

    } catch (err) {
      console.error(err);
      status.textContent = "Could not submit right now. Please try again.";
      status.className = "lead-status error";
    }
  }

  async function loadConfig() {
    const r = await fetch(`${apiBase}/v1/widget/config?widget_key=${tenantKey}`);
    const cfg = await r.json();
    root.querySelector(".ai-title").innerText = cfg.tenant_name;
    addMessage(cfg.welcome_message, "bot");
    renderQuickReplies(["Book Appointment", "Pricing", "Location", "Call Me"]);
  }

  function handleActions(actions) {
    if (!actions || !actions.length) return;

    actions.forEach((a) => {
      if (a.type === "open_calendly" && a.url) {
        const link = document.createElement("a");
        link.href = a.url;
        link.target = "_blank";
        link.className = "booking-btn";
        link.textContent = "Book Appointment";
        messages.appendChild(link);
      }

      if (a.type === "show_lead_form") {
        renderLeadForm(a.intent || "inquiry", a.message || "Leave your details and we’ll contact you.");
      }
    });

    messages.scrollTop = messages.scrollHeight;
  }

  async function sendMessage(text) {
    text = text || input.value.trim();
    if (!text) return;

    addMessage(text, "user");
    input.value = "";
    send.disabled = true;

    const typingEl = addTyping();

    try {
      const url =
        `${apiBase}/v1/widget/chat/stream?widget_key=${encodeURIComponent(tenantKey)}` +
        `&message=${encodeURIComponent(text)}` +
        `&session_id=${encodeURIComponent(sessionId)}`;

      const res = await fetch(url, { method: "GET" });
      if (!res.ok || !res.body) {
        throw new Error("Streaming failed");
      }

      typingEl.remove();
      const botEl = addMessage("", "bot");

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          if (!part.startsWith("data: ")) continue;
          const payload = JSON.parse(part.slice(6));

          if (payload.type === "token") {
            botEl.textContent += payload.content;
            messages.scrollTop = messages.scrollHeight;
          }

          if (payload.type === "done") {
            handleActions(payload.actions || []);
          }

          if (payload.type === "error") {
            botEl.textContent = payload.message || "Assistant unavailable";
          }
        }
      }
    } catch (e) {
      typingEl.remove();
      addMessage("Assistant temporarily unavailable.", "bot");
      console.error(e);
    } finally {
      send.disabled = false;
    }
  }

  send.onclick = () => sendMessage();
  input.onkeypress = (e) => {
    if (e.key === "Enter") sendMessage();
  };

  loadConfig();
})();