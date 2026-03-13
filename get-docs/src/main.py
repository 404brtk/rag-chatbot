from contextlib import asynccontextmanager

import httpx
import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI

from src.api.router import router
from src.config import settings
from src.utils.http_client import HttpClient


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_pool = aioredis.ConnectionPool.from_url(
        settings.REDIS_URL,
        max_connections=3,
        decode_responses=True,
    )
    app.state.redis = aioredis.Redis(connection_pool=redis_pool)
    app.state.http_client = HttpClient(
        httpx.AsyncClient(
            headers={"User-Agent": settings.USER_AGENT},
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
        ),
    )
    yield
    await app.state.http_client.aclose()
    await redis_pool.disconnect()


app = FastAPI(title="get-docs", lifespan=lifespan)
app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, reload=True)
