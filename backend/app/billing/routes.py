import os
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.tenants.models import Tenant
from app.tenants.routes import get_current_tenant

router = APIRouter()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

PRICE_MAP = {
    "starter": os.getenv("STRIPE_PRICE_STARTER"),
    "growth": os.getenv("STRIPE_PRICE_GROWTH"),
    "pro": os.getenv("STRIPE_PRICE_PRO"),
}


@router.post("/checkout")
def create_checkout_session(
    plan: str,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    if plan not in PRICE_MAP or not PRICE_MAP[plan]:
        raise HTTPException(status_code=400, detail="Invalid or missing Stripe price for plan")

    app_base_url = os.getenv("APP_BASE_URL", "http://localhost:3000")

    try:
        customer_id = tenant.stripe_customer_id

        if not customer_id:
            customer = stripe.Customer.create(
                email=tenant.contact_email,
                name=tenant.name,
                metadata={"tenant_id": str(tenant.id)},
            )
            customer_id = customer.id
            tenant.stripe_customer_id = customer_id
            db.commit()
            db.refresh(tenant)

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[
                {
                    "price": PRICE_MAP[plan],
                    "quantity": 1,
                }
            ],
            success_url=f"{app_base_url}?checkout=success",
            cancel_url=f"{app_base_url}?checkout=cancelled",
            metadata={
                "tenant_id": str(tenant.id),
                "plan": plan,
            },
            subscription_data={
                "metadata": {
                    "tenant_id": str(tenant.id),
                    "plan": plan,
                }
            },
        )

        return {"checkout_url": session.url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/portal")
def create_customer_portal(
    tenant: Tenant = Depends(get_current_tenant),
):
    if not tenant.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Stripe customer not found")

    app_base_url = os.getenv("APP_BASE_URL", "http://localhost:3000")

    try:
        session = stripe.billing_portal.Session.create(
            customer=tenant.stripe_customer_id,
            return_url=app_base_url,
        )
        return {"portal_url": session.url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    if not webhook_secret:
        raise HTTPException(status_code=500, detail="Stripe webhook secret missing")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=webhook_secret,
        )
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature")

    event_type = event["type"]
    obj = event["data"]["object"]

    if event_type == "checkout.session.completed":
        tenant_id = obj.get("metadata", {}).get("tenant_id")
        plan = obj.get("metadata", {}).get("plan")
        customer_id = obj.get("customer")
        subscription_id = obj.get("subscription")

        if tenant_id:
            tenant = db.query(Tenant).filter(Tenant.id == int(tenant_id)).first()
            if tenant:
                tenant.stripe_customer_id = customer_id
                tenant.stripe_subscription_id = subscription_id
                tenant.plan_name = plan
                tenant.subscription_status = "active"
                db.commit()

    if event_type in ["customer.subscription.updated", "customer.subscription.deleted"]:
        customer_id = obj.get("customer")
        status = obj.get("status")
        subscription_id = obj.get("id")
        plan = obj.get("metadata", {}).get("plan")

        tenant = db.query(Tenant).filter(Tenant.stripe_customer_id == customer_id).first()
        if tenant:
            tenant.stripe_subscription_id = subscription_id
            tenant.subscription_status = status

            if plan:
                tenant.plan_name = plan

            if event_type == "customer.subscription.deleted":
                tenant.subscription_status = "cancelled"

            db.commit()

    return {"received": True}