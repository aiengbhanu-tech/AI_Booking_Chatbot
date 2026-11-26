"""Plan limits from the pricing cards are enforced as hard caps."""
import dataclasses
import json
from datetime import timedelta

import pytest

from app import plans
from app.analytics.models import ChatMessage
from app.core.db import SessionLocal
from app.leads.models import Lead
from app.tenants.models import Tenant
from app.voice import twilio_client
from app.voice import worker as worker_mod
from app.voice.models import VoiceCall, VoiceCallback
from app.voice.tools import tools_for
from app.voice.utils import utcnow

from tests.test_voice import BIZ_LINE, CALLER, enable_phone, set_plan, twilio_post


def add_chats(tenant_id, n, prefix="s"):
    db = SessionLocal()
    for i in range(n):
        db.add(ChatMessage(tenant_id=tenant_id, session_id=f"{prefix}{i}", role="user", content="hi"))
    db.commit()
    db.close()


def use_voice_minutes(tenant_id, minutes, channel="web"):
    db = SessionLocal()
    db.add(VoiceCall(tenant_id=tenant_id, channel=channel, direction="inbound", status="completed",
                     answered_by="ai", duration_seconds=int(minutes * 60), ended_at=utcnow()))
    db.commit()
    db.close()


def headers(tenant):
    return {"X-API-Key": tenant["api_key"]}


# ---------------- plan definitions ----------------

def test_plans_match_pricing_cards():
    s, g, p = plans.PLANS["starter"], plans.PLANS["growth"], plans.PLANS["pro"]
    assert (s.chats_per_month, s.voice_minutes_per_month) == (1000, 100)
    assert (g.chats_per_month, g.voice_minutes_per_month) == (3000, 400)
    assert (p.chats_per_month, p.voice_minutes_per_month) == (None, 1200)
    assert not s.phone_receptionist and g.phone_receptionist and p.phone_receptionist
    assert not g.live_transfer and p.live_transfer


@pytest.mark.parametrize("plan,status,expected", [
    (None, None, "starter"),            # no plan -> minimum limits
    ("growth", "active", "growth"),
    ("pro", "trialing", "pro"),
    ("growth", "past_due", "growth"),   # Stripe retry window keeps access
    ("growth", "cancelled", "starter"),
    ("enterprise", "active", "starter"),
])
def test_plan_resolution(plan, status, expected):
    assert plans.plan_for(Tenant(plan_name=plan, subscription_status=status)).key == expected


def test_usage_endpoint(client, tenant):
    add_chats(tenant["id"], 3)
    use_voice_minutes(tenant["id"], 12.5)
    u = client.get("/v1/usage", headers=headers(tenant)).json()
    assert u["plan"]["key"] == "starter" and u["chats_used"] == 3 and u["chats_limit"] == 1000
    assert u["voice_minutes_used"] == 12.5 and u["voice_minutes_limit"] == 100


# ---------------- chats ----------------

@pytest.fixture
def tiny_starter(monkeypatch):
    monkeypatch.setitem(plans.PLANS, "starter",
                        dataclasses.replace(plans.PLANS["starter"], chats_per_month=2, voice_minutes_per_month=10))


def test_chat_limit_blocks_new_conversations_only(client, tenant, tiny_starter, monkeypatch):
    add_chats(tenant["id"], 2)  # limit reached
    monkeypatch.setattr("app.widget.routes.run_chat",
                        lambda **kw: {"answer": "normal answer", "actions": [], "sources": []})

    # an ongoing conversation keeps working
    r = client.post("/v1/widget/chat", json={"widget_key": tenant["widget_key"], "message": "hi", "session_id": "s0"})
    assert r.json()["answer"] == "normal answer"

    # a new one gets the limit message + lead form, and is not stored/counted
    r = client.post("/v1/widget/chat", json={"widget_key": tenant["widget_key"], "message": "hi", "session_id": "new"})
    body = r.json()
    assert "leave your details" in body["answer"].lower()
    assert body["actions"][0]["type"] == "show_lead_form"

    r = client.get("/v1/widget/chat/stream", params={"widget_key": tenant["widget_key"], "message": "hi", "session_id": "new2"})
    events = [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: ")]
    assert events[-1]["type"] == "done" and events[-1]["actions"][0]["type"] == "show_lead_form"

    r = client.post("/v1/chat", json={"message": "hi"}, headers=headers(tenant))
    assert r.status_code == 429

    # lead capture is never blocked
    r = client.post("/v1/widget/lead", json={"widget_key": tenant["widget_key"], "name": "A", "phone": "5551234567"})
    assert r.json()["ok"] is True


def test_pro_chats_unlimited(client, tenant, monkeypatch):
    set_plan(tenant, "pro")
    monkeypatch.setitem(plans.PLANS, "pro", dataclasses.replace(plans.PLANS["pro"], chats_per_month=None))
    add_chats(tenant["id"], 50)
    db = SessionLocal()
    t = db.query(Tenant).get(tenant["id"])
    assert plans.can_chat(db, t, "brand-new")
    db.close()


# ---------------- widget voice minutes ----------------

def enable_web_voice(client, tenant, engine="auto"):
    r = client.put("/v1/voice/settings", headers=headers(tenant),
                   json={"web_voice_enabled": True, "web_voice_engine": engine})
    assert r.status_code == 200, r.text


def fake_openai(monkeypatch):
    class R:
        status_code = 201
        text = "v=0"
        headers = {"location": "/v1/realtime/calls/rtc_1"}
    monkeypatch.setattr("app.voice.routes.httpx.post", lambda *a, **k: R())


def start_web(client, tenant, sid="sess"):
    return client.post("/v1/voice/web/session", json={"widget_key": tenant["widget_key"], "session_id": sid, "sdp": "v=0"})


def test_web_voice_capped_to_remaining_minutes(client, tenant, monkeypatch):
    enable_web_voice(client, tenant)
    fake_openai(monkeypatch)
    use_voice_minutes(tenant["id"], 95)  # Starter: 100 -> 5 minutes left
    r = start_web(client, tenant)
    assert r.status_code == 200 and r.json()["max_seconds"] == 300

    # the live session reserves its 5 minutes, so a parallel one can't start
    assert start_web(client, tenant, "other").status_code == 402
    cfg = client.get("/v1/widget/config", params={"widget_key": tenant["widget_key"]}).json()
    assert cfg["voice_mode"] == "browser"


def test_web_voice_falls_back_to_browser_when_used_up(client, tenant, monkeypatch):
    enable_web_voice(client, tenant)
    fake_openai(monkeypatch)
    cfg = client.get("/v1/widget/config", params={"widget_key": tenant["widget_key"]}).json()
    assert cfg["voice_mode"] == "realtime"
    use_voice_minutes(tenant["id"], 99.7)  # 18 s left < 30 s minimum
    assert start_web(client, tenant).status_code == 402
    cfg = client.get("/v1/widget/config", params={"widget_key": tenant["widget_key"]}).json()
    assert cfg["voice_enabled"] is True and cfg["voice_mode"] == "browser"


def test_browser_only_engine_never_uses_minutes(client, tenant, monkeypatch):
    enable_web_voice(client, tenant, engine="browser")
    fake_openai(monkeypatch)
    cfg = client.get("/v1/widget/config", params={"widget_key": tenant["widget_key"]}).json()
    assert cfg["voice_mode"] == "browser"
    assert start_web(client, tenant).status_code == 402


def test_web_end_bills_server_measured_time_not_client_claim(client, tenant, monkeypatch):
    enable_web_voice(client, tenant)
    fake_openai(monkeypatch)
    s = start_web(client, tenant).json()
    client.post("/v1/voice/web/end", json={"widget_key": tenant["widget_key"], "voice_call_id": s["voice_call_id"],
                                           "token": s["token"], "duration_seconds": 1, "transcript": []})
    db = SessionLocal()
    call = db.query(VoiceCall).get(s["voice_call_id"])
    db.close()
    assert call.duration_seconds <= 5 and call.ended_at is not None


def test_sweep_hangs_up_abandoned_web_session(client, tenant, monkeypatch):
    enable_web_voice(client, tenant)
    fake_openai(monkeypatch)
    s = start_web(client, tenant).json()
    db = SessionLocal()
    call = db.query(VoiceCall).get(s["voice_call_id"])
    call.started_at = utcnow() - timedelta(seconds=call.max_seconds + 60)
    db.commit()
    db.close()

    hung_up = []
    monkeypatch.setattr(worker_mod.httpx, "post", lambda url, **kw: hung_up.append(url))
    assert worker_mod.sweep_expired_sessions() == 1
    assert hung_up and hung_up[0].endswith("/v1/realtime/calls/rtc_1/hangup")
    db = SessionLocal()
    call = db.query(VoiceCall).get(s["voice_call_id"])
    db.close()
    assert call.ended_at and call.duration_seconds == call.max_seconds
    assert worker_mod.sweep_expired_sessions() == 0


# ---------------- phone features by plan ----------------

def test_starter_cannot_enable_phone_features(client, tenant):
    h = headers(tenant)
    r = client.put("/v1/voice/settings", headers=h, json={"phone_enabled": True, "twilio_phone_number": BIZ_LINE})
    assert r.status_code == 403 and "Growth" in r.json()["detail"]
    assert client.put("/v1/voice/settings", headers=h, json={"sms_booking_link_enabled": True}).status_code == 403
    out = client.get("/v1/voice/settings", headers=h).json()
    assert out["plan_features"]["phone_receptionist"] is False


def test_downgraded_tenant_phone_line_turns_off(client, tenant):
    enable_phone(client, tenant, plan="growth", ring_business_first=False)
    set_plan(tenant, "growth", status="cancelled")  # subscription ended -> Starter
    r = twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CAD1"})
    assert "not available" in r.text


def test_transfer_only_on_pro(client, tenant):
    enable_phone(client, tenant, plan="growth")
    db = SessionLocal()
    t = db.query(Tenant).get(tenant["id"])
    from app.voice.service import get_voice_settings
    vs = get_voice_settings(db, t.id)
    assert "transfer_to_human" not in {x["name"] for x in tools_for("phone", t, vs)}
    t.plan_name = "pro"
    assert "transfer_to_human" in {x["name"] for x in tools_for("phone", t, vs)}
    db.close()


def test_phone_without_minutes_takes_message_instead_of_ai(client, tenant):
    enable_phone(client, tenant, plan="growth", ring_business_first=False)
    use_voice_minutes(tenant["id"], 400, channel="phone")  # Growth minutes used up
    r = twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CAM1"})
    assert "call you back" in r.text and "<Stream" not in r.text
    db = SessionLocal()
    lead = db.query(Lead).one()
    db.close()
    assert lead.intent == "callback" and lead.phone == CALLER


def test_worker_cancels_callback_when_minutes_used_up(client, tenant, monkeypatch):
    enable_phone(client, tenant, plan="growth", ring_business_first=False, missed_call_mode="callback_only")
    twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CAW1"})
    use_voice_minutes(tenant["id"], 400, channel="phone")
    dialed = []
    monkeypatch.setattr(twilio_client, "create_call", lambda **kw: dialed.append(kw) or "X")
    worker_mod.process_due_callbacks()
    db = SessionLocal()
    cb = db.query(VoiceCallback).one()
    db.close()
    assert not dialed and cb.status == "cancelled" and "minutes" in cb.last_error
