"""IdGenerator no longer keeps every instance alive."""

import pytest

from fake_ami import make_client, run_client, wait_for
from pyami_asterisk.utils import IdGenerator


def test_instances_are_not_kept():
    before = len(IdGenerator.instances)
    generators = [IdGenerator("action") for _ in range(100)]
    assert len(IdGenerator.instances) == before
    assert len({g() for g in generators}) == 100


@pytest.mark.asyncio
async def test_many_actions_do_not_leak_and_get_unique_ids(fake_ami):
    answers = []
    client = make_client(fake_ami)
    client.register_event(["*"], lambda event: None)
    before = len(IdGenerator.instances)
    async with run_client(client):
        await wait_for(lambda: fake_ami.logins == 1)
        for _ in range(1000):
            await client._send_action({"Action": "CoreStatus"}, answers.append)
        await wait_for(lambda: len(answers) == 1000)
    assert len(IdGenerator.instances) == before
    ids = [p["ActionID"] for p in fake_ami.actions("CoreStatus")]
    assert len(set(ids)) == 1000
