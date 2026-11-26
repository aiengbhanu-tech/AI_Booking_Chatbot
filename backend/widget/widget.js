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

      <div class="ai-voice-bar" style="display:none;">
        <span class="ai-voice-dot"></span>
        <span class="ai-voice-state">Connecting…</span>
        <span class="ai-voice-timer"></span>
        <button class="ai-voice-end" type="button">End voice</button>
      </div>

      <div class="ai-input-wrap">
        <div class="ai-input">
          <input placeholder="Ask a question..." />
          <button class="ai-voice-btn" type="button" aria-label="Talk to the assistant" title="Talk to the assistant" style="display:none;">🎤</button>
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
  const voiceBtn = root.querySelector(".ai-voice-btn");
  const voiceBar = root.querySelector(".ai-voice-bar");
  const voiceStateEl = root.querySelector(".ai-voice-state");
  const voiceTimerEl = root.querySelector(".ai-voice-timer");
  const voiceEndBtn = root.querySelector(".ai-voice-end");

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
    if (voice) endVoice("closed");
    endBrowserVoice();
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

      voiceMode = cfg.voice_mode || (cfg.voice_enabled ? "realtime" : "off");
      if (voiceMode === "realtime" && !rtcSupported) voiceMode = "browser";
      if (cfg.voice_enabled && ((voiceMode === "realtime" && rtcSupported) || browserVoiceSupported)) {
        voiceBtn.style.display = "";
      }

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
    if (!text) return "";
    let finalAnswer = "";

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
            finalAnswer = payload.answer || botEl.textContent;
            handleActions(payload.actions || [], text);
          }

          if (payload.type === "error") {
            botEl.textContent = payload.message || "Assistant unavailable";
            finalAnswer = botEl.textContent;
            setStatus("Unavailable");
          }
        }
      }
    } catch (e) {
      typingRow.remove();
      addMessage("Assistant temporarily unavailable.", "bot");
      setStatus("Unavailable");
      console.error(e);
      finalAnswer = "Sorry, the assistant is temporarily unavailable.";
    } finally {
      send.disabled = false;
      setTimeout(() => setStatus("Online now"), 900);
    }
    return finalAnswer;
  }

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }



  // -------------------------------------------------------------------
  // Free browser voice: the browser's own speech recognition + speech
  // synthesis drive the normal text chat. No AI voice minutes are used
  // (each turn is an ordinary chat message). Used when the plan's AI voice
  // minutes run out, or when the business picks "browser voice" mode.
  // -------------------------------------------------------------------
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  const rtcSupported = !!(window.RTCPeerConnection && navigator.mediaDevices);
  const browserVoiceSupported = !!(SpeechRec && window.speechSynthesis);
  let voiceMode = "off";
  let bv = null;
  const BV_MAX_IDLE = 3; // stop after 3 silent listening rounds

  if (window.speechSynthesis) {
    window.speechSynthesis.getVoices(); // voices load asynchronously in Chrome
  }

  function bvLang() {
    return navigator.language || "en-US";
  }

  function pickSpeechVoice(lang) {
    const voices = (window.speechSynthesis && window.speechSynthesis.getVoices()) || [];
    const base = lang.split("-")[0];
    return (
      voices.find((x) => x.lang === lang && /natural|google|samantha|aria|jenny/i.test(x.name)) ||
      voices.find((x) => x.lang === lang) ||
      voices.find((x) => (x.lang || "").startsWith(base)) ||
      null
    );
  }

  function speechText(text) {
    return String(text || "")
      .replace(/https?:\/\/\S+/g, "the link in the chat")
      .replace(/[*_#`>\[\]()|]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function startBrowserVoice() {
    if (bv || !browserVoiceSupported) return;
    bv = { rec: null, idle: 0, started: Date.now(), timer: null };
    voiceBar.style.display = "flex";
    voiceBtn.classList.add("active");
    bv.timer = setInterval(() => {
      if (!bv) return;
      const sec = Math.floor((Date.now() - bv.started) / 1000);
      voiceTimerEl.textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
    }, 1000);
    bvListen();
  }

  function bvListen() {
    if (!bv) return;
    const state = bv;
    const rec = new SpeechRec();
    state.rec = rec;
    rec.lang = bvLang();
    rec.interimResults = false;
    rec.continuous = false;
    rec.maxAlternatives = 1;
    let heard = false;

    rec.onresult = async (e) => {
      const said = ((e.results[0] && e.results[0][0] && e.results[0][0].transcript) || "").trim();
      if (!said || bv !== state) return;
      heard = true;
      state.idle = 0;
      setVoiceState("Thinking…");
      const answer = await sendMessage(said);
      if (bv === state) bvSpeak(answer);
    };
    rec.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        addMessage("Microphone access was blocked. You can keep chatting by text.", "bot", { small: true });
        endBrowserVoice();
      }
    };
    rec.onend = () => {
      if (bv !== state || heard) return;
      state.idle += 1;
      if (state.idle >= BV_MAX_IDLE) {
        addMessage("Voice paused. Tap 🎤 to talk again.", "bot", { small: true });
        endBrowserVoice();
        return;
      }
      bvListen();
    };
    setVoiceState("Listening… speak now");
    try { rec.start(); } catch (_) {}
  }

  function bvSpeak(text) {
    if (!bv) return;
    const state = bv;
    const clean = speechText(text);
    if (!clean) { bvListen(); return; }
    // Chrome cuts off long utterances, so speak sentence by sentence
    const parts = clean.match(/[^.!?]+[.!?]*/g) || [clean];
    const lang = bvLang();
    const chosen = pickSpeechVoice(lang);
    window.speechSynthesis.cancel();
    setVoiceState("Speaking… (tap 🎤 to interrupt)", true);
    parts.forEach((part, i) => {
      const u = new SpeechSynthesisUtterance(part.trim());
      u.lang = lang;
      if (chosen) u.voice = chosen;
      u.rate = 1.03;
      if (i === parts.length - 1) {
        u.onend = () => { if (bv === state) bvListen(); };
        u.onerror = u.onend;
      }
      window.speechSynthesis.speak(u);
    });
  }

  function endBrowserVoice() {
    const state = bv;
    if (!state) return;
    bv = null;
    try { state.rec && state.rec.abort(); } catch (_) {}
    try { window.speechSynthesis.cancel(); } catch (_) {}
    clearInterval(state.timer);
    voiceBar.style.display = "none";
    voiceBar.classList.remove("speaking");
    voiceTimerEl.textContent = "";
    voiceBtn.classList.remove("active");
  }

  // -------------------------------------------------------------------
  // Voice mode: browser <-> OpenAI Realtime over WebRTC.
  // The backend creates the session (API key never reaches the browser)
  // and executes tools (knowledge search, leads, appointment requests).
  // -------------------------------------------------------------------
  let voice = null;

  function setVoiceState(text, speaking) {
    voiceStateEl.textContent = text;
    voiceBar.classList.toggle("speaking", !!speaking);
  }

  function voiceSend(evt) {
    if (voice && voice.dc && voice.dc.readyState === "open") {
      voice.dc.send(JSON.stringify(evt));
    }
  }

  async function startVoice() {
    if (voice) return;
    voiceBtn.disabled = true;
    voiceBar.style.display = "flex";
    setVoiceState("Connecting…");

    const v = { transcript: [], started: Date.now(), pc: null, dc: null, stream: null, audio: null, info: null, timer: null, busyTools: 0 };
    voice = v;

    try {
      v.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
      });
      if (voice !== v) { v.stream.getTracks().forEach((t) => t.stop()); return; }
      v.pc = new RTCPeerConnection();
      v.audio = document.createElement("audio");
      v.audio.autoplay = true;
      v.audio.setAttribute("playsinline", "");
      v.pc.ontrack = (e) => { v.audio.srcObject = e.streams[0]; };
      v.stream.getTracks().forEach((t) => v.pc.addTrack(t, v.stream));

      v.dc = v.pc.createDataChannel("oai-events");
      v.dc.onmessage = (e) => {
        try { onVoiceEvent(JSON.parse(e.data)); } catch (err) { console.error(err); }
      };
      v.dc.onopen = () => {
        setVoiceState("Listening…");
        voiceSend({ type: "response.create", response: { instructions: v.info.greeting } });
      };
      v.pc.onconnectionstatechange = () => {
        if (voice === v && ["failed", "disconnected"].includes(v.pc.connectionState)) {
          addMessage("Voice connection lost.", "bot", { small: true });
          endVoice("connection_lost");
        }
      };

      const offer = await v.pc.createOffer();
      await v.pc.setLocalDescription(offer);

      const res = await fetch(`${apiBase}/v1/voice/web/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ widget_key: tenantKey, session_id: sessionId, sdp: offer.sdp })
      });
      const data = await res.json();
      if (res.status === 402) {
        const fallback = new Error("realtime unavailable");
        fallback.useBrowserVoice = true;
        throw fallback;
      }
      if (!res.ok) throw new Error(data.detail || "Voice unavailable");
      v.info = data;
      if (voice !== v) { endSession(v); return; } // user cancelled while connecting
      await v.pc.setRemoteDescription({ type: "answer", sdp: data.sdp });

      const maxMs = (data.max_seconds || 600) * 1000;
      v.timer = setInterval(() => {
        const ms = Date.now() - v.started;
        const sec = Math.floor(ms / 1000);
        voiceTimerEl.textContent = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
        if (ms >= maxMs) {
          addMessage("Voice session time limit reached.", "bot", { small: true });
          endVoice("time_limit");
        }
      }, 1000);
      voiceBtn.classList.add("active");
    } catch (err) {
      if (err && err.useBrowserVoice && browserVoiceSupported) {
        endVoice("fallback");
        voiceMode = "browser";
        startBrowserVoice();
        return;
      }
      console.error("Voice start error:", err);
      const denied = err && (err.name === "NotAllowedError" || err.name === "SecurityError");
      addMessage(
        denied
          ? "Microphone access was blocked. You can keep chatting by text."
          : "Voice isn't available right now. You can keep chatting by text.",
        "bot",
        { small: true }
      );
      endVoice("start_failed");
    } finally {
      voiceBtn.disabled = false;
    }
  }

  async function onVoiceEvent(e) {
    const v = voice;
    if (!v) return;

    if (e.type === "input_audio_buffer.speech_started") setVoiceState("Listening…");
    if (e.type === "response.created") setVoiceState("Speaking…", true);

    if (e.type === "conversation.item.input_audio_transcription.completed" && e.transcript && e.transcript.trim()) {
      v.transcript.push({ role: "user", text: e.transcript.trim() });
      addMessage(e.transcript.trim(), "user");
    }

    if (e.type === "response.output_audio_transcript.done" && e.transcript && e.transcript.trim()) {
      v.transcript.push({ role: "assistant", text: e.transcript.trim() });
      addMessage(e.transcript.trim(), "bot");
    }

    if (e.type === "error") console.warn("Realtime error", e.error);

    if (e.type === "response.done") {
      const calls = ((e.response && e.response.output) || []).filter((o) => o.type === "function_call");
      if (!calls.length) {
        if (!v.busyTools) setVoiceState("Listening…");
        return;
      }
      v.busyTools++;
      setVoiceState("Working on it…");
      for (const fc of calls) {
        let args = {};
        try { args = JSON.parse(fc.arguments || "{}"); } catch (_) {}
        let result;
        try {
          const r = await fetch(`${apiBase}/v1/voice/web/tool`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              widget_key: tenantKey,
              voice_call_id: v.info.voice_call_id,
              token: v.info.token,
              name: fc.name,
              arguments: args
            })
          });
          const d = await r.json();
          result = r.ok ? d.result : { ok: false, error: d.detail || "Action failed" };
          if (r.ok && result && result.ok &&
              ["create_lead", "request_appointment", "request_callback"].includes(fc.name)) {
            leadSubmitted = true;
          }
          if (r.ok && d.actions && d.actions.length) handleActions(d.actions, "");
        } catch (err) {
          result = { ok: false, error: "Action failed. Offer to take details another way." };
        }
        if (voice !== v) return;
        voiceSend({
          type: "conversation.item.create",
          item: { type: "function_call_output", call_id: fc.call_id, output: JSON.stringify(result) }
        });
      }
      v.busyTools--;
      voiceSend({ type: "response.create" });
    }
  }

  function endSession(v) {
    clearInterval(v.timer);
    try { v.dc && v.dc.close(); } catch (_) {}
    try { v.pc && v.pc.close(); } catch (_) {}
    try { v.stream && v.stream.getTracks().forEach((t) => t.stop()); } catch (_) {}
    if (v.audio) v.audio.srcObject = null;
    if (v.info && !v.reported) {
      v.reported = true;
      fetch(`${apiBase}/v1/voice/web/end`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        keepalive: true,
        body: JSON.stringify({
          widget_key: tenantKey,
          voice_call_id: v.info.voice_call_id,
          token: v.info.token,
          duration_seconds: Math.round((Date.now() - v.started) / 1000),
          transcript: v.transcript.slice(-200)
        })
      }).catch(() => {});
    }
  }

  function endVoice(reason) {
    const v = voice;
    if (!v) return;
    voice = null;
    endSession(v);
    voiceBar.style.display = "none";
    voiceBar.classList.remove("speaking");
    voiceTimerEl.textContent = "";
    voiceBtn.classList.remove("active");
  }

  voiceBtn.onclick = () => {
    if (voice) return endVoice("user");
    if (bv) {
      // Tapping while the assistant speaks interrupts it and listens again
      if (window.speechSynthesis.speaking) window.speechSynthesis.cancel();
      else endBrowserVoice();
      return;
    }
    if (voiceMode === "realtime" && rtcSupported) startVoice();
    else startBrowserVoice();
  };
  voiceEndBtn.onclick = () => { endVoice("user"); endBrowserVoice(); };
  window.addEventListener("pagehide", () => { endVoice("pagehide"); endBrowserVoice(); });

  send.onclick = () => sendMessage();

  input.onkeypress = (e) => {
    if (e.key === "Enter") sendMessage();
  };

  loadConfig();
})();