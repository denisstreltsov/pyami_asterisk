# Changelog

## Unreleased

### Fixed

- Reconnect is one loop inside `connect_ami()`: no recursion, so a long-running client no longer ends
  with `RecursionError` after many drops.
- Ping and `create_action(..., repeat=N)` run in exactly one copy after a reconnect (1.5.2 started one more
  copy on every reconnect).
- The previous socket is closed when the connection ends, including after `Event: Shutdown`.
- Actions still waiting for an answer when the connection ends are dropped with a log line.
- Fractional `reconnect_timeout`, `reconnect_timeout_increase` and `ping_delay` work (1.5.2 truncated them
  with `int()`, so `reconnect_timeout=0.5` silently disabled reconnecting).
- After a connection that dropped sooner than `reconnect_timeout` the client pauses before reconnecting,
  so a PBX that drops right after login does not get a tight loop.

### Added

- `reconnect_timeout_max`: upper bound of the pause grown by `reconnect_timeout_increase`.

### Changed

- `reconnect_timeout=0` means no reconnect at all; 1.5.2 made one immediate attempt before giving up.

### Development

- Fake AMI server for tests, `pytest>=8`, GitHub Actions on Python 3.8-3.13; Travis CI removed.
