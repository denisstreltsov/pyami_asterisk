import asyncio
import contextlib
import socket
import sys
from pathlib import Path

import pytest

file = Path(__file__).resolve()
parent, root = file.parent, file.parents[1]
sys.path.append(str(root))
from pyami_asterisk import AMIClient
from pyami_asterisk.utils import EOL, _convert_bytes_to_dict


def read_fixture(name):
    """Fixture bytes with CRLF line ends; the files themselves stay untouched."""
    return (parent / "fixtures" / name).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


class GenActions:
    instanses = list()

    def __init__(self):
        self.instanses.append(self)
        self.gen = self.get_gen()
        self.response = ""

    def get_gen(self):
        response = b""
        for resp in read_fixture("actions.txt").splitlines(keepends=True):
            response += resp
            if response.endswith(EOL * 2):
                self.response = response.decode()
                yield self.response
                response = b""

    def __call__(self):
        return next(self.gen)

    def __repr__(self):
        return self.response


class GenActionsResponse:
    instanses = list()

    def __init__(self):
        self.instanses.append(self)
        self.gen = self.get_gen()
        self.response = ""

    def get_gen(self):
        response = b""
        for resp in read_fixture("actions_response.txt").splitlines(keepends=True):
            response += resp
            if response.endswith(EOL * 2):
                self.response = response.decode()
                yield self.response
                response = b""

    def __call__(self):
        return next(self.gen)

    def __repr__(self):
        return self.response


def unused_tcp_port_factory():
    """Find an unused localhost TCP port from 1024-65535 and return it."""
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


open_writers = []


async def handle_echo(reader, writer, stream=None):
    open_writers.append(writer)
    data = await reader.readuntil(separator=EOL * 2)
    message = _convert_bytes_to_dict(data)
    if message['Action'] == 'Login':
        response = "Asterisk Call Manager/5.0.1\r\n".encode()
        if (message["Username"] == "valid_username" and message["Secret"] == "valid_password"):
            response += read_fixture("login_ok.txt")
        else:
            response += read_fixture("login_failed.txt")
        writer.write(response)
        await writer.drain()


async def _server(stream=None, **config):
    HOST = "127.0.0.1"
    PORT = unused_tcp_port_factory()
    USENAME = 'username'
    SECRET = 'password'
    defaults = dict(host=HOST, port=PORT, username=USENAME, secret=SECRET, ping_delay=0)
    config = dict(defaults, **config)
    server = await asyncio.start_server(lambda r, w: handle_echo(r, w, stream), HOST, PORT)
    asyncio.create_task(server.serve_forever())
    ami = AMIClient(**config)
    yield ami
    await ami.connection_close()
    # Python 3.12+: wait_closed() waits for client connections, so close the server side too
    for writer in open_writers:
        writer.close()
    open_writers.clear()
    server.close()
    await server.wait_closed()


@pytest.mark.asyncio
async def test_connection():
    server = _server()
    ami = await server.asend(None)
    await ami.connect_ami()
    assert ami._connected is True
    try:
        await server.asend(None)
    except StopAsyncIteration:
        pass


@pytest.mark.asyncio
async def test_login_ok():
    config = dict(username="valid_username", secret="valid_password")
    server = _server(**config)
    ami = await server.asend(None)
    try:
        await asyncio.wait_for(ami.connect_ami(), timeout=1)
    except asyncio.TimeoutError:
        pass
    try:
        await server.asend(None)
    except StopAsyncIteration:
        pass
    assert ami._authenticated is True


@pytest.mark.asyncio
async def test_login_failed():
    config = dict(username="not_valid_username", secret="not_valid_password")
    server = _server(**config)
    ami = await server.asend(None)
    try:
        await asyncio.wait_for(ami.connect_ami(), timeout=1)
    except asyncio.TimeoutError:
        pass
    try:
        await server.asend(None)
    except StopAsyncIteration:
        pass
    assert ami._authenticated is False
