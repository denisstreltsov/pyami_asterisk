"""Writing actions: non-string values, CR/LF injection."""

import pytest

from fake_ami import make_client, run_client, wait_for
from pyami_asterisk import AMIClient
from pyami_asterisk.utils import _convert_dict_to_bytes


def test_strings_and_lists_as_in_1_5_2():
    assert _convert_dict_to_bytes({"Action": "Originate", "Variable": ["a=1", "b=2"]}) == \
        b"Action: Originate\r\nVariable: a=1\r\nVariable: b=2\r\n\r\n"


def test_numbers_and_bools_are_written_as_text():
    assert _convert_dict_to_bytes({"Timeout": 30000, "Priority": 1, "Async": True, "Early": False}) == \
        b"Timeout: 30000\r\nPriority: 1\r\nAsync: true\r\nEarly: false\r\n\r\n"


def test_none_leaves_the_key_out():
    assert _convert_dict_to_bytes({"Action": "Ping", "CallerID": None}) == b"Action: Ping\r\n\r\n"


@pytest.mark.parametrize("action", [
    {"Action": "Originate", "CallerID": "x\r\nAction: Command\r\nCommand: core stop now"},
    {"Action": "Originate", "CallerID": "x\nAction: Command"},
    {"Action": "Originate", "Variable": ["ok=1", "bad=\r"]},
    {"Action\r\nX": "Ping"},
])
def test_cr_or_lf_is_refused(action):
    with pytest.raises(ValueError):
        _convert_dict_to_bytes(action)
    with pytest.raises(ValueError):
        AMIClient().create_action(action, print)


@pytest.mark.asyncio
async def test_injection_through_send_action_writes_nothing(fake_ami):
    client = make_client(fake_ami)
    client.register_event(["*"], lambda event: None)
    async with run_client(client):
        await wait_for(lambda: fake_ami.logins == 1)
        with pytest.raises(ValueError):
            await client._send_action({"Action": "Originate", "CallerID": "x\r\nAction: Command"})
        assert client._actions_ids == {}
        await client._send_action({"Action": "Ping"})
        await wait_for(lambda: fake_ami.actions("Ping"))
    assert [p["Action"] for p in fake_ami.received] == ["Login", "Ping"]


@pytest.mark.asyncio
async def test_int_values_reach_the_pbx(fake_ami):
    answers = []
    client = make_client(fake_ami)
    client.create_action({"Action": "Originate", "Channel": "PJSIP/100", "Timeout": 30000, "Priority": 1},
                         answers.append)
    async with run_client(client):
        await wait_for(lambda: answers)
    sent = fake_ami.actions("Originate")[0]
    assert (sent["Timeout"], sent["Priority"]) == ("30000", "1")
