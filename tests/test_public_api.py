"""Pins the public API of 1.5.2: names and signatures existing users depend on."""

import inspect

import pytest

from pyami_asterisk import AMIClient


def params(func):
    return [(p.name, p.kind.name, p.default) for p in inspect.signature(func).parameters.values()]


def test_constructor_takes_free_form_config_and_has_these_defaults():
    assert params(AMIClient.__init__) == [("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
                                          ("config", "VAR_KEYWORD", inspect.Parameter.empty)]
    assert AMIClient.defaults == dict(host="127.0.0.1", port=5038, ping_delay=5, reconnect_timeout=5,
                                      reconnect_timeout_increase=0, ami_version=False)


def test_register_event_signature():
    assert [p[0] for p in params(AMIClient.register_event)] == ["self", "patterns", "callbacks"]


def test_create_action_signature():
    assert params(AMIClient.create_action)[1:] == [
        ("action", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ("callback", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ("repeat", "POSITIONAL_OR_KEYWORD", False)]


def test_create_asyncio_task_signature():
    assert [p[0] for p in params(AMIClient.create_asyncio_task)] == ["self", "tasks"]


def test_connect_is_sync_and_connect_ami_connection_close_are_coroutines():
    assert params(AMIClient.connect) == [("self", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty)]
    assert not inspect.iscoroutinefunction(AMIClient.connect)
    for name in ("connect_ami", "connection_close"):
        assert inspect.iscoroutinefunction(getattr(AMIClient, name)), name
        assert [p[0] for p in params(getattr(AMIClient, name))] == ["self"]


def test_private_send_action_stays_available():
    assert params(AMIClient._send_action)[1:] == [
        ("action", "POSITIONAL_OR_KEYWORD", inspect.Parameter.empty),
        ("callback", "POSITIONAL_OR_KEYWORD", None)]
    assert inspect.iscoroutinefunction(AMIClient._send_action)


def test_register_event_and_create_action_queue_work_before_connecting():
    client = AMIClient()
    client.register_event(["A", "B"], print)
    client.create_action({"Action": "Ping"}, print, repeat=3)
    client.create_asyncio_task([])
    assert client._patterns == [{"A": print}, {"B": print}]
    assert client._actions == [{"action": {"Action": "Ping"}, "callback": print, "repeat": 3}]


def test_package_exports_amiclient():
    import pyami_asterisk
    assert pyami_asterisk.AMIClient is AMIClient
