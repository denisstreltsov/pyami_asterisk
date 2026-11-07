"""The fake AMI server, checked with the real client and with a raw socket."""

import asyncio

import pytest

from fake_ami import FakeAmi, packet, parse_packets, run_client, wait_for
from pyami_asterisk import AMIClient


def make_client(server, **config):
    settings = dict(host=server.host, port=server.port, username="user", secret="pass", ping_delay=0)
    return AMIClient(**dict(settings, **config))


async def raw_connect(server):
    return await asyncio.open_connection(server.host, server.port)


async def read_packet(reader):
    return parse_packets(await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2))[0]


@pytest.mark.asyncio
async def test_real_client_logs_in_gets_event_and_action_answer(fake_ami):
    events, answers = [], []
    client = make_client(fake_ami)
    client.register_event(["PeerStatus"], events.append)
    client.create_action({"Action": "CoreStatus"}, answers.append)
    fake_ami.reply("CoreStatus", {"CoreCurrentCalls": "3"})

    async with run_client(client):
        await wait_for(lambda: answers)
        await fake_ami.send({"Event": "PeerStatus", "Peer": "PJSIP/100"})
        await wait_for(lambda: events)

    assert client._authenticated is True
    assert answers[0]["CoreCurrentCalls"] == "3"
    assert events[0]["Peer"] == "PJSIP/100"
    login = fake_ami.received[0]
    assert (login["Action"], login["Username"], login["Secret"]) == ("Login", "user", "pass")
    assert fake_ami.connections == 1


@pytest.mark.asyncio
async def test_banner_is_configurable_and_defaults_to_ami_7(fake_ami):
    reader, writer = await raw_connect(fake_ami)
    assert await reader.readline() == b"Asterisk Call Manager/7.0.3\r\n"
    writer.close()
    other = await FakeAmi(banner="Asterisk Call Manager/5.0.1").start()
    try:
        reader, writer = await raw_connect(other)
        assert await reader.readline() == b"Asterisk Call Manager/5.0.1\r\n"
        writer.close()
    finally:
        await other.stop()


@pytest.mark.asyncio
async def test_wrong_credentials_get_an_error_answer(fake_ami):
    reader, writer = await raw_connect(fake_ami)
    await reader.readline()
    writer.write(packet({"Action": "Login", "Username": "x", "Secret": "y", "ActionID": "a1"}))
    answer = await read_packet(reader)
    assert (answer["Response"], answer["ActionID"]) == ("Error", "a1")
    writer.close()


@pytest.mark.asyncio
async def test_login_can_be_scripted_to_fail_or_stay_silent():
    failing = await FakeAmi(login="reject").start()
    silent = await FakeAmi(login="silent").start()
    try:
        reader, writer = await raw_connect(failing)
        await reader.readline()
        writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass"}))
        assert (await read_packet(reader))["Response"] == "Error"
        writer.close()

        reader, writer = await raw_connect(silent)
        await reader.readline()
        writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass"}))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 0.2)
        assert silent.received[0]["Action"] == "Login"
        writer.close()
    finally:
        await failing.stop()
        await silent.stop()


@pytest.mark.asyncio
async def test_hangup_before_and_after_the_login_answer(fake_ami):
    fake_ami.hangups.extend(["on login", "after login"])
    for expect_answer in (False, True):
        reader, writer = await raw_connect(fake_ami)
        await reader.readline()
        writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass"}))
        rest = await asyncio.wait_for(reader.read(), 2)  # until the server closes
        assert (b"Authentication accepted" in rest) is expect_answer
        writer.close()
    assert fake_ami.connections == 2


@pytest.mark.asyncio
async def test_hangup_at_once_closes_before_the_banner(fake_ami):
    fake_ami.hangups.append("at once")
    reader, writer = await raw_connect(fake_ami)
    assert await asyncio.wait_for(reader.read(), 2) == b""
    writer.close()


@pytest.mark.asyncio
async def test_drop_closes_logged_in_connections_and_new_ones_are_accepted(fake_ami):
    client = make_client(fake_ami, reconnect_timeout=0)
    async with run_client(client):
        await wait_for(lambda: client._authenticated)
        fake_ami.drop()
        await wait_for(lambda: not fake_ami.clients)
    reader, writer = await raw_connect(fake_ami)
    assert await reader.readline() == b"Asterisk Call Manager/7.0.3\r\n"
    writer.close()


@pytest.mark.asyncio
async def test_no_reply_leaves_the_action_unanswered_but_recorded(fake_ami):
    fake_ami.reply("Hold", None)
    reader, writer = await raw_connect(fake_ami)
    await reader.readline()
    writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass"}))
    await read_packet(reader)
    writer.write(packet({"Action": "Hold", "ActionID": "h1"}))
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 0.2)
    assert fake_ami.received[-1] == {"Action": "Hold", "ActionID": "h1"}
    writer.close()


@pytest.mark.asyncio
async def test_a_scripted_reply_may_be_a_series_of_packets_with_the_same_action_id(fake_ami):
    fake_ami.reply("Status", [{"Response": "Success", "EventList": "start"}, {"Event": "StatusComplete"}])
    reader, writer = await raw_connect(fake_ami)
    await reader.readline()
    writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass"}))
    await read_packet(reader)
    writer.write(packet({"Action": "Status", "ActionID": "s1"}))
    first, second = await read_packet(reader), await read_packet(reader)
    assert (first["ActionID"], first["EventList"]) == ("s1", "start")
    assert (second["ActionID"], second["Event"]) == ("s1", "StatusComplete")
    writer.close()


@pytest.mark.asyncio
async def test_wait_for_times_out():
    with pytest.raises(TimeoutError):
        await wait_for(lambda: False, timeout=0.05)
