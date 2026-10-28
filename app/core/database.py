from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def ensure_database_schema(bind_engine):
    """Automatically add missing columns in SQLite for seamless schema evolution."""
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
    ]
    with bind_engine.connect() as conn:
        for table, col, col_type in columns_to_add:
            try:
                # Check if column exists
                res = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                existing_cols = [row[1] for row in res]
                if existing_cols and col not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                    conn.commit()
            except Exception as e:
                print(f"[Database Schema] Note on {table}.{col}: {e}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

