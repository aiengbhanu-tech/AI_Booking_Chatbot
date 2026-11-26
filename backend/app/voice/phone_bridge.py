"""Bridge a Twilio Media Stream (phone audio, G.711 μ-law 8 kHz) to OpenAI Realtime.

Twilio  --media(base64 μ-law)-->  us  --input_audio_buffer.append-->  OpenAI
Twilio  <--media / clear / mark--  us  <--response.output_audio.delta--  OpenAI

Handles barge-in (caller talks over the agent), tool calls, transfer/hang-up
after the agent finishes speaking, and a hard max call duration.
"""
import asyncio
import json
import time

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect as ws_connect

from app.core.config import settings
from app.core.db import SessionLocal
from app.tenants.models import Tenant
from app.voice import twilio_client
from app.voice.calls import finalize_call
from app.voice.models import VoiceCall, VoiceCallback
from app.voice.prompts import build_instructions, greeting_instruction, session_config
from app.voice.service import get_voice_settings, lock_and_remaining_seconds
from app.voice.tools import ToolContext, execute_tool, tools_for
from app.voice.utils import verify_token

REALTIME_URL = "wss://api.openai.com/v1/realtime?model={model}"
WRAP_UP_SECONDS = 30


def _load(call_id: int):
    # Objects are used after the session closes, so keep their loaded state on commit.
    db = SessionLocal(expire_on_commit=False)
    try:
        call = db.query(VoiceCall).filter(VoiceCall.id == call_id).first()
        if not call:
            return None
        tenant = db.query(Tenant).filter(Tenant.id == call.tenant_id).first()
        vs = get_voice_settings(db, call.tenant_id)
        cb_context = None
        if call.callback_id:
            cb = db.query(VoiceCallback).filter(VoiceCallback.id == call.callback_id).first()
            if cb:
                cb.status = "in_progress"
                cb_context = cb.context
        # Reserve this call's maximum length from the plan's monthly AI minutes
        _, remaining = lock_and_remaining_seconds(db, call.tenant_id)
        call.max_seconds = min(settings.VOICE_MAX_PHONE_CALL_SECONDS, remaining)
        call.status = "ai_active"
        call.answered_by = "ai"
        db.commit()
        db.expunge_all()
        return call, tenant, vs, cb_context
    finally:
        db.close()


class PhoneSession:
    def __init__(self, twilio_ws: WebSocket):
        self.tw = twilio_ws
        self.oa = None
        self.stream_sid: str | None = None
        self.call: VoiceCall | None = None
        self.ctx: ToolContext | None = None
        self.transcript: list[dict] = []
        self.tool_events: list[dict] = []
        self.started = time.time()
        # barge-in bookkeeping
        self.latest_media_ts = 0
        self.response_start_ts: int | None = None
        self.last_assistant_item: str | None = None
        self.mark_queue: list[str] = []
        # deferred control (hangup / transfer) once the goodbye has been played
        self.pending_control: dict | None = None
        self.control_armed = False
        self.closed = False

    # ---------- Twilio helpers ----------
    async def tw_send(self, msg: dict):
        if self.stream_sid and not self.closed:
            await self.tw.send_text(json.dumps({**msg, "streamSid": self.stream_sid}))

    async def oa_send(self, msg: dict):
        if self.oa is not None:
            await self.oa.send(json.dumps(msg))

    # ---------- lifecycle ----------
    async def run(self):
        await self.tw.accept()
        try:
            start = await self._wait_for_start()
            if not start:
                return
            params = start.get("customParameters") or {}
            try:
                call_id = int(params.get("voice_call_id", "0"))
            except ValueError:
                return
            if not verify_token(params.get("token"), "stream", call_id):
                print("[PHONE BRIDGE] rejected stream with bad token")
                return
            loaded = await asyncio.to_thread(_load, call_id)
            if not loaded or not settings.OPENAI_API_KEY:
                return
            self.call, tenant, vs, cb_context = loaded
            self.ctx = ToolContext(
                tenant_id=tenant.id,
                channel="phone",
                voice_call_id=self.call.id,
                caller_phone=self.call.from_number if self.call.direction == "inbound" else self.call.to_number,
                call_sid=self.call.provider_call_sid,
            )
            instructions = build_instructions(
                tenant, vs, "phone",
                caller_phone=self.ctx.caller_phone,
                direction=self.call.direction,
                callback_context=cb_context,
            )
            cfg = session_config(instructions, tools_for("phone", tenant, vs), vs, phone=True)

            async with ws_connect(
                REALTIME_URL.format(model=settings.REALTIME_MODEL),
                additional_headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                max_size=None,
                open_timeout=15,
            ) as oa:
                self.oa = oa
                await self.oa_send({"type": "session.update", "session": cfg})
                await self.oa_send({"type": "response.create", "response": {
                    "instructions": greeting_instruction(tenant, vs, "phone", self.call.direction)}})
                tasks = [
                    asyncio.create_task(self._from_twilio()),
                    asyncio.create_task(self._from_openai()),
                    asyncio.create_task(self._watchdog()),
                ]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in tasks:
                    t.cancel()
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print("[PHONE BRIDGE ERROR]", repr(e))
        finally:
            self.closed = True
            if self.call:
                await asyncio.to_thread(
                    finalize_call, self.call.id, self.transcript, self.tool_events,
                    int(time.time() - self.started),
                )
            try:
                await self.tw.close()
            except Exception:
                pass

    async def _wait_for_start(self) -> dict | None:
        while True:
            msg = json.loads(await self.tw.receive_text())
            if msg.get("event") == "start":
                self.stream_sid = msg["start"]["streamSid"]
                return msg["start"]
            if msg.get("event") == "stop":
                return None

    async def _watchdog(self):
        """Never exceed the minutes reserved for this call: ask the AI to wrap up
        30 seconds before the limit, then hang up at the limit."""
        limit = self.call.max_seconds if self.call and self.call.max_seconds is not None             else settings.VOICE_MAX_PHONE_CALL_SECONDS
        wrap_at = max(0, limit - WRAP_UP_SECONDS)
        await asyncio.sleep(wrap_at)
        if limit > WRAP_UP_SECONDS:
            await self.oa_send({"type": "response.create", "response": {"instructions": (
                "Time is almost up for this call. Politely tell the caller you need to wrap up, "
                "offer to have the team call them back if they still need help (use request_callback), "
                "then say goodbye and call end_call.")}})
        await asyncio.sleep(limit - wrap_at)
        print("[PHONE BRIDGE] call reached its time limit; hanging up")
        await self._do_control({"type": "hangup"})

    # ---------- Twilio -> OpenAI ----------
    async def _from_twilio(self):
        while True:
            msg = json.loads(await self.tw.receive_text())
            ev = msg.get("event")
            if ev == "media":
                self.latest_media_ts = int(msg["media"].get("timestamp", 0))
                await self.oa_send({"type": "input_audio_buffer.append", "audio": msg["media"]["payload"]})
            elif ev == "mark":
                name = (msg.get("mark") or {}).get("name")
                if self.mark_queue:
                    self.mark_queue.pop(0)
                if name == "control" and self.pending_control:
                    await self._do_control(self.pending_control)
            elif ev == "stop":
                return

    # ---------- OpenAI -> Twilio ----------
    async def _from_openai(self):
        async for raw in self.oa:
            ev = json.loads(raw)
            t = ev.get("type")

            if t == "response.output_audio.delta":
                await self.tw_send({"event": "media", "media": {"payload": ev["delta"]}})
                if self.response_start_ts is None:
                    self.response_start_ts = self.latest_media_ts
                if ev.get("item_id"):
                    self.last_assistant_item = ev["item_id"]
                await self.tw_send({"event": "mark", "mark": {"name": "audio"}})
                self.mark_queue.append("audio")

            elif t == "input_audio_buffer.speech_started":
                await self._barge_in()

            elif t == "conversation.item.input_audio_transcription.completed":
                text = (ev.get("transcript") or "").strip()
                if text:
                    self.transcript.append({"role": "user", "text": text, "t": round(time.time() - self.started, 1)})

            elif t == "response.output_audio_transcript.done":
                text = (ev.get("transcript") or "").strip()
                if text:
                    self.transcript.append({"role": "assistant", "text": text, "t": round(time.time() - self.started, 1)})

            elif t == "response.done":
                self.response_start_ts = None
                await self._handle_response_done(ev.get("response") or {})

            elif t == "error":
                print("[REALTIME ERROR]", ev.get("error"))

    async def _barge_in(self):
        if self.mark_queue and self.response_start_ts is not None and self.last_assistant_item:
            elapsed = max(0, self.latest_media_ts - self.response_start_ts)
            await self.oa_send({
                "type": "conversation.item.truncate",
                "item_id": self.last_assistant_item,
                "content_index": 0,
                "audio_end_ms": elapsed,
            })
        await self.tw_send({"event": "clear"})
        self.mark_queue.clear()
        self.last_assistant_item = None
        self.response_start_ts = None

    async def _handle_response_done(self, response: dict):
        calls = [o for o in response.get("output") or [] if o.get("type") == "function_call"]

        if not calls:
            # The agent just finished a spoken turn. If a hangup/transfer is waiting,
            # fire it once Twilio confirms the audio has played (mark "control").
            if self.pending_control and not self.control_armed:
                self.control_armed = True
                await self.tw_send({"event": "mark", "mark": {"name": "control"}})
                # Fallback in case the mark never comes back
                asyncio.create_task(self._control_fallback())
            return

        for fc in calls:
            name = fc.get("name")
            try:
                args = json.loads(fc.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            t0 = time.time()
            result = await asyncio.to_thread(execute_tool, self.ctx, name, args)
            self.tool_events.append({
                "name": name, "args": args, "ok": bool(result.get("ok")),
                "ms": int((time.time() - t0) * 1000), "t": round(t0 - self.started, 1),
            })
            await self.oa_send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": fc.get("call_id"), "output": json.dumps(result)}})

        for c in self.ctx.controls:
            if c["type"] in ("hangup", "transfer"):
                self.pending_control = c
        self.ctx.controls.clear()
        await self.oa_send({"type": "response.create"})

    async def _control_fallback(self):
        await asyncio.sleep(12)
        if self.pending_control:
            await self._do_control(self.pending_control)

    async def _do_control(self, control: dict):
        self.pending_control = None
        sid = self.call.provider_call_sid if self.call else None
        if not sid:
            return
        try:
            if control["type"] == "transfer":
                caller_id = self.call.to_number if self.call.direction == "inbound" else self.call.from_number
                tw = twilio_client.twiml(twilio_client.dial(control["to"], twilio_client.public_url(
                    "/v1/voice/twilio/transfer-complete"), 25, caller_id=caller_id))
            else:
                tw = twilio_client.twiml(twilio_client.hangup())
            await asyncio.to_thread(twilio_client.update_call_twiml, sid, tw)
        except Exception as e:
            print("[PHONE CONTROL ERROR]", repr(e))


async def handle_media_stream(ws: WebSocket):
    await PhoneSession(ws).run()
