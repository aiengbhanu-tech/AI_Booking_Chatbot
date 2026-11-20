"""End-to-end test of the Twilio <-> OpenAI Realtime bridge with a scripted fake model."""
import asyncio
import json

from app.core.db import SessionLocal
from app.voice import phone_bridge, twilio_client
from app.voice.models import VoiceCall
from app.voice.utils import sign_token

from tests.test_voice import BIZ_LINE, CALLER, enable_phone, twilio_post


class FakeRealtime:
    """Behaves like the OpenAI Realtime websocket: reacts to what the bridge sends."""

    def __init__(self):
        self.sent: list[dict] = []
        self.queue: asyncio.Queue = asyncio.Queue()
        self.response_creates = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if msg["type"] == "response.create":
            self.response_creates += 1
            if self.response_creates == 1:  # greeting
                for ev in [
                    {"type": "response.output_audio.delta", "delta": "AAAA", "item_id": "item_1"},
                    {"type": "response.output_audio_transcript.done", "transcript": "Thanks for calling SmileCare!"},
                    {"type": "input_audio_buffer.speech_started"},  # caller barges in
                    {"type": "conversation.item.input_audio_transcription.completed", "transcript": "That's all, bye."},
                    {"type": "response.done", "response": {"output": [
                        {"type": "function_call", "name": "end_call", "call_id": "fc_1", "arguments": '{"reason":"done"}'}]}},
                ]:
                    await self.queue.put(ev)
            elif self.response_creates == 2:  # after tool output -> goodbye turn
                await self.queue.put({"type": "response.output_audio.delta", "delta": "BBBB", "item_id": "item_2"})
                await self.queue.put({"type": "response.done", "response": {"output": [{"type": "message"}]}})

    def __aiter__(self):
        return self

    async def __anext__(self):
        return json.dumps(await self.queue.get())


def test_bridge_full_call(client, tenant, monkeypatch):
    enable_phone(client, tenant, ring_business_first=False)
    twilio_post(client, "/v1/voice/twilio/incoming", {"To": BIZ_LINE, "From": CALLER, "CallSid": "CABRIDGE"})
    db = SessionLocal()
    call_id = db.query(VoiceCall).filter_by(provider_call_sid="CABRIDGE").one().id
    db.close()

    fake = FakeRealtime()
    monkeypatch.setattr(phone_bridge, "ws_connect", lambda *a, **k: fake)
    hangups = []
    monkeypatch.setattr(twilio_client, "update_call_twiml", lambda sid, tw: hangups.append((sid, tw)))
    monkeypatch.setattr("app.voice.calls.summarize_transcript", lambda t: "Caller said bye.")

    with client.websocket_connect("/v1/voice/twilio/media-stream") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json({"event": "start", "start": {"streamSid": "MZ1", "customParameters": {
            "voice_call_id": str(call_id), "token": sign_token("stream", call_id)}}})
        ws.send_json({"event": "media", "media": {"payload": "/////w==", "timestamp": "100"}})

        received = []
        while not any(m.get("mark", {}).get("name") == "control" for m in received):
            received.append(ws.receive_json())

        # audio forwarded to the phone, barge-in cleared the buffer
        assert received[0] == {"event": "media", "media": {"payload": "AAAA"}, "streamSid": "MZ1"}
        assert {"event": "clear", "streamSid": "MZ1"} in received
        assert any(m.get("media", {}).get("payload") == "BBBB" for m in received)

        # Twilio confirms the goodbye finished playing -> bridge hangs up
        ws.send_json({"event": "mark", "mark": {"name": "control"}})
        for _ in range(50):
            if hangups:
                break
            ws.send_json({"event": "media", "media": {"payload": "/////w==", "timestamp": "200"}})
        ws.send_json({"event": "stop"})
        # Server persists the call, then closes the socket.
        while True:
            msg = ws.receive()
            if msg["type"] == "websocket.close":
                break

    types = [m["type"] for m in fake.sent]
    assert types[0] == "session.update"
    sess = fake.sent[0]["session"]
    assert sess["audio"]["input"]["format"] == {"type": "audio/pcmu"}
    assert "SmileCare Dental" in sess["instructions"]
    assert {t["name"] for t in sess["tools"]} >= {"search_knowledge", "request_appointment", "end_call"}
    assert "input_audio_buffer.append" in types
    assert "conversation.item.truncate" in types
    out = next(m for m in fake.sent if m["type"] == "conversation.item.create")
    assert out["item"]["call_id"] == "fc_1" and json.loads(out["item"]["output"])["ok"] is True

    assert hangups and hangups[0][0] == "CABRIDGE" and "<Hangup/>" in hangups[0][1]

    db = SessionLocal()
    call = db.query(VoiceCall).filter_by(id=call_id).one()
    db.close()
    assert call.status == "completed" and call.answered_by == "ai"
    assert [t["role"] for t in call.transcript] == ["assistant", "user"]
    assert call.tool_events[0]["name"] == "end_call"
    assert call.summary == "Caller said bye."
