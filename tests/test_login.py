"""Login: timeout, a dropped login is a failed attempt, the answer is parsed by fields."""

import asyncio

import pytest

from fake_ami import FakeAmi, make_client, packet, run_client, wait_for

FAST = dict(reconnect_timeout=0.01, login_timeout=0.2)


def keep_open(client):
    client.register_event(["*"], lambda event: None)


@pytest.mark.asyncio
async def test_refused_login_stops_as_in_1_5_2(fake_ami):
    client = make_client(fake_ami, secret="wrong", **FAST)
    await asyncio.wait_for(client.connect_ami(), 2)
    assert client._authenticated is False
    assert fake_ami.connections == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("hangup", ["at once", "on login", "after login"])
async def test_dropped_login_is_retried(fake_ami, hangup):
    fake_ami.hangups = [hangup]
    client = make_client(fake_ami, **FAST)
    keep_open(client)
    async with run_client(client) as task:
        await wait_for(lambda: fake_ami.logins == 1)
        assert not task.done()
        assert fake_ami.connections == 2


@pytest.mark.asyncio
async def test_silent_pbx_times_out_and_is_retried():
    server = await FakeAmi(login="silent").start()
    try:
        client = make_client(server, **FAST)
        keep_open(client)
        async with run_client(client) as task:
            await wait_for(lambda: server.connections == 2, timeout=2)
            server.login = "accept"
            await wait_for(lambda: server.logins == 1, timeout=2)
            assert not task.done()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_dropped_login_without_reconnect_returns_quietly(fake_ami):
    fake_ami.hangups = ["on login"]
    client = make_client(fake_ami, reconnect_timeout=0, login_timeout=0.2)
    await asyncio.wait_for(client.connect_ami(), 2)
    assert fake_ami.connections == 1


async def scripted_pbx(answer):
    """A PBX that sends the banner, waits for Login and answers with the given bytes."""
    async def serve(reader, writer):
        writer.write(b"Asterisk Call Manager/2.10.6\r\n")
        await reader.readuntil(b"\r\n\r\n")
        writer.write(answer)
        await writer.drain()
        await reader.read()
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    packet({"Response": "Success", "Message": "Authentication accepted"}),
    packet({"Message": "Authentication accepted", "ActionID": "x", "Response": "Success"}),
    packet({"Event": "FullyBooted", "Status": "Fully Booted"}) + packet({"Response": "Success"}),
])
async def test_login_answer_is_parsed_by_fields(answer):
    versions = []
    server, port = await scripted_pbx(answer)
    client = make_client(FakeAmi(port=port), ami_version=versions.append, **FAST)
    keep_open(client)
    try:
        async with run_client(client):
            await wait_for(lambda: client._authenticated)
        assert versions == [{"AMI_version": "Asterisk Call Manager/2.10.6"}]
    finally:
        server.close()
        await server.wait_closed()
