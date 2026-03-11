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
  const send = root.querySelector("button");
  const quick = root.querySelector(".ai-quick");

  let sessionId = "sess_" + Date.now();

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

  async function loadConfig() {
    const r = await fetch(`${apiBase}/v1/widget/config?widget_key=${tenantKey}`);
    const cfg = await r.json();
    root.querySelector(".ai-title").innerText = cfg.tenant_name;
    addMessage(cfg.welcome_message, "bot");
    renderQuickReplies(["Book appointment", "Services", "Pricing"]);
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

          if (payload.type === "done" && payload.actions) {
            payload.actions.forEach((a) => {
              if (a.type === "open_calendly" && a.url) {
                const link = document.createElement("a");
                link.href = a.url;
                link.target = "_blank";
                link.className = "booking-btn";
                link.textContent = "Book Appointment";
                messages.appendChild(link);
              }
            });
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