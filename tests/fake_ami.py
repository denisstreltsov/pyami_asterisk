"""A scriptable fake Asterisk Manager Interface server for tests.

Listens on 127.0.0.1 on a free port and speaks the AMI wire format over a real TCP socket.
Everything the client sends is recorded as parsed packets in ``received``.
"""

import asyncio
import contextlib
import time

EOL = "\r\n"
DEFAULT_BANNER = "Asterisk Call Manager/7.0.3"


def packet(fields):
    """Encode a dict as one AMI packet. A list value is written as one line per item."""
    lines = []
    for key, value in fields.items():
        for item in value if isinstance(value, list) else [value]:
            lines.append(f"{key}: {item}")
    return (EOL.join(lines) + EOL * 2).encode()


def parse_packets(data):
    """Split a byte stream into packets; repeated keys become lists."""
    result = []
    for block in data.decode().split(EOL * 2):
        fields = {}
        for line in block.split(EOL):
            if ": " not in line:
                continue
            key, value = line.split(": ", 1)
            if key in fields:
                fields[key] = (fields[key] if isinstance(fields[key], list) else [fields[key]]) + [value]
            else:
                fields[key] = value
        if fields:
            result.append(fields)
    return result


class FakeAmi:
    """Scripting knobs (plain attributes):

    banner       first line sent on connect
    login        "accept" (when credentials match), "reject" (always Error) or "silent" (never answer)
    hangups      consumed one entry per new connection: "at once" (close before the banner),
                 "on login" (close on receiving Login), "after login" (answer, then close)
    replies      action name -> reply fields, a list of packets, or None for no reply (see ``reply``)
    received     every packet the client sent, parsed, in order
    connections  number of accepted TCP connections
    logins       number of accepted logins
    clients      writers of the connections that are logged in
    """

    def __init__(self, username="user", secret="pass", banner=DEFAULT_BANNER, login="accept"):
        self.username = username
        self.secret = secret
        self.banner = banner
        self.login = login
        self.host = "127.0.0.1"
        self.port = 0
        self.hangups = []
        self.replies = {"Ping": {"Ping": "Pong"}}
        self.received = []
        self.connections = 0
        self.logins = 0
        self.clients = []
        self._writers = set()
        self._server = None

    async def start(self):
        self._server = await asyncio.start_server(self._serve, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def stop(self):
        self.drop()
        for writer in list(self._writers):
            writer.close()
        self._server.close()
        await self._server.wait_closed()

    def reply(self, action, fields):
        """Script the answer to an action by name.

        ``fields`` are added to ``Response: Success`` and the request's ActionID. A list is sent as
        several packets (``Response: Success`` is added to every packet that is not an Event).
        ``None`` means no answer at all.
        """
        self.replies[action] = fields

    async def send(self, fields):
        """Send a packet (usually an event) to every logged-in connection."""
        await self.send_raw(packet(fields))

    async def send_raw(self, data):
        for writer in list(self.clients):
            writer.write(data)
            await writer.drain()

    def drop(self):
        """Close every logged-in connection; the server keeps accepting new ones."""
        for writer in self.clients:
            writer.close()
        self.clients.clear()

    def actions(self, name):
        """Packets the client sent with ``Action: name``."""
        return [p for p in self.received if p.get("Action") == name]

    async def _serve(self, reader, writer):
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

    async def _handle(self, action, writer, hangup):
        """Answer one packet; False means the connection must be closed."""
        head = {"Response": "Success", "ActionID": action.get("ActionID", "")}
        name = action.get("Action")
        if name == "Login":
            if hangup == "on login":
                return False
            if self.login == "silent":
                return True
            if self.login == "reject" or (action.get("Username"), action.get("Secret")) != (self.username,
                                                                                            self.secret):
                writer.write(packet({**head, "Response": "Error", "Message": "Authentication failed"}))
                await writer.drain()
                return False
            writer.write(packet({**head, "Message": "Authentication accepted"}))
            await writer.drain()
            if hangup == "after login":
                return False
            self.logins += 1
            self.clients.append(writer)
            return True
        if name == "Logoff":
            writer.write(packet({**head, "Response": "Goodbye", "Message": "Thanks for all the fish."}))
            await writer.drain()
            return False
        scripted = self.replies.get(name, {"Message": "Action processed"})
        if scripted is not None:
            for fields in [scripted] if isinstance(scripted, dict) else scripted:
                base = {} if "Event" in fields else {"Response": "Success"}
                writer.write(packet({**base, "ActionID": head["ActionID"], **fields}))
            await writer.drain()
        return True


def make_client(server, **config):
    """An AMIClient pointed at ``server``, no Ping and no reconnect unless asked."""
    from pyami_asterisk import AMIClient

    settings = dict(host=server.host, port=server.port, username="user", secret="pass", ping_delay=0,
                    reconnect_timeout=0)
    return AMIClient(**dict(settings, **config))


@contextlib.asynccontextmanager
async def run_client(client):
    """Run ``client.connect_ami()`` in the background; stop it and close its socket on exit."""
    task = asyncio.ensure_future(client.connect_ami())
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        if client._writer is not None:
            client._writer.close()


async def wait_for(condition, timeout=5.0):
    """Wait until ``condition()`` is truthy and return its value; AssertionError on timeout."""
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.005)
