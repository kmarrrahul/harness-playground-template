"""
Infra Agent — FastAPI application routes.

Provides SSE-streamed AI agent sessions for AWS/Terraform/Filesystem operations.
Supports multiple AI providers: GitHub Copilot, Google Antigravity (and future
providers: Cursor, Claude Agent).
"""
from __future__ import annotations

import os
import pathlib
import logging
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .dependencies import APP_SESSION_KEY

logging.basicConfig(
    level=logging.DEBUG,
    format="%(levelname)s:%(name)s:%(message)s",
)
# Keep third-party loggers quiet so our CLI output isn't drowned out
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("fastapi").setLevel(logging.INFO)
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────
_APP_DIR = pathlib.Path(__file__).resolve().parent
_STATIC = _APP_DIR / "static"
_TEMPLATES = _APP_DIR / "templates"

# ── Base path (for reverse-proxy setups like /agents/infra-playground/) ────
_BASE_PATH = os.environ.get("BASE_PATH", "").strip("/")
if _BASE_PATH:
    _BASE_PATH = "/" + _BASE_PATH + "/"
else:
    _BASE_PATH = "/"

app = FastAPI(docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATES))

# ── Routers ──────────────────────────────────────────────────────────────────
from .routers import core, auth, skills, agent

app.include_router(core.router)
app.include_router(auth.router)
app.include_router(skills.router)
app.include_router(agent.router)

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {
        "base_path": _BASE_PATH,
        "encryption_key": APP_SESSION_KEY
    })
