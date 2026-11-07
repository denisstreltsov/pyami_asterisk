"""Reconnect: one loop, no recursion, no duplicated Ping/repeat tasks, no leaked sockets."""

import asyncio
import traceback

import pytest

from fake_ami import FakeAmi, make_client, run_client, wait_for

FAST = dict(reconnect_timeout=0.01)


def keep_open(client):
    """With no pattern registered 1.5.2 closes the connection as soon as nothing is pending."""
    client.register_event(["*"], lambda event: None)


@pytest.mark.asyncio
async def test_thirty_drops_in_a_row_reconnect_without_recursion(fake_ami):
    client = make_client(fake_ami, **FAST)
    keep_open(client)
    depths = []
    login = client._login

    async def login_recording_stack_depth():
        depths.append(len(traceback.extract_stack()))
        return await login()

    client._login = login_recording_stack_depth
    async with run_client(client) as task:
        for n in range(1, 31):
            await wait_for(lambda: fake_ami.logins == n and fake_ami.clients)
            fake_ami.drop()
        await wait_for(lambda: fake_ami.logins == 31)
        assert not task.done()
        assert client._connected is True
        assert len(set(depths)) == 1, depths  # 1.5.2 nests one connect_ami per reconnect


@pytest.mark.asyncio
async def test_shutdown_event_reconnects_and_closes_the_old_socket(fake_ami):
    client = make_client(fake_ami, **FAST)
    keep_open(client)
    async with run_client(client):
        await wait_for(lambda: fake_ami.logins == 1)
        # the server keeps the old connection open; the client must close it itself
        await fake_ami.send({"Event": "Shutdown", "Shutdown": "Cleanly", "Restart": "True"})
        await wait_for(lambda: fake_ami.logins == 2)
        await wait_for(lambda: len(fake_ami._writers) == 1)


@pytest.mark.asyncio
async def test_ping_runs_once_after_reconnects(fake_ami):
    client = make_client(fake_ami, ping_delay=0.05, **FAST)
    keep_open(client)
    async with run_client(client):
        for n in range(1, 5):
            await wait_for(lambda: fake_ami.logins == n and fake_ami.clients)
            await asyncio.sleep(0.06)
            fake_ami.drop()
        await wait_for(lambda: fake_ami.logins == 5)
        assert len(client._connection_tasks) == 1
        before = len(fake_ami.actions("Ping"))
        await asyncio.sleep(0.5)
        pings = len(fake_ami.actions("Ping")) - before
        assert 5 <= pings <= 13  # one loop every 0.05 s; five loops would give ~50


@pytest.mark.asyncio
async def test_repeated_action_is_resumed_exactly_once(fake_ami):
    answers = []
    client = make_client(fake_ami, **FAST)
    keep_open(client)
    client.create_action({"Action": "CoreStatus"}, answers.append, repeat=0.05)
    async with run_client(client):
        for n in range(1, 4):
            await wait_for(lambda: fake_ami.logins == n and fake_ami.clients)
            await asyncio.sleep(0.06)
            fake_ami.drop()
        await wait_for(lambda: fake_ami.logins == 4)
        await wait_for(lambda: answers)
        assert len(client._connection_tasks) == 1
        before = len(fake_ami.actions("CoreStatus"))
        await asyncio.sleep(0.5)
        assert 5 <= len(fake_ami.actions("CoreStatus")) - before <= 13


@pytest.mark.asyncio
async def test_pbx_down_for_a_while_then_back():
    server = await FakeAmi().start()
    port = server.port
    client = make_client(server, **FAST)
    keep_open(client)
    async with run_client(client) as task:
        await wait_for(lambda: server.logins == 1)
        await server.stop()
        await asyncio.sleep(0.2)  # several refused attempts
        assert not task.done()
        server = await FakeAmi(port=port).start()
        try:
            await wait_for(lambda: server.logins == 1)
            assert client._connected is True
        finally:
            await client.connection_close()
            await server.stop()


@pytest.mark.asyncio
async def test_reconnect_pause_grows_up_to_the_cap():
    server = await FakeAmi().start()
    port = server.port
    await server.stop()
    client = make_client(server, reconnect_timeout=0.01, reconnect_timeout_increase=0.01,
                         reconnect_timeout_max=0.03)
    async with run_client(client):
        await wait_for(lambda: client.reconnect_timeout == 0.03)
        await asyncio.sleep(0.2)
        assert client.reconnect_timeout == 0.03
        server = await FakeAmi(port=port).start()
        try:
            await wait_for(lambda: server.logins == 1)
            assert client.reconnect_timeout == 0.01  # starts over after a successful connection
        finally:
            await client.connection_close()
            await server.stop()


@pytest.mark.asyncio
async def test_reconnect_timeout_zero_means_no_reconnect(fake_ami):
    client = make_client(fake_ami, reconnect_timeout=0)
    keep_open(client)
    async with run_client(client) as task:
        await wait_for(lambda: fake_ami.logins == 1)
        fake_ami.drop()
        await asyncio.wait_for(task, 2)
        await asyncio.sleep(0.05)
        assert fake_ami.connections == 1
        assert client._connected is False


@pytest.mark.asyncio
async def test_actions_waiting_for_an_answer_are_dropped_on_loss(fake_ami):
    fake_ami.reply("Silent", None)
    client = make_client(fake_ami, **FAST)
    keep_open(client)
    client.create_action({"Action": "Silent"}, lambda answer: None)
    async with run_client(client):
        await wait_for(lambda: fake_ami.actions("Silent"))
        assert len(client._actions_ids) == 1
        fake_ami.drop()
        await wait_for(lambda: fake_ami.logins == 2)
        assert client._actions_ids == {}


@pytest.mark.asyncio
async def test_close_during_the_reconnect_pause_stops_the_loop(fake_ami):
    client = make_client(fake_ami, reconnect_timeout=0.3)
    keep_open(client)
    async with run_client(client) as task:
        await wait_for(lambda: fake_ami.logins == 1)
        fake_ami.drop()
        await asyncio.sleep(0.05)
        await client.connection_close()
        await asyncio.wait_for(task, 1)
        assert fake_ami.connections == 1
