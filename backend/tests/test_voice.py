from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pytest

from app.core.db import SessionLocal
from app.leads.models import Lead
from app.voice import twilio_client
from app.voice import worker as worker_mod
from app.voice.calls import derive_outcome, finalize_call
from app.voice.models import VoiceCall, VoiceCallback
from app.voice.tools import ToolContext, execute_tool
from app.voice.utils import next_allowed_call_time, normalize_phone, sign_token

BIZ_LINE = "+15550001111"
OWNER_CELL = "+15550002222"
CALLER = "+15557654321"


# ---------------- helpers ----------------

def twilio_post(client, path, params, query=None):
    """POST like Twilio does, with a valid X-Twilio-Signature."""
    url = "https://voice.example.com" + path + (("?" + urlencode(query)) if query else "")
    sig = twilio_client.compute_signature("twilio-test-token", url, params)
    return client.post(path, params=query, data=params, headers={"X-Twilio-Signature": sig})


def enable_phone(client, tenant, **overrides):
    body = {
        "web_voice_enabled": True,
        "phone_enabled": True,
        "twilio_phone_number": BIZ_LINE,
        "forward_to_number": OWNER_CELL,
        "ring_business_first": True,
        "callback_window_start_hour": 0,
        "callback_window_end_hour": 24,
        "callback_delay_seconds": 0,
        **overrides,
    }
    r = client.put("/v1/voice/settings", json=body, headers={"X-API-Key": tenant["api_key"]})
    assert r.status_code == 200, r.text
    return r.json()


def callbacks():
    db = SessionLocal()
    try:
        return db.query(VoiceCallback).all()
    finally:
        db.close()


# ---------------- pure utils ----------------

@pytest.mark.parametrize("raw,cc,expected", [
    ("+1 (555) 765-4321", "+1", "+15557654321"),
    ("555-765-4321", "+1", "+15557654321"),
    ("15557654321", "+1", "+15557654321"),
    ("98765 43210", "+91", "+919876543210"),
    ("0044 20 7946 0958", "+1", "+442079460958"),
    ("abc", "+1", None),
    ("12", "+1", None),
    (None, "+1", None),
])
def test_normalize_phone(raw, cc, expected):
    assert normalize_phone(raw, cc) == expected


def test_calling_window():
    # 23:30 New York -> next day 09:00 New York
    ny_late = datetime(2026, 11, 20, 4, 30, tzinfo=timezone.utc)  # 23:30 EST on the 19th
    out = next_allowed_call_time(ny_late, "America/New_York", 9, 19)
    assert out == datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)
    # inside the window -> unchanged
    mid = datetime(2026, 11, 20, 17, 0, tzinfo=timezone.utc)  # 12:00 EST
    assert next_allowed_call_time(mid, "America/New_York", 9, 19) == mid
    # early morning -> same-day 09:00
    early = datetime(2026, 11, 20, 11, 0, tzinfo=timezone.utc)  # 06:00 EST
    assert next_allowed_call_time(early, "America/New_York", 9, 19) == datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc)


def test_twilio_signature_matches_documented_example():
    # Example from Twilio's webhook security documentation
    params = {
        "CallSid": "CA1234567890ABCDE",
        "Caller": "+12349013030",
        "Digits": "1234",
        "From": "+12349013030",
        "To": "+18005551212",
    }
    sig = twilio_client.compute_signature("12345", "https://mycompany.com/myapp.php?foo=1&bar=2", params)
    assert sig == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="


def test_outcome_priority():
    assert derive_outcome([], []) == "no_conversation"
    assert derive_outcome([{"role": "user", "text": "hi"}], []) == "info_provided"
    ev = [{"name": "create_lead", "ok": True}, {"name": "request_appointment", "ok": True}]
    assert derive_outcome([], ev) == "appointment_requested"
    assert derive_outcome([], [{"name": "request_appointment", "ok": False}]) == "no_conversation"


# ---------------- chatbot unaffected ----------------

def test_widget_config_unchanged_and_voice_off_by_default(client, tenant):
    r = client.get("/v1/widget/config", params={"widget_key": tenant["widget_key"]})
    assert r.status_code == 200
    cfg = r.json()
    for k in ("tenant_name", "welcome_message", "calendly_url", "primary_color", "position"):
        assert k in cfg
    assert cfg["voice_enabled"] is False


def test_widget_lead_still_works_without_voice(client, tenant):
    r = client.post("/v1/widget/lead", json={
        "widget_key": tenant["widget_key"], "name": "Ann", "phone": "555-765-4321", "intent": "callback"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert callbacks() == []  # no voice settings -> no auto-callback


def test_widget_lead_auto_callback_when_enabled(client, tenant):
    enable_phone(client, tenant, auto_callback_web_leads=True)
    r = client.post("/v1/widget/lead", json={
        "widget_key": tenant["widget_key"], "name": "Ann", "phone": "555-765-4321", "intent": "callback"})
    assert r.status_code == 200
    cbs = callbacks()
    assert len(cbs) == 1 and cbs[0].phone == CALLER and cbs[0].reason == "web_lead"


# ---------------- settings ----------------

def test_settings_require_api_key(client):
    assert client.get("/v1/voice/settings").status_code == 401


def test_settings_validation(client, tenant):
    h = {"X-API-Key": tenant["api_key"]}
    r = client.put("/v1/voice/settings", json={"phone_enabled": True}, headers=h)
    assert r.status_code == 400
    r = client.put("/v1/voice/settings", json={"timezone": "Mars/Base"}, headers=h)
    assert r.status_code == 422
    out = enable_phone(client, tenant)
    assert out["settings"]["twilio_phone_number"] == BIZ_LINE
    assert out["platform"]["webhooks"]["voice_url"] == "https://voice.example.com/v1/voice/twilio/incoming"
    cfg = client.get("/v1/widget/config", params={"widget_key": tenant["widget_key"]}).json()
    assert cfg["voice_enabled"] is True


def test_twilio_number_unique_across_tenants(client, tenant):
    enable_phone(client, tenant)
    other = client.post("/v1/tenants", json={"name": "Other"}).json()
    r = client.put("/v1/voice/settings", json={"twilio_phone_number": BIZ_LINE}, headers={"X-API-Key": other["api_key"]})
    assert r.status_code == 409


# ---------------- phone call flows ----------------

def test_rejects_unsigned_twilio_webhook(client, tenant):
    enable_phone(client, tenant)
    r = client.post("/v1/voice/twilio/incoming", data={"To": BIZ_LINE, "From": CALLER, "CallSid": "CA1"})
    assert r.status_code == 403


def test_incoming_rings_business_then_ai_answers(client, tenant):
    enable_phone(client, tenant)
    r = twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CA1"})
    assert r.status_code == 200
    assert "<Dial" in r.text and OWNER_CELL in r.text

    db = SessionLocal()
    call = db.query(VoiceCall).filter_by(provider_call_sid="CA1").one()
    db.close()

    r = twilio_post(client, "/v1/voice/twilio/dial-complete", {"DialCallStatus": "no-answer", "CallSid": "CA1"},
                    query={"voice_call_id": call.id})
    assert "<Connect><Stream" in r.text
    assert "wss://voice.example.com/v1/voice/twilio/media-stream" in r.text
    assert sign_token("stream", call.id) in r.text


def test_business_answers_no_callback(client, tenant):
    enable_phone(client, tenant)
    twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CA2"})
    db = SessionLocal()
    cid = db.query(VoiceCall).filter_by(provider_call_sid="CA2").one().id
    db.close()
    r = twilio_post(client, "/v1/voice/twilio/dial-complete", {"DialCallStatus": "completed", "CallSid": "CA2"},
                    query={"voice_call_id": cid})
    assert "<Hangup/>" in r.text
    twilio_post(client, "/v1/voice/twilio/status", {"CallSid": "CA2", "CallStatus": "completed", "CallDuration": "42"})
    assert callbacks() == []


def test_caller_hangs_up_while_ringing_is_missed_and_called_back(client, tenant):
    enable_phone(client, tenant)
    twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CA3"})
    twilio_post(client, "/v1/voice/twilio/status", {"CallSid": "CA3", "CallStatus": "completed", "CallDuration": "9"})

    db = SessionLocal()
    call = db.query(VoiceCall).filter_by(provider_call_sid="CA3").one()
    assert call.status == "missed"
    db.close()
    cbs = callbacks()
    assert len(cbs) == 1 and cbs[0].phone == CALLER and cbs[0].reason == "missed_call"

    # Status callback retried by Twilio -> still only one callback
    twilio_post(client, "/v1/voice/twilio/status", {"CallSid": "CA3", "CallStatus": "completed"})
    assert len(callbacks()) == 1

    # Customer calls again -> pending callback cancelled
    twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CA4"})
    assert callbacks()[0].status == "cancelled"


def test_callback_only_mode(client, tenant):
    enable_phone(client, tenant, missed_call_mode="callback_only", ring_business_first=False)
    r = twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CA5"})
    assert "call you right back" in r.text and "<Hangup/>" in r.text
    assert len(callbacks()) == 1


def test_unknown_number_politely_rejected(client, tenant):
    r = twilio_post(client, "/v1/voice/twilio/incoming", {"To": "+15559999999", "From": CALLER, "CallSid": "CA6"})
    assert r.status_code == 200 and "not available" in r.text


def test_ai_call_with_no_speech_counts_as_missed(client, tenant):
    enable_phone(client, tenant, ring_business_first=False)
    twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CA7"})
    db = SessionLocal()
    call = db.query(VoiceCall).filter_by(provider_call_sid="CA7").one()
    call.status, call.answered_by = "ai_active", "ai"
    db.commit()
    cid = call.id
    db.close()
    finalize_call(cid, [{"role": "assistant", "text": "Thanks for calling!"}], [], 4)
    assert len(callbacks()) == 1


# ---------------- callback worker ----------------

def test_worker_places_callback_and_handles_voicemail_and_retry(client, tenant, monkeypatch):
    enable_phone(client, tenant, ring_business_first=False, missed_call_mode="callback_only", callback_max_attempts=2)
    twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CA8"})

    placed = []
    monkeypatch.setattr(twilio_client, "create_call",
                        lambda to, from_, answer_url, status_url: placed.append((to, from_, answer_url)) or "CAOUT1")
    assert worker_mod.process_due_callbacks() == 1
    assert placed[0][0] == CALLER and placed[0][1] == BIZ_LINE

    cb = callbacks()[0]
    assert cb.status == "dialing" and cb.attempts == 1
    db = SessionLocal()
    out_call = db.query(VoiceCall).filter_by(provider_call_sid="CAOUT1").one()
    db.close()

    # No answer -> retry scheduled
    twilio_post(client, "/v1/voice/twilio/outbound-status", {"CallSid": "CAOUT1", "CallStatus": "no-answer"},
                query={"voice_call_id": out_call.id})
    cb = callbacks()[0]
    assert cb.status == "pending" and cb.next_attempt_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)

    # Second attempt reaches voicemail -> short message, no AI conversation
    db = SessionLocal()
    row = db.query(VoiceCallback).one()
    row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    db.close()
    monkeypatch.setattr(twilio_client, "create_call", lambda **kw: "CAOUT2")
    assert worker_mod.process_due_callbacks() == 1
    db = SessionLocal()
    out2 = db.query(VoiceCall).filter_by(provider_call_sid="CAOUT2").one()
    db.close()
    r = twilio_post(client, "/v1/voice/twilio/outbound", {"CallSid": "CAOUT2", "AnsweredBy": "machine_end_beep"},
                    query={"voice_call_id": out2.id})
    assert "<Say>" in r.text and "<Stream" not in r.text
    assert callbacks()[0].status == "voicemail"


def test_outbound_human_gets_ai_stream(client, tenant, monkeypatch):
    enable_phone(client, tenant, ring_business_first=False, missed_call_mode="callback_only")
    twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CA9"})
    monkeypatch.setattr(twilio_client, "create_call", lambda **kw: "CAOUT3")
    worker_mod.process_due_callbacks()
    db = SessionLocal()
    out = db.query(VoiceCall).filter_by(provider_call_sid="CAOUT3").one()
    db.close()
    r = twilio_post(client, "/v1/voice/twilio/outbound", {"CallSid": "CAOUT3", "AnsweredBy": "human"},
                    query={"voice_call_id": out.id})
    assert "<Connect><Stream" in r.text


def test_media_stream_rejects_bad_token(client):
    with client.websocket_connect("/v1/voice/twilio/media-stream") as ws:
        ws.send_json({"event": "start", "start": {"streamSid": "MZ1", "customParameters": {"voice_call_id": "1", "token": "bad"}}})
        with pytest.raises(Exception):
            ws.receive_text()


# ---------------- tools ----------------

def _tenant_id(tenant_resp):
    return tenant_resp["id"]


def test_tools_require_confirmation_and_save_leads(client, tenant):
    enable_phone(client, tenant)
    ctx = ToolContext(tenant_id=_tenant_id(tenant), channel="phone", caller_phone=CALLER, call_sid="CA10")
    r = execute_tool(ctx, "request_appointment", {"name": "Ann", "preferred_time": "Tue 3pm", "confirmed": False})
    assert r["ok"] is False
    r = execute_tool(ctx, "request_appointment", {"name": "Ann", "preferred_time": "Tue 3pm", "confirmed": True})
    assert r["ok"] is True and "do NOT tell" in r["message"]
    db = SessionLocal()
    lead = db.query(Lead).one()
    db.close()
    assert lead.intent == "appointment" and lead.phone == CALLER and "Tue 3pm" in lead.notes

    r = execute_tool(ctx, "request_callback", {"name": "Ann", "asap": True})
    assert r["ok"] and r["auto_callback_scheduled"] is True

    r = execute_tool(ctx, "end_call", {"reason": "done"})
    assert r["ok"] and ctx.controls[-1]["type"] == "hangup"


def test_phone_only_tools_not_available_on_web(client, tenant):
    enable_phone(client, tenant)
    ctx = ToolContext(tenant_id=_tenant_id(tenant), channel="web", session_id="sess_1")
    assert execute_tool(ctx, "end_call", {"reason": "x"})["ok"] is False
    assert execute_tool(ctx, "transfer_to_human", {"reason": "x"})["ok"] is False
    assert execute_tool(ctx, "nope", {})["ok"] is False


def test_search_knowledge_degrades_gracefully(client, tenant):
    ctx = ToolContext(tenant_id=_tenant_id(tenant), channel="web")
    r = execute_tool(ctx, "search_knowledge", {"query": "pricing"})
    assert r["ok"] is False and "callback" in r["error"]


# ---------------- web voice endpoints ----------------

def test_web_voice_disabled_by_default(client, tenant):
    r = client.post("/v1/voice/web/session", json={"widget_key": tenant["widget_key"], "session_id": "s1", "sdp": "v=0"})
    assert r.status_code == 403


def test_web_voice_session_tool_and_end(client, tenant, monkeypatch):
    enable_phone(client, tenant)

    class FakeResp:
        status_code = 201
        text = "v=0\r\no=answer"

    captured = {}

    def fake_post(url, headers, files, timeout):
        captured["url"] = url
        captured["session"] = files["session"][1]
        return FakeResp()

    monkeypatch.setattr("app.voice.routes.httpx.post", fake_post)
    r = client.post("/v1/voice/web/session", json={"widget_key": tenant["widget_key"], "session_id": "sess_9", "sdp": "v=0"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["sdp"].startswith("v=0") and captured["url"].endswith("/v1/realtime/calls")
    assert "search_knowledge" in captured["session"] and "end_call" not in captured["session"]

    bad = client.post("/v1/voice/web/tool", json={"widget_key": tenant["widget_key"], "voice_call_id": s["voice_call_id"],
                                                  "token": "forged", "name": "create_lead", "arguments": {}})
    assert bad.status_code == 403

    ok = client.post("/v1/voice/web/tool", json={
        "widget_key": tenant["widget_key"], "voice_call_id": s["voice_call_id"], "token": s["token"],
        "name": "create_lead",
        "arguments": {"name": "Bo", "email": "bo@example.com", "intent": "pricing", "confirmed": True}})
    assert ok.status_code == 200 and ok.json()["result"]["ok"] is True

    monkeypatch.setattr("app.voice.calls.summarize_transcript", lambda t: "Bo asked about pricing.")
    end = client.post("/v1/voice/web/end", json={
        "widget_key": tenant["widget_key"], "voice_call_id": s["voice_call_id"], "token": s["token"],
        "duration_seconds": 30,
        "transcript": [{"role": "user", "text": "How much is cleaning?"}, {"role": "assistant", "text": "Let me check."}]})
    assert end.status_code == 200

    h = {"X-API-Key": tenant["api_key"]}
    detail = client.get(f"/v1/voice/calls/{s['voice_call_id']}", headers=h).json()
    assert detail["outcome"] == "lead_captured" and detail["summary"] == "Bo asked about pricing."
    assert len(detail["transcript"]) == 2
    # mirrored into chat history so existing analytics count it
    summary = client.get("/v1/analytics/summary", headers=h).json()
    assert summary["total_messages"] == 2 and summary["total_leads"] == 1
    vs = client.get("/v1/voice/summary", headers=h).json()
    assert vs["web_voice_sessions"] == 1


def test_dashboard_manual_callback_and_cancel(client, tenant):
    h = {"X-API-Key": tenant["api_key"]}
    assert client.post("/v1/voice/callbacks", json={"phone": CALLER}, headers=h).status_code == 400
    enable_phone(client, tenant)
    cb = client.post("/v1/voice/callbacks", json={"phone": "555 765 4321", "name": "Ann"}, headers=h).json()
    assert cb["phone"] == CALLER and cb["status"] == "pending"
    assert client.post(f"/v1/voice/callbacks/{cb['id']}/cancel", headers=h).json()["status"] == "cancelled"
    # tenant isolation
    other = client.post("/v1/tenants", json={"name": "Other"}).json()
    assert client.post(f"/v1/voice/callbacks/{cb['id']}/cancel", headers={"X-API-Key": other["api_key"]}).status_code == 404
