import sys
from pathlib import Path

import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_ami import FakeAmi  # noqa: E402


@pytest_asyncio.fixture
async def fake_ami():
    server = await FakeAmi().start()
    try:
        yield server
    finally:
        await server.stop()
