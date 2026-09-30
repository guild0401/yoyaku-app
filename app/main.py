"""FastAPI アプリ本体。静的ファイル・テンプレート・API ルートをまとめる。"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_config
from . import db
from .routes import public, admin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

app = FastAPI(title="予約アプリ", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
app.include_router(public.router)
app.include_router(admin.router)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    cfg = get_config()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "business_name": cfg.business_name,
            "tagline": cfg.tagline,
            "demo_mode": cfg.demo_mode,
        },
    )
