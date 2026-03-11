(function () {
  function loadCss(cssHref) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = cssHref;
    document.head.appendChild(link);
  }

  function createMessage(container, text, sender) {
    const wrap = document.createElement("div");
    wrap.className = `ai-agent-message ${sender}`;

    const bubble = document.createElement("div");
    bubble.className = "ai-agent-bubble-text";
    bubble.textContent = text;

    wrap.appendChild(bubble);
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
  }

  function clearActions(actionsEl) {
    actionsEl.innerHTML = "";
  }

  function renderActions(actionsEl, actions) {
    clearActions(actionsEl);

    if (!actions || !actions.length) return;

    actions.forEach((action) => {
      if (action.type === "open_calendly" && action.url) {
        const link = document.createElement("a");
        link.href = action.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.className = "ai-agent-action-link";
        link.textContent = "Book appointment";
        actionsEl.appendChild(link);
      }

      if (action.type === "lead_created") {
        const note = document.createElement("div");
        note.className = "ai-agent-action-link";
        note.textContent = "Your request was saved";
        actionsEl.appendChild(note);
      }

      if (action.type === "callback_requested") {
        const note = document.createElement("div");
        note.className = "ai-agent-action-link";
        note.textContent = "Callback requested";
        actionsEl.appendChild(note);
      }
    });
  }

  function buildWidget(config) {
    const root = document.createElement("div");
    root.id = "ai-agent-widget-root";

    const bubble = document.createElement("button");
    bubble.className = "ai-agent-bubble";
    bubble.type = "button";
    bubble.innerHTML = "💬";

    const panel = document.createElement("div");
    panel.className = "ai-agent-panel";

    const header = document.createElement("div");
    header.className = "ai-agent-header";
    header.textContent = config.title || "Ask us anything";

    const status = document.createElement("div");
    status.className = "ai-agent-status";
    status.textContent = "AI assistant is online";

    const messages = document.createElement("div");
    messages.className = "ai-agent-messages";

    const actions = document.createElement("div");
    actions.className = "ai-agent-actions";

    const footer = document.createElement("div");
    footer.className = "ai-agent-footer";

    const input = document.createElement("input");
    input.className = "ai-agent-input";
    input.type = "text";
    input.placeholder = config.placeholder || "Type your question...";

    const send = document.createElement("button");
    send.className = "ai-agent-send";
    send.type = "button";
    send.textContent = "Send";

    footer.appendChild(input);
    footer.appendChild(send);

    panel.appendChild(header);
    panel.appendChild(status);
    panel.appendChild(messages);
    panel.appendChild(actions);
    panel.appendChild(footer);

    root.appendChild(bubble);
    root.appendChild(panel);
    document.body.appendChild(root);

    createMessage(
      messages,
      config.welcomeMessage || "Hi! How can I help you today?",
      "bot"
    );

    function setPosition(position) {
      const isLeft = position === "left";
      bubble.style.left = isLeft ? "20px" : "";
      bubble.style.right = isLeft ? "" : "20px";

      panel.style.left = isLeft ? "20px" : "";
      panel.style.right = isLeft ? "" : "20px";
    }

    setPosition(config.position || "right");

    bubble.addEventListener("click", function () {
      panel.style.display = panel.style.display === "block" ? "none" : "block";
    });

    async function sendMessage() {
      const text = input.value.trim();
      if (!text) return;

      createMessage(messages, text, "user");
      input.value = "";
      send.disabled = true;
      status.textContent = "Thinking...";

      clearActions(actions);

      try {
        const res = await fetch(`${config.apiBase}/v1/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-API-Key": config.apiKey,
          },
          body: JSON.stringify({
            message: text,
            session_id: config.sessionId || "demo-session",
          }),
        });

        if (!res.ok) {
          const errText = await res.text();
          throw new Error(`HTTP ${res.status}: ${errText}`);
        }

        const data = await res.json();
        createMessage(messages, data.answer || "No response received.", "bot");
        renderActions(actions, data.actions || []);
        status.textContent = "AI assistant is online";
      } catch (err) {
        createMessage(
          messages,
          "Sorry, the assistant is temporarily unavailable.",
          "bot"
        );
        status.textContent = "Connection issue";
        console.error("[AIAgentWidget]", err);
      } finally {
        send.disabled = false;
      }
    }

    send.addEventListener("click", sendMessage);

    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        sendMessage();
      }
    });
  }

  window.AIAgentWidget = {
    init: function (config) {
      if (!config || !config.apiBase || !config.apiKey) {
        console.error("AIAgentWidget.init requires apiBase and apiKey");
        return;
      }

      const currentScript =
        document.currentScript ||
        Array.from(document.getElementsByTagName("script")).slice(-1)[0];

      let cssPath = "";
      if (currentScript && currentScript.src) {
        cssPath = currentScript.src.replace(/widget\.js(\?.*)?$/, "widget.css");
      }

      if (cssPath) loadCss(cssPath);
      buildWidget(config);
    },
  };
})();