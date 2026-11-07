"""Reading packets: repeated keys, lines without ': ', routing by parsed fields, long packets."""

import asyncio

import pytest

from fake_ami import make_client, run_client, wait_for
from pyami_asterisk.utils import _convert_bytes_to_dict


def test_repeated_key_keeps_every_value_in_order():
    data = b"Event: VarSet\r\nVariable: a=1\r\nVariable: b=2\r\nVariable: c=3\r\n\r\n"
    assert _convert_bytes_to_dict(data)["Variable"] == ["a=1", "b=2", "c=3"]


def test_two_repeated_keys_do_not_share_a_list():
    data = b"Variable: a=1\r\nOutput: x\r\nVariable: b=2\r\nOutput: y\r\n\r\n"
    parsed = _convert_bytes_to_dict(data)
    assert parsed["Variable"] == ["a=1", "b=2"]
    assert parsed["Output"] == ["x", "y"]


def test_value_containing_separator_is_kept_whole():
    assert _convert_bytes_to_dict(b"Data: a: b: c\r\n\r\n") == {"Data": "a: b: c"}


def test_lines_without_separator_do_not_crash():
    data = b"Response: Follows\r\nPrivilege: Command\r\nraw line one\r\nraw line two\r\nEmpty:\r\n\r\n"
    parsed = _convert_bytes_to_dict(data)
    assert parsed["Response"] == "Follows"
    assert parsed["Output"] == ["raw line one", "raw line two"]
    assert parsed["Empty"] == ""


def test_single_values_stay_strings():
    assert _convert_bytes_to_dict(b"Response: Success\r\nPing: Pong\r\n\r\n") == {"Response": "Success",
                                                                                   "Ping": "Pong"}


def keep_open(client):
    client.register_event(["*"], lambda event: None)


@pytest.mark.asyncio
async def test_event_with_repeated_keys_reaches_the_callback_whole(fake_ami):
    events = []
    client = make_client(fake_ami)
    client.register_event(["VarSet"], events.append)
    async with run_client(client):
        await wait_for(lambda: fake_ami.logins == 1)
        await fake_ami.send({"Event": "VarSet", "Variable": ["a=1", "b=2"]})
        await wait_for(lambda: events)
    assert events[0]["Variable"] == ["a=1", "b=2"]


@pytest.mark.asyncio
async def test_word_actionid_inside_a_value_does_not_crash(fake_ami):
    events = []
    client = make_client(fake_ami)
    client.register_event(["UserEvent"], events.append)
    async with run_client(client) as task:
        await wait_for(lambda: fake_ami.logins == 1)
        await fake_ami.send({"Event": "UserEvent", "Body": "see ActionID in docs"})
        await wait_for(lambda: events)
        assert not task.done()
    assert events[0]["Body"] == "see ActionID in docs"


@pytest.mark.asyncio
async def test_shutdown_inside_a_value_is_not_a_shutdown(fake_ami):
    events = []
    client = make_client(fake_ami, reconnect_timeout=0.01)
    client.register_event(["UserEvent"], events.append)
    async with run_client(client):
        await wait_for(lambda: fake_ami.logins == 1)
        await fake_ami.send({"Event": "UserEvent", "Body": "Event: Shutdown"})
        await wait_for(lambda: events)
        await asyncio.sleep(0.1)
        assert fake_ami.connections == 1


@pytest.mark.asyncio
async def test_unknown_actionid_goes_to_event_callbacks(fake_ami):
    events = []
    client = make_client(fake_ami)
    client.register_event(["OriginateResponse"], events.append)
    async with run_client(client):
        await wait_for(lambda: fake_ami.logins == 1)
        await fake_ami.send({"Event": "OriginateResponse", "ActionID": "someone-else", "Response": "Success"})
        await wait_for(lambda: events)


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{}, {"buffer_limit": 1024}])
async def test_packets_longer_than_the_buffer_are_read_whole(fake_ami, config):
    events = []
    client = make_client(fake_ami, **config)
    client.register_event(["Big"], events.append)
    payload = "x" * 200_000
    async with run_client(client) as task:
        await wait_for(lambda: fake_ami.logins == 1)
        await fake_ami.send({"Event": "Big", "Data": payload})
        await fake_ami.send({"Event": "Big", "Data": "small"})
        await wait_for(lambda: len(events) == 2)
        assert not task.done()
    assert events[0]["Data"] == payload
    assert events[1]["Data"] == "small"
