import asyncio
from loguru import logger as log
from .utils import _convert_dict_to_bytes, EOL, IdGenerator, _convert_bytes_to_dict


class AMIClient:
    defaults = dict(host="127.0.0.1",
                    port=5038,
                    ping_delay=5,
                    reconnect_timeout=5,
                    reconnect_timeout_increase=0,
                    ami_version=False)

    def __init__(self, **config):
        """
        Config data connect to AMI
            Keyword Arguments:
                host (str): Asterisk AMI host
                port (int): Asterisk AMI port
                username (str): Asterisk AMI port
                secret (str): Asterisk AMI port
                ping_delay (int): Ping delay
                reconnect_timeout (int): Reconnect timeout
                reconnect_timeout_increase (int): Reconnect timeout increase
                reconnect_timeout_max (int): Upper bound of the reconnect timeout (default: no bound)
                buffer_limit (int): Read buffer size in bytes (default 64 KiB); longer packets are still read whole
                ami_version (func): callback AMI version
        """
        self.config = dict(self.defaults, **config)
        self.ping_delay = float(self.config["ping_delay"])
        self.reconnect_timeout = float(self.config["reconnect_timeout"])
        self.reconnect_timeout_increase = float(self.config["reconnect_timeout_increase"])
        self.reconnect_timeout_max = self.config.get("reconnect_timeout_max")
        self.log = config.get('log', log)
        self._reader = None
        self._writer = None
        self._connected = False
        self._authenticated = None
        self.ami_version = self.config.get('ami_version')
        self._asyncio_tasks = []
        self._patterns = []
        self._data = asyncio.Queue()
        self._actions = []
        self._actions_ids = {}
        self._actions_queue = asyncio.Queue()
        self._actions_repeat = False
        self._actions_repeat_connections_lost = []
        self._closing = False
        self._connected_at = 0.0
        # Ping and repeated actions: they live as long as one connection and are cancelled when it ends
        self._connection_tasks = set()
        self._id_generator = IdGenerator('action')

    async def _open_connection(self):
        """Open the TCP connection, retrying after ``reconnect_timeout`` until it succeeds or the client is closed."""
        while not self._closing:
            try:
                connection = asyncio.open_connection(self.config["host"], self.config["port"],
                                                     limit=int(self.config.get("buffer_limit", 2 ** 16)))
                self._reader, self._writer = await asyncio.wait_for(connection, timeout=5)
            except (asyncio.TimeoutError, OSError):
                if self.reconnect_timeout == 0:
                    return False
                self.log.warning(f"Connection failed ({self.config['host']}, {self.config['port']}), next connection "
                                 f"attempt in {self.reconnect_timeout} second(s)")
                await asyncio.sleep(self.reconnect_timeout)
                if self.reconnect_timeout_increase > 0:
                    self.reconnect_timeout += self.reconnect_timeout_increase
                    if self.reconnect_timeout_max is not None:
                        self.reconnect_timeout = min(self.reconnect_timeout, float(self.reconnect_timeout_max))
                continue
            self.reconnect_timeout = float(self.config["reconnect_timeout"])
            return True
        return False

    async def connect_ami(self):
        """Connect, log in and process AMI messages; a lost connection is re-established in this same loop."""
        self._closing = False
        while True:
            self._connected = await self._open_connection()
            if not self._connected:
                return
            self._authenticated = await self._login()
            if not self._authenticated:
                return
            self._connected_at = asyncio.get_running_loop().time()
            self._service_ping()
            await self._handler_tasks()
            await self._event_listener()
            if not await self._connection_lost():
                return

    async def _handler_tasks(self, action_in_callback: bool = False):
        if self._actions:
            for action in self._actions:
                if action['repeat'] > 0 and not action_in_callback:
                    self._spawn_connection_task(self._actions_task_repeat(action))
                    self._actions_repeat = True
                    self._actions_repeat_connections_lost.append(action)
                else:
                    await self._send_action(action['action'], callback=action['callback'])
            self._actions.clear()
        if self._asyncio_tasks:
            for task in self._asyncio_tasks:
                asyncio.create_task(task)
            self._asyncio_tasks.clear()

    async def _login(self):
        await self._send_action({
            "Action": "Login",
            "Username": self.config["username"],
            "Secret": self.config["secret"],
        })
        data = await self._reader.readuntil(separator=EOL * 2)
        if data.decode().split(EOL.decode())[1] == "Response: Success" and \
                data.decode().split(EOL.decode())[-3] == "Message: Authentication accepted":
            self.ami_version = data.decode().split(EOL.decode())[0]
            if self.config.get('ami_version'):
                self.config.get('ami_version')(dict(AMI_version=self.ami_version))
            self._actions_ids.clear()
            return True
        self.log.error("Authentication failed")
        return False

    async def _actions_task_repeat(self, action: dict):
        while self._connected:
            action.get('action')['ActionID'] = self._id_generator()
            await self._send_action(action.get('action'), action.get('callback'))
            await asyncio.sleep(action.get('repeat'))

    async def _event_listener(self):
        while self._connected:
            try:
                data = await self._read_packet()
                if data == "".encode():
                    continue
                message = _convert_bytes_to_dict(data)
                if message.get("Event") == "Shutdown":
                    self.log.warning("Asterisk is shutdown or restarted")
                    return
                if message.get("Response") == "Goodbye":
                    await self.connection_close()

                action_id = message.get("ActionID")
                if isinstance(action_id, str):
                    response = message
                    if response['ActionID'] in self._actions_ids:
                        if self._actions_ids.get(response['ActionID']).get('callback') is not None:
                            self._actions_queue.put_nowait((self._actions_ids.get(response['ActionID']), response))
                            asyncio.create_task(self._actions_callbacks())
                            if response.get('Message', '').endswith('successfully queued') \
                                    and self._actions_ids.get(response['ActionID'])[
                                        'action'].get('Async', "false") == 'true' \
                                    or response.get('EventList', '') == 'start':
                                self._actions_ids.get(response['ActionID'])['wait_next'] = True
                            elif response.get('Response') in ('Success', 'Error', 'Fail', 'Failure'):
                                self._actions_ids.get(response['ActionID'])['wait_next'] = False
                            elif response.get('Event', '').endswith('Complete'):
                                self._actions_ids.get(response['ActionID'])['wait_next'] = False
                        if not self._actions_ids.get(response['ActionID'])['wait_next']:
                            self._actions_ids.pop(response['ActionID'])
                        continue

                if self._patterns:
                    self._data.put_nowait(message)
                    asyncio.create_task(self._events_callbacks())

            except (asyncio.IncompleteReadError, TimeoutError, RuntimeError, OSError):
                if self._connected:
                    self.log.warning("AMI connection lost")
                return

    async def _read_packet(self) -> bytes:
        """Read one packet (up to an empty line), also when it is longer than the read buffer."""
        chunks = []
        while True:
            try:
                chunks.append(await self._reader.readuntil(separator=EOL * 2))
                return b"".join(chunks)
            except asyncio.LimitOverrunError as e:
                chunks.append(await self._reader.readexactly(e.consumed))

    async def _check_empty(self):
        if not self._patterns and not self._actions_ids and not self._actions_repeat:
            self._connected = False
            await self.connection_close()

    async def _actions_callbacks(self):
        action, response = await self._actions_queue.get()
        if asyncio.iscoroutinefunction(action.get('callback')):
            await action.get('callback')(response)
        else:
            action.get('callback')(response)
        self._actions_queue.task_done()
        await self._handler_tasks(action_in_callback=True)
        await self._check_empty()

    async def _events_callbacks(self):
        data = await self._data.get()
        for pattern in self._patterns:
            if "*" == list(pattern.keys())[0]:
                if asyncio.iscoroutinefunction(pattern.get("*")):
                    await pattern.get("*")(data)
                else:
                    pattern.get("*")(data)
            if "*" != list(pattern.keys())[0] and list(pattern.keys())[0] == data.get('Event'):
                if asyncio.iscoroutinefunction(list(pattern.values())[0]):
                    await list(pattern.values())[0](data)
                else:
                    list(pattern.values())[0](data)
        self._data.task_done()
        await self._handler_tasks(action_in_callback=True)

    async def _send_action(self, action: dict, callback: object = None):
        if "ActionID" not in action:
            action['ActionID'] = self._id_generator()
        self._actions_ids[action['ActionID']] = {'action': action, 'callback': callback, 'wait_next': False}
        self._writer.write(_convert_dict_to_bytes(action))
        try:
            await self._writer.drain()
        except (ConnectionError, RuntimeError):
            # closing the socket wakes the event listener, which hands over to the reconnect loop
            self._writer.close()

    async def connection_close(self):
        """Close the connection"""
        self._closing = True
        self._connected = False
        self._cancel_connection_tasks()
        self._writer.close()
        self.log.warning('AMI connection close')
        await self._writer.wait_closed()

    def _service_ping(self):
        if self.ping_delay > 0:
            self._spawn_connection_task(
                self._actions_task_repeat({'action': {"Action": "Ping"}, 'repeat': self.ping_delay}))

    def _spawn_connection_task(self, coro):
        task = asyncio.ensure_future(coro)
        self._connection_tasks.add(task)
        task.add_done_callback(self._connection_tasks.discard)
        return task

    def _cancel_connection_tasks(self):
        for task in list(self._connection_tasks):
            task.cancel()
        self._connection_tasks.clear()

    async def _connection_lost(self):
        """Clean up after the connection ended. True means: connect again."""
        self._connected = False
        self._authenticated = False
        self._cancel_connection_tasks()
        if self._actions_ids:
            self.log.warning(f"Connection lost, dropping {len(self._actions_ids)} action(s) waiting for an answer")
            self._actions_ids.clear()
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except (OSError, RuntimeError):
                pass
        if self._closing or self.reconnect_timeout == 0:
            return False
        if self._actions_repeat:
            # resumed by _handler_tasks after the next login, exactly once each
            self._actions = self._actions_repeat_connections_lost + self._actions
            self._actions_repeat_connections_lost = []
            self._actions_repeat = False
        lived = asyncio.get_running_loop().time() - self._connected_at
        if lived < self.reconnect_timeout:
            # dropped soon after login: pause, so a PBX that drops at once does not get a tight loop
            self.log.warning(f"AMI connection lost, next connection attempt in {self.reconnect_timeout} second(s)")
            await asyncio.sleep(self.reconnect_timeout)
        return not self._closing

    def register_event(self, patterns: list, callbacks: object):
        for pattern in patterns:
            self._patterns.append({pattern: callbacks})

    def create_action(self, action: dict, callback: object, repeat: int = False):
        self._actions.append({'action': action, 'callback': callback, 'repeat': repeat})

    def create_asyncio_task(self, tasks: list):
        for task in tasks:
            self._asyncio_tasks.append(task)

    def connect(self):
        asyncio.run(self.connect_ami())
