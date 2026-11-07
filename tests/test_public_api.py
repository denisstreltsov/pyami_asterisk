"""Pins the 1.5.2 public API that existing users depend on."""

import inspect

from pyami_asterisk import AMIClient

EMPTY = inspect.Parameter.empty


def params(func):
    return [(p.name, p.kind.name, p.default) for p in inspect.signature(func).parameters.values()]


def test_constructor_takes_free_form_config():
    assert params(AMIClient.__init__) == [("self", "POSITIONAL_OR_KEYWORD", EMPTY), ("config", "VAR_KEYWORD", EMPTY)]


def test_defaults_of_1_5_2_are_kept():
    for key, value in dict(host="127.0.0.1", port=5038, ping_delay=5, reconnect_timeout=5,
                           reconnect_timeout_increase=0, ami_version=False).items():
        assert AMIClient.defaults[key] == value, key


def test_method_signatures():
    assert [p[0] for p in params(AMIClient.register_event)] == ["self", "patterns", "callbacks"]
    assert params(AMIClient.create_action)[1:] == [("action", "POSITIONAL_OR_KEYWORD", EMPTY),
                                                   ("callback", "POSITIONAL_OR_KEYWORD", EMPTY),
                                                   ("repeat", "POSITIONAL_OR_KEYWORD", False)]
    assert [p[0] for p in params(AMIClient.create_asyncio_task)] == ["self", "tasks"]
    assert params(AMIClient._send_action)[1:3] == [("action", "POSITIONAL_OR_KEYWORD", EMPTY),
                                                   ("callback", "POSITIONAL_OR_KEYWORD", None)]


def test_sync_and_async_methods():
    assert not inspect.iscoroutinefunction(AMIClient.connect)
    for name in ("connect_ami", "connection_close", "_send_action"):
        assert inspect.iscoroutinefunction(getattr(AMIClient, name)), name


def test_registration_before_connecting():
    client = AMIClient()
    client.register_event(["A", "B"], print)
    client.create_action({"Action": "Ping"}, print, repeat=3)
    client.create_asyncio_task([])
    assert client._patterns == [{"A": print}, {"B": print}]
    assert client._actions == [{"action": {"Action": "Ping"}, "callback": print, "repeat": 3}]
