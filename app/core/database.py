import re
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

logger = logging.getLogger("kre8.db")

def resolve_db_url(raw: str | None) -> str:
    """Sanitize and normalize database connection string from environment."""
    if not raw or not str(raw).strip():
        logger.info("[Database] No DATABASE_URL provided. Falling back to local SQLite.")
        return "sqlite:///./kre8.db"

    url = str(raw).strip()

    # Strip surrounding quotes or escaped quotes
    while (url.startswith('"') and url.endswith('"')) or (url.startswith("'") and url.endswith("'")):
        url = url[1:-1].strip()

    # Strip accidental 'DATABASE_URL=' prefix from PaaS UI copies
    if url.startswith("DATABASE_URL="):
        url = url.split("DATABASE_URL=", 1)[1].strip()
        while (url.startswith('"') and url.endswith('"')) or (url.startswith("'") and url.endswith("'")):
            url = url[1:-1].strip()

    if not url:
        return "sqlite:///./kre8.db"

    # Normalize dialect prefix for SQLAlchemy (and handle accidentally omitted 'postgresql:' scheme)
    if url.startswith("//"):
        url = "postgresql+psycopg2:" + url
    elif url.startswith("postgres.") or url.startswith("postgres:"):
        url = "postgresql+psycopg2://" + url
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    return url

db_url = resolve_db_url(settings.DATABASE_URL)
is_sqlite = "sqlite" in db_url

engine_kwargs = {}
if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Supabase / PostgreSQL pooling optimization & health checks
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300

try:
    engine = create_engine(db_url, **engine_kwargs)
    if not is_sqlite:
        masked = re.sub(r':([^:@]+)@', ':****@', db_url)
        logger.info(f"[Database] Engine successfully initialized for PostgreSQL ({masked})")
except Exception as e:
    masked = re.sub(r':([^:@]+)@', ':****@', db_url)
    logger.error(f"[Database] Failed to initialize engine with URL '{masked}': {e}. Falling back to SQLite.")
    db_url = "sqlite:///./kre8.db"
    is_sqlite = True
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def ensure_database_schema(bind_engine):
    """Automatically add missing columns in SQLite & PostgreSQL for seamless schema evolution."""
    from sqlalchemy import text
    columns_to_add = [
        ("user_preferences", "ai_provider", "VARCHAR(50) DEFAULT 'gemini'"),
        ("user_preferences", "ai_model", "VARCHAR(100) DEFAULT 'gemini-2.5-flash'"),
        ("user_preferences", "openai_api_key", "VARCHAR(255)"),
        ("user_preferences", "anthropic_api_key", "VARCHAR(255)"),
        ("user_preferences", "groq_api_key", "VARCHAR(255)"),
        ("user_preferences", "openrouter_api_key", "VARCHAR(255)"),
        ("user_preferences", "deepseek_api_key", "VARCHAR(255)"),
        ("scripts", "versions", "JSON"),
        ("creator_watchlist", "avatar_url", "VARCHAR(1000)"),
        ("creator_watchlist", "subscriber_count_text", "VARCHAR(50)"),
        ("creator_watchlist", "pacing_style", "VARCHAR(200)"),
        ("creator_watchlist", "signature_hooks", "JSON"),
        ("social_accounts", "channel_id", "VARCHAR(255)"),
        ("social_accounts", "custom_url", "VARCHAR(500)"),
        ("social_accounts", "total_videos_count", "INTEGER DEFAULT 0"),
        ("social_accounts", "raw_details", "JSON"),
        ("user_preferences", "twitter_client_id", "VARCHAR(255)"),
        ("user_preferences", "twitter_client_secret", "VARCHAR(255)"),
        ("user_preferences", "news_region", "VARCHAR(50) DEFAULT 'GLOBAL'"),
        ("news_articles", "region", "VARCHAR(50) DEFAULT 'GLOBAL'"),
        ("news_articles", "category", "VARCHAR(50) DEFAULT 'general'"),
    ]
    with bind_engine.connect() as conn:
        dialect = bind_engine.dialect.name
        for table, col, col_type in columns_to_add:
            try:
                if dialect == "sqlite":
                    res = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                    existing_cols = [row[1] for row in res]
                    if existing_cols and col not in existing_cols:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                        conn.commit()
                elif dialect in ("postgresql", "postgres"):
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"))
                    conn.commit()
            except Exception as e:
                logger.debug(f"[Database Schema] Note on {table}.{col}: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
