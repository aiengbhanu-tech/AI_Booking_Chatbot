from pathlib import Path

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
from contextlib import asynccontextmanager
from app.core.db import engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WIDGET_DIR = PROJECT_ROOT / "widget"

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=False,
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

if WIDGET_DIR.exists():
    app.mount("/widget", StaticFiles(directory=str(WIDGET_DIR)), name="widget")

@app.get("/health")
def health():
    return {"status": "ok", "env": settings.ENV}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        with engine.connect():
            print("✅ DB connected successfully")
    except Exception as e:
        print("❌ DB connection failed:", e)

    yield

    # Shutdown (optional)
    print("🛑 App shutting down")