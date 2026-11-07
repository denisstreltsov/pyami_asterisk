"""Callbacks: exceptions are logged, tasks are kept referenced, Async Originate, safe close."""

import asyncio
import gc
import logging

import pytest

from fake_ami import make_client, run_client, wait_for
from pyami_asterisk import AMIClient


class RecordingLog:
    """A logger with the loguru/logging method names; records what was logged."""

    def __init__(self):
        self.records = []

    def __getattr__(self, level):
        return lambda message, *args, **kwargs: self.records.append((level, message))


@pytest.mark.asyncio
async def test_exception_in_a_callback_is_logged_and_the_others_still_run(fake_ami):
    log, seen = RecordingLog(), []

    def broken(event):
        raise ValueError("boom")

    async def broken_async(event):
        raise RuntimeError("boom")

    client = make_client(fake_ami, log=log)
    client.register_event(["*"], broken)
    client.register_event(["Hangup"], broken_async)
    client.register_event(["*"], lambda event: seen.append(event["Event"]))
    async with run_client(client) as task:
        await wait_for(lambda: fake_ami.logins == 1)
        await fake_ami.send({"Event": "Newchannel"})
        await fake_ami.send({"Event": "Hangup"})
        await wait_for(lambda: len(seen) == 2)
        assert not task.done() and client._connected
    assert sorted(seen) == ["Hangup", "Newchannel"]
    assert sum(level == "exception" for level, _ in log.records) == 3


@pytest.mark.asyncio
async def test_exception_in_an_action_callback_is_logged(fake_ami):
    log, answers = RecordingLog(), []

    def broken(answer):
        raise ValueError("boom")

    client = make_client(fake_ami, log=log)
    client.register_event(["*"], lambda event: None)
    client.create_action({"Action": "CoreStatus"}, broken)
    client.create_action({"Action": "CoreSettings"}, answers.append)
    async with run_client(client):
        await wait_for(lambda: answers and log.records)
    assert ("exception" in [level for level, _ in log.records])


@pytest.mark.asyncio
async def test_failing_user_task_is_logged_with_std_logging(fake_ami, caplog):
    async def user_task():
        raise ValueError("boom")

    client = make_client(fake_ami, log=logging.getLogger("pyami-test"))
    client.register_event(["*"], lambda event: None)
    client.create_asyncio_task([user_task()])
    with caplog.at_level(logging.ERROR, logger="pyami-test"):
        async with run_client(client):
            await wait_for(lambda: "Exception in AMI task" in caplog.text)
    assert "ValueError: boom" in caplog.text


@pytest.mark.asyncio
async def test_callback_tasks_survive_garbage_collection(fake_ami):
    done = []

    async def slow(event):
        await asyncio.sleep(0.05)
        gc.collect()
        await asyncio.sleep(0.05)
        done.append(event["Event"])

    client = make_client(fake_ami)
    client.register_event(["*"], slow)
    async with run_client(client):
        await wait_for(lambda: fake_ami.logins == 1)
        for n in range(20):
            await fake_ami.send({"Event": f"E{n}"})
        gc.collect()
        await wait_for(lambda: len(done) == 20)


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["true", "True", True, "yes", "1"])
async def test_async_originate_waits_for_the_originate_response(fake_ami, flag):
    answers = []
    fake_ami.reply("Originate", [{"Message": "Originate successfully queued"},
                                 {"Event": "OriginateResponse", "Response": "Success", "Channel": "PJSIP/100"}])
    client = make_client(fake_ami)
    client.register_event(["*"], lambda event: None)
    client.create_action({"Action": "Originate", "Channel": "PJSIP/100", "Async": flag}, answers.append)
    async with run_client(client):
        await wait_for(lambda: len(answers) == 2)
    assert answers[1]["Event"] == "OriginateResponse"


@pytest.mark.asyncio
async def test_connection_close_without_a_connection_is_safe():
    client = AMIClient()
    await client.connection_close()
    await client.connection_close()


@pytest.mark.asyncio
async def test_connection_close_twice_is_safe(fake_ami):
    client = make_client(fake_ami)
    client.register_event(["*"], lambda event: None)
    async with run_client(client) as task:
        await wait_for(lambda: fake_ami.logins == 1)
        await client.connection_close()
        await client.connection_close()
        await asyncio.wait_for(task, 1)
