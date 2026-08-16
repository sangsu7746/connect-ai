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
from api.render import router as render_router, videos_dir

app = FastAPI(title="blog-reels-maker")
init_db()
_conn = get_conn()
ensure_seed(_conn)
# 서버가 running 잡 도중 죽었다 재시작한 경우 — 그 행들은 영원히 done이
# 안 돼서 has_running()이 계속 409를 반환한다. 시작 시 정리한다 (C2).
_conn.execute("UPDATE jobs SET status='error', error='서버 재시작으로 중단' "
              "WHERE status='running'")
_conn.commit()
_conn.close()

app.include_router(categories_router)
app.include_router(trends_router)
app.include_router(discover_router)
app.include_router(scripts_router)
app.include_router(articles_router)
app.include_router(images_router)
app.include_router(render_router)
app.mount("/images", StaticFiles(directory=str(images_dir())), name="images")
app.mount("/videos", StaticFiles(directory=str(videos_dir())), name="videos")

@app.get("/api/health")
def health():
    return {"ok": True}
