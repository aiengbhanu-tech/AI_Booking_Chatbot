"""Plan limits (must match the pricing cards in the dashboard) and monthly usage.

Limits are hard caps: nothing is allowed past them. Tenants without an active
paid plan get the minimum (Starter) limits. Usage resets on the 1st of each
month (UTC).
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.analytics.models import ChatMessage
from app.core.db import get_db
from app.core.security import get_current_tenant
from app.tenants.models import Tenant


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    chats_per_month: int | None  # None = unlimited
    voice_minutes_per_month: int
    phone_receptionist: bool     # phone line, AI answers calls
    missed_call_callbacks: bool
    sms_booking_link: bool
    call_summaries: bool
    live_transfer: bool


PLANS: dict[str, Plan] = {
    "starter": Plan("starter", "Starter", 1000, 100, False, False, False, False, False),
    "growth": Plan("growth", "Growth", 3000, 400, True, True, True, True, False),
    "pro": Plan("pro", "Pro", None, 1200, True, True, True, True, True),
}
MINIMUM_PLAN = "starter"
# past_due keeps access during Stripe's payment-retry window
ACTIVE_STATUSES = ("active", "trialing", "past_due")

# Don't start a voice session that can't hold a meaningful conversation
MIN_WEB_VOICE_SECONDS = 30
MIN_PHONE_VOICE_SECONDS = 60


def plan_for(tenant: Tenant | None) -> Plan:
    if tenant and tenant.plan_name in PLANS and (tenant.subscription_status or "") in ACTIVE_STATUSES:
        return PLANS[tenant.plan_name]
    return PLANS[MINIMUM_PLAN]


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month_start(now: datetime | None = None) -> datetime:
    start = month_start(now)
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)


# -------------------------
# Chats (a "chat" = one conversation/session in the month)
# -------------------------

def chats_used(db: Session, tenant_id: int) -> int:
    return int(
        db.query(func.count(func.distinct(ChatMessage.session_id)))
        .filter(ChatMessage.tenant_id == tenant_id, ChatMessage.created_at >= month_start())
        .scalar()
        or 0
    )


def can_chat(db: Session, tenant: Tenant, session_id: str | None) -> bool:
    """Ongoing conversations always continue; new ones only start within the limit."""
    limit = plan_for(tenant).chats_per_month
    if limit is None:
        return True
    if session_id:
        seen = (
            db.query(ChatMessage.id)
            .filter(
                ChatMessage.tenant_id == tenant.id,
                ChatMessage.session_id == session_id,
                ChatMessage.created_at >= month_start(),
            )
            .first()
        )
        if seen:
            return True
    return chats_used(db, tenant.id) < limit


def chat_limit_message(tenant: Tenant) -> str:
    return (
        f"Sorry, our online assistant is unavailable right now. "
        f"Please leave your details and the {tenant.name} team will get back to you."
    )


# -------------------------
# AI voice minutes (widget realtime voice + phone calls handled by the AI)
# -------------------------

def voice_seconds_used(db: Session, tenant_id: int) -> int:
    """Finished AI calls count their real duration; calls still running count their
    full reserved length, so parallel calls can never overrun the plan."""
    from app.voice.models import VoiceCall  # local import: voice depends on plans

    rows = (
        db.query(VoiceCall.ended_at, VoiceCall.duration_seconds, VoiceCall.max_seconds)
        .filter(
            VoiceCall.tenant_id == tenant_id,
            VoiceCall.answered_by == "ai",
            VoiceCall.started_at >= month_start(),
        )
        .all()
    )
    total = 0
    for ended_at, duration, reserved in rows:
        total += (duration or 0) if ended_at else (reserved or 0)
    return total


def voice_seconds_remaining(db: Session, tenant: Tenant) -> int:
    limit = plan_for(tenant).voice_minutes_per_month * 60
    return max(0, limit - voice_seconds_used(db, tenant.id))


def usage_snapshot(db: Session, tenant: Tenant) -> dict:
    plan = plan_for(tenant)
    used_voice = voice_seconds_used(db, tenant.id)
    return {
        "plan": asdict(plan),
        "plan_active": plan.key == tenant.plan_name,
        "period_start": month_start().isoformat(),
        "resets_at": next_month_start().isoformat(),
        "chats_used": chats_used(db, tenant.id),
        "chats_limit": plan.chats_per_month,
        "voice_minutes_used": round(used_voice / 60, 1),
        "voice_minutes_limit": plan.voice_minutes_per_month,
        "voice_seconds_remaining": max(0, plan.voice_minutes_per_month * 60 - used_voice),
    }


router = APIRouter()


@router.get("")
def get_usage(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    return usage_snapshot(db, tenant)
