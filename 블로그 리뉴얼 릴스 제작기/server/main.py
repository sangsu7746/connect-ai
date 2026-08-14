import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fastapi import FastAPI
from core.db import init_db, get_conn
from core.seed_data import ensure_seed
from api.categories import router as categories_router

app = FastAPI(title="blog-reels-maker")
init_db()
_conn = get_conn()
ensure_seed(_conn)
_conn.close()

app.include_router(categories_router)

@app.get("/api/health")
def health():
    return {"ok": True}
