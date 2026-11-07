"""ordered_events: callbacks of consecutive events do not interleave."""

import asyncio
import random

import pytest

from fake_ami import make_client, run_client, wait_for


async def run_with(fake_ami, **config):
    log = []

    async def slow(event):
        log.append(("start", event["N"]))
        await asyncio.sleep(random.uniform(0, 0.01))
        log.append(("end", event["N"]))

    client = make_client(fake_ami, **config)
    client.register_event(["Step"], slow)
    async with run_client(client):
        await wait_for(lambda: fake_ami.logins == 1)
        for n in range(30):
            await fake_ami.send({"Event": "Step", "N": n})
        await wait_for(lambda: len(log) == 60)
    return log


@pytest.mark.asyncio
async def test_ordered_events_are_handled_one_after_another(fake_ami):
    log = await run_with(fake_ami, ordered_events=True)
    expected = [(stage, str(n)) for n in range(30) for stage in ("start", "end")]
    assert log == expected


@pytest.mark.asyncio
async def test_default_keeps_1_5_2_concurrency(fake_ami):
    random.seed(1)
    log = await run_with(fake_ami)
    starts = [n for stage, n in log if stage == "start"]
    assert sorted(starts, key=int) == [str(n) for n in range(30)]
    assert log != [(stage, str(n)) for n in range(30) for stage in ("start", "end")]


@pytest.mark.asyncio
async def test_a_failing_callback_does_not_stall_the_order(fake_ami):
    seen = []

    async def sometimes_broken(event):
        if event["N"] == "1":
            raise ValueError("boom")
        seen.append(event["N"])

    client = make_client(fake_ami, ordered_events=True)
    client.register_event(["Step"], sometimes_broken)
    async with run_client(client):
        await wait_for(lambda: fake_ami.logins == 1)
        for n in range(3):
            await fake_ami.send({"Event": "Step", "N": n})
        await wait_for(lambda: len(seen) == 2)
    assert seen == ["0", "2"]
