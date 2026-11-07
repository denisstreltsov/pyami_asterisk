"""The fake AMI server, checked with a raw socket and with the 1.5.2 client."""

import asyncio

import pytest

from fake_ami import FakeAmi, make_client, packet, parse_packets, run_client, wait_for


async def raw_connect(server):
    reader, writer = await asyncio.open_connection(server.host, server.port)
    assert (await reader.readline()).startswith(b"Asterisk Call Manager/")
    return reader, writer


async def read_packet(reader):
    return parse_packets(await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2))[0]


def test_packet_and_parse_round_trip():
    data = packet({"Event": "VarSet", "Variable": ["a=1", "b=2"], "Value": "x: y"})
    assert data == b"Event: VarSet\r\nVariable: a=1\r\nVariable: b=2\r\nValue: x: y\r\n\r\n"
    assert parse_packets(data) == [{"Event": "VarSet", "Variable": ["a=1", "b=2"], "Value": "x: y"}]


@pytest.mark.asyncio
async def test_banner_is_configurable():
    server = await FakeAmi(banner="Asterisk Call Manager/5.0.1").start()
    try:
        reader, writer = await asyncio.open_connection(server.host, server.port)
        assert await reader.readline() == b"Asterisk Call Manager/5.0.1\r\n"
        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_login_accept_and_reject(fake_ami):
    reader, writer = await raw_connect(fake_ami)
    writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass", "ActionID": "1"}))
    assert await read_packet(reader) == {"Response": "Success", "ActionID": "1",
                                         "Message": "Authentication accepted"}
    writer.close()

    reader, writer = await raw_connect(fake_ami)
    writer.write(packet({"Action": "Login", "Username": "user", "Secret": "wrong", "ActionID": "2"}))
    answer = await read_packet(reader)
    assert (answer["Response"], answer["ActionID"]) == ("Error", "2")
    assert await reader.read() == b""  # closed after a refused login
    assert fake_ami.logins == 1


@pytest.mark.asyncio
async def test_silent_login_never_answers():
    server = await FakeAmi(login="silent").start()
    try:
        reader, writer = await raw_connect(server)
        writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass"}))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 0.2)
        writer.close()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_hangups_at_scripted_moments(fake_ami):
    fake_ami.hangups = ["at once", "on login", "after login"]
    reader, writer = await asyncio.open_connection(fake_ami.host, fake_ami.port)
    assert await reader.read() == b""
    writer.close()

    reader, writer = await raw_connect(fake_ami)
    writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass"}))
    assert await reader.read() == b""
    writer.close()

    reader, writer = await raw_connect(fake_ami)
    writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass"}))
    assert (await read_packet(reader))["Response"] == "Success"
    assert await reader.read() == b""
    writer.close()
    assert fake_ami.connections == 3


@pytest.mark.asyncio
async def test_scripted_replies_event_lists_and_no_reply(fake_ami):
    fake_ami.reply("CoreShowChannels", [{"EventList": "start"}, {"Event": "CoreShowChannel", "Channel": "PJSIP/1"},
                                        {"Event": "CoreShowChannelsComplete", "EventList": "Complete"}])
    fake_ami.reply("Silent", None)
    reader, writer = await raw_connect(fake_ami)
    writer.write(packet({"Action": "Login", "Username": "user", "Secret": "pass"}))
    await read_packet(reader)
    writer.write(packet({"Action": "Silent", "ActionID": "s"}))
    writer.write(packet({"Action": "CoreShowChannels", "ActionID": "c"}))
    got = [await read_packet(reader) for _ in range(3)]
    assert [p.get("Event") for p in got] == [None, "CoreShowChannel", "CoreShowChannelsComplete"]
    assert {p["ActionID"] for p in got} == {"c"}
    assert got[0]["Response"] == "Success"
    writer.close()
    assert [p["ActionID"] for p in fake_ami.actions("Silent")] == ["s"]


@pytest.mark.asyncio
async def test_1_5_2_client_logs_in_gets_event_and_action_answer(fake_ami):
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
    assert client.ami_version == "Asterisk Call Manager/7.0.3"
    assert answers[0]["CoreCurrentCalls"] == "3"
    assert events[0]["Peer"] == "PJSIP/100"
    login = fake_ami.received[0]
    assert (login["Action"], login["Username"], login["Secret"]) == ("Login", "user", "pass")
