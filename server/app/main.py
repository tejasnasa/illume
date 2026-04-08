from contextlib import asynccontextmanager

from app.api.v1 import ws
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Starting up...")
    yield
    print("Shutting down...")


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"])

app.include_router(ws.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
