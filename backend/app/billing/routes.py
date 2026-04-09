import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.security import get_current_tenant
from app.tenants.models import Tenant

router = APIRouter()

def get_stripe():
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


@router.post("/checkout")
def create_checkout(
    plan: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    stripe_client = get_stripe()
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    price_map = {
        "starter": settings.STRIPE_PRICE_STARTER,
        "growth": settings.STRIPE_PRICE_GROWTH,
        "pro": settings.STRIPE_PRICE_PRO,
    }

    price_id = price_map.get(plan)
    if not price_id:
        raise HTTPException(status_code=400, detail="Invalid plan")

    checkout = stripe_client.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{settings.APP_BASE_URL}/billing?success=1",
        cancel_url=f"{settings.APP_BASE_URL}/billing?canceled=1",
        metadata={"tenant_id": str(tenant.id), "plan": plan},
    )

    return {
        "checkout_url": checkout.url,
        "plan": plan,
    }


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Stripe webhook not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        tenant_id = session.get("metadata", {}).get("tenant_id")
        plan = session.get("metadata", {}).get("plan")

        if tenant_id:
            tenant = db.query(Tenant).filter(Tenant.id == int(tenant_id)).first()
            if tenant:
                tenant.stripe_customer_id = session.get("customer")
                tenant.plan_name = plan
                tenant.subscription_status = "active"
                db.add(tenant)
                db.commit()

    return {"received": True}