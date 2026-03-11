import redis.asyncio as aioredis

from src.models.enums import TaskState
from src.models.responses import CrawlResponse

_KEY_PREFIX = "get-docs:job:"
_COMPLETED_TTL = 3600  # 1 hour
_IN_PROGRESS_TTL = 600  # 10 minutes


def _key(job_id: str) -> str:
    return f"{_KEY_PREFIX}{job_id}"


async def create_job(r: aioredis.Redis, job: CrawlResponse) -> None:
    await r.set(_key(job.job_id), job.model_dump_json(), ex=_IN_PROGRESS_TTL)


async def get_job(r: aioredis.Redis, job_id: str) -> CrawlResponse | None:
    data = await r.get(_key(job_id))
    if data is None:
        return None
    return CrawlResponse.model_validate_json(data)


async def update_job(r: aioredis.Redis, job: CrawlResponse) -> None:
    is_terminal = job.status in (TaskState.COMPLETED, TaskState.FAILED)
    ttl = _COMPLETED_TTL if is_terminal else _IN_PROGRESS_TTL
    await r.set(_key(job.job_id), job.model_dump_json(), ex=ttl)
