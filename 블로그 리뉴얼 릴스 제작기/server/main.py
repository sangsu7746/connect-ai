import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from core.db import init_db, get_conn
from core.seed_data import ensure_seed
from core.image_gen import images_dir
from api.categories import router as categories_router
from api.trends import router as trends_router
from api.discover import router as discover_router
from api.scripts import router as scripts_router
from api.articles import router as articles_router
from api.images import router as images_router

app = FastAPI(title="blog-reels-maker")
init_db()
_conn = get_conn()
ensure_seed(_conn)
_conn.close()

app.include_router(categories_router)
app.include_router(trends_router)
app.include_router(discover_router)
app.include_router(scripts_router)
app.include_router(articles_router)
app.include_router(images_router)
app.mount("/images", StaticFiles(directory=str(images_dir())), name="images")

@app.get("/api/health")
def health():
    return {"ok": True}
