from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    auth,
    chat,
    glossary,
    graph,
    guide,
    ownership,
    repository,
    ws,
)
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
    allow_origins=["http://localhost:3000"],
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


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
