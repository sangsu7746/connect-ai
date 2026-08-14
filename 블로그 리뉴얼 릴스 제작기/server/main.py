import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fastapi import FastAPI
from core.db import init_db

app = FastAPI(title="blog-reels-maker")
init_db()

@app.get("/api/health")
def health():
    return {"ok": True}
