import os
from pathlib import Path
from dotenv import load_dotenv
from typing import List

# Load .env file from kre8-backend directory or project root
backend_dir = Path(__file__).resolve().parent.parent.parent
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

class Settings:
    PROJECT_NAME: str = "Kre8 Creator API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api"
    
    # Secret key for JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "kre8_super_secret_jwt_key_2026_creator_dashboard")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./kre8.db")
    
    # CORS
    _cors_env = os.getenv("CORS_ORIGINS", "")
    CORS_ORIGINS: List[str] = [
        orig.strip() for orig in _cors_env.split(",") if orig.strip()
    ] if _cors_env else [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://localhost:3000",
    ]
    
    # Gemini API Key & Model Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # News API Key (NewsAPI.org or GNews.io)
    NEWS_API_KEY: str = os.getenv("NEWS_API_KEY", "")

settings = Settings()
