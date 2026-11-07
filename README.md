# pyami_asterisk (compatible fork)

![tests](https://github.com/HSMM/pyami_asterisk/actions/workflows/tests.yml/badge.svg)

An asyncio client for the Asterisk Manager Interface (AMI). This is a compatible fork of
[denisstreltsov/pyami_asterisk](https://github.com/streltsovdenis/pyami_asterisk) by Denis Streltsov (MIT),
last released upstream as 1.5.2. Russian version: [README.ru.md](README.ru.md).

The 1.5.2 public API and the private `_send_action(action, callback)` keep working; new behaviour is additive or
opt-in (see [ADR 1](docs/adr/0001-compatible-fork.md)).

## What the fork fixes

Planned, tracked as issues:

- Parsing and writing of AMI packets
- Login: timeout, crash on a dropped login, and telling a refused login from a lost connection
- Reconnect: one loop, no recursion, bounded pauses, no leaked sockets
- Actions with an awaited answer, and no lost callbacks
- Lifecycle inside a running event loop, injectable time, ordered events
- Release 1.6.0

Done so far: modern packaging, CI and a fake AMI server for tests.

## Install

The tag `v1.6.0` does not exist yet; until it is released, install from the repository:

```bash
pip install "pyami-asterisk @ git+https://github.com/HSMM/pyami_asterisk@v1.6.0"
```

## Development

```bash
uv venv --python 3.12 .venv
uv pip install -e . --group dev
.venv/bin/python -m pytest -q
```

## Usage

Asterisk AMI Listen all Events

```python
import asyncio
from pyami_asterisk import AMIClient


def all_events(events):
    print(events)


async def hangup_call(events):
    """asynchronous callbacks"""
    await asyncio.sleep(3)
    print(events)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.register_event(["*"], all_events)
ami.register_event(["Hangup"], hangup_call)
ami.connect()
```

Asterisk AMI Listen Events: Registry, ContactStatus, PeerStatus

```python
from pyami_asterisk import AMIClient


def register_multiple_events(events):
    print(events)


async def callback_peer_status(events):
    """
        Response event:
        {
            'Event': 'PeerStatus', 
            'Privilege': 'system,all',
            'ChannelType': 'PJSIP', 
            'Peer': 'PJSIP/888', 
            'PeerStatus': 'Unreachable',
        }
    """
    if events.get('PeerStatus') == 'Unreachable':
        await asyncio.sleep(2)
        print(events)

    async def ping(events):
        """asynchronous callbacks"""
        await asyncio.sleep(3)
        print(events)

    ami.create_action({"Action": "Ping"}, ping)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.register_event(patterns=["Registry", "ContactStatus"], callbacks=register_multiple_events)
ami.register_event(["PeerStatus"], callback_peer_status)
ami.connect()
```

Asterisk AMI Actions: CoreSettings

```python
import asyncio
from pyami_asterisk import AMIClient


def core_settings(events):
    print(events)


async def core_status(events):
    """asynchronous callbacks"""
    await asyncio.sleep(4)
    print(events)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.create_action({"Action": "CoreSettings"}, core_settings)
ami.create_action({"Action": "CoreStatus"}, core_status)
ami.connect()
```

Asterisk AMI Actions: CoreSettings, CoreStatus (repeat 3 seconds)

```python
from pyami_asterisk import AMIClient


def core_settings(events):
    print(events)


def core_status(events):
    print(events)
    print(events['CoreCurrentCalls'])


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.create_action({"Action": "CoreSettings"}, core_settings)
ami.create_action({"Action": "CoreStatus"}, core_status, repeat=3)
ami.connect()
```

Asterisk AMI Action Originate

```python
from pyami_asterisk import AMIClient


def callback_originate(events):
    print(events)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.create_action(
    {
        "Action": "Originate",
        "Channel": "pjsip/203",
        "Timeout": "20000",
        "CallerID": "+37529XXXXXXX <203>",
        "Exten": "+37529XXXXXXX",
        "Context": "from-internal",
        "Async": "true",
        "Variable": r"PJSIP_HEADER(add,Call-Info)=\;Answer-After=0",  # or multiple Variable ['var=1', 'var=2']
        "Priority": "1",
    },
    callback_originate,
)
ami.connect()
```

Asterisk AMI Listen Events + Action

```python
from pyami_asterisk import AMIClient


def callback_peer_status(events):
    
    def callback_ping(response_ping):
        print("Response Ping", response_ping)

    print("PeerStatus", events)
    ami.create_action({"Action": "Ping"}, callback_ping)


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.register_event(["PeerStatus"], callback_peer_status)
ami.connect()
```

Create asyncio task

``` python
import asyncio
import random
from pyami_asterisk import AMIClient


async def refresh_tokens(timeout=4):
    """Example: Refresh tokens"""
    while True:
        print(random.randrange(0, 1000))
        await asyncio.sleep(timeout)
    


ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.create_asyncio_task(tasks=[refresh_tokens(timeout=2)])
ami.connect()
```

Run / stop async

``` python
import asyncio
from pyami_asterisk import AMIClient


async def all_events(event):
    print(event)
    if event.get('Event') == 'SuccessfulAuth':
        # connection close
        await ami.connection_close()


async def run_async():
    await asyncio.sleep(2)
    await ami.connect_ami()

ami = AMIClient(host='127.0.0.1', port=5038, username='username', secret='password')
ami.register_event(["*"], all_events)
asyncio.run(run_async())
```

## Credits

Based on [denisstreltsov/pyami_asterisk](https://github.com/streltsovdenis/pyami_asterisk) by Denis Streltsov (MIT).
