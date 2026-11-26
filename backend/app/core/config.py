from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "AI Agent SaaS"
    ENV: str = "dev"
    API_KEY_SALT: str = "change-me-super-secret"
    APP_BASE_URL: str = "http://localhost:3000"
    # Comma-separated origins, "*" for any (needed so client websites can embed the
    # widget; safe because auth is the X-API-Key header, not cookies), or a JSON list.
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://app:app@localhost:5432/app"

    # Qdrant
    QDRANT_API_KEY: str | None = None
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "website_chunks"

    # OpenAI
    OPENAI_API_KEY: str | None = None
    OPENAI_CHAT_MODEL: str = "gpt-5.4-mini"
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"

    # AI provider selection
    EMBEDDING_PROVIDER: str = "openai"
    CHAT_PROVIDER: str = "openai"
    SENTENCE_TRANSFORMER_MODEL: str = "all-MiniLM-L6-v2"

    # Ingest
    CRAWL_MAX_PAGES: int = 50
    CRAWL_TIMEOUT_SECONDS: int = 20
    CHUNK_SIZE: int = 900
    CHUNK_OVERLAP: int = 150

    # RAG
    TOP_K: int = 6
    MAX_CONTEXT_CHARS: int = 12000

    # Stripe
    STRIPE_SECRET_KEY: str | None = None
    STRIPE_WEBHOOK_SECRET: str | None = None
    STRIPE_PRICE_STARTER: str | None = None
    STRIPE_PRICE_GROWTH: str | None = None
    STRIPE_PRICE_PRO: str | None = None

    # Voice agent (merged from relay-voice)
    # Public HTTPS base URL of THIS backend, as Twilio sees it (e.g. https://api.example.com).
    # Used to build webhook / media-stream URLs and to validate Twilio signatures.
    PUBLIC_BASE_URL: str | None = None
    # Mini: ~3x cheaper than gpt-realtime-2.1, good for receptionist calls
    REALTIME_MODEL: str = "gpt-realtime-2.1-mini"
    REALTIME_TRANSCRIBE_MODEL: str = "gpt-4o-mini-transcribe"
    REALTIME_VOICE: str = "marin"
    VOICE_TOKEN_SECRET: str | None = None  # falls back to API_KEY_SALT
    VOICE_MAX_WEB_SESSION_SECONDS: int = 600
    VOICE_MAX_PHONE_CALL_SECONDS: int = 1200
    VOICE_CALLBACK_WORKER_ENABLED: bool = True
    VOICE_CALLBACK_POLL_SECONDS: int = 15

    # Twilio (phone calls, missed-call callbacks, SMS booking links)
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_VALIDATE_SIGNATURES: bool = True

    @property
    def allowed_origins(self) -> list[str]:
        raw = (self.ALLOWED_ORIGINS or "").strip()
        if raw.startswith("["):
            import json

            return [str(o).strip() for o in json.loads(raw) if str(o).strip()]
        return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


settings = Settings()