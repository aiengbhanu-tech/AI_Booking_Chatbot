from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.tenants.routes import router as tenants_router
from app.ingest.service import router as ingest_router
from app.rag.routes import router as rag_router
from app.leads.routes import router as leads_router
from app.analytics.routes import router as analytics_router
from app.widget.routes import router as widget_router
from app.billing.routes import router as billing_router

app = FastAPI(title=settings.APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tenants_router, prefix="/v1/tenants", tags=["tenants"])
app.include_router(ingest_router, prefix="/v1/ingest", tags=["ingest"])
app.include_router(rag_router, prefix="/v1", tags=["chat"])
app.include_router(leads_router, prefix="/v1/leads", tags=["leads"])
app.include_router(analytics_router, prefix="/v1/analytics", tags=["analytics"])
app.include_router(widget_router, prefix="/v1/widget", tags=["widget"])
app.include_router(billing_router, prefix="/v1/billing", tags=["billing"])

app.mount("/widget", StaticFiles(directory="../widget"), name="widget")


@app.get("/health")
def health():
    return {"status": "ok", "env": settings.ENV}