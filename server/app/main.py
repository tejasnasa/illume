from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import chat, health, repository, ws, graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up...")
    yield
    print("Shutting down...")


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"])

app.include_router(ws.router)
app.include_router(repository.router)
app.include_router(chat.router)
app.include_router(health.router)
app.include_router(graph.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
