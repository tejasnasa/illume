"""
FastAPI application entry point.

Registers all API routers, middleware (CORS, Auth), and handles application lifespan events.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import (
    auth,
    chat,
    contact,
    github_proxy,
    glossary,
    graph,
    guide,
    ownership,
    repository,
    stats,
    ws,
)
from app.core.config import settings
from app.core.health import probe_dependencies
from app.middleware.auth import AuthMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up...")
    yield
    print("Shutting down...")


app = FastAPI(lifespan=lifespan)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws.router)
app.include_router(repository.router)
app.include_router(chat.router)
app.include_router(graph.router)
app.include_router(auth.router)
app.include_router(glossary.router)
app.include_router(ownership.router)
app.include_router(guide.router)
app.include_router(stats.router)
app.include_router(github_proxy.router)
app.include_router(contact.router)


@app.get("/healthz")
async def healthz():
    """Report liveness together with whether each dependency answers.

    Degrades to 503 rather than staying 200: a poller that only looks at the status
    code then treats an instance with no database or no Redis as not ready, which is
    the contract every such probe expects. The body still names which check failed, so
    a 503 is diagnosable without container logs.
    """
    checks = await probe_dependencies()
    healthy = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
