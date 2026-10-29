import os
import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    # In cloud/Docker/Coolify environments, bind to 0.0.0.0 so external reverse-proxies can reach the container
    is_prod = bool(os.getenv("PORT") or os.getenv("COOLIFY_URL") or os.getenv("RAILWAY_STATIC_URL") or os.getenv("RENDER"))
    host = os.getenv("HOST", "0.0.0.0" if is_prod else "127.0.0.1")
    reload = os.getenv("RELOAD", "false" if is_prod else "true").lower() == "true"

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["app"] if reload else None,
        reload_excludes=["*.db", "*.db-journal", "*.pyc", "__pycache__"] if reload else None,
    )
