"""A small fake Asterisk Manager Interface server for tests.

It listens on 127.0.0.1 and a free port, speaks the AMI wire format over a real TCP socket and can be
scripted: banner, answer to Login, replies to actions, events, hang-ups. Everything the client sends is
recorded as parsed packets.
"""

import asyncio
import contextlib
import time
from collections.abc import Callable

EOL = "\r\n"
DEFAULT_BANNER = "Asterisk Call Manager/7.0.3"


def packet(fields: dict) -> bytes:
    return (EOL.join(f"{key}: {value}" for key, value in fields.items()) + EOL * 2).encode()


def parse_packets(data: bytes) -> list[dict]:
    """Split a byte stream into packets (blank-line separated) and each packet into a field dict."""
    result = []
    for block in data.decode().split(EOL * 2):
        fields = dict(line.split(": ", 1) for line in block.split(EOL) if ": " in line)
        if fields:
            result.append(fields)
    return result


class FakeAmi:
    """Scripting knobs, all plain attributes:

    banner    first line sent on connect
    login     "accept" (default, when credentials match), "reject" (always answer Error) or "silent"
              (read the Login, never answer)
    hangups   queue consumed one entry per new connection: "at once" (close before the banner),
              "on login" (close on receiving Login, no answer), "after login" (answer, then close)
    replies   action name -> reply fields, a list of packets, or None for no reply (see ``reply``)
    received  every packet the client sent, parsed, in order
    connections  number of accepted TCP connections
    clients   writers of connections that have logged in
    """

    def __init__(self, username: str = "user", secret: str = "pass", banner: str = DEFAULT_BANNER,
                 login: str = "accept") -> None:
        self.username = username
        self.secret = secret
        self.banner = banner
        self.login = login
        self.host = "127.0.0.1"
        self.port = 0
        self.hangups: list[str] = []
        self.replies: dict[str, dict | list[dict] | None] = {"Ping": {"Ping": "Pong"}}
        self.received: list[dict] = []
        self.connections = 0
        self.clients: list[asyncio.StreamWriter] = []
        self._writers: set[asyncio.StreamWriter] = set()
        self._server: asyncio.Server | None = None

    async def start(self) -> "FakeAmi":
        self._server = await asyncio.start_server(self._serve, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        self.drop()
        for writer in list(self._writers):
            writer.close()
        self._server.close()
        await self._server.wait_closed()

    def reply(self, action: str, fields: dict | list[dict] | None) -> None:
        """Script the answer to an action by name. ``fields`` are added to ``Response: Success`` and the
        ActionID of the request; a list is sent as several packets (``Response: Success`` is added to
        every packet that is not an Event); ``None`` means no answer at all."""
        self.replies[action] = fields

    async def send(self, event: dict) -> None:
        """Send an event to every logged-in connection."""
        for writer in list(self.clients):
            writer.write(packet(event))
            await writer.drain()

    def drop(self) -> None:
        """Close every logged-in connection; the server keeps accepting new ones."""
        for writer in self.clients:
            writer.close()
        self.clients.clear()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._writers.add(writer)
        hangup = self.hangups.pop(0) if self.hangups else ""
        try:
            if hangup == "at once":
                return
            writer.write((self.banner + EOL).encode())
            await writer.drain()
            while True:
                data = await reader.readuntil((EOL * 2).encode())
                for action in parse_packets(data):
                    self.received.append(action)
                    if not await self._handle(action, writer, hangup):
                        return
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            if writer in self.clients:
                self.clients.remove(writer)
            self._writers.discard(writer)
            writer.close()

    async def _handle(self, action: dict, writer: asyncio.StreamWriter, hangup: str) -> bool:
        """Answer one packet; False means the connection must be closed."""
        head = {"Response": "Success", "ActionID": action.get("ActionID", "")}
        if action.get("Action") == "Login":
            if hangup == "on login":
                return False
            if self.login == "silent":
                return True
            if self.login == "reject" or (action.get("Username"), action.get("Secret")) != (self.username, self.secret):
                writer.write(packet({**head, "Response": "Error", "Message": "Authentication failed"}))
                await writer.drain()
                return False
            writer.write(packet({**head, "Message": "Authentication accepted"}))
            await writer.drain()
            if hangup == "after login":
                return False
            self.clients.append(writer)
            return True
        scripted = self.replies.get(action.get("Action"), {"Message": "Action processed"})
        if scripted is not None:
            for fields in ([scripted] if isinstance(scripted, dict) else scripted):
                base = {} if "Event" in fields else {"Response": "Success"}
                writer.write(packet({**base, "ActionID": head["ActionID"], **fields}))
            await writer.drain()
        return True


@contextlib.asynccontextmanager
async def run_client(client):
    """Run ``client.connect_ami()`` as a background task; stop it and close its socket on exit."""
    task = asyncio.create_task(client.connect_ami())
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        if client._writer is not None:
            client._writer.close()


async def wait_for(condition: Callable[[], object], timeout: float = 5.0):
    """Wait until ``condition()`` is truthy and return its value; TimeoutError otherwise."""
    deadline = time.monotonic() + timeout
    while not (value := condition()):
        if time.monotonic() > deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(0.005)
    return value
