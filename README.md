# AI Receptionist SaaS

AI receptionist for business websites **and phone lines**:

- **Website chatbot.** Embed it with one script tag. It answers from the business's own website through RAG, captures leads, and shows booking links. *(Unchanged.)*
- **Voice in the chatbot.** A 🎤 button in the same widget lets visitors talk to the assistant instead of typing.
- **Phone receptionist.** Calls to the business's Twilio number ring the team first. If nobody picks up, the AI answers: it explains services, pricing, and hours, takes appointment requests, and records callbacks.
- **Missed-call callbacks.** When a caller hangs up before speaking to anyone, the AI calls them back within the business's calling hours. Voicemail detection and retries are built in.
- **Dashboard.** One place for leads, chats, calls, transcripts, AI summaries, and the callback queue.

The voice engine was merged in from the `relay-voice` prototype. It uses OpenAI Realtime with tools and call logs, and was re-implemented inside this FastAPI backend. Voice now uses the **same knowledge base and the same leads table** as the chatbot.

## Architecture

```
                    ┌──────────────────── FastAPI backend ─────────────────────┐
Website widget ───► │ /v1/widget/*   text chat (RAG + leads)        [unchanged] │
  (text)            │                                                          │
Website widget ───► │ /v1/voice/web/*  creates OpenAI Realtime WebRTC session, │──► OpenAI Realtime
  (🎤 voice)        │                  runs tools for the browser              │
                    │                                                          │
Phone caller ─────► │ /v1/voice/twilio/*  webhooks (TwiML)                     │
  (Twilio)          │ /v1/voice/twilio/media-stream  WS bridge  ◄─────────────►│──► OpenAI Realtime
                    │                                                          │
                    │ callback worker (in-process) ──► Twilio REST: dial out   │
                    │                                                          │
                    │ shared tools: search_knowledge (Qdrant) · create_lead ·  │
                    │   request_appointment · request_callback · SMS booking   │
                    │   link · transfer_to_human · end_call                    │
                    └──────────────── Postgres · Qdrant ───────────────────────┘
Dashboard (Next.js) ──► /v1/voice/settings, /calls, /callbacks, /summary  (+ existing APIs)
```

Voice code lives in [`backend/app/voice/`](backend/app/voice):

| File | Purpose |
|---|---|
| `models.py` | `voice_settings` (per tenant), `voice_calls`, `voice_callbacks` |
| `routes.py` | Dashboard APIs, widget voice APIs, Twilio webhooks + media-stream WS |
| `phone_bridge.py` | Twilio μ-law audio ⇄ OpenAI Realtime, barge-in, tool calls, hang-up/transfer |
| `tools.py` | Tools the voice agent can call (reuse RAG retriever + `Lead` model) |
| `prompts.py` | Receptionist persona, session config, post-call summary |
| `worker.py` | Background loop that places callbacks (multi-replica safe on Postgres) |
| `calls.py` | Call finalisation: outcome, summary, missed-call detection |
| `twilio_client.py` | Signature validation, REST calls, TwiML (plain `httpx`, no SDK) |

### Call flow

1. A customer calls the Twilio number, and the `/twilio/incoming` webhook fires.
2. If **Ring my team first** is on, the call rings the forward-to number for N seconds.
3. If the team answers, the call proceeds normally and no AI is involved.
4. If nobody answers, one of two things happens:
   - **AI answers** mode: the AI picks up live and helps the caller.
   - **Hang up & AI calls back** mode: the caller hears "we'll call you right back" and a callback is queued.
5. If the caller hangs up while ringing, or the AI picked up but the caller never spoke, it counts as a **missed call** and a callback is queued.
6. The worker dials the customer within calling hours. On voicemail it leaves a short message. If nobody answers, it retries.
7. If the customer calls in again first, the pending callback is cancelled.

### Backwards compatibility

- The migration only **adds** tables. No existing table or column changes.
- Voice is **off for every tenant** until it's enabled under *Voice Agent & Calls* in the dashboard.
- `/v1/widget/config` gained one extra field, `voice_enabled`. The widget shows the 🎤 button only when it is `true`, so existing embeds look and behave exactly as before.
- `/v1/widget/lead` behaves the same. It can also queue an AI callback for `intent=callback`, but only if *auto-callback web leads* is enabled, and any voice error is swallowed.
- Widget voice transcripts are also written to `chat_messages` under the same session, so the existing message analytics include them.

## Plans & limits

Limits match the dashboard pricing cards and are **hard caps**. They are defined in [`backend/app/plans.py`](backend/app/plans.py). Clients without an active subscription get the Starter limits. Usage resets on the 1st of each month (UTC).

| | Starter | Growth | Pro |
|---|---|---|---|
| Chats / month (one chat = one conversation) | 1,000 | 3,000 | Unlimited |
| AI voice minutes / month (widget + phone) | 100 | 400 | 1,200 |
| Phone receptionist, missed-call callbacks, SMS booking link, call summaries | — | ✓ | ✓ |
| Live transfer to staff | — | — | ✓ |
| Free browser voice in the widget | ✓ | ✓ | ✓ |

What happens at each limit:
- **Chat limit:** conversations already in progress continue. New ones get a polite message and the lead form, and leads are never blocked.
- **AI voice minutes:**
  - Every AI session reserves its maximum length up front, so parallel calls can't overrun the plan.
  - The widget switches to the **free browser voice**: the browser's own speech recognition and speech, which uses no minutes, only normal chat messages.
  - Phone calls play "we'll call you back" and create a callback lead for the team. AI callbacks pause until minutes reset.
  - Live phone calls are asked to wrap up 30 seconds before the limit, then end.
- **Abandoned sessions:** widget voice sessions the browser never closed are hung up by the server and counted at their reserved length.

Each widget can be set to **"Free browser voice only"** so it never uses AI voice minutes. The browser voice works best in Chrome and Edge; Chrome's speech recognition is processed by Google.

The default voice model is **`gpt-realtime-2.1-mini`**, about 3× cheaper than `gpt-realtime-2.1`. Set `REALTIME_MODEL` in `.env` to change it.

## Setup

```bash
docker compose up -d                      # Postgres + Qdrant
cd backend
python -m venv venv && venv\Scripts\activate   # (Windows)  or: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                    # fill in keys
alembic upgrade head                      # adds the voice tables
uvicorn app.main:app --reload --port 8000

cd ../dashboard
npm install && npm run dev                # http://localhost:3000
```

### Website voice (🎤 in the widget)

1. Set `OPENAI_API_KEY`. The browser never sees it: the backend creates each Realtime session.
2. In the dashboard, go to **Voice Agent & Calls**, tick **Enable voice in chat widget**, and save.
3. Open the demo link. Microphone access needs HTTPS or `localhost`.

### Phone line + missed-call callbacks (Twilio)

1. Buy a Twilio phone number.
2. Expose the backend over HTTPS. In development: `ngrok http 8000`.
3. Set `PUBLIC_BASE_URL` (the https URL), `TWILIO_ACCOUNT_SID`, and `TWILIO_AUTH_TOKEN`, then restart.
4. In the dashboard, enter the Twilio number and your team's phone, enable the phone line, and save.
5. The dashboard then shows two webhook URLs. Paste them into the Twilio console under **Phone Numbers → your number → Voice configuration**:
   - *A call comes in*: `…/v1/voice/twilio/incoming` (HTTP POST)
   - *Call status changes*: `…/v1/voice/twilio/status` (HTTP POST). Missed-call detection needs this one.
6. Set your **calling hours and timezone**. Callbacks are never placed outside that window.

## Tests

```bash
cd backend
pip install pytest
python -m pytest tests -q
```

The 34 tests cover the call flows (forwarding, AI pickup, missed call → callback, dedupe, cancel on call-in, voicemail, retry), Twilio signature validation against Twilio's documented example, tenant isolation, tool confirmation rules, the widget voice session/tool/end flow, and a full phone-bridge conversation against a scripted fake Realtime socket. Twilio and OpenAI are stubbed, so no credentials are needed.

## Before production traffic

- **Consent and compliance.** Automated outbound calls are regulated (TCPA in the US, plus local rules elsewhere). Make sure customers have consented to callbacks, and keep calling hours conservative. Recording and transcription disclosure laws vary by state and country, so add a disclosure to the greeting where required.
- **Rate limits.** Add rate limiting on `/v1/widget/*` and `/v1/voice/web/*`. They are public, keyed only by the widget key, just like the existing chat endpoints.
- **Real bookings.** Appointment requests are saved as `appointment` leads for staff to confirm. The agent is told never to say a slot is booked. A real calendar integration would make bookings final.
- **Scaling.** The callback worker runs inside the API process. With several replicas it stays safe on Postgres (`SKIP LOCKED`). You can disable it with `VOICE_CALLBACK_WORKER_ENABLED=false` on all but one replica.
- **Live testing.** Live calls and audio quality have not been tested with real Twilio and OpenAI credentials yet. Test with a real number before launch.
