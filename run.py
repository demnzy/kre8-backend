import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        # Only reload on source changes so DB writes / bytecode don't kill in-flight requests
        reload_dirs=["app"],
        reload_excludes=["*.db", "*.db-journal", "*.pyc", "__pycache__"],
    )
