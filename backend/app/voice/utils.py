import hashlib
import hmac
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


def _secret() -> bytes:
    return (settings.VOICE_TOKEN_SECRET or settings.API_KEY_SALT).encode("utf-8")


def sign_token(*parts: object) -> str:
    """HMAC token binding a voice session to its ids (used for widget voice + media streams)."""
    msg = ":".join(str(p) for p in parts).encode("utf-8")
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:40]


def verify_token(token: str | None, *parts: object) -> bool:
    if not token:
        return False
    return hmac.compare_digest(token, sign_token(*parts))


def normalize_phone(raw: str | None, default_country_code: str = "+1") -> str | None:
    """Best-effort E.164 normalisation. Returns None when the value can't be a phone number."""
    if not raw:
        return None
    raw = raw.strip()
    has_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("00") and not has_plus:
        digits, has_plus = digits[2:], True
    if not digits:
        return None
    if has_plus:
        candidate = "+" + digits
    else:
        cc = re.sub(r"\D", "", default_country_code or "")
        if cc and digits.startswith(cc) and len(digits) > 10:
            candidate = "+" + digits
        else:
            candidate = "+" + cc + digits
    # E.164: max 15 digits, realistic minimum 8
    if not 8 <= len(candidate) - 1 <= 15:
        return None
    return candidate


def tz_or_utc(name: str | None):
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def next_allowed_call_time(
    desired: datetime,
    tz_name: str | None,
    start_hour: int,
    end_hour: int,
) -> datetime:
    """Move `desired` (aware, any tz) into the tenant's permitted calling window.

    Callers must not be phoned at night. If start_hour >= end_hour the window is
    treated as "always allowed" to avoid locking callbacks forever on bad config.
    """
    if desired.tzinfo is None:
        desired = desired.replace(tzinfo=timezone.utc)
    start_hour = max(0, min(23, int(start_hour)))
    end_hour = max(1, min(24, int(end_hour)))
    if start_hour >= end_hour:
        return desired

    tz = tz_or_utc(tz_name)
    local = desired.astimezone(tz)
    window_start = local.replace(hour=start_hour, minute=0, second=0, microsecond=0)

    if local.hour < start_hour:
        local = window_start
    elif local.hour >= end_hour:
        local = window_start + timedelta(days=1)

    return local.astimezone(timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
