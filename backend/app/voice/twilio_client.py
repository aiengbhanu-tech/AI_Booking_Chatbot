"""Minimal Twilio integration over httpx (no extra SDK dependency).

Covers: webhook signature validation, placing outbound calls, redirecting /
hanging up live calls, sending SMS, and TwiML generation.
"""
import base64
import hashlib
import hmac
from urllib.parse import urlencode
from xml.sax.saxutils import escape, quoteattr

import httpx

from app.core.config import settings

API = "https://api.twilio.com/2010-04-01"


class TwilioNotConfigured(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.PUBLIC_BASE_URL)


def public_url(path: str, **query) -> str:
    if not settings.PUBLIC_BASE_URL:
        raise TwilioNotConfigured("PUBLIC_BASE_URL is not set")
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    q = {k: v for k, v in query.items() if v is not None}
    return f"{base}{path}" + (f"?{urlencode(q)}" if q else "")


def media_stream_url() -> str:
    base = public_url("/v1/voice/twilio/media-stream")
    return "wss://" + base.split("://", 1)[1]


# -------------------------
# Signature validation
# -------------------------

def compute_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def validate_signature(url: str, params: dict[str, str], signature: str | None) -> bool:
    if not settings.TWILIO_VALIDATE_SIGNATURES:
        return True
    if not settings.TWILIO_AUTH_TOKEN or not signature:
        return False
    expected = compute_signature(settings.TWILIO_AUTH_TOKEN, url, params)
    return hmac.compare_digest(expected, signature)


# -------------------------
# REST
# -------------------------

def _client() -> httpx.Client:
    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN):
        raise TwilioNotConfigured("Twilio credentials are not set")
    return httpx.Client(
        base_url=f"{API}/Accounts/{settings.TWILIO_ACCOUNT_SID}",
        auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
        timeout=15,
    )


def _post(path: str, data: dict) -> dict:
    with _client() as c:
        r = c.post(path, data={k: v for k, v in data.items() if v is not None})
    if r.status_code >= 400:
        try:
            msg = r.json().get("message")
        except Exception:
            msg = r.text[:300]
        raise RuntimeError(f"Twilio error {r.status_code}: {msg}")
    return r.json()


def create_call(to: str, from_: str, answer_url: str, status_url: str) -> str:
    data = {
        "To": to,
        "From": from_,
        "Url": answer_url,
        "Method": "POST",
        "StatusCallback": status_url,
        "StatusCallbackMethod": "POST",
        "StatusCallbackEvent": "completed",
        # Detect voicemail so the AI doesn't hold a conversation with an answering machine
        "MachineDetection": "Enable",
        "Timeout": "25",
    }
    return _post("/Calls.json", data)["sid"]


def update_call_twiml(call_sid: str, twiml: str) -> None:
    _post(f"/Calls/{call_sid}.json", {"Twiml": twiml})


def send_sms(to: str, from_: str, body: str) -> str:
    return _post("/Messages.json", {"To": to, "From": from_, "Body": body[:1500]})["sid"]


# -------------------------
# TwiML
# -------------------------

def twiml(*verbs: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(verbs) + "</Response>"


def say(text: str) -> str:
    return f"<Say>{escape(text)}</Say>"


def hangup() -> str:
    return "<Hangup/>"


def dial(number: str, action_url: str, timeout: int, caller_id: str | None = None) -> str:
    attrs = f' action={quoteattr(action_url)} method="POST" timeout="{int(timeout)}" answerOnBridge="true"'
    if caller_id:
        attrs += f" callerId={quoteattr(caller_id)}"
    return f"<Dial{attrs}><Number>{escape(number)}</Number></Dial>"


def connect_stream(params: dict[str, str]) -> str:
    p = "".join(f"<Parameter name={quoteattr(k)} value={quoteattr(str(v))}/>" for k, v in params.items())
    return f"<Connect><Stream url={quoteattr(media_stream_url())}>{p}</Stream></Connect>"
