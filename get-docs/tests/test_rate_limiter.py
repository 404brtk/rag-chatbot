import asyncio

import pytest

from src.utils.rate_limiter import fetch_with_rate_limit


@pytest.fixture()
def _patch_time(mocker):
    mocker.patch("src.utils.rate_limiter.time.monotonic", return_value=1000.0)
    mocker.patch("src.utils.rate_limiter.asyncio.sleep", new_callable=mocker.AsyncMock)


class TestFetchWithRateLimit:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_patch_time")
    async def test_concurrency_bounded(self):
        max_active = 0
        active = 0

        async def fetch(item):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0)
            active -= 1
            return item * 10

        results = await fetch_with_rate_limit(
            list(range(10)),
            fetch,
            max_concurrent=3,
            delay_seconds=0,
        )

        assert max_active <= 3
        assert len(results) == 10

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_patch_time")
    async def test_order_preserved(self):
        async def fetch(item):
            return item * 2

        results = await fetch_with_rate_limit(
            [1, 2, 3, 4, 5],
            fetch,
            max_concurrent=5,
            delay_seconds=0,
        )

        items = [item for item, _ in results]
        assert items == [1, 2, 3, 4, 5]
        values = [result for _, result in results]
        assert values == [2, 4, 6, 8, 10]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_patch_time")
    async def test_exceptions_returned_not_raised(self):
        async def fetch(item):
            if item == 2:
                raise ValueError("boom")
            return item * 10

        results = await fetch_with_rate_limit(
            [1, 2, 3],
            fetch,
            max_concurrent=3,
            delay_seconds=0,
        )

        assert len(results) == 3
        assert results[0] == (1, 10)
        assert isinstance(results[1][1], ValueError)
        assert results[2] == (3, 30)

    @pytest.mark.asyncio
    async def test_empty_items(self):
        async def fetch(item):
            return item

        results = await fetch_with_rate_limit([], fetch)
        assert results == []

    @pytest.mark.asyncio
    async def test_delay_enforced(self, mocker):
        timestamps: list[float] = []
        real_monotonic_val = 0.0

        def fake_monotonic():
            return real_monotonic_val

        mocker.patch(
            "src.utils.rate_limiter.time.monotonic", side_effect=fake_monotonic
        )

        original_sleep = asyncio.sleep

        async def fake_sleep(delay):
            nonlocal real_monotonic_val
            real_monotonic_val += delay
            await original_sleep(0)

        mocker.patch("src.utils.rate_limiter.asyncio.sleep", side_effect=fake_sleep)

        async def fetch(item):
            timestamps.append(real_monotonic_val)
            return item

        await fetch_with_rate_limit(
            [1, 2, 3],
            fetch,
            max_concurrent=1,
            delay_seconds=2.0,
        )

        assert len(timestamps) == 3
        for i in range(1, len(timestamps)):
            gap = timestamps[i] - timestamps[i - 1]
            assert gap >= 2.0, f"Gap between request {i - 1} and {i} was {gap}s"

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_patch_time")
    async def test_progress_callback(self):
        progress_calls: list[tuple[int, int]] = []

        async def on_progress(completed, total):
            progress_calls.append((completed, total))

        async def fetch(item):
            return item

        await fetch_with_rate_limit(
            [1, 2, 3],
            fetch,
            max_concurrent=3,
            delay_seconds=0,
            on_progress=on_progress,
        )

        assert len(progress_calls) == 3
        totals = [t for _, t in progress_calls]
        assert all(t == 3 for t in totals)
        completed_values = sorted(c for c, _ in progress_calls)
        assert completed_values == [1, 2, 3]
