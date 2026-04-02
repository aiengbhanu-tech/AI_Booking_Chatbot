(function () {
  const script =
    document.currentScript ||
    Array.from(document.getElementsByTagName("script")).find((s) =>
      (s.src || "").includes("/widget/widget.js")
    ) ||
    Array.from(document.getElementsByTagName("script")).find((s) =>
      (s.src || "").includes("widget.js")
    );

  if (!script) {
    console.error("Widget script tag not found");
    return;
  }

  const tenantKey = script.getAttribute("data-tenant-key");
  const apiBase = script.getAttribute("data-api-base") || "http://localhost:8000";
  const position = script.getAttribute("data-position") || "right";

  if (!tenantKey) {
    console.error("Widget requires data-tenant-key");
    return;
  }

  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = script.src.replace("widget.js", "widget.css");
  document.head.appendChild(css);

  const root = document.createElement("div");
  root.id = "ai-chat-widget";
  root.className = position === "left" ? "position-left" : "position-right";

  root.innerHTML = `
    <button class="ai-bubble" aria-label="Open chat">
      <span class="ai-bubble-icon">💬</span>
    </button>

    <section class="ai-panel" aria-live="polite">
      <div class="ai-header">
        <div class="ai-header-main">
          <div class="ai-avatar">AI</div>
          <div>
            <div class="ai-title">Assistant</div>
            <div class="ai-status">Online now</div>
          </div>
        </div>
        <button class="ai-close" aria-label="Close chat">×</button>
      </div>

      <div class="ai-messages"></div>

      <div class="ai-quick"></div>

      <div class="ai-form-wrap" style="display:none;"></div>

      <div class="ai-input-wrap">
        <div class="ai-input">
          <input placeholder="Ask a question..." />
          <button class="ai-send-btn">Send</button>
        </div>
        <div class="ai-footer-note">Powered by your website AI assistant</div>
      </div>
    </section>
  `;

  document.body.appendChild(root);

  const bubble = root.querySelector(".ai-bubble");
  const panel = root.querySelector(".ai-panel");
  const close = root.querySelector(".ai-close");
  const titleEl = root.querySelector(".ai-title");
  const statusEl = root.querySelector(".ai-status");
  const messages = root.querySelector(".ai-messages");
  const input = root.querySelector(".ai-input input");
  const send = root.querySelector(".ai-send-btn");
  const quick = root.querySelector(".ai-quick");
  const formWrap = root.querySelector(".ai-form-wrap");

  let sessionId = "sess_" + Date.now();
  let currentIntent = "inquiry";
  let tenantConfig = null;
  let submittingLead = false;

  // UX improvement: remember if this visitor already submitted details
  let leadSubmitted = false;
  let leadProfile = {
    name: "",
    phone: "",
    email: "",
  };

  bubble.addEventListener("click", () => {
    panel.classList.toggle("open");
    if (panel.classList.contains("open")) {
      setTimeout(() => input.focus(), 120);
    }
  });

  close.addEventListener("click", () => {
    panel.classList.remove("open");
  });

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function scrollMessagesToBottom() {
    messages.scrollTop = messages.scrollHeight;
  }

  function scrollFormToTop() {
    formWrap.scrollTop = 0;
  }

  function addMessage(text, cls, options = {}) {
    const wrap = document.createElement("div");
    wrap.className = `msg-row ${cls}`;

    const bubbleEl = document.createElement("div");
    bubbleEl.className = `msg ${cls}`;
    bubbleEl.textContent = text || "";

    if (options.small) bubbleEl.classList.add("small");

    wrap.appendChild(bubbleEl);
    messages.appendChild(wrap);
    scrollMessagesToBottom();
    return bubbleEl;
  }

  function addTyping() {
    const row = document.createElement("div");
    row.className = "msg-row bot";

    const el = document.createElement("div");
    el.className = "msg bot typing";
    el.innerHTML = `<span></span><span></span><span></span>`;

    row.appendChild(el);
    messages.appendChild(row);
    scrollMessagesToBottom();
    return row;
  }

  function clearQuickReplies() {
    quick.innerHTML = "";
  }

  function renderQuickReplies(items) {
    clearQuickReplies();

    items.forEach((label) => {
      const btn = document.createElement("button");
      btn.className = "quick-btn";
      btn.textContent = label;

      btn.onclick = () => {
        if (label === "Leave Details") {
          renderLeadForm("inquiry", "Leave your details and the clinic will contact you.");
          return;
        }
        sendMessage(label);
      };

      quick.appendChild(btn);
    });
  }

  function createActionCard(title, text, buttons = []) {
    const card = document.createElement("div");
    card.className = "action-card";

    const cardTitle = document.createElement("div");
    cardTitle.className = "action-card-title";
    cardTitle.textContent = title;

    const cardText = document.createElement("div");
    cardText.className = "action-card-text";
    cardText.textContent = text;

    card.appendChild(cardTitle);
    card.appendChild(cardText);

    if (buttons.length) {
      const row = document.createElement("div");
      row.className = "action-card-buttons";

      buttons.forEach((btnDef) => {
        const btn = document.createElement(btnDef.href ? "a" : "button");
        btn.className = btnDef.primary ? "action-btn primary" : "action-btn";

        if (btnDef.href) {
          btn.href = btnDef.href;
          btn.target = "_blank";
          btn.rel = "noopener noreferrer";
        } else if (btnDef.onClick) {
          btn.addEventListener("click", btnDef.onClick);
          btn.type = "button";
        }

        btn.textContent = btnDef.label;
        row.appendChild(btn);
      });

      card.appendChild(row);
    }

    messages.appendChild(card);
    scrollMessagesToBottom();
  }

  function renderLeadForm(intent = "inquiry", helperText = "Leave your details and we’ll get back to you.") {
    currentIntent = intent;
    formWrap.style.display = "block";

    formWrap.innerHTML = `
      <div class="lead-form-card">
        <div class="lead-form-title">
          ${intent === "appointment" ? "Request Appointment" : intent === "callback" ? "Request Callback" : "Request Information"}
        </div>
        <div class="lead-form-helper">${helperText}</div>

        <div class="lead-grid">
          <input class="lead-input" id="lead-name" placeholder="Your name" value="${escapeHtml(leadProfile.name)}" />
          <input class="lead-input" id="lead-phone" placeholder="Phone number" value="${escapeHtml(leadProfile.phone)}" />
        </div>

        <div class="lead-grid">
          <input class="lead-input" id="lead-email" placeholder="Email (optional)" value="${escapeHtml(leadProfile.email)}" />
          <input class="lead-input" id="lead-time" placeholder="Preferred time (optional)" />
        </div>

        <textarea class="lead-input lead-textarea" id="lead-notes" placeholder="Any notes"></textarea>

        <div class="lead-form-actions">
          <button class="lead-submit" type="button">Submit Request</button>
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

    scrollFormToTop();
  }

  async function submitLead() {
    if (submittingLead) return;

    const name = formWrap.querySelector("#lead-name").value.trim();
    const phone = formWrap.querySelector("#lead-phone").value.trim();
    const email = formWrap.querySelector("#lead-email").value.trim();
    const time = formWrap.querySelector("#lead-time").value.trim();
    const notes = formWrap.querySelector("#lead-notes").value.trim();
    const status = formWrap.querySelector(".lead-status");
    const submitBtn = formWrap.querySelector(".lead-submit");

    if (!name || !phone) {
      status.textContent = "Please enter your name and phone number.";
      status.className = "lead-status error";
      return;
    }

    try {
      submittingLead = true;
      submitBtn.disabled = true;
      submitBtn.textContent = "Submitting...";

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

      // remember user details for this session
      leadSubmitted = true;
      leadProfile = { name, phone, email };

      status.textContent = "Thanks! Your request has been submitted.";
      status.className = "lead-status success";

      addMessage(
        "Thanks! Your details have been submitted. Someone from the clinic should contact you soon.",
        "bot",
        { small: true }
      );

      setTimeout(() => {
        formWrap.style.display = "none";
        formWrap.innerHTML = "";
      }, 1200);
    } catch (err) {
      console.error(err);
      status.textContent = "Could not submit right now. Please try again.";
      status.className = "lead-status error";
    } finally {
      submittingLead = false;
      submitBtn.disabled = false;
      submitBtn.textContent = "Submit Request";
    }
  }

  async function loadConfig() {
    try {
      const r = await fetch(`${apiBase}/v1/widget/config?widget_key=${encodeURIComponent(tenantKey)}`);
      const cfg = await r.json();

      if (!r.ok) {
        throw new Error(cfg.detail || "Failed to load config");
      }

      tenantConfig = cfg;
      titleEl.textContent = cfg.tenant_name || "Assistant";

      addMessage(
        cfg.welcome_message || "Hi! How can I help you today?",
        "bot"
      );

      renderQuickReplies([
        "Book Appointment",
        "Pricing",
        "Location",
        "Call Me"
      ]);
    } catch (e) {
      console.error("Widget config error:", e);
      titleEl.textContent = "Assistant";
      setStatus("Unavailable");
      addMessage("Assistant temporarily unavailable.", "bot");
    }
  }

  function handleActions(actions, userText) {
    if (!actions || !actions.length) return;

    actions.forEach((a) => {
      if (a.type === "open_calendly" && a.url) {
        createActionCard(
          "Book a consultation",
          "Choose a convenient time directly from the clinic booking page.",
          [
            { label: "Book Appointment", href: a.url, primary: true },
            leadSubmitted
              ? {
                  label: "Details Already Shared",
                  onClick: () =>
                    addMessage(
                      "We already have your details on this chat. The clinic can follow up with you if needed.",
                      "bot",
                      { small: true }
                    )
                }
              : {
                  label: "Leave Details",
                  onClick: () =>
                    renderLeadForm(
                      "appointment",
                      "Prefer a callback instead? Leave your details and the clinic can contact you."
                    )
                }
          ]
        );
      }

      if (a.type === "show_lead_form") {
        // UX rule: only auto-open form for appointment/callback if not already submitted
        const shouldAutoOpen =
          !leadSubmitted && (a.intent === "appointment" || a.intent === "callback");

        if (shouldAutoOpen) {
          renderLeadForm(
            a.intent || "inquiry",
            a.message || "Leave your details and the clinic will contact you."
          );
        } else if (leadSubmitted) {
          createActionCard(
            "Your details are already saved",
            "We already have your details in this chat session. The clinic can follow up with you if needed."
          );
        } else {
          createActionCard(
            a.intent === "pricing" ? "Need exact pricing?" : "Need more help?",
            a.message || "Leave your details and the clinic will contact you.",
            [
              {
                label: "Open Form",
                onClick: () =>
                  renderLeadForm(
                    a.intent || "inquiry",
                    a.message || "Leave your details and the clinic will contact you."
                  ),
                primary: true
              }
            ]
          );
        }
      }

      if (a.type === "callback_suggested") {
        if (leadSubmitted) {
          createActionCard(
            "Callback request",
            "Your details are already available in this chat session. The clinic can follow up with you if needed."
          );
        } else {
          createActionCard(
            "Request a callback",
            a.message || "Leave your phone number and preferred time for a callback.",
            [
              {
                label: "Open Callback Form",
                onClick: () =>
                  renderLeadForm(
                    "callback",
                    "Share your name, phone number, and preferred time for a callback."
                  ),
                primary: true
              }
            ]
          );
        }
      }

      if (a.type === "pricing_suggested") {
        createActionCard(
          "Get exact pricing",
          a.message || "Pricing can vary by treatment. You can request a consultation for exact pricing.",
          leadSubmitted
            ? [
                {
                  label: "Details Already Shared",
                  onClick: () =>
                    addMessage(
                      "We already have your details. The clinic can contact you with more pricing information if needed.",
                      "bot",
                      { small: true }
                    )
                }
              ]
            : [
                {
                  label: "Request Pricing Help",
                  onClick: () =>
                    renderLeadForm(
                      "pricing",
                      "Leave your details and the clinic can help with exact pricing."
                    ),
                  primary: true
                }
              ]
        );
      }

      if (a.type === "location_suggested") {
        createActionCard(
          "Location details",
          a.message || "You can ask for address and directions information here."
        );
      }
    });
  }

  async function sendMessage(text) {
    text = text || input.value.trim();
    if (!text) return;

    addMessage(text, "user");
    input.value = "";
    send.disabled = true;
    setStatus("Thinking...");

    const typingRow = addTyping();

    try {
      const url =
        `${apiBase}/v1/widget/chat/stream?widget_key=${encodeURIComponent(tenantKey)}` +
        `&message=${encodeURIComponent(text)}` +
        `&session_id=${encodeURIComponent(sessionId)}`;

      const res = await fetch(url, { method: "GET" });
      if (!res.ok || !res.body) {
        throw new Error("Streaming failed");
      }

      typingRow.remove();
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
            scrollMessagesToBottom();
          }

          if (payload.type === "done") {
            setStatus("Online now");
            handleActions(payload.actions || [], text);
          }

          if (payload.type === "error") {
            botEl.textContent = payload.message || "Assistant unavailable";
            setStatus("Unavailable");
          }
        }
      }
    } catch (e) {
      typingRow.remove();
      addMessage("Assistant temporarily unavailable.", "bot");
      setStatus("Unavailable");
      console.error(e);
    } finally {
      send.disabled = false;
      setTimeout(() => setStatus("Online now"), 900);
    }
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  send.onclick = () => sendMessage();

  input.onkeypress = (e) => {
    if (e.key === "Enter") sendMessage();
  };

  loadConfig();
})();