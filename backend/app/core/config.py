from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    APP_NAME: str = "AI Agent SaaS"
    ENV: str = "dev"
    API_KEY_SALT: str = "change-me-super-secret"

    # Database
    DATABASE_URL: str = "postgresql+psycopg2://app:app@localhost:5432/app"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "website_chunks"

    # OpenAI
    OPENAI_API_KEY: str | None = None
    OPENAI_CHAT_MODEL: str = "gpt-5.4-mini"
    OPENAI_EMBED_MODEL: str = "text-embedding-3-small"
    
    # AI provider selection
    EMBEDDING_PROVIDER: str = "sentence_transformers"
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
    APP_BASE_URL: str = "http://localhost:3000"

settings = Settings()