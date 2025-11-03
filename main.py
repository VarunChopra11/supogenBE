from fastapi import FastAPI
from api.v1.routers.auth_routers import auth
from api.v1.routers.auth_routers import discord
from api.v1.routers.documents import router as documents_router
from api.v1.routers.chat import router as chat_router
from fastapi.middleware.cors import CORSMiddleware
from api.v1.db.init_db import init_db, close_db
from contextlib import asynccontextmanager
from api.v1.services.discord_services.discord_bot import run_discord_bot_async
from dotenv import load_dotenv
import asyncio
import uvicorn
import os

load_dotenv(override=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield
    await close_db()

app = FastAPI(lifespan=lifespan)


origins = [
    "https://app.supogen.com",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, tags=["auth"])
app.include_router(discord.router)
app.include_router(chat_router, tags=["chat"])
app.include_router(documents_router, prefix="/documents", tags=["documents"])


@app.get("/wakeup")
async def wakeup():
    return {"status": "awake", "message": "This server is awake."}

@app.head("/wakeup")
async def wakeup_head():
    return

async def start_fastapi():
    """Start FastAPI server on the current event loop."""
    mode = os.getenv("MODE", "development")
    if mode == "development":
        deployment_host = "localhost"
    else:
        deployment_host = "0.0.0.0"
    config = uvicorn.Config("main:app", host=deployment_host, port=8000, reload=False, loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    """Start both FastAPI and the Discord bot on the same event loop."""
    await asyncio.gather(
        start_fastapi(),
        run_discord_bot_async(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")