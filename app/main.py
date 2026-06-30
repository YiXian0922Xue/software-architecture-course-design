from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.config import ROOT, get_settings


settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0", description="基于 RAG 的实验报告编写智能体")
app.include_router(router)
app.mount("/static", StaticFiles(directory=ROOT / "app" / "static"), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "app" / "static" / "index.html")

