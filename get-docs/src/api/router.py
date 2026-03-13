import uuid
from datetime import datetime, timezone
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.api.redis_store import create_job, get_job, update_job
from src.core.orchestrator import get_docs
from src.models.enums import TaskState
from src.models.requests import GetDocsRequest
from src.models.responses import (
    CrawlCreateResponse,
    CrawlResponse,
    DocPageResponse,
    EthicsInfo,
    JobProgress,
)
from src.utils.http_client import HttpClient
from src.utils.logger import logger

router = APIRouter()


def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis


def get_http_client(request: Request) -> HttpClient:
    return request.app.state.http_client


RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]
HttpClientDep = Annotated[HttpClient, Depends(get_http_client)]


def _build_ethics_info(result) -> EthicsInfo:
    e = result.ethics
    return EthicsInfo(
        robots_crawl_delay_seconds=e.robots_crawl_delay_seconds,
        content_signal_ai_input=e.content_signal_ai_input,
        license_spdx_id=e.license_spdx_id,
        pages_filtered_by_robots=e.pages_filtered_by_robots,
        pages_filtered_by_content_signal=e.pages_filtered_by_content_signal,
    )


def _to_page_responses(pages) -> list[DocPageResponse]:
    return [
        DocPageResponse(
            url=p.url,
            title=p.title,
            content=p.content,
            content_length=len(p.content),
        )
        for p in pages
    ]


async def _run_job(
    job_id: str,
    request: GetDocsRequest,
    redis: aioredis.Redis,
    http_client: HttpClient,
) -> None:
    target = str(request.url or request.github_repo)
    logger.info(f"[job:{job_id}] Starting job for {target}")
    try:
        job = await get_job(redis, job_id)
        if job is None:
            return
        job.status = TaskState.IN_PROGRESS
        job.progress = JobProgress()
        await update_job(redis, job)

        async def on_progress(fetched: int, total: int | None) -> None:
            logger.info(
                f"[job:{job_id}] Progress: {fetched}/{total if total is not None else '?'} pages fetched"
            )
            j = await get_job(redis, job_id)
            if j is None:
                return
            j.progress = JobProgress(pages_fetched=fetched, pages_total=total)
            await update_job(redis, j)

        result = await get_docs(request, http_client, on_progress=on_progress)

        job = await get_job(redis, job_id)
        if job is None:
            return
        job.status = TaskState.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.source_method = result.source_method
        job.github_repo = result.github_repo
        job.pages = _to_page_responses(result.pages)
        job.ethics = _build_ethics_info(result)
        job.request = request
        job.progress = JobProgress(
            pages_fetched=len(result.pages),
            pages_total=len(result.pages),
        )
        await update_job(redis, job)

        logger.info(
            f"[job:{job_id}] Completed via {result.source_method} - {len(result.pages)} pages"
        )

    except Exception:
        logger.exception(f"[job:{job_id}] Failed")
        job = await get_job(redis, job_id)
        if job is None:
            return
        job.status = TaskState.FAILED
        job.completed_at = datetime.now(timezone.utc)
        await update_job(redis, job)


@router.post("/crawl", status_code=202, response_model=CrawlCreateResponse)
async def create_crawl_job(
    request: GetDocsRequest,
    background_tasks: BackgroundTasks,
    redis: RedisDep,
    http_client: HttpClientDep,
) -> CrawlCreateResponse:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    target = str(request.url or request.github_repo)
    logger.info(f"POST /crawl - target={target}, job_id={job_id}")

    job = CrawlResponse(
        job_id=job_id,
        status=TaskState.PENDING,
        created_at=now,
        request=request,
    )
    await create_job(redis, job)

    background_tasks.add_task(_run_job, job_id, request, redis, http_client)

    return CrawlCreateResponse(job_id=job_id, status=TaskState.PENDING, created_at=now)


@router.get("/crawl/{job_id}", response_model=CrawlResponse)
async def get_crawl_job(
    job_id: str, redis: RedisDep, verbose: bool = False
) -> JSONResponse:
    logger.info(f"GET /crawl/{job_id}")
    job = await get_job(redis, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    logger.info(f"GET /crawl/{job_id} - status={job.status}")
    if verbose:
        data = job.model_dump(mode="json")
    else:
        data = job.model_dump(mode="json", exclude={"request", "ethics"})
    return JSONResponse(content=data)
