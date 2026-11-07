import pytest_asyncio

from fake_ami import FakeAmi


@pytest_asyncio.fixture
async def fake_ami():
    server = await FakeAmi().start()
    try:
        yield server
    finally:
        await server.stop()
